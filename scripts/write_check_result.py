from __future__ import annotations
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
name = sys.argv[2]
status = sys.argv[3]
result = json.loads(path.read_text()) if path.exists() else {}
result[name] = status
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
