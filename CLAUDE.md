# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# analytic-maps (The Next - SiJalan)

FastAPI backend + vanilla JS frontend. Route planning on Google Maps, route
analysis, export to GIS formats, browsing/scoring of Inpres Jalan Daerah (IJD)
road proposals, and an AI chat assistant. UI/user-facing strings, code
comments, and docstrings are in Indonesian.

This file covers the file map and run instructions. For design rationale
and reusable patterns, see `docs/ARCHITECTURE.md`; for change recipes, see
`CONTRIBUTING.md`; for hard-won gotchas, see `docs/MEMORY.md`; for adding an
IJD scoring parameter specifically, use the `ijd-scoring-parameter` skill
(`.claude/skills/`). For the known fairness/data-quality trade-offs of the
scoring methodology itself (not implementation bugs), see
`docs/analisis_keadilan_kemanfaatan_skoring.md` before "fixing" something
that's actually a documented, deliberate trade-off. `docs/verifikasi_*.md`
are manual hand-computed verifications of specific usulan against the DB —
the pattern to follow when asked to re-verify a score end-to-end.

## Run

Windows: the bare `python` command resolves to the Microsoft Store alias
stub unless the venv is activated first — activate before running anything:

```
.venv\Scripts\Activate.ps1         # PowerShell; may need Set-ExecutionPolicy -Scope Process RemoteSigned first
python app.py                      # uvicorn with reload, port from .env (default 8000)
```

Requires `.env` (copy from `.env.example`):

- `GOOGLE_MAPS_API_KEY` — mandatory. `/api/config` returns 500 without it,
  which breaks the whole frontend (the Maps JS SDK is loaded dynamically via
  that endpoint, see static/index.html).
- `APP_USERNAME`/`APP_PASSWORD` — optional HTTP Basic Auth gate in front of
  the entire app (static files + every `/api/*` route), enforced by the
  `basic_auth_middleware` in app.py. Leave both blank to disable (default
  dev flow, no login prompt); set both to require a browser login dialog —
  useful for an internet-facing staging box.
- `PG_HOST/PORT/USER/PASS/DB` — PostgreSQL connection (default db
  `route_gis`). Usulan-Inpres browsing, IJD scoring, the Data viewer, chat
  DB tools, and the `Maps/` overlay layers (`map_layers`/`map_layer_meta`)
  all need it; route planning/export works without it. Migrated from MySQL
  24 Jul 2026 (see `docs/migrasi_mysql_ke_postgresql.md`) — `MYSQL_*` vars
  are legacy/unused, kept in `.env` only as a fallback pointer to the old
  MySQL instance during the post-migration grace period.
- Chat provider keys, all optional: `GROQ_API_KEY`, `GROK_API_KEY`,
  `OPEN_AI_API_KEY`, `CLOUDE_API_KEY` (Anthropic — yes, spelled with OU;
  don't "fix" the name without migrating existing `.env` files),
  `GEMINI_API_KEY`. `/api/chat` tries providers in that order until one
  succeeds (see `_call_chat`); with zero keys the chat panel is dead but the
  rest of the app works.

Deps: `requirements.txt`, venv at `.venv/` (already gitignored).

## Architecture (near-single-file backend + PostgreSQL, no ORM)

- [app.py](app.py) — the backend. FastAPI app, all routes, all GIS logic,
  IJD scoring. Still the file to start reading in — don't go looking for a
  `routers/` or `services/` dir. A few pieces have been extracted into their
  own modules (see below) but nothing resembling a framework of packages;
  when in doubt, the code you're looking for is in app.py.
- [chat_providers.py](chat_providers.py) — chat assistant LLM-provider logic
  (Groq/Grok/OpenAI/Claude/Gemini calls, `_call_chat` fallback chain, the
  read-only DB tool functions). Extracted out of app.py; the `POST /api/chat`
  route itself stays in app.py and just calls
  `chat_providers._call_chat(...)`. Imports from app.py (usulan_inpres CRUD
  helpers) are done lazily inside functions, not at module top-level, to
  avoid a circular import — app.py imports `chat_providers` at top-level.
- [db.py](db.py) — the `db_cursor()` contextmanager (see below).
- [map_layer_labels.py](map_layer_labels.py) — `MAP_LAYER_LABELS` /
  `_map_layer_label`, shared between app.py and
  `scripts/import_maps_to_postgis.py`.
- Database: PostgreSQL via `psycopg` (v3), raw parameterized SQL through the
  `db_cursor()` contextmanager in [db.py](db.py) — `%s` placeholders (same
  as the old MySQL driver, unchanged). Schemas live in PostgreSQL itself
  (created by `scripts/migrate_pg_01_schema.py`, introspected from the old
  MySQL schema); the `scripts/schema_*.sql` files under
  [scripts/](scripts/) are now historical column documentation only — not
  executed by any live code path. Tables are populated by the import/
  extract scripts there, not by the app (exception: the app upserts via
  `/api/usulan-inpres/import` and caches fetched KML into
  `usulan_inpres.geom_geojson`). Migrated from MySQL 24 Jul 2026 — see
  `docs/migrasi_mysql_ke_postgresql.md` for the conversion checklist and
  MySQL-idiom rewrites (`ON DUPLICATE KEY UPDATE`→`ON CONFLICT`, `IN %s`
  tuple-expansion→`= ANY(%s)`+list, `DIV`→`/`, etc.) — useful context if a
  script still shows MySQL-flavored SQL in a comment/docstring.
- [static/index.html](static/index.html) — one page, no build step, no framework.
- [static/js/](static/js/) — frontend logic, split into plain `<script>` files
  (no bundler, no ES modules) loaded in dependency order from index.html:
  `state.js` (global `state` object, toast/status) → `utils.js` (formatting
  helpers) → `data-viewer.js` (topbar "Data" table browser; independent of
  Google Maps) → `map-bootstrap.js` (Maps init, geocoding) → `points.js`
  (origin/destination/waypoints, markers) → `routing.js` (Directions calls,
  route computation) → `drawing.js` (polylines, hover) → `maps-overlay.js`
  (topbar layer picker; toggles reference SHP layers from `Maps/` on/off as
  `google.maps.Data` overlays) → `map-tools.js` (ArcGIS-style identify/
  select/measure tools + overlay legend) → `route-list.js` (result list +
  analysis panel) → `analysis.js` (admin region / road classification
  panels) → `usulan-inpres.js` (Inpres match + browse/detail) →
  `dalam-angka.js` (topbar "Dalam Angka" BPS publication search/preview
  panel; independent of Google Maps, same pattern as data-viewer.js) →
  `chat.js` (chat panel, grounded in the currently viewed route) →
  `export.js` → `main.js` (reset, top-level event binding, and the
  mobile "..." topbar dropdown — `.topbar-more`, `display:contents` on
  desktop so it's visually a no-op there, collapses secondary nav buttons
  into a dropdown under 900px). All files share the same global
  scope — add a new script tag in index.html (in the right position relative
  to its dependencies) rather than reintroducing a single monolithic file.
- [static/css/style.css](static/css/style.css)
- Static files are served by mounting `StaticFiles` at `/` — **must stay the
  last route registered** in app.py, or it will shadow `/api/*` routes.

## API endpoints (all in app.py)

- `GET /api/config` — hands the Google Maps API key to the frontend.
- `POST /api/export` — dispatches on `format` (geojson/csv/gpx/wkt/shp) to
  `_build_*` helper functions. Add a new export format by adding a helper +
  a branch here.
- `POST /api/analyze/road-classification` — samples up to 60 points along a
  route, queries OSM Overpass API (falls back across 3 mirrors, see
  `OVERPASS_MIRRORS`), nearest-way match via `shapely.strtree.STRtree`,
  classifies via `HIGHWAY_CLASSIFICATION` map. This mapping is a **best-effort
  approximation** of Indonesian road hierarchy (OSM has no official PUPR
  classification) — labelled "(perkiraan)" in the UI, keep it that way.
- `/api/usulan-inpres/*` — list/detail/nearby search, xlsx import (upsert)
  and export, per-usulan geometry and SHP export, and
  `GET .../{id}/ijd-score`. Geometry comes from the SITIA `kml_original_url`:
  fetched on first request, parsed by `_parse_kml_linestrings`, and cached in
  the `geom_geojson` column.
- `GET /api/usulan-inpres/{id}/ijd-score?tahun=` — "Prioritisasi Teknokratik"
  scoring per the IJD policy document (default `tahun=2026`, `2025` also
  available). Weights/values are **data, not code**: rows in the
  `ijd_scoring_rules` table (`schema_ijd_scoring.sql` for 2025,
  `schema_ijd_scoring_2026.sql` for 2026 — a new policy year means a new
  seed file + `INSERT`, not a code change) keyed by `tahun_berlaku`. The set
  of parameters shown is `set(rules) | set(IJD_PENDING_PARAMETERS)` for that
  year, not a hardcoded A-F loop — this is why F (present in 2025) cleanly
  disappears in 2026 instead of showing as "belum tersedia". 2026 computes
  A (A1 tematik + A2 konektivitas + A3 kawasan tematik via `kawasan_tematik`
  (kabupaten-level, works without `kode_kecamatan`) **and**
  `kecamatan_data_turunan.potensi_*` (kecamatan-level, needs
  `usulan_inpres.kode_kecamatan` — silently falls back to the kabupaten-level
  match alone when it's NULL, which lowers A3/A without marking A
  `"tersedia": false`) + A4 data dukung), B, C, D, and E; F was removed
  from the 2026 policy. **A (`_ijd_score_tematik_v2`) promoted to official
  29 Jul 2026** (explicit user/kaidah-owner confirmation, during a
  technocratic-score validation report exercise, see `docs/validation-
  report/`): `_IJD_SCORERS["A"]` now points to `_ijd_score_tematik_v2`, not
  the older `_ijd_score_tematik` (kept in code as reference/history, no
  longer called). The only behavioral change is A1/A2 (the single-column
  thematic-category lookup, weighted 40%/30% respectively): confirmed
  policy is that A1 "TEMATIK SiTIA" and A2 "TEMATIK KONEKTIVITAS" read
  **only** `usulan_inpres.tematik_kawasan_kompetensi` — the 27.7.26
  KERANGKA PENGGUNAAN DATA UNTUK APLIKASI CPIT.xlsx source document says
  literally "Kesesuaian Tematik diambil dari SiTIA pada kolom AL" with no
  mention of any fallback. The old `_ijd_score_tematik` additionally fell
  back to `tematik_kawasan_balai` then `tematik_kawasan_pemda` when
  `_kompetensi` was empty — that fallback is now confirmed **not** to be
  policy-sanctioned for A1/A2 and is no longer used in production. **A3
  (tematik tambahan, `kawasan_tematik`/`kecamatan_data_turunan.potensi_*`)
  and A4 (data dukung, `jenis_data_dukung_tematik_kompetensi`) are
  completely unaffected** — neither ever used the Balai/Pemda fallback
  to begin with, so this promotion changes nothing about their logic.
  National impact: 1,229/3,072 usulan (40%) have `tematik_kawasan_
  kompetensi` NULL and previously scored A1/A2 via Balai (302) or Pemda
  (927) fallback under the old function; those now report A entirely
  `"tersedia": false`. **A3/A4 do NOT independently rescue A** — both
  functions `return` immediately once A1/A2 fails to resolve, before the
  A3/A4 lookup code is ever reached (verified against all 370 sampled
  records in the validation report, zero exceptions) — there is no path
  where A scores off A3/A4 alone while A1/A2 is unresolved. **`_ijd_bulk_cache`
  is stale after this change** (in-process, same limitation as always —
  see below) — restart the server to pick up new scores; exports
  generated before the restart still reflect the old fallback-enabled A.
  **B (`_ijd_score_kemantapan_v2`) promoted to official 29 Jul 2026**
  (same session, explicit user/kaidah-owner confirmation): `_IJD_SCORERS
  ["B"]` now points to `_ijd_score_kemantapan_v2`, not the older
  `_ijd_score_kemantapan` (kept in code as reference/history, no longer
  called). Formula unchanged in shape (`(kondisi_baik_km +
  kondisi_sedang_km) / denominator × 100`, <60%→TIDAK_MANTAP(100),
  ≥60%→MANTAP(60)) — the only change is the **denominator**: confirmed to
  be `panjang_ruas_km` (the ruas's own official SITIA length), not
  `kondisi_baik_km + _sedang_km + _ringan_km + _berat_km` (sum of the
  four self-reported condition columns) as the old function used. The
  27.7.26 KERANGKA PENGGUNAAN DATA UNTUK APLIKASI CPIT.xlsx source states
  the rule as "(panjang baik + panjang sedang) / panjang ruas total ×
  100" — "panjang ruas total" is now confirmed to mean `panjang_ruas_km`.
  `pct_mantap` is clamped to 100% (a handful of rows report condition
  lengths that sum past their own official ruas length — a genuine
  source-data inconsistency, same clamp pattern as `_kemantapan_ruas_
  fakta`). Nationwide (rechecked 29 Jul 2026 against the current
  3,072-usulan dataset), this reclassifies 23/2,068 comparable usulan
  (1.1%) between MANTAP/TIDAK_MANTAP, and clamps 37 usulan whose raw
  `pct_mantap` would exceed 100% — small in volume but a real behavior
  change for those rows. **Far more consequential**:
  `_ijd_score_kemantapan_v2` requires `kondisi_baik_km`/
  `kondisi_sedang_km` to be **non-NULL** (not just non-zero) to report
  available, stricter than the old function's `float(x or 0)` coercion
  (which only failed when *all four* condition columns were null/zero).
  This alone pushes B-unavailable from 226/3,072 (7.4%) under the old
  formula to **794/3,072 (25.8%)** under the new one — B is now
  unavailable for roughly 1 in 4 usulan nationally, not 1 in 14. Every
  downstream consumer of "Kelengkapan Data Skor Teknokratis" (bulk
  export, dashboard, `docs/validation-report/`) needs to be read against
  this new baseline, not the pre-29-Jul-2026 one.
  **C (`_ijd_score_kemanfaatan`) is 3 independently-
  gated subs, not all-or-nothing** (changed 2026-07-22): A1 Kepadatan
  (35%) prefers kecamatan-level `kecamatan_data_turunan` via
  `usulan_inpres.kode_kecamatan`, and — **with explicit user sign-off,
  not the default pattern for new sub-parameters** — falls back to a
  labelled kabupaten-average proxy (`SUM(jumlah_penduduk) /
  SUM(luas_km2_derived)` across `bps_kecamatan_demografi`, always tagged
  "PROKSI kabupaten" in `keterangan` since it's not literal policy-doc
  wording, Table 4 is explicitly per-kecamatan for A1) when
  `kode_kecamatan` is NULL; A2 Produktivitas/IP (23%,
  `bps_kabupaten_padi` + `bps_kabupaten_indeks_penanaman`) and A3
  Kendaraan/km (30%, `bps_kabupaten_kendaraan` ÷ `bps_kabupaten_jalan`)
  are genuinely kabupaten-level and resolve `kode_kab` via the same
  `kab_by_wilayah`/`wilayah_mapping` fallback as A3 above and NPR
  (`_bappenas_kode_kab`) — no proxy caveat needed there, they're already
  at the right granularity. C only reports `"tersedia": false` when
  *none* of its subs resolved (nationally ~0.4% of usulan, vs. 100%
  before the 2026-07-22/23 changes). Every
  component that lacks a data source reports `"tersedia": false` with a
  specific reason instead of contributing 0 — `skor_ternormalisasi_100`
  is normalized against `bobot_tersedia`, not 100.
  **`usulan_inpres.kode_kecamatan` / `lanjutan_ijd_2025` / `geom_geojson`
  are NOT backfilled by the xlsx import** — they're set by
  `spatial_join_kecamatan.py` (after `fetch_kml_massal.py`) and
  `import_dpp_ijd_2025.py` respectively; if a fresh reimport of
  `usulan_inpres` leaves those columns NULL nationally, rerun that
  pipeline (see `docs/MEMORY.md` for the exact order and for the
  `sitia.binamarga.pu.go.id` reachability gotcha that can block the
  KML-fetch step) before treating a nationwide drop in A1/A3 (not C as a
  whole anymore) as a scoring bug —
  `docs/verifikasi_ijd_ciparay_cikumpay.md` and
  `docs/verifikasi_npr_ciparay_cikumpay.md` both hit and document this
  exact scenario (22 Jul 2026 re-validation).
  **D (`_ijd_score_koridor_v2`) promoted to official 28 Jul 2026** (explicit
  user request, same session that added the "PETA KORIDOR" map overlay
  layer above): `_IJD_SCORERS["D"]` now points to `_ijd_score_koridor_v2`,
  not the older `_ijd_score_koridor` (kept in code as reference/history,
  no longer called). Adds a 4th tier "koridor tidak langsung" (75, DB
  sub_kode `TIDAK_LANGSUNG` seeded into `ijd_scoring_rules` — sourced from
  the CPIT framework doc, not PDF Tabel 5, kept transparent in the SQL
  comment) on top of the existing 100/50/0: usulan route within 50m of
  `map_layers` layer `'PETA KORIDOR'` geometry, checked after the exact
  `kode_koridor`→`bappenas_koridor` match and before the old Balai/proxy
  fallback chain. **Radius check is PRECOMPUTED, not a live query**
  (settled 28 Jul 2026, same session, after two rounds of query
  optimization — 280s → ~53s via `ST_DWithin(geometry,...)` planar +
  batched `MATERIALIZED` spatial JOIN — still wasn't good enough since it
  re-ran on every cold `_ijd_bulk_cache` miss). `scripts/spatial_join_
  koridor_radius.py` fills `usulan_inpres.koridor_radius_50m` (TEXT,
  nullable — nearest `PETA KORIDOR` `NO_KORIDOR` within 50m, or NULL) ONCE,
  same pattern as `kode_kecamatan`/`spatial_join_kecamatan.py`.
  `_ijd_score_koridor_v2` just reads that column now — **zero spatial
  query at scoring time**, national bulk went from ~53s to ~5s. Re-run the
  script (idempotent, only fills NULLs; `--force` recomputes everything)
  after `fetch_kml_massal.py`/reimporting `usulan_inpres`/reimporting the
  PETA KORIDOR layer, or the column stays stale for new/changed rows —
  same "rerun the pipeline" caveat `kode_kecamatan` already has. Full
  detail: `docs/checklist_implementasi_cpit.md` §"D Koridor 'tidak
  langsung' ... DIPROMOSIKAN RESMI". `@app.on_event("startup")`
  `_warm_ijd_bulk_cache_nasional()` (near the top of app.py) still
  pre-computes the nasional/2026 bulk result in a background thread on
  boot so even that ~5s never hits a real user, though it matters much
  less now than when it was written against the ~53s number — server
  itself stays responsive to other requests immediately (<5s), only that
  cache slot warms in the background. A request landing before warm-up
  finishes still computes normally (race, not a bug) — restart re-triggers
  warm-up (cache is in-process, lost on restart same as always).
  **`_ijd_bulk_cache` invalidation is narrow** — only `POST /api/usulan-
  inpres/import` (added same session), `POST /api/bappenas-lokus-a/import`,
  and the penilaian-bappenas AI-narasi endpoints call `.clear()`. Data
  changes made OUTSIDE the running app process — any `scripts/*.py` run
  from the CLI (`import_maps_to_postgis.py`, `import_peta_koridor_to_
  postgis.py`, `spatial_join_kecamatan*.py`, `fetch_kml_massal.py`, etc.) —
  **cannot** reach into the live process's in-memory dict to invalidate it;
  there is no cross-process signal for that. Preview/Dashboard will keep
  serving pre-change results until the server is restarted, same limitation
  `_map_layer_geojson_cache` already has — this is not something a code fix
  can close without a shared cache (Redis, a DB-backed version counter,
  etc.), which hasn't been asked for.
  See `.claude/skills/ijd-scoring-parameter/` before touching this.
  `GET /api/usulan-inpres/ijd-score/preview` / `.../export/xlsx`
  (`_ijd_score_bulk_rows`) rank usulan nationally and per-provinsi via
  `_ijd_ranking_sort_key()`. **Ranking basis changed 22 Jul 2026 (explicit
  user request): sorts by NPR score descending** (the alternative/
  experimental model below, `_compute_npr`), **not** `skor_ternormalisasi_100`
  A-E teknokratis anymore — before that, it briefly used a "complete-data
  usulan first" rule on the teknokratis score (see
  `docs/verifikasi_ijd_ciparay_cikumpay.md`), which is now superseded; don't
  reintroduce it without checking `_ijd_ranking_sort_key()`'s current
  docstring first. The teknokratis score is still fully computed and shown
  (see columns below), just no longer the sort key. `provinsi`
  is a repeatable query param (`?provinsi=A&provinsi=B`, multi-select in the
  UI) normalized/cache-keyed by `_normalisasi_provinsi_multi()` — empty is
  nasional, one or more names filter to those provinces (`WHERE provinsi IN
  %s`). The export also carries a `Kelengkapan Data Skor Teknokratis` column
  (which A-E parameters, if any, are missing — **still teknokratis-based**,
  unrelated to the NPR ranking change above), a `Temuan Data Quality — Outlier
  Produksi Kecamatan` column (`IJD_OUTLIER_PRODUKSI_AMBANG`: flags
  `bps_kecamatan_potensi_tematik` production values that are implausibly
  large — a known, still-unfixed `extract_dalam_angka.py` parser bug, see
  `docs/verifikasi_npr_ciparay_cikumpay.md` §3), a `PENILAIAN PRIORITASI
  USULAN NASIONAL` + `RANKING NASIONAL` column pair (the `skor-prioritas-
  nasional` formula below, batched via `spn_by_id`/`spn_rank_by_score`
  rather than queried per row — same reasoning as the teknokratis ctx
  batching above), and — added 22 Jul 2026 alongside the ranking-basis
  change, so the old basis stays legible — a `Skor Teknokratis A-E
  (Ternormalisasi 0-100)` column plus `Skor NPR (Eksperimental...)` /
  `Kategori NPR (Eksperimental)` columns (NPR total only; the full 27-column
  SI/SC breakdown stays exclusive to `/npr/export/xlsx` below). Only the
  checked (`[v]`) checklist lines are kept in the Aspek A/Aspek B export
  columns — unmatched criteria are dropped, not listed as `[ ]`.
  `GET /api/usulan-inpres/ijd-score/dashboard` — KPI/top-10/komposisi
  summary reusing `_ijd_score_bulk_rows`, behind the navbar "Dashboard Skor
  IJD" button. `avg_total`/komposisi/`cakupan_komponen` still use
  `skor_tertimbang` sum of available teknokratis components (deliberately
  not `skor_ternormalisasi_100` — renormalizing would let a sparse-but-lucky
  usulan outrank a fully-scored one). **`top10` was switched to NPR-score
  ranking 22 Jul 2026** to stay consistent with the export's ranking-basis
  change above — it's the one exception in this endpoint that isn't
  teknokratis-based.
- `GET /api/usulan-inpres/{id}/skor-prioritas-nasional` /
  `GET /api/prioritas-nasional` — national priority score (70% teknokratis +
  10% PU + 10% Bappenas + 10% Kemenko per the 14072026 document) and the
  national ranking; Bappenas/Kemenko indication columns are imported but
  still empty in the 15 Juli snapshot, so they currently score 0.
- `GET /api/pagu-provinsi` / `GET /api/alokasi-2-lapis` — provincial
  indicative budget (partial score: A1 road-length + A2 road unsoundness
  `kemantapan_ijd_2026` + A3 kawasan pangan (proxied by ATR/BPN sawah area,
  `si_lahan_sawah_provinsi`) + A4 fiscal capacity, renormalized shares;
  only A5 Indeks Kemahalan Konstruksi still missing, no source found yet)
  and the two-layer allocation simulation on top of the national ranking.
  Both label themselves "perkiraan/parsial" — keep that.
- `GET /api/usulan-inpres/{id}/npr` / `GET /api/usulan-inpres/npr/preview` /
  `GET /api/usulan-inpres/npr/export/xlsx` —
  NPR (Nilai Prioritas Ruas), an **alternative/experimental** scoring model
  from `docs/kajian_metodologi_skala_prioritas_ruas.md`, not an official
  policy and entirely separate from the IJD Prioritisasi Teknokratik A-E
  score above. 70% Skor Intensitas (population + kuintil-nasional
  perkebunan production) + 30% Skor Cakupan (6 kawasan-tematik/lokus/simpul
  categories, reusing `kawasan_tematik`/`bappenas_lokus_a`/
  `simpul_transportasi`). The `/preview` bulk endpoint must go through
  `_npr_bulk_ctx()` to batch the per-row DB lookups instead of querying per
  usulan — same pattern as `_ijd_score_bulk_rows`'s ctx.
- `GET /api/bappenas-lokus-a/kriteria` / `POST .../import` — list the Aspek
  A Bappenas lokus criteria (`bappenas_lokus_a` table, ~13 kriteria: LOKPRI,
  PKPN, PKSN, KI Prioritas, BBM 1 Harga, KPP_DESA, etc.) with row counts,
  and let a user re-upload the source xlsx for one criterion (DELETE+INSERT
  for that `kriteria` only). Parsing logic lives once in
  `scripts/import_bappenas_lokus_a.py` (`KRITERIA_SOURCES`); this endpoint
  imports that module rather than duplicating the per-sheet regex/matching
  rules. Browsed via the navbar "Lokus Bappenas" button (separate from the
  generic "Data" viewer, `data-viewer.js` `dataViewerOpenLokusBappenas()`).
- `GET /api/laporan-daerah-prioritas/{dashboard,distribusi,preview,
  export/xlsx}` / `GET .../detail/{kode_kab}` — "Laporan Prioritas" navbar
  button: per-kabupaten/kota (not per-usulan) aggregate of Aspek A (15
  Bappenas lokus checklist criteria from `bappenas_lokus_a` +
  `kawasan_tematik`, `LAPORAN_ASPEK_A`) + Aspek B (Daya Ungkit Ekonomi,
  reworked 2026-07-21 to reuse NPR's Skor Intensitas/Skor Cakupan
  0-100 scoring and its `_npr_kelas_cache` verbatim via
  `LAPORAN_ASPEK_B`/`_LAPORAN_ASPEK_B_SI_SOURCE` so the two features stay
  consistent from one source). The combined "total" (`_LAPORAN_MAKS_TOTAL`
  = 15 + 100) sums two different scales as-is — a deliberate rough
  Tinggi/Sedang/Rendah bucketing, not a normalized single score. `/export/xlsx`
  follows the official `docs/docs/Laporan Prioritas.xlsx` column layout
  exactly (`_laporan_export_template_cols`) and Aspek B is intentionally
  dropped from that export (still shown in the UI Dashboard/Checklist tabs).
- `GET`/`POST /api/usulan-inpres/{id}/penilaian-bappenas` — AI-generated
  draft of the Bappenas qualitative assessment (aspek A/B points + narrative,
  cached in `penilaian_bappenas_ai`). Uses `_llm_plain()` — the tool-less
  provider fallback chain. Always labelled as an AI draft in the UI; keep it
  that way. Aspek A/B checklist scoring itself is rule-based (not LLM),
  cached in `aspek_a_checklist`/`aspek_a_total_kriteria` and
  `aspek_b_checklist`/`aspek_b_total_indikator` — the LLM only writes the
  narrative prose (`aspek_b_narasi_ai`), fed by `_bappenas_fakta_pendukung()`
  which assembles kecamatan/kabupaten BPS figures plus four dedicated fakta
  helpers: `_kemantapan_ruas_fakta` (% tidak mantap = `(kondisi_ringan_km +
  kondisi_berat_km) / panjang_ruas_km` — a different denominator than the
  official IJD parameter B score, by explicit user request, clamped to
  100%), `_konektivitas_jalan_fakta` (from `usulan_konektivitas_jalan`, the
  same table NPR's "Konektivitas Jaringan Jalan" uses), `_simpul_transportasi_fakta`
  (nearest airport/port + distance from `simpul_transportasi_kecamatan_radius`,
  kecamatan-level with actual `jarak_km` — finer-grained than the kabupaten
  ada/tidak used elsewhere), and `_kecamatan_dilalui_fakta` (every kecamatan
  the route crosses via `usulan_kecamatan_dilalui`, not just the single
  dominant `kode_kecamatan`, plus their combined population). Each helper
  returns `None` when its source table has no row for that usulan, so the
  prompt never fabricates a fact. `POST .../penilaian-bappenas/bulk` drives
  this per-provinsi in small batches (`_PENILAIAN_BULK_BATCH = 5` — shrunk
  repeatedly from 30 after audits found larger batches made the model skip
  per-usulan checklist items; resume-able unless `force=true`), one LLM call
  per request, frontend polls until `sisa=0`.
- `GET /api/data/tables` / `GET /api/data/{table}` — read-only paged table
  viewer behind the topbar "Data" button. Only tables whitelisted in
  `DATA_TABLES` in app.py are exposed — add new tables there.
- `GET /api/dalam-angka/list` / `.../preview` / `.../pdf` — topbar "Dalam
  Angka" panel (`static/js/dalam-angka.js`): search/browse every synced
  "\<Wilayah\> Dalam Angka \<tahun\>" BPS publication (`dalam_angka_publikasi`
  table, filled by `scripts/sync_dalam_angka_bps_api.py`, **not** whitelisted
  in `DATA_TABLES` — it has its own dedicated panel instead of the generic
  Data viewer). `/list` returns cached `url_publikasi` as-is (fast for
  hundreds of wilayah); `/preview` regenerates one fresh link on demand via
  `_dalam_angka_fresh_url()` since BPS's `download.php` token can expire.
  **`GET /api/dalam-angka/pdf` proxies the actual PDF bytes through the
  backend** rather than having the "Pratinjau" `<iframe>` embed the raw BPS
  URL directly — `webapi.bps.go.id` sits behind an Imperva/F5-style
  anti-bot WAF (`TS...` session cookies) that inconsistently blocks
  cross-origin iframe fetches but reliably allows requests carrying a normal
  browser `User-Agent` (`_BPS_DOWNLOAD_UA`, confirmed by direct testing
  24 Jul 2026: default-UA request → `403`, browser-UA request → `200`).
  The "Tab Baru" button still links directly to BPS (a top-level navigation
  behaves like a normal browser request, so it doesn't hit this issue).
- `GET /api/bps-subjek/{subcat,subject,var,{var_id}/tahun,{var_id}/turvar,
  {var_id}/turth,{var_id}/data}` — "Data per Subjek" tab inside the same
  Dalam Angka panel (still `dalam-angka.js`, not a separate frontend file):
  live drill-down through BPS's own subjek→subject→variabel→tahun hierarchy
  via the Web API dynamic-table model (`_bps_api_get`/`_bps_api_list_all` in
  app.py), independent of the `dalam_angka_publikasi` PDF catalog above.
  Requires `BPS_API_KEY` (503 without it). List responses (`subcat`/
  `subject`/`var`/`tahun`/`turvar`/`turth`) are cached forever in-memory per
  cache key (`_bps_subjek_cache`, restart to refresh); only the final
  `.../data` values call is uncached, since it's parameterized by the
  user's tahun/turvar/turth picks. `vervar.label` from BPS sometimes wraps
  province-level rows in `<b>` when one variable mixes provinsi and
  kab/kota granularity in the same table — `_bps_clean_wilayah_label`
  strips the tag and turns it into an `is_provinsi` flag rather than
  showing literal `<b>` text (frontend already HTML-escapes labels, so raw
  tags would otherwise render as visible markup, not bold).
- `GET /api/data/geo/provinces` / `GET /api/data/geo/kabupaten` — provinsi/
  kabupaten master (from `penduduk_kecamatan`, full national coverage) that
  drives the region-filter dropdowns in the generic "Data" table viewer
  (`DATA_TABLE_GEO`), separate from the IJD-specific
  `/api/usulan-inpres/provinsi` / `.../kabupaten` used by the usulan browse
  panel.
- `GET /api/usulan-inpres/{id}/dalam-angka` — resolves an usulan's
  kabupaten/kota to its BPS "Dalam Angka" publication link, so the usulan
  detail panel can offer a direct jump into the Dalam Angka viewer instead
  of the user having to search by region name themselves.
- `POST /api/penduduk-kecamatan/import` / `GET .../export/xlsx` — BPS
  population-per-kecamatan master (also loadable via the CLI script).
- `POST /api/chat` — chat assistant, logic lives in `chat_providers.py`
  (route/dispatch stays in app.py, `chat()` returns `{"reply", "actions"}` —
  see below for `actions`). Providers are tried in order
  Groq → Grok → OpenAI → Claude → Gemini depending on which API keys exist.
  The model gets a compact context of the currently viewed route plus
  `CHAT_TOOLS`: three original fixed read-only helpers (search/detail/
  KML-geometry of usulan, calling existing parameterized-query functions)
  **plus**, added 27 Jul 2026 on explicit user request (superseding the old
  "never give the model free-form SQL" stance):
  - `daftar_tabel_database` — schema introspection (list tables, or columns
    of one table).
  - `jalankan_query_sql` — arbitrary single-statement `SELECT`/`WITH` across
    every table in `public`, capped at 200 rows, 8s `statement_timeout`.
    Genuinely free-form SQL, not a query builder — the safety model is two
    independent layers, not "trust the regex": (1) text validation rejects
    multiple statements and any DDL/DML keyword anywhere in the string
    (`_SQL_KEYWORD_TERLARANG`), but (2) the real backstop is
    `SET TRANSACTION READ ONLY` issued before the query runs, which
    PostgreSQL itself enforces against every write path — including a
    data-modifying CTE smuggled inside a syntactically-SELECT statement
    (`WITH x AS (DELETE ... RETURNING *) SELECT * FROM x`) that would slip
    past a keyword-only filter. Verified directly: same statement run
    without the keyword-regex layer still gets rejected by Postgres with
    `ReadOnlySqlTransaction`. Don't remove the `SET TRANSACTION READ ONLY`
    call thinking the regex alone is sufficient.
  - `hitung_skor_ijd_usulan` — IJD teknokratik score isn't stored anywhere
    (computed on-the-fly by a weighted multi-component formula), so
    `jalankan_query_sql` can't answer score questions at all; this calls
    `usulan_inpres_ijd_score`/`_compute_ijd_score` directly instead of
    letting the model guess at replicating the algorithm via SQL.
  - `daftar_layer_peta_overlay` / `analisa_spasial_usulan` — spatial
    questions against the map overlay layers (`map_layers`, real PostGIS
    geometry) for a given usulan's route: nearest-N features + distance +
    intersection test, via `ST_GeomFromGeoJSON` cast (done in SQL, not
    Python/shapely, so none of the shapely/numpy MultiPolygon-from-dict bugs
    elsewhere in this codebase apply here) and a KNN `<->` ORDER BY so it
    uses `idx_map_layers_geom` instead of a full scan. Usulan route geometry
    itself (`usulan_inpres.geom_geojson`) is plain JSON text, not a native
    geometry column — that's why this needs its own tool rather than being
    answerable through `jalankan_query_sql`. `daftar_layer_peta_overlay`
    exists because the model needs the exact `(provinsi, kabupaten, layer)`
    triple first (reuses `maps_provinces`/`maps_kabupaten`/`maps_layers`
    directly) — **gotcha**: national flat buckets (`BANDARA`, `JALAN
    NASIONAL`, `BATAS PROVINSI`, etc.) have `kabupaten=""` as their one
    real, non-omittable value, not "no kabupaten yet" — the tool
    distinguishes this by checking `kabupaten is None` (not given) vs
    `kabupaten == ""` (given, flat bucket), not a truthiness check; a
    truthiness check silently gets stuck one level too shallow, which is
    the exact bug this was fixed from. In practice this 3-hop discovery
    (list buckets → list sub-wilayah → list layers → query) is only
    reliably chained by stronger models — observed gpt-4o-mini give up and
    report "no data" without ever calling `analisa_spasial_usulan` for the
    empty-kabupaten case, consistent with the same-model checklist-skipping
    behavior already documented for the bulk Bappenas narrative above.
  - `tampilkan_usulan_di_peta` — **not** in `CHAT_TOOL_DISPATCH`, registered
    in `CLIENT_ACTION_TOOLS` instead: this is the first "AI can act, not
    just answer" tool (27 Jul 2026). When the model calls a
    `CLIENT_ACTION_TOOLS` name, `_run_tool_call` records
    `{"nama", "argumen"}` into a per-request `actions` list (created fresh
    inside each `_call_openai_compatible`/`_call_openai_responses`/
    `_call_gemini`/`_call_claude` — deliberately NOT a module-level global,
    since FastAPI serves concurrent `/api/chat` requests) instead of
    dispatching server-side, and feeds the model a synthetic
    `{"status": "diteruskan_ke_frontend_untuk_dieksekusi"}` result so it
    still composes a normal closing sentence. `_call_chat` now returns
    `(text, actions)`; the `/api/chat` route returns both; `chat.js`'s
    `CHAT_CLIENT_ACTIONS` dispatch table (keys **must** stay in sync with
    `CLIENT_ACTION_TOOLS`) executes them — currently just
    `loadUsulanDetail(id)` (draws the route + opens its attribute panel,
    reusing the same function the "Jelajahi Usulan Inpres" browse panel
    already uses). Add new UI-facing tools by: adding the tool schema to
    `CHAT_TOOLS`, adding its name to `CLIENT_ACTION_TOOLS`, and adding a
    matching entry to `CHAT_CLIENT_ACTIONS` in chat.js — no other provider
    code needs to change, they all thread `actions` generically.
  - `tampilkan_layer_batas_administratif_usulan` — second UI-action tool
    (27 Jul 2026), but a different shape than `tampilkan_usulan_di_peta`:
    it's a **hybrid**, registered in both `CHAT_TOOL_DISPATCH` (runs
    server-side first) and `_TOOLS_NEED_ACTIONS_PARAM` (also gets the
    `actions` list passed in as a kwarg so it can append to it itself).
    Added because letting the model resolve the map-overlay `(provinsi,
    kabupaten, layer)` triple itself via `daftar_layer_peta_overlay` before
    calling a plain client-action tool was exactly the 3-hop chain
    `analisa_spasial_usulan` already struggles with — this tool takes
    `(id, level)` where `level ∈ {kecamatan, kabupaten, provinsi}`, resolves
    the usulan's own provinsi/kabupaten_kota from `usulan_inpres` and
    matches it against `map_layer_meta` server-side (ILIKE, handles the
    `KABUPATEN`/`KOTA` prefix stripping the same way
    `import_batas_administrasi_kecamatan.py`'s `kabupaten_label()` produces
    it), then appends a **generically-named** `tampilkan_layer_peta_overlay`
    action (not `tampilkan_layer_batas_administratif_usulan` — the tool name
    the model calls and the action name the frontend executes are
    deliberately different here) with the already-resolved, guaranteed-valid
    triple. `chat.js`'s handler for it just calls the existing
    `showMapLayer(provinsi, kabupaten, layer)` from maps-overlay.js — same
    function the overlay tree checkboxes use, works whether or not that
    panel is currently open. `BATAS PROVINSI` (flat national bucket,
    `kabupaten=""`, one layer) needs no resolution at all.
  OpenAI additionally gets `web_search_preview`; the system prompt tells the
  model whether web search is available.
- `GET /api/maps/provinces` / `GET /api/maps/kabupaten` / `GET /api/maps/layers`
  / `GET /api/maps/layer` — drive the topbar reference-map overlay. **As of
  24 Jul 2026 these query PostGIS (`map_layers`/`map_layer_meta` tables,
  `scripts/schema_map_layers_postgis.sql`), not the `Maps/` folder on disk**
  — `Maps/` itself is untouched (still the source of truth, gitignored,
  ~2.1GB) but is only read directly anymore by
  `scripts/import_maps_to_postgis.py` and the older `scripts/spatial_join_*.py`
  / `scripts/import_*.py` pipeline scripts that predate this migration
  (`_resolve_map_dir`/`MAPS_DIR`/`_batas_kec_shp` in app.py stay file-based
  on purpose, for those scripts' `from app import ...`). `map_layers` is one
  generic table (`provinsi`, `kabupaten`, `layer`, `attrs JSONB`, `geom
  geometry(Geometry,4326)`) rather than one table per layer, because every
  RBI `.shp`'s attribute columns differ — app.py never depended on specific
  column names anyway (`maps_layer()` just re-serializes `attrs` as GeoJSON
  `properties`), so this changes nothing observable. `map_layer_meta` is a
  fast provinsi/kabupaten/layer listing index (feature_count, size_mb,
  source_shp) so `maps_provinces`/`maps_kabupaten`/`maps_layers` don't have
  to scan the geometry table. `_map_layer_label` (now in `map_layer_labels.py`,
  shared with the import script) derives an Indonesian display name from the
  RBI code prefix via `MAP_LAYER_LABELS` (extend that dict for new layer
  codes). Geometry is simplified server-side (`ST_SimplifyPreserveTopology`)
  for layers with >3000 features (`feature_count` from `map_layer_meta`,
  cheaper than a live count) and the assembled GeoJSON is cached in-memory
  per (provinsi, kabupaten, layer) in `_map_layer_geojson_cache` — restart
  the server to pick up a re-import. `Maps/JALAN PROVINSI/` and
  `Maps/JALAN TOL/` are flat (no kabupaten subfolder) national road layers —
  imported with `kabupaten=""`, same fallback `maps_kabupaten` already used
  pre-migration; prefer flattening a new source to the plain
  provinsi/kabupaten shape over adding a special case (see `docs/MEMORY.md`
  §"Maps/ overlay").
  The "BATAS KECAMATAN" overlay (provinsi bucket fixed to that literal
  string, `BATAS_KEC_DIRNAME` in app.py) is sourced from
  `Maps/BATAS_ADMINISTRASI.gdb` (BIG file geodatabase, layer
  `ADMINISTRASI_KECAMATAN_AR`, 7283 definitive kecamatan polygons — replaced
  the old Dukcapil Dec 2019 SHP 26 Jul 2026), imported by
  `scripts/import_batas_administrasi_kecamatan.py`. Unlike every other
  `map_layers` source, this one has real per-polygon province/kabupaten
  attributes (`WADMPR`/`WADMKK`), so the import script writes them straight
  into the `kabupaten`/`layer` DB columns (kabupaten=real provinsi name,
  layer=real kabupaten/kota name) instead of stuffing them into `attrs` —
  the generic `maps_provinces`/`maps_kabupaten`/`maps_layers`/`maps_layer`
  endpoints then serve the provinsi→kabupaten→kecamatan-polygon hierarchy
  with **zero special-casing**, unlike the old SHP (no province/kabupaten
  columns at all, forced a virtual-hierarchy hack with name-matching against
  `penduduk_kecamatan` and a homonym-disambiguation heuristic — both gone
  now that the source carries ground truth). `KODE_KECAMATAN` (used by the
  identify popup's DB join) is still matched by name against
  `penduduk_kecamatan` at import time — the source's own `KDCPUM` column is
  a *Kemendagri* code, not BPS (verified 0% direct overlap with
  `kode_kecamatan`), so name-matching (now scoped per real kabupaten, ~96.6%
  hit rate, better than the old ~89-96%) is still required, just no longer
  ambiguous across regions. Geometry is `.simplify()`d at import time (not
  read time): the per-kabupaten feature counts here never cross the
  `maps_layer()` "simplify if >3000 features" threshold, but this source is
  far more vertex-dense than the old SHP, so it needs simplification
  regardless to stay light client-side. `_batas_kec_index()`/
  `_batas_kec_layer_geojson()` still exist in app.py (now just plain
  DB-column queries, no Python-side geometry surgery) purely for
  `scripts/import_indeks_penanaman_raster.py`'s reuse — not called by the
  maps endpoints anymore. `_batas_kec_shp()` (the *old* Dukcapil SHP, read
  straight off disk) is untouched and still feeds
  `spatial_join_kecamatan*.py`/`spatial_join_simpul_transportasi.py` (which
  set `usulan_inpres.kode_kecamatan`/`usulan_kecamatan_dilalui`, feeding IJD
  scoring) — that pipeline is deliberately a separate decision from the map
  overlay swap above and hasn't been repointed at the new gdb source.
  Kecamatan crossed by the currently displayed usulan route are recolored
  client-side (`updateKecamatanLintasan` in maps-overlay.js, now keyed off
  the `"BATAS KECAMATAN::"` layer-key prefix rather than a `BATASKEC__` raw
  layer name), and the identify popup joins the feature to DB tables via
  `GET /api/kecamatan/{kode}/data?tabel=` (whitelist `KECAMATAN_JOIN_TABLES`).

## Data pipeline (scripts/)

CLI scripts (venv active, PostgreSQL creds `PG_*` from `.env`) that verify
their target table exists (created by `migrate_pg_01_schema.py`) and
upsert, so they're safe to re-run:

- `import_usulan_inpres.py` — SITIA xlsx (in `docs/`) ↔ `usulan_inpres`
  table; `--export` regenerates an import-compatible xlsx.
- `import_penduduk_kecamatan.py` — BPS kode-wilayah + population per
  kecamatan master (basis for IJD score C.A1).
- `import_dpp_ijd_2025.py` — DPP IJD TA 2025 program list (646 kegiatan) +
  deterministic name/region matching that sets
  `usulan_inpres.lanjutan_ijd_2025`, the source of IJD parameter E.
- `build_wilayah_mapping.py` — SITIA region names → BPS codes
  (`wilayah_mapping` table, 100% coverage); rerun after each new usulan
  import. Rows with `metode='MANUAL'` are never overwritten.
- `build_kecamatan_turunan.py` — per-kecamatan derived table
  (`kecamatan_data_turunan`: density for IJD C.A1, vehicle counts with
  `kendaraan_estimasi=1` marking kab→kec proportional estimates); rerun
  after adding provinces to `dalam_angka/`.
- `fetch_kml_massal.py` — bulk-caches usulan route geometry into
  `geom_geojson` (SITIA uploads are a mix of KML/KMZ/nested-KMZ/zipped SHP —
  `_parse_usulan_geometry` handles all); resume-able, rerun for new tarikan.
- `spatial_join_kecamatan.py` — route geometry × `Maps/BATAS KECAMATAN`
  polygons → fills `usulan_inpres.kode_kecamatan` (basis of IJD C.A1);
  manual entries are never overwritten. Run after fetch_kml_massal.
- `spatial_join_kecamatan_multi.py` — complement to `spatial_join_kecamatan.py`
  (which only keeps the single dominant kecamatan): records **every**
  kecamatan a route crosses into `usulan_kecamatan_dilalui`, without
  touching `usulan_inpres.kode_kecamatan`. Reuses `norm`/`sample_points`
  from `spatial_join_kecamatan.py` rather than duplicating them, but samples
  much denser (~1 point/1.5km, min 20) so short kecamatan clipped only at a
  route's tail end still get caught. Feeds the chat/narrative
  "kecamatan dilalui" fact (`_kecamatan_dilalui_fakta` in app.py).
- `spatial_join_simpul_transportasi.py` — fills in coverage gaps for all 4
  transport-node SHP layers (`Maps/BANDARA/`, `Maps/KONEKTIVITAS SIMPUL
  TRANSPORTASI/{pelabuhan,Pelabuhan Penyeberangan,Pelabuhan Laut}/`) into
  `simpul_transportasi_kecamatan_radius` (fixed 30km radius, actual
  `jarak_km` per node per kecamatan — finer-grained than the kabupaten-level
  ada/tidak in `simpul_transportasi`). Point-in-polygon spatial join against
  `Maps/BATAS KECAMATAN` is the *only* method for the two layers with no
  usable text attributes (Bandara, Pelabuhan Laut); for the two layers
  `import_simpul_transportasi.py` already text-matches, it's a fallback for
  rows that failed text-match only. Reuses that script's
  `norm`/`_match_kabupaten`/`build_master_index` rather than rewriting them.
  See `docs/kajian_overlay_kecamatan_simpul_jalan.md`.
- `spatial_join_koridor_radius.py` — fills `usulan_inpres.koridor_
  radius_50m` (TEXT, nullable) with the `NO_KORIDOR` of the nearest `PETA
  KORIDOR` layer geometry within 50m (or NULL) via a batched `ST_DWithin`
  spatial JOIN, since both sides already live in PostGIS (unlike
  `spatial_join_kecamatan.py`, no geopandas/shapely needed here — the join
  runs entirely in SQL). Feeds IJD parameter D's "koridor tidak langsung"
  tier (`_ijd_score_koridor_v2` in app.py) — precomputed so scoring itself
  does zero spatial queries (~53s → ~5s for the national bulk score, see
  the `GET /api/usulan-inpres/{id}/ijd-score` entry above). Idempotent
  (only fills NULL rows unless `--force`) — rerun after `fetch_kml_massal.py`,
  reimporting `usulan_inpres`, or reimporting the PETA KORIDOR layer
  (`import_peta_koridor_to_postgis.py`) or the column goes stale, same
  caveat as `kode_kecamatan`.
- `sync_usulan_pipeline.py` — thin orchestration wrapper (subprocess, no
  new logic) that runs `import_usulan_inpres.py` (xlsx arg optional — skip
  if already imported via the browser) → `fetch_kml_massal.py` →
  `spatial_join_kecamatan.py` → `spatial_join_kecamatan_multi.py` →
  `spatial_join_koridor_radius.py` in the right order, stopping at the
  first failing step. Added so re-syncing everything after a usulan
  reimport/geometry refresh doesn't require remembering the 5-step order —
  safe to rerun anytime, each underlying script's own idempotency (or lack
  thereof, `spatial_join_kecamatan_multi.py` always fully recomputes) is
  unchanged.
- `import_maps_to_postgis.py` — one-way migration of every `.shp` under
  `Maps/` into PostGIS (`map_layers`/`map_layer_meta`), the source of
  `/api/maps/*` since 24 Jul 2026 (see above). Walks the same
  provinsi/[kabupaten]/*.shp structure the old file-based endpoints used to
  walk directly. Resumable per (provinsi, kabupaten, layer) — safe to rerun,
  skips what's already in `map_layer_meta` unless `--force`; `--provinsi`
  (repeatable) runs it province-by-province. Deliberately skips
  `Maps/IP2019-2024/` (rasters, has its own
  `import_indeks_penanaman_raster.py`) and `Maps/JALAN (mentah, belum
  diproses)/` (explicitly unprocessed staging data, duplicate of the already-
  imported `Maps/JALAN NASIONAL/`) — `--include-mentah` overrides the latter.
  Geometry read/cleanup is deliberately per-feature, not vectorized
  (`gdf.geometry.is_valid`, `shapely.force_2d(array)`) — a handful of source
  `.shp` files have degenerate geometry (e.g. a 1-point "LineString") that
  makes the *vectorized* GEOS call itself raise and take out every feature in
  the file, not just the bad one; `on_invalid="ignore"` on `gpd.read_file`
  covers the subset of cases where GDAL raises during parsing, before
  geopandas ever hands back a GeoDataFrame. One source file (`SULAWESI
  SELATAN/Kabupaten Barru/JALANLINE.shp`) is genuinely corrupt (bad `.shx`
  record length) and is skipped permanently, logged as `GAGAL` — not
  fixable from the read side.
- `import_batas_administrasi_kecamatan.py` — replaces the whole "BATAS
  KECAMATAN" `map_layers` bucket (DELETE + reinsert, not incremental) from
  `Maps/BATAS_ADMINISTRASI.gdb` (layer `ADMINISTRASI_KECAMATAN_AR`, BIG file
  geodatabase — needs `engine="pyogrio"` in `gpd.read_file`, the default
  `fiona` engine hits the same shapely/numpy MultiPolygon-from-dict bug
  described under `_batas_kec_layer_geojson` above). Separate from
  `import_maps_to_postgis.py` because the source is a `.gdb` (not a `.shp`
  under `Maps/<provinsi>/<kabupaten>/`) and needs name-matching against
  `penduduk_kecamatan` for `KODE_KECAMATAN` (see the app.py architecture
  note above for why). Does **not** touch `Maps/BATAS KECAMATAN/` (the old
  SHP) or re-run `spatial_join_kecamatan*.py` — rerun those separately and
  deliberately if the goal is also updating `usulan_inpres.kode_kecamatan`
  itself, not just the map overlay.
- `import_batas_administrasi_kabupaten_provinsi.py` — sibling to
  `import_batas_administrasi_kecamatan.py`, same `Maps/BATAS_ADMINISTRASI.gdb`
  source but layer `Area_Batas_Wilayah_Administrasi`, adding two more
  `map_layers` overlays: "BATAS KABUPATEN" (one layer per provinsi holding
  all its kabupaten/kota polygons) and "BATAS PROVINSI" (one national flat
  layer, `kabupaten=""`). The source has no clean one-row-per-provinsi
  layer — provinsi polygons are built here via `geopandas` `dissolve()`
  over every row (`TIPADM` 4=kabupaten/5=kota/6=unassigned island
  fragments) grouped by `WADMPR`; skipping `TIPADM=6` would drop small
  islands from the dissolved provinsi shape.
- `import_peta_koridor_to_postgis.py` — imports the "PETA KORIDOR" overlay
  layer (per-ruas geometry of Koridor IJD proposals, 11,612 features/506
  kabupaten/37 provinsi — all except DKI Jakarta) into `map_layers`/
  `map_layer_meta`, one `layer="PETA KORIDOR"` row per (provinsi,
  kabupaten) — **not** one layer per koridor. Source is deliberately
  `Maps/PETA KORIDOR/GABUNGAN_KORIDOR_SELURUH_INDONESIA/
  seluruh_ruas_koridor_indonesia.shp`, a single pre-merged national file
  (verified clean: 0 null/empty geometry, 0 null `NO_KORIDOR`, 0 duplicate
  `(NO_KORIDOR, ID_RUAS)`), **not** the ~10,624 per-koridor `.shp` files
  under `Maps/PETA KORIDOR/<provinsi>/<kabupaten>/SHP_PER_KORIDOR/<nama
  koridor>/` (same data, split apart one koridor at a time — walking those
  would need 3 extra directory levels beyond what `import_maps_to_postgis.py`
  handles and would blow up the layer picker to thousands of entries per
  kabupaten if imported 1:1). `RUAS_KML_KMZ/*.kml` (raw per-ruas upload) and
  the per-koridor `.gpkg` duplicates are intentionally skipped — the merged
  national `.shp` is already the processed/validated version. `attrs->>
  'NO_KORIDOR'` on each feature is the same code format as
  `usulan_inpres.kode_koridor` / `bappenas_koridor.no_koridor` (e.g.
  `"11-KG-002"`) — this overlay is the first place actual koridor geometry
  (not just a text code) is queryable, useful groundwork for a future
  spatial (not just text-match) version of parameter D's `kode_koridor`
  validation, though that's not implemented yet. `size_mb` in
  `map_layer_meta` is an estimate of the per-kabupaten payload actually
  stored (JSON attrs + WKB), not `source_shp`'s file size — unlike every
  other `import_*_to_postgis.py` script, one shared source file here maps
  to hundreds of layer rows, so the source file's total size would be
  misleading per-row. Resumable per (provinsi, kabupaten) via
  `map_layer_meta`, `--force` to reimport, `--provinsi` (repeatable) to
  scope a run.
- `import_kemantapan_ijd2026.py` — road-soundness per kab/kota
  (`kemantapan_ijd_2026`), the source of IJD pagu component G8.A2; also
  writes the official "Tidak mantap (%)" figure into
  `bps_kabupaten_jalan.tidak_mantap_pct_ijd` (Kab./Kota rows only, matched
  by `kode_kab`) as an independent comparison against that table's
  BPS-PDF-derived `kondisi_*_km` columns.
- `import_bappenas_koridor.py` — SITIA koridor master + Bappenas tematik/
  connectivity/priority-rank annotations (`Daftar_Koridor_Bappenas_Admin_*.xlsx`)
  → `bappenas_koridor`, keyed by `id_koridor` (the SITIA numeric ID).
  Koridor-level, not ruas-level — the source file's ruas-detail columns are
  always `"---"` at this granularity and are intentionally not imported.
- `import_kawasan_tematik.py` — thematic kawasan (Perkebunan/Perikanan/
  Transmigrasi/KI Prioritas/PKPN) from the Bappenas lokus workbook →
  `kawasan_tematik`, the source of IJD parameter A3.
- `import_bappenas_lokus_a.py` — Aspek A Bappenas lokus criteria (LOKPRI,
  PKPN, PKSN, Perbatasan, Transmigrasi, SR, Sekolah Garuda, KNMP, KDMP,
  KI Prioritas, Swasembada Pangan RPJMN, BBM 1 Harga, KPP_DESA) →
  `bappenas_lokus_a`; each criterion's parsing rule (sheet name, matching
  logic) lives in `KRITERIA_SOURCES`, shared with the
  `/api/bappenas-lokus-a/import` endpoint. Sheet names cited in the source
  "Kumpulan Data" inventory are frequently imprecise — always verify
  against the actual xlsx before trusting a citation there.
- `import_kertas_kerja.py` — Indeks Penanaman (IP) per kabupaten from
  `Kertas Kerja.xlsx` sheet "Kertas Kerja" (not the "Master Data" sheet the
  source inventory names) → `bps_kabupaten_indeks_penanaman`, the source of
  IJD C.A2 Indeks Penanaman sub-parameter; outlier-clamps IP outside
  0-500%.
- `import_ip_oplah.py` — supersedes `import_kertas_kerja.py`'s values (by
  name match, not a full replace) with `docs/docs/IP 2019-2024, OPLAH.xlsx`
  sheet "IP TOTAL" (IP 2024 column) — per
  `docs/perbandingan_ip_oplah_vs_bps_kabupaten_indeks_penanaman.md`, OPLAH
  (satellite Luas Tanam + ML) matches the primary raster source
  (`bps_kabupaten_indeks_penanaman_raster`) 84.4% of the time vs. Kertas
  Kerja's 23.6% (administrative Luas Panen, prone to false-zero rows) —
  decided/approved by the user 27 Jul 2026. Run after
  `import_kertas_kerja.py`, not instead of it.
- `import_konektivitas_jalan.py` / `import_jalan_nasional.py` /
  `spatial_konektivitas_jalan.py` — three-part "Konektivitas Jaringan
  Jalan" signal for Laporan Daerah Prioritas Aspek B
  (`konektivitas_jaringan_jalan` table), from weakest to strongest proxy.
  `import_konektivitas_jalan.py` sets `ada_jalan_daerah` per kabupaten from
  the `Maps/<provinsi>/<kabupaten>/` folder structure itself (matched by
  folder name, not shapefile attributes — those vary too much across the
  234 per-kabupaten road SHPs to be reliable). `import_jalan_nasional.py`
  adds a stronger signal, `ada_jalan_nasional`, from `Maps/JALAN
  NASIONAL/Jalan Nasional.shp`'s `CITY_ID` column (a direct BPS kabupaten
  code, no matching needed) without touching `ada_jalan_daerah` — same
  table, additive UPSERT. `spatial_konektivitas_jalan.py` is the real
  spatial check (explicit user request,
  `docs/spec/laporan prioritas.md`): per usulan with cached KML geometry,
  tests actual distance (reprojected to EPSG:3857 for meters, `STRtree`
  built from Jalan Nasional + Jalan Provinsi + Jalan Tol combined) against
  a 100m threshold (confirmed with the user 21 Jul 2026) rather than just
  "kabupaten has a mapped road."
- `extract_dalam_angka.py` — parses BPS "Kab/Kota Dalam Angka" PDFs from
  `dalam_angka/<kode> <Provinsi>/` (all 38 provinces downloaded; supports
  `--workers N` for concurrent per-province PDF parsing). Feeds IJD
  parameter C tables (`schema_bps_kemanfaatan.sql`): kecamatan density
  (C.A1), kabupaten padi productivity (C.A2), kabupaten vehicle counts
  (C.A3 proxy). Coverage varies a lot by province/table — a province having
  the province-level book doesn't guarantee a given BPS table parses
  cleanly (format drifts between provinces); see `docs/checklist_implementasi_cpit.md`
  for current per-province coverage. Also feeds
  `bps_kecamatan_produksi_komoditas` (`schema_kecamatan_produksi_komoditas.sql`,
  via `_extract_kecamatan_table_by_group`): per-kecamatan production
  **per commodity** (`jenis_tanaman` kept verbatim from the PDF header, not
  normalized — the commodity list isn't uniform across kab/kota), distinct
  from `bps_kecamatan_potensi_tematik.perkebunan_produksi_ton` which sums
  all commodities into one number. Added 2026-07-21 after a per-commodity
  cross-check surfaced the `_is_total_row` bug below.
- `extract_statistik_indonesia.py` — parses `docs/docs/00 Statistik
  Indonesia 2026.pdf` for province-level road-length/vehicle/sawah-land
  tables (`schema_statistik_indonesia.sql`: `si_panjang_jalan_provinsi`,
  `si_kendaraan_provinsi`, `si_lahan_sawah_provinsi`) — feeds Pagu
  Provinsi A1 and A3.
- `sync_dalam_angka_bps_api.py` — syncs `dalam_angka_publikasi` (link
  catalog, not the PDFs themselves) from BPS Web API (`webapi.bps.go.id`,
  needs `BPS_API_KEY` in `.env`, free registration) for every
  provinsi/kabupaten — replaces hosting the ~9.6GB `dalam_angka/` PDF corpus
  on the server. Cached `url_publikasi` tokens can expire; the app re-fetches
  a fresh one on demand (`/api/dalam-angka/preview`), this script just seeds/
  refreshes the catalog. Rerun periodically to catch newly-published years.
- `sync_kepadatan_kabupaten_bps_api.py` — kabupaten-level population density
  from BPS Web API's per-provinsi dynamic tables (`bps_api_kepadatan_kabupaten`,
  schema in `schema_bps_api_kepadatan_kabupaten.sql`) — an independent
  **cross-check** source for IJD C.A1, not a replacement for
  `kecamatan_data_turunan` (finer-grained, kecamatan-level). Coverage/
  freshness varies per province (each BPS provincial office manages its own
  dynamic-table `var_id`, some as recent as 2024, others 2016-2021, some
  missing entirely) — **not currently wired into any scoring or UI
  endpoint**, reference data only as of 24 Jul 2026.
- `smoke_check.py` — not a test suite (see `docs/ARCHITECTURE.md`
  §"Verification without a test suite"); a reusable before/after
  structural diff (`--save`/`--check`) over a fixed list of read-only
  endpoints, meant as a safety net while incrementally refactoring app.py
  (e.g. moving functions to a new module) without changing behavior.

The PDF extractors are position/regex-based (PyMuPDF) and tuned to the 2026
BPS layouts — expect to adjust them for other publication years.

Several source files under `docs/docs/` (`5_IJD 2026 - DATA...xlsx`,
`6_Usulan Lokus IJD 2026 Sektor Bappenas.xlsx`) were pulled from public
Google Sheets/Drive links embedded in file 2's "Kumpulan Data" sheet
(column E hyperlinks, not just filenames — most resolve directly via
`.../export?format=xlsx` or `embeddedfolderview?id=<id>#list` for folders,
no auth needed). See `docs/checklist_implementasi_cpit.md` Fase 9 for the
full link inventory, including a public "Dalam Angka" Drive folder (all 38
provinces now downloaded locally to `dalam_angka/`) and public SHP folders
for road/transport-node connectivity validation.

## Conventions / gotchas

- Coordinate order and the no-test-suite verification approach are common
  trip-ups — see `docs/ARCHITECTURE.md` (§"Coordinate order",
  §"Verification without a test suite") rather than re-deriving them.
- SHP export uses a `TemporaryDirectory`, writes with `pyogrio` engine, then
  zips the sidecar files (`.shp/.dbf/.shx/.prj/.cpg`) in memory.
- `maps.md` is a design/spec doc (Indonesian), not source of truth for
  implemented behavior — cross-check against app.py before trusting it.
  **It currently contains a hardcoded Google Maps API key at the bottom —
  treat as sensitive, don't propagate it into new files.**
- `docs/` holds the domain source material (IJD scoring criteria PDFs, CPIT
  framework, SITIA export xlsx, gap analyses) — the SQL schema comments cite
  specific documents/tables there; keep those citations accurate when
  changing schemas.
