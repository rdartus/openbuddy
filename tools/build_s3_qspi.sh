#!/usr/bin/env bash
# ESP-IDF 5.5.2 must already be installed and exported in this shell.
set -euo pipefail
ROOT=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
MP=$(realpath "${1:?Usage: bash tools/build_s3_qspi.sh /path/to/micropython}")
test "$(git -C "$MP" rev-parse HEAD)" = "0fd6c573ea815774668bbb16b8e197c8822368b2"
test "$(git -C "${IDF_PATH:?Export ESP-IDF first}" rev-parse HEAD)" = "30aaf64524299d3bde422ca9a2848090d1bc5d0f"
idf.py --version
make -C "$MP/mpy-cross" -j2
BOARD_DIR="$ROOT/firmware/boards/OPENBUDDY_S3_AMOLED_V2"
make -C "$MP/ports/esp32" submodules BOARD_DIR="$BOARD_DIR"
make -C "$MP/ports/esp32" BOARD_DIR="$BOARD_DIR" \
  USER_C_MODULES="$ROOT/firmware/amoled_qspi/micropython.cmake"
python "$ROOT/tools/package_s3_firmware.py" --micropython "$MP" --idf "$IDF_PATH"
