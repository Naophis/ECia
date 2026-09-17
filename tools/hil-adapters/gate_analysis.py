"""Turn an on-chip gate capture into the Milestone 1 measurements.

The capture is a free-running DMA stream of a GPIO input register, so each
entry is one sample of every pin in that port at a fixed interval. See
docs/on-chip-capture.md for how it is produced and why the sample clock is
deliberately incommensurate with the PWM period.

Nothing here touches hardware, which is the point: the analysis is unit-tested
against synthesised waveforms with a known answer before it is ever pointed at
the board.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence


@dataclass(frozen=True)
class Channel:
    """One gate signal and the port bit it is sampled on."""

    name: str
    bit: int


@dataclass
class DeadTime:
    edges: int = 0
    histogram: dict[int, int] = field(default_factory=dict)
    mean_samples: float = 0.0
    mean_ns: float = 0.0
    min_samples: int = 0
    max_samples: int = 0


@dataclass
class Pwm:
    periods: int = 0
    period_ns: float = 0.0
    frequency_hz: float = 0.0
    duty_percent: float = 0.0


def bit_series(samples: Sequence[int], bit: int) -> list[int]:
    mask = 1 << bit
    return [1 if (sample & mask) else 0 for sample in samples]


def runs(series: Sequence[int]) -> list[tuple[int, int, int]]:
    """[(value, start_index, length), ...] for consecutive equal values."""
    result: list[tuple[int, int, int]] = []
    if not series:
        return result
    value = series[0]
    start = 0
    for index in range(1, len(series)):
        if series[index] != value:
            result.append((value, start, index - start))
            value = series[index]
            start = index
    result.append((value, start, len(series) - start))
    return result


def measure_pwm(samples: Sequence[int], high_side: Channel, sample_period_ns: float) -> Pwm:
    """Period and duty of one high-side gate.

    Only whole periods between successive rising edges are used, and the first
    and last runs are ignored: the capture starts and stops at an arbitrary
    phase, so those two are truncated and would drag the mean down.
    """
    series = bit_series(samples, high_side.bit)
    blocks = runs(series)
    if len(blocks) < 4:
        return Pwm()
    interior = blocks[1:-1]
    rising = [start for value, start, _ in interior if value == 1]
    if len(rising) < 2:
        return Pwm()
    period_samples = (rising[-1] - rising[0]) / (len(rising) - 1)
    highs = [length for value, _, length in interior if value == 1]
    duty = (sum(highs) / len(highs)) / period_samples if period_samples else 0.0
    period_ns = period_samples * sample_period_ns
    return Pwm(
        periods=len(rising) - 1,
        period_ns=period_ns,
        frequency_hz=1e9 / period_ns if period_ns else 0.0,
        duty_percent=duty * 100.0,
    )


def measure_dead_time(
    samples: Sequence[int],
    high_side: Channel,
    low_side: Channel,
    sample_period_ns: float,
) -> DeadTime:
    """Width of the both-gates-low gap at every complementary transition.

    With a free-running sampler whose phase slides across the waveform, the
    expected number of samples landing inside a gap of true width w (in sample
    periods) is exactly w. The mean run length over many edges is therefore an
    unbiased estimate, and resolves far below one sample -- which is what makes
    a 58.8 ns sampler good enough for a ~550 ns dead time.

    Only gaps bracketed by opposite gates are counted. A stretch with both
    gates low because the phase is *floating* is not a dead time, and is
    excluded by requiring the gate before the gap and the gate after it to
    differ.
    """
    high = bit_series(samples, high_side.bit)
    low = bit_series(samples, low_side.bit)
    both_low = [1 if (not h and not l) else 0 for h, l in zip(high, low)]

    result = DeadTime()
    for value, start, length in runs(both_low):
        if value != 1 or start == 0 or start + length >= len(both_low):
            continue  # truncated by the capture window, or not a gap
        before_high, before_low = high[start - 1], low[start - 1]
        after_high, after_low = high[start + length], low[start + length]
        if (before_high, before_low) == (after_high, after_low):
            continue  # same gate resumed: a PWM off-time, not a commutation gap
        if before_high == after_high and before_low == after_low:
            continue
        result.edges += 1
        result.histogram[length] = result.histogram.get(length, 0) + 1

    if result.edges:
        total = sum(length * count for length, count in result.histogram.items())
        result.mean_samples = total / result.edges
        result.mean_ns = result.mean_samples * sample_period_ns
        result.min_samples = min(result.histogram)
        result.max_samples = max(result.histogram)
    return result


def count_overlap(samples: Sequence[int], high_side: Channel, low_side: Channel) -> int:
    """Samples where both gates of one phase are high.

    Must be zero. The MP6540HA turns that combination into high impedance
    rather than shoot-through, so this is defence in depth -- but a nonzero
    count means the dead-time configuration is wrong, which is a fault.
    """
    mask = (1 << high_side.bit) | (1 << low_side.bit)
    return sum(1 for sample in samples if (sample & mask) == mask)


def pattern_timeline(
    samples: Sequence[int],
    channels: Iterable[Channel],
    sample_period_ns: float,
    min_samples: int = 2,
) -> list[dict[str, object]]:
    """Stable gate patterns in order, with their durations.

    Patterns shorter than `min_samples` are dropped: every commutation passes
    through transient combinations while the dead time elapses, and those are
    not sectors.
    """
    channels = list(channels)
    packed = []
    for sample in samples:
        value = 0
        for index, channel in enumerate(channels):
            if sample & (1 << channel.bit):
                value |= 1 << index
        packed.append(value)

    timeline = []
    for value, start, length in runs(packed):
        if length < min_samples:
            continue
        timeline.append({
            "pattern": "".join(
                "1" if value & (1 << index) else "0" for index in range(len(channels))
            ),
            "gates": [channel.name for index, channel in enumerate(channels) if value & (1 << index)],
            "start_ns": round(start * sample_period_ns, 1),
            "duration_ns": round(length * sample_period_ns, 1),
        })
    return timeline


def analyse(
    samples: Sequence[int],
    channels: Sequence[Channel],
    sample_period_ns: float,
    phase_pairs: Sequence[tuple[str, Channel, Channel]],
) -> dict[str, object]:
    """The whole Milestone 1 verdict for one capture.

    `phase_pairs` is (phase name, high-side channel, low-side channel); only
    phases whose both gates live in the captured port can be given.
    """
    report: dict[str, object] = {
        "samples": len(samples),
        "sample_period_ns": sample_period_ns,
        "window_us": round(len(samples) * sample_period_ns / 1000.0, 1),
        "phases": {},
        "timeline": pattern_timeline(samples, channels, sample_period_ns),
    }
    overlaps = 0
    for phase, high_side, low_side in phase_pairs:
        pwm = measure_pwm(samples, high_side, sample_period_ns)
        dead = measure_dead_time(samples, high_side, low_side, sample_period_ns)
        overlap = count_overlap(samples, high_side, low_side)
        overlaps += overlap
        report["phases"][phase] = {
            "high_side": high_side.name,
            "low_side": low_side.name,
            "pwm": vars(pwm),
            "dead_time": vars(dead),
            "overlap_samples": overlap,
        }
    report["overlap_samples_total"] = overlaps
    report["shoot_through_free"] = overlaps == 0
    return report
