# Contributing

Practical recipes for common changes. For environment setup and the file
map, see `CLAUDE.md`. For design rationale, see `docs/ARCHITECTURE.md`. For
non-obvious gotchas already paid for once, see `docs/MEMORY.md` — check it
before debugging something that feels like it should just work.

## Setup

```
.venv\Scripts\Activate.ps1
python app.py
```

`.env` needs `GOOGLE_MAPS_API_KEY` at minimum; `PG_*` (PostgreSQL) for
anything touching usulan/IJD/CPIT data (most of the recent work). See
CLAUDE.md's Run section for the full list and what breaks without each key.

## Adding a new import/build script

Copy the shape of an existing one (`scripts/import_dpp_ijd_2025.py` is a
clean example) rather than starting from scratch:

1. `schema_<name>.sql` — `CREATE TABLE IF NOT EXISTS`, comment header
   explaining the source file/sheet and what gap/parameter it feeds.
2. `import_<name>.py` — `connect()` → `run_schema()` → parse → upsert via
   `ON CONFLICT ... DO UPDATE` → print a summary (rows processed, rows
   skipped by reason). Must be safe to re-run on the same input.
3. If the source needs Indonesian place-name matching, reuse the four-step
   cascade described in `docs/MEMORY.md`, don't write a new fuzzy matcher.
4. Register any new browsable table in `DATA_TABLES` (app.py) so it shows
   up in the topbar "Data" viewer — free UI, no reason to skip it.

## Adding or changing an IJD scoring parameter

This has a Claude Code skill: `.claude/skills/ijd-scoring-parameter/`. Use
it (`/ijd-scoring-parameter` or ask Claude to follow it) rather than
re-deriving the pattern — it encodes the seed-rules → scorer-function →
register → verify loop that's been repeated ~8 times this project.

## Adding a new export format

`_build_<format>()` helper in app.py + a branch in `POST /api/export`'s
dispatch. Watch the coordinate order (`docs/ARCHITECTURE.md`) — this is
where it bites most often.

## Adding a new map overlay data source

If it's a `.shp` under `Maps/<provinsi>/<kabupaten>/`, it needs zero code —
the topbar layer picker discovers files by scanning the directory. If it's
a differently-shaped source (see `Maps/BATAS KECAMATAN/` for a precedent —
one national file, no province/kabupaten subfolder, attributes needing a
name-matched index), special-case it in `maps_provinces`/`maps_kabupaten`/
`maps_layers`/`maps_layer` the way `BATAS_KEC_DIRNAME` is handled, and build
a lazily-cached index function rather than re-scanning per request.

## Conventions

- UI strings, code comments, and docstrings: **Indonesian**. Identifiers:
  English is fine (existing code mixes both — match whatever's already in
  the file you're editing rather than converting wholesale).
- No comments explaining *what* code does — name things so it's obvious.
  Comments earn their place only for a non-obvious *why* (a policy
  constraint, a library quirk, a workaround for a specific bug — see the
  density of "why" comments already in app.py's scoring functions as the
  bar to match).
- Don't add error handling for inputs that can't occur (internal scripts,
  trusted DB state). Do handle malformed external data defensively (xlsx
  imports, external API responses) — the difference is whether the input
  crosses a trust boundary.
- Commit only when asked. When asked, follow the message style already in
  `git log` (terse, present-tense, states the *why* not the diff).

## Verifying a change

No test suite — see `docs/ARCHITECTURE.md`'s verification section. Concretely:
write a one-off script under the scratchpad dir using
`fastapi.testclient.TestClient`, compare against a hand-computed expected
value, run it, delete it. For anything touching the map UI, actually run
`python app.py` and click through the feature in a browser — type checking
a scoring function doesn't tell you a CSS `[hidden]` override is missing.

## Updating project docs

- `checklist_implementasi_cpit.md` — task status per CPIT/IJD gap (G1-G19).
  Update the relevant `Fase N` section when you close or partially close a
  gap; keep the "terblokir" list accurate (don't leave stale blockers once
  a file shows up in `docs/docs/`).
- `docs/MEMORY.md` — add an entry only for something that would cost real
  time to rediscover (an environment bug, a data-format surprise, a design
  decision that isn't obvious from the code). Don't log routine work here.
- `CLAUDE.md` — update when the *shape* of the codebase changes (new
  top-level module, new endpoint category, new required env var) — not for
  every feature.
