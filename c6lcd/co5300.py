"""CO5300 on Waveshare S3 AMOLED 1.64, using documented single-lane SPI.

CO5300 datasheet pp. 20-24: 02 00 CMD 00 wraps both registers and pixels.
No QPI/quad opcode is used, so stock MicroPython works. The existing 320x172
landscape canvas is centred and rotated in software on the 280x456 panel.
"""

from machine import Pin, SPI
import time

import board_config as cfg
from st7789 import LCD as TextRenderer, rgb


class LCD(TextRenderer):
    WIDTH = 280
    HEIGHT = 456

    def __init__(self, orientation="landscape"):
        self.cs = Pin(cfg.LCD_CS, Pin.OUT, value=1)
        self.rst = Pin(cfg.LCD_RST, Pin.OUT, value=1)
        self.spi = SPI(cfg.LCD_SPI_ID, baudrate=cfg.LCD_SPI_BAUD,
                       polarity=0, phase=0, sck=Pin(cfg.LCD_SCLK),
                       mosi=Pin(cfg.LCD_MOSI), miso=None)
        # A shadow buffer preserves neighbours when expanding updates to even pixels.
        self.buffer = bytearray(self.WIDTH * self.HEIGHT * 2)
        self.view = memoryview(self.buffer)
        self.rst(0)
        time.sleep_ms(10)
        self.rst(1)
        time.sleep_ms(150)
        for command, data, delay in (
                (0x36, b"\x00", 0), (0x3A, b"\x55", 0),
                (0x11, None, 80), (0xC4, b"\x80", 0),
                (0x35, b"\x00", 0), (0x53, b"\x20", 1),
                (0x63, b"\xff", 1), (0x51, b"\x00", 1),
                (0x29, None, 10)):
            self._cmd(command, data)
            if delay:
                time.sleep_ms(delay)
        self.set_orientation(orientation)
        self._cmd(0x51, b"\x80")  # Moderate AMOLED brightness, no PWM backlight.

    def _cmd(self, command, data=None):
        self.cs(0)
        try:
            self.spi.write(bytes((0x02, 0, command, 0)))
            if data is not None:
                self.spi.write(data)
        finally:
            self.cs(1)

    def set_orientation(self, name):
        if name not in ("landscape", "landscape_inv"):
            raise ValueError("AMOLED UI supports landscape orientations only")
        self.orientation = name
        self.w, self.h = 320, 172
        self.buffer[:] = bytes(len(self.buffer))
        self._flush(0, 0, self.WIDTH, self.HEIGHT)

    def _point(self, x, y):
        if self.orientation == "landscape":
            return 54 + y, 68 + 319 - x
        return 54 + 171 - y, 68 + x

    def _bounds(self, x, y, w, h):
        if w <= 0 or h <= 0:
            return None
        if x < 0 or y < 0 or x + w > self.w or y + h > self.h:
            raise ValueError("Drawing outside the logical display")
        ax, ay = self._point(x, y)
        bx, by = self._point(x + w - 1, y + h - 1)
        return min(ax, bx), min(ay, by), h, w

    def _flush(self, x, y, w, h):
        x1, y1 = (x + w + 1) & ~1, (y + h + 1) & ~1
        x, y = x & ~1, y & ~1
        # Waveshare's panel gap is 20 columns; update coordinates must be even.
        left, right = x + 20, x1 - 1 + 20
        self._cmd(0x2A, bytes((left >> 8, left & 255, right >> 8, right & 255)))
        self._cmd(0x2B, bytes((y >> 8, y & 255, (y1 - 1) >> 8, (y1 - 1) & 255)))
        self.cs(0)
        try:
            self.spi.write(b"\x02\x00\x2c\x00")
            for row in range(y, y1):
                start = (row * self.WIDTH + x) * 2
                self.spi.write(self.view[start:start + (x1 - x) * 2])
        finally:
            self.cs(1)

    def blit(self, buf, x, y, w, h):
        bounds = self._bounds(x, y, w, h)
        if bounds is None:
            return
        if len(buf) != w * h * 2:
            raise ValueError("Invalid RGB565 buffer length")
        for row in range(h):
            for column in range(w):
                px, py = self._point(x + column, y + row)
                target = (py * self.WIDTH + px) * 2
                source = (row * w + column) * 2
                self.buffer[target] = buf[source]
                self.buffer[target + 1] = buf[source + 1]
        self._flush(*bounds)

    def fill_rect(self, x, y, w, h, color):
        bounds = self._bounds(x, y, w, h)
        if bounds is None:
            return
        px, py, pw, ph = bounds
        line = bytes((color >> 8, color & 255)) * pw
        for row in range(py, py + ph):
            start = (row * self.WIDTH + px) * 2
            self.buffer[start:start + len(line)] = line
        self._flush(*bounds)
