"""RAM-only panel check: python -m mpremote connect PORT run tools/test_amoled.py.

Requires deployed Python files and native QSPI firmware. Reset afterwards to
restart the companion. This check does not initialize BLE or asset storage.
"""

import time
import board_config as cfg


def main():
    if (cfg.BOARD_MODEL != "waveshare-s3-amoled-164-v2"
            or cfg.DISPLAY_DRIVER != "co5300"):
        raise RuntimeError("Select the waveshare-s3-amoled-164-v2 board profile first")
    from co5300 import LCD, rgb

    lcd = None
    try:
        lcd = LCD()
        for name, color in (("red", rgb(255, 0, 0)),
                            ("green", rgb(0, 255, 0)),
                            ("blue", rgb(0, 0, 255)),
                            ("black", 0), ("white", 0xFFFF)):
            print("Full physical panel:", name)
            lcd.clear_all(color)
            time.sleep_ms(1500)
        lcd.clear_all(0)
    finally:
        if lcd is not None:
            lcd.close()


if __name__ == "__main__":
    main()
