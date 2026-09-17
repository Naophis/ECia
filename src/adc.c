#include "adc.h"

#include "board.h"

/* PA0 = ADC2_IN1, PA4 = ADC2_IN17, PA5 = ADC2_IN13: all three phases are
 * reachable from one ADC, so they are converted by the same instance with the
 * same settings. VREFINT is ADC1_IN18 -- it is not routed to ADC2. */
#define CH_PHASE_A 1u
#define CH_PHASE_B 17u
#define CH_PHASE_C 13u
#define CH_VREFINT 18u

/* ADC_CCR.PRESC encoding: 0=/1 1=/2 2=/4 3=/6 4=/8 5=/10 6=/12 7=/16 ...
 * 4 gives SYSCLK/8 = 21.25 MHz, half the previous 42.5 MHz. */
#ifndef ADC_PRESC
#define ADC_PRESC 4u
#endif
#define ADC_CLOCK_HZ (SYSCLK_HZ / 8u)

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

    /* Asynchronous clock (CKMODE = 0) taken from SYSCLK and divided by PRESC,
     * rather than the synchronous HCLK/4 path. HCLK/4 is 42.5 MHz and offers
     * no way to go slower; PRESC does. Every conversion on every channel --
     * the internal reference included -- came back with a +-25 % spread at
     * 42.5 MHz, and whether that is the conversion outrunning the 8.5 kOhm
     * divider or noise on the reference itself is decided by changing this
     * number and nothing else. */
    /* Back to the synchronous HCLK/4 path. The asynchronous clock at half the
     * rate produced the same spread, so the slower conversion bought nothing
     * -- and the faster one buys sample count, which is what actually narrows
     * a mean. */
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

static void burst(ADC_TypeDef *adc, uint32_t channel, adc_stat_t *stat)
{
    uint16_t values[ADC_BURST];
    uint32_t total = 0u;

    /* The first conversion after a channel change carries whatever charge the
     * previous channel left on the sample capacitor, so it is thrown away
     * rather than counted. */
    (void)convert(adc, channel);

    /* Insertion sort as the samples arrive: ADC_BURST is small, this runs
     * outside any control path, and it gives the median for free. */
    for (uint32_t index = 0u; index < ADC_BURST; index++) {
        const uint16_t value = convert(adc, channel);
        total += value;
        uint32_t slot = index;
        while (slot > 0u && values[slot - 1u] > value) {
            values[slot] = values[slot - 1u];
            slot--;
        }
        values[slot] = value;
    }

    stat->min = values[0];
    stat->max = values[ADC_BURST - 1u];
    stat->mean = (uint16_t)(total / ADC_BURST);
    stat->median = (uint16_t)(((uint32_t)values[ADC_BURST / 2u - 1u]
                               + values[ADC_BURST / 2u]) / 2u);
}

void adc_read(adc_sample_t *sample)
{
    burst(ADC2, CH_PHASE_A, &sample->phase_a);
    burst(ADC2, CH_PHASE_B, &sample->phase_b);
    burst(ADC2, CH_PHASE_C, &sample->phase_c);
    burst(ADC1, CH_VREFINT, &sample->vrefint);
}
