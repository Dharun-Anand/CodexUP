#include "sys/usb/usbus/usbus.c"
#include <stdlib.h>

void harness() {
    // Allocate usbus with minimally sufficient size and ensure it is non-NULL
    size_t usbus_len;
    __CPROVER_assume(usbus_len >= sizeof(usbus_t));
    usbus_t *usbus = malloc(usbus_len);
    __CPROVER_assume(usbus != NULL);

    // Model the existing handlers list to avoid unconstrained dereferences
    _Bool has_existing_handler;
    if (has_existing_handler) {
        usbus_handler_t *node = malloc(sizeof(usbus_handler_t));
        __CPROVER_assume(node != NULL);
        node->next = NULL;            // Single, well-formed node
        usbus->handlers = node;
    }
    else {
        usbus->handlers = NULL;       // Empty list
    }

    // handler argument remains nondet; malloc may return NULL
    size_t handler_len;
    __CPROVER_assume(handler_len >= sizeof(usbus_handler_t));
    usbus_handler_t *handler = malloc(handler_len);

    usbus_register_event_handler(usbus, handler);
}
