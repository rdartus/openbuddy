"""Minimal QMI8658 accelerometer over I2C; no gyro, IRQ or touch access."""

import board_config as cfg
from machine import I2C, Pin


class Accelerometer:
    # +/-2 g: 16384 LSB/g, little-endian XYZ starting at AX_L (0x35).
    def __init__(self):
        self.i2c = I2C(cfg.IMU_I2C_ID, sda=Pin(cfg.IMU_SDA), scl=Pin(cfg.IMU_SCL),
                       freq=cfg.IMU_I2C_FREQ, timeout=10000)
        self.address = cfg.IMU_ADDRESS
        self.status = bytearray(1)
        self.buffer = bytearray(6)
        try:
            self.i2c.readfrom_mem_into(self.address, 0x00, self.status)
            if self.status[0] != 0x05:
                raise ValueError("QMI8658 WHO_AM_I must be 0x05")
            # Disable sensors before changing their configuration. Do not reset the
            # shared I2C bus or touch controller; enable only the accelerometer.
            for register, value in ((0x08, 0x00), (0x02, 0x60), (0x03, 0x07),
                                    (0x06, 0x00), (0x09, 0x00), (0x08, 0x01)):
                self.i2c.writeto_mem(self.address, register, bytes((value,)))
        except BaseException:
            self.close()
            raise

    def read(self):
        """Return a fresh signed XYZ sample, or None without waiting for data."""
        self.i2c.readfrom_mem_into(self.address, 0x2E, self.status)
        if not self.status[0] & 0x01:
            return None
        self.i2c.readfrom_mem_into(self.address, 0x35, self.buffer)
        values = []
        for offset in (0, 2, 4):
            value = self.buffer[offset] | self.buffer[offset + 1] << 8
            values.append(value - 65536 if value & 0x8000 else value)
        return tuple(values)

    def close(self):
        if self.i2c is not None:
            self.i2c.deinit()
            self.i2c = None
