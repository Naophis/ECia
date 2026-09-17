/* The six-step table (spec §8). Table-driven, not a switch: the sector
 * definition is data so that reversing the sequence or auditing it against the
 * schematic is a one-line change.
 */

#pragma once

#include <stdint.h>

#include "motor_hw.h"

#define SECTOR_COUNT 6u

enum comparator_edge {
    EDGE_RISING = 0,
    EDGE_FALLING = 1,
};

typedef struct {
    enum phase_drive phase[3];       /* A, B, C */
    uint8_t floating;                /* index of the floating phase, 0..2 */
    enum comparator_edge expected;   /* BEMF edge expected on the floating phase */
} commutation_sector_t;

extern const commutation_sector_t commutation_table[SECTOR_COUNT];

/* Put the bridge in `sector`. The three phase states change together on a
 * single COM event. */
void commutation_apply(uint32_t sector);
