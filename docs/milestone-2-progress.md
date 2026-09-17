# Milestone 2 — in progress

Milestone 2 is open-loop forced six-step, and it is the first milestone where
the motor carries current. The motor is soldered to the board and cannot be
disconnected, so the prerequisite came first: prove the power stage follows the
gates, with no winding current at all.

## Done: the power stage, verified FET by FET

`MOTOR_MODE_PHASE_PROBE` drives exactly one gate of one phase at 100 % while
both gates of the other two phases stay off. The MP6540HA makes HS=L, LS=L high
impedance, so the driven phase has no return path through the motor in either a
wye or a delta winding, and nothing carries current. The three BEMF dividers
are read at each step.

Trial `20260917T051420.844246Z-003`:

| Step | Driven node | Other two nodes |
|---|---|---|
| A high side | 12751 mV | 12828, 12854 |
| A low side | 494 mV | 347, 404 |
| B high side | 12884 mV | 12749, 13057 |
| B low side | 451 mV | 470, 420 |
| C high side | 12585 mV | 12649, 12585 |
| C low side | 342 mV | 462, 348 |

**All six FETs work.** Each high side pulls its node to the supply; each low
side pulls it to ground. `CCER` read back at every step matched what the step
asked for (`0x0001`, `0x0004`, `0x0010`, `0x0040`, `0x0100`, `0x0400`).

The other two nodes tracking the driven one to within 1.5 % is not noise -- it
is the expected result and a second, independent confirmation. With no current
there is no IR drop, so every terminal connected through a winding must sit at
the same potential. It also confirms all three phases really are connected to
the motor.

## Open: the ADC reference is not trustworthy yet

Every conversion, on every channel including the internal reference, carries a
spread of about ±25 % around its mean:

| Step | Phase A (min/mean/max) | VREFINT (min/mean/max) |
|---|---|---|
| A high side | 1533 / 1985 / 2504 | 1011 / 1257 / 1550 |
| B high side | 1615 / 1983 / 2438 | 1003 / 1256 / 1543 |
| C high side | 1551 / 1956 / 2350 | 989 / 1255 / 1579 |

Bursting eight conversions per channel makes the *mean* solid -- the three
high-side steps agree to 1.5 % -- which is what let this trial pass. The
spread itself is unexplained.

It also biases the absolute scale. Referring the phases to VREFINT gives
VDDA ≈ 3.99 V, and **that is impossible**: the part's absolute maximum VDDA is
3.6 V. So VREFINT is reading low, and the ratiometric correction built on it is
not yet valid. Taking VDDA as a nominal 3.3 V instead puts the supply at about
**10.6 V** rather than the 12.75 V the ratiometric figure claims. The earlier
bench note for this board (1685 mV at PA0, VIN ≈ 11.1 V) is consistent with the
nominal-rail reading, not the ratiometric one.

**VIN is therefore around 10.6 V, known to about ±20 %, and should not be
quoted more precisely until this is fixed.** Nothing in Milestone 2 so far
depends on the absolute value -- the FET verdicts are ratios of the same
channel against itself.

Candidate causes, none yet tested: supply noise from the gate driver's charge
pump reaching VDDA; the ADC clock at HCLK/4 = 42.5 MHz being too fast for this
input impedance despite the 640.5-cycle sampling time; an asymmetric noise
distribution making the mean a biased estimator where a median would not be.

## Next

1. Root-cause the ±25 % spread. Zero current, so it can be attacked freely.
   First test: slow the ADC clock via `ADC_CCR.PRESC` with `CKMODE = 0` and see
   whether the spread scales with conversion rate.
2. Only then, the first trial that puts current through the motor: hold
   sector 0 at the lowest duty that produces a measurable phase voltage, for a
   short window, and confirm the source phase rises, the sink phase sits at
   ground, and the floating phase sits between them.

The safety policy is currently 2 % duty and 100 ms, which was set for exactly
that step. At 2 % into a stalled winding the current is roughly 0.8 A and the
energy per trial is on the order of 10 mJ.
