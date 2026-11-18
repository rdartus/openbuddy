QSPI_TEST_DIR := $(USERMOD_DIR)
SRC_USERMOD += $(QSPI_TEST_DIR)/../../firmware/amoled_qspi/amoled_qspi.c
SRC_USERMOD += $(QSPI_TEST_DIR)/qspi_mock.c
CFLAGS_USERMOD += -I$(QSPI_TEST_DIR)/include -DCONFIG_IDF_TARGET_ESP32S3=1
