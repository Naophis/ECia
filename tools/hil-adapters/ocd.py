"""Shared debugger plumbing for the hilctl adapter scripts.

Only ./tools/hilctl runs these adapters, and only these adapters talk to the
probe. Everything here is deliberately fail-closed: a missing probe, an extra
probe, a wrong MCU or an unreadable register raises, and the caller turns that
into a nonzero exit.

The debugger is driven over OpenOCD's Tcl RPC port rather than one-shot `-c`
batches: OpenOCD writes human log lines to stderr, so a one-shot invocation
gives no reliable way to tell a real register value from a warning, while the
Tcl port answers each command with its result and nothing else.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CFG = Path(__file__).resolve().parent / "openocd.cfg"

# The build under /home/naoto/tools is the one every previous bring-up session
# on this board used; /usr/bin/openocd is kept as a fallback only.
OPENOCD = os.environ.get("HIL_OPENOCD", "/home/naoto/tools/openocd-install/bin/openocd")
OPENOCD_SCRIPTS = os.environ.get(
    "HIL_OPENOCD_SCRIPTS", "/home/naoto/tools/openocd-install/share/openocd/scripts"
)

# ---------------------------------------------------------------------------
# STM32G431 registers used by the adapters. Addresses come from RM0440 memory
# map; TIM1_BDTR is the same address swdcli.py has been using on this board.
# ---------------------------------------------------------------------------
TIM1_BASE = 0x40012C00
TIM1_CR1 = TIM1_BASE + 0x00
TIM1_CCER = TIM1_BASE + 0x20
TIM1_BDTR = TIM1_BASE + 0x44
TIM_BDTR_MOE = 1 << 15

DBGMCU_IDCODE = 0xE0042000
FLASH_SIZE_REG = 0x1FFF75E0  # 16-bit, size in KiB
PACKAGE_REG = 0x1FFF7500
UID_BASE = 0x1FFF7590

DEV_ID_G431 = 0x468  # STM32G431/G441 (category 2)
EXPECTED_FLASH_KB = 128

# ST-LINK USB product IDs (V2, V2-1, V3 family).
STLINK_PIDS = {"3744", "3748", "374a", "374b", "374d", "374e", "374f", "3752", "3753", "3754"}


class AdapterError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Probe identity
# ---------------------------------------------------------------------------
def _sysfs_probes() -> list[dict[str, str]]:
    found = []
    for device in sorted(Path("/sys/bus/usb/devices").glob("*")):
        try:
            vendor = (device / "idVendor").read_text().strip().lower()
            product = (device / "idProduct").read_text().strip().lower()
        except OSError:
            continue
        if vendor != "0483" or product not in STLINK_PIDS:
            continue
        try:
            raw = (device / "serial").read_bytes().rstrip(b"\n")
        except OSError:
            raw = b""
        # ST-LINK/V2 stores a raw 12-byte serial in its USB string descriptor.
        # The kernel exposes it UTF-8-encoded, so decode back to code points and
        # take the low byte of each: that is the canonical 24-hex-digit form ST's
        # own tools print.
        try:
            code_points = raw.decode("utf-8")
        except UnicodeDecodeError:
            code_points = raw.decode("latin-1")
        if all(character in "0123456789abcdefABCDEF" for character in code_points) and len(code_points) in (24, 32):
            serial = code_points.upper()
        else:
            serial = "".join(f"{ord(character) & 0xFF:02X}" for character in code_points)
        found.append({
            "path": str(device),
            "product_id": product,
            "serial": serial,
            "product": (device / "product").read_text().strip() if (device / "product").exists() else "",
        })
    return found


def require_single_probe(expected_serial: str) -> dict[str, str]:
    """Bind this run to exactly one ST-LINK with the expected serial.

    OpenOCD's own `adapter serial` filter is not used: this probe reports a
    binary serial that cannot be passed through an argv safely. Refusing to run
    unless exactly one ST-LINK is attached gives the same guarantee without the
    encoding ambiguity -- and refusing on ambiguity is the safe direction.
    """
    probes = _sysfs_probes()
    if not probes:
        raise AdapterError("no ST-LINK found on USB")
    if len(probes) > 1:
        serials = ", ".join(probe["serial"] for probe in probes)
        raise AdapterError(f"{len(probes)} ST-LINK probes attached ({serials}); refusing to guess")
    probe = probes[0]
    if expected_serial and probe["serial"] != expected_serial:
        raise AdapterError(
            f"probe serial mismatch: attached {probe['serial']}, expected {expected_serial}"
        )
    return probe


# ---------------------------------------------------------------------------
# OpenOCD session
# ---------------------------------------------------------------------------
def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class OpenOCD:
    def __init__(self, timeout: float = 10.0):
        self.port = _free_port()
        self.log = tempfile.NamedTemporaryFile(
            prefix="hil-openocd-", suffix=".log", mode="w+", delete=False
        )
        if not Path(OPENOCD).exists():
            raise AdapterError(f"openocd not found at {OPENOCD} (set HIL_OPENOCD)")
        self.proc = subprocess.Popen(
            [
                OPENOCD,
                "-s", OPENOCD_SCRIPTS,
                "-c", f"tcl_port {self.port}",
                "-c", "gdb_port disabled",
                "-c", "telnet_port disabled",
                "-f", str(CFG),
            ],
            stdout=subprocess.DEVNULL,
            stderr=self.log,
            text=True,
        )
        self.sock = None
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise AdapterError("openocd exited:\n" + self.log_tail())
            try:
                self.sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
                break
            except OSError:
                time.sleep(0.05)
        if self.sock is None:
            self.close()
            raise AdapterError(f"openocd did not open its Tcl port:\n{self.log_tail()}")

    def __enter__(self) -> "OpenOCD":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def log_text(self) -> str:
        """Everything OpenOCD has logged so far.

        Commands driven over the Tcl port answer with their *return value*,
        which for several of them (`program` above all) is an empty string --
        the verdict goes to the log. Callers that need the verdict take the
        length of this before the command and slice from there afterwards.
        """
        try:
            self.log.flush()
            return Path(self.log.name).read_text(errors="replace")
        except OSError:
            return ""

    def log_tail(self, lines: int = 25) -> str:
        try:
            self.log.flush()
            return "".join(Path(self.log.name).read_text(errors="replace").splitlines(True)[-lines:])
        except OSError:
            return "(openocd log unavailable)"

    def cmd(self, line: str) -> str:
        if self.sock is None:
            raise AdapterError("openocd session is closed")
        self.sock.sendall(line.encode() + b"\x1a")
        buffer = b""
        while not buffer.endswith(b"\x1a"):
            chunk = self.sock.recv(4096)
            if not chunk:
                raise AdapterError("openocd closed the connection:\n" + self.log_tail())
            buffer += chunk
        return buffer[:-1].decode(errors="replace").strip()

    @staticmethod
    def _numbers(reply: str, what: str) -> list[int]:
        # A failed access answers with prose ("Failed to read memory at ..."),
        # which int() would turn into a bare ValueError and hide the one event
        # that matters most: the target dropping off SWD.
        try:
            return [int(word, 0) for word in reply.split()]
        except ValueError:
            raise AdapterError(f"{what}: openocd said {reply!r}") from None

    def read(self, address: int, width: int = 32) -> int:
        return self._numbers(
            self.cmd(f"read_memory {address:#x} {width} 1"), f"read {address:#x}"
        )[0]

    def read_block(self, address: int, words: int) -> list[int]:
        return self._numbers(
            self.cmd(f"read_memory {address:#x} 32 {words}"), f"read {address:#x}"
        )

    def read_bytes(self, address: int, length: int, chunk_words: int = 512) -> bytes:
        """Word-sized reads of an aligned block, in chunks.

        One `read_memory` for the whole buffer would return tens of kilobytes
        of decimal text in a single Tcl reply; chunking keeps each reply small
        without paying a per-word AP transaction.
        """
        if address % 4:
            raise AdapterError(f"read_bytes needs a word-aligned address, got {address:#x}")
        words_total = (length + 3) // 4
        data = bytearray()
        for offset in range(0, words_total, chunk_words):
            count = min(chunk_words, words_total - offset)
            for word in self.read_block(address + offset * 4, count):
                data += (word & 0xFFFFFFFF).to_bytes(4, "little")
        return bytes(data[:length])

    def write(self, address: int, value: int, width: int = 32) -> None:
        masked = value & ((1 << width) - 1)
        reply = self.cmd(f"write_memory {address:#x} {width} {{{masked}}}")
        if reply:
            raise AdapterError(f"write {address:#x}: openocd said {reply!r}")

    def state(self) -> str:
        """'running', 'halted', 'reset' or 'unknown'.

        `poll` first: a freshly attached target reports "unknown" until it has
        been polled once, and treating that as "not halted" would fail every
        post-flash check for the wrong reason. `[target current] curstate`
        then answers with the bare state word, so it survives changes to the
        `targets` table layout and the blank lines OpenOCD pads it with.
        """
        try:
            self.cmd("poll")
        except AdapterError:
            pass
        for command in ("[target current] curstate", "targets"):
            try:
                reply = self.cmd(command)
            except AdapterError:
                continue
            lines = [line for line in reply.splitlines() if line.strip()]
            if not lines:
                continue
            word = lines[-1].split()[-1].strip().lower()
            if word in {"running", "halted", "reset", "debug-running", "unknown"}:
                return word
        return "unknown"

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.cmd("shutdown")
            except Exception:
                pass
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None
        if self.proc.poll() is None:
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        try:
            self.log.close()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Shared target helpers
# ---------------------------------------------------------------------------
def identify_silicon(session: OpenOCD) -> dict[str, object]:
    idcode = session.read(DBGMCU_IDCODE)
    dev_id = idcode & 0xFFF
    flash_kb = session.read(FLASH_SIZE_REG, 16) & 0xFFFF
    package = session.read(PACKAGE_REG, 16) & 0x1F
    uid = session.read_block(UID_BASE, 3)
    return {
        "idcode": f"{idcode:#010x}",
        "dev_id": f"{dev_id:#05x}",
        "rev_id": f"{idcode >> 16:#06x}",
        "flash_size_kb": flash_kb,
        "package_raw": package,
        "uid": "".join(f"{word:08X}" for word in reversed(uid)),
        "matches_g431xb": dev_id == DEV_ID_G431 and flash_kb == EXPECTED_FLASH_KB,
    }


def bridge_off(session: OpenOCD) -> dict[str, object]:
    """Disable the TIM1 bridge outputs and confirm they are off.

    Order matters: MOE is cleared first so the gates are released within one
    debug transaction, and only then is the core reset. Halting alone is not
    enough -- the Cortex-M stops but TIM1 keeps running and keeps driving the
    MP6540HA gate inputs.
    """
    session.cmd("halt")
    before = session.read(TIM1_BDTR)
    session.write(TIM1_BDTR, before & ~TIM_BDTR_MOE)
    session.write(TIM1_CCER, 0)
    session.write(TIM1_CR1, 0)
    session.cmd("reset halt")
    after_bdtr = session.read(TIM1_BDTR)
    after_ccer = session.read(TIM1_CCER)
    after_cr1 = session.read(TIM1_CR1)
    state = session.state()
    ok = (
        not (after_bdtr & TIM_BDTR_MOE)
        and after_ccer == 0
        and (after_cr1 & 1) == 0
        and state == "halted"
    )
    return {
        "bdtr_before": f"{before:#010x}",
        "bdtr": f"{after_bdtr:#010x}",
        "ccer": f"{after_ccer:#010x}",
        "cr1": f"{after_cr1:#010x}",
        "moe": int(bool(after_bdtr & TIM_BDTR_MOE)),
        "state": state,
        "outputs_off": ok,
    }


def emit(payload: dict[str, object]) -> None:
    """The adapter output contract: the last non-empty line is the JSON result."""
    print(json.dumps(payload, sort_keys=True))
