from __future__ import annotations
import json
import shutil
import subprocess
import sys

required_python = (3, 12, 13)
result = {
    "python": {
        "required": "3.12.13",
        "actual": sys.version.split()[0],
        "pass": sys.version_info[:3] == required_python,
    }
}
for name, command, expected, exact in [
    ("uv", ["uv", "--version"], "uv 0.12.0", False),
    ("node", ["node", "--version"], "v22.23.2", True),
    ("npm", ["npm", "--version"], "10.9.8", True),
    ("docker", ["docker", "--version"], "Docker version", False),
    ("compose", ["docker", "compose", "version"], "Docker Compose version", False),
]:
    if shutil.which(command[0]) is None:
        result[name] = {"pass": False, "actual": "missing"}
        continue
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    actual = (completed.stdout or completed.stderr).strip()
    result[name] = {
        "required": expected,
        "pass": completed.returncode == 0
        and (actual == expected if exact else actual.startswith(expected)),
        "actual": actual,
    }
print(json.dumps(result, ensure_ascii=False, indent=2))
if not all(item["pass"] for item in result.values()):
    raise SystemExit(1)
