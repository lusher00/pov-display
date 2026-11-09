idf_component_register(SRCS "main.c" "config.c" "angle.c" "leds.c" "render.c" "console.c" "board.c"
                            "status.c" "wifi.c" "web.c"
                       INCLUDE_DIRS "."
                       EMBED_TXTFILES "index.html"
                       REQUIRES esp_lcd esp_timer esp_driver_gpio esp_driver_uart nvs_flash console esp_adc
                                esp_psram esp_wifi esp_netif esp_event esp_http_server mdns)
