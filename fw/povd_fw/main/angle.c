// rotor angle from pulses on ENC_A
//
// slots = pulse positions per revolution. With missing = 1, one position has no magnet: the long
// gap is detected (period > 1.5 x the last slot period) and the pulse after it is angle 0, the
// same scheme as the 5-magnets-one-flipped pulley. With missing = 0 every pulse advances one slot
// and slot 0 is wherever counting started (slots = 1 is a single index pulse per rev).
// Between pulses the angle is extrapolated from the last slot period.
#include <string.h>
#include "driver/gpio.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "povd.h"

static portMUX_TYPE mux = portMUX_INITIALIZER_UNLOCKED;
static volatile int64_t  t_last;        // time of last pulse, us
static volatile int32_t  slot_us;       // period of one slot, us
static volatile int      slot;          // slot index of the last pulse
static volatile bool     synced;
static volatile uint32_t revs, edges_a, edges_b;

#define MIN_PERIOD_US 20                // ignore glitches closer than this

static void IRAM_ATTR pulse(int64_t now)
{
    portENTER_CRITICAL_ISR(&mux);
    int32_t dt = (int32_t)(now - t_last);
    if (dt >= MIN_PERIOD_US) {
        t_last = now;
        int slots = cfg.slots > 0 ? cfg.slots : 1;
        if (cfg.missing && slots > 1) {
            if (slot_us > 0 && dt > slot_us + slot_us / 2) {      // gap: this pulse is slot 0
                slot = 0;
                slot_us = dt / 2;
                synced = true;
                revs++;
            } else {
                slot_us = dt;
                if (++slot >= slots) slot = 0;                       // lost the gap; resync at next one
            }
        } else {
            slot_us = dt;
            if (++slot >= slots) { slot = 0; revs++; }
            synced = true;
        }
    }
    portEXIT_CRITICAL_ISR(&mux);
}

static void IRAM_ATTR isr_a(void *arg)
{
    edges_a++;
    if (cfg.sim_rpm <= 0) pulse(esp_timer_get_time());
}

// internal pulse generator: one call per slot, the missing slot skipped
static esp_timer_handle_t sim_timer;
static int sim_slot;

static void sim_cb(void *arg)
{
    int slots = cfg.slots > 0 ? cfg.slots : 1;
    if (++sim_slot >= slots) sim_slot = 0;
    if (cfg.missing && slots > 1 && sim_slot == slots - 1) return;
    portENTER_CRITICAL(&mux);
    edges_a++;
    portEXIT_CRITICAL(&mux);
    pulse(esp_timer_get_time());
}

void angle_sim_update(void)
{
    if (!sim_timer) {
        esp_timer_create_args_t a = {.callback = sim_cb, .name = "sim_rpm"};
        esp_timer_create(&a, &sim_timer);
    }
    esp_timer_stop(sim_timer);
    if (cfg.sim_rpm > 0) {
        int slots = cfg.slots > 0 ? cfg.slots : 1;
        uint64_t us = (uint64_t)(60e6f / cfg.sim_rpm / slots);
        esp_timer_start_periodic(sim_timer, us < 50 ? 50 : us);
    }
}

static void IRAM_ATTR isr_b(void *arg)
{
    edges_b++;
}

void angle_init(void)
{
    gpio_config_t io = {
        .pin_bit_mask = (1ULL << PIN_ENC_A) | (1ULL << PIN_ENC_B),
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,   // pull-ups are on the board (JP2)
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_NEGEDGE,      // hall switch pulls low at the magnet
    };
    gpio_config(&io);
    gpio_set_intr_type(PIN_ENC_B, GPIO_INTR_ANYEDGE);
    gpio_install_isr_service(ESP_INTR_FLAG_IRAM);
    gpio_isr_handler_add(PIN_ENC_A, isr_a, NULL);
    gpio_isr_handler_add(PIN_ENC_B, isr_b, NULL);
    angle_sim_update();
}

void angle_get(angle_t *a)
{
    int64_t now = esp_timer_get_time();
    portENTER_CRITICAL(&mux);
    int64_t tl = t_last;
    int32_t sp = slot_us;
    int s = slot;
    bool sy = synced;
    a->revs = revs;
    a->enc_a_edges = edges_a;
    a->enc_b_edges = edges_b;
    portEXIT_CRITICAL(&mux);

    int slots = cfg.slots > 0 ? cfg.slots : 1;
    int64_t since = now - tl;
    // stopped: no pulse for 3 slot periods, or slower than 30 rpm
    bool stopped = sp <= 0 || since > 3LL * sp || (int64_t)sp * slots > 2000000;
    a->valid = sy && !stopped;
    a->rpm = (sp > 0 && !stopped) ? 60e6f / ((float)sp * slots) : 0;
    if (!a->valid) { a->frac = 0; return; }
    float f = (float)since / (float)sp;
    // the slot before the missing one may run two periods before the next pulse
    float fmax = (cfg.missing && s == slots - 2) ? 1.999f : 0.999f;
    if (f > fmax) f = fmax;
    float frac = ((float)s + f) / (float)slots;
    if (frac >= 1.0f) frac -= 1.0f;
    a->frac = frac;
}
