/* Vector table and reset entry for STM32G431KBU6.
 *
 * Written in C rather than assembly so the table is readable next to the IRQn
 * enum it mirrors. Every slot points at Default_Handler through a weak alias;
 * defining a handler anywhere in the firmware overrides its slot with no
 * change here.
 *
 * Nothing in this file may touch the motor bridge. The reset path must leave
 * the MP6540HA gate inputs alone until motor_hw_init() configures them, which
 * is safe because the driver's logic inputs have weak internal pull-downs
 * (see docs/hardware-mapping.md).
 */

#include <stdint.h>

extern uint32_t _sidata, _sdata, _edata, _sbss, _ebss, _estack;

int main(void);

void Reset_Handler(void);
void Default_Handler(void);

#define ALIAS_DEFAULT __attribute__((weak, alias("Default_Handler")))

/* Core exceptions */
ALIAS_DEFAULT void NMI_Handler(void);
ALIAS_DEFAULT void HardFault_Handler(void);
ALIAS_DEFAULT void MemManage_Handler(void);
ALIAS_DEFAULT void BusFault_Handler(void);
ALIAS_DEFAULT void UsageFault_Handler(void);
ALIAS_DEFAULT void SVC_Handler(void);
ALIAS_DEFAULT void DebugMon_Handler(void);
ALIAS_DEFAULT void PendSV_Handler(void);
ALIAS_DEFAULT void SysTick_Handler(void);

/* Peripheral interrupts. Only the ones this firmware will ever enable are
 * named; STM32G431's highest IRQn is 101 (FMAC), so the table holds 102
 * peripheral slots. The unnamed slots stay zero rather than being filled with
 * Default_Handler -- C has no way to fill-then-override a designated
 * initialiser, and a zero vector is the better failure anyway: taking an
 * interrupt this firmware never enabled escalates to HardFault immediately
 * instead of quietly spinning in a shared handler. IRQ numbers are from the
 * IRQn_Type enum in vendor/cmsis_device_g4/stm32g431xx.h. */
ALIAS_DEFAULT void TIM1_BRK_TIM15_IRQHandler(void);
ALIAS_DEFAULT void TIM1_UP_TIM16_IRQHandler(void);
ALIAS_DEFAULT void TIM1_TRG_COM_TIM17_IRQHandler(void);
ALIAS_DEFAULT void TIM1_CC_IRQHandler(void);
ALIAS_DEFAULT void TIM2_IRQHandler(void);
ALIAS_DEFAULT void TIM7_IRQHandler(void);
ALIAS_DEFAULT void DMA1_Channel1_IRQHandler(void);
ALIAS_DEFAULT void COMP1_2_3_IRQHandler(void);

#define IRQ_SLOTS 102

__attribute__((section(".isr_vector"), used))
void (*const vector_table[16 + IRQ_SLOTS])(void) = {
    (void (*)(void)) & _estack,
    Reset_Handler,
    NMI_Handler,
    HardFault_Handler,
    MemManage_Handler,
    BusFault_Handler,
    UsageFault_Handler,
    0, 0, 0, 0,
    SVC_Handler,
    DebugMon_Handler,
    0,
    PendSV_Handler,
    SysTick_Handler,

    [16 + 11] = DMA1_Channel1_IRQHandler,
    [16 + 24] = TIM1_BRK_TIM15_IRQHandler,
    [16 + 25] = TIM1_UP_TIM16_IRQHandler,
    [16 + 26] = TIM1_TRG_COM_TIM17_IRQHandler,
    [16 + 27] = TIM1_CC_IRQHandler,
    [16 + 28] = TIM2_IRQHandler,
    [16 + 55] = TIM7_IRQHandler,
    [16 + 64] = COMP1_2_3_IRQHandler,
};

void Reset_Handler(void)
{
    const uint32_t *source = &_sidata;
    for (uint32_t *destination = &_sdata; destination < &_edata;) {
        *destination++ = *source++;
    }
    for (uint32_t *zero = &_sbss; zero < &_ebss;) {
        *zero++ = 0;
    }
    main();
    for (;;) {
    }
}

void Default_Handler(void)
{
    /* Spin rather than reset: the debugger can then read the stacked frame and
     * say which vector fired. The independent watchdog is what stops the
     * bridge if this happens mid-run. */
    for (;;) {
    }
}
