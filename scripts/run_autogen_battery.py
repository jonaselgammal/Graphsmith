#!/usr/bin/env python3
"""Run a small end-to-end battery for auto skill generation."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BATTERY_PATH = ROOT / "specs" / "autogen_prompt_battery.json"


def _run_case(case: dict[str, object], output_dir: Path) -> tuple[bool, str]:
    goal = str(case["goal"])
    expected = str(case["expected"])
    must_contain = [str(x) for x in case.get("must_contain", [])]
    cmd = [
        sys.executable, "-m", "graphsmith.cli.main",
        "create-skill-from-goal", goal,
        "--output-dir", str(output_dir),
    ]
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    output = (proc.stdout or "") + (proc.stderr or "")

    if expected == "pass":
        ok = proc.returncode == 0
    else:
        ok = proc.returncode != 0
    if ok:
        ok = all(text in output for text in must_contain)
    return ok, output


def main() -> int:
    cases = json.loads(BATTERY_PATH.read_text(encoding="utf-8"))
    print("\n  Autogen Battery")
    print("  " + "=" * 32)

    failed = 0
    with tempfile.TemporaryDirectory() as tmpdir:
        out_root = Path(tmpdir)
        for case in cases:
            goal = str(case["goal"])
            ok, output = _run_case(case, out_root)
            mark = "PASS" if ok else "FAIL"
            print(f"  [{mark}] {goal}")
            if not ok:
                failed += 1
                preview = "\n".join(output.strip().splitlines()[:8])
                if preview:
                    print(preview)
                    print()

    print("")
    if failed:
        print(f"  {failed} battery case(s) failed.")
        print("")
        return 1

    print(f"  All {len(cases)} battery cases passed.")
    print("")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
