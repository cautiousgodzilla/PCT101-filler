"""
Supabase authentication for the Python backend.

This is the Python/`local_server.py` equivalent of the MikeOSS Express
`requireAuth` middleware: the client (vanilla JS + supabase-js) signs in with
Supabase Auth and sends the JWT as `Authorization: Bearer <token>`; here we
verify that token against Supabase's GoTrue endpoint using the **service role
key** and return the verified user.

Graceful degradation: if Supabase env vars are not configured, `is_configured()`
is False and the server leaves endpoints open (useful for local form-filling
without an auth setup). Once configured, protected endpoints require a valid JWT.

Env vars (server):
  SUPABASE_URL            e.g. https://abcd.supabase.co
  SUPABASE_ANON_KEY       public anon/publishable key (also sent to the client)
  SUPABASE_SECRET_KEY     service role key (server only — never sent to client)
"""

import json
import os
import urllib.request
import urllib.error


def _env(*names):
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return ""


def supabase_url() -> str:
    return _env("SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL").rstrip("/")


def anon_key() -> str:
    return _env("SUPABASE_ANON_KEY", "NEXT_PUBLIC_SUPABASE_ANON_KEY",
                "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_DEFAULT_KEY")


def service_key() -> str:
    return _env("SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY")


def is_configured() -> bool:
    """True when the client can run Supabase Auth (url + anon key present)."""
    return bool(supabase_url() and anon_key())


def public_config() -> dict:
    """Public config served to the vanilla-JS frontend (safe to expose)."""
    return {
        "configured": is_configured(),
        "supabase_url": supabase_url(),
        "supabase_anon_key": anon_key(),
    }


def verify_token(token: str) -> dict | None:
    """Validate a user JWT with Supabase GoTrue; return {id, email, ...} or None.

    Mirrors `admin.auth.getUser(token)` — uses the service role key as the apikey
    (falls back to anon) and the user's JWT as the bearer.
    """
    token = (token or "").strip()
    url = supabase_url()
    if not token or not url:
        return None
    apikey = service_key() or anon_key()
    if not apikey:
        return None
    req = urllib.request.Request(
        url + "/auth/v1/user",
        headers={"apikey": apikey, "Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            user = json.loads(r.read().decode("utf-8", "replace"))
    except (urllib.error.HTTPError, urllib.error.URLError, ValueError):
        return None
    if not user or not user.get("id"):
        return None
    return user


def _bearer(headers) -> str:
    auth = headers.get("Authorization") or headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def user_from_headers(headers) -> dict | None:
    """Extract + verify the Bearer token from request headers."""
    return verify_token(_bearer(headers))
