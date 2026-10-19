"""Import manager corrections exported from the platform's ``corrections`` table.

Input rows (JSON array or JSONL) look like the table: ``{id, org_id, location_id, kind, payload,
consent_training, t}`` where payload may be a dict or a JSON string. Output is ``correction``
records. Tenant ids are pseudonymised (sha256 prefix) so the labelled dataset does not carry the
customer's account id. ``consent_training`` is copied faithfully (default 0): corrections without
opt-in may drive per-venue tuning but are never training-eligible.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .schema import SCHEMA_VERSION, Issue, read_jsonl

KINDS = {"role", "table_empty", "wrong_alert"}


def validate_correction(r: dict, out: list[Issue]) -> None:
    if not isinstance(r.get("correction_id"), str) or not r.get("correction_id"):
        out.append(Issue("error", "correction_id", "required"))
    if r.get("kind") not in KINDS:
        out.append(Issue("error", "kind", f"must be one of {sorted(KINDS)}"))
    c = r.get("consent")
    if not isinstance(c, dict) or not isinstance(c.get("training"), bool):
        out.append(Issue("error", "consent.training", "boolean required"))
    p = r.get("payload")
    if not isinstance(p, dict):
        out.append(Issue("error", "payload", "object required"))
        return
    k = r.get("kind")
    if k == "role":
        f = p.get("feature")
        if p.get("role") not in ("staff", "guest"):
            out.append(Issue("error", "payload.role", "must be staff or guest"))
        if not (isinstance(f, list) and len(f) == 3
                and all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in f)):
            out.append(Issue("error", "payload.feature", "[h,s,v] each in 0..1 required"))
    elif k == "table_empty" and not p.get("table_id"):
        out.append(Issue("error", "payload.table_id", "required"))
    elif k == "wrong_alert" and not (p.get("alert_id") or p.get("table_id")):
        out.append(Issue("error", "payload", "alert_id or table_id required"))


def _load_rows(path: str | Path) -> list[dict]:
    text = Path(path).read_text(encoding="utf-8").strip()
    if text.startswith("["):
        return json.loads(text)
    rows, errs = read_jsonl(path)
    if errs:
        raise ValueError("; ".join(str(e) for e in errs))
    return rows


def convert_row(row: dict, index: int) -> dict:
    payload = row.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = None
    org = hashlib.sha256(str(row.get("org_id", "")).encode()).hexdigest()[:12]
    rid = row.get("id", index)
    return {
        "record_type": "correction", "schema_version": SCHEMA_VERSION,
        "correction_id": f"corr-{org}-{rid}", "tenant_ref": org,
        "venue_id": row.get("location_id"), "kind": row.get("kind"), "payload": payload,
        "t": row.get("t"), "consent": {"training": bool(row.get("consent_training", 0))},
        "lineage": {"source": "manager_correction", "licence": "customer-consent-agreement"},
    }


def import_corrections(path: str | Path, existing_ids: set[str] | None = None
                       ) -> tuple[list[dict], list[tuple[int, list[Issue]]]]:
    """Return (accepted records, [(row index, issues)] rejected). Duplicates are skipped."""
    from .schema import validate_record
    seen = set(existing_ids or ())
    good, bad = [], []
    for i, row in enumerate(_load_rows(path)):
        rec = convert_row(row, i)
        issues = [x for x in validate_record(rec) if x.level == "error"]
        if issues:
            bad.append((i, issues))
        elif rec["correction_id"] not in seen:
            seen.add(rec["correction_id"])
            good.append(rec)
    return good, bad
