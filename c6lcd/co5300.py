"""Waveshare S3 AMOLED 1.64 (SH8601/CO5300 naming), with native QSPI pixels.

Keep the co5300 module name for persisted board profiles. The native bus owns
the fixed QSPI pins and command framing; registers are single-lane, pixels quad.
The 320x172 canvas is centred and rotated in software on the 280x456 panel.
"""

from machine import Pin
import time

try:
    import amoled_qspi
except ImportError:
    raise ImportError("AMOLED requires native amoled_qspi; install the OpenBuddy "
                      "ESP32-S3 QSPI MicroPython firmware (with octal PSRAM), "
                      "not stock MicroPython")

import board_config as cfg
from st7789 import LCD as TextRenderer, rgb


class LCD(TextRenderer):
    WIDTH = 280
    HEIGHT = 456

    def __init__(self, orientation="landscape"):
        self.bus = None
        try:
            self.bus = amoled_qspi.Bus(baudrate=cfg.LCD_SPI_BAUD, cs=cfg.LCD_CS)
            self.rst = Pin(cfg.LCD_RST, Pin.OUT, value=1)
            # Shadow preserves aligned neighbours; scratch packs one native RAMWR.
            # Two persistent 255360-byte buffers fit the board's 8 MB PSRAM.
            self.buffer = bytearray(self.WIDTH * self.HEIGHT * 2)
            self.view = memoryview(self.buffer)
            self.transfer_buffer = bytearray(len(self.buffer))
            self.transfer_view = memoryview(self.transfer_buffer)
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
        except BaseException:
            self.close()
            raise

    def close(self):
        """Release the native bus; safe after partial initialization or repeated calls."""
        try:
            if self.bus is not None:
                self.bus.deinit()
        finally:
            self.bus = None
            self.view = self.buffer = None
            self.transfer_view = self.transfer_buffer = None

    def _cmd(self, command, data=None):
        self.bus.write(command, data, quad=False)

    def set_orientation(self, name):
        if name not in ("landscape", "landscape_inv"):
            raise ValueError("AMOLED UI supports landscape orientations only")
        self.orientation = name
        self.w, self.h = 320, 172
        self.clear_all()

    def clear_all(self, color=0):
        """Fill the full physical 280x456 panel, including the canvas margins."""
        line = bytes((color >> 8, color & 255)) * self.WIDTH
        for start in range(0, len(self.buffer), len(line)):
            self.view[start:start + len(line)] = line
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
        if w <= 0 or h <= 0:
            return
        if x < 0 or y < 0 or x + w > self.WIDTH or y + h > self.HEIGHT:
            raise ValueError("Drawing outside the physical display")
        x1, y1 = (x + w + 1) & ~1, (y + h + 1) & ~1
        x, y = x & ~1, y & ~1
        row_bytes = (x1 - x) * 2
        length = 0
        for row in range(y, y1):
            start = (row * self.WIDTH + x) * 2
            self.transfer_view[length:length + row_bytes] = self.view[start:start + row_bytes]
            length += row_bytes
        # Waveshare's panel gap is 20 columns; update coordinates must be even.
        left, right = x + 20, x1 - 1 + 20
        self._cmd(0x2A, bytes((left >> 8, left & 255, right >> 8, right & 255)))
        self._cmd(0x2B, bytes((y >> 8, y & 255, (y1 - 1) >> 8, (y1 - 1) & 255)))
        # Every native write starts a new RAMWR, so rows must be contiguous.
        self.bus.write(0x2C, self.transfer_view[:length], quad=True)

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
