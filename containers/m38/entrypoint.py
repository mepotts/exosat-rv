"""Target-free bootstrap for probing the dedicated M38 runtime image."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


def main() -> int:
    contract_path = Path("/opt/m38/runtime-contract.json")
    content = contract_path.read_bytes()
    contract = json.loads(content)
    expected_uid_text, expected_gid_text = contract["container_user"].split(":", maxsplit=1)
    expected_uid = int(expected_uid_text)
    expected_gid = int(expected_gid_text)
    effective_uid = os.geteuid()
    effective_gid = os.getegid()
    identity_matches = effective_uid == expected_uid and effective_gid == expected_gid
    result = {
        "contract_sha256": hashlib.sha256(content).hexdigest(),
        "effective_gid": effective_gid,
        "effective_uid": effective_uid,
        "expected_gid": expected_gid,
        "expected_uid": expected_uid,
        "observation_scope": "identity-only; launch isolation requires external audit",
        "status": "ready" if identity_matches else "invalid-container-identity",
    }
    print(json.dumps(result, allow_nan=False, separators=(",", ":"), sort_keys=True))
    return 0 if result["status"] == "ready" else 70


if __name__ == "__main__":
    raise SystemExit(main())
