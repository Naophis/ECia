#!/usr/bin/env python3
"""PreToolUse guard: keep every hardware action inside ./tools/hilctl.

Denies
  * direct debugger / programmer / power CLIs (openocd, st-flash, pyocd, ...)
    wherever they appear in a Bash command, including after a pipe, inside a
    `bash -c "..."` payload, or spelled with an absolute path,
  * ./tools/hilctl-user, which is the human-only approval tool,
  * any write to the user/wrapper-owned state under .hil/.

Everything else is passed through with no opinion (empty stdout, exit 0).
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path


# Binaries that talk to the probe, the target, or the bench power supply.
BLOCKED_BINARIES = {
    "openocd",
    "st-flash",
    "st-info",
    "st-util",
    "stlink",
    "st-link_cli",
    "st-link_gdbserver",
    "stm32_programmer_cli",
    "stm32_programmer.sh",
    "stm32cubeprogrammer",
    "stm32cubeprog",
    "cubeprogrammer",
    "pyocd",
    "pyocd-gdbserver",
    "jlinkexe",
    "jlink",
    "jlinkgdbserver",
    "jlinkgdbserverclexe",
    "blackmagic",
    "bmpflash",
    "dfu-util",
    "arm-none-eabi-gdb",
    "gdb-multiarch",
    "arm-none-eabi-gdb-py",
    "uhubctl",
    "usbrelay",
}

# The human-only approval tool.
BLOCKED_SCRIPTS = {"hilctl-user"}

# Command words that merely introduce another command.
PASSTHROUGH_WORDS = {
    "sudo", "doas", "env", "nohup", "time", "command", "builtin", "exec",
    "xargs", "nice", "ionice", "stdbuf", "setsid", "timeout", "watch",
}

SHELL_WORDS = {"sh", "bash", "zsh", "dash", "ksh", "fish"}

PROTECTED_STATE = (".hil/approval.json", ".hil/safety-policy.json", ".hil/runtime.json")
PROTECTED_FILES = PROTECTED_STATE + (".claude/hooks/guard_hardware.py",)

# Commands that can modify a file named in their arguments.
MUTATING_COMMANDS = {
    "tee", "sed", "rm", "mv", "cp", "truncate", "dd", "install", "ln", "shred",
    "python", "python3", "perl", "ruby", "jq", "sponge", "patch", "git",
}

REDIRECT = re.compile(r"(?:^|\s)\d?>>?\s*(?P<target>[^\s;|&<>]+)")

SEGMENT_SPLIT = re.compile(r"(?:\|\||&&|\||;|\n|&)")


def deny(reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    raise SystemExit(0)


def tokens(text: str) -> list[str]:
    try:
        return shlex.split(text, comments=True)
    except ValueError:
        # Unbalanced quoting: fall back to a coarse split so the guard still
        # sees the words rather than silently allowing the command.
        return text.split()


def command_word(segment: list[str]) -> tuple[str | None, list[str], bool]:
    """Return the real command word of a segment plus any assignment values.

    Leading `VAR=value` assignments and wrapper words (sudo, xargs, timeout,
    ...) are skipped, as are the wrappers' own option words -- `xargs -I{}
    pyocd` must still resolve to `pyocd`. The assignment values are handed back
    so `OPENOCD=/usr/bin/openocd $OPENOCD ...` is caught too.
    """
    index = 0
    assignments: list[str] = []
    skipping_options = False
    while index < len(segment):
        word = segment[index]
        if "=" in word and not word.startswith("-") and word.split("=", 1)[0].isidentifier():
            assignments.append(word.split("=", 1)[1])
            index += 1
            continue
        if word.startswith("-"):
            if skipping_options:
                index += 1
                continue
            return None, assignments, skipping_options
        if Path(word).name.lower() in PASSTHROUGH_WORDS:
            skipping_options = True
            index += 1
            continue
        return word, assignments, skipping_options
    return None, assignments, skipping_options


def check_command(command: str, depth: int = 0) -> None:
    if depth > 4:
        return
    # Command substitution hides a whole command inside one token.
    for inner in re.findall(r"\$\(([^()]*)\)|`([^`]*)`", command):
        for candidate in inner:
            if candidate.strip():
                check_command(candidate, depth + 1)

    for raw_segment in SEGMENT_SPLIT.split(command):
        segment = tokens(raw_segment)
        if not segment:
            continue
        word, assignments, wrapped = command_word(segment)
        if wrapped:
            for token in segment:
                if Path(token).name.lower() in BLOCKED_BINARIES:
                    deny(
                        f"'{Path(token).name}' talks to the probe or the target directly. "
                        "Every build/identify/flash/test/stop action must go through ./tools/hilctl."
                    )
        for value in assignments:
            if Path(value).name.lower() in BLOCKED_BINARIES:
                deny(
                    f"'{Path(value).name}' talks to the probe or the target directly. "
                    "Every build/identify/flash/test/stop action must go through ./tools/hilctl."
                )
        if word is None:
            continue
        name = Path(word).name.lower()
        if name in BLOCKED_BINARIES:
            deny(
                f"'{name}' talks to the probe or the target directly. "
                "Every build/identify/flash/test/stop action must go through ./tools/hilctl."
            )
        if name in BLOCKED_SCRIPTS:
            deny(
                "./tools/hilctl-user is the human-only approval tool. "
                "Ask the user to run it in their own terminal."
            )
        if name in SHELL_WORDS:
            for token in segment[1:]:
                if token.startswith("-"):
                    continue
                check_command(token, depth + 1)


def is_protected(candidate: str) -> str | None:
    cleaned = candidate.strip("\"'")
    for protected in PROTECTED_STATE:
        if cleaned == protected or cleaned.endswith("/" + protected) or cleaned.endswith(protected.lstrip(".")):
            return protected
        if Path(cleaned).name == Path(protected).name and ".hil" in cleaned:
            return protected
    return None


def check_paths(command: str) -> None:
    """Deny only real writes to the protected state.

    Naming one of these files is fine -- listing it, reading it, or mentioning
    it in a .gitignore heredoc is ordinary work. What is denied is a redirect
    whose target is one of them, or a mutating command that takes one as an
    argument.
    """
    for match in REDIRECT.finditer(command):
        protected = is_protected(match.group("target"))
        if protected:
            deny(
                f"{protected} is owned by the user and the hilctl wrapper. "
                "It must never be written from a tool call."
            )

    for raw_segment in SEGMENT_SPLIT.split(command):
        segment = tokens(raw_segment)
        if not segment:
            continue
        word, _, _ = command_word(segment)
        if word is None or Path(word).name.lower() not in MUTATING_COMMANDS:
            continue
        for token in segment[1:]:
            protected = is_protected(token)
            if protected is None and any(is_protected(part) for part in re.split(r"[\s,()\[\]]+", token)):
                protected = next(
                    is_protected(part) for part in re.split(r"[\s,()\[\]]+", token) if is_protected(part)
                )
            if protected:
                deny(
                    f"{protected} is owned by the user and the hilctl wrapper. "
                    "It must never be written from a tool call."
                )


def check_file_tool(tool_input: dict) -> None:
    target = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if not target:
        return
    try:
        relative = os.path.relpath(str(target), str(Path.cwd()))
    except ValueError:
        relative = str(target)
    normalized = Path(relative).as_posix()
    for protected in PROTECTED_FILES:
        if normalized == protected or normalized.endswith("/" + protected):
            deny(
                f"{protected} is protected state. Editing it would weaken the HIL safety layer."
            )


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {}) or {}
    if tool == "Bash":
        command = str(tool_input.get("command", ""))
        check_command(command)
        check_paths(command)
    elif tool in {"Write", "Edit", "MultiEdit", "NotebookEdit"}:
        check_file_tool(tool_input)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
