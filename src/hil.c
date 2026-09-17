#include "hil.h"

#include "motor_control.h"

#ifndef BUILD_ID
#define BUILD_ID 0u
#endif

/* Not static, not const, and volatile: the host locates these by symbol and
 * reads them while the core is running, so the compiler must neither fold them
 * away nor cache their fields. */
volatile hil_cmd_t hil_cmd;
volatile hil_state_t hil_state;
volatile hil_bridge_t hil_bridge;
volatile hil_probe_t hil_probe;
volatile hil_capture_t hil_capture;
volatile hil_capture_t hil_capture_b;
volatile hil_capture_t hil_capture_f;

static void capture_header(volatile hil_capture_t *capture, uint32_t port_base)
{
    capture->port_base = port_base;
    capture->samples = 0u;
    capture->capacity = CAPTURE_SAMPLES;
    capture->sysclk_hz = SYSCLK_HZ;
    capture->ticks_per_sample = CAPTURE_TICKS_PER_SAMPLE;
    capture->seq = 0u;
    capture->abi_version = HIL_ABI_VERSION;
    capture->magic = HIL_CAPTURE_MAGIC;
}

void hil_init(void)
{
    hil_cmd.arm_key = 0u;
    hil_cmd.request = HIL_REQUEST_IDLE;
    hil_cmd.duty_milli = 0u;
    hil_cmd.duration_ms = 0u;
    hil_cmd.rpm_limit = 0u;
    hil_cmd.seq = 0u;
    hil_cmd.tail_magic = HIL_TAIL_MAGIC;
    hil_cmd.abi_version = HIL_ABI_VERSION;
    /* Magic last: the host polls it to decide the block is live, so it must
     * not become valid before the rest of the fields are. */
    hil_cmd.magic = HIL_MAGIC;

    hil_state.seq_ack = 0u;
    hil_state.state = MOTOR_STOP;
    hil_state.fault = FAULT_NONE;
    hil_state.moe = 0u;
    hil_state.build_id = BUILD_ID;
    hil_state.mode = MOTOR_BRIDGE_MODE;
    hil_state.tail_magic = HIL_TAIL_MAGIC;
    hil_state.abi_version = HIL_ABI_VERSION;
    hil_state.magic = HIL_MAGIC;

    capture_header(&hil_capture, CAPTURE_PORT_IDR);
    capture_header(&hil_capture_b, CAPTURE_PORT_B_IDR);
    capture_header(&hil_capture_f, CAPTURE_PORT_F_IDR);
}
