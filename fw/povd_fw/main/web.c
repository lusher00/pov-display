// web page and JSON API on port 80
//
//   GET  /             the page (main/index.html, embedded at build time)
//   GET  /api/config   all config keys except wifi_pass: [{k, t, v, lo, hi}, ...]
//   GET  /api/status   {rpm, synced, ...}
//   POST /api/set      body k=<key>&v=<value>; also k=buck, k=time
//   POST /api/save     store the config in flash
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include <ctype.h>
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "esp_http_server.h"
#include "esp_log.h"
#include "povd.h"

extern const char index_html_start[] asm("_binary_index_html_start");
extern const char index_html_end[] asm("_binary_index_html_end");

static httpd_handle_t server;
static char jbuf[4096];
static SemaphoreHandle_t lock;

static void url_decode(char *s)
{
    char *o = s;
    for (; *s; s++) {
        if (*s == '+') *o++ = ' ';
        else if (*s == '%' && isxdigit((unsigned char)s[1]) && isxdigit((unsigned char)s[2])) {
            char h[3] = {s[1], s[2], 0};
            *o++ = (char)strtol(h, NULL, 16);
            s += 2;
        } else *o++ = *s;
    }
    *o = 0;
}

static esp_err_t send_json(httpd_req_t *r, int (*fn)(char *, int))
{
    xSemaphoreTake(lock, portMAX_DELAY);
    int n = fn(jbuf, sizeof(jbuf));
    httpd_resp_set_type(r, "application/json");
    httpd_resp_set_hdr(r, "Cache-Control", "no-store");
    esp_err_t e = httpd_resp_send(r, jbuf, n);
    xSemaphoreGive(lock);
    return e;
}

static esp_err_t h_index(httpd_req_t *r)
{
    httpd_resp_set_type(r, "text/html");
    return httpd_resp_send(r, index_html_start, index_html_end - index_html_start - 1);
}

static esp_err_t h_config(httpd_req_t *r) { return send_json(r, config_json); }
static esp_err_t h_status(httpd_req_t *r) { return send_json(r, status_json); }

static esp_err_t h_set(httpd_req_t *r)
{
    char body[256] = {0}, k[40] = {0}, v[160] = {0};
    int len = r->content_len < (int)sizeof(body) - 1 ? r->content_len : (int)sizeof(body) - 1;
    int got = 0;
    while (got < len) {
        int n = httpd_req_recv(r, body + got, len - got);
        if (n <= 0) return ESP_FAIL;
        got += n;
    }
    if (httpd_query_key_value(body, "k", k, sizeof(k)) != ESP_OK) {
        httpd_resp_send_err(r, HTTPD_400_BAD_REQUEST, "missing k");
        return ESP_FAIL;
    }
    httpd_query_key_value(body, "v", v, sizeof(v));
    url_decode(k);
    url_decode(v);
    char msg[96];
    int res = povd_set(k, v, msg, sizeof(msg));
    if (res) {
        httpd_resp_set_status(r, "400 Bad Request");
        return httpd_resp_sendstr(r, msg);
    }
    return httpd_resp_sendstr(r, "ok");
}

static esp_err_t h_save(httpd_req_t *r)
{
    return httpd_resp_sendstr(r, config_save() ? "saved" : "save failed");
}

void web_start(void)
{
    if (server) return;
    lock = xSemaphoreCreateMutex();
    httpd_config_t c = HTTPD_DEFAULT_CONFIG();
    c.core_id = 0;                       // core 1 belongs to the strip output
    c.stack_size = 8192;
    if (httpd_start(&server, &c) != ESP_OK) { server = NULL; return; }
    httpd_uri_t u[] = {
        {.uri = "/", .method = HTTP_GET, .handler = h_index},
        {.uri = "/api/config", .method = HTTP_GET, .handler = h_config},
        {.uri = "/api/status", .method = HTTP_GET, .handler = h_status},
        {.uri = "/api/set", .method = HTTP_POST, .handler = h_set},
        {.uri = "/api/save", .method = HTTP_POST, .handler = h_save},
    };
    for (int i = 0; i < (int)(sizeof(u) / sizeof(u[0])); i++) httpd_register_uri_handler(server, &u[i]);
}
