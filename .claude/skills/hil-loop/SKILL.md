---
name: hil-loop
description: Run the hardware-in-the-loop development campaign for one approved Milestone of the STM32G431 + MP6540HA sensorless BLDC firmware. Invoke only as /hil-loop N, and only after the user has approved Milestone N with ./tools/hilctl-user approve-milestone N --arm.
---

# HIL campaign loop

`$1` is the Milestone number. Work only inside it. `docs/motor-control-spec.md`
§19 defines each Milestone's success condition; §18 defines the rules this
skill implements.

## Before the first trial

1. `./tools/hilctl doctor --json` — must be `ok`. Do not continue otherwise.
2. `./tools/hilctl identify --json` — must report the expected MCU and probe.
3. `./tools/hilctl campaign start --milestone $1` — this runs a stop preflight
   and an identity preflight before arming the loop. If it refuses, report why
   and stop; never work around it.

If the user has not approved this Milestone, stop and say so. Never run
`./tools/hilctl-user` yourself.

## The loop

Repeat, without asking for per-trial confirmation:

1. **Observe** the last trial's evidence: `.hil/logs/<trial_id>/manifest.json`,
   `test-evidence.json`, and the adapter stdout logs.
2. **One hypothesis** that the next trial can actually decide.
3. **One minimal change** — one control-logic point or one parameter. If two
   changes genuinely cannot be separated, record why in the trial label.
4. **Build and run one bounded trial**:
   `./tools/hilctl trial --duty D --duration-ms T --rpm-limit R --label "<hypothesis>"`
   Start from the lowest duty and the shortest duration that can answer the
   question, and raise only one of duty, duration or RPM at a time.
5. **Evaluate** against the expected value, and record the decision.

`hilctl trial` already builds, checks the probe and die, flashes with the
target left halted, verifies the halted state, runs the bounded test and stops
the bridge afterwards — including from its `finally` path. Do not reimplement
any of that.

Never set a breakpoint inside an energised run: halting the core does not stop
TIM1, so the bridge would keep driving the same sector (see
`docs/hardware-mapping.md`).

## Stop and report — do not continue past these

- The Milestone's documented success condition is measured and its evidence is
  saved under `.hil/logs/`.
- The same failure signature three times, the campaign trial limit, or a trial
  that produces no new information.
- Any fault latched by `hilctl`, a failed stop, a target or probe mismatch, or
  a missing artifact.
- Anything that would need a higher safety ceiling, a wiring or component
  change, a disabled protection, or a next Milestone.
- Anything only a human can observe: noise, vibration, heat, smell. Never
  assume these are fine.

Finish with `./tools/hilctl campaign complete` (success) or
`./tools/hilctl campaign stop --reason "<why>"` (anything else). Completion
disarms the hardware; the next Milestone needs a fresh user approval.

## Report at the end

Implementation, measurements against the success condition, evidence paths
under `.hil/logs/`, remaining risks, the first test proposed for the next
Milestone, and the exact approval command the user should run.
