"""Backends reading/writing each variable kind through the Onshape REST API."""

from __future__ import annotations

from typing import Protocol

from .client import OnshapeClient
from .model import (
    QUANTITY_TYPES,
    Kind,
    Skipped,
    Variable,
    format_literal,
    infer_type,
    parse_literal,
)
from .urlparse import Location


class Backend(Protocol):
    kind: Kind

    def read(self) -> tuple[list[Variable], list[Skipped]]: ...

    def validate(self, variable: Variable) -> str | None:
        """Return a reason this variable cannot be stored here, else None."""

    def add(self, variables: list[Variable]) -> None: ...

    def remove(self, names: list[str]) -> None: ...


# --------------------------------------------------------------------------- Variable Studio


class VariableStudioBackend:
    kind = Kind.VARIABLESTUDIO

    def __init__(
        self,
        client: OnshapeClient,
        loc: Location,
        eid: str | None,
        *,
        studio_name: str = "Variables",
        link_to: str | None = None,
    ) -> None:
        self.client, self.loc, self.eid = client, loc, eid
        self.studio_name, self.link_to = studio_name, link_to

    def _vars_path(self, eid: str) -> str:
        return f"/variables/d/{self.loc.did}/{self.loc.wvm}/{self.loc.wvmid}/e/{eid}/variables"

    def _raw(self) -> list[dict]:
        if not self.eid:
            return []
        groups = self.client.get(self._vars_path(self.eid))
        return [v for group in groups for v in group.get("variables", [])]

    def read(self) -> tuple[list[Variable], list[Skipped]]:
        found, skipped = [], []
        for raw in self._raw():
            name, expr = raw["name"], raw.get("expression", "")
            vtype = raw.get("type")
            if vtype not in QUANTITY_TYPES:
                vtype = infer_type(expr)
            if vtype is None:
                skipped.append(Skipped(name, f"unsupported variable type {raw.get('type')!r}"))
                continue
            found.append(Variable(name, expr, vtype, raw.get("description") or ""))
        return found, skipped

    def validate(self, variable: Variable) -> str | None:
        return None

    def _ensure_studio(self) -> str:
        if self.eid:
            return self.eid
        self.loc.require_workspace()
        elements = self.client.get(f"/documents/d/{self.loc.did}/w/{self.loc.wvmid}/elements")
        for element in elements:
            if element.get("elementType") == "VARIABLESTUDIO" and element.get("name") == self.studio_name:
                self.eid = element["id"]
                return self.eid
        created = self.client.post(
            f"/variables/d/{self.loc.did}/w/{self.loc.wvmid}/variablestudio", {"name": self.studio_name}
        )
        self.eid = created["id"]
        return self.eid

    def _write(self, eid: str, rows: list[dict]) -> None:
        self.loc.require_workspace()
        self.client.post(f"/variables/d/{self.loc.did}/w/{self.loc.wvmid}/e/{eid}/variables", rows)

    def add(self, variables: list[Variable]) -> None:
        eid = self._ensure_studio()
        rows = self._raw()
        for v in variables:
            row = {"name": v.name, "type": v.vtype, "expression": v.expression}
            if v.description:
                row["description"] = v.description
            rows.append(row)
        self._write(eid, rows)
        if self.link_to:
            self._link(eid, self.link_to)

    def remove(self, names: list[str]) -> None:
        if self.eid:
            self._write(self.eid, [r for r in self._raw() if r["name"] not in names])

    def _link(self, studio_eid: str, part_studio_eid: str) -> None:
        path = f"/variables/d/{self.loc.did}/w/{self.loc.wvmid}/e/{part_studio_eid}/variablestudioreferences"
        refs = self.client.get(path).get("references", [])
        if any(r.get("referenceElementId") == studio_eid for r in refs):
            return
        refs.append({"referenceElementId": studio_eid, "entireVariableStudio": True})
        self.client.post(path, {"references": refs})


# --------------------------------------------------------------------------- Part Studio

_VALUE_KEYS = {"LENGTH": "lengthValue", "ANGLE": "angleValue", "NUMBER": "numberValue"}
_ASSIGN = "assignVariable"


def _param(feature: dict, parameter_id: str) -> dict | None:
    return next((p for p in feature.get("parameters", []) if p.get("parameterId") == parameter_id), None)


class PartStudioBackend:
    kind = Kind.PARTSTUDIO

    def __init__(self, client: OnshapeClient, loc: Location, eid: str) -> None:
        self.client, self.loc, self.eid = client, loc, eid
        self._ids: dict[str, str] = {}

    def _features_path(self) -> str:
        return f"/partstudios/d/{self.loc.did}/{self.loc.wvm}/{self.loc.wvmid}/e/{self.eid}/features"

    def read(self) -> tuple[list[Variable], list[Skipped]]:
        features = self.client.get(self._features_path()).get("features", [])
        found, skipped, self._ids = [], [], {}
        for feature in features:
            if feature.get("featureType") != _ASSIGN:
                continue
            name_param = _param(feature, "name")
            name = (name_param or {}).get("value") or feature.get("name", "?")
            vtype = (_param(feature, "variableType") or {}).get("value", "")
            if vtype not in QUANTITY_TYPES:
                skipped.append(Skipped(name, f"unsupported variable type {vtype!r}"))
                continue
            value = _param(feature, _VALUE_KEYS[vtype]) or _param(feature, "value") or {}
            found.append(Variable(name, value.get("expression", ""), vtype))
            self._ids[name] = feature["featureId"]
        return found, skipped

    def validate(self, variable: Variable) -> str | None:
        return None

    @staticmethod
    def _feature(v: Variable) -> dict:
        def enum(pid: str, enum_name: str, value: str) -> dict:
            return {"btType": "BTMParameterEnum-145", "enumName": enum_name, "value": value, "parameterId": pid}

        def quantity(pid: str) -> dict:
            return {"btType": "BTMParameterQuantity-147", "expression": v.expression, "parameterId": pid}

        parameters = [
            enum("mode", "VariableMode", "ASSIGNED"),
            enum("variableType", "VariableType", v.vtype),
            {"btType": "BTMParameterString-149", "value": v.name, "parameterId": "name"},
            quantity(_VALUE_KEYS[v.vtype]),
            quantity("value"),
        ]
        if v.vtype == "LENGTH":
            parameters.insert(2, enum("measurementMode", "VariableMeasurementMode", "DISTANCE"))
        return {
            "feature": {
                "btType": "BTMFeature-134",
                "featureType": _ASSIGN,
                "name": v.name,
                "suppressed": False,
                "parameters": parameters,
            }
        }

    def add(self, variables: list[Variable]) -> None:
        self.loc.require_workspace()
        for v in variables:
            self.client.post(self._features_path(), self._feature(v))

    def remove(self, names: list[str]) -> None:
        self.loc.require_workspace()
        if not self._ids:
            self.read()
        for name in names:
            self.client.delete(f"{self._features_path()}/featureid/{self._ids[name]}")


# --------------------------------------------------------------------------- Configuration

_CONFIG_QUANTITY = "BTMConfigurationParameterQuantity-1826"


class ConfigBackend:
    kind = Kind.CONFIG

    def __init__(self, client: OnshapeClient, loc: Location, eid: str) -> None:
        self.client, self.loc, self.eid = client, loc, eid

    def _path(self, wvm: str | None = None, wvmid: str | None = None) -> str:
        return (
            f"/elements/d/{self.loc.did}/{wvm or self.loc.wvm}/{wvmid or self.loc.wvmid}"
            f"/e/{self.eid}/configuration"
        )

    def read(self) -> tuple[list[Variable], list[Skipped]]:
        found, skipped = [], []
        for param in self.client.get(self._path()).get("configurationParameters", []):
            name = param.get("parameterId") or param.get("parameterName", "?")
            if not param.get("btType", "").startswith("BTMConfigurationParameterQuantity"):
                skipped.append(Skipped(name, f"unsupported configuration input {param.get('btType')!r}"))
                continue
            rng = param.get("rangeAndDefault", {})
            vtype = param.get("quantityType") or rng.get("quantityType") or "NUMBER"
            if vtype not in QUANTITY_TYPES:
                skipped.append(Skipped(name, f"unsupported quantity type {vtype!r}"))
                continue
            expr = format_literal(rng.get("defaultValue", 0), rng.get("units", ""))
            found.append(Variable(name, expr, vtype))
        return found, skipped

    def validate(self, variable: Variable) -> str | None:
        if parse_literal(variable.expression) is None:
            return "expression is not a plain `<number> <unit>` literal, so it cannot be a configuration default"
        return None

    @staticmethod
    def _param(v: Variable) -> dict:
        value, unit = parse_literal(v.expression)  # validated beforehand
        rng = {
            "btType": "BTQuantityRange-181",
            "quantityType": v.vtype,
            "units": unit,
            "defaultValue": value,
            "minValue": min(0.0, value),
            "maxValue": max(abs(value) * 10, 360.0 if v.vtype == "ANGLE" else 1.0),
        }
        return {
            "btType": _CONFIG_QUANTITY,
            "parameterId": v.name,
            "parameterName": v.name,
            "quantityType": v.vtype,
            "rangeAndDefault": rng,
        }

    def _write(self, definition: dict) -> None:
        self.loc.require_workspace()
        # The GET response type (BTConfigurationResponse) is not accepted by POST.
        body = {
            "btType": "BTConfigurationUpdateCall-2933",
            "configurationParameters": definition.get("configurationParameters", []),
        }
        for key in ("serializationVersion", "sourceMicroversion", "libraryVersion"):
            if key in definition:
                body[key] = definition[key]
        self.client.post(self._path("w", self.loc.wvmid), body)

    def add(self, variables: list[Variable]) -> None:
        definition = self.client.get(self._path())
        definition.setdefault("configurationParameters", []).extend(self._param(v) for v in variables)
        self._write(definition)

    def remove(self, names: list[str]) -> None:
        definition = self.client.get(self._path())
        definition["configurationParameters"] = [
            p
            for p in definition.get("configurationParameters", [])
            if (p.get("parameterId") or p.get("parameterName")) not in names
        ]
        self._write(definition)
