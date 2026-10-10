# onshape_var_convert – Onshape variable converter

Moves variables between **Part Studio variables**, **Variable Studio variables** and **Configuration (quantity)
inputs**, in any direction. Variables are *moved*: written to the destination, re-read to verify, then deleted from the
source.

Mostly by Sonnet 5.5

## Setup

Create an API key at <https://dev-portal.onshape.com> and rename `.env.example` as '.env' before populating the keys.

## installation

Clone the repo.  
If you will use it a lot recommend `uv tool install [repo-path]` to install as a uv tool, so can run from
terminal anywhere with `onshape_var_convert <ps url> --from --to` command.
Otherwise you need to run from the repo root dir, or provide that path to uv, eg `uv run <path to repo> <ps url>...`

## Usage

```
# Convert Part Studio variables -> configuration inputs (same Part Studio)
uv run onshape_var_convert <partstudio-url> --from partstudio --to config --names width,height

# Part Studio / config -> a Variable Studio (found/created by name, then referenced by the Part Studio)
uv run onshape_var_convert <partstudio-url> --from config --to variablestudio --vs-name Variables
uv run onshape_var_convert <partstudio-url> --from partstudio --to variablestudio --target-url <variablestudio-url>

# Variable Studio -> Part Studio variables / configuration inputs (target Part Studio required)
uv run onshape_var_convert <variablestudio-url> --from variablestudio --to partstudio --target-url <partstudio-url>
```

`--dry-run` previews; `--names a,b` selects a subset (default: all).

## Behaviour and limits

- Only LENGTH / ANGLE / NUMBER variables. Others (string, boolean, enum, list, untypable formulas) are skipped and
  reported.
- Configuration defaults must be plain `<number> <unit>` literals; formulas are skipped when converting to config.
  Config min/max are generated (`min(0, v)` .. `10x|v|`).
- A name already present in the destination aborts the run before anything changes.
- Part Studio variables are appended at the end of the feature list.
- Deleting a configuration input may affect features that reference it.

## Development

`uv run pytest`. Endpoint shapes come from the public Onshape API (`/variables`, `/partstudios/.../features`
`assignVariable`, `/elements/.../configuration`); tests use mocked HTTP, so try `--dry-run` and a scratch document first
against a real account.

## Live tests

`tests/live/` runs the converter against the Onshape document "test" and resets its six baseline variables
(`tests/og_vars.py`) before and after every test. Skipped unless the key is set:

```
$env:ONSHAPE_TEST_API_KEY = "access:secret"
uv run pytest -m live
```
