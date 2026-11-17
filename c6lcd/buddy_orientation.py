"""Debounced gravity orientation; failures leave USB/BLE and BOOT usable."""

import time

import board_config as cfg

FLIP = {"landscape": "landscape_inv", "landscape_inv": "landscape"}
POLL_MS = 100
SETTLE_MS = 500
RETRY_MS = 30000


def gravity_orientation(sample):
    """Choose landscape polarity; ignore portrait, flat, diagonal and moving poses."""
    axis = cfg.IMU_LANDSCAPE_AXIS
    value = sample[axis] * cfg.IMU_LANDSCAPE_SIGN
    magnitude = sum(component * component for component in sample)
    # Accept 0.75..1.25 g and require a clearly dominant in-plane axis.
    if not 12288 ** 2 <= magnitude <= 20480 ** 2:
        return None
    strength = abs(value)
    other = max(abs(sample[index]) for index in range(3) if index != axis)
    if strength < 9830 or strength * 100 < other * 135:
        return None
    return "landscape_inv" if value > 0 else "landscape"


class AutoOrientation:
    def __init__(self, factory=None):
        if factory is None:
            from qmi8658 import Accelerometer
            factory = Accelerometer
        self.factory = factory
        self.sensor = None
        self.available = False
        self.inverted = False
        self.errors = 0
        self.next_poll = None
        self.candidate = None
        self.since = None

    def flip(self):
        """Keep a manual 180-degree correction until the next restart."""
        self.inverted = not self.inverted
        self.candidate = self.since = None

    def poll(self, now, current):
        if self.next_poll is not None and time.ticks_diff(now, self.next_poll) < 0:
            return None
        self.next_poll = time.ticks_add(now, POLL_MS)
        try:
            if self.sensor is None:
                self.sensor = self.factory()
                self.errors = 0
                print("QMI8658 auto orientation ready")
            sample = self.sensor.read()
            self.available = True
            self.errors = 0
        except (OSError, ValueError) as error:
            self.errors += 1
            self.candidate = self.since = None
            if self.sensor is None or self.errors >= 3:
                self.close()
                self.next_poll = time.ticks_add(now, RETRY_MS)
                print("Auto orientation unavailable; keeping BOOT rotation:", error)
            return None
        target = gravity_orientation(sample) if sample is not None else None
        if target is not None and self.inverted:
            target = FLIP[target]
        if target is None or target == current:
            self.candidate = self.since = None
        elif target != self.candidate:
            self.candidate, self.since = target, now
        elif time.ticks_diff(now, self.since) >= SETTLE_MS:
            self.candidate = self.since = None
            return target
        return None

    def close(self):
        if self.sensor is not None:
            try:
                self.sensor.close()
            except OSError:
                pass
        self.sensor = None
        self.available = False
