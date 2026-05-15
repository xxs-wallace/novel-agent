from __future__ import annotations

import base64
import json
from typing import Any


PREFIX = "artifact_"


def encode_artifact_id(descriptor: dict[str, Any]) -> str:
    raw = json.dumps(descriptor, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return PREFIX + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_artifact_id(artifact_id: str) -> dict[str, Any]:
    if not artifact_id.startswith(PREFIX):
        raise ValueError("invalid artifact id")
    raw = artifact_id[len(PREFIX) :]
    padding = "=" * (-len(raw) % 4)
    payload = base64.urlsafe_b64decode((raw + padding).encode("ascii"))
    decoded = json.loads(payload.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("invalid artifact descriptor")
    return dict(decoded)
