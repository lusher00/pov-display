// buck enable, current sense ADC, optical-link UART
#include <string.h>
#include "driver/gpio.h"
#include "driver/uart.h"
#include "esp_adc/adc_oneshot.h"
#include "esp_adc/adc_cali.h"
#include "esp_adc/adc_cali_scheme.h"
#include "sdkconfig.h"
#include "povd.h"

#if !CONFIG_POVD_QEMU     // the ADC's startup calibration never finishes in QEMU
static adc_oneshot_unit_handle_t adc;
static adc_cali_handle_t cali;
#endif
static bool buck_on;

void buck_set(bool on)
{
    gpio_set_level(PIN_BUCK_EN, on);
    buck_on = on;
}

bool buck_get(void) { return buck_on; }

void board_init(void)
{
    gpio_config_t io = {
        .pin_bit_mask = 1ULL << PIN_BUCK_EN,
        .mode = GPIO_MODE_OUTPUT,
    };
    gpio_set_level(PIN_BUCK_EN, 0);
    gpio_config(&io);
    buck_set(false);

#if !CONFIG_POVD_QEMU
    adc_oneshot_unit_init_cfg_t uc = {.unit_id = ADC_UNIT_1};
    adc_oneshot_new_unit(&uc, &adc);
    adc_oneshot_chan_cfg_t cc = {.atten = ADC_ATTEN_DB_12, .bitwidth = ADC_BITWIDTH_DEFAULT};
    adc_oneshot_config_channel(adc, ADC_CHANNEL_0, &cc);              // IO1
    adc_cali_curve_fitting_config_t kc = {.unit_id = ADC_UNIT_1, .chan = ADC_CHANNEL_0,
                                          .atten = ADC_ATTEN_DB_12, .bitwidth = ADC_BITWIDTH_DEFAULT};
    if (adc_cali_create_scheme_curve_fitting(&kc, &cali) != ESP_OK) cali = NULL;
#endif

#if CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG   // in the QEMU build UART0 on these pins is the console
    uart_config_t u = {
        .baud_rate = 115200,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    uart_driver_install(UART_NUM_1, 256, 0, 0, NULL, 0);
    uart_param_config(UART_NUM_1, &u);
    uart_set_pin(UART_NUM_1, PIN_OPT_TX, PIN_OPT_RX, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE);
#endif
}

int i_in_mv(void)
{
#if CONFIG_POVD_QEMU
    return 0;
#else
    int sum = 0;
    for (int i = 0; i < 16; i++) {
        int raw = 0, mv = 0;
        adc_oneshot_read(adc, ADC_CHANNEL_0, &raw);
        if (cali) adc_cali_raw_to_voltage(cali, raw, &mv);
        else mv = raw * 3100 / 4095;
        sum += mv;
    }
    return sum / 16;
#endif
}

bool uart_loopback(void)
{
#if !CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG
    return false;
#endif
    const char *msg = "povd-loopback";
    uint8_t buf[32] = {0};
    uart_flush_input(UART_NUM_1);
    uart_write_bytes(UART_NUM_1, msg, strlen(msg));
    int n = uart_read_bytes(UART_NUM_1, buf, strlen(msg), pdMS_TO_TICKS(100));
    return n == (int)strlen(msg) && !memcmp(buf, msg, n);
}
