"""Check the firmware's real struct layout against what the host assumes.

The host reads these blocks positionally, so a field added on one side and not
the other silently shifts every value after it. Reading the layout out of the
ELF's DWARF is the only way to compare what the compiler actually produced
against the host's field lists -- and doing it here means a mismatch costs a
test run, not a bench trial and a human re-arm.

Skipped when the firmware has not been built.
"""

import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "hil-adapters"))

ELF = ROOT / "build" / "ecia_bldc.elf"


def dwarf_members(lines, anchor_field):
    """Field names, in order, of the struct containing `anchor_field`."""
    start = next(i for i, line in enumerate(lines) if anchor_field in line)
    index = start
    while "DW_TAG_structure_type" not in lines[index]:
        index -= 1

    members = []
    index += 1
    while index < len(lines) and "DW_TAG_structure_type" not in lines[index]:
        if "DW_TAG_member" not in lines[index]:
            index += 1
            continue
        name = offset = None
        cursor = index + 1
        while cursor < len(lines) and "DW_TAG_" not in lines[cursor]:
            matched = re.search(r"DW_AT_name\s*:\s*(?:\([^)]*\):\s*)?(\S+)\s*$", lines[cursor])
            if matched:
                name = matched.group(1)
            matched = re.search(r"DW_AT_data_member_location:\s*(\d+)", lines[cursor])
            if matched:
                offset = int(matched.group(1))
            cursor += 1
        if name is not None:
            members.append((name, offset))
        index = cursor
    return members


@unittest.skipUnless(ELF.is_file(), "firmware not built")
class AbiLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = subprocess.run(
            ["arm-none-eabi-objdump", "--dwarf=info", str(ELF)],
            capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise unittest.SkipTest("arm-none-eabi-objdump unavailable")
        cls.lines = result.stdout.splitlines()
        import run_trial
        cls.run_trial = run_trial

    def assert_matches(self, anchor, host_fields):
        members = dwarf_members(self.lines, anchor)
        self.assertEqual([name for name, _ in members], list(host_fields))
        # Positional reads assume tightly packed 32-bit fields with no padding.
        for index, (name, offset) in enumerate(members):
            self.assertEqual(offset, index * 4, f"{name} is not at word {index}")

    def test_hil_state_matches_the_host_field_list(self):
        self.assert_matches("startup_failure_count", self.run_trial.STATE_FIELDS)

    def test_hil_cmd_matches_the_host_field_list(self):
        self.assert_matches("duty_milli", self.run_trial.CMD_FIELDS)

    def test_probe_step_matches_the_host_field_list(self):
        self.assert_matches("high_side", self.run_trial.PROBE_STEP_FIELDS)

    def test_every_block_ends_with_the_tail_sentinel(self):
        for anchor in ("startup_failure_count", "duty_milli"):
            members = dwarf_members(self.lines, anchor)
            self.assertEqual(members[-1][0], "tail_magic", anchor)
