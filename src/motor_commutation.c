#include "motor_commutation.h"

/* Forward sequence from spec §8. Sector n energises source -> sink and leaves
 * the third phase floating, where the BEMF zero crossing is expected with the
 * listed polarity.
 *
 *   Sector  Source  Sink  Floating  Expected ZC
 *   0       A       B     C         C rising
 *   1       A       C     B         B falling
 *   2       B       C     A         A rising
 *   3       B       A     C         C falling
 *   4       C       A     B         B rising
 *   5       C       B     A         A falling
 *
 * If the motor turns the wrong way once wires are attached, reverse this table
 * rather than touching anything else.
 */
const commutation_sector_t commutation_table[SECTOR_COUNT] = {
    {{PHASE_SOURCE, PHASE_SINK,   PHASE_FLOAT },  2u, EDGE_RISING  },
    {{PHASE_SOURCE, PHASE_FLOAT,  PHASE_SINK  },  1u, EDGE_FALLING },
    {{PHASE_FLOAT,  PHASE_SOURCE, PHASE_SINK  },  0u, EDGE_RISING  },
    {{PHASE_SINK,   PHASE_SOURCE, PHASE_FLOAT },  2u, EDGE_FALLING },
    {{PHASE_SINK,   PHASE_FLOAT,  PHASE_SOURCE},  1u, EDGE_RISING  },
    {{PHASE_FLOAT,  PHASE_SINK,   PHASE_SOURCE},  0u, EDGE_FALLING },
};

void commutation_apply(uint32_t sector)
{
    const commutation_sector_t *entry = &commutation_table[sector % SECTOR_COUNT];
    motor_hw_set_bridge(entry->phase[0], entry->phase[1], entry->phase[2]);
}
