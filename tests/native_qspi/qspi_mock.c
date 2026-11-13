#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include "py/runtime.h"
#include "py/gc.h"
#include "driver/spi_master.h"
#include "driver/gpio.h"
#include "esp_heap_caps.h"

// Build with real MicroPython v1.29.0, replacing only the hardware APIs.
#define CHECK(condition) do { if (!(condition)) { \
    fprintf(stderr, "QSPI check failed: %s (%s:%d)\n", #condition, __FILE__, __LINE__); \
    abort(); \
} } while (0)

static struct {
    bool bus, device, acquired, external, cs_low;
    void *dma;
    int failure, calls, releases, removes, frees, gpio_calls;
    int command;
    bool quad;
    size_t length, offset;
    uint8_t expected[40000];
} mock;

static void check_exit(void) {
    // Reproduce ESP32 main.c's soft-reset hook; minimal unix omits this hook.
    gc_sweep_all();
    CHECK(!mock.bus && !mock.device && !mock.acquired && mock.dma == NULL && !mock.cs_low);
}

void *heap_caps_malloc(size_t size, uint32_t caps) {
    CHECK(size == 4092);
    CHECK(caps == (MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
    if (mock.failure == 1) {
        return NULL;
    }
    // A second constructor must not replace the first object's allocation.
    void *p = malloc(size);
    if (mock.dma == NULL) {
        mock.dma = p;
    }
    return p;
}

void heap_caps_free(void *p) {
    CHECK(p != NULL);
    if (p == mock.dma) {
        mock.dma = NULL;
    }
    free(p);
}

esp_err_t spi_bus_initialize(int host, const spi_bus_config_t *c, int dma) {
    CHECK(host == SPI2_HOST && dma == SPI_DMA_CH_AUTO);
    CHECK(c->sclk_io_num == 10 && c->mosi_io_num == 11 && c->miso_io_num == 12);
    CHECK(c->quadwp_io_num == 13 && c->quadhd_io_num == 14);
    CHECK(c->data4_io_num == -1 && c->data5_io_num == -1);
    CHECK(c->data6_io_num == -1 && c->data7_io_num == -1);
    CHECK(c->max_transfer_sz == 4092);
    CHECK(c->flags == (SPICOMMON_BUSFLAG_MASTER | SPICOMMON_BUSFLAG_QUAD));
    if (mock.bus || mock.failure == 2) {
        return ESP_ERR_INVALID_STATE;
    }
    mock.bus = true;
    return ESP_OK;
}

esp_err_t spi_bus_add_device(int host, const spi_device_interface_config_t *c, spi_device_handle_t *device) {
    CHECK(host == SPI2_HOST && mock.bus && !mock.device);
    CHECK(c->command_bits == 8 && c->address_bits == 24 && c->dummy_bits == 0);
    CHECK(c->mode == 0 && c->clock_speed_hz > 0);
    CHECK(c->spics_io_num == 9 && c->queue_size == 1 && c->flags == SPI_DEVICE_HALFDUPLEX);
    if (mock.failure == 3) {
        return ESP_ERR_NO_MEM;
    }
    mock.device = true;
    *device = (spi_device_handle_t)&mock;
    return ESP_OK;
}

esp_err_t spi_bus_remove_device(spi_device_handle_t device) {
    CHECK(device == (spi_device_handle_t)&mock && mock.device && !mock.acquired);
    if (mock.failure == 10) {
        return ESP_ERR_INVALID_STATE;
    }
    mock.removes++;
    mock.device = false;
    return ESP_OK;
}

esp_err_t spi_bus_free(int host) {
    CHECK(host == SPI2_HOST && mock.bus && !mock.device && !mock.acquired && !mock.external);
    if (mock.failure == 11) {
        return ESP_ERR_INVALID_STATE;
    }
    mock.frees++;
    mock.bus = false;
    return ESP_OK;
}

esp_err_t spi_device_acquire_bus(spi_device_handle_t device, uint32_t wait) {
    CHECK(device == (spi_device_handle_t)&mock && mock.device && !mock.acquired);
    CHECK(wait == portMAX_DELAY);
    if (mock.failure == 4) {
        return ESP_ERR_INVALID_STATE;
    }
    mock.acquired = true;
    return ESP_OK;
}

void spi_device_release_bus(spi_device_handle_t device) {
    CHECK(device == (spi_device_handle_t)&mock && mock.acquired);
    mock.acquired = false;
    mock.releases++;
}

esp_err_t spi_device_polling_transmit(spi_device_handle_t device, spi_transaction_t *t) {
    CHECK(device == (spi_device_handle_t)&mock && mock.acquired);
    spi_transaction_ext_t *ext = (spi_transaction_ext_t *)t;
    size_t count = mock.length - mock.offset;
    if (count > 4092) {
        count = 4092;
    }
    uint32_t flags = SPI_TRANS_VARIABLE_CMD | SPI_TRANS_VARIABLE_ADDR;
    if (mock.quad) {
        flags |= SPI_TRANS_MODE_QIO;
    }
    if (mock.offset + count < mock.length) {
        flags |= SPI_TRANS_CS_KEEP_ACTIVE;
    }
    CHECK(t->flags == flags && t->length == count * 8);
    CHECK(t->rx_buffer == NULL && t->rxlength == 0);
    CHECK(ext->dummy_bits == 0);
    if (mock.offset == 0) {
        CHECK(!mock.cs_low);
        CHECK(ext->command_bits == 8 && ext->address_bits == 24);
        CHECK(t->cmd == (mock.quad ? 0x32 : 0x02));
        CHECK(t->addr == (uint32_t)mock.command << 8);
    } else {
        CHECK(mock.cs_low);
        CHECK(ext->command_bits == 0 && ext->address_bits == 0);
        CHECK(t->cmd == 0 && t->addr == 0);
    }
    if (count) {
        CHECK(t->tx_buffer == mock.dma);
        CHECK(memcmp(t->tx_buffer, mock.expected + mock.offset, count) == 0);
    } else {
        CHECK(t->tx_buffer == NULL);
    }
    mock.calls++;
    if (mock.failure == mock.calls + 4) {
        return ESP_ERR_INVALID_STATE;
    }
    mock.cs_low = (flags & SPI_TRANS_CS_KEEP_ACTIVE) != 0;
    mock.offset += count;
    return ESP_OK;
}

int gpio_reset_pin(int pin) {
    CHECK(pin == 9 && !mock.device && !mock.external);
    mock.gpio_calls++;
    return ESP_OK;
}
int gpio_set_level(int pin, int level) {
    CHECK(pin == 9 && level == 1 && !mock.external);
    mock.cs_low = false;
    return ESP_OK;
}
int gpio_set_direction(int pin, int mode) {
    CHECK(pin == 9 && mode == GPIO_MODE_OUTPUT && !mock.external);
    return ESP_OK;
}

static mp_obj_t test_configure(size_t n_args, const mp_obj_t *args) {
    static bool registered_exit;
    if (!registered_exit) {
        CHECK(atexit(check_exit) == 0);
        registered_exit = true;
    }
    CHECK(!mock.bus && !mock.device && !mock.acquired && mock.dma == NULL);
    memset(&mock, 0, sizeof(mock));
    mock.command = mp_obj_get_int(args[0]);
    mp_buffer_info_t buffer;
    mp_get_buffer_raise(args[1], &buffer, MP_BUFFER_READ);
    CHECK(buffer.len <= sizeof(mock.expected));
    mock.length = buffer.len;
    if (buffer.len) {
        memcpy(mock.expected, buffer.buf, buffer.len);
    }
    mock.quad = mp_obj_is_true(args[2]);
    mock.failure = mp_obj_get_int(args[3]);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(test_configure_obj, 4, 4, test_configure);

static mp_obj_t test_failure(mp_obj_t failure) {
    mock.failure = mp_obj_get_int(failure);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(test_failure_obj, test_failure);

static mp_obj_t test_external(mp_obj_t enabled) {
    CHECK(!mock.device && !mock.acquired && mock.dma == NULL);
    mock.bus = mock.external = mp_obj_is_true(enabled);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(test_external_obj, test_external);

static mp_obj_t test_check(mp_obj_t successful) {
    CHECK(!mock.device && !mock.acquired && mock.dma == NULL && !mock.cs_low);
    CHECK(mock.bus == mock.external);
    if (mp_obj_is_true(successful)) {
        CHECK(mock.offset == mock.length);
        CHECK((size_t)mock.calls == (mock.length ? (mock.length + 4091) / 4092 : 1));
        CHECK(mock.releases == 1 && mock.removes == 1 && mock.frees == 1);
    }
    if (mock.external) {
        CHECK(mock.frees == 0 && mock.removes == 0 && mock.gpio_calls == 0);
    }
    if (mock.failure >= 1 && mock.failure <= 7) {
        CHECK(mock.releases == (mock.failure >= 5 ? 1 : 0));
        CHECK(mock.removes == (mock.failure >= 4 ? 1 : 0));
        CHECK(mock.frees == (mock.failure >= 3 ? 1 : 0));
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(test_check_obj, test_check);

static const mp_rom_map_elem_t test_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR__qspi_test) },
    { MP_ROM_QSTR(MP_QSTR_configure), MP_ROM_PTR(&test_configure_obj) },
    { MP_ROM_QSTR(MP_QSTR_failure), MP_ROM_PTR(&test_failure_obj) },
    { MP_ROM_QSTR(MP_QSTR_external), MP_ROM_PTR(&test_external_obj) },
    { MP_ROM_QSTR(MP_QSTR_check), MP_ROM_PTR(&test_check_obj) },
};
static MP_DEFINE_CONST_DICT(test_globals, test_globals_table);
const mp_obj_module_t qspi_test_module = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&test_globals,
};
MP_REGISTER_MODULE(MP_QSTR__qspi_test, qspi_test_module);
