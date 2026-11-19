"""Landscape diagnostic UI and a deliberately dim, non-blocking status halo."""

import time

from st7789 import rgb
import board_config as cfg

COLORS = {
    "offline": (72, 84, 108), "idle": (72, 132, 180),
    "thinking": (70, 116, 255), "working": (32, 220, 210),
    "permission": (255, 120, 24), "question": (255, 210, 40),
    "success": (50, 230, 120), "error": (255, 55, 60),
    "retry": (220, 140, 32), "pairing": (170, 90, 255),
}
LABELS = {
    "offline": "OFFLINE", "idle": "READY", "thinking": "THINKING",
    "working": "WORKING", "permission": "PERMISSION", "question": "QUESTION",
    "success": "DONE", "error": "ERROR", "retry": "RETRY", "pairing": "PAIRING",
}
BACKGROUND = rgb(*cfg.UI_BACKGROUND)
WHITE = rgb(225, 233, 245)
MUTED = rgb(120, 138, 158)


def printable(text):
    return "".join(character if 32 <= ord(character) <= 126 else "?"
                    for character in text)


def page(text, width, rows, now):
    """Return a fixed-width window; wait at both ends of a long text."""
    capacity = width * rows
    last = max(0, len(text) - capacity)
    step = (now // 350) % (last + 9) if last else 0
    start = min(last, max(0, step - 4))
    content = text[start:start + capacity]
    return [content[offset:offset + width] for offset in range(0, len(content), width)]


class BuddyUI:
    def __init__(self, lcd, led, player=None):
        self.lcd = lcd
        self.led = led
        self.player = player
        self.previous = None
        self.face_frame = None
        self.led_value = None
        self.choice_view = None
        self.lcd.fill_rect(0, 0, lcd.w, lcd.h, BACKGROUND)

    def invalidate(self):
        """Force a full redraw, e.g. after the panel orientation changed."""
        self.previous = None
        self.choice_view = None

    def _face(self, accent, frame, state):
        lcd = self.lcd
        stage_x, stage_y, stage_w, stage_h = cfg.UI_PET_STAGE
        scale = cfg.UI_PET_SCALE
        lcd.fill_rect(stage_x, stage_y, stage_w, stage_h, BACKGROUND)
        bob = 3 if frame % 2 and state in ("thinking", "working") else 0
        x, y = 17, 20 + bob

        def rect(dx, dy, w, h, color):
            lcd.fill_rect(stage_x + (x + dx) * scale,
                          stage_y + (y + dy) * scale, w * scale, h * scale, color)

        rect(28, -10, 5, 10, accent)
        rect(5, 0, 56, 48, accent)
        rect(0, 10, 66, 30, accent)
        rect(10, 8, 46, 28, BACKGROUND)
        height = 2 if frame % 8 == 0 else 8
        rect(18, 17, 7, height, WHITE)
        rect(41, 17, 7, height, WHITE)
        rect(24, 43, 18, 3, BACKGROUND)
        rect(10, 48, 12, 8, accent)
        rect(44, 48, 12, 8, accent)

    def draw(self, buddy, now):
        usb = getattr(buddy, "kind", None) == "usb"
        pairing = buddy.pairing_open(now) or buddy.passkey is not None
        state = "pairing" if pairing else buddy.state if buddy.online(now) else "offline"
        color = COLORS[state]
        accent = rgb(*color)
        if buddy.passkey is not None:
            detail = "%06d" % buddy.passkey
            footer = "CHECK PC CODE - BOOT TO CONFIRM" if buddy.confirm else "ENTER THIS CODE ON YOUR PC"
        elif pairing:
            remaining = max(0, time.ticks_diff(buddy.pair_until, now) // 1000)
            detail = "WINDOW %ds" % remaining
            footer = "ADD OPENBUDDY IN WINDOWS BLUETOOTH"
        elif buddy.hid_until is not None:
            detail = "F13 TEST ARMED"
            footer = "SHORT BOOT = ONE F13 KEY"
        else:
            detail = ((printable(buddy.label)[:24] or "Awaiting events")
                      if buddy.online(now) else "No Python bridge")
            footer = "USB BRIDGE ACTIVE" if usb else "BOOT: ROTATE | HOLD 3s: PAIR"
        link = "USB LINK" if usb else "BLE SECURE" if buddy.secure else "BLE WAIT"
        asset_ready = self.player is not None and self.player.available
        quota = printable(getattr(buddy, "info", ""))[:24] if buddy.online(now) else ""
        candidate = getattr(buddy, "prompt", None)
        prompt = candidate.ready() if callable(getattr(candidate, "ready", None)) else None
        if not isinstance(prompt, dict) or state not in ("question", "permission") or cfg.DISPLAY_DRIVER != "co5300":
            prompt = None
        if prompt is not None:
            footer = "SENDING - CHECK OPENCODE" if prompt["sent"] else "SWIPE: CHOICE  TAP: ANSWER"
        snapshot = (state, detail if prompt is None else prompt["token"], footer,
                    link, asset_ready, quota, prompt["selected"] if prompt else None)
        changed = snapshot != self.previous
        if changed:
            self.previous = snapshot
            self.face_frame = None
            lcd = self.lcd
            lcd.fill_rect(0, 0, lcd.w, lcd.h, BACKGROUND)
            lcd.fill_rect(0, 0, lcd.w, 3, accent)
            lcd.text("OPENBUDDY", 12, cfg.UI_HEADER_Y, WHITE, BACKGROUND)
            lcd.text(link, cfg.UI_LINK_X, cfg.UI_HEADER_Y, MUTED, BACKGROUND)
            lcd.text(LABELS[state], cfg.UI_TEXT_X, cfg.UI_STATE_Y, accent, BACKGROUND, 2)
            scale = 2 if buddy.passkey is not None else 1
            max_detail = min(24, (lcd.w - cfg.UI_TEXT_X) // (8 * scale))
            if prompt is None:
                lcd.text(detail[:max_detail], cfg.UI_TEXT_X, cfg.UI_DETAIL_Y, WHITE, BACKGROUND, scale)
            asset_label = "PET / FLASH" if getattr(self.player, "source", None) == "internal" else "PET / MICROSD"
            if prompt is None:
                lcd.text(quota or (asset_label if asset_ready
                                   else "USB SERIAL / v1" if usb else "HID + GATT / v1"),
                           cfg.UI_TEXT_X, cfg.UI_INFO_Y, MUTED, BACKGROUND)
            lcd.fill_rect(cfg.UI_DIVIDER_INSET, cfg.UI_DIVIDER_Y,
                          lcd.w - 2 * cfg.UI_DIVIDER_INSET, 1, accent)
            lcd.text(footer[:(lcd.w - 24) // 8], 12, cfg.UI_FOOTER_Y, MUTED, BACKGROUND)
        if prompt is not None:
            width = (self.lcd.w - cfg.UI_TEXT_X - 4) // 8
            if prompt["title_at"] is None:
                prompt["title_at"] = now
            if prompt["option_at"] is None:
                prompt["option_at"] = now
            question = page(prompt["text"], width, 3,
                            time.ticks_diff(now, prompt["title_at"]))
            option = page(prompt["options"][prompt["selected"]], width, 3,
                          time.ticks_diff(now, prompt["option_at"]))
            current = (tuple(question), tuple(option), prompt["selected"], prompt["sent"])
            if changed or current != self.choice_view:
                self.choice_view = current
                lcd = self.lcd
                lcd.fill_rect(cfg.UI_TEXT_X, cfg.UI_DETAIL_Y, lcd.w - cfg.UI_TEXT_X,
                              cfg.UI_DIVIDER_Y - cfg.UI_DETAIL_Y, BACKGROUND)
                for index, line in enumerate(question):
                    lcd.text(line, cfg.UI_TEXT_X, cfg.UI_DETAIL_Y + index * 12, WHITE, BACKGROUND)
                lcd.text("%d/%d" % (prompt["selected"] + 1, len(prompt["options"])),
                         cfg.UI_TEXT_X, cfg.UI_DETAIL_Y + 49, MUTED, BACKGROUND)
                for index, line in enumerate(option):
                    lcd.text(line, cfg.UI_TEXT_X, cfg.UI_DETAIL_Y + 63 + index * 12,
                             accent, BACKGROUND)
        else:
            self.choice_view = None
        frame = now // 350
        played = asset_ready and self.player.draw(state, now, force=changed)
        if not played and frame != self.face_frame:
            if asset_ready:
                self.lcd.fill_rect(*cfg.UI_PET_STAGE, BACKGROUND)
            self.face_frame = frame
            self._face(accent, frame, state)
        # RGB components stay below 40; do not blink at strobe frequencies.
        phase = (now % 2000) / 1000
        breath = 1 - abs(phase - 1)
        brightness = 0.02 if state == "offline" else 0.03 + 0.09 * breath
        value = tuple(min(32, int(channel * brightness)) for channel in color)
        if self.led is not None and value != self.led_value:
            self.led_value = value
            self.led[0] = value
            self.led.write()
