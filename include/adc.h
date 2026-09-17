/* Phase-voltage sensing through the BEMF dividers.
 *
 * Each phase reaches the MCU through 56k/10k, so the pin sees phase * 10/66
 * and the source impedance is about 8.5 kOhm. That needs the longest sampling
 * time the ADC offers; these are DC measurements taken from the 1 kHz tick,
 * never from a commutation path.
 *
 * VREFINT is read alongside so the result is referred to the factory
 * calibration rather than to an assumed 3.3 V rail.
 */

#pragma once

#include <stdint.h>

/* Each channel is converted ADC_BURST times in a row and reported as min,
 * mean and max. Two conversions could show that a reading moves but not how
 * much or how often; a spread turns "the numbers look wrong" into a number.
 * The mean is what a measurement should use; the spread is what says whether
 * the mean means anything. */
/* 32, and a median alongside the mean. Halving the ADC clock did not change
 * the spread at all, so it is not the conversion outrunning the input. What
 * the numbers do show is a distribution that leans low: VREFINT's maximum
 * corresponds to VDDA = 3.23 V, which is possible, while its mean corresponds
 * to 3.99 V, which is above the part's absolute maximum and therefore cannot
 * be true. A mean and a median that disagree say the noise is one-sided; a
 * mean and a median that agree say it is not, and that the bias is elsewhere.
 * Neither is answerable with eight samples. */
#define ADC_BURST 32u

typedef struct {
    uint16_t min;
    uint16_t mean;
    uint16_t median;
    uint16_t max;
} adc_stat_t;

typedef struct {
    adc_stat_t phase_a;
    adc_stat_t phase_b;
    adc_stat_t phase_c;
    adc_stat_t vrefint;
} adc_sample_t;

void adc_init(void);
void adc_read(adc_sample_t *sample);
