// strip output: LCD_CAM in i80 mode, 8-bit bus, DMA
//
// Each bus byte carries one bit for each of the 8 strips (D0 = channel 1 ... D7 = channel 8) and
// one PCLK edge clocks all 8 strips together. One column is a complete SK9822 frame on every
// channel: 4 zero bytes, 4 bytes per LED (0xE0|bright, B, G, R), then zero bytes for the end frame.
// Each frame byte becomes 8 bus bytes (MSB first), so a column is 8 x frame-length bus bytes.
//
// The rendered image lives in PSRAM as [column][frame byte k] = 64-bit word holding that byte for
// all 8 channels. The output task transposes one column into an internal DMA buffer and starts the
// transfer whenever the rotor angle reaches a new column.
#include <string.h>
#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_lcd_panel_io.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "esp_log.h"
#include "sdkconfig.h"
#include "povd.h"

static const char *TAG = "leds";

static esp_lcd_i80_bus_handle_t bus;
static esp_lcd_panel_io_handle_t io;
static uint64_t *pix;                 // PSRAM image
static int pix_cols, pix_leds;
static uint8_t *dma_buf[2];           // internal RAM, one column each
static uint8_t *blank_buf;
static int frame_bytes, bus_bytes;    // SK9822 frame length, and x8 on the bus (padded)
static volatile bool inflight;
static volatile bool pause_req, paused;

// stats
static volatile uint32_t st_cols, st_skipped, st_busy;

#if !CONFIG_POVD_QEMU
static bool IRAM_ATTR on_done(esp_lcd_panel_io_handle_t h, esp_lcd_panel_io_event_data_t *e, void *ctx)
{
    inflight = false;
    return false;
}
#endif

static inline void tr8(uint64_t x, uint8_t *o)
{
    // 8x8 bit transpose: byte c of x is channel c; o[j] bit c = bit (7-j) of channel c
    uint64_t t;
    t = (x ^ (x >> 7)) & 0x00AA00AA00AA00AAULL;  x ^= t ^ (t << 7);
    t = (x ^ (x >> 14)) & 0x0000CCCC0000CCCCULL; x ^= t ^ (t << 14);
    t = (x ^ (x >> 28)) & 0x00000000F0F0F0F0ULL; x ^= t ^ (t << 28);
    for (int j = 0; j < 8; j++) o[j] = (uint8_t)(x >> (8 * (7 - j)));
}

int leds_stream_bytes(void) { return 4 * pix_leds; }
uint64_t *leds_pixels(void) { return pix; }

static void build_column(int col, uint8_t *out)
{
    const uint64_t *src = pix + (size_t)col * 4 * pix_leds;
    uint8_t *o = out + 4 * 8;                       // after the zero start frame
    for (int k = 0; k < 4 * pix_leds; k++, o += 8) tr8(src[k], o);
}

static void free_all(void)
{
    if (io) { esp_lcd_panel_io_del(io); io = NULL; }
    if (bus) { esp_lcd_del_i80_bus(bus); bus = NULL; }
    for (int i = 0; i < 2; i++) { heap_caps_free(dma_buf[i]); dma_buf[i] = NULL; }
    heap_caps_free(blank_buf); blank_buf = NULL;
    heap_caps_free(pix); pix = NULL;
}

static void setup_all(void)
{
    pix_cols = cfg.columns_per_rev;
    pix_leds = cfg.leds_per_strip;
    int end_bytes = 4 + (pix_leds + 15) / 16;       // SK9822: >= n/2 extra clocks after the data
    frame_bytes = 4 + 4 * pix_leds + end_bytes;
    bus_bytes = (frame_bytes * 8 + 63) & ~63;       // pad with zeros to the DMA alignment

#if !CONFIG_POVD_QEMU    // QEMU has no LCD_CAM model: columns are built but not sent
    esp_lcd_i80_bus_config_t bc;
    memset(&bc, 0, sizeof(bc));
    bc.dc_gpio_num = PIN_DC;
    bc.wr_gpio_num = PIN_PCLK;
    bc.clk_src = LCD_CLK_SRC_DEFAULT;
    for (int i = 0; i < 8; i++) bc.data_gpio_nums[i] = PIN_D0 + i;   // IO6..IO13
    bc.bus_width = 8;
    bc.max_transfer_bytes = bus_bytes;
    ESP_ERROR_CHECK(esp_lcd_new_i80_bus(&bc, &bus));

    esp_lcd_panel_io_i80_config_t ic;
    memset(&ic, 0, sizeof(ic));
    ic.cs_gpio_num = -1;
    ic.pclk_hz = (uint32_t)(cfg.clk_mhz * 1e6f);
    ic.trans_queue_depth = 2;
    ic.on_color_trans_done = on_done;
    ic.lcd_cmd_bits = 0;                            // no command phase: data only
    ic.lcd_param_bits = 8;
    ic.flags.pclk_idle_low = 1;                     // SK9822 latches on the rising edge
    ESP_ERROR_CHECK(esp_lcd_new_panel_io_i80(bus, &ic, &io));
#endif

    for (int i = 0; i < 2; i++) {
        dma_buf[i] = heap_caps_aligned_calloc(64, 1, bus_bytes, MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL);
        assert(dma_buf[i]);
    }
    blank_buf = heap_caps_aligned_calloc(64, 1, bus_bytes, MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL);
    assert(blank_buf);
    // blank frame: every LED 0xE0 (brightness 0), colour 0
    for (int k = 0; k < pix_leds; k++) tr8(0xE0E0E0E0E0E0E0E0ULL, blank_buf + (4 + 4 * k) * 8);

    size_t psz = (size_t)pix_cols * 4 * pix_leds * sizeof(uint64_t);
    pix = heap_caps_calloc(1, psz, MALLOC_CAP_SPIRAM);
    if (!pix) pix = heap_caps_calloc(1, psz, MALLOC_CAP_8BIT);
    if (!pix) {
        ESP_LOGE(TAG, "no memory for %d columns x %d LEDs (%u bytes): lower columns_per_rev", pix_cols, pix_leds, (unsigned)psz);
        abort();
    }
    ESP_LOGI(TAG, "bus %.1f MHz, %d bus bytes/column (%.0f us), image %u bytes",
             cfg.clk_mhz, bus_bytes, bus_bytes / cfg.clk_mhz, (unsigned)psz);
}

static void send(uint8_t *buf)
{
#if CONFIG_POVD_QEMU
    (void)buf;
#else
    inflight = true;
    esp_lcd_panel_io_tx_color(io, -1, buf, bus_bytes);
#endif
}

static void output_task(void *arg)
{
    int last = -1, pp = 0;
    bool blanked = false;
    angle_t a;
    for (;;) {
        if (pause_req) {
            while (inflight) {}
            paused = true;
            while (pause_req) vTaskDelay(1);
            paused = false;
            last = -1;
            blanked = false;
            continue;
        }
        angle_get(&a);
        if (!a.valid) {
            if (!blanked && !inflight) { send(blank_buf); blanked = true; }
            last = -1;
            vTaskDelay(1);
            continue;
        }
        blanked = false;
        int col = (int)(a.frac * pix_cols);
        if (col >= pix_cols) col = pix_cols - 1;
        if (col == last) continue;
        if (inflight) { st_busy++; continue; }
        build_column(col, dma_buf[pp]);
        send(dma_buf[pp]);
        pp ^= 1;
        if (last >= 0 && col != (last + 1) % pix_cols) st_skipped++;
        last = col;
        st_cols++;
    }
}

void leds_init(void)
{
    setup_all();
    // core 1, top priority, never blocks while displaying
    xTaskCreatePinnedToCore(output_task, "leds", 4096, NULL, configMAX_PRIORITIES - 1, NULL, 1);
}

void leds_reconfigure(void)
{
    pause_req = true;
    while (!paused) vTaskDelay(1);
    free_all();
    setup_all();
    render();
    pause_req = false;
}

void leds_counters(uint32_t *cols, uint32_t *skipped)
{
    *cols = st_cols;
    *skipped = st_skipped;
}

float leds_t_column_us(void) { return bus_bytes / cfg.clk_mhz; }
