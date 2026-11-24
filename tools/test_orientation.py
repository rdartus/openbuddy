"""Read raw S3 v2 accelerometer axes without changing display or flash files.

Run with mpremote while the bridge is stopped, then reset the board afterward.
"""

import time

import board_config as cfg

if cfg.BOARD_MODEL != "waveshare-s3-amoled-164-v2":
    raise ValueError("Orientation diagnostic requires the S3 AMOLED v2 profile")

from qmi8658 import Accelerometer

sensor = Accelerometer()
try:
    print("Raw X/Y/Z (1 g = 16384); keep the board still:")
    for _ in range(10):
        time.sleep_ms(100)
        print(sensor.read())
finally:
    sensor.close()
