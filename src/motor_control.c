#include "motor_control.h"

#include "board.h"
#include "capture.h"
#include "hil.h"
#include "motor_commutation.h"
#include "adc.h"
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
static uint32_t probe_step;
static uint32_t probe_step_ms;

static void probe_bridge_table(void)
{
    /* Walk all six sectors with MOE clear and record what TIM1 ends up
     * holding. Nothing is energised: MOE is the gate, and it stays off for
     * the whole walk -- which is checked, not assumed, and recorded. */
    hil_bridge.count = SECTOR_COUNT;
    hil_bridge.moe_while_probing = 0u;

    for (uint32_t index = 0u; index < SECTOR_COUNT; index++) {
        commutation_apply(index);
        uint32_t ccer, ccmr1, ccmr2;
        motor_hw_read_bridge(&ccer, &ccmr1, &ccmr2);
        hil_bridge.sector[index].ccer = ccer;
        hil_bridge.sector[index].ccmr1 = ccmr1;
        hil_bridge.sector[index].ccmr2 = ccmr2;
        if (motor_hw_is_enabled()) {
            hil_bridge.moe_while_probing = 1u;
        }
    }

    motor_hw_disable();
    hil_bridge.tail_magic = HIL_TAIL_MAGIC;
    hil_bridge.abi_version = HIL_ABI_VERSION;
    hil_bridge.magic = HIL_MAGIC;
}

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
    probe_step = 0u;
    probe_step_ms = 0u;

    hil_state.state = MOTOR_STOP;
    hil_state.fault = FAULT_NONE;
    hil_state.sector = 0u;
    hil_state.run_ms = 0u;
    hil_state.duty_applied_milli = 0u;
    hil_state.commutations = 0u;
    hil_state.moe = 0u;

    probe_bridge_table();
    adc_init();
}

#if MOTOR_BRIDGE_MODE == MOTOR_MODE_PHASE_PROBE
/* Step 0 is the undriven baseline; steps 1..6 walk A-high, A-low, B-high,
 * B-low, C-high, C-low; step 7 returns to undriven. */
static void probe_gate_for_step(uint32_t step, uint32_t *phase, uint32_t *high_side)
{
    if (step == 0u || step > 6u) {
        *phase = 3u; /* none */
        *high_side = 0u;
        return;
    }
    *phase = (step - 1u) / 2u;
    *high_side = ((step - 1u) % 2u) == 0u;
}

static void apply_probe_step(uint32_t step)
{
    uint32_t phase, high_side;
    probe_gate_for_step(step, &phase, &high_side);
    motor_hw_drive_single_gate(phase, high_side != 0u);
}

static void record_probe_step(uint32_t step)
{
    if (step >= HIL_PROBE_STEPS) {
        return;
    }
    uint32_t phase, high_side;
    probe_gate_for_step(step, &phase, &high_side);

    adc_sample_t sample;
    adc_read(&sample);

    uint32_t ccer, ccmr1, ccmr2;
    motor_hw_read_bridge(&ccer, &ccmr1, &ccmr2);

    hil_probe.step[step].step = step;
    hil_probe.step[step].phase = phase;
    hil_probe.step[step].high_side = high_side;
    hil_probe.step[step].phase_a = sample.phase_a;
    hil_probe.step[step].phase_b = sample.phase_b;
    hil_probe.step[step].phase_c = sample.phase_c;
    hil_probe.step[step].vrefint = sample.vrefint;
    hil_probe.step[step].ccer = ccer;
}

static void advance_probe(void)
{
    if (probe_step >= HIL_PROBE_STEPS) {
        return;
    }
    probe_step_ms++;
    if (probe_step_ms < PROBE_STEP_MS) {
        return;
    }
    probe_step_ms = 0u;

    /* Read at the end of the dwell, then move on. */
    record_probe_step(probe_step);
    probe_step++;
    if (probe_step < HIL_PROBE_STEPS) {
        apply_probe_step(probe_step);
    } else {
        motor_hw_drive_single_gate(3u, false); /* park undriven */
        hil_probe.complete = 1u;
    }
}
#endif

static void stop_bridge(uint32_t fault)
{
    motor_hw_disable();
    motor_hw_set_duty(0u);
    capture_pending = false;
    capture_poll(); /* keep whatever the DMA already collected */
    capture_abort();

    run_limit_ms = 0u;
    hil_state.moe = 0u;
    /* run_ms and duty_applied_milli are deliberately left at the values the
     * run reached. The host reads this block only after seq_ack lands, so
     * zeroing them here threw away the evidence of what actually ran; they are
     * cleared at the start of the next run instead. */
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
    hil_state.run_ms = 0u;
    sector = 0u;
    sector_timer_us = 0u;

    motor_hw_set_duty(requested);
    hil_state.duty_applied_milli = motor_hw_duty_milli();
    hil_state.fault = FAULT_NONE;
    hil_state.commutations = 0u;
    hil_state.sector = 0u;

#if MOTOR_BRIDGE_MODE == MOTOR_MODE_COMPLEMENTARY_A
    motor_hw_set_complementary_a();
#elif MOTOR_BRIDGE_MODE == MOTOR_MODE_PHASE_PROBE
    hil_probe.count = HIL_PROBE_STEPS;
    hil_probe.complete = 0u;
    hil_probe.tail_magic = HIL_TAIL_MAGIC;
    hil_probe.abi_version = HIL_ABI_VERSION;
    hil_probe.magic = HIL_MAGIC;
    probe_step = 0u;
    probe_step_ms = 0u;
    apply_probe_step(0u);
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
#if MOTOR_BRIDGE_MODE == MOTOR_MODE_PHASE_PROBE
    advance_probe();
#endif
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
