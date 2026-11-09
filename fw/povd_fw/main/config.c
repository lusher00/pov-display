// config keys, defaults and NVS storage
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "nvs_flash.h"
#include "nvs.h"
#include "sdkconfig.h"
#include "povd.h"

povd_config_t cfg;

typedef enum { T_INT, T_FLOAT, T_STR } ktype_t;
typedef struct { const char *name; ktype_t t; void *p; int size; float lo, hi; bool reconf; } key_t_;

static const key_t_ KEYS[] = {
    {"blades",           T_INT,   &cfg.blades,           0, 1, 8,    false},
    {"strips_per_blade", T_INT,   &cfg.strips_per_blade, 0, 1, 8,    false},
    {"leds_per_strip",   T_INT,   &cfg.leds_per_strip,   0, 1, MAX_LEDS, true},
    {"led_pitch_mm",     T_FLOAT, &cfg.led_pitch_mm,     0, 0.5, 100, false},
    {"r0_mm",            T_FLOAT, &cfg.r0_mm,            0, 0, 2000, false},
    {"strip_rev",        T_INT,   &cfg.strip_rev,        0, 0, 1,    false},
    {"columns_per_rev",  T_INT,   &cfg.columns_per_rev,  0, 8, MAX_COLS, true},
    {"clk_mhz",          T_FLOAT, &cfg.clk_mhz,          0, 0.5, 40, true},
    {"slots",            T_INT,   &cfg.slots,            0, 1, 4096, false},
    {"missing",          T_INT,   &cfg.missing,          0, 0, 1,    false},
    {"phase_deg",        T_FLOAT, &cfg.phase_deg,        0, -360, 360, false},
    {"mirror",           T_INT,   &cfg.mirror,           0, 0, 1,    false},
    {"bright",           T_INT,   &cfg.bright,           0, 0, 31,   false},
    {"pattern",          T_STR,   cfg.pattern,           sizeof(cfg.pattern), 0, 0, false},
    {"color",            T_STR,   cfg.color,             sizeof(cfg.color), 0, 0, false},
    {"buck_boot",        T_INT,   &cfg.buck_boot,        0, 0, 1,    false},
    {"sim_rpm",          T_FLOAT, &cfg.sim_rpm,          0, 0, 5000, false},
    {"wifi_ssid",        T_STR,   cfg.wifi_ssid,         sizeof(cfg.wifi_ssid), 0, 0, false},
    {"wifi_pass",        T_STR,   cfg.wifi_pass,         sizeof(cfg.wifi_pass), 0, 0, false},
    {"hostname",         T_STR,   cfg.hostname,          sizeof(cfg.hostname), 0, 0, false},
};
#define NKEYS (int)(sizeof(KEYS) / sizeof(KEYS[0]))

static const char *NAMES[NKEYS + 1];

const char *const *config_keys(int *n)
{
    for (int i = 0; i < NKEYS; i++) NAMES[i] = KEYS[i].name;
    *n = NKEYS;
    return NAMES;
}

void config_defaults(void)
{
    memset(&cfg, 0, sizeof(cfg));
    cfg.blades = 4;
    cfg.strips_per_blade = 2;
    cfg.leds_per_strip = 62;
    cfg.led_pitch_mm = 8.06f;
    cfg.r0_mm = 100.0f;
    cfg.strip_rev = 0;
#if CONFIG_SPIRAM
    cfg.columns_per_rev = 360;
#else
    cfg.columns_per_rev = 90;        // QEMU build: no PSRAM, the image has to fit in internal RAM
#endif
    cfg.clk_mhz = 10.0f;
    cfg.slots = 1;
    cfg.missing = 0;
    cfg.phase_deg = 0;
    cfg.mirror = 0;
    cfg.bright = 3;
    strcpy(cfg.pattern, "index");
    strcpy(cfg.color, "ffffff");
    cfg.buck_boot = 0;
    strcpy(cfg.hostname, "povd");
}

void config_load(void)
{
    config_defaults();
    nvs_handle_t h;
    if (nvs_open("povd", NVS_READONLY, &h) != ESP_OK) return;
    povd_config_t tmp;
    size_t len = sizeof(tmp);
    if (nvs_get_blob(h, "cfg", &tmp, &len) == ESP_OK && len == sizeof(tmp)) cfg = tmp;
    else printf("stored config missing or from another version: using defaults\n");
    nvs_close(h);
}

bool config_save(void)
{
    nvs_handle_t h;
    if (nvs_open("povd", NVS_READWRITE, &h) != ESP_OK) return false;
    bool ok = nvs_set_blob(h, "cfg", &cfg, sizeof(cfg)) == ESP_OK && nvs_commit(h) == ESP_OK;
    nvs_close(h);
    return ok;
}

static void print_key(const key_t_ *k)
{
    switch (k->t) {
    case T_INT:   printf("%-17s %d\n", k->name, *(int *)k->p); break;
    case T_FLOAT: printf("%-17s %g\n", k->name, *(float *)k->p); break;
    case T_STR:
        if (!strcmp(k->name, "wifi_pass")) printf("%-17s %s\n", k->name, *(char *)k->p ? "(set)" : "");
        else printf("%-17s %s\n", k->name, (char *)k->p);
        break;
    }
}

void config_print(void)
{
    for (int i = 0; i < NKEYS; i++) print_key(&KEYS[i]);
}

int config_set(const char *key, const char *val, bool *reconf)
{
    for (int i = 0; i < NKEYS; i++) {
        const key_t_ *k = &KEYS[i];
        if (strcmp(k->name, key)) continue;
        if (!val) { print_key(k); return 0; }
        char *end;
        if (k->t == T_STR) {
            if (strlen(val) >= (size_t)k->size) return -2;
            strcpy((char *)k->p, val);
        } else {
            float v = strtof(val, &end);
            if (end == val || *end || v < k->lo || v > k->hi) return -2;
            if (k->t == T_INT) *(int *)k->p = (int)v;
            else *(float *)k->p = v;
        }
        if (reconf) *reconf = k->reconf;
        print_key(k);
        return 0;
    }
    return -1;
}

int config_json(char *buf, int size)
{
    int n = snprintf(buf, size, "[");
    for (int i = 0; i < NKEYS && n < size; i++) {
        const key_t_ *k = &KEYS[i];
        if (!strcmp(k->name, "wifi_pass")) continue;
        const char *sep = n > 1 ? "," : "";
        switch (k->t) {
        case T_INT:
            n += snprintf(buf + n, size - n, "%s{\"k\":\"%s\",\"t\":\"int\",\"v\":%d,\"lo\":%g,\"hi\":%g}",
                          sep, k->name, *(int *)k->p, k->lo, k->hi);
            break;
        case T_FLOAT:
            n += snprintf(buf + n, size - n, "%s{\"k\":\"%s\",\"t\":\"float\",\"v\":%g,\"lo\":%g,\"hi\":%g}",
                          sep, k->name, *(float *)k->p, k->lo, k->hi);
            break;
        case T_STR: {
            n += snprintf(buf + n, size - n, "%s{\"k\":\"%s\",\"t\":\"str\",\"v\":\"", sep, k->name);
            for (const char *c = (const char *)k->p; *c && n < size - 8; c++) {   // JSON-escape
                if (*c == '"' || *c == '\\') buf[n++] = '\\';
                if ((unsigned char)*c >= 0x20) buf[n++] = *c;
            }
            n += snprintf(buf + n, size - n, "\"}");
            break;
        }
        }
    }
    if (n < size) n += snprintf(buf + n, size - n, "]");
    return n;
}
