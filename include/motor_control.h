/* Motor state machine and the bounded-run contract with the host.
 *
 * Milestone 1 implements STOP and a single driven state; ALIGN, forced
 * commutation, acquisition and sensorless arrive in later milestones. The
 * states themselves are already explicit (spec §17) so that adding them is a
 * transition, not a rewrite.
 */

#pragma once

#include <stdint.h>

/* What the bridge does while a run is active. Compile-time, because each
 * Milestone 1 trial changes exactly one thing and rebuilds anyway -- keeping
 * the mode out of hil_cmd means the host's command block does not grow a field
 * that only one milestone uses. The value is reported in hil_state.mode so the
 * evidence records which build produced it.
 *
 *   1 COMPLEMENTARY_A  phase A as a complementary pair. The only mode that
 *                      exercises TIM1's dead-time generator, so this is what
 *                      the dead time is measured on.
 *   2 SECTOR_HOLD      six-step sector 0, held. Shows source / sink / floating
 *                      and proves the floating phase's gates stay low.
 *   3 SECTOR_STEP      six-step, advancing every SECTOR_STEP_US. Shows the
 *                      sector order and that a COM event changes all three
 *                      phases at once.
 */
#define MOTOR_MODE_COMPLEMENTARY_A 1
#define MOTOR_MODE_SECTOR_HOLD     2
#define MOTOR_MODE_SECTOR_STEP     3

#ifndef MOTOR_BRIDGE_MODE
#define MOTOR_BRIDGE_MODE MOTOR_MODE_COMPLEMENTARY_A
#endif

/* Sector dwell for MOTOR_MODE_SECTOR_STEP. 1 ms is slow enough that a 241 us
 * capture window sits inside one sector, and fast enough that a 200 ms run
 * covers many electrical revolutions. */
#ifndef SECTOR_STEP_US
#define SECTOR_STEP_US 1000u
#endif

void motor_control_init(void);

/* Called at 1 kHz from the main loop. Owns the run duration, the duty ceiling
 * and the transition back to STOP. */
void motor_control_tick_1khz(void);
