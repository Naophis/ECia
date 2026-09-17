/* ECia: STM32G431KBU6 + MP6540HA sensorless six-step firmware.
 *
 * Milestone 1 scope: TIM1 output generation only. No comparators, no BEMF, no
 * closed loop, and the motor is not connected.
 *
 * The bridge is dead on reset and stays dead until the host writes the arm key
 * and a run request into hil_cmd. Nothing in this file may change that.
 */

#include <stdbool.h>
#include <stdint.h>

#include "board.h"
#include "capture.h"
#include "clock.h"
#include "hil.h"
#include "motor_control.h"
#include "motor_hw.h"

static volatile uint32_t tick_pending;

void SysTick_Handler(void)
{
    tick_pending++;
}

int main(void)
{
    clock_init();
    hil_init();
    motor_hw_init();
    capture_init();
    motor_control_init();

    /* 1 kHz housekeeping. Deliberately the lowest-rate thing in the system and
     * never in a commutation path (spec §9). */
    SysTick->LOAD = (SYSCLK_HZ / 1000u) - 1u;
    SysTick->VAL = 0u;
    SysTick->CTRL = SysTick_CTRL_CLKSOURCE_Msk | SysTick_CTRL_TICKINT_Msk
                  | SysTick_CTRL_ENABLE_Msk;

    watchdog_init();

    for (;;) {
        if (tick_pending) {
            tick_pending--;
            motor_control_tick_1khz();
        }
        watchdog_kick();
    }
}
