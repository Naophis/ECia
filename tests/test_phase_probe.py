"""Verify the phase-probe interpretation against synthetic sweeps."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "hil-adapters"))

from phase_probe import ADC_FULL_SCALE, analyse, node_mv, vdda_mv  # noqa: E402


VREFINT_CAL = 1650          # a typical factory value
VREFINT_RAW = 1650          # reads the same -> VDDA = 3.000 V
VIN_MV = 12600.0


def counts_for(node_mv_value, vdda=3000.0):
    """Inverse of node_mv(): what the ADC would read for a node voltage."""
    pin_mv = node_mv_value * 10 / 66
    return round(pin_mv / vdda * ADC_FULL_SCALE)


def sweep(vin_mv=VIN_MV, broken=()):
    """A full eight-step sweep; `broken` names FETs that do nothing."""
    steps = []
    for index in range(8):
        if index == 0 or index > 6:
            phase, high = 3, 0
        else:
            phase, high = (index - 1) // 2, 1 if (index - 1) % 2 == 0 else 0
        nodes = [0.0, 0.0, 0.0]
        name = None
        if phase < 3:
            name = "ABC"[phase] + ("H" if high else "L")
            if name not in broken and high:
                nodes[phase] = vin_mv
        steps.append({
            "step": index, "phase": phase, "high_side": high,
            "phase_a": counts_for(nodes[0]), "phase_b": counts_for(nodes[1]),
            "phase_c": counts_for(nodes[2]), "vrefint": VREFINT_RAW,
            "ccer": 0x41,
        })
    return steps


class ScalingTests(unittest.TestCase):
    def test_vdda_uses_the_factory_calibration(self):
        self.assertAlmostEqual(vdda_mv(VREFINT_RAW, VREFINT_CAL), 3000.0, delta=0.1)
        # A rail above 3.0 V makes VREFINT read lower.
        self.assertGreater(vdda_mv(1500, VREFINT_CAL), 3000.0)

    def test_node_voltage_undoes_the_divider(self):
        self.assertAlmostEqual(node_mv(counts_for(12600.0), 3000.0), 12600.0, delta=15.0)

    def test_a_zero_reference_does_not_divide_by_zero(self):
        self.assertEqual(vdda_mv(0, VREFINT_CAL), 0.0)


class SweepTests(unittest.TestCase):
    def test_a_healthy_bridge_passes_and_reports_vin(self):
        report = analyse(sweep(), VREFINT_CAL)
        self.assertTrue(report["ok"], report["fets"])
        self.assertAlmostEqual(report["vin_mv"], VIN_MV, delta=30.0)
        self.assertEqual(len(report["fets"]), 6)

    def test_a_dead_high_side_is_caught(self):
        report = analyse(sweep(broken={"BH"}), VREFINT_CAL)
        self.assertFalse(report["ok"])
        self.assertFalse(report["fets"]["BH"]["ok"])
        self.assertTrue(report["fets"]["AH"]["ok"])

    def test_a_low_side_that_never_pulls_down_is_caught(self):
        steps = sweep()
        steps[2]["phase_a"] = counts_for(VIN_MV)  # A low-side step, still high
        report = analyse(steps, VREFINT_CAL)
        self.assertFalse(report["ok"])
        self.assertFalse(report["fets"]["AL"]["ok"])

    def test_vin_is_the_median_so_one_bad_phase_does_not_move_it(self):
        report = analyse(sweep(broken={"CH"}), VREFINT_CAL)
        self.assertAlmostEqual(report["vin_mv"], VIN_MV, delta=30.0)

    def test_an_incomplete_sweep_is_not_ok(self):
        self.assertFalse(analyse(sweep()[:4], VREFINT_CAL)["ok"])
