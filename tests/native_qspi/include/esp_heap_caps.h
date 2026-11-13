#ifndef QSPI_TEST_HEAP_H
#define QSPI_TEST_HEAP_H
#include <stddef.h>
#include <stdint.h>
#define MALLOC_CAP_DMA (1 << 3)
#define MALLOC_CAP_INTERNAL (1 << 11)
#define MALLOC_CAP_8BIT (1 << 2)
void *heap_caps_malloc(size_t size, uint32_t caps);
void heap_caps_free(void *pointer);
#endif
