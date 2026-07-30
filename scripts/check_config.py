from __future__ import annotations
import os
import re
import sys

required = [
    "KAJOVODAGMAR_ROOT_ENCRYPTION_KEY",
    "KAJOVODAGMAR_INITIALIZATION_SECRET_HASH",
]
missing = [name for name in required if not os.getenv(name)]
if missing:
    print("Chybí infrastrukturní hodnoty: " + ", ".join(missing), file=sys.stderr)
    raise SystemExit(1)
origin = os.getenv("KAJOVODAGMAR_PUBLIC_ORIGIN", "https://chat.hcasc.cz")
if not origin.startswith("https://"):
    print("Produkční origin musí používat HTTPS.", file=sys.stderr)
    raise SystemExit(1)
if re.search(
    r"replace-with|example\.invalid", " ".join(os.environ.get(n, "") for n in required)
):
    print("Infrastrukturní hodnoty obsahují nepoužitelný vzor.", file=sys.stderr)
    raise SystemExit(1)
print("Konfigurace infrastruktury prošla základní kontrolou.")
