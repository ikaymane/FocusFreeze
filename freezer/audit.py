"""Append-only audit log (B spec step 7): every freeze / thaw / block lands here.

One :class:`AuditEntry` per JSON line in ``audit.jsonl`` under ``FF_HOME``.
``prev_hash`` is the SHA-256 of the previous raw line (64 zeros for the
genesis entry), so a casual edit breaks the chain at exactly that line.
This is tamper-EVIDENCE for the demo and for review, not tamper-PROOFING:
rewriting the whole file consistently is undetectable here — keyed forgery
protection is the ledger's HMAC job (A, T3).
"""

from __future__ import annotations

import hashlib
import json
import time

from freezer.contracts import AuditEntry
from freezer.cost import home

GENESIS = "0" * 64
_REQUIRED = {"ts", "actor", "action", "app_id", "reason", "prev_hash"}
_ACTIONS = {"freeze", "thaw", "block", "propose", "rule_add"}


def path():
    return home() / "audit.jsonl"


def _canonical(entry: AuditEntry) -> bytes:
    return json.dumps({
        "ts": entry.ts, "actor": entry.actor, "action": entry.action,
        "app_id": entry.app_id, "reason": entry.reason,
        "prev_hash": entry.prev_hash,
    }, sort_keys=True).encode("utf-8")


def log(actor: str, action: str, app_id: str, reason: str = "") -> AuditEntry:
    home().mkdir(parents=True, exist_ok=True)
    p = path()
    prev = GENESIS
    if p.exists():
        raw = p.read_bytes().splitlines()
        if raw:
            prev = hashlib.sha256(raw[-1]).hexdigest()
    entry = AuditEntry(ts=time.time(), actor=actor, action=action,
                       app_id=app_id, reason=reason, prev_hash=prev)
    with open(p, "ab") as f:
        f.write(_canonical(entry) + b"\n")
    return entry


def verify() -> tuple[bool, int | None, int]:
    """Walk the chain. Returns (ok, bad_index, count); bad is 0-based.

    A prev mismatch on line ``i`` reports ``i - 1``: the line whose content
    no longer matches its successor (the edited line in the casual-edit
    case). Malformed lines report themselves.
    """
    p = path()
    if not p.exists():
        return (True, None, 0)
    raw = p.read_bytes().splitlines()
    for i, line in enumerate(raw):
        try:
            body = json.loads(line)
        except Exception:  # noqa: BLE001 - corrupt line fails closed
            return (False, i, len(raw))
        if (not isinstance(body, dict) or set(_REQUIRED) - set(body)
                or body.get("action") not in _ACTIONS):
            return (False, i, len(raw))
        want = GENESIS if i == 0 else hashlib.sha256(raw[i - 1]).hexdigest()
        if body.get("prev_hash") != want:
            return (False, i - 1 if i else 0, len(raw))
    return (True, None, len(raw))
