# nola-living-wage

How many people who work in Orleans Parish (place of work, not residence) earn below the MIT living wage, what it would cost to close the gap, and whether the parish's output can cover it. See [SPEC.md](SPEC.md).

## Reproduce

```sh
uv sync
cp .env.example .env   # both keys optional; bulk downloads need none
uv run nola-lw all
```
