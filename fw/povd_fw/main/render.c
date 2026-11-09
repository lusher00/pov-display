// patterns, rendered straight into polar form
//
// For each column and channel: the channel's blade angle is the column angle plus
// blade * 360 / blades (+ phase_deg, sign flipped by mirror). LED i of strip k on a blade sits at
// r = r0_mm + (i + k / strips_per_blade) * led_pitch_mm, so extra strips on a blade fill in
// between the first strip's LEDs (radial interleave). Channels beyond blades * strips_per_blade
// are left dark.
#include <math.h>
#include <string.h>
#include <stdlib.h>
#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_timer.h"
#include "povd.h"

typedef struct { uint8_t r, g, b; } rgb_t;

static int64_t clock_base_s;          // seconds since midnight at clock_t0
static int64_t clock_t0_us;

void clock_set(int h, int m, int s)
{
    clock_base_s = h * 3600 + m * 60 + s;
    clock_t0_us = esp_timer_get_time();
}

static rgb_t hsv(float h, float s, float v)
{
    h = fmodf(h, 360.0f);
    if (h < 0) h += 360.0f;
    float c = v * s, x = c * (1 - fabsf(fmodf(h / 60.0f, 2) - 1)), m = v - c;
    float r, g, b;
    if (h < 60)       { r = c; g = x; b = 0; }
    else if (h < 120) { r = x; g = c; b = 0; }
    else if (h < 180) { r = 0; g = c; b = x; }
    else if (h < 240) { r = 0; g = x; b = c; }
    else if (h < 300) { r = x; g = 0; b = c; }
    else              { r = c; g = 0; b = x; }
    rgb_t o = {(uint8_t)((r + m) * 255), (uint8_t)((g + m) * 255), (uint8_t)((b + m) * 255)};
    return o;
}

static const rgb_t BLACK = {0, 0, 0}, WHITE = {255, 255, 255}, RED = {255, 0, 0};

// angular distance in degrees, 0..180
static float adist(float a, float b)
{
    float d = fmodf(fabsf(a - b), 360.0f);
    return d > 180 ? 360 - d : d;
}

// hand from the centre at angle a (degrees clockwise from 12), length len (fraction of R)
static bool hand(float th, float r, float R, float a, float len, float width_mm)
{
    if (r > len * R) return false;
    float d = adist(th, a) * (float)M_PI / 180.0f * r;   // arc distance from the hand line
    return d < width_mm;
}

typedef struct {
    int pat;
    float R, pitch, col_deg;
    rgb_t solid;
    float hh, mm, ss;
} ctx_t;

enum { P_OFF, P_INDEX, P_CHAN, P_RINGS, P_SPOKES, P_GRID, P_WHEEL, P_SOLID, P_CLOCK };
static const char *PNAMES[] = {"off", "index", "chan", "rings", "spokes", "grid", "wheel", "solid", "clock"};

static int pattern_id(const char *s)
{
    for (int i = 0; i < (int)(sizeof(PNAMES) / sizeof(PNAMES[0])); i++)
        if (!strcmp(s, PNAMES[i])) return i;
    return -1;
}

bool render_pattern_valid(const char *name) { return pattern_id(name) >= 0; }

const char *render_pattern_names(void) { return "off index chan rings spokes grid wheel solid clock"; }

static rgb_t pixel(const ctx_t *c, int ch, int led, float th, float r)
{
    switch (c->pat) {
    case P_INDEX:   // one radial line at angle 0: use it to set phase_deg
        return adist(th, 0) < c->col_deg ? WHITE : BLACK;
    case P_CHAN: {  // channel n lights its first n LEDs, own colour, at every angle
        return led <= ch ? hsv(ch * 45.0f, 1, 1) : BLACK;
    }
    case P_RINGS: {
        int band = (int)(r / 40.0f);
        return hsv(band * 50.0f, 1, 1);
    }
    case P_SPOKES:
        if (r > c->R - 1.5f * c->pitch) return WHITE;
        if (fmodf(th + 360.0f, 30.0f) < c->col_deg * 1.5f) return WHITE;
        return BLACK;
    case P_GRID: {
        float a = th * (float)M_PI / 180.0f;
        float x = r * sinf(a), y = r * cosf(a);
        float g = 100.0f, w = c->pitch * 0.6f;
        float fx = fabsf(fmodf(fabsf(x) + g / 2, g) - g / 2), fy = fabsf(fmodf(fabsf(y) + g / 2, g) - g / 2);
        if (fabsf(x) < w) return (rgb_t){0, 255, 0};
        if (fabsf(y) < w) return (rgb_t){255, 0, 0};
        if (fx < w || fy < w) return WHITE;
        return BLACK;
    }
    case P_WHEEL:
        return hsv(th, 1, 1);
    case P_SOLID:
        return c->solid;
    case P_CLOCK: {
        if (r > c->R - 2.5f * c->pitch && fmodf(th + 360.0f + 1.0f, 30.0f) < 2.0f) return WHITE;   // hour ticks
        if (hand(th, r, c->R, c->ss * 6.0f, 0.95f, c->pitch * 0.5f)) return RED;
        if (hand(th, r, c->R, c->mm * 6.0f, 0.85f, c->pitch * 0.8f)) return WHITE;
        if (hand(th, r, c->R, c->hh * 30.0f, 0.55f, c->pitch * 1.2f)) return WHITE;
        return BLACK;
    }
    default:
        return BLACK;
    }
}

static void parse_color(const char *s, rgb_t *o)
{
    unsigned v = (unsigned)strtoul(s, NULL, 16);
    o->r = v >> 16; o->g = v >> 8; o->b = v;
}

void render(void)
{
    uint64_t *pix = leds_pixels();
    if (!pix) return;
    int cols = cfg.columns_per_rev, n = cfg.leds_per_strip, spb = cfg.strips_per_blade;
    int used = cfg.blades * spb;
    if (used > NUM_CH) used = NUM_CH;
    ctx_t c = {0};
    c.pat = pattern_id(cfg.pattern);
    c.pitch = cfg.led_pitch_mm;
    c.R = cfg.r0_mm + n * cfg.led_pitch_mm;
    c.col_deg = 360.0f / cols;
    parse_color(cfg.color, &c.solid);
    if (c.pat == P_CLOCK) {
        int64_t t = clock_base_s + (esp_timer_get_time() - clock_t0_us) / 1000000;
        c.ss = (float)(t % 60);
        c.mm = (float)((t / 60) % 60) + c.ss / 60.0f;
        c.hh = (float)((t / 3600) % 12) + c.mm / 60.0f;
    }
    uint8_t hdr = 0xE0 | (cfg.bright & 31);
    int sb = 4 * n;
    for (int col = 0; col < cols; col++) {
        uint8_t *dst = (uint8_t *)(pix + (size_t)col * sb);     // [k][ch] bytes
        float col_th = (col + 0.5f) * 360.0f / cols;
        for (int ch = 0; ch < NUM_CH; ch++) {
            if (ch >= used) {
                for (int i = 0; i < n; i++) {
                    dst[(4 * i) * 8 + ch] = 0xE0;
                    dst[(4 * i + 1) * 8 + ch] = dst[(4 * i + 2) * 8 + ch] = dst[(4 * i + 3) * 8 + ch] = 0;
                }
                continue;
            }
            int blade = ch / spb, k = ch % spb;
            float th = col_th + blade * 360.0f / cfg.blades + cfg.phase_deg;
            if (cfg.mirror) th = -th;
            th = fmodf(th, 360.0f);
            if (th < 0) th += 360.0f;
            for (int i = 0; i < n; i++) {
                int ri = cfg.strip_rev ? n - 1 - i : i;              // i = position in the chain
                float r = cfg.r0_mm + (ri + (float)k / spb) * cfg.led_pitch_mm;
                rgb_t p = c.pat < 0 ? BLACK : pixel(&c, ch, ri, th, r);
                dst[(4 * i) * 8 + ch] = hdr;
                dst[(4 * i + 1) * 8 + ch] = p.b;
                dst[(4 * i + 2) * 8 + ch] = p.g;
                dst[(4 * i + 3) * 8 + ch] = p.r;
            }
        }
    }
}

static void render_task(void *arg)
{
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(200));
        static int64_t last_s = -1;
        if (strcmp(cfg.pattern, "clock")) continue;
        int64_t s = (esp_timer_get_time() - clock_t0_us) / 1000000;
        if (s != last_s) { last_s = s; render(); }
    }
}

void render_task_start(void)
{
    xTaskCreatePinnedToCore(render_task, "render", 4096, NULL, 2, NULL, 0);
}

// Print the image as the rotor would show it, sampled from blade 1 strip 1 (channel 1) on a
// square grid, two characters per cell, 24-bit ANSI colour. Inverts the mapping used by render().
void render_view(void)
{
    uint64_t *pix = leds_pixels();
    if (!pix) return;
    int cols = cfg.columns_per_rev, n = cfg.leds_per_strip;
    float R = cfg.r0_mm + n * cfg.led_pitch_mm;
    const int G = 33;                                   // cells across
    for (int y = 0; y < G; y++) {
        for (int x = 0; x < G; x++) {
            float px = ((x + 0.5f) / G * 2 - 1) * R, py = (1 - (y + 0.5f) / G * 2) * R;
            float r = sqrtf(px * px + py * py);
            float th = atan2f(px, py) * 180.0f / (float)M_PI;   // clockwise from 12 o'clock
            int i = (int)floorf((r - cfg.r0_mm) / cfg.led_pitch_mm + 0.5f);
            if (r > R || i < 0 || i >= n) { printf("\x1b[0m  "); continue; }
            float col_th = (cfg.mirror ? -th : th) - cfg.phase_deg;
            col_th = fmodf(col_th, 360.0f);
            if (col_th < 0) col_th += 360.0f;
            int col = (int)(col_th / 360.0f * cols) % cols;
            int pos = cfg.strip_rev ? n - 1 - i : i;              // position in the chain
            const uint8_t *src = (const uint8_t *)(pix + (size_t)col * 4 * n);
            uint8_t b = src[(4 * pos + 1) * 8], g = src[(4 * pos + 2) * 8], rr = src[(4 * pos + 3) * 8];
            printf("\x1b[48;2;%d;%d;%dm  ", rr, g, b);
        }
        printf("\x1b[0m\n");
    }
}
