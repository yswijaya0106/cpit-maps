# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# analytic-maps (RouteGIS)

FastAPI backend + vanilla JS frontend. Route planning on Google Maps, route
analysis, export to GIS formats, browsing/scoring of Inpres Jalan Daerah (IJD)
road proposals, and an AI chat assistant. UI/user-facing strings, code
comments, and docstrings are in Indonesian.

This file covers the file map and run instructions. For design rationale
and reusable patterns, see `docs/ARCHITECTURE.md`; for change recipes, see
`CONTRIBUTING.md`; for hard-won gotchas, see `docs/MEMORY.md`; for adding an
IJD scoring parameter specifically, use the `ijd-scoring-parameter` skill
(`.claude/skills/`).

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
- `MYSQL_HOST/PORT/USER/PASS/DB` — MySQL connection (default db `route_gis`).
  Usulan-Inpres browsing, IJD scoring, the Data viewer, and chat DB tools all
  need it; route planning/export works without it.
- Chat provider keys, all optional: `GROQ_API_KEY`, `GROK_API_KEY`,
  `OPEN_AI_API_KEY`, `CLOUDE_API_KEY` (Anthropic — yes, spelled with OU;
  don't "fix" the name without migrating existing `.env` files),
  `GEMINI_API_KEY`. `/api/chat` tries providers in that order until one
  succeeds (see `_call_chat`); with zero keys the chat panel is dead but the
  rest of the app works.

Deps: `requirements.txt`, venv at `.venv/` (already gitignored).

## Architecture (single-file backend + MySQL, no ORM)

- [app.py](app.py) — entire backend (~3500 lines). FastAPI app, all routes,
  all GIS logic, IJD scoring, chat providers. No other backend modules exist;
  don't go looking for a `routers/` or `services/` dir.
- Database: MySQL via `pymysql`, raw parameterized SQL through the
  `db_cursor()` contextmanager in app.py. Schemas live as plain SQL files in
  [scripts/](scripts/) (`schema_*.sql`); tables are populated by the import/
  extract scripts there, not by the app (exception: the app upserts via
  `/api/usulan-inpres/import` and caches fetched KML into
  `usulan_inpres.geom_geojson`).
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
  panels) → `usulan-inpres.js` (Inpres match + browse/detail) → `chat.js`
  (chat panel, grounded in the currently viewed route) → `export.js` →
  `main.js` (reset, top-level event binding). All files share the same global
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
  + A4 data dukung), B, C (A1 kepadatan only, via `kecamatan_data_turunan`
  + `usulan_inpres.kode_kecamatan`), D, and E; F was removed from the 2026
  policy. Every component that lacks a data source reports
  `"tersedia": false` with a specific reason instead of contributing 0 —
  `skor_ternormalisasi_100` is normalized against `bobot_tersedia`, not 100.
  See `.claude/skills/ijd-scoring-parameter/` before touching this.
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
- `GET /api/bappenas-lokus-a/kriteria` / `POST .../import` — list the Aspek
  A Bappenas lokus criteria (`bappenas_lokus_a` table, ~13 kriteria: LOKPRI,
  PKPN, PKSN, KI Prioritas, BBM 1 Harga, KPP_DESA, etc.) with row counts,
  and let a user re-upload the source xlsx for one criterion (DELETE+INSERT
  for that `kriteria` only). Parsing logic lives once in
  `scripts/import_bappenas_lokus_a.py` (`KRITERIA_SOURCES`); this endpoint
  imports that module rather than duplicating the per-sheet regex/matching
  rules. Browsed via the navbar "Lokus Bappenas" button (separate from the
  generic "Data" viewer, `data-viewer.js` `dataViewerOpenLokusBappenas()`).
- `GET`/`POST /api/usulan-inpres/{id}/penilaian-bappenas` — AI-generated
  draft of the Bappenas qualitative assessment (aspek A/B points + narrative,
  cached in `penilaian_bappenas_ai`). Uses `_llm_plain()` — the tool-less
  provider fallback chain. Always labelled as an AI draft in the UI; keep it
  that way.
- `GET /api/data/tables` / `GET /api/data/{table}` — read-only paged table
  viewer behind the topbar "Data" button. Only tables whitelisted in
  `DATA_TABLES` in app.py are exposed — add new tables there.
- `POST /api/penduduk-kecamatan/import` / `GET .../export/xlsx` — BPS
  population-per-kecamatan master (also loadable via the CLI script).
- `POST /api/chat` — chat assistant. Providers are tried in order
  Groq → Grok → OpenAI → Claude → Gemini depending on which API keys exist.
  The model gets a compact context of the currently viewed route plus three
  read-only tools (`CHAT_TOOLS`: search/detail/KML-geometry of usulan) that
  call existing parameterized-query helpers — **never give the model free-form
  SQL**. OpenAI additionally gets `web_search_preview`; the system prompt
  tells the model whether web search is available.
- `GET /api/maps/provinces` / `GET /api/maps/kabupaten` / `GET /api/maps/layers`
  / `GET /api/maps/layer` — drive the topbar reference-map overlay. Read
  shapefiles from `Maps/<provinsi>/<kabupaten>/*.shp` (two levels — mirrors
  the provinsi/kabupaten_kota split already used by usulan-inpres), each
  kabupaten folder holding ~40 RBI-style thematic `.shp` layers.
  `_map_layer_label` derives an Indonesian display name from the RBI code
  prefix via `MAP_LAYER_LABELS` (extend that dict for new layer codes).
  Geometry is simplified for layers with >3000 features (the 68MB
  `KONTUR_LN_25K.shp` contour layer is why) and cached in-memory per
  (provinsi, kabupaten, layer) in `_map_layer_geojson_cache` — restart the
  server to pick up changed `.shp` files. `Maps/JALAN PROVINSI/` and
  `Maps/JALAN TOL/` are flat (no kabupaten subfolder) national road layers —
  `maps_kabupaten`'s existing `kabupaten=""` fallback handles those with no
  special-case code; prefer flattening a new source to the plain
  provinsi/kabupaten shape over adding a special case (see `docs/MEMORY.md`
  §"Maps/ overlay").
  `Maps/BATAS KECAMATAN/` (national Dukcapil 2019 kecamatan-boundary SHP,
  90MB, attribute = kecamatan name ONLY) is special-cased as a virtual
  hierarchy in these same endpoints: the "kabupaten" dropdown lists
  provinces, layers are kabupaten (id `BATASKEC__<prov>__<kab>`), features
  carry KODE_KECAMATAN matched by name against `penduduk_kecamatan`
  (exact → space-collapsed → numeral-equalized SATU↔I↔1; ~96% polygon
  coverage; homonym multipolygons are trimmed to parts adjacent to their
  kabupaten). Kecamatan crossed by the currently displayed usulan route are
  recolored client-side (`updateKecamatanLintasan` in maps-overlay.js), and
  the identify popup joins the feature to DB tables via
  `GET /api/kecamatan/{kode}/data?tabel=` (whitelist
  `KECAMATAN_JOIN_TABLES`).

## Data pipeline (scripts/)

CLI scripts (venv active, MySQL creds from `.env`) that create their schema
if missing and upsert, so they're safe to re-run:

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
- `import_kemantapan_ijd2026.py` — road-soundness per kab/kota
  (`kemantapan_ijd_2026`), the source of IJD pagu component G8.A2.
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
- `extract_dalam_angka.py` — parses BPS "Kab/Kota Dalam Angka" PDFs from
  `dalam_angka/<kode> <Provinsi>/` (all 38 provinces downloaded; supports
  `--workers N` for concurrent per-province PDF parsing). Feeds IJD
  parameter C tables (`schema_bps_kemanfaatan.sql`): kecamatan density
  (C.A1), kabupaten padi productivity (C.A2), kabupaten vehicle counts
  (C.A3 proxy). Coverage varies a lot by province/table — a province having
  the province-level book doesn't guarantee a given BPS table parses
  cleanly (format drifts between provinces); see `docs/checklist_implementasi_cpit.md`
  for current per-province coverage.
- `extract_statistik_indonesia.py` — parses `docs/docs/00 Statistik
  Indonesia 2026.pdf` for province-level road-length/vehicle/sawah-land
  tables (`schema_statistik_indonesia.sql`: `si_panjang_jalan_provinsi`,
  `si_kendaraan_provinsi`, `si_lahan_sawah_provinsi`) — feeds Pagu
  Provinsi A1 and A3.
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
