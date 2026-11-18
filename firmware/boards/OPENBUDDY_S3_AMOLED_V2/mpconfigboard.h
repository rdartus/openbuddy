#define MICROPY_HW_BOARD_NAME "OpenBuddy Waveshare S3 AMOLED 1.64 v2"
#define MICROPY_HW_MCU_NAME "ESP32-S3"
#define MICROPY_HW_ENABLE_UART_REPL (1)
// Keep the ROM USB Serial/JTAG device instead of switching the shared PHY to OTG.
// This board does not need runtime USB devices; CDC via TinyUSB changes its USB identity.
#define MICROPY_HW_ENABLE_USBDEV (0)
#define MICROPY_HW_USB_CDC (0)
#define MICROPY_HW_ESP_USB_SERIAL_JTAG (1)
#define MICROPY_HW_I2C0_SCL (48)
#define MICROPY_HW_I2C0_SDA (47)
