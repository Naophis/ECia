"""Verify how the flash adapter decides whether programming succeeded.

This exists because the first real trial of Milestone 1 failed on exactly this:
`program ... verify` returns an empty string over OpenOCD's Tcl port and writes
its verdict to the log, so checking the return value rejected a flash that had
in fact verified OK -- and hilctl latched a campaign fault for it. A latched
fault costs a human round-trip, so the verdict logic is tested here rather than
on the bench.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "hil-adapters"))

from flash import program_verdict  # noqa: E402


SUCCESS_LOG = """background polling: on
TAP: stm32g4x.cpu (enabled)
halted
[stm32g4x.cpu] halted due to debug-request, current mode: Thread
xPSR: 0x01000000 pc: 0x080004e4 msp: 0x20001000
** Programming Started **
Info : device idcode = 0x20036468 (STM32G43/G44xx - Rev 'unknown' : 0x2003)
Info : RDP level 0 (0xAA)
Info : flash size = 128 KiB
Info : flash mode : single-bank
Info : Padding image section 0 at 0x08000ed4 with 4 bytes (bank write end alignment)
Warn : Adding extra erase range, 0x08000ed8 .. 0x08000fff
** Programming Finished **
** Verify Started **
** Verified OK **
"""


class ProgramVerdictTests(unittest.TestCase):
    def test_the_real_success_log_is_accepted(self):
        # Captured verbatim from .hil/logs/20260917T034333.196832Z-001.
        self.assertIsNone(program_verdict(SUCCESS_LOG))

    def test_an_empty_log_is_not_a_success(self):
        self.assertIsNotNone(program_verdict(""))

    def test_programming_failure_is_reported(self):
        log = "** Programming Started **\n** Programming Failed **\n"
        self.assertIn("Programming Failed", program_verdict(log))

    def test_verify_failure_is_reported_even_beside_a_success_marker(self):
        log = SUCCESS_LOG + "** Verify Failed **\n"
        self.assertIn("Verify Failed", program_verdict(log))

    def test_an_incidental_error_line_does_not_fail_a_verified_flash(self):
        # Verification compares flash byte for byte, so it outranks a stray
        # error line; failing here would latch a fault for nothing.
        log = SUCCESS_LOG + "Error: timed out while waiting for target halted\n"
        self.assertIsNone(program_verdict(log))

    def test_only_this_command_s_log_slice_counts(self):
        # The caller must pass the slice produced by this program command. If a
        # previous flash's output leaked in, a failed flash would look fine --
        # this test documents the contract the caller has to keep.
        previous = SUCCESS_LOG
        this_time = "** Programming Started **\n** Programming Failed **\n"
        self.assertIsNotNone(program_verdict(this_time))
        self.assertIsNone(program_verdict(previous + this_time.replace("Failed", "Finished")))


if __name__ == "__main__":
    unittest.main()
