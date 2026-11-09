// povd hub firmware: shared definitions
#pragma once
#include <stdint.h>
#include <stdbool.h>

// ---- pins (povd-hub.kicad_pcb, U5 Waveshare ESP32-S3-Zero) ----
#define PIN_I_IN      1    // INA240 output, ADC1 channel 0
#define PIN_ENC_B     2
#define PIN_ENC_A     3
#define PIN_BUCK_EN   4    // high = 5 V / 15 A buck on
#define PIN_PCLK      5    // shared strip clock (LCD_CAM WR)
#define PIN_D0        6    // LCD_D0..D6 = IO6..IO12, LCD_D7 = IO13
#define PIN_DC        14   // i80 driver needs a D/C pin; IO14 is not connected on the hub
#define PIN_OPT_TX    43
#define PIN_OPT_RX    44

#define NUM_CH        8    // strip outputs: D0 -> DAT1 ... D7 -> DAT8
#define MAX_LEDS      256  // per channel (strips chained on one output count together)
#define MAX_COLS      1440

// ---- config: every field is a console key with the same name ----
typedef struct {
    int   blades;            // blades on the rotor, equally spaced
    int   strips_per_blade;  // channel c is blade c / strips_per_blade, strip c % strips_per_blade
    int   leds_per_strip;    // LEDs on one channel
    float led_pitch_mm;      // LED spacing along the strip
    float r0_mm;             // radius of the first LED in the chain
    int   strip_rev;         // 1 = chain starts at the tip
    int   columns_per_rev;   // angular resolution
    float clk_mhz;           // strip clock
    int   slots;             // pulse positions per rev on ENC_A (1 = one index pulse)
    int   missing;           // 1 = one position has no magnet: the pulse after the gap is angle 0
    float phase_deg;         // rotates the image
    int   mirror;            // 1 = flip rotation sense
    int   bright;            // SK9822 global brightness 0..31
    char  pattern[16];       // off index chan rings spokes grid wheel solid clock
    char  color[8];          // RRGGBB for pattern solid
    int   buck_boot;         // 1 = turn the 5 V buck on at boot
    float sim_rpm;           // >0: generate ENC_A pulses internally at this rpm (bench and QEMU)
    char  wifi_ssid[33];     // network to join; empty = WiFi off
    char  wifi_pass[65];
    char  hostname[32];      // mDNS name: http://<hostname>.local
} povd_config_t;

extern povd_config_t cfg;

// config.c
void config_defaults(void);
void config_load(void);
bool config_save(void);
void config_print(void);
// returns 0 ok, -1 unknown key, -2 bad value; *reconf set when the bus/buffers must be rebuilt
int  config_set(const char *key, const char *val, bool *reconf);
const char *const *config_keys(int *n);
int  config_json(char *buf, int size);          // all keys except wifi_pass, with type and range

// angle.c
typedef struct {
    bool     valid;      // rotor turning and (if missing=1) index seen
    float    frac;       // 0..1 angle since index
    float    rpm;
    uint32_t revs;
    uint32_t enc_a_edges, enc_b_edges;
} angle_t;
void angle_init(void);
void angle_get(angle_t *a);
void angle_sim_update(void);       // start/stop the internal pulse generator from cfg.sim_rpm

// leds.c
void leds_init(void);
void leds_reconfigure(void);       // pause output, rebuild bus and buffers, resume
uint64_t *leds_pixels(void);       // [col][byte k of the LED stream] -> 8 channel bytes
int  leds_stream_bytes(void);      // 4 * leds_per_strip
void leds_counters(uint32_t *cols, uint32_t *skipped);   // cumulative
float leds_t_column_us(void);

// render.c
void render(void);                 // fill leds_pixels() from cfg.pattern
void render_task_start(void);
void render_view(void);            // print the rendered image as colour blocks
void clock_set(int h, int m, int s);

// board.c
void board_init(void);
void buck_set(bool on);
bool buck_get(void);
int  i_in_mv(void);
bool uart_loopback(void);

// wifi.c, web.c
void wifi_start(void);                         // (re)connect with cfg.wifi_ssid / wifi_pass
void wifi_print(void);
const char *wifi_ip(void);
void web_start(void);
int  status_json(char *buf, int size);

// console.c
void console_start(void);
// set a config key (or buck / time) and apply it; 0 ok, else msg says why. Used by console and web.
int  povd_set(const char *key, const char *val, char *msg, int msg_size);
void status_print(void);
