#!/bin/sh
# Parse production code against actual v5.5.2 public IDF headers and v1.29.0
# MicroPython headers. Only sdkconfig and FreeRTOS task types are host shims.
set -eu
: "${MICROPYTHON:?Set MICROPYTHON to the v1.29.0 source tree}"
: "${IDF_PATH:?Set IDF_PATH to the v5.5.2 source tree}"
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
BUILD=${BUILD:-build-native-qspi}
set --
for component in esp_driver_spi esp_driver_gpio esp_common esp_hw_support esp_system esp_rom heap hal soc; do
    set -- "$@" "-I$IDF_PATH/components/$component/include"
done
"${CC:-cc}" -fsyntax-only -std=gnu99 -Wall -Wextra -Werror -Wno-unused-parameter \
    -DCONFIG_IDF_TARGET_ESP32S3=1 -DUNIX \
    -DMICROPY_PY_BUILTINS_MEMORYVIEW=1 -DMICROPY_PY_BUILTINS_BYTEARRAY=1 \
    -DMICROPY_PY_ARRAY=1 -DMICROPY_FLOAT_IMPL=MICROPY_FLOAT_IMPL_DOUBLE -DMICROPY_PY_GC=1 \
    -I"$ROOT/tests/native_qspi/idf_syntax" \
    -I"$MICROPYTHON" -I"$MICROPYTHON/ports/unix" \
    -I"$MICROPYTHON/ports/unix/variants/minimal" -I"$MICROPYTHON/ports/unix/$BUILD" \
    -I"$IDF_PATH/components/soc/esp32s3/include" \
    -I"$IDF_PATH/components/hal/esp32s3/include" \
    "$@" "$ROOT/native/amoled_qspi/amoled_qspi.c"
