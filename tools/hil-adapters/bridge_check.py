"""Check the six-step bridge table the firmware actually programmed.

The firmware walks all six sectors with MOE clear and records TIM1's CCER,
CCMR1 and CCMR2 for each. This module derives what those registers must be
straight from the table in docs/motor-control-spec.md §8 and compares.

That is a real check, not a tautology: the specification defines each sector as
source / sink / floating phases, and the firmware has to express that through
two different registers -- OCxM for the role and CCxE/CCxNE for which output is
enabled. This catches a sector table that is right on paper and wrong in the
encoding, which is exactly the class of bug that would put a high side and a
low side on at once.
"""

from __future__ import annotations

SOURCE, SINK, FLOAT = "source", "sink", "float"

# docs/motor-control-spec.md §8, transcribed independently of the firmware:
# sector -> (phase A role, phase B role, phase C role).
SPEC_SECTORS = [
    (SOURCE, SINK, FLOAT),   # 0: A -> B, C floating, expect C rising
    (SOURCE, FLOAT, SINK),   # 1: A -> C, B floating, expect B falling
    (FLOAT, SOURCE, SINK),   # 2: B -> C, A floating, expect A rising
    (SINK, SOURCE, FLOAT),   # 3: B -> A, C floating, expect C falling
    (SINK, FLOAT, SOURCE),   # 4: C -> A, B floating, expect B rising
    (FLOAT, SINK, SOURCE),   # 5: C -> B, A floating, expect A falling
]

# TIM1 bit positions (CMSIS stm32g431xx.h).
CC1E, CC1NE = 1 << 0, 1 << 2
CC2E, CC2NE = 1 << 4, 1 << 6
CC3E, CC3NE = 1 << 8, 1 << 10
ENABLES = ((CC1E, CC1NE), (CC2E, CC2NE), (CC3E, CC3NE))

OC1M_POS, OC2M_POS, OC3M_POS = 4, 12, 4
OC1PE, OC2PE, OC3PE = 1 << 3, 1 << 11, 1 << 3

OCM_FORCE_INACTIVE = 4
OCM_PWM1 = 6


def expected_registers(roles: tuple[str, str, str]) -> dict[str, int]:
    ccer = 0
    for index, role in enumerate(roles):
        enable, enable_n = ENABLES[index]
        if role == SOURCE:
            ccer |= enable
        elif role == SINK:
            ccer |= enable_n

    def mode(role: str) -> int:
        return OCM_PWM1 if role == SOURCE else OCM_FORCE_INACTIVE

    ccmr1 = (mode(roles[0]) << OC1M_POS) | OC1PE | (mode(roles[1]) << OC2M_POS) | OC2PE
    ccmr2 = (mode(roles[2]) << OC3M_POS) | OC3PE
    return {"ccer": ccer, "ccmr1": ccmr1, "ccmr2": ccmr2}


def describe(roles: tuple[str, str, str]) -> str:
    return " ".join(f"{name}={role}" for name, role in zip("ABC", roles))


def check(sectors: list[dict[str, int]]) -> dict[str, object]:
    """Compare recorded registers against the specification, sector by sector."""
    if len(sectors) != len(SPEC_SECTORS):
        return {"ok": False, "error": f"expected {len(SPEC_SECTORS)} sectors, got {len(sectors)}"}

    results = []
    ok = True
    for index, (recorded, roles) in enumerate(zip(sectors, SPEC_SECTORS)):
        want = expected_registers(roles)
        # OCxM's high bit (OCxM_3) and the rest of CCMR are not part of what
        # this check owns, so compare only the fields the sector defines.
        mask1 = (0x7 << OC1M_POS) | OC1PE | (0x7 << OC2M_POS) | OC2PE
        mask2 = (0x7 << OC3M_POS) | OC3PE
        entry = {
            "sector": index,
            "roles": describe(roles),
            "ccer": {"want": f"{want['ccer']:#06x}", "got": f"{recorded['ccer']:#06x}"},
            "ccmr1": {"want": f"{want['ccmr1'] & mask1:#06x}", "got": f"{recorded['ccmr1'] & mask1:#06x}"},
            "ccmr2": {"want": f"{want['ccmr2'] & mask2:#06x}", "got": f"{recorded['ccmr2'] & mask2:#06x}"},
        }
        entry["ok"] = (
            recorded["ccer"] == want["ccer"]
            and (recorded["ccmr1"] & mask1) == (want["ccmr1"] & mask1)
            and (recorded["ccmr2"] & mask2) == (want["ccmr2"] & mask2)
        )
        ok = ok and entry["ok"]
        results.append(entry)

    # No sector may enable a high side and a low side of the same phase.
    overlaps = []
    for index, recorded in enumerate(sectors):
        for phase, (enable, enable_n) in zip("ABC", ENABLES):
            if (recorded["ccer"] & enable) and (recorded["ccer"] & enable_n):
                overlaps.append(f"sector {index} phase {phase}")
    if overlaps:
        ok = False

    return {"ok": ok, "sectors": results, "both_gates_enabled": overlaps}
