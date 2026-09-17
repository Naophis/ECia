/* TIM1: the three-phase bridge, and nothing else.
 *
 * The gate outputs are only ever changed through this module, and only ever
 * through TIM1 -- writing GPIO in sequence to commutate is forbidden (spec §5).
 */

#pragma once

#include <stdbool.h>
#include <stdint.h>

/* One phase's role within a sector. */
enum phase_drive {
    PHASE_FLOAT = 0, /* both gates off: the phase node is high impedance */
    PHASE_SOURCE,    /* high side chopping at the commanded duty, low side off */
    PHASE_SINK,      /* low side on continuously, high side off */
};

/* Configure the six gate pins and TIM1. Leaves MOE clear and the counter
 * running, so the bridge is dead until motor_hw_enable(). */
void motor_hw_init(void);

/* duty_milli is in 0.001 % steps and is clamped to MAX_DUTY_MILLI here, not by
 * the caller: this is the last place that can refuse an out-of-range duty. */
void motor_hw_set_duty(uint32_t duty_milli);
uint32_t motor_hw_duty_milli(void);

/* Stage the three phase roles and apply them atomically on a COM event, so all
 * six outputs change in the same hardware update (spec §5). */
void motor_hw_set_bridge(enum phase_drive a, enum phase_drive b, enum phase_drive c);

/* Drive one phase as a true complementary pair, which is the only arrangement
 * that exercises TIM1's dead-time generator. Used by Milestone 1 to measure
 * the dead time; the six-step drive never uses it. */
void motor_hw_set_complementary_a(void);

/* Drive exactly one gate of one phase at 100 %, with both gates of the other
 * two phases off. With the other phases high-impedance there is no return path
 * through the motor, so this energises a gate without energising a winding --
 * which is what makes it safe on a board whose motor cannot be unsoldered.
 * phase is 0..2 for A..C. */
void motor_hw_drive_single_gate(uint32_t phase, bool high_side);

/* Read back the three registers that define the bridge state. Used to record
 * what each sector actually programmed, with the outputs disabled. */
void motor_hw_read_bridge(uint32_t *ccer, uint32_t *ccmr1, uint32_t *ccmr2);

void motor_hw_enable(void);
void motor_hw_disable(void);
bool motor_hw_is_enabled(void);
