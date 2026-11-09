// WiFi station on the home network, and mDNS so the page is at http://<hostname>.local
#include <string.h>
#include <stdio.h>
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_log.h"
#include "mdns.h"
#include "povd.h"

static const char *TAG = "wifi";
static esp_netif_t *netif;
static bool inited, started;
static char ip_str[20] = "off";
static int retries;

static void on_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        strcpy(ip_str, "not connected");
        if (!cfg.wifi_ssid[0]) return;
        retries++;
        if (retries == 5) ESP_LOGW(TAG, "can't join \"%s\"; still retrying (check wifi_ssid / wifi_pass)", cfg.wifi_ssid);
        esp_wifi_connect();
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *e = (ip_event_got_ip_t *)data;
        snprintf(ip_str, sizeof(ip_str), IPSTR, IP2STR(&e->ip_info.ip));
        retries = 0;
        printf("\nwifi: joined \"%s\", http://%s  or  http://%s.local\n", cfg.wifi_ssid, ip_str, cfg.hostname);
    }
}

const char *wifi_ip(void) { return ip_str; }

void wifi_print(void)
{
    printf("wifi_ssid         %s\n", cfg.wifi_ssid[0] ? cfg.wifi_ssid : "(not set: wifi off)");
    printf("ip                %s\n", ip_str);
    if (cfg.wifi_ssid[0]) printf("page              http://%s.local\n", cfg.hostname);
}

void wifi_start(void)
{
    if (!inited) {
        esp_netif_init();
        esp_event_loop_create_default();
        netif = esp_netif_create_default_wifi_sta();
        wifi_init_config_t wc = WIFI_INIT_CONFIG_DEFAULT();
        esp_wifi_init(&wc);
        esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, on_event, NULL);
        esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, on_event, NULL);
        esp_wifi_set_mode(WIFI_MODE_STA);
        mdns_init();
        mdns_service_add(NULL, "_http", "_tcp", 80, NULL, 0);
        inited = true;
    }
    if (started) { esp_wifi_disconnect(); esp_wifi_stop(); started = false; }
    strcpy(ip_str, "off");
    if (!cfg.wifi_ssid[0]) return;

    esp_netif_set_hostname(netif, cfg.hostname);
    mdns_hostname_set(cfg.hostname);
    mdns_instance_name_set("povd rotor");

    wifi_config_t w;
    memset(&w, 0, sizeof(w));
    strncpy((char *)w.sta.ssid, cfg.wifi_ssid, sizeof(w.sta.ssid));
    strncpy((char *)w.sta.password, cfg.wifi_pass, sizeof(w.sta.password));
    w.sta.threshold.authmode = cfg.wifi_pass[0] ? WIFI_AUTH_WPA2_PSK : WIFI_AUTH_OPEN;
    esp_wifi_set_config(WIFI_IF_STA, &w);
    strcpy(ip_str, "connecting");
    retries = 0;
    esp_wifi_start();
    started = true;
}
