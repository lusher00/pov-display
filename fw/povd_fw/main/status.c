// status snapshot, as console text and as JSON for the web page
#include <stdio.h>
#include "esp_timer.h"
#include "povd.h"

typedef struct {
    angle_t a;
    float cols_s, skip_s, t_col_us, col_period_us;
    int buck, i_mv;
} snap_t;

typedef struct { int64_t t; uint32_t cols, skip; } rate_t;

// rates are per caller: each keeps its own last sample
static void snapshot(snap_t *s, rate_t *r)
{
    angle_get(&s->a);
    uint32_t c, k;
    leds_counters(&c, &k);
    int64_t now = esp_timer_get_time();
    float dt = r->t ? (now - r->t) / 1e6f : 0;
    s->cols_s = dt > 0 ? (c - r->cols) / dt : 0;
    s->skip_s = dt > 0 ? (k - r->skip) / dt : 0;
    r->t = now; r->cols = c; r->skip = k;
    s->t_col_us = leds_t_column_us();
    s->col_period_us = s->a.rpm > 0 ? 60e6f / s->a.rpm / cfg.columns_per_rev : 0;
    s->buck = buck_get();
    s->i_mv = i_in_mv();
}

void status_print(void)
{
    static rate_t r;
    snap_t s;
    snapshot(&s, &r);
    printf("rpm               %.1f\n", s.a.rpm);
    printf("synced            %d\n", s.a.valid);
    printf("revs              %lu\n", (unsigned long)s.a.revs);
    printf("enc_a_edges       %lu\n", (unsigned long)s.a.enc_a_edges);
    printf("enc_b_edges       %lu\n", (unsigned long)s.a.enc_b_edges);
    printf("columns_sent/s    %.0f   (since the last status)\n", s.cols_s);
    printf("columns_skipped/s %.0f\n", s.skip_s);
    printf("t_column_us       %.1f   (one column on the bus at clk_mhz)\n", s.t_col_us);
    if (s.col_period_us > 0)
        printf("column_period_us  %.1f   (must exceed t_column_us)\n", s.col_period_us);
    printf("buck              %d\n", s.buck);
    printf("I_IN_mV           %d\n", s.i_mv);
    printf("wifi              %s\n", wifi_ip());
}

int status_json(char *buf, int size)
{
    static rate_t r;
    snap_t s;
    snapshot(&s, &r);
    return snprintf(buf, size,
        "{\"rpm\":%.1f,\"synced\":%d,\"revs\":%lu,\"enc_a_edges\":%lu,\"enc_b_edges\":%lu,"
        "\"columns_sent_s\":%.0f,\"columns_skipped_s\":%.0f,\"t_column_us\":%.1f,\"column_period_us\":%.1f,"
        "\"buck\":%d,\"I_IN_mV\":%d,\"ip\":\"%s\"}",
        s.a.rpm, s.a.valid, (unsigned long)s.a.revs, (unsigned long)s.a.enc_a_edges,
        (unsigned long)s.a.enc_b_edges, s.cols_s, s.skip_s, s.t_col_us, s.col_period_us,
        s.buck, s.i_mv, wifi_ip());
}
