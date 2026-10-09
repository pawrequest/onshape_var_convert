"""Kind-neutral variable model and expression/unit helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

QUANTITY_TYPES = ("LENGTH", "ANGLE", "NUMBER")


class Kind(StrEnum):
    PARTSTUDIO = "partstudio"
    VARIABLESTUDIO = "variablestudio"
    CONFIG = "config"


@dataclass(frozen=True)
class Variable:
    name: str
    expression: str
    vtype: str
    description: str = ""


@dataclass(frozen=True)
class Skipped:
    name: str
    reason: str


# Short unit suffix (as used in expressions) -> Onshape unit name (as used in config definitions)
UNIT_NAMES = {
    "mm": "millimeter",
    "cm": "centimeter",
    "m": "meter",
    "in": "inch",
    "ft": "foot",
    "yd": "yard",
    "deg": "degree",
    "rad": "radian",
    "": "",
}
UNIT_SUFFIXES = {v: k for k, v in UNIT_NAMES.items()}
_UNIT_TYPES = {
    "millimeter": "LENGTH",
    "centimeter": "LENGTH",
    "meter": "LENGTH",
    "inch": "LENGTH",
    "foot": "LENGTH",
    "yard": "LENGTH",
    "degree": "ANGLE",
    "radian": "ANGLE",
    "": "NUMBER",
}

_LITERAL = re.compile(r"^\s*(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*([A-Za-z]*)\s*$")


def parse_literal(expression: str) -> tuple[float, str] | None:
    """Return (value, onshape unit name) for a plain `<number> <unit>` expression, else None."""
    match = _LITERAL.match(expression)
    if not match:
        return None
    unit = UNIT_NAMES.get(match.group(2))
    if unit is None:
        return None
    return float(match.group(1)), unit


def infer_type(expression: str) -> str | None:
    """Infer LENGTH/ANGLE/NUMBER from a literal expression; None for formulas/references."""
    parsed = parse_literal(expression)
    return _UNIT_TYPES[parsed[1]] if parsed else None


def format_literal(value: float, unit: str) -> str:
    number = f"{value:.12g}"
    suffix = UNIT_SUFFIXES.get(unit, unit)
    return f"{number} {suffix}".strip()
