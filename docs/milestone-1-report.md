# Milestone 1 — TIM1 output, measured

Completed 2026-09-17. Spec §19 Milestone 1: TIM1 only, no comparators, no BEMF,
no closed loop. Every number below is measured on the board, not inferred.

There is no oscilloscope on this bench, so the measurement is made on-chip:
TIM7 paces a DMA stream from the GPIO input registers into SRAM and the host
reads the buffer back over SWD. See [on-chip-capture.md](on-chip-capture.md).

The motor is soldered to the board and could not be removed. Every trial was
therefore designed to draw **no winding current**: only phase A is ever driven,
with phases B and C left with both gates off. The MP6540HA makes HS=L, LS=L
high impedance, so phase A's current has no return path in either a wye or a
delta winding. The only conducting paths are the BEMF dividers -- 66 kΩ and
160 kΩ, about 0.3 mA in total at 12.6 V.

## Results against the success criteria

| Spec §19 item | Measured | Design | Error | Evidence |
|---|---|---|---|---|
| PWM | **32005.0 Hz** | 32003.0 Hz | +0.006 % | trial 1 |
| Dead time | **546.2 ± 4.5 ns** | 547.06 ns | −0.16 % (0.2σ) | trial 1, 14 edges |
| Dead time (corroboration) | 553.5 ± 10.9 ns | 547.06 ns | +1.2 % (0.6σ) | trial 5, 22 edges, coarser sampler |
| No shoot-through | **0 samples** | 0 | — | every trial |
| Hi-Z | **HSB, HSC, LSB, LSC all 0.000 % high** over a 361 µs window | 0 % | — | trial 5, three ports |
| Sector transition | **all 6 sectors match spec §8 exactly** | — | — | trial 5, registers read back with MOE clear |

Two independent cross-checks fell out of the data:

- **The duty deficit is the dead time.** Commanded 5.000 %, measured 3.227 %.
  The 1.773 % difference is 2 × 93 ticks / 5312 = 3.50 %/2 per edge, i.e. the
  dead time measured a second way, from a completely different quantity.
- **The capture timebase is verified against TIM1's own ARR** on every trial.
  Trial 5: measured PWM period 31252.9 ns against the register-derived
  31247.1 ns, ratio 1.0002.

### The six-step table, read back from TIM1 with the outputs disabled

| Sector | Roles | CCER | CCMR1 | CCMR2 |
|---|---|---|---|---|
| 0 | A=source B=sink C=float | `0x0041` | `0x4868` | `0x0048` |
| 1 | A=source B=float C=sink | `0x0401` | `0x4868` | `0x0048` |
| 2 | A=float B=source C=sink | `0x0410` | `0x6848` | `0x0048` |
| 3 | A=sink B=source C=float | `0x0014` | `0x6848` | `0x0048` |
| 4 | A=sink B=float C=source | `0x0104` | `0x4848` | `0x0068` |
| 5 | A=float B=sink C=source | `0x0140` | `0x4848` | `0x0068` |

Expected values are derived from spec §8's source/sink/float definition by
`tools/hil-adapters/bridge_check.py`, which is itself covered by seven unit
tests that confirm it rejects a swapped sector, a sink driven from the high
side, a driven floating phase, both gates of one phase enabled, and a source
left in force-inactive mode. `moe_while_probing` read 0: the walk never
energised anything.

## Design decisions the measurements settled

**Sector roles are encoded in OCxM, not CCRx.** `CCPC` preloads OCxM, CCxE and
CCxNE and applies them on a COM event, but CCRx is preloaded against the
*update* event. Encoding a sink phase as CCRx = 0 would therefore leave up to
one PWM period (31 µs) where new enable bits met the old compare value, and the
sink would chop instead of sitting on. With the role in OCxM the whole sector
change lands inside one COM event, and the dead-time generator still inserts
the dead time when OCxREF moves.

**OSSR does not hold a floating phase's gates low.** RM0440 qualifies OSSR and
OSSI with "as soon as CCxE=1 or CCxNE=1"; a channel with both enable bits clear
is released to high impedance regardless. What holds those gates low is the
GPIO pull-downs this firmware configures, plus the MP6540HA's own internal
input pull-downs. That was an assumption until the capture measured those four
pins at 0.000 % high.

## Evidence

`.hil/logs/<trial_id>/` for each trial: `manifest.json` (git commit, working
tree diff hash, artifact SHA-256, target identity, parameters),
`test-evidence.json` (full trace and analysis), `hil_capture*.bin` (raw
samples), and the stdout/stderr of every adapter.

| Trial | Label |
|---|---|
| `20260917T043354.495032Z-001` | complementary phase A: PWM, dead time, overlap |
| `20260917T043723.838125Z-002` | three-port capture: LSB and LSC stay low |
| `20260917T043946.099207Z-003` | three-port at 30 ticks/sample + timebase check |
| `20260917T044213.595785Z-004` | aborted: ST-LINK re-enumerated mid-run |
| `20260917T044445.279484Z-001` | six-sector bridge table vs spec §8 |

## What went wrong, and what it changed

Three campaign faults were latched, none of them a target or firmware fault:

1. **`program ... verify` verdict misread.** OpenOCD's Tcl port returns an empty
   string and writes the verdict to its log; the adapter checked the return
   value and rejected a flash that had verified OK. Fixed, and the real failing
   log is now a regression test (`tests/test_flash_verdict.py`).
2. **ST-LINK/V2 wedged.** It kept enumerating and still reported a target
   voltage, but every SWD connect failed until the probe was physically
   replugged. Four OpenOCD sessions per trial, back to back, appear to trigger
   it; a 150 ms settle between sessions was added.
3. **ST-LINK/V2 re-enumerated itself mid-run** (devnum 10 → 11) under sustained
   polling. SWD clock pinned to 1 MHz, trace polling relaxed to 50 ms, capture
   reads doubled in size.

One measurement defect was caught by the data rather than by a test, and it is
the one worth remembering: **running three DMA streams off a 17 MHz TIM7 update
exceeded DMA1's throughput**, so the streams advanced at the DMA's rate instead
of the timer's. The edges stayed perfectly evenly spaced -- nothing looked
wrong -- and every reported time was 8.4 % short. The sampler now runs at
30 ticks per sample, and the host cross-checks the capture's timebase against
TIM1's ARR on every trial and fails the trial on a mismatch. An instrument that
can quietly lie is worse than no instrument.

## Remaining risks

1. **`hil_state.build_id` is captured at CMake configure time**, so it does not
   move when only the working tree changes. The trial manifest records the
   commit, the working-tree diff hash and the artifact SHA-256, so the binary is
   still identified exactly -- but the value compiled into the firmware is not
   the one to trust.
2. **The probe is the least reliable part of the bench.** Three of the three
   campaign faults came from it. The mitigations above are untested over a long
   campaign; Milestone 2 runs many more trials.
3. **Dead time is measured at the MCU pins**, not at the phase node. The
   MP6540HA's own propagation delay is not specified and is not observed here.
   Its truth table makes HS=H, LS=H high impedance rather than shoot-through,
   so the exposure is bounded, but it is bounded by the datasheet, not measured.
4. **Nothing has drawn motor current yet.** Every Milestone 1 result is about
   gate signals. The power stage's behaviour under load is entirely unverified.
5. **Automatic synchronous rectification** (hardware-mapping.md) will make the
   floating phase not truly floating while its current decays. This is the
   first thing to instrument once current flows.

## First test for Milestone 2

Milestone 2 is open-loop forced six-step at fixed duty, and it is the first
time the motor carries current. The motor cannot be disconnected, so the first
trial should be the smallest thing that proves the power stage follows the
gates:

**Hold sector 0 (A source, B sink, C floating) at the lowest duty that produces
a measurable phase voltage, for 50 ms, and read the three BEMF dividers with
the ADC.** Expected: phase A peak ≈ VIN·10/66, phase B ≈ 0, phase C somewhere
between. This also yields the first measurement of VIN, which nothing on this
board has observed yet.

Stalled current at 5 % duty into a ~0.2 Ω winding would be several amps, so the
duty must come down and the ADC must go in *before* any sector stepping. The
safety policy's 10 % ceiling is far above what this trial needs; a lower
`max_duty_percent` for Milestone 2 would be worth setting.
