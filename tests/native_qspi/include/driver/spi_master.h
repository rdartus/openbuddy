// Host-only subset of the public ESP-IDF 5.5.2 API. No hardware implementation.
#ifndef QSPI_TEST_SPI_MASTER_H
#define QSPI_TEST_SPI_MASTER_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef int esp_err_t;
#define ESP_OK 0
#define ESP_ERR_NO_MEM 0x101
#define ESP_ERR_INVALID_ARG 0x102
#define ESP_ERR_INVALID_STATE 0x103
#define SPI2_HOST 1
#define SPI_DMA_CH_AUTO 3
#define portMAX_DELAY UINT32_MAX
#define SPICOMMON_BUSFLAG_MASTER (1 << 0)
#define SPICOMMON_BUSFLAG_QUAD ((1 << 6) | (1 << 7))
#define SPI_DEVICE_HALFDUPLEX (1 << 4)
#define SPI_TRANS_MODE_QIO (1 << 1)
#define SPI_TRANS_VARIABLE_CMD (1 << 5)
#define SPI_TRANS_VARIABLE_ADDR (1 << 6)
#define SPI_TRANS_CS_KEEP_ACTIVE (1 << 8)

typedef struct {
    int mosi_io_num, miso_io_num, sclk_io_num, quadwp_io_num, quadhd_io_num;
    int data4_io_num, data5_io_num, data6_io_num, data7_io_num;
    bool data_io_default_level;
    int max_transfer_sz;
    uint32_t flags;
} spi_bus_config_t;
typedef struct {
    uint8_t command_bits, address_bits, dummy_bits, mode;
    int clock_speed_hz, spics_io_num;
    uint32_t flags;
    int queue_size;
} spi_device_interface_config_t;
typedef struct {
    uint32_t flags;
    uint16_t cmd;
    uint64_t addr;
    size_t length, rxlength;
    uint32_t override_freq_hz;
    void *user;
    union { const void *tx_buffer; uint8_t tx_data[4]; };
    union { void *rx_buffer; uint8_t rx_data[4]; };
} spi_transaction_t;
typedef struct {
    spi_transaction_t base;
    uint8_t command_bits, address_bits, dummy_bits;
} spi_transaction_ext_t;
typedef struct spi_device_t *spi_device_handle_t;
esp_err_t spi_bus_initialize(int host, const spi_bus_config_t *config, int dma);
esp_err_t spi_bus_add_device(int host, const spi_device_interface_config_t *config, spi_device_handle_t *device);
esp_err_t spi_bus_remove_device(spi_device_handle_t device);
esp_err_t spi_bus_free(int host);
esp_err_t spi_device_acquire_bus(spi_device_handle_t device, uint32_t wait);
void spi_device_release_bus(spi_device_handle_t device);
esp_err_t spi_device_polling_transmit(spi_device_handle_t device, spi_transaction_t *transaction);
#endif
