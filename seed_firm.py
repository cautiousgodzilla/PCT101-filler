"""
One-time seed: push firm_config.json (your firm details + agent roster) into the
Supabase firms/firm_domains/agents tables.

Run AFTER applying supabase_schema.sql, with SUPABASE_URL + SUPABASE_SECRET_KEY
set (in .env or the environment):

    python seed_firm.py

Idempotent: re-running updates the existing firm (matched by domain) and replaces
its agent roster. No PII lives in this script — it reads the git-ignored
firm_config.json.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "api"))

import _extract  # noqa: E402  (loads ../.env into the environment on import)
import _db        # noqa: E402


def main():
    if not _db.is_configured():
        print("✗ Supabase not configured. Set SUPABASE_URL and SUPABASE_SECRET_KEY.")
        return 1
    cfg_path = os.path.join(HERE, "firm_config.json")
    if not os.path.isfile(cfg_path):
        print("✗ firm_config.json not found.")
        return 1
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    existing = _db._rest("GET", "/firm_domains?select=domain,firm_id") or []
    for firm in cfg.get("firms", []):
        domains = [d.lower() for d in firm.get("domains", []) if d]
        if not domains:
            continue
        fid = next((r["firm_id"] for r in existing if (r.get("domain") or "").lower() in domains), None)
        sa = firm.get("signing_agent") or {}
        fields = {
            "firm_name": firm.get("firm_name", ""),
            "firm_address": firm.get("firm_address", ""),
            "firm_phone": firm.get("firm_phone", ""),
            "firm_email": firm.get("firm_email", ""),
            "signing_agent_name": sa.get("name", ""),
            "signing_agent_inpa": sa.get("inpa", ""),
        }
        if fid:
            _db._rest("PATCH", f"/firms?id=eq.{fid}", body=fields)
        else:
            created = _db._rest("POST", "/firms", body=fields, prefer="return=representation")
            fid = created[0]["id"]
        for d in domains:
            _db._rest("POST", "/firm_domains", body={"domain": d, "firm_id": fid},
                      prefer="resolution=merge-duplicates")
        _db._rest("DELETE", f"/agents?firm_id=eq.{fid}")
        rows = [
            {"firm_id": fid, "name": a.get("name", ""), "inpa": a.get("inpa", ""),
             "mobile": a.get("mobile", ""), "sort_order": i}
            for i, a in enumerate(firm.get("agents", []))
        ]
        if rows:
            _db._rest("POST", "/agents", body=rows)
        print(f"✓ Seeded {fields['firm_name']!r}  domains={domains}  agents={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
