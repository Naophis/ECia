#!/usr/bin/env python3
"""PostToolUse audit: append every ./tools/hilctl call to the HIL log.

Only hilctl invocations are recorded; ordinary tool calls are ignored and the
log file is not created for them.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path


LOG_PATH = Path(".hil/logs/claude-tools.jsonl")
HILCTL = re.compile(r"(?:^|[\s/])hilctl(?![\w-])")


def truncate(value: object, limit: int = 4000) -> object:
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + f"...[{len(value) - limit} more chars]"
    return value


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if payload.get("tool_name") != "Bash":
        return 0
    command = str((payload.get("tool_input") or {}).get("command", ""))
    if not HILCTL.search(command):
        return 0

    response = payload.get("tool_response") or {}
    record = {
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "session_id": payload.get("session_id"),
        "command": command,
        "stdout": truncate(response.get("stdout") if isinstance(response, dict) else response),
        "stderr": truncate(response.get("stderr") if isinstance(response, dict) else None),
    }
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
