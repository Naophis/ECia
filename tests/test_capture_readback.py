"""Verify how the trial adapter reads and validates the on-chip gate capture.

A stub debugger session stands in for OpenOCD, so the header validation, the
byte-order handling and the saved artefact are all checked without a probe --
and before any firmware exists to produce a real capture.
"""

import importlib
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ADAPTERS = Path(__file__).resolve().parents[1] / "tools" / "hil-adapters"
sys.path.insert(0, str(ADAPTERS))

run_trial = importlib.import_module("run_trial")


GPIOA_IDR = 0x48000010
SYSCLK_HZ = 170_000_000
TICKS_PER_SAMPLE = 10
CAPTURE_BASE = 0x20001000


def build_blob(
    samples,
    magic=run_trial.HIL_CAPTURE_MAGIC,
    abi=run_trial.ABI_VERSION,
    port_base=GPIOA_IDR,
    declared=None,
    capacity=None,
    sysclk_hz=SYSCLK_HZ,
    ticks=TICKS_PER_SAMPLE,
    seq=7,
):
    declared = len(samples) if declared is None else declared
    capacity = max(len(samples), declared) if capacity is None else capacity
    header = struct.pack(
        "<8I", magic, abi, port_base, declared, capacity, sysclk_hz, ticks, seq
    )
    body = struct.pack(f"<{len(samples)}H", *samples)
    if len(body) % 4:
        body += b"\x00\x00"
    return header + body


class StubSession:
    """Serves word reads out of a flat blob mapped at CAPTURE_BASE."""

    def __init__(self, blob, base=CAPTURE_BASE):
        self.blob = blob
        self.base = base
        self.reads = 0

    def _slice(self, address, length):
        offset = address - self.base
        if offset < 0 or offset + length > len(self.blob):
            raise AssertionError(f"read outside the blob: {address:#x}+{length}")
        return self.blob[offset:offset + length]

    def read_block(self, address, words):
        self.reads += 1
        return list(struct.unpack(f"<{words}I", self._slice(address, words * 4)))

    def read_bytes(self, address, length, chunk_words=512):
        self.reads += 1
        return self._slice(address, length)


def synth(period_ticks=5312, duty_ticks=1594, dead_ticks=93, periods=60):
    """The same complementary waveform the analyser tests use."""
    high_bit, low_bit = 8, 7
    values = []
    total = period_ticks * periods
    for index in range(total // TICKS_PER_SAMPLE):
        position = (index * TICKS_PER_SAMPLE) % period_ticks
        value = 0
        if position < duty_ticks:
            value |= 1 << high_bit
        elif position < duty_ticks + dead_ticks:
            pass
        elif position < period_ticks - dead_ticks:
            value |= 1 << low_bit
        values.append(value)
    return values


class CaptureReadbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.original_root = run_trial.ROOT
        run_trial.ROOT = self.root

    def tearDown(self):
        run_trial.ROOT = self.original_root
        self.tmp.cleanup()

    def read(self, blob, trial_id="t1"):
        return run_trial.read_capture(StubSession(blob), CAPTURE_BASE, trial_id)

    def test_valid_capture_is_measured_and_saved(self):
        values = synth()
        report, error = self.read(build_blob(values))

        self.assertIsNone(error)
        self.assertEqual(report["samples"], len(values))
        self.assertTrue(report["shoot_through_free"])
        self.assertEqual(report["port_base"], f"{GPIOA_IDR:#010x}")
        self.assertEqual(report["seq"], 7)

        phase = report["phases"]["A"]
        self.assertAlmostEqual(phase["pwm"]["duty_percent"], 30.0, delta=0.5)
        self.assertAlmostEqual(phase["dead_time"]["mean_ns"], 93 / SYSCLK_HZ * 1e9, delta=20.0)

        saved = self.root / ".hil" / "logs" / "t1" / "gate-capture.bin"
        self.assertTrue(saved.exists())
        self.assertEqual(len(saved.read_bytes()), len(values) * 2)

    def test_overlap_in_the_capture_is_reported(self):
        values = synth(periods=10)
        values[100] |= (1 << 8) | (1 << 7)
        report, error = self.read(build_blob(values))

        self.assertIsNone(error)
        self.assertFalse(report["shoot_through_free"])
        self.assertEqual(report["overlap_samples_total"], 1)

    def test_wrong_magic_is_refused(self):
        report, error = self.read(build_blob(synth(periods=4), magic=0xDEADBEEF))
        self.assertIsNone(report)
        self.assertIn("magic", error)

    def test_wrong_abi_version_is_refused(self):
        report, error = self.read(build_blob(synth(periods=4), abi=99))
        self.assertIsNone(report)
        self.assertIn("abi_version", error)

    def test_empty_capture_is_not_an_error_report(self):
        report, error = self.read(build_blob([], declared=0, capacity=4096))
        self.assertIsNone(report)
        self.assertIn("empty", error)

    def test_sample_count_beyond_capacity_is_refused(self):
        values = synth(periods=4)
        report, error = self.read(build_blob(values, declared=len(values), capacity=4))
        self.assertIsNone(report)
        self.assertIn("buffer", error)

    def test_unknown_port_is_refused(self):
        report, error = self.read(build_blob(synth(periods=4), port_base=0x40000000))
        self.assertIsNone(report)
        self.assertIn("GPIO IDR", error)

    def test_unusable_timebase_is_refused(self):
        report, error = self.read(build_blob(synth(periods=4), ticks=0))
        self.assertIsNone(report)
        self.assertIn("timebase", error)

    def test_a_port_without_a_full_phase_still_reports_a_timeline(self):
        # GPIOF carries only LSC, so there is no phase to measure dead time on,
        # but the sector timeline must still come back.
        values = [1, 1, 1, 0, 0, 0, 1, 1, 1]
        report, error = self.read(build_blob(values, port_base=0x48001410))

        self.assertIsNone(error)
        self.assertEqual(report["phases"], {})
        self.assertEqual(len(report["timeline"]), 3)


if __name__ == "__main__":
    unittest.main()
