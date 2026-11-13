# Usage: make -f tests/native_qspi/Makefile MICROPYTHON=/path/to/micropython
# Requires the unmodified MicroPython v1.29.0 source tree and a host C compiler.
ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
MICROPYTHON ?= /tmp/opencode/qspi-micropython
BUILD ?= build-native-qspi
FEATURES := -DMICROPY_PY_BUILTINS_MEMORYVIEW=1 -DMICROPY_PY_BUILTINS_BYTEARRAY=1 -DMICROPY_PY_ARRAY=1 -DMICROPY_FLOAT_IMPL=MICROPY_FLOAT_IMPL_DOUBLE -DMICROPY_PY_GC=1

.PHONY: test build
test: build
	$(MICROPYTHON)/ports/unix/$(BUILD)/micropython $(ROOT)/tests/native_qspi/test_qspi.py

build:
	$(MAKE) -C $(MICROPYTHON)/ports/unix VARIANT=minimal BUILD=$(BUILD) USER_C_MODULES=$(ROOT)/tests CFLAGS_EXTRA='$(FEATURES)' -j4
