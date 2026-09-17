# ECia board hardware mapping (verified)

Target: **STM32G431KBU6** (UFQFPN32, DIE468) + **MP6540HA**.

Every row below is confirmed against a primary source, not inferred from the
schematic symbol or from shell history. Sources are cited per section.

## Sources

| Tag | Source |
|---|---|
| `PINDATA` | ST `STM32_open_pin_data`, `mcu/STM32G431K(6-8-B)Ux.xml` and `mcu/IP/GPIO-STM32G43x_gpio_v1_0_Modes.xml` |
| `CMSIS` | ST `cmsis_device_g4`, `Include/stm32g431xx.h` |
| `HAL` | ST `stm32g4xx_hal_driver`, `Inc/stm32g4xx_hal_comp.h` (input-mux to pin mapping) |
| `SILICON` | Read from this board over SWD, 2026-09-17 (`./tools/hilctl identify --json`) |
| `BENCH` | Hardware test on this board, 2026-09-17, recorded while bringing up ESCape32 |
| `SPEC` | `docs/motor-control-spec.md` §4, §6, §7 (schematic-derived) |

## Silicon identity

`SILICON`: IDCODE `0x20036468` -> DEV_ID `0x468`, REV_ID `0x2003`;
FLASH_SIZE (`0x1FFF75E0`) = 128 KiB; package register (`0x1FFF7500`) raw = 8;
UID = `3031383930364B10002C0009`.

`PINDATA` gives DIE468 / UFQFPN32 / 26 I/O / 170 MHz / 32 KiB RAM for
STM32G431K(6-8-B)Ux, which is consistent. DEV_ID `0x468` covers STM32G431 and
G441; the flash size selects the `xB` (128 KiB) member. Package and
temperature grade are not readable from silicon, so the adapters claim only
**STM32G431xB**. UFQFPN32 is corroborated independently: PF0 carries
TIM1_CH3N on this board, and PF0 is bonded out only on the 32-pin package.

Memory (`CMSIS`): flash 128 KiB @ `0x08000000`; SRAM1 16 KiB @ `0x20000000`,
SRAM2 6 KiB @ `0x20004000` (contiguous 22 KiB), CCM SRAM 10 KiB @
`0x10000000`.

## A. Motor bridge (TIM1)

| Signal | Pin | Pkg pin | Peripheral | AF | Source |
|---|---|---|---|---|---|
| HSA | PA8 | 18 | TIM1_CH1 | AF6 | `PINDATA`, `SPEC` |
| LSA | PA7 | 12 | TIM1_CH1N | AF6 | `PINDATA`, `SPEC` |
| HSB | PA9 | 19 | TIM1_CH2 | AF6 | `PINDATA`, `SPEC` |
| LSB | PB0 | 13 | TIM1_CH2N | AF6 | `PINDATA`, `SPEC` |
| HSC | PA10 | 20 | TIM1_CH3 | AF6 | `PINDATA`, `SPEC` |
| LSC | PF0 | 2 | TIM1_CH3N | AF6 | `PINDATA`, `SPEC` |

No contradiction between the schematic and the MCU: every one of the six pins
supports exactly the TIM1 function the schematic assigns it, all on AF6.

`BENCH` confirms the gate-driver interface as well: forcing TIM1_CH1 (MP6540HA
pin 6, net HSA) pulled phase A to VIN (1685 mV at PA0 through the 56k/10k
divider, i.e. VIN ~= 11.1 V); forcing TIM1_CH1N (pin 3, net LSA) pulled it to
ground. The fitted part is the **MP6540HA** with six independent HS/LS gate
inputs -- the schematic draws it with the MP6540H symbol (ENx/PWMx pin names),
which is a reused symbol and not the fitted part's interface. The MCU
therefore generates the dead time itself; no PWM+EN style driving.

`TIM1_BASE` = `0x40012C00` (`CMSIS`); `BDTR` at `+0x44`, `CCER` at `+0x20`,
`CR1` at `+0x00`, `CCR5` at `+0x48`, `CCMR3` at `+0x50`.

### MP6540HA behaviour that the firmware must account for

From the MP6540H/MP6540HA datasheet (Rev 1.0), pin table and Table 2. Pin 3 =
LSA, pin 6 = HSA, matching the `BENCH` result exactly.

| HSx | LSx | Sx |
|---|---|---|
| L | L | High impedance |
| L | H | GND |
| H | L | VIN |
| H | H | **High impedance** |

Three consequences:

1. **Both-inputs-high does not cause shoot-through.** The driver blocks it. The
   MCU dead time is defence in depth, not the only barrier. It is still
   configured properly -- this is not licence to omit it.
2. **"The logic inputs have weak internal pull-down resistors."** This closes
   the reset window: between reset and TIM1 initialisation the six MCU pins are
   analog inputs and float, and the driver then reads them low, i.e. all
   outputs high-impedance. GPIO pull-downs in firmware are still configured, as
   belt and braces.
3. **Automatic synchronous rectification is always on.** When both FETs of a
   phase are off and Sx is driven below ground, the LS-FET turns on by itself
   until the current reaches ~zero (and symmetrically the HS-FET if Sx rises
   above VIN). **The floating phase is therefore not electrically floating
   while its current is still decaying.** This is a first-class concern for
   BEMF zero-cross detection from Milestone 3 onward: the blanking window must
   outlast the recirculation, not merely the switching noise. It is also a
   plausible contributor to the sync problems the ESCape32 build had on this
   board.

Protection: HS and LS OCP thresholds are 10-13-17 A with a 0.4 us deglitch and
a 10 ms retry; thermal shutdown at 150 degC. For a 1103-class micromouse fan
motor these are far above any normal operating current, so -- exactly as spec
§14 says -- MP6540HA's protection is **not** a current regulator. The bench
supply's own current limit is the real protection.

No propagation-delay figure is specified; only output slew, 0.33 V/ns rising
and 0.32 V/ns falling (about 38 ns at 12.6 V).

nSLEEP is pulled down internally and must be held high for normal operation; no
MCU pin drives it on this board, so it is hard-wired. nFAULT is open-drain and
likewise not routed to the MCU.

## B. BEMF sensing and virtual neutral

Divider per phase (`SPEC`): phase -> 56 k -> BEMF_x -> 10 k -> GND, i.e.
BEMF_x = phase x 10/66. Virtual neutral: BEMF_A/B/C each through 47 k into
BEMF_N.

| Signal | Pin | Pkg pin | COMP role | ADC | Source |
|---|---|---|---|---|---|
| BEMF_A | PA0 | 5 | COMP1_INM (IO2) | ADC1_IN1 / ADC2_IN1 | `PINDATA`, `HAL` |
| BEMF_B | PA4 | 9 | COMP1_INM (IO1) | ADC2_IN17 | `PINDATA`, `HAL` |
| BEMF_C | PA5 | 10 | COMP2_INM (IO1) | ADC2_IN13 | `PINDATA`, `HAL` |
| BEMF_N | PA1 | 6 | COMP1_INP (IO1) | ADC1_IN2 / ADC2_IN2 | `PINDATA`, `HAL` |
| BEMF_N | PA3 | 8 | COMP2_INP (IO2) | ADC1_IN4 | `PINDATA`, `HAL` |

**The double connection of BEMF_N to both PA1 and PA3 is now fully
explained**, and must not be changed: PA1 is the only COMP1_INP pin available
on this package (COMP1's other plus input, IO2, is PB1, which is not bonded
out on UFQFPN32), and PA3 is the only usable COMP2_INP pin (COMP2's IO1 plus
input is PA7, which this board uses for TIM1_CH1N). Each comparator needs its
own physical connection to the virtual neutral.

## C. Comparators

`HAL` gives the input-mux-to-pin mapping and `CMSIS` the field positions
(`COMP_CSR`: EN bit 0, INMSEL bits 7:4, INPSEL bit 8, POLARITY bit 15, HYST
bits 18:16, BLANKING bits 21:19, BRGEN bit 22, SCALEN bit 23, VALUE bit 30,
LOCK bit 31).

| Floating phase | Comparator | INP | INM | INPSEL | INMSEL |
|---|---|---|---|---|---|
| A | COMP1 | PA1 (BEMF_N) | PA0 (BEMF_A) | 0 (IO1) | `0b0111` (IO2) |
| B | COMP1 | PA1 (BEMF_N) | PA4 (BEMF_B) | 0 (IO1) | `0b0110` (IO1) |
| C | COMP2 | PA3 (BEMF_N) | PA5 (BEMF_C) | 1 (IO2) | `0b0110` (IO1) |

This is exactly the arrangement `SPEC` §7 proposed as its first candidate, and
it is the only one this package supports. Note the neutral is on the **plus**
input, so `COMP_OUT` high means BEMF_N > BEMF_phase, i.e. the floating phase
is *below* neutral; `COMP_CSR.POLARITY` inverts this per sector so the
expected edge is always the same polarity in software.

The same three CSR values are what the ESCape32 build running on this board
used (`compctl()`: `0x80071` = A1>A0, `0x80061` = A1>A4, `0x80161` = A3>A5),
and `BENCH` confirmed all five BEMF pins and both neutral pins respond.

Blanking: `COMP_CSR.BLANKING` = `0b001` selects **TIM1_OC5** for COMP1 and
COMP2 (`HAL`). TIM1 channel 5 is an internal-only channel with CCR5 at
`+0x48`, so the commutation blanking window can be generated in hardware from
the same timer that generates the PWM, with no software involvement. This is
the intended implementation of `SPEC` §11 blanking.

## D. Other signals

| Signal | Pin | Pkg pin | Use | Source |
|---|---|---|---|---|
| PWM1 (external command) | PA2 | 7 | TIM15_CH1, AF9 | `PINDATA`, `SPEC` §16 |
| SWDIO | PA13 | 23 | SYS_JTMS-SWDIO | `PINDATA` |
| SWCLK | PA14 | 24 | SYS_JTCK-SWCLK | `PINDATA` |
| (unconnected) | PA6 | 11 | TIM1_BKIN available, AF6 | `PINDATA`, `BENCH` |
| (unconnected) | PF1 | 4 | ADC2_IN10 / COMP3_INM | `PINDATA`, `BENCH` |

PA2 also happens to be COMP2_INM (IO2), but COMP2's INM is bound to PA5 here,
so PA2 stays free for DShot via **TIM15_CH1 input capture + DMA** (`SPEC` §16
first choice). TIM15_CH1 on PA2 is AF9.

No current-sense (SOA/SOB/SOC) or voltage-sense pin is connected to the MCU on
this board (`BENCH`: PA6 and PF1 are unconnected). Per `SPEC` §14 this means
**no phase-current control, no software current limit, and no low-voltage
cutoff**; MP6540HA's internal protection must not be treated as a current
regulator. The only current limit on the bench is the physical supply limit.

PA14 is also a TIM1_BKIN candidate but is SWCLK and therefore unusable. PA6 is
the only free TIM1_BKIN pin; with nothing driving it, BREAK has no hardware
source on this board, so emergency stop is software-initiated (`TIM1_EGR.BG`,
or clearing `BDTR.MOE`).

## E. Clock

`PINDATA` gives 170 MHz max for this part. There is **no crystal**: PF0 and
PF1 are the OSC pins and PF0 is used for TIM1_CH3N, so HSI16 + PLL is the only
option. The ESCape32 build on this board ran HSI16 x 21 / PLLR -> 168 MHz.

## Debug-halt hazard (important for every powered milestone)

Halting the Cortex-M does **not** stop TIM1. With the core halted, TIM1 keeps
PWMing whatever sector was active, so one phase stays energised indefinitely.
`DBGMCU_APB2FZ` (`0xE0042010`, `CMSIS`) bit 11 `DBG_TIM1_STOP` freezes the
counter on halt, but freezing is not safe either: the outputs freeze at their
instantaneous level, which can be a permanently-on high side.

The stop path therefore does not rely on either. `tools/hil-adapters/stop.py`
halts, then **clears `BDTR.MOE` first** -- which releases all six gate inputs
within one debug transaction -- then zeroes CCER and CR1, then `reset halt`,
then reads the registers back and exits nonzero unless the off-state is
confirmed. Corollary for the HIL loop: never set a breakpoint inside an
energised run.
