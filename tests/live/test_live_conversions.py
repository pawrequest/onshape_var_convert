import pytest

from onshape_var_convert.backends import ConfigBackend, PartStudioBackend, VariableStudioBackend
from onshape_var_convert.cli import build_parser, run
from onshape_var_convert.convert import ConversionError
from onshape_var_convert.urlparse import parse_url

from . import helpers
from .helpers import KIND_VARS, baseline

pytestmark = pytest.mark.live

KINDS = ["partstudio", "variablestudio", "config"]
DIRECTIONS = [(s, d) for s in KINDS for d in KINDS if s != d]


def snap(doc):
    return helpers._approx(doc.snapshot())


def convert(doc, src, dst, *extra):
    if src == "variablestudio":
        argv = [doc.vs_url, "--target-url", doc.ps_url]
    elif dst == "variablestudio":
        argv = [doc.ps_url, "--target-url", doc.vs_url]
    else:
        argv = [doc.ps_url]
    args = build_parser().parse_args(["convert", *argv, "--from", src, "--to", dst, *extra])
    return run(args, doc.client)


def test_baseline_reads_through_app_backends(doc):
    loc = parse_url(doc.ps_url)
    vs_loc = parse_url(doc.vs_url)
    backends = {
        "partstudio": PartStudioBackend(doc.client, loc, loc.eid),
        "variablestudio": VariableStudioBackend(doc.client, vs_loc, vs_loc.eid),
        "config": ConfigBackend(doc.client, loc, loc.eid),
    }
    expected = baseline()
    for kind, backend in backends.items():
        found, skipped = backend.read()
        assert not skipped, (kind, skipped)
        values = {v.name: helpers.literal_to_mm(v.expression) for v in found}
        assert {n: round(x, 6) for n, x in values.items()} == expected[kind]


@pytest.mark.parametrize(("src", "dst"), DIRECTIONS)
def test_move_all(doc, src, dst):
    before = snap(doc)
    assert convert(doc, src, dst) == 0
    after = snap(doc)
    expected = {k: dict(v) for k, v in before.items()}
    expected[dst] = {**before[dst], **before[src]}
    expected[src] = {}
    assert after == expected


@pytest.mark.parametrize(("src", "dst"), DIRECTIONS)
def test_move_subset(doc, src, dst):
    moved = sorted(KIND_VARS[src])[0]
    before = snap(doc)
    assert convert(doc, src, dst, "--names", moved) == 0
    after = snap(doc)
    assert after[src] == {n: v for n, v in before[src].items() if n != moved}
    assert after[dst] == {**before[dst], moved: before[src][moved]}


@pytest.mark.parametrize(("src", "dst"), DIRECTIONS)
def test_dry_run_changes_nothing(doc, src, dst):
    before = snap(doc)
    assert convert(doc, src, dst, "--dry-run") == 0
    assert snap(doc) == before


@pytest.mark.parametrize(("src", "dst"), DIRECTIONS)
def test_name_collision_aborts(doc, src, dst):
    name = sorted(KIND_VARS[src])[0]
    {"partstudio": doc.add_ps, "variablestudio": doc.add_vs}.get(
        dst, lambda n, e: doc.add_cfg(n, float(e.split()[0]))
    )(name, "7 mm")
    before = snap(doc)
    with pytest.raises(ConversionError):
        convert(doc, src, dst)
    assert snap(doc) == before


def test_round_trip(doc):
    assert convert(doc, "partstudio", "config") == 0
    assert convert(doc, "config", "variablestudio") == 0
    assert convert(doc, "variablestudio", "partstudio") == 0
    after = snap(doc)
    everything = {n: float(v) for n, v in helpers.OG_VARS.items()}
    assert after == {"partstudio": everything, "variablestudio": {}, "config": {}}


def test_formula_is_skipped_when_converting_to_config(doc, capsys):
    doc.add_vs("f", "1 mm + 2 mm")
    assert convert(doc, "variablestudio", "config") == 0
    after = snap(doc)
    assert set(after["config"]) == {"cfg1", "cfg2", "vs1", "vs2"}
    assert set(after["variablestudio"]) == {"f"}
    assert "skipped f" in capsys.readouterr().out


def test_missing_name_errors(doc):
    before = snap(doc)
    with pytest.raises(ConversionError):
        convert(doc, "partstudio", "config", "--names", "nope")
    assert snap(doc) == before
