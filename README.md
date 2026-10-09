# scratch – Onshape variable converter

Moves variables between **Part Studio variables**, **Variable Studio variables** and
**Configuration (quantity) inputs**, in any direction. Variables are *moved*: written to the
destination, re-read to verify, then deleted from the source.

## Setup
Create an API key at <https://dev-portal.onshape.com> and export it (or put it in a git-ignored `.env`):

```
ONSHAPE_ACCESS_KEY=...
ONSHAPE_SECRET_KEY=...
# optional: ONSHAPE_BASE_URL=https://company.onshape.com  ONSHAPE_API_VERSION=v10
```

## Usage
Use workspace URLs (`/w/`), since versions are read-only.

```
# Part Studio variables -> configuration inputs (same Part Studio)
uv run scratch convert <partstudio-url> --from partstudio --to config --names width,height

# Part Studio / config -> a Variable Studio (found/created by name, then referenced by the Part Studio)
uv run scratch convert <partstudio-url> --from config --to variablestudio --vs-name Variables
uv run scratch convert <partstudio-url> --from partstudio --to variablestudio --target-url <variablestudio-url>

# Variable Studio -> Part Studio variables / configuration inputs (target Part Studio required)
uv run scratch convert <variablestudio-url> --from variablestudio --to partstudio --target-url <partstudio-url>
```

`--dry-run` previews; `--names a,b` selects a subset (default: all).

## Behaviour and limits
- Only LENGTH / ANGLE / NUMBER variables. Others (string, boolean, enum, list, untypable formulas) are skipped and reported.
- Configuration defaults must be plain `<number> <unit>` literals; formulas are skipped when converting to config. Config min/max are generated (`min(0, v)` .. `10x|v|`).
- A name already present in the destination aborts the run before anything changes.
- Part Studio variables are appended at the end of the feature list.
- Deleting a configuration input may affect features that reference it.

## Development
`uv run pytest`. Endpoint shapes come from the public Onshape API (`/variables`, `/partstudios/.../features`
`assignVariable`, `/elements/.../configuration`); tests use mocked HTTP, so try `--dry-run` and a scratch
document first against a real account.

## Live tests
`tests/live/` runs the converter against the Onshape document "test" and resets its six baseline
variables (`src/scratch/og_vars.py`) before and after every test. Skipped unless the key is set:

```
$env:ONSHAPE_TEST_API_KEY = "access:secret"
uv run pytest -m live
```
