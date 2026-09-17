"""Verify that a partially-corrupted SWD read is refused, not believed.

This bench's ST-LINK returned a 24-word block whose tail was stitched together
from the wrong addresses: the head magic was perfect, every early field was
right, and only the last four words were wrong. Nothing in the data looked
suspicious. The firmware's own disassembly was the only way to tell.

Blocks that change while the firmware runs cannot be validated by reading them
twice, so they carry a magic at both ends. These tests hold that contract.
"""

import importlib
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "hil-adapters"))

run_trial = importlib.import_module("run_trial")
from ocd import AdapterError  # noqa: E402


BASE = 0x20003000


def state_words(tail=run_trial.HIL_TAIL_MAGIC, magic=run_trial.HIL_MAGIC):
    words = [0] * len(run_trial.STATE_FIELDS)
    words[0] = magic
    words[1] = run_trial.ABI_VERSION
    words[-1] = tail
    return words


class StubSession:
    def __init__(self, words, corrupt_tail=0):
        self.words = list(words)
        self.corrupt_tail = corrupt_tail
        self.read_retries = 0

    def read_block(self, address, count, verify=True):
        offset = (address - BASE) // 4
        out = self.words[offset:offset + count]
        if self.corrupt_tail:
            out = out[:-self.corrupt_tail] + [0xDEADBEEF] * self.corrupt_tail
        return out


class SentinelTests(unittest.TestCase):
    def test_an_intact_block_is_accepted(self):
        state = run_trial.read_struct(StubSession(state_words()), BASE, run_trial.STATE_FIELDS)
        self.assertEqual(state["magic"], run_trial.HIL_MAGIC)
        self.assertEqual(state["tail_magic"], run_trial.HIL_TAIL_MAGIC)

    def test_a_corrupted_tail_is_refused_even_though_the_head_is_perfect(self):
        session = StubSession(state_words(), corrupt_tail=4)
        with self.assertRaises(AdapterError) as caught:
            run_trial.read_struct(session, BASE, run_trial.STATE_FIELDS, retries=2)
        self.assertIn("tail magic", str(caught.exception))
        # Retried before giving up: a bad read is a transport fault, not a result.
        self.assertEqual(session.read_retries, 2)

    def test_a_tail_that_is_only_briefly_wrong_is_retried_and_accepted(self):
        session = StubSession(state_words(), corrupt_tail=4)

        original = session.read_block

        def recover(address, count, verify=True):
            session.corrupt_tail = 0  # the next read comes back clean
            return original(address, count, verify)

        session.read_block = recover
        state = run_trial.read_struct(session, BASE, run_trial.STATE_FIELDS, retries=2)
        self.assertEqual(state["tail_magic"], run_trial.HIL_TAIL_MAGIC)

    def test_a_wrong_head_magic_is_refused(self):
        session = StubSession(state_words(magic=0x12345678))
        with self.assertRaises(AdapterError) as caught:
            run_trial.read_struct(session, BASE, run_trial.STATE_FIELDS, retries=1)
        self.assertIn("head magic", str(caught.exception))

    def test_the_boot_poll_may_see_an_uninitialised_block_without_raising(self):
        # Before hil_init() runs, the block is all zeroes; the poll has to be
        # able to look at that and simply wait, not fail the trial.
        session = StubSession([0] * len(run_trial.STATE_FIELDS))
        state = run_trial.read_struct(session, BASE, run_trial.STATE_FIELDS,
                                      require_sentinels=False)
        self.assertEqual(state["magic"], 0)


class VerifiedReadTests(unittest.TestCase):
    """Static blocks are validated by reading them twice instead.

    Double-reading and the tail sentinel cover different failures and neither
    subsumes the other: reading twice catches corruption that varies between
    reads, and the sentinel catches corruption that is reproducible. A
    deterministic bad read agrees with itself, which is why both exist.
    """

    class FlakySession:
        """Corrupts the tail of the first `flaky_reads` reads, differently each time."""

        def __init__(self, words, flaky_reads=1):
            self.words = list(words)
            self.remaining = flaky_reads
            self.reads = 0

        def _read_once(self, address, count):
            self.reads += 1
            out = self.words[(address - BASE) // 4:][:count]
            if self.remaining > 0:
                self.remaining -= 1
                return out[:-1] + [0xBADF00D + self.reads]
            return out

        read_block = None  # bound to OpenOCD.read_block in each test

    def test_double_reading_catches_a_transient_bad_read(self):
        from ocd import OpenOCD

        session = self.FlakySession(list(range(24)), flaky_reads=1)
        session.read_block = lambda a, c, verify=True: OpenOCD.read_block(session, a, c, verify)
        session.verify_retries = 3
        session.read_retries = 0

        values = session.read_block(BASE, 24)
        self.assertEqual(values, list(range(24)))
        self.assertGreaterEqual(session.read_retries, 1)

    def test_a_read_that_never_settles_raises(self):
        from ocd import OpenOCD

        session = self.FlakySession(list(range(24)), flaky_reads=99)
        session.read_block = lambda a, c, verify=True: OpenOCD.read_block(session, a, c, verify)
        session.verify_retries = 3
        session.read_retries = 0

        with self.assertRaises(AdapterError):
            session.read_block(BASE, 24)


if __name__ == "__main__":
    unittest.main()
