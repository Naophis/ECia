#!/usr/bin/env python3
"""hilctl `verify_halted`: observe, never create, the post-flash halted state.

Contract: the final non-empty stdout line is JSON with `state` and
`probe_serial`; hilctl only proceeds to the bounded test when `state` is
"halted". This adapter therefore must not halt or reset the target -- doing so
would make the check vacuous. `init` attaches to the core without changing its
run state.

Usage: verify_halted.py <expected_probe_serial>
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ocd import TIM1_BDTR, TIM1_CCER, TIM1_CR1, TIM_BDTR_MOE  # noqa: E402
from ocd import AdapterError, OpenOCD, emit, require_single_probe  # noqa: E402


def main(argv: list[str]) -> int:
    expected_serial = argv[1] if len(argv) > 1 else ""
    session = None
    try:
        probe = require_single_probe(expected_serial)
        session = OpenOCD(timeout=6.0)
        session.cmd("init")
        state = session.state()
        bdtr = session.read(TIM1_BDTR)
        payload = {
            "state": state,
            "probe_serial": probe["serial"],
            "bdtr": f"{bdtr:#010x}",
            "moe": int(bool(bdtr & TIM_BDTR_MOE)),
            "ccer": f"{session.read(TIM1_CCER):#010x}",
            "cr1": f"{session.read(TIM1_CR1):#010x}",
        }
        emit(payload)
        return 0 if state == "halted" and not (bdtr & TIM_BDTR_MOE) else 1
    except AdapterError as error:
        emit({
            "state": "unknown",
            "error": str(error),
            "openocd_log": session.log_tail(12) if session else "",
        })
        return 1
    finally:
        if session is not None:
            session.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
