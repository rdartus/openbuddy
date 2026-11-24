"""FT3168 polling and landscape gesture recognition for the S3 AMOLED v2."""

import time

import board_config as cfg

HOLD_MS = 1000
HOLD_MAX_MS = 3000
GESTURE_GUARD_MS = 1200
STILL_PIXELS = 18
MAX_SAMPLE_GAP_MS = 350
MIN_HOLD_SAMPLES = 5


def confirm_area(position):
    """Only a deliberate hold over the visible choice can send a reply."""
    x, y = position
    left, top, width, height = cfg.UI_CHOICE_HOLD_RECT
    return left <= x < left + width and top <= y < top + height


class Touch:
    def __init__(self, factory=None):
        self.owns_bus = factory is None
        if factory is None:
            from machine import I2C, Pin
            factory = lambda: I2C(cfg.IMU_I2C_ID, sda=Pin(cfg.IMU_SDA),
                                  scl=Pin(cfg.IMU_SCL), freq=cfg.IMU_I2C_FREQ, timeout=10000)
        self.i2c = factory()
        self.status = bytearray(1)
        self.coords = bytearray(4)
        self.i2c.writeto_mem(cfg.TOUCH_ADDRESS, 0x00, b"\x00")
        self.start = None
        self.last = None
        self.moved = False
        self.samples = 0
        self.hold_stable = False
        self.last_sample_at = None
        self.guard_until = None
        self.next_poll = None
        self.errors = 0

    def sample(self, orientation):
        self.i2c.readfrom_mem_into(cfg.TOUCH_ADDRESS, 0x02, self.status)
        if self.status[0] != 1:
            return None
        self.i2c.readfrom_mem_into(cfg.TOUCH_ADDRESS, 0x03, self.coords)
        physical_x = (self.coords[0] & 15) << 8 | self.coords[1]
        physical_y = (self.coords[2] & 15) << 8 | self.coords[3]
        if physical_x >= 280 or physical_y >= 456:
            return None
        # Inverse of co5300.LCD._point(), for the full 456x280 canvas.
        if orientation == "landscape":
            return 455 - physical_y, physical_x
        return physical_y, 279 - physical_x

    def poll(self, now, orientation, request=None):
        if self.next_poll is not None and time.ticks_diff(now, self.next_poll) < 0:
            return None
        self.next_poll = time.ticks_add(now, 60)
        try:
            position = self.sample(orientation)
            self.errors = 0
        except OSError:
            self.start = None
            self.last = None
            self.moved = False
            self.hold_stable = False
            self.guard_until = time.ticks_add(now, GESTURE_GUARD_MS)
            self.errors += 1
            if self.errors >= 3:
                raise
            return None  # IMU failure or bus reinitialization must not stop USB.
        if position is not None:
            if self.start is None:
                self.start = (position[0], position[1], now, orientation, request)
                self.moved = False
                self.samples = 0
                self.hold_stable = request is not None and confirm_area(position)
            else:
                if (self.last_sample_at is None
                        or time.ticks_diff(now, self.last_sample_at) > MAX_SAMPLE_GAP_MS
                        or not confirm_area(position)):
                    self.hold_stable = False
                if (abs(position[0] - self.start[0]) > STILL_PIXELS
                        or abs(position[1] - self.start[1]) > STILL_PIXELS):
                    self.moved = True
                    self.hold_stable = False
            self.samples += 1
            self.last_sample_at = now
            self.last = position
            return None
        if self.start is None:
            return None
        x, y, began, original, original_request = self.start
        self.start = None
        # Read the last contact before release; a swipe is measured during touch.
        end = self.last or (x, y)
        self.last = None
        moved = self.moved
        self.moved = False
        duration = time.ticks_diff(now, began)
        if original != orientation or original_request is not request or duration > HOLD_MAX_MS:
            self.guard_until = time.ticks_add(now, GESTURE_GUARD_MS)
            return None
        dx, dy = end[0] - x, end[1] - y
        if duration <= 1600 and abs(dx) >= 55 and abs(dx) > abs(dy) * 2:
            self.guard_until = time.ticks_add(now, GESTURE_GUARD_MS)
            return "left" if dx < 0 else "right"
        if duration <= 1600 and abs(dy) >= 55 and abs(dy) > abs(dx) * 2:
            self.guard_until = time.ticks_add(now, GESTURE_GUARD_MS)
            return "up" if dy < 0 else "down"
        if (request is not None and not moved and self.hold_stable
                and self.samples >= MIN_HOLD_SAMPLES
                and time.ticks_diff(now, self.last_sample_at) <= MAX_SAMPLE_GAP_MS
                and HOLD_MS <= duration <= HOLD_MAX_MS
                and abs(dx) <= STILL_PIXELS and abs(dy) <= STILL_PIXELS
                and confirm_area((x, y)) and confirm_area(end)
                and (self.guard_until is None or time.ticks_diff(began, self.guard_until) >= 0)):
            return "hold"
        self.guard_until = time.ticks_add(now, GESTURE_GUARD_MS)
        return None

    def close(self):
        if self.i2c is not None:
            if self.owns_bus:
                self.i2c.deinit()
            self.i2c = None
