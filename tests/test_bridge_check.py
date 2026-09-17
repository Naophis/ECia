"""Verify the six-step bridge-table check against known-good and broken tables."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "hil-adapters"))

from bridge_check import SPEC_SECTORS, check, expected_registers  # noqa: E402


def good_table():
    return [expected_registers(roles) for roles in SPEC_SECTORS]


class BridgeCheckTests(unittest.TestCase):
    def test_the_specified_table_passes(self):
        report = check(good_table())
        self.assertTrue(report["ok"], report["sectors"])
        self.assertEqual(report["both_gates_enabled"], [])
        self.assertEqual(len(report["sectors"]), 6)

    def test_a_swapped_sector_is_caught(self):
        table = good_table()
        table[2], table[3] = table[3], table[2]
        report = check(table)
        self.assertFalse(report["ok"])
        self.assertEqual([e["sector"] for e in report["sectors"] if not e["ok"]], [2, 3])

    def test_a_sink_driven_from_the_high_side_is_caught(self):
        # Sector 0 sinks on phase B: CC2NE. Enabling CC2E instead would put the
        # high side on where the low side belongs.
        table = good_table()
        table[0]["ccer"] = (table[0]["ccer"] & ~(1 << 6)) | (1 << 4)
        report = check(table)
        self.assertFalse(report["ok"])

    def test_a_floating_phase_that_is_actually_driven_is_caught(self):
        table = good_table()
        table[0]["ccer"] |= 1 << 8  # CC3E: phase C should be floating in sector 0
        self.assertFalse(check(table)["ok"])

    def test_both_gates_of_one_phase_enabled_is_reported_separately(self):
        table = good_table()
        table[1]["ccer"] |= (1 << 0) | (1 << 2)  # CC1E and CC1NE together
        report = check(table)
        self.assertFalse(report["ok"])
        self.assertIn("sector 1 phase A", report["both_gates_enabled"])

    def test_a_source_left_in_force_inactive_mode_is_caught(self):
        table = good_table()
        table[0]["ccmr1"] = (table[0]["ccmr1"] & ~(0x7 << 4)) | (4 << 4)
        self.assertFalse(check(table)["ok"])

    def test_a_short_table_is_refused(self):
        self.assertFalse(check(good_table()[:5])["ok"])
