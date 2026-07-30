from __future__ import annotations
import json
from kajovodagmar.security.crypto import generate_token, token_digest

secret = generate_token(24)
print(
    json.dumps(
        {"secret": secret, "digest": token_digest(secret, "initialization")},
        ensure_ascii=False,
    )
)
