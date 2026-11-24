#ifndef QSPI_TEST_GPIO_H
#define QSPI_TEST_GPIO_H
#define GPIO_MODE_OUTPUT 2
int gpio_reset_pin(int pin);
int gpio_set_level(int pin, int level);
int gpio_set_direction(int pin, int mode);
#endif
