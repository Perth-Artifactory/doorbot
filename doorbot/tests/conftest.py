"""
Shared test configuration and fixtures for doorbot tests.

This module provides common mock hardware classes and setup that is shared
across all test files. By centralizing the mocking code here, we avoid
duplication and ensure consistent test behavior.

The mocking strategy (borrowed from tools/interactive_slack_testing.py):
1. Mock all hardware modules BEFORE importing app.py
2. Import the actual functions from app.py
3. Test the real implementation with mocked dependencies
"""

import sys
import asyncio
from unittest.mock import Mock

# ===== MOCK HARDWARE CLASSES =====


class MockPigpio:
    def pi(self):
        return MockPi()


class MockPi:
    def __init__(self):
        self.connected = True

    def stop(self):
        pass


class MockDoorbotHatGpio:
    def __init__(self, pi):
        self.relay_state = {}

    def set_relay(self, channel, state):
        self.relay_state[channel] = state

    def read_switches(self):
        return {0: False, 1: False}


class MockKeyReader:
    def __init__(self, pi):
        pass

    def start_reading(self):
        pass

    def stop_reading(self):
        pass


class MockBlinkstickInterface:
    def __init__(self):
        self.color = "blue"

    def set_colour_name(self, color):
        self.color = color

    def set_white(self):
        self.set_colour_name("white")


class MockSocketClient:
    def __init__(self, socket_path):
        self.socket_path = socket_path

    async def authorize(self, card_number):
        return {"allowed": True, "sound_path": "/test/sound.mp3"}

    async def refresh(self):
        return True

    def is_available(self):
        return True


class MockSoundPlayer:
    def __init__(self, sound_dir, custom_sound_dir):
        pass

    def play_sound(self, sound_name):
        pass


class MockMonotonicWaiter:
    def __init__(self, name):
        self.name = name
        self._duration = 0

    def set_wait_time(self, duration_s):
        self._duration = duration_s

    async def wait(self):
        if self._duration > 0:
            self._duration = 0
            return True
        await asyncio.sleep(0.1)
        return False


class MockTextToSpeech:
    def non_blocking_speak(self, text):
        pass


# ===== INSTALL MOCKS INTO sys.modules =====


def setup_hardware_mocks():
    """
    Install all hardware mocks into sys.modules.

    This MUST be called before importing doorbot.app or any module that imports it.
    The mocks intercept hardware dependencies so the real app code can run without
    actual hardware present.
    """
    # Create mock text_to_speech module
    mock_tts_module = Mock()
    mock_tts_module.non_blocking_speak = MockTextToSpeech().non_blocking_speak

    # Inject mocks into sys.modules BEFORE importing
    sys.modules["pigpio"] = MockPigpio()
    sys.modules["doorbot.interfaces.doorbot_hat_gpio"] = Mock(
        DoorbotHatGpio=MockDoorbotHatGpio
    )
    sys.modules["doorbot.interfaces.wiegand_key_reader"] = Mock(KeyReader=MockKeyReader)
    sys.modules["doorbot.interfaces.blinkstick_interface"] = Mock(
        BlinkstickInterface=MockBlinkstickInterface
    )
    sys.modules["doorbot.interfaces.socket_client"] = Mock(
        SocketClient=MockSocketClient
    )
    sys.modules["doorbot.interfaces.sound_player"] = Mock(SoundPlayer=MockSoundPlayer)
    sys.modules["doorbot.interfaces.monotonic_waiter"] = Mock(
        MonotonicWaiter=MockMonotonicWaiter
    )
    sys.modules["doorbot.interfaces.text_to_speech"] = mock_tts_module


# Install the mocks immediately when this module is imported
# This ensures they're in place before any test file imports doorbot.app
setup_hardware_mocks()
