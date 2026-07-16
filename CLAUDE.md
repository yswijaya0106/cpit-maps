# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# analytic-maps (RouteGIS)

FastAPI backend + vanilla JS frontend. Route planning on Google Maps, route
analysis, export to GIS formats, browsing/scoring of Inpres Jalan Daerah (IJD)
road proposals, and an AI chat assistant. UI/user-facing strings, code
comments, and docstrings are in Indonesian.

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

- [app.py](app.py) — entire backend (~1600 lines). FastAPI app, all routes,
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
- `GET /api/usulan-inpres/{id}/ijd-score` — "Prioritisasi Teknokratik"
  scoring per Inpres 11/2025. Weights/values are **data, not code**: rows in
  the `ijd_scoring_rules` table (seeded by `scripts/schema_ijd_scoring.sql`)
  keyed by `tahun_berlaku`, so policy changes mean SQL updates, not code
  changes. Only parameters A/B/D/F are computed; C and E are intentionally
  reported "belum tersedia" (see `IJD_PENDING_PARAMETERS`) until their BPS
  source tables are populated by the extract scripts.
- `GET /api/usulan-inpres/{id}/skor-prioritas-nasional` /
  `GET /api/prioritas-nasional` — national priority score (70% teknokratis +
  10% PU + 10% Bappenas + 10% Kemenko per the 14072026 document) and the
  national ranking; Bappenas/Kemenko indication columns are imported but
  still empty in the 15 Juli snapshot, so they currently score 0.
- `GET /api/pagu-provinsi` / `GET /api/alokasi-2-lapis` — provincial
  indicative budget (partial score: road-length A1 + fiscal A4 only,
  renormalized shares) and the two-layer allocation simulation on top of the
  national ranking. Both label themselves "perkiraan/parsial" — keep that.
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
  server to pick up changed `.shp` files.
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
- `extract_dalam_angka.py` — parses BPS "Kab/Kota Dalam Angka" PDFs from
  `dalam_angka/<kode> <Provinsi>/` (currently only 36 Banten; drop in more
  province folders and re-run with `--load`). Feeds IJD parameter C tables
  (`schema_bps_kemanfaatan.sql`).
- `extract_statistik_indonesia.py` — parses `docs/docs/00 Statistik
  Indonesia 2026.pdf` for province-level road-length/vehicle/sawah tables
  (`schema_statistik_indonesia.sql`).

The PDF extractors are position/regex-based (PyMuPDF) and tuned to the 2026
BPS layouts — expect to adjust them for other publication years.

## Conventions / gotchas

- Coordinates are `[lat, lng]` in API payloads but shapely/geojson need
  `(lng, lat)` — conversions happen inline in the `_build_*`/`_routes_to_*`
  helpers, easy to get backwards when adding new export formats.
- SHP export uses a `TemporaryDirectory`, writes with `pyogrio` engine, then
  zips the sidecar files (`.shp/.dbf/.shx/.prj/.cpg`) in memory.
- No test suite exists. Verify changes by running the app and exercising the
  UI (route search → analysis → export) rather than assuming coverage.
- `maps.md` is a design/spec doc (Indonesian), not source of truth for
  implemented behavior — cross-check against app.py before trusting it.
  **It currently contains a hardcoded Google Maps API key at the bottom —
  treat as sensitive, don't propagate it into new files.**
- `docs/` holds the domain source material (IJD scoring criteria PDFs, CPIT
  framework, SITIA export xlsx, gap analyses) — the SQL schema comments cite
  specific documents/tables there; keep those citations accurate when
  changing schemas.
