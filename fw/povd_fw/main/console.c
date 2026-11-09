// console on the USB port. Every config key is a command: "<key>" prints it, "<key> <value>" sets it.
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "esp_console.h"
#include "esp_system.h"
#include "sdkconfig.h"
#include "povd.h"

const char *render_pattern_names(void);
bool render_pattern_valid(const char *name);

int povd_set(const char *key, const char *val, char *msg, int msg_size)
{
    msg[0] = 0;
    if (!strcmp(key, "buck") && val) {
        buck_set(atoi(val) != 0);
        printf("buck %d\n", buck_get());
        return 0;
    }
    if (!strcmp(key, "time") && val) {
        int h = 0, m = 0, s = 0;
        if (sscanf(val, "%d:%d:%d", &h, &m, &s) < 2) { snprintf(msg, msg_size, "time hh:mm[:ss]"); return -2; }
        clock_set(h, m, s);
        render();
        return 0;
    }
    if (val && !strcmp(key, "pattern") && !render_pattern_valid(val)) {
        snprintf(msg, msg_size, "patterns: %s", render_pattern_names());
        return -2;
    }
    bool reconf = false;
    int r = config_set(key, val, &reconf);
    if (r == -1) { snprintf(msg, msg_size, "unknown key %s", key); return r; }
    if (r == -2) { snprintf(msg, msg_size, "bad value for %s", key); return r; }
    if (!val) return 0;
    if (!strncmp(key, "wifi_", 5) || !strcmp(key, "hostname")) wifi_start();
    else if (reconf) leds_reconfigure();
    else render();
    angle_sim_update();
    return 0;
}

static int cmd_key(int argc, char **argv)
{
    char msg[96];
    if (povd_set(argv[0], argc > 1 ? argv[1] : NULL, msg, sizeof(msg))) { printf("%s\n", msg); return 1; }
    return 0;
}

static int cmd_wifi(int argc, char **argv)
{
    if (argc >= 2) {
        snprintf(cfg.wifi_ssid, sizeof(cfg.wifi_ssid), "%s", argv[1]);
        snprintf(cfg.wifi_pass, sizeof(cfg.wifi_pass), "%s", argc >= 3 ? argv[2] : "");
        config_save();
        wifi_start();
        printf("saved; joining \"%s\"\n", cfg.wifi_ssid);
    } else if (argc == 1) {
        wifi_print();
    }
    return 0;
}

static int cmd_show(int argc, char **argv) { config_print(); return 0; }

static int cmd_save(int argc, char **argv)
{
    printf(config_save() ? "saved\n" : "save failed\n");
    return 0;
}

static int cmd_defaults(int argc, char **argv)
{
    config_defaults();
    leds_reconfigure();
    printf("defaults loaded (not saved)\n");
    return 0;
}

static int cmd_buck(int argc, char **argv)
{
    char msg[96];
    if (argc > 1) povd_set("buck", argv[1], msg, sizeof(msg));
    else printf("buck %d\n", buck_get());
    return 0;
}

static int cmd_i(int argc, char **argv)
{
    printf("I_IN %d mV\n", i_in_mv());
    return 0;
}

static int cmd_uart(int argc, char **argv)
{
    printf(uart_loopback() ? "OPT_TX -> OPT_RX loopback ok\n" : "loopback failed (jumper TP16 to TP17?)\n");
    return 0;
}

static int cmd_time(int argc, char **argv)
{
    char msg[96];
    if (povd_set("time", argc > 1 ? argv[1] : "", msg, sizeof(msg))) { printf("%s\n", msg); return 1; }
    return 0;
}

static int cmd_status(int argc, char **argv) { status_print(); return 0; }

static int cmd_view(int argc, char **argv) { render_view(); return 0; }

static int cmd_restart(int argc, char **argv) { esp_restart(); return 0; }

static void reg(const char *name, const char *help, int (*fn)(int, char **))
{
    esp_console_cmd_t c = {.command = name, .help = help, .hint = NULL, .func = fn};
    ESP_ERROR_CHECK(esp_console_cmd_register(&c));
}

void console_start(void)
{
    esp_console_repl_t *repl = NULL;
    esp_console_repl_config_t rc = ESP_CONSOLE_REPL_CONFIG_DEFAULT();
    rc.prompt = "povd>";
    rc.max_cmdline_length = 128;
#if CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG
    esp_console_dev_usb_serial_jtag_config_t hc = ESP_CONSOLE_DEV_USB_SERIAL_JTAG_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_console_new_repl_usb_serial_jtag(&hc, &rc, &repl));
#else   // QEMU build: console on UART0
    esp_console_dev_uart_config_t hc = ESP_CONSOLE_DEV_UART_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_console_new_repl_uart(&hc, &rc, &repl));
#endif

    int n;
    const char *const *keys = config_keys(&n);
    for (int i = 0; i < n; i++) reg(keys[i], "config key: '<key>' prints, '<key> <value>' sets", cmd_key);
    reg("show", "print all config keys", cmd_show);
    reg("save", "store the config in flash", cmd_save);
    reg("defaults", "load default config (not saved)", cmd_defaults);
    reg("buck", "buck [0|1]: 5 V / 15 A strip supply off/on", cmd_buck);
    reg("i", "read I_IN (INA240 output) in mV", cmd_i);
    reg("uart", "OPT_TX -> OPT_RX loopback test", cmd_uart);
    reg("time", "time hh:mm[:ss] for pattern clock", cmd_time);
    reg("status", "rpm, sync, output timing, buck, current, wifi", cmd_status);
    reg("view", "print the rendered image (blade 1, strip 1) as colour blocks", cmd_view);
    reg("wifi", "wifi: show; wifi <ssid> [password]: join and save (quote names with spaces)", cmd_wifi);
    reg("restart", "reboot", cmd_restart);
    esp_console_register_help_command();
    ESP_ERROR_CHECK(esp_console_start_repl(repl));
}
