"""
Separate file for Slack blockkit blocks because they are huge and make code
hard to follow.
"""

# The Slack Home Tab
home_view = {
    "type": "home",
    "callback_id": "home_view",
    # body of the view
    "blocks": [
        {
            "type": "actions",
            "block_id": "message_actions",
            "elements": [
                {
                    "type": "static_select",
                    "placeholder": {
                        "type": "plain_text",
                        "text": "Select a message to send",
                        "emoji": True,
                    },
                    "options": [
                        {
                            "text": {
                                "type": "plain_text",
                                "text": "Your key has been disabled",
                                "emoji": True,
                            },
                            "value": "key_disabled",
                        },
                        {
                            "text": {
                                "type": "plain_text",
                                "text": "A volunteer will contact you shortly",
                                "emoji": True,
                            },
                            "value": "volunteer_contact",
                        },
                        {
                            "text": {
                                "type": "plain_text",
                                "text": "I know you're there",
                                "emoji": True,
                            },
                            "value": "notice_you",
                        },
                        {
                            "text": {
                                "type": "plain_text",
                                "text": "Please check slack",
                                "emoji": True,
                            },
                            "value": "check_slack",
                        },
                    ],
                    "action_id": "sendMessage",
                }
            ],
        },
        {
            "dispatch_action": True,
            "type": "input",
            "block_id": "tts_input",
            "element": {"type": "plain_text_input", "action_id": "ttsMessage"},
            "label": {
                "type": "plain_text",
                "text": "Send a custom message via text-to-speech",
                "emoji": True,
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "block_id": "unlock_section",
            "text": {
                "type": "mrkdwn",
                "text": "Manually unlock the door, a sound notification will be played automatically",
            },
            "accessory": {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "Unlock for 30 seconds",
                    "emoji": True,
                },
                "value": "30",
                "action_id": "unlock",
            },
        },
        # Add a divider
        {"type": "divider"},
        # Add buttons for the actions:
        # - update keys
        # - livliness check
        # - Restarting App
        # - Rebooting Raspberry Pi
        {
            "type": "actions",
            "block_id": "admin_actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Update Keys",
                        "emoji": True,
                    },
                    "value": "update_keys",
                    "action_id": "updateKeys",
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Liveliness Check",
                        "emoji": True,
                    },
                    "value": "liveliness_check",
                    "action_id": "livelinessCheck",
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Restart App",
                        "emoji": True,
                    },
                    "value": "restart_app",
                    "action_id": "restartApp",
                    "confirm": {
                        "title": {"type": "plain_text", "text": "Are you sure?"},
                        "text": {
                            "type": "mrkdwn",
                            "text": "This will restart the app. Are you sure you want to continue?",
                        },
                        "confirm": {"type": "plain_text", "text": "Yes"},
                        "deny": {"type": "plain_text", "text": "No"},
                    },
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Reboot Raspberry Pi",
                        "emoji": True,
                    },
                    "value": "reboot_pi",
                    "action_id": "rebootPi",
                    "confirm": {
                        "title": {"type": "plain_text", "text": "Are you sure?"},
                        "text": {
                            "type": "mrkdwn",
                            "text": "This will reboot the Raspberry Pi. Are you sure you want to continue?",
                        },
                        "confirm": {"type": "plain_text", "text": "Yes"},
                        "deny": {"type": "plain_text", "text": "No"},
                    },
                },
            ],
        },
    ],
}


# Displayed when user doesn't have access to home view
home_view_denied = {
    "type": "home",
    "callback_id": "home_view",
    # body of the view
    "blocks": [
        {
            "type": "section",
            "text": {
                "type": "plain_text",
                "text": "You don't have access to the Doorbot admin page",
                "emoji": True,
            },
        },
    ],
}


def door_access(name, tag, status):
    """Message posted when door access is being reported"""
    attachments = [
        {
            "fields": [
                {"title": "Name", "value": name, "short": True},
                {"title": "Tag", "value": tag, "short": True},
                {"title": "Status", "value": status, "short": True},
            ]
        }
    ]
    return {
        "text": "Someone interacted with the door",
        "attachments": attachments,
        "metadata": {
            "event_type": "door_access",
            "event_payload": {"name": name, "tag": tag, "status": status},
        },
    }
