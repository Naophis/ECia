/* On-chip gate capture: the oscilloscope substitute (docs/on-chip-capture.md).
 *
 * TIM7 paces a DMA stream from a GPIO input register into hil_capture.data, so
 * what lands in the buffer is the real pin state presented to the MP6540HA.
 * The CPU is not involved between start and completion.
 */

#pragma once

#include <stdbool.h>
#include <stdint.h>

void capture_init(void);

/* Arm a one-shot capture. Safe to call while the bridge is live; it is not
 * safe to call twice without capture_done() in between. */
void capture_start(uint32_t seq);

/* True once the DMA has filled the buffer. Records the sample count into
 * hil_capture and stops the sampler on the first true. */
bool capture_poll(void);

void capture_abort(void);
