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

extern volatile hil_cmd_t hil_cmd;
extern volatile hil_state_t hil_state;
extern volatile hil_capture_t hil_capture;

void hil_init(void);
