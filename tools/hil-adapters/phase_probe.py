"""Interpret the phase-probe sweep: six FETs, one at a time, and VIN.

Each step drives exactly one gate of one phase at 100 % while the other two
phases are left high impedance. With no return path through the motor, nothing
carries current -- so this verifies every FET and measures the supply on a
board whose motor cannot be unsoldered.

Raw ADC counts are referred to the factory VREFINT calibration rather than to
an assumed 3.3 V rail, then scaled back up through the divider.
"""

from __future__ import annotations

# ST factory calibration, stm32g4xx_ll_adc.h: VREFINT_CAL is the VREFINT
# reading taken at Vref+ = 3.000 V, stored at 0x1FFF75AA.
VREFINT_CAL_ADDR = 0x1FFF75AA
VREFINT_CAL_VREF_MV = 3000
ADC_FULL_SCALE = 4095

# docs/hardware-mapping.md: phase -> 56k -> pin -> 10k -> GND.
DIVIDER_NUM = 10
DIVIDER_DEN = 66

PHASE_NAMES = ("A", "B", "C")


def vdda_mv(vrefint_raw: int, vrefint_cal: int) -> float:
    if not vrefint_raw:
        return 0.0
    return VREFINT_CAL_VREF_MV * vrefint_cal / vrefint_raw


def node_mv(raw: int, vdda: float) -> float:
    """Phase-node voltage, undoing the divider."""
    return raw * vdda / ADC_FULL_SCALE * DIVIDER_DEN / DIVIDER_NUM


def describe_step(step: dict[str, int]) -> str:
    if step["phase"] >= len(PHASE_NAMES):
        return "all gates off"
    return f"{PHASE_NAMES[step['phase']]} {'high' if step['high_side'] else 'low'} side on"


def analyse(steps: list[dict[str, int]], vrefint_cal: int,
            high_fraction: float = 0.8, low_mv: float = 500.0) -> dict[str, object]:
    """Turn the sweep into a per-FET verdict and a VIN estimate.

    A driven high side must pull its own phase node close to VIN and must not
    move the other two; a driven low side must pull it near ground. VIN itself
    is taken as the median of the high-side readings, which needs no assumption
    about which phase is which.
    """
    rows = []
    high_readings = []
    for step in steps:
        vdda = vdda_mv(step["vrefint"], vrefint_cal)
        nodes = [node_mv(step[f"phase_{name.lower()}"], vdda) for name in PHASE_NAMES]
        row = {
            "step": step["step"],
            "drive": describe_step(step),
            "vdda_mv": round(vdda, 1),
            "node_mv": {name: round(value, 1) for name, value in zip(PHASE_NAMES, nodes)},
            "ccer": f"{step['ccer']:#06x}",
        }
        if step["phase"] < len(PHASE_NAMES):
            driven = nodes[step["phase"]]
            others = [v for i, v in enumerate(nodes) if i != step["phase"]]
            row["driven_mv"] = round(driven, 1)
            row["others_mv"] = [round(v, 1) for v in others]
            if step["high_side"]:
                high_readings.append(driven)
        rows.append(row)

    vin_mv = 0.0
    if high_readings:
        ordered = sorted(high_readings)
        vin_mv = ordered[len(ordered) // 2]

    verdicts = {}
    for step, row in zip(steps, rows):
        if step["phase"] >= len(PHASE_NAMES):
            continue
        name = f"{PHASE_NAMES[step['phase']]}{'H' if step['high_side'] else 'L'}"
        driven = row["driven_mv"]
        if step["high_side"]:
            ok = vin_mv > 0 and driven >= vin_mv * high_fraction
            want = f">= {round(vin_mv * high_fraction, 1)} mV"
        else:
            ok = driven <= low_mv
            want = f"<= {low_mv} mV"
        verdicts[name] = {"ok": bool(ok), "driven_mv": driven, "expected": want}

    return {
        "ok": all(v["ok"] for v in verdicts.values()) and len(verdicts) == 6,
        "vin_mv": round(vin_mv, 1),
        "fets": verdicts,
        "steps": rows,
    }
