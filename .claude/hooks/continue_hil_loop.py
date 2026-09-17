#!/usr/bin/env python3
"""Stop hook: keep the HIL loop running while a campaign is active.

Exit 2 tells Claude Code to continue instead of ending the turn. The hook only
does that while .hil/runtime.json says a campaign is active and no stop reason
has been latched, so completing or faulting a campaign ends the loop.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


RUNTIME_PATH = Path(".hil/runtime.json")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    # Never re-trigger on a turn that this hook already extended.
    if payload.get("stop_hook_active"):
        return 0
    if not RUNTIME_PATH.exists():
        return 0
    try:
        runtime = json.loads(RUNTIME_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    if runtime.get("campaign_active") is not True or runtime.get("stop_reason"):
        return 0
    milestone = runtime.get("milestone")
    print(
        f"HIL campaign for milestone {milestone} is still active. Continue the loop: "
        "observe the last trial's evidence, state one hypothesis, make one minimal change, "
        "build, run one bounded ./tools/hilctl trial, then evaluate. "
        "Finish with './tools/hilctl campaign complete' or './tools/hilctl campaign stop --reason ...' "
        "before ending the turn.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
