#!/usr/bin/env python3
"""hilctl `test`: run exactly one bounded trial and save its evidence.

Contract: the final non-empty stdout line is JSON with `status` in
{pass, retryable, fault} plus a stable `signature`.

The host never drives the bridge directly. It writes a command block into the
running firmware, which owns every limit that matters (duty ceiling, run
duration, RPM ceiling, ZC timeout, desync detection) so that a host crash, a
lost USB link or a killed adapter cannot leave the motor energised. The
ordering below -- parameters first, then the arm key, then the request word --
means a half-written command block can never arm the bridge.

See docs/hil-abi.md for the shared structure layout.

Usage: test.py <artifact.elf> <duty> <duration_ms> <rpm_limit> <trial_id> <probe_serial>
"""

from __future__ import annotations

import json
import struct
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gate_analysis import Channel, analyse  # noqa: E402
from ocd import ROOT, TIM1_BDTR, TIM_BDTR_MOE  # noqa: E402
from ocd import AdapterError, OpenOCD, bridge_off, emit, require_single_probe  # noqa: E402


HIL_MAGIC = 0x314C4948  # 'HIL1'
HIL_CAPTURE_MAGIC = 0x434C4948  # 'HILC'
CAPTURE_HEADER_WORDS = 8

# Which gate sits on which bit of each sampled port. See docs/hil-abi.md.
CAPTURE_PORTS = {
    0x48000010: {  # GPIOA_IDR
        "channels": [Channel("LSA", 7), Channel("HSA", 8), Channel("HSB", 9), Channel("HSC", 10)],
        "phases": [("A", Channel("HSA", 8), Channel("LSA", 7))],
    },
    0x48000410: {"channels": [Channel("LSB", 0)], "phases": []},  # GPIOB_IDR
    0x48001410: {"channels": [Channel("LSC", 0)], "phases": []},  # GPIOF_IDR
}
ABI_VERSION = 1
ARM_KEY = 0xA5C35A3C

REQUEST_IDLE = 0
REQUEST_RUN = 1
REQUEST_STOP = 2

STATE_NAMES = {
    0: "STOP", 1: "ALIGN", 2: "FORCED_START", 3: "ACQUIRE", 4: "SENSORLESS", 5: "FAULT",
}

CMD_FIELDS = (
    "magic", "abi_version", "arm_key", "request",
    "duty_milli", "duration_ms", "rpm_limit", "seq",
)
STATE_FIELDS = (
    "magic", "abi_version", "seq_ack", "state", "fault", "uptime_ms", "run_ms",
    "sector", "duty_applied_milli", "commutations",
    "valid_zc", "rejected_zc", "early_zc", "late_zc", "lost_zc",
    "t60_raw_ticks", "t60_filt_ticks", "phase_error_ticks", "rpm_est",
    "startup_count", "startup_failure_count", "moe", "build_id", "mode",
)
SAMPLE_INTERVAL_S = 0.02


def symbols(artifact: Path) -> dict[str, int]:
    result = subprocess.run(
        ["arm-none-eabi-nm", "--defined-only", str(artifact)],
        text=True, capture_output=True, check=False,
    )
    if result.returncode != 0:
        raise AdapterError(f"arm-none-eabi-nm failed: {result.stderr.strip()}")
    table: dict[str, int] = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) == 3:
            table[parts[2]] = int(parts[0], 16)
    return table


def read_struct(session: OpenOCD, address: int, fields: tuple[str, ...]) -> dict[str, int]:
    words = session.read_block(address, len(fields))
    raw = b"".join(word.to_bytes(4, "little") for word in words)
    signed = {"phase_error_ticks"}
    values = {}
    for index, name in enumerate(fields):
        chunk = raw[index * 4:index * 4 + 4]
        values[name] = struct.unpack("<i" if name in signed else "<I", chunk)[0]
    return values


def read_capture(
    session: OpenOCD, address: int, trial_id: str
) -> tuple[dict[str, object] | None, str | None]:
    """Pull the on-chip gate capture and reduce it to Milestone 1 measurements.

    Returns (report, error). A firmware without the capture, or with an empty
    one, is not an error -- the milestone that needs it is the one that fills
    it, and earlier milestones should not fail for lacking it.
    """
    header = session.read_block(address, CAPTURE_HEADER_WORDS)
    magic, abi, port_base, samples, capacity, sysclk_hz, ticks, seq = header
    if magic != HIL_CAPTURE_MAGIC:
        return None, f"hil_capture magic {magic:#010x} != {HIL_CAPTURE_MAGIC:#010x}"
    if abi != ABI_VERSION:
        return None, f"hil_capture abi_version {abi} != {ABI_VERSION}"
    if not samples:
        return None, "hil_capture is empty"
    if samples > capacity:
        return None, f"hil_capture claims {samples} samples in a {capacity}-entry buffer"
    port = CAPTURE_PORTS.get(port_base)
    if port is None:
        return None, f"hil_capture port_base {port_base:#010x} is not a known GPIO IDR"
    if not sysclk_hz or not ticks:
        return None, f"hil_capture timebase is unusable: {sysclk_hz} Hz / {ticks} ticks"

    raw = session.read_bytes(address + CAPTURE_HEADER_WORDS * 4, samples * 2)
    values = list(struct.unpack(f"<{samples}H", raw))

    directory = ROOT / ".hil" / "logs" / trial_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "gate-capture.bin").write_bytes(raw)

    sample_period_ns = ticks / sysclk_hz * 1e9
    report = analyse(values, port["channels"], sample_period_ns, port["phases"])
    report.update({
        "port_base": f"{port_base:#010x}",
        "sysclk_hz": sysclk_hz,
        "ticks_per_sample": ticks,
        "seq": seq,
        "raw_file": str((directory / "gate-capture.bin").relative_to(ROOT)),
    })
    return report, None


def finish(payload: dict[str, object], evidence: dict[str, object], trial_id: str) -> int:
    directory = ROOT / ".hil" / "logs" / trial_id
    try:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "test-evidence.json").write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except OSError as error:
        payload.setdefault("evidence_error", str(error))
    emit(payload)
    # hilctl reads the JSON `status`, not the exit code, for pass/retryable;
    # a nonzero exit is kept for anything that never produced a verdict.
    return 0 if payload.get("status") == "pass" else 1


def main(argv: list[str]) -> int:
    if len(argv) < 7:
        emit({"status": "fault", "signature": "adapter-usage",
              "error": "usage: test.py <elf> <duty> <duration_ms> <rpm_limit> <trial_id> <probe_serial>"})
        return 2
    artifact = Path(argv[1]).resolve()
    duty_percent = float(argv[2])
    duration_ms = int(argv[3])
    rpm_limit = int(argv[4])
    trial_id = argv[5]
    expected_serial = argv[6]

    evidence: dict[str, object] = {
        "trial_id": trial_id,
        "artifact": str(artifact),
        "requested": {"duty_percent": duty_percent, "duration_ms": duration_ms, "rpm_limit": rpm_limit},
        "trace": [],
    }
    session = None
    try:
        probe = require_single_probe(expected_serial)
        table = symbols(artifact)
        missing = [name for name in ("hil_cmd", "hil_state") if name not in table]
        if missing:
            return finish(
                {"status": "fault", "signature": "firmware-abi-missing",
                 "error": f"symbols not found in {artifact.name}: {', '.join(missing)}"},
                evidence, trial_id)
        cmd_address = table["hil_cmd"]
        state_address = table["hil_state"]

        session = OpenOCD()
        session.cmd("init")
        if session.state() != "halted":
            return finish(
                {"status": "fault", "signature": "target-not-halted",
                 "error": f"target was {session.state()} at trial start"},
                evidence, trial_id)

        # Boot the firmware. It must come up disarmed with MOE clear; that is
        # checked below before anything is armed.
        session.cmd("resume")
        deadline = time.time() + 2.0
        state = {}
        while time.time() < deadline:
            state = read_struct(session, state_address, STATE_FIELDS)
            if state["magic"] == HIL_MAGIC and state["abi_version"] == ABI_VERSION:
                break
            time.sleep(0.02)
        else:
            return finish(
                {"status": "fault", "signature": "firmware-not-alive",
                 "error": "hil_state magic never appeared after resume"},
                evidence, trial_id)

        evidence["boot_state"] = dict(state)
        bdtr = session.read(TIM1_BDTR)
        if state["state"] != 0 or state["moe"] or (bdtr & TIM_BDTR_MOE):
            return finish(
                {"status": "fault", "signature": "firmware-not-disarmed",
                 "error": f"firmware came up energised: state={state['state']} bdtr={bdtr:#x}"},
                evidence, trial_id)

        # Parameters, then the arm key, then the request word.
        sequence = (state["seq_ack"] + 1) & 0xFFFFFFFF
        session.write(cmd_address + CMD_FIELDS.index("duty_milli") * 4, round(duty_percent * 1000))
        session.write(cmd_address + CMD_FIELDS.index("duration_ms") * 4, duration_ms)
        session.write(cmd_address + CMD_FIELDS.index("rpm_limit") * 4, rpm_limit)
        session.write(cmd_address + CMD_FIELDS.index("seq") * 4, sequence)
        session.write(cmd_address + CMD_FIELDS.index("arm_key") * 4, ARM_KEY)
        started = time.time()
        session.write(cmd_address + CMD_FIELDS.index("request") * 4, REQUEST_RUN)

        # The firmware stops itself at duration_ms; the host margin only covers
        # debug-link latency, and hilctl's own timeout sits above both.
        hard_deadline = started + duration_ms / 1000.0 + 2.0
        last = state
        while time.time() < hard_deadline:
            last = read_struct(session, state_address, STATE_FIELDS)
            evidence["trace"].append({
                "t_ms": round((time.time() - started) * 1000, 1),
                **{key: last[key] for key in
                   ("state", "fault", "sector", "run_ms", "duty_applied_milli", "commutations",
                    "valid_zc", "rejected_zc", "lost_zc", "rpm_est", "t60_filt_ticks",
                    "phase_error_ticks", "moe")},
            })
            if last["seq_ack"] == sequence and last["state"] in (0, 5):
                break
            time.sleep(SAMPLE_INTERVAL_S)
        else:
            session.write(cmd_address + CMD_FIELDS.index("request") * 4, REQUEST_STOP)
            last = read_struct(session, state_address, STATE_FIELDS)
            evidence["final_state"] = dict(last)
            bridge_off(session)
            return finish(
                {"status": "fault", "signature": "run-did-not-self-terminate",
                 "error": f"firmware still running {duration_ms} ms after the requested window"},
                evidence, trial_id)

        session.write(cmd_address + CMD_FIELDS.index("request") * 4, REQUEST_IDLE)
        session.write(cmd_address + CMD_FIELDS.index("arm_key") * 4, 0)
        evidence["final_state"] = dict(last)

        # Read the capture before resetting: `reset halt` leaves SRAM intact
        # only because startup never runs, which is a thin guarantee to lean on.
        capture = None
        if "hil_capture" in table:
            capture, capture_error = read_capture(session, table["hil_capture"], trial_id)
            evidence["capture"] = capture if capture else {"unavailable": capture_error}

        off = bridge_off(session)
        evidence["bridge_after"] = off

        if last["state"] == 5 or last["fault"]:
            return finish(
                {"status": "retryable", "signature": f"fault-{last['fault']}",
                 "fault": last["fault"], "state": STATE_NAMES.get(last["state"], last["state"]),
                 "trial_id": trial_id},
                evidence, trial_id)
        if not off["outputs_off"]:
            return finish(
                {"status": "fault", "signature": "outputs-not-off-after-run"},
                evidence, trial_id)

        summary = {
            "status": "pass",
            "signature": "run-complete",
            "trial_id": trial_id,
            "run_ms": last["run_ms"],
            "commutations": last["commutations"],
            "valid_zc": last["valid_zc"],
            "rejected_zc": last["rejected_zc"],
            "lost_zc": last["lost_zc"],
            "rpm_est": last["rpm_est"],
            "duty_applied_percent": last["duty_applied_milli"] / 1000.0,
            "build_id": f"{last['build_id']:08x}",
            "mode": last["mode"],
        }
        if capture:
            # A capture that shows both gates of a phase high at once means the
            # dead-time configuration is wrong. That is a fault, not a result.
            if not capture["shoot_through_free"]:
                return finish(
                    {"status": "fault", "signature": "gate-overlap-detected",
                     "overlap_samples": capture["overlap_samples_total"]},
                    evidence, trial_id)
            summary["capture"] = {
                "samples": capture["samples"],
                "window_us": capture["window_us"],
                "shoot_through_free": True,
                "phases": {
                    name: {
                        "pwm_hz": round(phase["pwm"]["frequency_hz"], 1),
                        "duty_percent": round(phase["pwm"]["duty_percent"], 2),
                        "dead_time_ns": round(phase["dead_time"]["mean_ns"], 1),
                        "dead_time_edges": phase["dead_time"]["edges"],
                    }
                    for name, phase in capture["phases"].items()
                },
                "sectors": len(capture["timeline"]),
            }
        return finish(summary, evidence, trial_id)
    except AdapterError as error:
        if session is not None:
            try:
                bridge_off(session)
            except AdapterError:
                pass
        evidence["error"] = str(error)
        return finish(
            {"status": "fault", "signature": "adapter-error", "error": str(error),
             "openocd_log": session.log_tail(15) if session else ""},
            evidence, trial_id)
    finally:
        if session is not None:
            session.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
