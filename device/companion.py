"""Single-threaded firmware loop: BLE callbacks never perform LCD drawing."""

import os
import sys
import time

ORIENTATION_FILE = "openbuddy-orientation.txt"
PET_RETRY_MS = 3000
PET_SLOW_RETRY_MS = 30000
PET_FAST_ATTEMPTS = 20


def load_orientation():
    from buddy_orientation import FLIP

    try:
        with open(ORIENTATION_FILE) as handle:
            name = handle.read().strip()
    except OSError:
        return "landscape"
    return name if name in FLIP else "landscape"


def save_orientation(name):
    try:
        with open(ORIENTATION_FILE, "w") as handle:
            handle.write(name)
    except OSError:
        pass


def print_error(error, stage):
    """Diagnostics must not hide the exception being reported."""
    try:
        print("OpenBuddy error during:", stage)
        sys.print_exception(error)
    except Exception:
        pass


def report_error(error, stage, buddy=None):
    print_error(error, stage)
    try:
        with open("openbuddy-error.txt", "w") as handle:
            handle.write("Stage: " + stage + "\n")
            if buddy is not None:
                handle.write("\n".join(buddy.diagnostics) + "\n")
            sys.print_exception(error, handle)
            handle.flush()
        os.sync()
    except Exception:
        pass  # A full filesystem or a logging failure must not mask the cause.


def close_resource(name, resource):
    if resource is None:
        return
    try:
        close = getattr(resource, "close", None)
        if close is not None:
            close()
    except Exception as error:
        # Continue closing other resources; preserve the primary error journal.
        print_error(error, name + " cleanup")


def run():
    lcd = led = buddy = storage = player = orientation = touch = None
    stage = "imports"
    try:
        from machine import Pin
        import board_config as cfg
        from buddy_usb import BuddyUSB
        from buddy_ui import BuddyUI
        from shared_spi import SharedSPI
        from storage import Storage
        from buddy_orientation import FLIP

        stage = "display"
        print("OpenBuddy startup:", stage)
        if cfg.DISPLAY_DRIVER == "co5300":
            from co5300 import LCD
            bus = None  # The S3 SD bus is created only when needed.
            lcd = LCD(load_orientation())
        else:
            from st7789 import LCD
            bus = SharedSPI()
            lcd = LCD(load_orientation(), bus=bus)
        stage = "LED"
        if cfg.RGB_LED is not None:
            from neopixel import NeoPixel
            led = NeoPixel(Pin(cfg.RGB_LED), 1)
            led[0] = (0, 0, 0)
            led.write()
        stage = "storage"
        storage = Storage(bus)
        stage = "orientation"
        touch_retry_at = None
        if cfg.AUTO_ORIENTATION:
            from buddy_orientation import AutoOrientation
            orientation = AutoOrientation()
            if hasattr(cfg, "TOUCH_ADDRESS"):
                from ft3168 import Touch
            orientation.poll(time.ticks_ms(), lcd.orientation)
            if hasattr(cfg, "TOUCH_ADDRESS") and orientation.sensor is not None:
                try:
                    touch = Touch(lambda: orientation.sensor.i2c)
                except (OSError, ValueError) as error:
                    print("Touch unavailable; use OpenCode to answer:", error)
                    touch_retry_at = time.ticks_add(time.ticks_ms(), 3000)
        stage = "assets"
        player = storage.load_player(lcd)

        def asset_status():
            return {"sd": storage.mounted, "orientation": lcd.orientation,
                    "imu": orientation.available if orientation is not None else False,
                    "touch": touch is not None,
                    "assets": player.source if player is not None and player.available else None,
                    "pet": player.pet_id if player is not None and player.available else None}

        def reload_pet():
            nonlocal player
            try:
                if player is not None:
                    player.close()
                storage.close()
                player = storage.load_player(lcd, attempts=1)
                ui.player = player
            except OSError as error:
                print("Pet reload failed:", error)

        stage = "USB"
        print("OpenBuddy startup:", stage)
        usb = BuddyUSB(asset_status=asset_status)
        stage = "BLE"
        print("OpenBuddy startup:", stage)
        try:
            from buddy_ble import BuddyBLE
            buddy = BuddyBLE(asset_status=asset_status)
        except Exception as error:
            report_error(error, stage)
            print("BLE unavailable; continuing with USB only until restart")
        stage = "UI"
        print("OpenBuddy startup:", stage)
        ui = BuddyUI(lcd, led, player)
        pet_attempts = 0
        pet_retry_at = time.ticks_add(time.ticks_ms(), PET_RETRY_MS)
        stage = "BOOT button"
        button = Pin(cfg.BOOT_BUTTON, Pin.IN, Pin.PULL_UP)
        raw_level = button.value()
        stable_level = raw_level
        changed_at = time.ticks_ms()
        pressed_at = None
        long_sent = False
        print("OpenBuddy BLE and USB ready; hold BOOT 3s to allow BLE pairing"
              if buddy is not None else "OpenBuddy USB ready; BLE unavailable")
        stage = "main loop"
        while True:
            now = time.ticks_ms()
            level = button.value()
            if level != raw_level:
                raw_level = level
                changed_at = now
            if level != stable_level and time.ticks_diff(now, changed_at) >= 30:
                stable_level = level
                if level == 0:
                    pressed_at = now
                    long_sent = False
                else:
                    if pressed_at is not None and not long_sent:
                        if buddy is not None and buddy.confirm is not None:
                            buddy.button()  # BLE pairing needs a physical confirmation.
                        else:
                            name = FLIP[lcd.orientation]
                            lcd.set_orientation(name)
                            if orientation is not None:
                                orientation.flip()
                            save_orientation(name)
                            ui.invalidate()
                    pressed_at = None
            if (pressed_at is not None and not long_sent
                    and time.ticks_diff(now, pressed_at) >= 3000):
                if buddy is not None:
                    buddy.button(long_press=True)
                long_sent = True
            if (not (player is not None and player.available)
                    and time.ticks_diff(now, pet_retry_at) >= 0):
                pet_attempts += 1
                pet_retry_at = time.ticks_add(
                    now, PET_RETRY_MS if pet_attempts < PET_FAST_ATTEMPTS else PET_SLOW_RETRY_MS)
                reload_pet()
            if buddy is not None:
                buddy.tick(now)
            usb.tick(now)
            if orientation is not None:
                name = orientation.poll(now, lcd.orientation)
                if name is not None:
                    lcd.set_orientation(name)
                    ui.invalidate()  # Automatic rotations never write to flash.
                if orientation.sensor is None and touch is not None:
                    touch.close()
                    touch = None
                if (hasattr(cfg, "TOUCH_ADDRESS") and orientation.sensor is not None and touch is None
                        and (touch_retry_at is None or time.ticks_diff(now, touch_retry_at) >= 0)):
                    try:
                        touch = Touch(lambda: orientation.sensor.i2c)
                    except (OSError, ValueError):
                        touch_retry_at = time.ticks_add(now, 3000)
            pairing = buddy is not None and (buddy.pairing_open(now) or buddy.passkey is not None)
            active = usb if buddy is None or (usb.online(now) and not pairing) else buddy
            if touch is not None and active.online(now) and not pairing:
                try:
                    gesture = touch.poll(now, lcd.orientation)
                except OSError:
                    touch.close()
                    touch = None
                    touch_retry_at = time.ticks_add(now, 3000)
                    gesture = None
                if gesture == "left":
                    active.prompt.move(1)
                elif gesture == "right":
                    active.prompt.move(-1)
                elif gesture == "tap":
                    active.choose()
            ui.draw(active, now)
            time.sleep_ms(20)
    except Exception as error:
        report_error(error, stage, buddy)
        # Do not draw an error on a potentially broken or deinitialized LCD bus.
        raise
    finally:
        close_resource("touch", touch)
        close_resource("orientation", orientation)
        close_resource("BLE", buddy)
        close_resource("player", player)
        close_resource("storage", storage)
        close_resource("display", lcd)
        if led is not None:
            try:
                led[0] = (0, 0, 0)
                led.write()
            except Exception as error:
                print_error(error, "LED cleanup")
