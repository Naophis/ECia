"""Verify the gate-capture analysis against synthesised waveforms.

The point is to know the analyser is right *before* it is used to judge the
firmware: every waveform here has an exact known answer, so a wrong dead time
on the bench can only come from the firmware or the hardware.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "hil-adapters"))

from gate_analysis import (  # noqa: E402
    Channel, analyse, bit_series, count_overlap, measure_dead_time, measure_pwm,
    pattern_timeline, runs,
)


HSA = Channel("HSA", 8)
LSA = Channel("LSA", 7)
HSB = Channel("HSB", 9)
HSC = Channel("HSC", 10)

# The real capture: 170 MHz core, TIM7 dividing by 10, so one sample is 10
# core ticks. Working in ticks and dividing at the end keeps the synthesis
# exact.
TICKS_PER_SAMPLE = 10
SAMPLE_PERIOD_NS = 1e9 / (170e6 / TICKS_PER_SAMPLE)  # 58.8235...


def synth_complementary(
    ticks: int,
    period_ticks: int,
    duty_ticks: int,
    dead_ticks: int,
    phase_ticks: int = 0,
    high_bit: int = HSA.bit,
    low_bit: int = LSA.bit,
) -> list[int]:
    """One complementary pair with TIM1-style dead time on both edges.

    Within a period: high side on for `duty_ticks`, then a `dead_ticks` gap,
    then the low side until `period_ticks`, then another gap before the high
    side comes back. Sampled every TICKS_PER_SAMPLE ticks starting at
    `phase_ticks`, which is what makes the sampler's phase slide relative to
    the waveform exactly as it does on the board.
    """
    samples = []
    for index in range(ticks // TICKS_PER_SAMPLE):
        tick = phase_ticks + index * TICKS_PER_SAMPLE
        position = tick % period_ticks
        value = 0
        if position < duty_ticks:
            value |= 1 << high_bit
        elif position < duty_ticks + dead_ticks:
            pass  # both off
        elif position < period_ticks - dead_ticks:
            value |= 1 << low_bit
        samples.append(value)
    return samples


class RunsTests(unittest.TestCase):
    def test_runs_reports_value_start_and_length(self):
        self.assertEqual(runs([0, 0, 1, 1, 1, 0]), [(0, 0, 2), (1, 2, 3), (0, 5, 1)])

    def test_runs_of_empty_series(self):
        self.assertEqual(runs([]), [])

    def test_bit_series_extracts_one_pin(self):
        self.assertEqual(bit_series([0x100, 0x000, 0x180], 8), [1, 0, 1])


class PwmTests(unittest.TestCase):
    def test_period_and_duty_are_recovered(self):
        # 32 kHz at 170 MHz = 5312 ticks; 25 % duty; 93-tick dead time.
        samples = synth_complementary(5312 * 40, 5312, 1328, 93)
        pwm = measure_pwm(samples, HSA, SAMPLE_PERIOD_NS)

        self.assertGreater(pwm.periods, 30)
        self.assertAlmostEqual(pwm.frequency_hz, 32_003.0, delta=32_003.0 * 0.01)
        self.assertAlmostEqual(pwm.duty_percent, 25.0, delta=0.5)

    def test_short_capture_reports_nothing_rather_than_guessing(self):
        self.assertEqual(measure_pwm([0x100, 0x100], HSA, SAMPLE_PERIOD_NS).periods, 0)


class DeadTimeTests(unittest.TestCase):
    def test_mean_run_length_recovers_sub_sample_width(self):
        # 93 ticks = 9.3 samples: never an integer number of samples, so this
        # only works if the sliding phase is being exploited.
        samples = synth_complementary(5312 * 60, 5312, 2656, 93)
        dead = measure_dead_time(samples, HSA, LSA, SAMPLE_PERIOD_NS)

        self.assertGreater(dead.edges, 100)
        self.assertAlmostEqual(dead.mean_samples, 9.3, delta=0.3)
        self.assertAlmostEqual(dead.mean_ns, 93 / 170e6 * 1e9, delta=20.0)
        # The histogram must straddle the true width, not sit on one value.
        self.assertIn(9, dead.histogram)
        self.assertIn(10, dead.histogram)

    def test_a_different_dead_time_is_distinguished(self):
        narrow = measure_dead_time(
            synth_complementary(5312 * 60, 5312, 2656, 40), HSA, LSA, SAMPLE_PERIOD_NS)
        wide = measure_dead_time(
            synth_complementary(5312 * 60, 5312, 2656, 200), HSA, LSA, SAMPLE_PERIOD_NS)

        self.assertAlmostEqual(narrow.mean_ns, 40 / 170e6 * 1e9, delta=20.0)
        self.assertAlmostEqual(wide.mean_ns, 200 / 170e6 * 1e9, delta=20.0)
        self.assertLess(narrow.mean_ns, wide.mean_ns)

    def test_a_floating_phase_is_not_counted_as_dead_time(self):
        # Both gates low for the whole capture: a floating phase, not a gap.
        dead = measure_dead_time([0] * 500, HSA, LSA, SAMPLE_PERIOD_NS)
        self.assertEqual(dead.edges, 0)

    def test_pwm_off_time_is_not_counted_as_dead_time(self):
        # High side chopping with the low side never driven -- every gap
        # returns to the same gate, so none of them is a commutation gap.
        samples = []
        for index in range(600):
            samples.append((1 << HSA.bit) if (index % 10) < 3 else 0)
        dead = measure_dead_time(samples, HSA, LSA, SAMPLE_PERIOD_NS)
        self.assertEqual(dead.edges, 0)


class OverlapTests(unittest.TestCase):
    def test_clean_waveform_has_no_overlap(self):
        samples = synth_complementary(5312 * 20, 5312, 2656, 93)
        self.assertEqual(count_overlap(samples, HSA, LSA), 0)

    def test_overlap_is_counted(self):
        samples = [0, (1 << HSA.bit) | (1 << LSA.bit), 1 << HSA.bit]
        self.assertEqual(count_overlap(samples, HSA, LSA), 1)


class TimelineTests(unittest.TestCase):
    def test_sector_patterns_appear_in_order_with_durations(self):
        channels = [LSA, HSA, HSB, HSC]
        samples = [1 << HSA.bit] * 100 + [1 << HSB.bit] * 100 + [1 << HSC.bit] * 100
        timeline = pattern_timeline(samples, channels, SAMPLE_PERIOD_NS)

        self.assertEqual([entry["gates"] for entry in timeline],
                         [["HSA"], ["HSB"], ["HSC"]])
        for entry in timeline:
            self.assertAlmostEqual(entry["duration_ns"], 100 * SAMPLE_PERIOD_NS, delta=1.0)

    def test_transients_shorter_than_the_threshold_are_dropped(self):
        channels = [LSA, HSA]
        samples = [1 << HSA.bit] * 50 + [0] + [1 << LSA.bit] * 50
        self.assertEqual(len(pattern_timeline(samples, channels, SAMPLE_PERIOD_NS)), 2)


class AnalyseTests(unittest.TestCase):
    def test_full_report_passes_a_clean_capture(self):
        samples = synth_complementary(5312 * 60, 5312, 1594, 93)
        report = analyse(samples, [LSA, HSA, HSB, HSC], SAMPLE_PERIOD_NS, [("A", HSA, LSA)])

        self.assertTrue(report["shoot_through_free"])
        self.assertEqual(report["overlap_samples_total"], 0)
        phase = report["phases"]["A"]
        self.assertAlmostEqual(phase["pwm"]["duty_percent"], 30.0, delta=0.5)
        self.assertAlmostEqual(phase["dead_time"]["mean_ns"], 547.0, delta=20.0)

    def test_full_report_flags_a_capture_with_overlap(self):
        samples = synth_complementary(5312 * 10, 5312, 1594, 93)
        samples[100] |= (1 << HSA.bit) | (1 << LSA.bit)
        report = analyse(samples, [LSA, HSA], SAMPLE_PERIOD_NS, [("A", HSA, LSA)])

        self.assertFalse(report["shoot_through_free"])
        self.assertEqual(report["overlap_samples_total"], 1)


if __name__ == "__main__":
    unittest.main()
