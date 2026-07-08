# analytic-maps (RouteGIS)

FastAPI backend + vanilla JS frontend. Route planning on Google Maps, route
analysis, export to GIS formats. UI/user-facing strings are in Indonesian.

## Run

Windows: the bare `python` command resolves to the Microsoft Store alias
stub unless the venv is activated first — activate before running anything:

```
.venv\Scripts\Activate.ps1         # PowerShell; may need Set-ExecutionPolicy -Scope Process RemoteSigned first
python app.py                      # uvicorn with reload, port from .env (default 8000)
```

Requires `.env` (copy from `.env.example`) with `GOOGLE_MAPS_API_KEY` set —
`/api/config` returns 500 without it, which breaks the whole frontend (the
Maps JS SDK is loaded dynamically via that endpoint, see static/index.html).

Deps: `requirements.txt`, venv at `.venv/` (already gitignored).

## Architecture (single-file backend, no ORM/DB)

- [app.py](app.py) — entire backend. FastAPI app, all routes, all GIS logic.
  No other backend modules exist; don't go looking for a `routers/` or
  `services/` dir.
- [static/index.html](static/index.html) — one page, no build step, no framework.
- [static/js/](static/js/) — frontend logic, split into plain `<script>` files
  (no bundler, no ES modules) loaded in dependency order from index.html:
  `state.js` (global `state` object, toast/status) → `utils.js` (formatting
  helpers) → `map-bootstrap.js` (Maps init, geocoding) → `points.js`
  (origin/destination/waypoints, markers) → `routing.js` (Directions calls,
  route computation) → `drawing.js` (polylines, hover) → `maps-overlay.js`
  (topbar layer picker; toggles reference SHP layers from `Maps/` on/off as
  `google.maps.Data` overlays) → `route-list.js` (result list + analysis
  panel) → `analysis.js` (admin region / road classification panels) →
  `usulan-inpres.js` (Inpres match + browse/detail) → `export.js` →
  `main.js` (reset, top-level event binding). All files
  share the same global scope — add a new script tag in index.html (in the
  right position relative to its dependencies) rather than reintroducing a
  single monolithic file.
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
