"""Hardware profiles for Waveshare C6 LCD and S3 AMOLED v2.

Single source of truth for pins and panel geometry. Imported by st7789.py and
main.py, so a pin or offset change happens here only.
"""

# --- Display (ST7789, SPI, write-only) -------------------------------------
LCD_SPI_ID = 1
LCD_SPI_BAUD = 40_000_000   # 40 MHz is the practical ceiling on this board
LCD_MOSI = 6                # shared with the TF card slot
LCD_SCLK = 7                # shared with the TF card slot
LCD_CS = 14
LCD_DC = 15
LCD_RST = 21
LCD_BL = 22                 # backlight, drive with PWM (see BL_DUTY_PERCENT)

# Waveshare warns that >50 % backlight duty for long periods can leave
# permanent dark shadows on the panel. Never drive GPIO22 as a plain output.
BL_PWM_FREQ = 1000
BL_DUTY_PERCENT = 50

# --- Other onboard peripherals ----------------------------------------------
RGB_LED = 8                 # one WS2812 (GRB order), VERY bright: keep values < 40
BOOT_BUTTON = 9             # pressed = low (RESET is not a GPIO)
SD_CS = 4                   # TF card, same SPI bus as the LCD
SD_MISO = 5
SD_SPI_BAUD = 8_000_000      # conservative shared-bus clock; benchmark on the card
SD_MOUNT = "/sd"
PET_DIRECTORY = "/sd/openbuddy/pets"
PET_SELECTION = "/sd/openbuddy/active.json"

# --- Panel geometry ----------------------------------------------------------
# The 172px glass is centred in the controller's 240px RAM axis:
# (240 - 172) / 2 = 34. Without the offset the picture is shifted and wraps.
PANEL_SHORT = 172
PANEL_LONG = 320
RAM_SHORT_OFFSET = 34

# name: (MADCTL, width, height, x_offset, y_offset)
# MV (0x20) swaps the axes, so the 34px offset moves from X to Y in landscape.
ORIENTATIONS = {
    "portrait":      (0x00, 172, 320, 34, 0),   # USB-C at the bottom
    "landscape":     (0xA0, 320, 172, 0, 34),   # USB-C on the left
    "portrait_inv":  (0xC0, 172, 320, 34, 0),   # USB-C on top
    "landscape_inv": (0x60, 320, 172, 0, 34),   # USB-C on the right
}
ORDER = ("portrait", "landscape", "portrait_inv", "landscape_inv")
DEFAULT_ORIENTATION = "landscape"
AUTO_ORIENTATION = False
# Logical landscape canvas and UI geometry (the physical panel may be rotated).
UI_WIDTH, UI_HEIGHT = 320, 172
# Device modules are copied to the ESP32 root; host tooling imports the same source.
try:
    from pet_format import BACKGROUND as UI_BACKGROUND
except ImportError:
    from device.pet_format import BACKGROUND as UI_BACKGROUND
UI_PET_SCALE = 1
UI_PET_STAGE = (8, 35, 104, 104)
UI_TEXT_X, UI_LINK_X = 124, 224
UI_HEADER_Y, UI_STATE_Y, UI_DETAIL_Y, UI_INFO_Y = 15, 55, 87, 113
UI_DIVIDER_Y, UI_FOOTER_Y = 141, 153
UI_DIVIDER_INSET = 0
UI_CHOICE_HOLD_RECT = None  # The C6 has no touch controller.

# Stock firmware defaults to C6; dedicated builds freeze their board identity.
# A saved explicit profile always wins. The chip model cannot identify PCB wiring.
BOARD_MODEL = "waveshare-c6-lcd-147"
try:
    from openbuddy_build import BOARD_MODEL
except ImportError:
    pass
DISPLAY_DRIVER = "st7789"
PET_STORAGE = "auto"
SD_SPI_ID = LCD_SPI_ID
SD_SCLK = LCD_SCLK
SD_MOSI = LCD_MOSI
try:
    with open("openbuddy-board.txt") as handle:
        BOARD_MODEL = handle.read(64).strip()
except OSError:
    pass
if BOARD_MODEL == "waveshare-s3-amoled-164-v2":
    DISPLAY_DRIVER = "co5300"
    LCD_SCLK, LCD_MOSI, LCD_CS, LCD_RST = 10, 11, 46, 21
    LCD_SPI_BAUD = 40_000_000
    LCD_DC = LCD_BL = RGB_LED = None
    BOOT_BUTTON = 0
    SD_SPI_ID = 2
    SD_SCLK, SD_MOSI, SD_MISO, SD_CS = 41, 39, 40, 38
    PANEL_SHORT, PANEL_LONG, RAM_SHORT_OFFSET = 280, 456, 20
    # Fill the physical panel in landscape; keep the 96x104 pack unchanged.
    UI_WIDTH, UI_HEIGHT = 456, 280
    UI_PET_SCALE = 2
    UI_PET_STAGE = (8, 36, 208, 208)
    UI_TEXT_X, UI_LINK_X = 228, 344
    UI_HEADER_Y, UI_STATE_Y, UI_DETAIL_Y, UI_INFO_Y = 24, 82, 132, 174
    UI_DIVIDER_Y, UI_FOOTER_Y = 256, 264
    UI_CHOICE_HOLD_RECT = (UI_TEXT_X - 4, UI_DETAIL_Y + 70,
                           UI_WIDTH - UI_TEXT_X + 4, 32)
    PET_STORAGE = "internal"
    PET_DIRECTORY = "/openbuddy/pets"
    PET_SELECTION = "/openbuddy/active.json"
    # Only a verified pet installation switches the v2 storage preference.
    try:
        with open("openbuddy-storage.txt") as handle:
            storage = handle.read(16).strip()
        if storage in ("internal", "sd"):
            PET_STORAGE = storage
    except OSError:
        pass
    if PET_STORAGE == "sd":
        PET_DIRECTORY = SD_MOUNT + "/openbuddy/pets"
        PET_SELECTION = SD_MOUNT + "/openbuddy/active.json"
    AUTO_ORIENTATION = True
    IMU_I2C_ID = 0
    IMU_SDA, IMU_SCL = 47, 48
    IMU_I2C_FREQ = 300_000
    IMU_ADDRESS = 0x6B
    # Measured upright: USB-C left => Y positive; USB-C right => Y negative.
    IMU_LANDSCAPE_AXIS = 1
    IMU_LANDSCAPE_SIGN = -1
    TOUCH_ADDRESS = 0x38
elif BOARD_MODEL != "waveshare-c6-lcd-147":
    raise ValueError("Unknown OpenBuddy board profile: " + BOARD_MODEL)
