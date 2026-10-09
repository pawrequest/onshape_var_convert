"""Move variables between two backends: write, verify, then delete the source."""

from __future__ import annotations

from dataclasses import dataclass, field

from .backends import Backend
from .model import Skipped, Variable


class ConversionError(RuntimeError):
    pass


@dataclass
class Report:
    moved: list[Variable] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)
    dry_run: bool = False


def convert(
    source: Backend, dest: Backend, names: set[str] | None = None, dry_run: bool = False
) -> Report:
    variables, skipped = source.read()
    report = Report(skipped=list(skipped), dry_run=dry_run)

    if names is not None:
        missing = names - {v.name for v in variables}
        if missing:
            raise ConversionError(
                f'Not found in source (or unsupported): {", ".join(sorted(missing))}'
            )
        variables = [v for v in variables if v.name in names]
        report.skipped = [s for s in report.skipped if s.name in names]

    movable = []
    for v in variables:
        reason = dest.validate(v)
        if reason:
            report.skipped.append(Skipped(v.name, reason))
        else:
            movable.append(v)

    existing = {v.name for v in dest.read()[0]}
    clashes = sorted(existing & {v.name for v in movable})
    if clashes:
        raise ConversionError(
            f'Destination already has: {", ".join(clashes)}. Nothing was changed.'
        )

    report.moved = movable
    if dry_run or not movable:
        return report

    dest.add(movable)
    now_there = {v.name for v in dest.read()[0]}
    absent = sorted({v.name for v in movable} - now_there)
    if absent:
        raise ConversionError(
            f'Destination write could not be verified for: {", ".join(absent)}. Source left untouched.'
        )
    source.remove([v.name for v in movable])
    return report
