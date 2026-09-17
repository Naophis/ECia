# STM32G431 BLDC project instructions

## Source of truth

- Read `docs/motor-control-spec.md` before changing motor-control code.
- Treat the schematic and MCU datasheet/reference manual as authoritative for pin and peripheral mapping.
- If hardware mapping and code disagree, stop and report the contradiction before flashing.

## Fixed architecture

- Target: STM32G431KBU6 + MP6540HA.
- Control path: open-loop forced six-step → COMP BEMF zero-cross acquisition → scheduled sensorless six-step.
- Do not introduce FOC, SimpleFOC, AM32, ESCape32, an observer, telemetry, bidirectional drive, or a generic ESC framework.
- Keep PWM generation, zero-cross detection, and commutation scheduling separate. Never schedule commutation from the PWM ISR.

## Workflow

- Milestone 0 is read-only for firmware and motor hardware. After presenting the investigation and receiving setup approval, only `.hil/config.json` may be drafted and verified; do not change firmware.
- Work only inside the currently approved Milestone.
- Within an approved Milestone, iterate autonomously: observe → one hypothesis → one minimal change → build → bounded trial → evaluate.
- Do not request approval for each successful bounded trial.
- Stop and ask before entering the next Milestone, changing wiring/components, raising a safety ceiling, disabling protection, or proceeding without an observable result.
- Preserve user changes. Never reset, clean, stash, or overwrite unrelated work.

## Hardware access

- Never run OpenOCD, ST-Link, STM32CubeProgrammer, pyOCD, J-Link, GDB load, serial motor commands, or power-control commands directly.
- All build/identify/flash/test/stop operations go through `./tools/hilctl`.
- Never invoke `./tools/hilctl-user` or edit `.hil/approval.json`, `.hil/safety-policy.json`, or `.hil/runtime.json`. Those are user/wrapper-owned.
- Never bypass or weaken `.claude/hooks/guard_hardware.py`.
- A connected debugger is not proof that the target, binary, probe, power state, or stop path is correct.
- Use `./tools/hilctl identify --json` for the read-only probe/MCU identity check. Do not query the probe directly.

## HIL campaign

- Use `/hil-loop <milestone>` only after the user approves that Milestone.
- Run `./tools/hilctl doctor --json` before starting a campaign.
- Every powered trial must have explicit duty, duration, and RPM limits within `.hil/safety-policy.json`.
- If the approved Milestone needs a higher ceiling, ask the user to update it with `./tools/hilctl-user set-limits ...`; never edit it yourself.
- One trial changes one control variable or one code hypothesis.
- Any fault, target mismatch, failed stop, missing artifact, or unsafe unknown ends the campaign.
- Three identical retryable failures, the campaign trial limit, or no new evidence ends the campaign.
- Do not use subagents or parallel shell jobs to operate live hardware.

## Completion

- A Milestone is complete only when its documented success condition is measured and its evidence is saved under `.hil/logs/`.
- Run relevant host-side tests before claiming completion.
- Complete the campaign with `./tools/hilctl campaign complete`; do not start the next Milestone automatically.
- Report implementation, measurements, evidence paths, remaining risks, and the proposed first test for the next Milestone.
