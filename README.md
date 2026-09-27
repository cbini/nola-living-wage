# nola-living-wage

How many people who work in Orleans Parish (place of work, not residence) earn below the MIT living wage, what it would cost to close the gap, and whether the parish's output can cover it. See [SPEC.md](SPEC.md); results are in [data/out/results.md](data/out/results.md).

## Reproduce

```sh
uv sync
cp .env.example .env   # both keys optional; bulk downloads need none
uv run --env-file .env nola-lw all   # uv loads the keys from .env
```

`all` runs fetch → checkpoint → run. The steps also run alone:

- `nola-lw fetch` downloads every source to `data/raw/` (manifest with URL, date, sha256). MIT thresholds come from the committed snapshot unless `--refresh-mit` is passed.
- `nola-lw checkpoint` writes `data/out/checkpoint.md` (SPEC §11 step 2).
- `nola-lw run` builds the universe, gaps, households, crosswalk, capacity and sensitivities from `data/raw/`, and writes `data/out/results.md`, one CSV per table, two charts and the QA log `data/out/qa.md`.
