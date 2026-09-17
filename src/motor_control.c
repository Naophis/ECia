#include "motor_control.h"

#include "board.h"
#include "capture.h"
#include "hil.h"
#include "motor_commutation.h"
#include "motor_hw.h"

/* Every limit that matters lives here rather than on the host. A host crash, a
 * dropped USB link or a killed adapter must not be able to leave the bridge
 * energised, so the firmware owns the duration and the duty ceiling and the
 * host's values are requests (docs/hil-abi.md). */

static uint32_t run_ms;
static uint32_t run_limit_ms;
static uint32_t sector;
static uint32_t sector_timer_us;
static uint32_t active_seq;
static bool capture_pending;

void motor_control_init(void)
{
    motor_hw_disable();
    motor_hw_set_duty(0u);
    run_ms = 0u;
    run_limit_ms = 0u;
    sector = 0u;
    sector_timer_us = 0u;
    active_seq = 0u;
    capture_pending = false;

    hil_state.state = MOTOR_STOP;
    hil_state.fault = FAULT_NONE;
    hil_state.sector = 0u;
    hil_state.run_ms = 0u;
    hil_state.duty_applied_milli = 0u;
    hil_state.commutations = 0u;
    hil_state.moe = 0u;
}

static void stop_bridge(uint32_t fault)
{
    motor_hw_disable();
    motor_hw_set_duty(0u);
    capture_pending = false;
    capture_poll(); /* keep whatever the DMA already collected */
    capture_abort();

    run_ms = 0u;
    run_limit_ms = 0u;
    hil_state.duty_applied_milli = 0u;
    hil_state.moe = 0u;
    hil_state.run_ms = 0u;
    hil_state.fault = fault;
    hil_state.state = (fault == FAULT_NONE) ? MOTOR_STOP : MOTOR_FAULT;
    /* seq_ack last: it is what tells the host the run is over, so everything
     * the host will read must already be settled. */
    hil_state.seq_ack = active_seq;
}

static void start_bridge(void)
{
    const uint32_t requested = hil_cmd.duty_milli;
    if (requested > MAX_DUTY_MILLI) {
        active_seq = hil_cmd.seq;
        stop_bridge(FAULT_DUTY_OUT_OF_RANGE);
        return;
    }
    if (hil_cmd.duration_ms == 0u) {
        /* Not "ran too long" -- a run with no window is a malformed command,
         * and refusing it is what keeps a zero-initialised block from arming. */
        active_seq = hil_cmd.seq;
        stop_bridge(FAULT_DURATION_INVALID);
        return;
    }

    active_seq = hil_cmd.seq;
    run_limit_ms = hil_cmd.duration_ms;
    run_ms = 0u;
    sector = 0u;
    sector_timer_us = 0u;

    motor_hw_set_duty(requested);
    hil_state.duty_applied_milli = motor_hw_duty_milli();
    hil_state.fault = FAULT_NONE;
    hil_state.commutations = 0u;
    hil_state.sector = 0u;

#if MOTOR_BRIDGE_MODE == MOTOR_MODE_COMPLEMENTARY_A
    motor_hw_set_complementary_a();
#else
    commutation_apply(sector);
#endif

    motor_hw_enable();
    hil_state.moe = 1u;
    hil_state.state = MOTOR_FORCED_START;

    /* Arm the capture on the *next* tick, not this one. CCRx and CCMRx are
     * preloaded, so they only take effect on the following update event --
     * capturing immediately would put up to one PWM period of transition
     * (31 us, 13 % of the 241 us window) into the measurement. */
    capture_pending = true;
}

static void advance_sector(void)
{
#if MOTOR_BRIDGE_MODE == MOTOR_MODE_SECTOR_STEP
    sector_timer_us += 1000u;
    while (sector_timer_us >= SECTOR_STEP_US) {
        sector_timer_us -= SECTOR_STEP_US;
        sector = (sector + 1u) % SECTOR_COUNT;
        commutation_apply(sector);
        hil_state.sector = sector;
        hil_state.commutations++;
    }
#endif
}

void motor_control_tick_1khz(void)
{
    hil_state.uptime_ms++;

    const bool armed = (hil_cmd.arm_key == HIL_ARM_KEY);
    const uint32_t request = hil_cmd.request;
    const uint32_t seq = hil_cmd.seq;

    if (hil_state.state == MOTOR_STOP || hil_state.state == MOTOR_FAULT) {
        /* A new run needs all three: the arm key, a run request, and a
         * sequence number the firmware has not already acknowledged. The
         * host writes the key and the request last for exactly this reason. */
        if (armed && request == HIL_REQUEST_RUN && seq != hil_state.seq_ack && seq != 0u) {
            start_bridge();
        }
        return;
    }

    /* Running. */
    if (!armed || request == HIL_REQUEST_STOP) {
        stop_bridge(FAULT_NONE);
        return;
    }
    if (!motor_hw_is_enabled()) {
        /* MOE went away without this module clearing it -- a break event, or
         * something writing TIM1 behind our back. Do not try to recover. */
        stop_bridge(FAULT_BRIDGE_STATE);
        return;
    }

    run_ms++;
    hil_state.run_ms = run_ms;
    advance_sector();
    if (capture_pending) {
        capture_pending = false;
        capture_start(active_seq);
    } else {
        capture_poll();
    }

    if (run_ms >= run_limit_ms) {
        stop_bridge(FAULT_NONE);
    }
}
