"""FT3168 polling and landscape gesture recognition for the S3 AMOLED v2."""

import time

import board_config as cfg


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

    def poll(self, now, orientation):
        if self.next_poll is not None and time.ticks_diff(now, self.next_poll) < 0:
            return None
        self.next_poll = time.ticks_add(now, 60)
        try:
            position = self.sample(orientation)
            self.errors = 0
        except OSError:
            self.start = None
            self.last = None
            self.errors += 1
            if self.errors >= 3:
                raise
            return None  # IMU failure or bus reinitialization must not stop USB.
        if position is not None:
            if self.start is None:
                self.start = (position[0], position[1], now, orientation)
            self.last = position
            return None
        if self.start is None:
            return None
        x, y, began, original = self.start
        self.start = None
        if original != orientation or time.ticks_diff(now, began) > 1600:
            return None
        # Read the last contact before release; a swipe is measured during touch.
        end = self.last or (x, y)
        self.last = None
        dx, dy = end[0] - x, end[1] - y
        if abs(dx) >= 55 and abs(dx) > abs(dy) * 2:
            return "left" if dx < 0 else "right"
        if abs(dx) <= 24 and abs(dy) <= 24 and time.ticks_diff(now, began) >= 40:
            return "tap"
        return None

    def close(self):
        if self.i2c is not None:
            if self.owns_bus:
                self.i2c.deinit()
            self.i2c = None
