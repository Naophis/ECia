#!/usr/bin/env python3
"""hilctl `identify`: read-only probe and MCU identity check.

Contract: the final non-empty stdout line is JSON with `mcu`, `probe_serial`
and `connected`. Nothing here resets, halts, or writes to the target.

Usage: identify.py <expected_probe_serial>
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ocd import AdapterError, OpenOCD, emit, identify_silicon, require_single_probe  # noqa: E402


# The suffix of STM32G431KBU6 encodes package (U = UFQFPN) and temperature
# grade, neither of which is readable from silicon. What the die does prove is
# the family and the flash size, so that is what this adapter claims, and the
# config expects the same string. The UFQFPN32 package is corroborated
# independently: PF0 carries TIM1_CH3N on this board, and PF0 is only bonded
# out on the 32-pin package.
VERIFIED_PART = "STM32G431xB"


def main(argv: list[str]) -> int:
    expected_serial = argv[1] if len(argv) > 1 else ""
    try:
        probe = require_single_probe(expected_serial)
    except AdapterError as error:
        emit({"connected": False, "error": str(error), "probe_serial": expected_serial})
        return 2

    session = None
    try:
        session = OpenOCD()
        session.cmd("init")
        silicon = identify_silicon(session)
        connected = bool(silicon["matches_g431xb"])
        emit({
            "connected": connected,
            "mcu": VERIFIED_PART if connected else "unknown",
            "probe_serial": probe["serial"],
            "probe_product": probe["product"],
            "core_state": session.state(),
            **silicon,
        })
        return 0 if connected else 2
    except AdapterError as error:
        emit({
            "connected": False,
            "probe_serial": probe["serial"],
            "error": str(error),
            "openocd_log": session.log_tail(12) if session else "",
        })
        return 2
    finally:
        if session is not None:
            session.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
