#!/usr/bin/env python3
"""hilctl `flash`: program the ELF and leave the target halted at reset.

Contract: the target must NOT be resumed. hilctl checks this immediately
afterwards with the `verify_halted` adapter, and the firmware's own
default-off behaviour is only a second line of defence -- freshly flashed
firmware must never start driving the bridge because of how it was loaded.

Usage: flash.py <artifact.elf> <expected_probe_serial>
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ocd import AdapterError, OpenOCD, bridge_off, emit, identify_silicon, require_single_probe  # noqa: E402


def program_verdict(log: str) -> str | None:
    """None if this program+verify succeeded, else why it did not.

    Only the log slice that *this* command produced may be passed in: an
    earlier "Verified OK" from a previous flash in the same session would
    otherwise vouch for a flash that never happened.

    A bare "Error:" line is deliberately not treated as failure. Verification
    compares the programmed flash byte for byte, so it is the authority on
    whether the image landed; failing the flash on an incidental error line
    would latch a campaign fault for no reason, and a latched fault costs a
    human round-trip to clear.
    """
    for marker in ("** Programming Failed **", "** Verify Failed **"):
        if marker in log:
            return f"openocd reported {marker.strip('* ')}"
    if "** Verified OK **" not in log:
        return "program/verify did not confirm"
    return None


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        emit({"status": "error", "error": "usage: flash.py <artifact.elf> <probe_serial>"})
        return 2
    artifact = Path(argv[1]).resolve()
    expected_serial = argv[2]

    session = None
    try:
        if not artifact.is_file():
            raise AdapterError(f"artifact not found: {artifact}")
        probe = require_single_probe(expected_serial)
        session = OpenOCD()
        session.cmd("init")

        # Re-check the die before erasing anything: hilctl already ran
        # identify, but a probe can be swapped between two subprocess calls and
        # the cost of writing this image into the wrong part is a bricked board.
        silicon = identify_silicon(session)
        if not silicon["matches_g431xb"]:
            raise AdapterError(f"target is not an STM32G431xB: {silicon}")

        # Stop the bridge before the flash controller starts erasing the code
        # that is currently driving it.
        bridge_off(session)

        # `program` answers the Tcl port with an empty string on success: its
        # progress and its verdict are written to OpenOCD's own log, not
        # returned. So the verdict has to be read from the log, and only from
        # the part of it this command produced -- an earlier "Verified OK" from
        # a previous flash in the same session would otherwise stand in for
        # this one.
        log_before = len(session.log_text())
        reply = session.cmd(f"program {{{artifact}}} verify")
        produced = session.log_text()[log_before:]
        problem = program_verdict(produced)
        if problem:
            raise AdapterError(f"{problem} (reply {reply!r}):\n{produced[-2000:]}")

        result = bridge_off(session)
        if not result["outputs_off"] or result["state"] != "halted":
            raise AdapterError(f"target not left halted with outputs off: {result}")

        emit({
            "status": "flashed",
            "artifact": str(artifact),
            "probe_serial": probe["serial"],
            "state": result["state"],
            **{key: result[key] for key in ("bdtr", "ccer", "cr1", "moe")},
        })
        return 0
    except AdapterError as error:
        emit({
            "status": "error",
            "error": str(error),
            "openocd_log": session.log_tail(15) if session else "",
        })
        return 1
    finally:
        if session is not None:
            session.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
