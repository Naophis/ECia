# Installation

Copy the contents of this kit into the root of the STM32 firmware repository. Merge rather than overwrite an existing `CLAUDE.md`, `.gitignore`, or `.claude/settings.local.json`.

## 1. Install files

```bash
cp -a stm32g431-bldc-claude-hil-kit/. /path/to/firmware-repository/
cd /path/to/firmware-repository
chmod +x tools/hilctl tools/hilctl-user
cat .gitignore.fragment >> .gitignore
```

Review the resulting diff before committing anything.

## 2. Verify the safety layer

```bash
python3 -m unittest discover -s tests -v
./tools/hilctl doctor --json
```

The tests must pass. `doctor` is expected to report `CONFIGURE_ME` fields until Milestone 0 identifies the real build, probe, flash, stop, test, and capture commands.

Do not populate `.hil/config.json` from shell history alone. Confirm the repository target, linker script, generated ARM ELF, MCU identity, probe serial, flash-halted verification, firmware default-off behavior, bounded test command, and stop path. After configuring the read-only identify command, verify it with:

```bash
./tools/hilctl identify --json
```

The command arrays are executed without a shell. Repository-local adapter scripts may call the selected debugger CLI, but they must obey these output contracts:

- `identify`: final non-empty line is JSON such as `{"mcu":"STM32G431KBU6","probe_serial":"...","connected":true}`.
- `verify_halted`: final non-empty line is JSON such as `{"state":"halted","probe_serial":"..."}`.
- `test`: final non-empty line is JSON with `status` equal to `pass`, `retryable`, or `fault`, plus a stable `signature`.
- `stop`: synchronously disables motor outputs and returns nonzero if off-state cannot be confirmed.

Keep `{probe_serial}`, `{artifact}`, `{duty}`, `{duration_ms}`, and `{rpm_limit}` placeholders required by `doctor`. Verify `target.flash_start` and `target.flash_end` against the actual part and linker script.

## 3. Start Claude Code

Run Claude Code at the repository root, then confirm `/context` lists `CLAUDE.md` and the project settings.

Ask Claude to perform Milestone 0 from `docs/motor-control-spec.md`. Milestone 0 is investigation only.

After reviewing and approving a powered Milestone, run this command yourself in a separate terminal:

```bash
./tools/hilctl-user approve-milestone 1 --arm
```

Then invoke the Claude skill:

```text
/hil-loop 1
```

Claude may iterate autonomously inside that Milestone. Completion disarms the campaign and requires a new user approval for the next Milestone.

If a later Milestone requires higher ceilings, review the physical setup and update only the needed values yourself. Example:

```bash
./tools/hilctl-user set-limits --max-rpm 50000 --max-duty-percent 20 --yes
```

## Emergency stop

From a human terminal:

```bash
./tools/hilctl stop
./tools/hilctl-user disarm --yes
```

This software layer does not replace a physical current limit, independent gate-disable path, guarded rotor, or accessible power disconnect.
