#!/usr/bin/env python3
"""hilctl `stop`: synchronously disable the motor outputs.

Contract: exit nonzero if the off-state cannot be confirmed. hilctl runs this
as a campaign preflight, after every trial, and again from the trial's
`finally` block, so it must be idempotent and safe on a target that is already
stopped -- but it must never report success on a target it could not reach.

Sequence: halt, clear TIM1 MOE (this is what actually releases the six gate
inputs of the MP6540HA), zero CCER and CR1, then `reset halt`, then read the
registers back. Halting the core alone is not a stop: TIM1 keeps running and
keeps commutating while the CPU is stopped.

Usage: stop.py <expected_probe_serial>
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ocd import AdapterError, OpenOCD, bridge_off, emit, require_single_probe  # noqa: E402


def main(argv: list[str]) -> int:
    expected_serial = argv[1] if len(argv) > 1 else ""
    session = None
    try:
        probe = require_single_probe(expected_serial)
        session = OpenOCD(timeout=6.0)
        session.cmd("init")
        if os.environ.get("HIL_CONNECT_UNDER_RESET"):
            # Recovery path. Attaching with NRST asserted is the only way into
            # a target stuck in a reset loop, but nothing can be read or
            # written while reset is held -- so release it straight into a
            # halt, which catches the core at the reset vector before a single
            # instruction runs. Peripherals, TIM1 included, come out of that
            # in their reset state, i.e. outputs off.
            session.cmd("reset halt")
        result = bridge_off(session)
        emit({"status": "stopped" if result["outputs_off"] else "unconfirmed",
              "probe_serial": probe["serial"], **result})
        return 0 if result["outputs_off"] else 1
    except AdapterError as error:
        emit({
            "status": "unconfirmed",
            "error": str(error),
            "openocd_log": session.log_tail(12) if session else "",
        })
        return 1
    finally:
        if session is not None:
            session.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
