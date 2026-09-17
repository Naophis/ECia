# Host/firmware HIL ABI

`tools/hil-adapters/run_trial.py` drives a bounded trial by writing one command
block into the running firmware and polling one state block back. Both live in
RAM and are found by symbol name (`hil_cmd`, `hil_state`) in the ELF, so the
addresses never need to be pinned in `.hil/config.json` and the config hash
stays stable while the firmware evolves.

All fields are `uint32_t`, little-endian, in the order listed. `phase_error_ticks`
is read as signed. Both structures must be naturally aligned and must not be
reordered without bumping `abi_version`.

## Constants

| Name | Value |
|---|---|
| `HIL_MAGIC` | `0x314C4948` (`"HIL1"`) |
| `HIL_ABI_VERSION` | `1` |
| `HIL_ARM_KEY` | `0xA5C35A3C` |

Requests: `0` idle, `1` run, `2` stop.
States: `0` STOP, `1` ALIGN, `2` FORCED_START, `3` ACQUIRE, `4` SENSORLESS, `5` FAULT.

## `hil_cmd` (host -> target)

```c
typedef struct {
    uint32_t magic;        /* HIL_MAGIC, set by firmware at init          */
    uint32_t abi_version;  /* HIL_ABI_VERSION, set by firmware at init    */
    uint32_t arm_key;      /* HIL_ARM_KEY arms; anything else disarms     */
    uint32_t request;      /* 0 idle / 1 run / 2 stop                     */
    uint32_t duty_milli;   /* duty in 0.001 % steps; firmware clamps      */
    uint32_t duration_ms;  /* firmware-enforced hard run limit            */
    uint32_t rpm_limit;    /* firmware-enforced ceiling; 0 = no rotation  */
    uint32_t seq;          /* host increments once per trial              */
} hil_cmd_t;
```

## `hil_state` (target -> host)

```c
typedef struct {
    uint32_t magic, abi_version;
    uint32_t seq_ack;                 /* echoes hil_cmd.seq when the run ends */
    uint32_t state, fault;
    uint32_t uptime_ms, run_ms, sector, duty_applied_milli, commutations;
    uint32_t valid_zc, rejected_zc, early_zc, late_zc, lost_zc;
    uint32_t t60_raw_ticks, t60_filt_ticks;
    int32_t  phase_error_ticks;
    uint32_t rpm_est;
    uint32_t startup_count, startup_failure_count;
    uint32_t moe;                     /* mirror of TIM1 BDTR.MOE              */
    uint32_t build_id;                /* short git SHA compiled in            */
} hil_state_t;
```

## `hil_capture` (target -> host, optional)

The on-chip gate capture described in [on-chip-capture.md](on-chip-capture.md).
An 8-word header followed by the sample buffer:

```c
typedef struct {
    uint32_t magic;             /* HIL_CAPTURE_MAGIC                        */
    uint32_t abi_version;       /* HIL_ABI_VERSION                          */
    uint32_t port_base;         /* address sampled, e.g. GPIOA_IDR 0x48000010 */
    uint32_t samples;           /* valid entries in data[]                  */
    uint32_t capacity;          /* allocated entries                        */
    uint32_t sysclk_hz;         /* 170000000                                */
    uint32_t ticks_per_sample;  /* TIM7 ARR + 1                             */
    uint32_t seq;               /* hil_cmd.seq of the run that filled it    */
    uint16_t data[];            /* one GPIO IDR sample per entry            */
} hil_capture_t;
```

`HIL_CAPTURE_MAGIC` = `0x434C4948` (`"HILC"` little-endian).

The sample period is `ticks_per_sample / sysclk_hz`. The host reads the header,
then `samples` 16-bit entries, saves them verbatim to
`.hil/logs/<trial_id>/gate-capture.bin`, and runs
`tools/hil-adapters/gate_analysis.py` over them. The symbol is optional: a
firmware without it simply produces a trial with no capture, not a failure.

Port-to-bit mapping known to the host:

| `port_base` | Bits |
|---|---|
| `0x48000010` (GPIOA_IDR) | 7 = LSA, 8 = HSA, 9 = HSB, 10 = HSC |
| `0x48000410` (GPIOB_IDR) | 0 = LSB |
| `0x48001410` (GPIOF_IDR) | 0 = LSC |

Only phase A has both of its gates in one port, so it is the phase the dead
time is measured on.

## Protocol

1. The host flashes and leaves the target halted, then `resume`s it.
2. The firmware initialises both blocks, comes up in `STOP` with `MOE` clear,
   and waits. **It must never energise the bridge on reset.** The host checks
   this and aborts the trial with signature `firmware-not-disarmed` otherwise.
3. The host writes `duty_milli`, `duration_ms`, `rpm_limit`, `seq`, then
   `arm_key`, then `request = 1`, in that order. A half-written command block
   therefore never arms anything.
4. The firmware runs for at most `duration_ms`, enforcing every ceiling itself,
   then returns to `STOP` (or `FAULT`) and sets `seq_ack = seq`.
5. The host polls `hil_state` every 20 ms into the trial trace, then writes
   `request = 0` and `arm_key = 0`, clears the bridge, and saves
   `.hil/logs/<trial_id>/test-evidence.json`.

Ownership of the limits sits in the firmware on purpose: a host crash, a USB
drop or a killed adapter must not be able to leave the motor energised. The
host-side ceilings in `.hil/safety-policy.json` are a second, independent
gate, and `./tools/hilctl stop` is a third.

## Firmware obligations

- `hil_cmd` and `hil_state` are plain RAM objects with external linkage, in
  `.bss`/`.data`, never optimised away (`volatile`, and referenced).
- Reset state: `MOE` clear, all six TIM1 outputs inactive, `state == STOP`.
- Enforce `duration_ms`, `rpm_limit`, and the compiled-in maximum duty; treat
  the host's `duty_milli` as a request, not an authority.
- An independent watchdog must stop the bridge if the control loop stalls.
- Never block in the commutation path; no `printf`, no floating point, no
  blocking ADC (see `docs/motor-control-spec.md` §9).
