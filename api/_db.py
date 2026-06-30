"""
Supabase Postgres access (firm/agent profiles) via PostgREST.

Backend-mediated multi-tenant model: the Python server is the only thing that
touches these tables, using the service-role key, and scopes every operation to
the caller's email domain. A "firm" is shared by all email domains mapped to it
in firm_domains (two domains of one organization -> one firm).

Stdlib only (urllib). Every function fails soft (returns None / does nothing) so
the app degrades gracefully when Supabase isn't configured or is unreachable.
"""

import json
import urllib.request
import urllib.parse
import urllib.error

try:
    import _auth
except ImportError:
    from . import _auth  # type: ignore

FIRM_FIELDS = ("firm_name", "firm_address", "firm_phone", "firm_fax", "firm_email",
               "signing_agent_name", "signing_agent_inpa")


def is_configured() -> bool:
    return bool(_auth.supabase_url() and _auth.service_key())


def domain_of(email: str) -> str:
    email = (email or "").lower().strip()
    return email.split("@", 1)[1] if "@" in email else ""


def _headers(prefer: str = "") -> dict:
    key = _auth.service_key()
    h = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if prefer:
        h["Prefer"] = prefer
    return h


def _rest(method: str, path: str, body=None, prefer: str = ""):
    """One PostgREST call. `path` includes the query string. Returns parsed JSON
    (or None). Raises on HTTP error so callers can decide to fail soft."""
    url = _auth.supabase_url() + "/rest/v1" + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=_headers(prefer), method=method)
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read().decode("utf-8", "replace")
        return json.loads(raw) if raw else None


def _firm_id_for_domain(email_domain: str):
    """Substring match (e.g. stored 'examplefirm' matches 'examplefirm.com')."""
    if not email_domain:
        return None
    rows = _rest("GET", "/firm_domains?select=domain,firm_id") or []
    for r in rows:
        d = (r.get("domain") or "").lower()
        if d and d in email_domain:
            return r.get("firm_id")
    return None


def _firm_bundle(firm_id):
    firms = _rest("GET", f"/firms?id=eq.{firm_id}&select=*") or []
    if not firms:
        return None
    agents = _rest("GET", f"/agents?firm_id=eq.{firm_id}&select=*&order=sort_order.asc") or []
    return {"firm": firms[0], "agents": agents}


def get_firm_bundle(email: str):
    """Read the firm + agents for a user's email domain, or None. Never creates."""
    if not is_configured():
        return None
    try:
        fid = _firm_id_for_domain(domain_of(email))
        return _firm_bundle(fid) if fid else None
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError):
        return None


def ensure_firm_bundle(email: str):
    """Like get_firm_bundle, but creates an empty firm for a new domain so the
    user has something to edit on the profile page."""
    if not is_configured():
        return None
    dom = domain_of(email)
    if not dom:
        return None
    try:
        fid = _firm_id_for_domain(dom)
        if not fid:
            created = _rest("POST", "/firms", body={}, prefer="return=representation")
            fid = created[0]["id"]
            _rest("POST", "/firm_domains", body={"domain": dom, "firm_id": fid})
        return _firm_bundle(fid)
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, KeyError, IndexError):
        return None


def save_firm(email: str, firm_fields: dict, agents: list):
    """Update the caller's firm (by domain) and replace its agent roster.
    Returns the refreshed bundle, or None on failure."""
    if not is_configured():
        return None
    dom = domain_of(email)
    if not dom:
        return None
    try:
        bundle = ensure_firm_bundle(email)
        if not bundle:
            return None
        fid = bundle["firm"]["id"]
        clean = {k: str(firm_fields.get(k, "")) for k in FIRM_FIELDS}
        try:
            _rest("PATCH", f"/firms?id=eq.{fid}", body=clean)
        except urllib.error.HTTPError as e:
            # DB predates the firm_fax column -> save the rest (apply the
            # supabase_schema.sql migration to persist fax).
            if "firm_fax" in clean and e.code in (400, 404):
                clean.pop("firm_fax")
                _rest("PATCH", f"/firms?id=eq.{fid}", body=clean)
            else:
                raise
        _rest("DELETE", f"/agents?firm_id=eq.{fid}")
        rows = [
            {"firm_id": fid, "name": str(a.get("name", "")), "inpa": str(a.get("inpa", "")),
             "mobile": str(a.get("mobile", "")), "sort_order": i}
            for i, a in enumerate(agents or [])
            if (a.get("name") or a.get("inpa") or a.get("mobile"))
        ]
        if rows:
            _rest("POST", "/agents", body=rows)
        return _firm_bundle(fid)
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, KeyError, IndexError):
        return None


def bundle_to_profile(bundle: dict) -> dict:
    """Shape a {firm, agents} bundle into the dict _forms._resolve_firm expects."""
    f = bundle.get("firm", {})
    agents = [
        {"name": a.get("name", ""), "inpa": a.get("inpa", ""), "mobile": a.get("mobile", "")}
        for a in bundle.get("agents", [])
    ]
    first = agents[0] if agents else {}
    return {
        "firm_name": f.get("firm_name", ""),
        "firm_address": f.get("firm_address", ""),
        "firm_phone": f.get("firm_phone", ""),
        "firm_fax": f.get("firm_fax", ""),
        "firm_email": f.get("firm_email", ""),
        # Signing agent = explicit signing_agent_*, else the FIRST roster agent.
        "agent_name": f.get("signing_agent_name") or first.get("name", ""),
        "agent_inpa": f.get("signing_agent_inpa") or first.get("inpa", ""),
        "agent_mobile": first.get("mobile", ""),
        "agents": agents,
    }
