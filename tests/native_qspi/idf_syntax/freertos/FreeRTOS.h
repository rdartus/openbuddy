// Scheduling is not compiled in a host syntax-only check.
#include <stdint.h>
typedef uint32_t TickType_t;
#define portMAX_DELAY UINT32_MAX
