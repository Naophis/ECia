# On-chip gate capture — the oscilloscope substitute

There is no oscilloscope on this bench. Milestone 1 still has to prove PWM,
dead time, Hi-Z and sector transition, so the measurement moves into the MCU:
a DMA stream samples the GPIO input registers at a fixed rate and the host
reads the buffer back over SWD.

This is not a workaround bolted on for one milestone. The same buffer is what
spec §15's debug GPIO would have been read with, and from Milestone 3 onward it
timestamps commutation and zero-cross events against each other.

## Mechanism

```
TIM7 (ARR = N-1, PSC = 0)  ──UP event──▶ DMAMUX request 9 ──▶ DMA1 channel
                                                                 │
                              CPAR = GPIOA_IDR (0x48000010)      │ 16-bit
                              CMAR = gate_capture[]  MINC        ▼
                                                            SRAM buffer
```

Every pin stays in its normal alternate-function output mode; `IDR` always
reflects the Schmitt-triggered **pin**, so this reads the real signal presented
to the MP6540HA gate input, not an internal timer signal.

| Setting | Value | Note |
|---|---|---|
| Sample clock | 170 MHz / N | N = 10 → 17 MHz → **58.8 ns per sample** |
| Buffer | `uint16_t[4096]` = 8 KiB | 241 µs ≈ 7.7 PWM periods at 32 kHz |
| Port | GPIOA `IDR` | PA7 = LSA (bit 7), PA8 = HSA (8), PA9 = HSB (9), PA10 = HSC (10) |
| DMA | P→M, PINC 0, MINC 1, PSIZE = MSIZE = 16-bit, one-shot | |

PB0 (LSB) and PF0 (LSC) live in other ports. DMAMUX allows several channels on
the same request ID, so two more channels sampling `GPIOB_IDR` (`0x48000410`)
and `GPIOF_IDR` (`0x48001410`) in lockstep add the missing two signals. That is
a separate change, made only after the single-port capture works.

Addresses and request IDs above come from ST's CMSIS device header and
`stm32g4xx_ll_dmamux.h`, not from inference.

## Resolution, and why 58.8 ns is enough

The dead time under test is ~550 ns, i.e. ~9.3 samples. A single edge therefore
measures to ±11 %, which on its own would be weak.

It is not a single edge. The sample clock is deliberately **not** commensurate
with the PWM period — 5312 timer ticks per PWM period against 10 ticks per
sample gives 531.2 samples per period — so the sampling phase slides across the
edge from one period to the next. Over a 4096-sample capture the same dead-time
gap is measured many times and the run-length histogram lands on two adjacent
values, k and k+1; their ratio recovers the true width to well under one
sample. This is ordinary equivalent-time sampling, and it works precisely
because the signal is periodic and the sampler is free-running.

A faster sample clock (N = 5 → 29.4 ns) is possible but is not the first
choice: a missed DMA request would silently skew the time base rather than
raise a flag, and the histogram already buys back the resolution.

## What each Milestone 1 check becomes

| Spec §19 item | Measurement | Verdict |
|---|---|---|
| PWM | period and high-run length of bit 8 (HSA) | frequency within 1 % of the configured value; duty within one sample of the commanded value |
| Dead time | run length where bits 8 and 7 are **both 0**, at every HSA↔LSA transition, both directions | histogram mean within ±10 % of `BDTR.DTG`, and no gap shorter than half the configured value |
| **No shoot-through** | `bit8 AND bit7` over the entire capture | must be **zero samples**. Absolute, not statistical. |
| Hi-Z | for the floating phase, both its gates low for the whole sector | no sample with either gate high |
| Sector transition | the six gate patterns in order, and all three phases changing within one sample at the COM event | atomic commutation confirmed |

## What it cannot measure

The capture is taken at the **MCU pins**. It does not see the MP6540HA's own
propagation delay, nor the phase-node waveform, nor any gate-driver asymmetry.
Two things reduce how much that matters here:

- The datasheet's Table 2 makes `HSx = H, LSx = H` produce **high impedance**,
  not shoot-through. The driver blocks the simultaneous-on case internally, so
  the MCU-side dead time is defence in depth rather than the only barrier.
- The datasheet gives no propagation-delay spec at all, only output slew
  (0.33 V/ns rising, 0.32 V/ns falling — about 38 ns at 12.6 V). The 548 ns
  measured on this board with the same driver is generous against that.

The phase node itself is still observable, just slowly: the BEMF dividers feed
PA0/PA4/PA5, and an ADC burst on a held sector gives the source phase's peak
(≈ VIN·10/66, which also **measures VIN**), the sink phase (≈ 0) and the
floating phase. That is a separate, later change in the Milestone 1 sequence.
