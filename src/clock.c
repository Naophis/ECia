/* HSI16 -> PLL -> 170 MHz, plus the independent watchdog.
 *
 * There is no crystal on this board (PF0/PF1 are the OSC pins and PF0 carries
 * TIM1_CH3N), so HSI16 is the only source.
 *
 * The order below is not interchangeable. ST's own HAL does exactly this:
 *   1. flash wait states raised *before* the frequency (stm32g4xx_hal_rcc.c)
 *   2. Range 1 boost enabled by clearing PWR_CR5.R1MODE, which is what allows
 *      anything above 150 MHz (HAL_PWREx_ControlVoltageScaling)
 *   3. AHB prescaler forced to /2 before switching to a PLL above 80 MHz
 *      ("Intermediate step with HCLK prescaler 2 necessary before to go over
 *      80Mhz" in HAL_RCC_ClockConfig)
 *   4. at least 1 us at /2, then back to /1
 */

#include "clock.h"

#include <stdint.h>

#include "board.h"

/* PLL: HSI16 / M * N / R = 16 / 4 * 85 / 2 = 170 MHz.
 * The VCO runs at 340 MHz, inside the 96-344 MHz window. */
#define PLL_M 4u
#define PLL_N 85u
#define PLL_R 2u

static void spin(uint32_t cycles)
{
    /* Deliberately crude: this is only used for the sub-microsecond clock
     * transition window, before any timer exists. Nothing in the control path
     * may busy-wait (spec §9). */
    while (cycles--) {
        __asm__ volatile("nop");
    }
}

void bringup_debug_window(void)
{
    /* SysTick polled, not interrupting, at the HSI16 reset clock. Accurate
     * enough for a window and it needs nothing configured first. */
    SysTick->LOAD = (HSI16_HZ / 1000u) - 1u;
    SysTick->VAL = 0u;
    SysTick->CTRL = SysTick_CTRL_CLKSOURCE_Msk | SysTick_CTRL_ENABLE_Msk;
    for (uint32_t elapsed = 0u; elapsed < BRINGUP_DEBUG_WINDOW_MS; elapsed++) {
        while (!(SysTick->CTRL & SysTick_CTRL_COUNTFLAG_Msk)) {
        }
    }
    SysTick->CTRL = 0u;
}

void clock_init(void)
{
    /* 4 wait states cover 170 MHz in Range 1 boost mode. Raising latency before
     * the frequency is always safe; the reverse is not. */
    FLASH->ACR = FLASH_ACR_LATENCY_4WS | FLASH_ACR_PRFTEN | FLASH_ACR_ICEN
               | FLASH_ACR_DCEN | FLASH_ACR_DBG_SWEN;
    while ((FLASH->ACR & FLASH_ACR_LATENCY) != FLASH_ACR_LATENCY_4WS) {
    }

    RCC->APB1ENR1 |= RCC_APB1ENR1_PWREN;
    (void)RCC->APB1ENR1;
    PWR->CR5 &= ~PWR_CR5_R1MODE; /* Range 1 boost: required above 150 MHz */

    RCC->CR &= ~RCC_CR_PLLON;
    while (RCC->CR & RCC_CR_PLLRDY) {
    }
    RCC->PLLCFGR = RCC_PLLCFGR_PLLSRC_HSI
                 | ((PLL_M - 1u) << RCC_PLLCFGR_PLLM_Pos)
                 | (PLL_N << RCC_PLLCFGR_PLLN_Pos)
                 | (((PLL_R / 2u) - 1u) << RCC_PLLCFGR_PLLR_Pos)
                 | RCC_PLLCFGR_PLLREN;
    RCC->CR |= RCC_CR_PLLON;
    while (!(RCC->CR & RCC_CR_PLLRDY)) {
    }

    /* APB1 and APB2 undivided: both run at 170 MHz, so every timer's clock is
     * SYSCLK with no x2 multiplier to reason about. */
    RCC->CFGR = (RCC->CFGR & ~(RCC_CFGR_PPRE1 | RCC_CFGR_PPRE2 | RCC_CFGR_HPRE))
              | RCC_CFGR_HPRE_DIV2;
    RCC->CFGR = (RCC->CFGR & ~RCC_CFGR_SW) | RCC_CFGR_SW_PLL;
    while ((RCC->CFGR & RCC_CFGR_SWS) != RCC_CFGR_SWS_PLL) {
    }

    /* At least 1 us at HCLK/2 before releasing the prescaler. 85 MHz makes
     * that 85 cycles; 512 is a wide margin and costs 3 us once at boot. */
    spin(512);
    RCC->CFGR = (RCC->CFGR & ~RCC_CFGR_HPRE) | RCC_CFGR_HPRE_DIV1;

    SCB->VTOR = FLASH_BASE;
}

void watchdog_init(void)
{
#if ENABLE_IWDG
    /* Freeze the watchdog while the debugger has the core halted. Without
     * this, every halt -- including the one the stop path performs -- would
     * land as a watchdog reset and hide the real reset cause. */
    RCC->APB2ENR |= RCC_APB2ENR_SYSCFGEN;
    DBGMCU->APB1FZR1 |= DBGMCU_APB1FZR1_DBG_IWDG_STOP;

    RCC->CSR |= RCC_CSR_LSION;
    while (!(RCC->CSR & RCC_CSR_LSIRDY)) {
    }

    IWDG->KR = 0x5555u; /* unlock PR/RLR */
    IWDG->PR = IWDG_PRESCALER_DIV8;
    IWDG->RLR = IWDG_RELOAD;
    while (IWDG->SR) {
    }
    IWDG->KR = 0xAAAAu; /* reload */
    IWDG->KR = 0xCCCCu; /* start; cannot be stopped again except by reset */
#endif
}

void watchdog_kick(void)
{
#if ENABLE_IWDG
    IWDG->KR = 0xAAAAu;
#endif
}
