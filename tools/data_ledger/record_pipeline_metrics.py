"""Refreshes the `current` block of pipeline_metrics.json from a real coverage
run, so the ledger's confidence panel never drifts into stale hand-typed
numbers.

    python -m pytest --cov=src/epcot_fw --cov-report=json:coverage.json -q
    python tools/data_ledger/record_pipeline_metrics.py coverage.json

The `baseline` block is deliberately left alone - it is a historical
measurement of a specific commit and is not recomputable from the current
working tree.
"""

import datetime
import json
import subprocess
import sys
from pathlib import Path

METRICS_PATH = Path(__file__).parent / "pipeline_metrics.json"


def _current_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(__file__).resolve().parents[2],
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def build_current(coverage_report: dict, *, tests: int | None, commit: str | None) -> dict:
    totals = coverage_report["totals"]
    return {
        "label": "Current",
        "commit": commit,
        "measured_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "tests": tests,
        "coverage_pct": round(totals["percent_covered"], 1),
        "covered_lines": totals["covered_lines"],
        "num_statements": totals["num_statements"],
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2

    coverage_report = json.loads(Path(argv[1]).read_text())
    tests = int(argv[2]) if len(argv) > 2 else None

    payload = json.loads(METRICS_PATH.read_text()) if METRICS_PATH.exists() else {}
    payload["current"] = build_current(coverage_report, tests=tests, commit=_current_commit())
    METRICS_PATH.write_text(json.dumps(payload, indent=2) + "\n")

    print(
        f"wrote {METRICS_PATH}: {payload['current']['coverage_pct']}% "
        f"({payload['current']['covered_lines']}/{payload['current']['num_statements']} statements)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
