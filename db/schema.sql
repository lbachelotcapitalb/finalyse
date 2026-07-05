-- finalyse — schéma Supabase (cours stockés + sync quotidien)
-- Idée : on ne scrape pas en live ; un cron alimente ces tables, l'app lit ici.
-- Schéma dédié pour cohabiter proprement dans un projet Supabase existant
-- (plafond free = 2 projets/compte → on loge finalyse dans le projet bwealthy).

create schema if not exists finalyse;

-- Référentiel des instruments (coté + fonds/UC), source unique de vérité.
create table if not exists finalyse.instruments (
  symbol      text primary key,              -- symbole EODHD : TICKER.US | ISIN.EUFUND | XAUUSD.FOREX
  key         text,                          -- clé interne d'univers (US_LARGE, CARMIGNAC_PAT…)
  isin        text,
  label       text,
  asset_class text,
  universe    text[]                         -- ['deep','ucits','uc','etf_us'] : appartenances
);

-- Cours ajustés (total return) quotidiens. PK composite = idempotence upsert.
create table if not exists finalyse.prices (
  symbol         text not null references finalyse.instruments(symbol) on delete cascade,
  date           date not null,
  adjusted_close double precision not null,
  primary key (symbol, date)
);
create index if not exists prices_symbol_date_idx on finalyse.prices (symbol, date desc);

-- Journal d'expériences (miroir interrogeable de journal/experiments.jsonl).
create table if not exists finalyse.experiments (
  id           bigserial primary key,
  ts           timestamptz not null default now(),
  source       text,
  note         text,
  window_years double precision,
  payload      jsonb not null                -- le record complet (métriques par profil, honnêteté, MC)
);

-- Log des runs de sync (observabilité du cron).
create table if not exists finalyse.sync_log (
  id         bigserial primary key,
  ran_at     timestamptz not null default now(),
  universe   text,
  n_symbols  int,
  n_rows     int,
  ok         boolean,
  detail     text
);
