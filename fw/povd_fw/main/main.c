// povd hub firmware, first light
#include <stdio.h>
#include "nvs_flash.h"
#include "sdkconfig.h"
#include "povd.h"

void app_main(void)
{
    board_init();                      // BUCK_EN low first
    esp_err_t e = nvs_flash_init();
    if (e == ESP_ERR_NVS_NO_FREE_PAGES || e == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        nvs_flash_erase();
        nvs_flash_init();
    }
    config_load();
    angle_init();
    leds_init();
    render();
    render_task_start();
    if (cfg.buck_boot) buck_set(true);
#if !CONFIG_POVD_QEMU
    wifi_start();
    web_start();
#endif
    printf("\npovd hub firmware. 'help' lists commands, 'show' the config. buck is %s.\n",
           buck_get() ? "on" : "off");
    if (!cfg.wifi_ssid[0]) printf("wifi is off: wifi \"<ssid>\" \"<password>\" to join your network\n");
    console_start();
}
