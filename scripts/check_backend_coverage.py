from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

MINIMUM_LINE_PERCENT = 90.0
MINIMUM_BRANCH_PERCENT = 85.0


def percentages(report: dict[str, Any]) -> tuple[float, float]:
    totals = report["totals"]
    statements = int(totals["num_statements"])
    branches = int(totals["num_branches"])
    if statements <= 0 or branches <= 0:
        raise ValueError("Coverage report neobsahuje měřitelné řádky a větve.")
    line_percent = 100 * int(totals["covered_lines"]) / statements
    branch_percent = 100 * int(totals["covered_branches"]) / branches
    return line_percent, branch_percent


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("Použití: check_backend_coverage.py COVERAGE_JSON")
    path = Path(sys.argv[1])
    report = json.loads(path.read_text(encoding="utf-8"))
    line_percent, branch_percent = percentages(report)
    print(
        f"Backend coverage: lines={line_percent:.2f}% "
        f"(minimum {MINIMUM_LINE_PERCENT:.2f}%), branches={branch_percent:.2f}% "
        f"(minimum {MINIMUM_BRANCH_PERCENT:.2f}%)."
    )
    if line_percent < MINIMUM_LINE_PERCENT or branch_percent < MINIMUM_BRANCH_PERCENT:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
