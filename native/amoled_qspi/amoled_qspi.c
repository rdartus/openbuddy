#include <string.h>
#include <stdint.h>

#include "py/runtime.h"
#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "esp_heap_caps.h"

#if !CONFIG_IDF_TARGET_ESP32S3
#error "amoled_qspi requires ESP32-S3"
#endif
#if !MICROPY_ENABLE_FINALISER
#error "amoled_qspi requires native finalisers"
#endif

#define QSPI_BLOCK_SIZE (4092)
#define QSPI_CS (9)
#define PANEL_WIDTH (280)
#define PANEL_HEIGHT (456)
#define CANVAS_WIDTH (320)
#define CANVAS_HEIGHT (172)
#define CANVAS_X (54)
#define CANVAS_Y (68)
// Match the Waveshare v2 demo; leave SPI3 available for the separate SD bus.
#define QSPI_HOST SPI2_HOST

typedef struct {
    mp_obj_base_t base;
    spi_device_handle_t device;
    uint8_t *dma;
    int cs;
    bool owns_bus;
    bool closed;
} amoled_qspi_bus_t;

// No queued work and no GIL release: all DMA has finished before cleanup.
static esp_err_t amoled_qspi_cleanup(amoled_qspi_bus_t *self) {
    esp_err_t result = ESP_OK;
    self->closed = true;
    if (self->dma != NULL) {
        heap_caps_free(self->dma);
        self->dma = NULL;
    }
    if (self->device != NULL) {
        esp_err_t err = spi_bus_remove_device(self->device);
        if (err != ESP_OK) {
            return err; // Retain ownership so explicit deinit can be retried.
        }
        self->device = NULL;
        // Also terminate a stream whose last successful block kept CS active.
        result = gpio_reset_pin(self->cs);
        err = gpio_set_level(self->cs, 1);
        if (result == ESP_OK) {
            result = err;
        }
        err = gpio_set_direction(self->cs, GPIO_MODE_OUTPUT);
        if (result == ESP_OK) {
            result = err;
        }
    }
    if (self->owns_bus) {
        esp_err_t err = spi_bus_free(QSPI_HOST);
        if (err != ESP_OK) {
            return err;
        }
        self->owns_bus = false;
    }
    return result;
}

static void amoled_qspi_raise(esp_err_t err) {
    mp_raise_msg_varg(&mp_type_OSError, MP_ERROR_TEXT("amoled_qspi ESP-IDF error 0x%x"), (unsigned int)err);
}

static mp_obj_t amoled_qspi_make_new(const mp_obj_type_t *type, size_t n_args,
    size_t n_kw, const mp_obj_t *all_args) {
    static const mp_arg_t allowed[] = {
        { MP_QSTR_baudrate, MP_ARG_INT, {.u_int = 10000000} },
        { MP_QSTR_cs, MP_ARG_KW_ONLY | MP_ARG_INT, {.u_int = QSPI_CS} },
    };
    mp_arg_val_t args[MP_ARRAY_SIZE(allowed)];
    mp_arg_parse_all_kw_array(n_args, n_kw, all_args, MP_ARRAY_SIZE(allowed), allowed, args);
    if (args[0].u_int <= 0 || args[0].u_int > 80000000) {
        mp_raise_ValueError(MP_ERROR_TEXT("baudrate must be 1..80000000"));
    }
    // Restrict selection to the legacy and vendor-v2 OpenBuddy profiles.
    if (args[1].u_int != 9 && args[1].u_int != 46) {
        mp_raise_ValueError(MP_ERROR_TEXT("cs must be 9 (legacy) or 46 (v2)"));
    }

    amoled_qspi_bus_t *self = mp_obj_malloc_with_finaliser(amoled_qspi_bus_t, type);
    self->device = NULL;
    self->dma = NULL;
    self->cs = args[1].u_int;
    self->owns_bus = false;
    self->closed = true;
    self->dma = heap_caps_malloc(QSPI_BLOCK_SIZE, MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    if (self->dma == NULL) {
        mp_raise_msg(&mp_type_MemoryError, MP_ERROR_TEXT("QSPI DMA buffer"));
    }

    const spi_bus_config_t bus_config = {
        .sclk_io_num = 10,
        .mosi_io_num = 11,
        .miso_io_num = 12,
        .quadwp_io_num = 13,
        .quadhd_io_num = 14,
        .data4_io_num = -1,
        .data5_io_num = -1,
        .data6_io_num = -1,
        .data7_io_num = -1,
        .max_transfer_sz = QSPI_BLOCK_SIZE,
        .flags = SPICOMMON_BUSFLAG_MASTER | SPICOMMON_BUSFLAG_QUAD,
    };
    esp_err_t err = spi_bus_initialize(QSPI_HOST, &bus_config, SPI_DMA_CH_AUTO);
    if (err == ESP_OK) {
        self->owns_bus = true;
        const spi_device_interface_config_t device_config = {
            .command_bits = 8,
            .address_bits = 24,
            .clock_speed_hz = args[0].u_int,
            .mode = 0,
            .spics_io_num = self->cs,
            .queue_size = 1,
            .flags = SPI_DEVICE_HALFDUPLEX,
        };
        err = spi_bus_add_device(QSPI_HOST, &device_config, &self->device);
    }
    if (err != ESP_OK) {
        amoled_qspi_cleanup(self);
        amoled_qspi_raise(err);
    }
    self->closed = false;
    return MP_OBJ_FROM_PTR(self);
}

static mp_obj_t amoled_qspi_write(size_t n_args, const mp_obj_t *pos_args, mp_map_t *kw_args) {
    static const mp_arg_t allowed[] = {
        { MP_QSTR_command, MP_ARG_REQUIRED | MP_ARG_OBJ, {.u_obj = MP_OBJ_NULL} },
        { MP_QSTR_data, MP_ARG_OBJ, {.u_obj = mp_const_none} },
        { MP_QSTR_quad, MP_ARG_BOOL, {.u_bool = false} },
    };
    mp_arg_val_t args[MP_ARRAY_SIZE(allowed)];
    mp_arg_parse_all(n_args - 1, pos_args + 1, kw_args, MP_ARRAY_SIZE(allowed), allowed, args);
    if (!mp_obj_is_int(args[0].u_obj)) {
        mp_raise_TypeError(MP_ERROR_TEXT("command must be an int"));
    }
    mp_int_t command = mp_obj_get_int(args[0].u_obj);
    if (command < 0 || command > 255) {
        mp_raise_ValueError(MP_ERROR_TEXT("command must be 0..255"));
    }
    mp_buffer_info_t buffer = {0};
    if (args[1].u_obj != mp_const_none) {
        mp_get_buffer_raise(args[1].u_obj, &buffer, MP_BUFFER_READ);
    }
    amoled_qspi_bus_t *self = MP_OBJ_TO_PTR(pos_args[0]);
    if (self->closed) {
        mp_raise_msg(&mp_type_OSError, MP_ERROR_TEXT("QSPI bus is deinitialized"));
    }

    esp_err_t err = spi_device_acquire_bus(self->device, portMAX_DELAY);
    if (err == ESP_OK) {
        size_t offset = 0;
        do {
            size_t count = buffer.len - offset;
            if (count > QSPI_BLOCK_SIZE) {
                count = QSPI_BLOCK_SIZE;
            }
            spi_transaction_ext_t transaction = {0};
            transaction.base.flags = SPI_TRANS_VARIABLE_CMD | SPI_TRANS_VARIABLE_ADDR;
            if (args[2].u_bool) {
                transaction.base.flags |= SPI_TRANS_MODE_QIO;
            }
            // Opcode and address always use one lane, including quad writes.
            if (offset == 0) {
                transaction.command_bits = 8;
                transaction.address_bits = 24;
                transaction.base.cmd = args[2].u_bool ? 0x32 : 0x02;
                transaction.base.addr = (uint32_t)command << 8;
            }
            if (offset + count < buffer.len) {
                transaction.base.flags |= SPI_TRANS_CS_KEEP_ACTIVE;
            }
            if (count != 0) {
                memcpy(self->dma, (const uint8_t *)buffer.buf + offset, count);
                transaction.base.tx_buffer = self->dma;
                transaction.base.length = count * 8;
            }
            err = spi_device_polling_transmit(self->device, &transaction.base);
            if (err != ESP_OK) {
                break;
            }
            offset += count;
        } while (offset < buffer.len);
        spi_device_release_bus(self->device);
    }
    if (err != ESP_OK) {
        amoled_qspi_cleanup(self);
        amoled_qspi_raise(err);
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_KW(amoled_qspi_write_obj, 1, amoled_qspi_write);

static void amoled_qspi_check_open(mp_obj_t bus) {
    amoled_qspi_bus_t *self = MP_OBJ_TO_PTR(bus);
    if (self->closed) {
        mp_raise_msg(&mp_type_OSError, MP_ERROR_TEXT("QSPI bus is deinitialized"));
    }
}

static void amoled_qspi_check_rect(mp_int_t x, mp_int_t y, mp_int_t w, mp_int_t h,
    int max_w, int max_h) {
    if (x < 0 || y < 0 || w <= 0 || h <= 0 || x >= max_w || y >= max_h ||
        w > max_w - x || h > max_h - y) {
        mp_raise_ValueError(MP_ERROR_TEXT("Invalid QSPI rectangle"));
    }
}

static mp_buffer_info_t amoled_qspi_shadow(mp_obj_t object) {
    mp_buffer_info_t shadow;
    mp_get_buffer_raise(object, &shadow, MP_BUFFER_WRITE);
    if (shadow.len != PANEL_WIDTH * PANEL_HEIGHT * 2) {
        mp_raise_ValueError(MP_ERROR_TEXT("Invalid QSPI shadow size"));
    }
    return shadow;
}

// All byte operations preserve RGB565 big-endian order in the PSRAM shadow.
static mp_obj_t amoled_qspi_fill_buffer(mp_obj_t bus, mp_obj_t shadow_in, mp_obj_t color_in) {
    amoled_qspi_check_open(bus);
    mp_buffer_info_t shadow = amoled_qspi_shadow(shadow_in);
    mp_int_t color = mp_obj_get_int(color_in);
    if (color < 0 || color > 0xffff) {
        mp_raise_ValueError(MP_ERROR_TEXT("Invalid RGB565 color"));
    }
    uint8_t *pixels = shadow.buf;
    for (size_t i = 0; i < shadow.len; i += 2) {
        pixels[i] = color >> 8;
        pixels[i + 1] = color;
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_3(amoled_qspi_fill_buffer_obj, amoled_qspi_fill_buffer);

static mp_obj_t amoled_qspi_fill_rect(size_t n_args, const mp_obj_t *args) {
    amoled_qspi_check_open(args[0]);
    mp_buffer_info_t shadow = amoled_qspi_shadow(args[1]);
    mp_int_t x = mp_obj_get_int(args[2]);
    mp_int_t y = mp_obj_get_int(args[3]);
    mp_int_t w = mp_obj_get_int(args[4]);
    mp_int_t h = mp_obj_get_int(args[5]);
    amoled_qspi_check_rect(x, y, w, h, PANEL_WIDTH, PANEL_HEIGHT);
    mp_int_t color = mp_obj_get_int(args[6]);
    if (color < 0 || color > 0xffff) {
        mp_raise_ValueError(MP_ERROR_TEXT("Invalid RGB565 color"));
    }
    uint8_t *pixels = shadow.buf;
    for (int row = y; row < y + h; row++) {
        size_t pos = ((size_t)row * PANEL_WIDTH + x) * 2;
        for (int col = 0; col < w; col++) {
            pixels[pos++] = color >> 8;
            pixels[pos++] = color;
        }
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(amoled_qspi_fill_rect_obj, 7, 7, amoled_qspi_fill_rect);

static mp_obj_t amoled_qspi_blit_rotated(size_t n_args, const mp_obj_t *args) {
    amoled_qspi_check_open(args[0]);
    mp_buffer_info_t shadow = amoled_qspi_shadow(args[1]);
    mp_buffer_info_t source;
    mp_get_buffer_raise(args[2], &source, MP_BUFFER_READ);
    mp_int_t x = mp_obj_get_int(args[3]);
    mp_int_t y = mp_obj_get_int(args[4]);
    mp_int_t w = mp_obj_get_int(args[5]);
    mp_int_t h = mp_obj_get_int(args[6]);
    amoled_qspi_check_rect(x, y, w, h, CANVAS_WIDTH, CANVAS_HEIGHT);
    if (source.len != (size_t)w * h * 2) {
        mp_raise_ValueError(MP_ERROR_TEXT("Invalid RGB565 source size"));
    }
    uintptr_t src = (uintptr_t)source.buf;
    uintptr_t dst = (uintptr_t)shadow.buf;
    if ((src <= dst && dst - src < source.len) ||
        (dst < src && src - dst < shadow.len)) {
        mp_raise_ValueError(MP_ERROR_TEXT("Overlapping RGB565 buffers"));
    }
    bool inverted = mp_obj_is_true(args[7]);
    const uint8_t *input = source.buf;
    uint8_t *pixels = shadow.buf;
    for (int row = 0; row < h; row++) {
        int px = inverted ? CANVAS_X + CANVAS_HEIGHT - 1 - y - row : CANVAS_X + y + row;
        for (int col = 0; col < w; col++) {
            int py = inverted ? CANVAS_Y + x + col : CANVAS_Y + CANVAS_WIDTH - 1 - x - col;
            size_t target = ((size_t)py * PANEL_WIDTH + px) * 2;
            size_t source_pos = ((size_t)row * w + col) * 2;
            pixels[target] = input[source_pos];
            pixels[target + 1] = input[source_pos + 1];
        }
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(amoled_qspi_blit_rotated_obj, 8, 8, amoled_qspi_blit_rotated);

static mp_obj_t amoled_qspi_pack_rect(size_t n_args, const mp_obj_t *args) {
    amoled_qspi_check_open(args[0]);
    mp_buffer_info_t shadow = amoled_qspi_shadow(args[1]);
    mp_buffer_info_t scratch;
    mp_get_buffer_raise(args[2], &scratch, MP_BUFFER_WRITE);
    mp_int_t x = mp_obj_get_int(args[3]);
    mp_int_t y = mp_obj_get_int(args[4]);
    mp_int_t w = mp_obj_get_int(args[5]);
    mp_int_t h = mp_obj_get_int(args[6]);
    amoled_qspi_check_rect(x, y, w, h, PANEL_WIDTH, PANEL_HEIGHT);
    if ((x | y | w | h) & 1 || scratch.len < (size_t)w * h * 2) {
        mp_raise_ValueError(MP_ERROR_TEXT("Invalid aligned QSPI buffer"));
    }
    // The scratch and shadow must not alias: row compaction would corrupt pixels.
    uintptr_t src = (uintptr_t)shadow.buf;
    uintptr_t dst = (uintptr_t)scratch.buf;
    if ((src <= dst && dst - src < shadow.len) ||
        (dst < src && src - dst < scratch.len)) {
        mp_raise_ValueError(MP_ERROR_TEXT("Overlapping QSPI buffers"));
    }
    size_t row_bytes = (size_t)w * 2;
    for (int row = 0; row < h; row++) {
        memcpy((uint8_t *)scratch.buf + (size_t)row * row_bytes,
            (const uint8_t *)shadow.buf + ((size_t)(y + row) * PANEL_WIDTH + x) * 2, row_bytes);
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(amoled_qspi_pack_rect_obj, 7, 7, amoled_qspi_pack_rect);

static mp_obj_t amoled_qspi_deinit(mp_obj_t self_in) {
    esp_err_t err = amoled_qspi_cleanup(MP_OBJ_TO_PTR(self_in));
    if (err != ESP_OK) {
        amoled_qspi_raise(err);
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(amoled_qspi_deinit_obj, amoled_qspi_deinit);

static mp_obj_t amoled_qspi_finalise(mp_obj_t self_in) {
    amoled_qspi_cleanup(MP_OBJ_TO_PTR(self_in));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(amoled_qspi_finalise_obj, amoled_qspi_finalise);

static const mp_rom_map_elem_t amoled_qspi_locals_table[] = {
    { MP_ROM_QSTR(MP_QSTR_write), MP_ROM_PTR(&amoled_qspi_write_obj) },
    { MP_ROM_QSTR(MP_QSTR_fill_buffer), MP_ROM_PTR(&amoled_qspi_fill_buffer_obj) },
    { MP_ROM_QSTR(MP_QSTR_fill_rect), MP_ROM_PTR(&amoled_qspi_fill_rect_obj) },
    { MP_ROM_QSTR(MP_QSTR_blit_rotated), MP_ROM_PTR(&amoled_qspi_blit_rotated_obj) },
    { MP_ROM_QSTR(MP_QSTR_pack_rect), MP_ROM_PTR(&amoled_qspi_pack_rect_obj) },
    { MP_ROM_QSTR(MP_QSTR_deinit), MP_ROM_PTR(&amoled_qspi_deinit_obj) },
    { MP_ROM_QSTR(MP_QSTR___del__), MP_ROM_PTR(&amoled_qspi_finalise_obj) },
};
static MP_DEFINE_CONST_DICT(amoled_qspi_locals, amoled_qspi_locals_table);

static MP_DEFINE_CONST_OBJ_TYPE(amoled_qspi_bus_type, MP_QSTR_Bus, MP_TYPE_FLAG_NONE,
    make_new, amoled_qspi_make_new, locals_dict, &amoled_qspi_locals);

static const mp_rom_map_elem_t amoled_qspi_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_amoled_qspi) },
    { MP_ROM_QSTR(MP_QSTR_Bus), MP_ROM_PTR(&amoled_qspi_bus_type) },
    { MP_ROM_QSTR(MP_QSTR_API_VERSION), MP_ROM_INT(3) },
};
static MP_DEFINE_CONST_DICT(amoled_qspi_globals, amoled_qspi_globals_table);

const mp_obj_module_t amoled_qspi_module = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&amoled_qspi_globals,
};
MP_REGISTER_MODULE(MP_QSTR_amoled_qspi, amoled_qspi_module);
