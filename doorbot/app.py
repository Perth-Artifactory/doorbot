"""
Doorbot_1.3

RFID and NFC based access control system for the Perth Artifactory.
Interfaces with Slack and other services for administration and logging.
"""

import time
import sys
import logging
from logging.handlers import RotatingFileHandler
import json
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.app.async_app import AsyncApp
from slack_sdk.errors import SlackApiError
import asyncio
import pigpio
import re
import os
import requests
import copy

from doorbot.interfaces import slack_blocks
from doorbot.interfaces.doorbot_hat_gpio import DoorbotHatGpio
from doorbot.interfaces.wiegand_key_reader import KeyReader
from doorbot.interfaces.blinkstick_interface import BlinkstickInterface
from doorbot.interfaces.socket_client import SocketClient
from doorbot.interfaces.sound_player import SoundPlayer
from doorbot.interfaces.monotonic_waiter import MonotonicWaiter
from doorbot.interfaces import text_to_speech

# ======= Logging =======

# Global queue for log messages to be sent via Slack
global_slack_log_queue = []

# Holds the config but not used directly
root_logger = None

# General logging not covered by bolt in this file. Logs as "app".
general_logger = None


class SlackLogger(logging.Handler):
    """Custom log handler to queue messages to be sent to a slack channel"""

    def emit(self, record):
        log_msg = self.format(record)
        sanitised_log_msg = re.sub(r"(?<=token=)[^&]*", "REDACTED", log_msg)
        global global_slack_log_queue
        global_slack_log_queue.append(sanitised_log_msg)


def setup_logging(log_path):
    """Setup all the handlers and formatters for logging"""
    global root_logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Writing to file
    file_handler = RotatingFileHandler(log_path, maxBytes=2000000, backupCount=5)
    file_handler.setLevel(logging.DEBUG)

    # Logging to stdout
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(logging.DEBUG)

    # Logging to a slack channel
    custom_handler = SlackLogger()
    custom_handler.setLevel(logging.INFO)

    # Create a formatter
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] {%(name)s} %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Add the formatter to the handlers
    file_handler.setFormatter(formatter)
    stream_handler.setFormatter(formatter)
    custom_handler.setFormatter(formatter)

    # Add the handlers to the root logger
    root_logger.addHandler(file_handler)
    root_logger.addHandler(stream_handler)
    root_logger.addHandler(custom_handler)

    global general_logger
    general_logger = logging.getLogger("app")


# ======= Config =======


class Config:
    """Config loader"""

    def __init__(self) -> None:
        with open("config.json", "r") as f:
            config = json.load(f)

        self.mock_raspberry_pi = config["mock_raspberry_pi"]
        self.SLACK_APP_TOKEN = config["SLACK_APP_TOKEN"]
        self.SLACK_BOT_TOKEN = config["SLACK_BOT_TOKEN"]
        self.channel = config["slack_channel"]
        self.channel_logs = config["slack_channel_logs"]
        self.admin_usergroup_handle = config["admin_usergroup_handle"]
        self.relay_channel = config["relay_channel"]
        self.door_sensor_channel = config["door_sensor_channel"]
        self.edge_auth_socket_path = config["edge_auth"]["socket_path"]
        self.sounds_dir = config["sounds_dir"]
        self.custom_sounds_dir = config["custom_sounds_dir"]
        self.log_path = config["log_path"]
        self.access_granted_webhook = config["access_granted_webhook"]
        self.door_sensor_ha_api_url = config["door_sensor_ha_api_url"]
        self.home_assistant_token = config["home_assistant_token"]

        # Cache the usergroup_id once its been looked up
        self.admin_usergroup_id = None


# Load the config
config = Config()


# ======= Setup =======

# Record start time for uptime report
start_time = time.monotonic()

# Setup all the logging
setup_logging(config.log_path)
general_logger.info(f"########## STARTUP ##########")

# App should only create this once
pigpio_pi = pigpio.pi()

# Load the Doorbot hat GPIO
hat_gpio = DoorbotHatGpio(pigpio_pi)

# Door "closed" sensor's last state to trigger webhook on change
door_sensor_last_state = None

# Create RFID reader class
key_reader = KeyReader(pigpio_pi)

# Blinkstick - more LEDs! Startup Blue until its ready - White once ready
blink = BlinkstickInterface()
blink.set_colour_name("blue")

# Timers
timer_relock = MonotonicWaiter(name="door_relock")
timer_blinkstick_white = MonotonicWaiter(name="blinkstick_white")

# Socket client for edge_auth daemon (handles all API communication)
socket_client = SocketClient(socket_path=config.edge_auth_socket_path)

# Sound player
sound_player = SoundPlayer(
    sound_dir=config.sounds_dir, custom_sound_dir=config.custom_sounds_dir
)

# Load the slack bolt app framework
app = AsyncApp(token=config.SLACK_BOT_TOKEN)


# ======= Door Lock/Unlock Methods =======


def gpio_unlock(time_s: float):
    hat_gpio.set_relay(config.relay_channel, True)
    timer_relock.set_wait_time(duration_s=time_s)
    general_logger.info(f"gpio_unlock - Unlock door for {time_s} s")


def gpio_lock():
    hat_gpio.set_relay(config.relay_channel, False)
    general_logger.info(f"gpio_lock - Locked door")


# ======= Slack Helper Methods =======


def get_user_at_id(b):
    """Returns user id like <@{user_id}> so that slack will render to @username"""
    try:
        return f"<@{b['user']['id']}>"
    except KeyError as e:
        general_logger.error(f"get_user_at_id exception: {e}")
        return "Unknown"


def get_response_text(b):
    """Find the text action payload from dropdown"""
    for block in b["actions"]:
        if "selected_option" in block:
            return block["selected_option"]["text"]["text"]
        else:
            return block["text"]["text"]


def get_response_value(b):
    """Find the value action payload from dropdown"""
    for block in b["actions"]:
        if "selected_option" in block:
            return block["selected_option"]["value"]
        else:
            return block["value"]


async def post_slack_door(message):
    await app.client.chat_postMessage(
        channel=config.channel,
        text=message,
    )


async def post_slack_log(message):
    await app.client.chat_postMessage(
        channel=config.channel_logs,
        text=message,
    )


def patch_home_blocks(
    blocks, block_id, action_id, appended_text=None, replacement_text=None, style=None
):
    """Patch blocks for home view buttons with loading indicators or updates"""
    new_blocks = copy.deepcopy(blocks)

    for block in new_blocks:
        if block.get("block_id") == block_id:
            # Handle different block types
            if "elements" in block:
                for element in block["elements"]:
                    if element.get("action_id") == action_id:
                        if replacement_text:
                            element["text"]["text"] = replacement_text
                        elif appended_text:
                            # Remove any existing loading indicator first
                            current_text = element["text"]["text"]
                            if " :spinthinking:" in current_text:
                                current_text = current_text.replace(
                                    " :spinthinking:", ""
                                )
                            element["text"]["text"] = current_text + appended_text

                        if style:
                            element["style"] = style
            elif (
                "accessory" in block
                and block["accessory"].get("action_id") == action_id
            ):
                # Handle section blocks with accessory buttons
                if replacement_text:
                    block["accessory"]["text"]["text"] = replacement_text
                elif appended_text:
                    current_text = block["accessory"]["text"]["text"]
                    if " :spinthinking:" in current_text:
                        current_text = current_text.replace(" :spinthinking:", "")
                    block["accessory"]["text"]["text"] = current_text + appended_text

                if style:
                    block["accessory"]["style"] = style

    return new_blocks


async def set_loading_icon_on_button(body, client, logger):
    """Set the spinning icon on the button for home view"""
    try:
        # Get the action that was clicked
        action = body["actions"][0]

        # Patch the blocks with loading indicator
        new_blocks = patch_home_blocks(
            blocks=body["view"]["blocks"],
            block_id=action.get("block_id"),
            action_id=action["action_id"],
            appended_text=" :spinthinking:",
        )

        # Update the home view
        await client.views_publish(
            user_id=body["user"]["id"],
            view={
                "type": "home",
                "blocks": new_blocks,
            },
        )
        logger.info("Loading indicator added to button")
    except SlackApiError as e:
        logger.error(f"Failed to update home view: {e.response['error']}")
        if (
            "response_metadata" in e.response
            and "messages" in e.response["response_metadata"]
        ):
            logger.error(e.response["response_metadata"]["messages"])


async def reset_button_after_action(
    body, client, logger, success_text=None, delay_seconds=3
):
    """Reset button to original state after an action completes"""
    try:
        # Get the action that was clicked
        action = body["actions"][0]

        if success_text:
            # First show success message
            new_blocks = patch_home_blocks(
                blocks=body["view"]["blocks"],
                block_id=action.get("block_id"),
                action_id=action["action_id"],
                replacement_text=success_text,
                style="primary",
            )

            await client.views_publish(
                user_id=body["user"]["id"],
                view={
                    "type": "home",
                    "blocks": new_blocks,
                },
            )

            # Wait a bit before resetting
            await asyncio.sleep(delay_seconds)

        # Reset to original home view
        await client.views_publish(
            user_id=body["user"]["id"], view=slack_blocks.home_view
        )
        logger.info("Button reset to original state")
    except SlackApiError as e:
        logger.error(f"Failed to reset button: {e.response['error']}")
    except Exception as e:
        logger.error(f"Unexpected error resetting button: {e}")


# ======== Slack Matchers ==========


async def check_user_authed(user_id):
    """Check whether a user/channel is authorised to control doorbot via slack"""
    try:
        if config.admin_usergroup_id is None:
            # Get list of usergroups
            # Call the usergroups.list method to retrieve information about all usergroups in your workspace
            response = await app.client.usergroups_list(include_users=False)

            # Iterate through the list of usergroups and find the one with the specified name
            for group in response["usergroups"]:
                if group["handle"] == config.admin_usergroup_handle:
                    config.admin_usergroup_id = group["id"]
                    break

            if config.admin_usergroup_id is None:
                raise Exception(
                    f"Could not find usergroup '{config.admin_usergroup_handle}'"
                )

        # Get authorised users
        response = await app.client.usergroups_users_list(
            usergroup=config.admin_usergroup_id
        )
        admin_users = response["users"]
        general_logger.debug(
            f"check_user_authed - Checking '{user_id}' (admin users: {', '.join(admin_users)})"
        )

        return user_id in admin_users

    except Exception as e:
        general_logger.error(f"check_user_authed - Exception: {e}")

    return False


async def authed_event(event):
    try:
        return await check_user_authed(event.get("user"))
    except Exception as e:
        general_logger.error(f"authed_event - Exception: {e}")
    return False


async def authed_action(body):
    try:
        return await check_user_authed(body.get("user").get("id"))
    except Exception as e:
        general_logger.error(f"authed_action - Exception: {e}")
    return False


# ======= Slack Handlers =======


@app.event("app_home_opened", matchers=[authed_event])
async def update_home_tab(client, event, logger):
    try:
        # views.publish is the method that your app uses to push a view to the Home tab
        await client.views_publish(
            # the user that opened your app's app home
            user_id=event["user"],
            # the view object that appears in the app home
            view=slack_blocks.home_view,
        )
    except Exception as e:
        logger.error(f"Error publishing home tab: {e}")


@app.event("app_home_opened")
async def update_home_tab(client, event, logger):
    """Fallback handler for unauthorised"""
    try:
        await client.views_publish(
            # the user that opened your app's app home
            user_id=event["user"],
            view=slack_blocks.home_view_denied,
        )
    except Exception as e:
        logger.error(f"Error publishing home tab denied: {e}")


@app.action("sendMessage", matchers=[authed_action])
async def handle_send_message(ack, body, logger):
    try:
        await ack()
        logger.debug("app.action 'sendMessage':" + str(body))
        text = get_response_text(body)
        text_to_speech.non_blocking_speak(text)
        logger.info(f"SEND MESSAGE = {text}")
        await post_slack_door(
            f"Admin {get_user_at_id(body)} played predefined text-to-speech: {text}"
        )
    except Exception as e:
        logger.error(f"Error in handle_send_message: {e}")


@app.action("ttsMessage", matchers=[authed_action])
async def handle_tts_message(ack, body, logger):
    try:
        await ack()
        logger.debug("app.action 'ttsMessage':" + str(body))
        text = get_response_value(body)
        text_to_speech.non_blocking_speak(text)
        logger.info(f"TTS MESSAGE = {text}")
        await post_slack_door(
            f"Admin {get_user_at_id(body)} played text-to-speech: {text}"
        )
    except Exception as e:
        logger.error(f"Error in handle_tts_message: {e}")


@app.action("unlock", matchers=[authed_action])
async def handle_unlock(ack, body, logger, client):
    try:
        await ack()

        # Set the spinning face going on the button
        await set_loading_icon_on_button(body=body, client=client, logger=logger)

        logger.debug("app.action 'unlock':" + str(body))
        value = get_response_value(body)
        try:
            time_s = float(value)
        except ValueError:
            logger.error("Invalid wait time: " + value)
            # Reset button on error
            await reset_button_after_action(body=body, client=client, logger=logger)
        else:
            # Valid time
            msg = f"Admin {get_user_at_id(body)} manually opened door for {time_s:.0f} seconds"
            gpio_unlock(time_s)
            logger.info(msg)
            await post_slack_door(msg)
            text_to_speech.non_blocking_speak(
                f"Door has been opened for {time_s:.0f} seconds"
            )

            # Reset button with success message
            await reset_button_after_action(
                body=body,
                client=client,
                logger=logger,
                success_text=f"Unlocked for {time_s:.0f}s! ✓",
            )
    except Exception as e:
        logger.error(f"Error in handle_unlock: {e}")
        # Reset button on error
        await reset_button_after_action(body=body, client=client, logger=logger)


@app.action("restartApp", matchers=[authed_action])
async def handle_restart_app(ack, body, logger, client):
    try:
        # Acknowledge the action
        await ack()

        # Set the spinning face going on the button
        await set_loading_icon_on_button(body=body, client=client, logger=logger)

        logger.debug("app.action 'handle_restart_app':" + str(body))

        blink.set_colour_name("fuchsia")  # light purple

        # Logs about restart
        msg = f"Admin {get_user_at_id(body)} has asked the doorbot app to restart"
        logger.warning(msg)
        await post_slack_door(msg)

        # Give log messages a chance to flush out
        await asyncio.sleep(1)

        blink.set_colour_name("navy")  # dark blue
    except Exception as e:
        logger.error(f"Error in handle_restart_app: {e}")

    # Restart the app by exiting and letting systemd restart us
    sys.exit()


@app.action("rebootPi", matchers=[authed_action])
async def handle_reboot_pi(ack, body, logger, client):
    try:
        # Acknowledge the action
        await ack()

        # Set the spinning face going on the button
        await set_loading_icon_on_button(body=body, client=client, logger=logger)

        logger.debug("app.action 'handle_restart_app':" + str(body))

        blink.set_colour_name("purple")

        # Logs about restart
        msg = f"Admin {get_user_at_id(body)} has asked the raspberry pi to reboot"
        logger.warning(msg)
        await post_slack_door(msg)

        # Give log messages a chance to flush out
        await asyncio.sleep(1)

        blink.set_colour_name("navy")  # dark blue

    except Exception as e:
        logger.error(f"Error in handle_reboot_pi: {e}")

    # Reboot the Raspberry Pi
    os.system("sudo reboot")


@app.action("livelinessCheck", matchers=[authed_action])
async def handle_liveliness_check(ack, body, logger, client):
    try:
        # Acknowledge the action
        await ack()

        # Set the spinning face going on the button
        await set_loading_icon_on_button(body=body, client=client, logger=logger)

        logger.debug("app.action 'handle_liveliness_check':" + str(body))

        # Briefly show a dimmer white
        blink.set_colour_name("gray")
        timer_blinkstick_white.set_wait_time(duration_s=1)

        # Calculate uptime
        uptime_seconds = time.monotonic() - start_time
        days, remainder = divmod(uptime_seconds, 3600 * 24)
        hours, _ = divmod(remainder, 3600)

        # Log and post about the liveliness check
        msg = f"Admin {get_user_at_id(body)} has requested liveliness check (uptime {int(days)}d {int(hours)}h)"
        logger.info(msg)
        await post_slack_door(msg)

        # Reset button with success message
        await reset_button_after_action(
            body=body,
            client=client,
            logger=logger,
            success_text=f"Alive! {int(days)}d {int(hours)}h ✓",
        )
    except Exception as e:
        logger.error(f"Error in handle_liveliness_check: {e}")
        # Reset button on error
        await reset_button_after_action(body=body, client=client, logger=logger)


@app.action("updateKeys", matchers=[authed_action])
async def handle_update_keys(ack, body, logger, client):
    try:
        await ack()
        await set_loading_icon_on_button(body=body, client=client, logger=logger)

        logger.debug("app.action 'update_keys':" + str(body))

        ok = await socket_client.refresh()

        msg = f"Admin {get_user_at_id(body)} has requested keys update"
        logger.info(msg)
        await post_slack_door(msg)

        success_text = "Keys updated! ✓" if ok else "Update failed ✗"
        await reset_button_after_action(
            body=body,
            client=client,
            logger=logger,
            success_text=success_text,
        )
    except Exception as e:
        logger.error(f"Error in handle_update_keys: {e}")
        await reset_button_after_action(body=body, client=client, logger=logger)


# ======= Background Tasks =======


async def read_tags():
    """Main worker coroutine to poll the RFID reader and unlock the door"""

    # Set blinkstick to WHITE as idle
    blink.set_white()

    general_logger.info("Ready to read tags")

    loop_counter = 0
    while True:
        try:
            if loop_counter % 36000 == 0:
                # Hourly log of tag reading
                general_logger.debug("Reading tags...")
            loop_counter += 1

            if len(key_reader.pending_keys) > 0:
                tag = key_reader.pending_keys.pop(0)

                # Pad with zeros to 10 digits like API expects
                tag = f"{tag:0>10}"

                result = await socket_client.authorize(tag)
                if result.get("allowed"):
                    # Access granted
                    blink.set_colour_name("green")
                    gpio_unlock(5.0)

                    # Play custom sound if provided, otherwise default
                    sound_path = result.get("sound_path")
                    if sound_path:
                        sound_player.play_sound(sound_path)
                    else:
                        sound_player.play_sound(
                            os.path.join(config.sounds_dir, "granted.mp3")
                        )

                    general_logger.info(f"read_tags - Access granted: tag = '{tag}'")

                else:
                    # Access denied
                    blink.set_colour_name("red")
                    timer_blinkstick_white.set_wait_time(duration_s=5)
                    sound_player.play_denied()
                    general_logger.info(f"read_tags - Access denied: tag = '{tag}'")

            if len(key_reader.pending_errors) > 0:
                # Set blinkstick off-red for 5 seconds
                blink.set_colour_name("maroon")
                timer_blinkstick_white.set_wait_time(duration_s=5)

                # Loggers only. Don't send to main door channel.
                msg = key_reader.pending_errors.pop(0)
                general_logger.info(f"read_tags - Bad read: {msg}")

        except Exception as e:
            general_logger.error(f"read_tags - An unexpected exception occurred: {e}")

            # Set blinkstick off-red while giving exception its sleep to prevent rapid
            # exception spins.
            blink.set_colour_name("maroon")
            await asyncio.sleep(5)
            blink.set_colour_name("white")

        await asyncio.sleep(0.1)


async def relock_door():
    """Worker coroutine to relock the door after provided wait"""
    while True:
        try:
            done = await timer_relock.wait()
            if done:
                # Lock the door
                gpio_lock()

                # Reset blinkstick to white
                blink.set_white()

        except Exception as e:
            general_logger.error(f"relock_door - An unexpected exception occurred: {e}")
            gpio_lock()
            await asyncio.sleep(5)

        await asyncio.sleep(0.1)


async def clear_blinkstick():
    """Worker coroutine to change blinkstick back to white after a delay"""
    while True:
        try:
            done = await timer_blinkstick_white.wait()
            if done:
                # Reset blinkstick to white
                blink.set_white()

        except Exception as e:
            general_logger.error(
                f"clear_blinkstick - An unexpected exception occurred: {e}"
            )
            await asyncio.sleep(5)

        await asyncio.sleep(0.1)


async def slack_logs_worker():
    """Worker coroutine post logs to slack when required"""
    global global_slack_log_queue
    while True:
        try:
            if len(global_slack_log_queue) > 0:
                await post_slack_log(global_slack_log_queue.pop())
        except Exception as e:
            general_logger.error(
                f"slack_logs_worker - An unexpected exception occurred: {e}"
            )
            await asyncio.sleep(5)
        await asyncio.sleep(0.1)


async def input_reader():
    """Worker coroutine to read inputs - for door open switch"""
    global door_sensor_last_state
    while True:
        try:
            status = hat_gpio.read_switches()
            door_state = status[config.door_sensor_channel]
            if door_sensor_last_state is None or door_state != door_sensor_last_state:
                door_sensor_last_state = door_state
                door_status_string = {False: "on", True: "off"}[door_state]
                general_logger.info(f"Door closed sensor: {door_status_string}")

                # Define payload and headers
                payload = {
                    "state": door_status_string,
                    "attributes": {"device_class": "door"},
                }
                headers = {
                    "Authorization": f"Bearer {config.home_assistant_token}",
                    "Content-Type": "application/json",
                }

                # Sending the POST request - will update/create home assistant entity
                response = requests.post(
                    config.door_sensor_ha_api_url,
                    json=payload,
                    headers=headers,
                    timeout=0.1,
                )

                # Check the response
                if response.status_code in (200, 201):
                    general_logger.debug(f"Success: {response.json()}")
                else:
                    general_logger.error(
                        f"HTTP Error {response.status_code}: {response.text}"
                    )

        except Exception as e:
            general_logger.error(
                f"input_reader - An unexpected exception occurred: {e}"
            )
            await asyncio.sleep(5)
        await asyncio.sleep(0.1)


# ======= Main =======


async def run():
    msg_start = "Doorbot 1.3 Slack App Starting"
    general_logger.info(f"Sending startup message: {msg_start}")
    await app.client.chat_postMessage(
        channel=config.channel,
        text=msg_start,
    )

    asyncio.ensure_future(read_tags())
    asyncio.ensure_future(relock_door())
    asyncio.ensure_future(clear_blinkstick())
    asyncio.ensure_future(slack_logs_worker())
    asyncio.ensure_future(input_reader())
    handler = AsyncSocketModeHandler(app, config.SLACK_APP_TOKEN)
    await handler.start_async()


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
