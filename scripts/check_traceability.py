from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument(
    "--allow-unverified",
    action="store_true",
    help="Ověří úplnost matice, ale nevyžaduje release stav implemented_verified.",
)
parser.add_argument(
    "--evidence-dir",
    type=Path,
    help="Adresář čerstvých důkazů úplné release brány.",
)
args = parser.parse_args()
items = json.loads((root / "docs/traceability/requirements.json").read_text())
ids = [item["id"] for item in items]
if len(ids) != len(set(ids)):
    raise SystemExit("Matice obsahuje duplicitní identifikátory.")
chapters = {identifier.split(".")[0] for identifier in ids}
if chapters != {str(i) for i in range(21)}:
    raise SystemExit(f"Matice nepokrývá kapitoly 0 až 20: {sorted(chapters)}")
for item in items:
    if (
        not item.get("implementation")
        or not item.get("verification")
        or not item.get("evidence")
        or not item.get("status")
    ):
        raise SystemExit(f"Neúplná vazba požadavku {item.get('id')}")
    if not re.fullmatch(r"\d{1,2}\.\d+", item["id"]):
        raise SystemExit(f"Neplatný identifikátor {item['id']}")
    for linked_path in item["implementation"] + item["verification"]:
        if not (root / linked_path).exists():
            raise SystemExit(
                f"Požadavek {item['id']} odkazuje na neexistující cestu {linked_path}."
            )
    for evidence_path in item["evidence"]:
        if not evidence_path.startswith("release/evidence/generated/"):
            raise SystemExit(
                f"Požadavek {item['id']} odkazuje mimo release evidence: {evidence_path}."
            )
counts = Counter(item["status"] for item in items)
print(
    f"Matice strukturálně pokrývá {len(items)} požadavků kapitol 0 až 20; "
    + ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))
    + "."
)
if not args.allow_unverified:
    blocked = [item["id"] for item in items if item["status"] != "implemented_verified"]
    if blocked:
        preview = ", ".join(blocked[:12])
        raise SystemExit(
            f"Release traceability není uzavřena: {len(blocked)} požadavků není implemented_verified "
            f"(např. {preview})."
        )
    if args.evidence_dir is None:
        raise SystemExit("Release traceability vyžaduje --evidence-dir.")
    evidence = args.evidence_dir.resolve()
    for item in items:
        for evidence_path in item["evidence"]:
            declared = (root / evidence_path).resolve()
            if declared.parent != evidence:
                raise SystemExit(
                    f"Důkaz požadavku {item['id']} není v čerstvém evidence adresáři: "
                    f"{evidence_path}."
                )
            if not declared.is_file():
                raise SystemExit(
                    f"Chybí deklarovaný důkaz požadavku {item['id']}: {evidence_path}."
                )
    required_junit = [
        "backend-coverage-tests.xml",
        "contract.xml",
        "integration.xml",
        "e2e.xml",
        "accessibility.xml",
        "visual.xml",
        "ai-eval.xml",
        "performance.xml",
        "security.xml",
        "acceptance.xml",
    ]
    requirement_classes: set[str] = set()
    for name in required_junit:
        path = evidence / name
        if not path.is_file():
            raise SystemExit(f"Chybí čerstvý JUnit důkaz {path}.")
        document = ET.parse(path)
        suites = document.getroot()
        tests = sum(int(suite.get("tests", "0")) for suite in suites.iter("testsuite"))
        failures = sum(
            int(suite.get("failures", "0")) + int(suite.get("errors", "0"))
            for suite in suites.iter("testsuite")
        )
        if tests <= 0 or failures:
            raise SystemExit(
                f"Důkaz {name} není úspěšný: tests={tests}, failures+errors={failures}."
            )
        if name == "backend-coverage-tests.xml":
            requirement_classes = {
                case.get("classname", "") for case in suites.iter("testcase")
            }
    for chapter in range(21):
        expected = f"tests.requirements.test_chapter_{chapter}"
        if expected not in requirement_classes:
            raise SystemExit(
                f"JUnit důkaz neobsahuje ověřovací test požadavků kapitoly {chapter}."
            )
    coverage = json.loads((evidence / "coverage-backend.json").read_text())
    totals = coverage["totals"]
    line_percent = 100 * totals["covered_lines"] / totals["num_statements"]
    branch_percent = 100 * totals["covered_branches"] / totals["num_branches"]
    if line_percent < 90 or branch_percent < 85:
        raise SystemExit(
            f"Backend coverage není důkazem: lines={line_percent:.2f}, "
            f"branches={branch_percent:.2f}."
        )
    frontend_coverage = json.loads((evidence / "coverage-frontend.json").read_text())[
        "total"
    ]
    frontend_thresholds = {
        "lines": 85,
        "branches": 80,
        "functions": 85,
        "statements": 85,
    }
    for metric, threshold in frontend_thresholds.items():
        measured = float(frontend_coverage[metric]["pct"])
        if measured < threshold:
            raise SystemExit(
                f"Frontend coverage není důkazem: {metric}={measured:.2f} < {threshold}."
            )
    for name in [
        "backup-check.json",
        "restore-backup-info.json",
        "sbom-backend-source.cdx.json",
        "sbom-frontend-source.cdx.json",
        "sbom-image.cdx.json",
        "grype-image.json",
        "bandit.json",
        "npm-audit.json",
        "python-vulnerability-report.cdx.json",
        "gitleaks.json",
    ]:
        path = evidence / name
        if not path.is_file():
            raise SystemExit(f"Chybí release důkaz {path}.")
        json.loads(path.read_text())
    restored = (evidence / "restored-instance.txt").read_text().strip()
    if not re.fullmatch(r"v0021:(uninitialized|active)", restored):
        raise SystemExit("Izolovaný restore neprokázal identitu instance v0021.")
    results = json.loads((evidence / "release-check-results.json").read_text())
    if not results or set(results.values()) != {"pass"}:
        raise SystemExit("Předchozí release brány nejsou všechny PASS.")
    print(
        f"Release důkazy jsou úplné: {len(required_junit)} JUnit sad, "
        f"backend coverage {line_percent:.2f}/{branch_percent:.2f} %, "
        f"frontend coverage "
        f"{frontend_coverage['lines']['pct']}/{frontend_coverage['branches']['pct']}/"
        f"{frontend_coverage['functions']['pct']}/{frontend_coverage['statements']['pct']} % "
        "a backup/restore/SBOM/security."
    )
