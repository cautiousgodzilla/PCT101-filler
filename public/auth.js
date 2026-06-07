/*
 * Supabase auth for the vanilla-JS front-end.
 *
 * Equivalent of MikeOSS's supabase.ts + AuthContext + getAuthHeader(), adapted
 * to a no-build setup: the supabase-js UMD bundle is loaded from a CDN in the
 * HTML, and the public config (URL + anon key) is fetched from /api/config so
 * no keys are hard-coded in the repo.
 *
 * Exposes window.Auth with: ready, isConfigured, getSession, getUser,
 * getAuthHeader, signIn, signUp, signOut, onAuthChange, requireAuthOrRedirect,
 * redirectIfAuthed.
 */
(function () {
  "use strict";

  let client = null;
  let config = null;

  const ready = (async () => {
    try {
      const r = await fetch("/api/config");
      config = await r.json();
    } catch (_) {
      config = { configured: false };
    }
    if (config && config.configured && window.supabase && config.supabase_url && config.supabase_anon_key) {
      client = window.supabase.createClient(config.supabase_url, config.supabase_anon_key);
    }
    return config;
  })();

  async function isConfigured() {
    await ready;
    return !!(config && config.configured && client);
  }

  async function getSession() {
    await ready;
    if (!client) return null;
    const { data } = await client.auth.getSession();
    return data.session || null;
  }

  async function getUser() {
    const s = await getSession();
    return s ? s.user : null;
  }

  // Append to fetch headers so backend requests carry the user's JWT.
  async function getAuthHeader() {
    const s = await getSession();
    return s && s.access_token ? { Authorization: "Bearer " + s.access_token } : {};
  }

  async function signIn(email, password) {
    await ready;
    if (!client) throw new Error("Authentication is not configured on this server.");
    const { data, error } = await client.auth.signInWithPassword({ email, password });
    if (error) throw error;
    return data;
  }

  async function signUp(email, password) {
    await ready;
    if (!client) throw new Error("Authentication is not configured on this server.");
    const { data, error } = await client.auth.signUp({ email, password });
    if (error) throw error;
    return data;
  }

  async function signOut() {
    await ready;
    if (client) await client.auth.signOut();
  }

  function onAuthChange(cb) {
    ready.then(() => {
      if (client) client.auth.onAuthStateChange((_event, session) => cb(session));
    });
  }

  // For protected pages: redirect to login if auth is on and there's no session.
  // Returns true if allowed to proceed.
  async function requireAuthOrRedirect(loginPath) {
    if (!(await isConfigured())) return true; // auth disabled -> open access
    const s = await getSession();
    if (!s) {
      window.location.href = loginPath || "/login.html";
      return false;
    }
    return true;
  }

  // For login/signup pages: bounce to the app if already signed in.
  async function redirectIfAuthed(appPath) {
    if (!(await isConfigured())) return;
    const s = await getSession();
    if (s) window.location.href = appPath || "/";
  }

  window.Auth = {
    ready, isConfigured, getSession, getUser, getAuthHeader,
    signIn, signUp, signOut, onAuthChange, requireAuthOrRedirect, redirectIfAuthed,
  };
})();
