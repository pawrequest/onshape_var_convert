import httpx
import pytest

from onshape_var_convert.backends import ConfigBackend, PartStudioBackend, VariableStudioBackend
from onshape_var_convert.client import OnshapeClient
from onshape_var_convert.convert import ConversionError, convert
from onshape_var_convert.model import Kind, Skipped, Variable, format_literal, infer_type, parse_literal
from onshape_var_convert.urlparse import parse_url

D, W, E, E2 = "a" * 24, "b" * 24, "c" * 24, "d" * 24
URL = f"https://cad.onshape.com/documents/{D}/w/{W}/e/{E}"


class Fake:
    def __init__(self, kind, variables=(), skipped=(), reject=()):
        self.kind = kind
        self.vars = list(variables)
        self.skipped = list(skipped)
        self.reject = set(reject)

    def read(self):
        return list(self.vars), list(self.skipped)

    def validate(self, v):
        return "nope" if v.name in self.reject else None

    def add(self, variables):
        self.vars += variables

    def remove(self, names):
        self.vars = [v for v in self.vars if v.name not in names]


def v(name, expr="10 mm", t="LENGTH"):
    return Variable(name, expr, t)


def make_client(handler):
    return OnshapeClient("k", "s", transport=httpx.MockTransport(handler))


def test_parse_url():
    loc = parse_url(URL)
    assert (loc.did, loc.wvm, loc.wvmid, loc.eid) == (D, "w", W, E)
    with pytest.raises(ValueError):
        parse_url("https://example.com")
    with pytest.raises(ValueError):
        parse_url(f"https://cad.onshape.com/documents/{D}/v/{W}/e/{E}").require_workspace()


def test_literals():
    assert parse_literal("10 mm") == (10.0, "millimeter")
    assert parse_literal("#a + 1 mm") is None
    assert infer_type("45 deg") == "ANGLE"
    assert infer_type("3") == "NUMBER"
    assert format_literal(2.5, "inch") == "2.5 in"
    assert format_literal(3, "") == "3"


def test_convert_moves_and_skips():
    src = Fake(Kind.PARTSTUDIO, [v("a"), v("b"), v("c")], [Skipped("s", "x")])
    dst = Fake(Kind.CONFIG, reject={"c"})
    report = convert(src, dst)
    assert [x.name for x in dst.vars] == ["a", "b"]
    assert [x.name for x in src.vars] == ["c"]
    assert {s.name for s in report.skipped} == {"s", "c"}


def test_convert_subset_dry_run_and_errors():
    src = Fake(Kind.PARTSTUDIO, [v("a"), v("b")])
    dst = Fake(Kind.CONFIG)
    convert(src, dst, {"a"}, dry_run=True)
    assert not dst.vars and len(src.vars) == 2
    with pytest.raises(ConversionError):
        convert(src, dst, {"zzz"})
    convert(src, dst, {"a"})
    assert [x.name for x in src.vars] == ["b"]


def test_convert_collision_aborts_untouched():
    src = Fake(Kind.PARTSTUDIO, [v("a")])
    dst = Fake(Kind.CONFIG, [v("a")])
    with pytest.raises(ConversionError):
        convert(src, dst)
    assert len(src.vars) == 1


def test_unverified_write_keeps_source():
    class Lossy(Fake):
        def add(self, variables):
            pass

    src = Fake(Kind.PARTSTUDIO, [v("a")])
    with pytest.raises(ConversionError):
        convert(src, Lossy(Kind.CONFIG))
    assert len(src.vars) == 1


def test_variable_studio_read_and_replace_all_write():
    posted = {}

    def handler(request):
        if request.method == "GET":
            return httpx.Response(
                200,
                json=[{"variables": [
                    {"name": "x", "expression": "5 mm", "type": "LENGTH"},
                    {"name": "y", "expression": "#x * 2", "type": "ANY"},
                ]}],
            )
        posted["body"] = request.read().decode()
        posted["url"] = str(request.url)
        return httpx.Response(200, json={})

    be = VariableStudioBackend(make_client(handler), parse_url(URL), E)
    found, skipped = be.read()
    assert [x.name for x in found] == ["x"] and skipped[0].name == "y"
    be.remove(["x"])
    assert f"/variables/d/{D}/w/{W}/e/{E}/variables" in posted["url"]
    assert '"x"' not in posted["body"] and '"y"' in posted["body"]


def test_variable_studio_creates_and_links():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        path = request.url.path
        if path.endswith("/elements"):
            return httpx.Response(200, json=[])
        if path.endswith("/variablestudio"):
            return httpx.Response(200, json={"id": E2})
        if path.endswith("/variablestudioreferences") and request.method == "GET":
            return httpx.Response(200, json={"references": []})
        if path.endswith("/variables") and request.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={})

    be = VariableStudioBackend(make_client(handler), parse_url(URL), None, link_to=E)
    be.add([v("a")])
    assert any(p.endswith("/variablestudio") for p in calls)
    assert any(p.endswith(f"/e/{E}/variablestudioreferences") for p in calls)


def test_part_studio_read_and_delete():
    deleted = []

    def handler(request):
        if request.method == "DELETE":
            deleted.append(request.url.path)
            return httpx.Response(200, json={})
        feats = [{
            "featureId": "F1", "featureType": "assignVariable",
            "parameters": [
                {"parameterId": "name", "value": "w"},
                {"parameterId": "variableType", "value": "LENGTH"},
                {"parameterId": "lengthValue", "expression": "12 mm"},
            ],
        }, {"featureId": "F2", "featureType": "extrude", "parameters": []}]
        return httpx.Response(200, json={"features": feats})

    be = PartStudioBackend(make_client(handler), parse_url(URL), E)
    assert be.read()[0] == [Variable("w", "12 mm", "LENGTH")]
    be.remove(["w"])
    assert deleted[0].endswith("/features/featureid/F1")


def test_part_studio_feature_shape():
    body = PartStudioBackend._feature(v("w", "2 in"))["feature"]
    ids = {p["parameterId"]: p for p in body["parameters"]}
    assert body["featureType"] == "assignVariable"
    assert ids["name"]["value"] == "w" and ids["lengthValue"]["expression"] == "2 in"


def test_config_read_and_write_preserves_other_inputs():
    import json

    posted = {}
    definition = {"configurationParameters": [
        {"btType": "BTMConfigurationParameterBoolean-2550", "parameterId": "flag"},
        {"btType": "BTMConfigurationParameterQuantity-1826", "parameterId": "len", "quantityType": "LENGTH",
         "rangeAndDefault": {"units": "millimeter", "defaultValue": 7}},
    ]}

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json=definition)
        posted.clear()
        posted.update(json.loads(request.read()))
        return httpx.Response(200, json={})

    be = ConfigBackend(make_client(handler), parse_url(URL), E)
    found, skipped = be.read()
    assert found == [Variable("len", "7 mm", "LENGTH")] and skipped[0].name == "flag"
    assert be.validate(v("q", "#a + 1")) is not None
    be.add([v("n", "3 in")])
    assert [p["parameterId"] for p in posted["configurationParameters"]] == ["flag", "len", "n"]
    assert posted["configurationParameters"][2]["rangeAndDefault"]["units"] == "inch"
    be.remove(["len"])
    assert [p["parameterId"] for p in posted["configurationParameters"]] == ["flag"]
