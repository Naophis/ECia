/* The host/firmware contract. Layout is fixed: see docs/hil-abi.md.
 *
 * tools/hil-adapters/run_trial.py finds these two objects by symbol name and
 * reads and writes them field by field, by index. Fields may be appended, but
 * never reordered or resized, without bumping HIL_ABI_VERSION.
 */

#pragma once

#include <stdint.h>

#include "board.h"

#define HIL_MAGIC         0x314C4948u /* "HIL1" */
#define HIL_CAPTURE_MAGIC 0x434C4948u /* "HILC" */
#define HIL_ABI_VERSION   1u
#define HIL_ARM_KEY       0xA5C35A3Cu
/* Every block carries this as its last word. A bulk SWD read that comes back
 * stitched together from the wrong addresses -- which this bench's probe has
 * done -- corrupts the tail of the block while the head still looks perfect,
 * so checking only a leading magic proves nothing about the fields that
 * matter. The head says "this is the block"; the tail says "and you read all
 * of it". */
#define HIL_TAIL_MAGIC    0x4C494154u /* "TAIL" */

enum hil_request {
    HIL_REQUEST_IDLE = 0,
    HIL_REQUEST_RUN = 1,
    HIL_REQUEST_STOP = 2,
};

enum motor_state {
    MOTOR_STOP = 0,
    MOTOR_ALIGN = 1,
    MOTOR_FORCED_START = 2,
    MOTOR_ACQUIRE = 3,
    MOTOR_SENSORLESS = 4,
    MOTOR_FAULT = 5,
};

enum motor_fault {
    FAULT_NONE = 0,
    FAULT_DUTY_OUT_OF_RANGE = 1,
    FAULT_DURATION_EXCEEDED = 2,
    FAULT_RPM_LIMIT = 3,
    FAULT_ZC_TIMEOUT = 4,
    FAULT_DESYNC = 5,
    FAULT_BRIDGE_STATE = 6,
    FAULT_CAPTURE = 7,
    FAULT_DURATION_INVALID = 8,
};

typedef struct {
    uint32_t magic;
    uint32_t abi_version;
    uint32_t arm_key;
    uint32_t request;
    uint32_t duty_milli;
    uint32_t duration_ms;
    uint32_t rpm_limit;
    uint32_t seq;
    uint32_t tail_magic;
} hil_cmd_t;

typedef struct {
    uint32_t magic;
    uint32_t abi_version;
    uint32_t seq_ack;
    uint32_t state;
    uint32_t fault;
    uint32_t uptime_ms;
    uint32_t run_ms;
    uint32_t sector;
    uint32_t duty_applied_milli;
    uint32_t commutations;
    uint32_t valid_zc;
    uint32_t rejected_zc;
    uint32_t early_zc;
    uint32_t late_zc;
    uint32_t lost_zc;
    uint32_t t60_raw_ticks;
    uint32_t t60_filt_ticks;
    int32_t phase_error_ticks;
    uint32_t rpm_est;
    uint32_t startup_count;
    uint32_t startup_failure_count;
    uint32_t moe;
    uint32_t build_id;
    uint32_t mode; /* compile-time bridge mode this build runs; see motor_control.h */
    uint32_t tail_magic;
} hil_state_t;

typedef struct {
    uint32_t magic;
    uint32_t abi_version;
    uint32_t port_base;
    uint32_t samples;
    uint32_t capacity;
    uint32_t sysclk_hz;
    uint32_t ticks_per_sample;
    uint32_t seq;
    uint16_t data[CAPTURE_SAMPLES];
} hil_capture_t;

/* The six-step table as TIM1 actually applied it, captured with MOE clear so
 * not one gate is energised. Reading the registers back is the only way to
 * check that the source/sink/float definition in spec §8 survived the trip
 * through OCxM and the CCER enable bits. */
typedef struct {
    uint32_t ccer;
    uint32_t ccmr1;
    uint32_t ccmr2;
} hil_bridge_sector_t;

typedef struct {
    uint32_t magic;
    uint32_t abi_version;
    uint32_t count;
    uint32_t moe_while_probing; /* must read 0: probing never energises */
    hil_bridge_sector_t sector[6];
    uint32_t tail_magic;
} hil_bridge_t;

extern volatile hil_bridge_t hil_bridge;

/* One entry per drive state of the phase-probe sweep: which single gate was
 * driven, and what the three BEMF dividers read while it was. */
#define HIL_PROBE_STEPS 8u

typedef struct {
    uint32_t step;      /* 0 = all off, then A-high, A-low, B-high, ... */
    uint32_t phase;     /* 0..2, or 3 for "no phase driven"             */
    uint32_t high_side; /* 1 = high side driven, 0 = low side           */
    uint32_t phase_a;   /* raw ADC counts                               */
    uint32_t phase_b;
    uint32_t phase_c;
    uint32_t vrefint;
    uint32_t ccer;      /* what TIM1 was actually holding               */
} hil_probe_step_t;

typedef struct {
    uint32_t magic;
    uint32_t abi_version;
    uint32_t count;
    uint32_t complete;
    hil_probe_step_t step[HIL_PROBE_STEPS];
    uint32_t tail_magic;
} hil_probe_t;

extern volatile hil_probe_t hil_probe;

extern volatile hil_cmd_t hil_cmd;
extern volatile hil_state_t hil_state;
extern volatile hil_capture_t hil_capture;   /* GPIOA: LSA, HSA, HSB, HSC */
extern volatile hil_capture_t hil_capture_b; /* GPIOB: LSB              */
extern volatile hil_capture_t hil_capture_f; /* GPIOF: LSC              */

void hil_init(void);
