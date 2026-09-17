#!/usr/bin/env python3
"""hilctl `build`: configure (once) and build the firmware ELF.

Kept as an adapter rather than a bare `cmake --build` argv so that a missing
build tree self-configures and so that the failure message says which part
went wrong. hilctl checks separately that the artifact exists, is an ARM ELF
whose entry point lies in this part's flash, and was actually refreshed by
this build.

Usage: build.py [cmake-target]
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD_DIR = ROOT / "build"
TOOLCHAIN = ROOT / "cmake" / "arm-none-eabi.cmake"


def run(argv: list[str]) -> int:
    print("+ " + " ".join(argv), flush=True)
    return subprocess.run(argv, cwd=ROOT, text=True, check=False).returncode


def main(argv: list[str]) -> int:
    if not (ROOT / "CMakeLists.txt").exists():
        print("no CMakeLists.txt at the repository root: firmware is not implemented yet",
              file=sys.stderr)
        return 3
    if not (BUILD_DIR / "CMakeCache.txt").exists():
        configure = [
            "cmake", "-S", str(ROOT), "-B", str(BUILD_DIR),
            "-DCMAKE_BUILD_TYPE=RelWithDebInfo",
        ]
        if TOOLCHAIN.exists():
            configure.append(f"-DCMAKE_TOOLCHAIN_FILE={TOOLCHAIN}")
        code = run(configure)
        if code != 0:
            return code
    # Remove the ELF before building. hilctl refuses to flash an artifact whose
    # mtime and hash are unchanged, to catch a build that silently did nothing
    # -- but that also rejects a trial whose one change lives outside the
    # firmware (a host-side analysis fix, a different duty), and every such
    # rejection disarms the campaign and costs a human re-arm.
    #
    # Deleting first makes the check stricter, not weaker: if the build fails
    # or produces nothing, there is no artifact at all and hilctl stops with
    # "firmware artifact missing after build" instead of flashing a stale one.
    artifact = BUILD_DIR / "ecia_bldc.elf"
    artifact.unlink(missing_ok=True)

    build = ["cmake", "--build", str(BUILD_DIR), "-j", str(os.cpu_count() or 1)]
    if len(argv) > 1:
        build += ["--target", argv[1]]
    return run(build)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
