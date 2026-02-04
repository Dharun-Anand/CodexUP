# Defines the root of the project.
# Be aware of how many directories deep you go!

# The value of root changes project by project but for now I'll have it be the static RIOT path
ROOT ?= ../../..

# Harness to utilize, omit the extension!
H_ENTRY = usbus_register_event_handler

# Extra CBMC flags to be passed during CBMC analysis
H_CBMCFLAGS = --nondet-static --unwind 2 # Rest to be filled in by LLM

# Env vars, filled in by LLM
H_DEF = -DMODULE_USBUS_URB=1 -DRIOT_BOARD=\"native\" -DCONFIG_USB_SERIAL_STR=\"SERIAL\"

# LLM should add more to this
H_INC = -I$(ROOT) \
        -I$(ROOT)/sys/include/  \
        -I$(ROOT)/core/lib/include/  \
        -I$(ROOT)/core/include/  \
        -I$(ROOT)/cpu/native/include/  \
        -I$(ROOT)/drivers/include/ \
        -I$(ROOT)/boards/common/native/include/

# Include our special build file
MAKE_INCLUDE_PATH ?= ..
include $(MAKE_INCLUDE_PATH)/Makefile.include
