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

typedef struct {
    uint16_t phase_a;
    uint16_t phase_b;
    uint16_t phase_c;
    uint16_t vrefint;
} adc_sample_t;

void adc_init(void);
void adc_read(adc_sample_t *sample);
