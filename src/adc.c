#include "adc.h"

#include "board.h"

/* PA0 = ADC2_IN1, PA4 = ADC2_IN17, PA5 = ADC2_IN13: all three phases are
 * reachable from one ADC, so they are converted by the same instance with the
 * same settings. VREFINT is ADC1_IN18 -- it is not routed to ADC2. */
#define CH_PHASE_A 1u
#define CH_PHASE_B 17u
#define CH_PHASE_C 13u
#define CH_VREFINT 18u

static void wait_cycles(uint32_t cycles)
{
    while (cycles--) {
        __asm__ volatile("nop");
    }
}

static void enable_adc(ADC_TypeDef *adc)
{
    adc->CR = 0u;                 /* leave deep power-down */
    adc->CR = ADC_CR_ADVREGEN;
    wait_cycles(SYSCLK_HZ / 50000u); /* 20 us for the regulator (RM0440 21.4.6) */

    adc->CR = ADC_CR_ADVREGEN | ADC_CR_ADCAL;
    while (adc->CR & ADC_CR_ADCAL) {
    }

    /* RM0440 21.4.9: keep writing ADEN until ADRDY comes up. */
    while (adc->CR = ADC_CR_ADEN | ADC_CR_ADVREGEN, !(adc->ISR & ADC_ISR_ADRDY)) {
    }
    adc->ISR = ADC_ISR_ADRDY;

    /* Longest sampling time on every channel: 640.5 cycles at HCLK/4 =
     * 42.5 MHz is about 15 us, which the 8.5 kOhm divider needs. */
    adc->SMPR1 = 0x3FFFFFFFu;
    adc->SMPR2 = 0x07FFFFFFu;
    adc->CFGR = 0u; /* 12-bit, single conversion, software trigger */
}

void adc_init(void)
{
    RCC->AHB2ENR |= RCC_AHB2ENR_ADC12EN;
    (void)RCC->AHB2ENR;

    ADC12_COMMON->CCR = ADC_CCR_VREFEN | (2u << ADC_CCR_CKMODE_Pos); /* HCLK/4 */

    enable_adc(ADC1);
    enable_adc(ADC2);
}

static uint16_t convert(ADC_TypeDef *adc, uint32_t channel)
{
    adc->SQR1 = channel << ADC_SQR1_SQ1_Pos; /* one conversion, this channel */
    adc->ISR = ADC_ISR_EOC;
    adc->CR |= ADC_CR_ADSTART;
    while (!(adc->ISR & ADC_ISR_EOC)) {
    }
    return (uint16_t)(adc->DR & 0xFFFFu);
}

void adc_read(adc_sample_t *sample)
{
    sample->phase_a = convert(ADC2, CH_PHASE_A);
    sample->phase_b = convert(ADC2, CH_PHASE_B);
    sample->phase_c = convert(ADC2, CH_PHASE_C);
    sample->vrefint = convert(ADC1, CH_VREFINT);
}
