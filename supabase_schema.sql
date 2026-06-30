-- PCT Form Filler — firm/agent profile schema (run once in Supabase SQL editor).
-- Multi-tenant: a "firm" is shared by everyone whose login-email domain maps to
-- it (firm_domains). Any authenticated user in the firm can edit it. No PII here.
--
-- Access model: RLS is ON with NO policies, so the anon/authenticated keys CANNOT
-- read these tables directly. Only the backend (service-role key) reaches them,
-- and the backend scopes every operation to the caller's email domain. This keeps
-- one firm's data invisible to other firms.

create extension if not exists "pgcrypto";

create table if not exists public.firms (
  id                  uuid primary key default gen_random_uuid(),
  firm_name           text not null default '',
  firm_address        text not null default '',
  firm_phone          text not null default '',
  firm_fax            text not null default '',
  firm_email          text not null default '',
  signing_agent_name  text not null default '',
  signing_agent_inpa  text not null default '',
  updated_at          timestamptz not null default now()
);

-- Migration for firms created before firm_fax existed (idempotent).
alter table public.firms add column if not exists firm_fax text not null default '';

-- Which email domains belong to which firm (two domains of one organization -> one firm).
create table if not exists public.firm_domains (
  domain   text primary key,            -- e.g. 'examplefirm.com'
  firm_id  uuid not null references public.firms(id) on delete cascade
);

create table if not exists public.agents (
  id          uuid primary key default gen_random_uuid(),
  firm_id     uuid not null references public.firms(id) on delete cascade,
  name        text not null default '',
  inpa        text not null default '',
  mobile      text not null default '',
  sort_order  int  not null default 0
);

create index if not exists agents_firm_id_idx on public.agents (firm_id);

-- Lock the tables: RLS enabled, no policies -> only the service-role key (backend)
-- can access. The Python server enforces per-domain scoping in code.
alter table public.firms        enable row level security;
alter table public.firm_domains enable row level security;
alter table public.agents       enable row level security;
