#include "sys/event/timeout_ztimer.c"
#include <stdlib.h>
#include <stdbool.h>

void event_post(event_queue_t *queue, event_t *event) {
    (void)queue; (void)event;
}

uint32_t ztimer_set(ztimer_clock_t *clock, ztimer_t *t, uint32_t offset) {
    (void)clock; (void)t; (void)offset;
    uint32_t ret; return ret; /* nondet */
}

bool ztimer_remove(ztimer_clock_t *clock, ztimer_t *t) {
    (void)clock; (void)t;
    bool removed; return removed; /* nondet */
}

void harness() {
    size_t event_timeout_len;
    __CPROVER_assume(event_timeout_len >= sizeof(event_timeout_t));
    event_timeout_t *event_timeout = malloc(event_timeout_len);
    __CPROVER_assume(event_timeout != NULL);

    uint32_t timeout;
    event_timeout_set(event_timeout, timeout);
}
