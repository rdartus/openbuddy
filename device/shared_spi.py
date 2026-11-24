"""One SPI controller, two chip selects, serialized by the firmware main loop."""

from machine import Pin, SPI

import board_config as cfg


class SharedSPI:
    def __init__(self, sd_only=False):
        # The S3 QSPI display owns its CS; the separate TF bus must not touch it.
        self.lcd_cs = (None if sd_only and cfg.DISPLAY_DRIVER == "co5300" else
                       Pin(cfg.LCD_CS, Pin.OUT, value=1))
        self.sd_cs = Pin(cfg.SD_CS, Pin.OUT, value=1)
        self.sd_only = sd_only
        self.baudrate = cfg.SD_SPI_BAUD if sd_only else cfg.LCD_SPI_BAUD
        self.spi = SPI(cfg.SD_SPI_ID if sd_only else cfg.LCD_SPI_ID,
                       baudrate=self.baudrate, polarity=0, phase=0,
                       sck=Pin(cfg.SD_SCLK if sd_only else cfg.LCD_SCLK),
                       mosi=Pin(cfg.SD_MOSI if sd_only else cfg.LCD_MOSI),
                       miso=Pin(cfg.SD_MISO))

    def configure(self, baudrate):
        if self.lcd_cs is not None:
            self.lcd_cs(1)
        self.sd_cs(1)
        if self.baudrate != baudrate:
            self.spi.init(baudrate=baudrate, polarity=0, phase=0)
            self.baudrate = baudrate

    def for_lcd(self):
        self.configure(cfg.SD_SPI_BAUD if self.sd_only else cfg.LCD_SPI_BAUD)

    def for_sd(self):
        self.configure(cfg.SD_SPI_BAUD)
