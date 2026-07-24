# The Next - SiJalan (analytic-maps)

FastAPI + vanilla JS route planning tool on Google Maps, with GIS export and
an Indonesian Inpres Jalan Daerah (IJD/CPIT) proposal-scoring module built
on top. UI and domain content are in Indonesian.

## Quick start

```
.venv\Scripts\Activate.ps1
python app.py
```

Needs `.env` (copy `.env.example`) — see `CLAUDE.md`'s Run section for
required keys and what breaks without each.

## Where to look

| Question | Doc |
|---|---|
| How is the codebase laid out? How do I run it? | `CLAUDE.md` |
| Why is it built this way? What patterns should I reuse? | `docs/ARCHITECTURE.md` |
| I'm about to make a change — what's the recipe? | `CONTRIBUTING.md` |
| Has someone already hit this bug/gotcha? | `docs/MEMORY.md` |
| What's the status of the IJD/CPIT scoring work? | `docs/checklist_implementasi_cpit.md` |
| What data gaps remain, and why? | `docs/analisa_gap_cpit.md` |

No test suite, no build step, no ORM — see `docs/ARCHITECTURE.md` for why
each of those is a deliberate choice, not a gap.
