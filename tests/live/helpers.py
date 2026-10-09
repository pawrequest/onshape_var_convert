"""Independent oracle for the live tests: raw REST calls, no use of onshape_var_convert.backends."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from onshape_var_convert.client import OnshapeClient
from onshape_var_convert.model import parse_literal
from tests.og_vars import OG_VARS

DID = '9323f6caa9681a8ed00b5323'
WID = 'b3c14a29fe0d314db7853c55'
PS_EID = 'a1e7991f82cd458a94622288'
STUDIO_NAME = 'test'
APP_CREATED_STUDIO = 'Variables'  # default --vs-name; removed if a failed run left it behind

TO_MM = {
    'millimeter': 1.0,
    'centimeter': 10.0,
    'meter': 1000.0,
    'inch': 25.4,
    'foot': 304.8,
    '': 1.0,
}
PS_VARS = {'ps1', 'ps2'}
VS_VARS = {'vs1', 'vs2'}
CFG_VARS = {'cfg1', 'cfg2'}
KIND_VARS = {'partstudio': PS_VARS, 'variablestudio': VS_VARS, 'config': CFG_VARS}


def baseline() -> dict[str, dict[str, float]]:
    return {kind: {n: float(OG_VARS[n]) for n in names} for kind, names in KIND_VARS.items()}


def client_from_env() -> OnshapeClient:
    key = __import__('os').environ['ONSHAPE_TEST_API_KEY']
    access, _, secret = key.partition(':')
    return OnshapeClient(access, secret)


def literal_to_mm(expression: str) -> float | str:
    parsed = parse_literal(expression)
    if parsed is None:
        return expression
    value, unit = parsed
    return value * TO_MM[unit]


@dataclass
class Doc:
    client: OnshapeClient
    vs_eid: str

    @property
    def ps_url(self) -> str:
        return f'https://cad.onshape.com/documents/{DID}/w/{WID}/e/{PS_EID}'

    @property
    def vs_url(self) -> str:
        return f'https://cad.onshape.com/documents/{DID}/w/{WID}/e/{self.vs_eid}'

    # ---- raw paths
    @property
    def _features(self) -> str:
        return f'/partstudios/d/{DID}/w/{WID}/e/{PS_EID}/features'

    @property
    def _vs_vars(self) -> str:
        return f'/variables/d/{DID}/w/{WID}/e/{self.vs_eid}/variables'

    @property
    def _config(self) -> str:
        return f'/elements/d/{DID}/w/{WID}/e/{PS_EID}/configuration'

    # ---- reads
    def _ps_features(self) -> list[dict]:
        feats = self.client.get(self._features).get('features', [])
        return [f for f in feats if f.get('featureType') == 'assignVariable']

    @staticmethod
    def _p(feature: dict, pid: str) -> dict:
        return next((p for p in feature['parameters'] if p['parameterId'] == pid), {})

    def snapshot(self) -> dict[str, dict]:
        ps = {}
        for f in self._ps_features():
            vtype = self._p(f, 'variableType').get('value')
            key = {'LENGTH': 'lengthValue', 'ANGLE': 'angleValue', 'NUMBER': 'numberValue'}.get(
                vtype, 'value'
            )
            expr = (self._p(f, key) or self._p(f, 'value')).get('expression', '')
            ps[self._p(f, 'name')['value']] = literal_to_mm(expr)
        vs = {
            v['name']: literal_to_mm(v['expression'])
            for group in self.client.get(self._vs_vars)
            for v in group.get('variables', [])
        }
        cfg = {}
        for p in self.client.get(self._config).get('configurationParameters', []):
            if p.get('btType', '').startswith('BTMConfigurationParameterQuantity'):
                rng = p['rangeAndDefault']
                cfg[p['parameterId']] = rng['defaultValue'] * TO_MM[rng.get('units', '')]
        return {'partstudio': ps, 'variablestudio': vs, 'config': cfg}

    # ---- direct writes (used by reset and by tests setting up scenarios)
    def set_vs_rows(self, rows: list[dict]) -> None:
        self.client.post(self._vs_vars, rows)

    def add_vs(self, name: str, expression: str) -> None:
        rows = [v for g in self.client.get(self._vs_vars) for v in g.get('variables', [])]
        rows.append({'name': name, 'type': 'LENGTH', 'expression': expression})
        self.set_vs_rows(rows)

    def add_ps(self, name: str, expression: str) -> None:
        def enum(pid, enum_name, value):
            return {
                'btType': 'BTMParameterEnum-145',
                'enumName': enum_name,
                'value': value,
                'parameterId': pid,
            }

        def qty(pid):
            return {
                'btType': 'BTMParameterQuantity-147',
                'expression': expression,
                'parameterId': pid,
            }

        feature = {
            'btType': 'BTMFeature-134',
            'featureType': 'assignVariable',
            'name': name,
            'suppressed': False,
            'parameters': [
                enum('mode', 'VariableMode', 'ASSIGNED'),
                enum('variableType', 'VariableType', 'LENGTH'),
                enum('measurementMode', 'VariableMeasurementMode', 'DISTANCE'),
                {'btType': 'BTMParameterString-149', 'value': name, 'parameterId': 'name'},
                qty('lengthValue'),
                qty('value'),
            ],
        }
        self.client.post(self._features, {'feature': feature})

    def add_cfg(self, name: str, value_mm: float) -> None:
        definition = self.client.get(self._config)
        definition['configurationParameters'].append(_cfg_param(name, value_mm))
        self.client.post(self._config, definition)

    # ---- reset
    def reset(self) -> None:
        for f in self._ps_features():
            self.client.delete(f'{self._features}/featureid/{f["featureId"]}')
        for name in sorted(PS_VARS):
            self.add_ps(name, f'{OG_VARS[name]} mm')

        self.set_vs_rows(
            [
                {'name': n, 'type': 'LENGTH', 'expression': f'{OG_VARS[n]} mm'}
                for n in sorted(VS_VARS)
            ]
        )

        definition = self.client.get(self._config)
        kept = [
            p
            for p in definition.get('configurationParameters', [])
            if not p.get('btType', '').startswith('BTMConfigurationParameterQuantity')
        ]
        self.client.post(
            self._config,
            {
                'btType': 'BTConfigurationUpdateCall-2933',
                'configurationParameters': kept
                + [_cfg_param(n, OG_VARS[n]) for n in sorted(CFG_VARS)],
            },
        )

        self._ensure_reference()
        self._drop_stray_studios()
        actual = self.snapshot()
        if _approx(actual) != _approx(baseline()):
            pytest.exit(f'Test document could not be reset to baseline: {actual}', returncode=3)

    def _ensure_reference(self) -> None:
        path = f'/variables/d/{DID}/w/{WID}/e/{PS_EID}/variablestudioreferences'
        refs = self.client.get(path).get('references', [])
        if not any(r.get('referenceElementId') == self.vs_eid for r in refs):
            refs.append({'referenceElementId': self.vs_eid, 'entireVariableStudio': True})
            self.client.post(path, {'references': refs})

    def _drop_stray_studios(self) -> None:
        for e in self.client.get(f'/documents/d/{DID}/w/{WID}/elements'):
            if e.get('elementType') == 'VARIABLESTUDIO' and e.get('name') == APP_CREATED_STUDIO:
                self.client.delete(f'/elements/d/{DID}/w/{WID}/e/{e["id"]}')


def _cfg_param(name: str, value_mm: float) -> dict:
    return {
        'btType': 'BTMConfigurationParameterQuantity-1826',
        'parameterId': name,
        'parameterName': name,
        'quantityType': 'LENGTH',
        'rangeAndDefault': {
            'btType': 'BTQuantityRange-181',
            'quantityType': 'LENGTH',
            'units': 'millimeter',
            'defaultValue': float(value_mm),
            'minValue': 0.0,
            'maxValue': 10000.0,
        },
    }


def _approx(snap: dict) -> dict:
    return {
        k: {n: (round(v, 6) if isinstance(v, float) else v) for n, v in d.items()}
        for k, d in snap.items()
    }


def find_studio_eid(client: OnshapeClient) -> str:
    for e in client.get(f'/documents/d/{DID}/w/{WID}/elements'):
        if e.get('elementType') == 'VARIABLESTUDIO' and e.get('name') == STUDIO_NAME:
            return e['id']
    raise RuntimeError(f'No Variable Studio named {STUDIO_NAME!r} in the test document')
