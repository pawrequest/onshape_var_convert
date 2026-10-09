"""Command line interface."""

from __future__ import annotations

import argparse
import sys

from .backends import Backend, ConfigBackend, PartStudioBackend, VariableStudioBackend
from .client import OnshapeClient, OnshapeError, load_dotenv
from .convert import ConversionError, convert
from .model import Kind
from .urlparse import Location, parse_url

KINDS = [k.value for k in Kind]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scratch", description="Move Onshape variables between kinds.")
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("convert", help="Move variables from one kind to another (source is deleted).")
    c.add_argument("url", help="Source element URL (Part Studio, or Variable Studio for --from variablestudio).")
    c.add_argument("--from", dest="src", choices=KINDS, required=True)
    c.add_argument("--to", dest="dst", choices=KINDS, required=True)
    c.add_argument("--names", help="Comma separated variable names (default: all).")
    c.add_argument("--all", action="store_true", help="Convert every variable (the default).")
    c.add_argument(
        "--target-url",
        help="Destination element URL: the Part Studio when converting from a Variable Studio, "
        "or an existing Variable Studio when converting to one.",
    )
    c.add_argument("--vs-name", default="Variables", help="Variable Studio to find/create when converting to one.")
    c.add_argument("--dry-run", action="store_true", help="Show what would move without changing anything.")
    return parser


def _backend(client: OnshapeClient, kind: str, loc: Location, *, vs_eid=None, vs_name="Variables", link_to=None) -> Backend:
    if kind == Kind.PARTSTUDIO:
        return PartStudioBackend(client, loc, loc.require_element())
    if kind == Kind.CONFIG:
        return ConfigBackend(client, loc, loc.require_element())
    return VariableStudioBackend(client, loc, vs_eid, studio_name=vs_name, link_to=link_to)


def build_backends(client: OnshapeClient, args: argparse.Namespace) -> tuple[Backend, Backend]:
    if args.src == args.dst:
        raise ValueError("--from and --to must differ.")
    loc = parse_url(args.url)
    target = parse_url(args.target_url) if args.target_url else None

    if args.src == Kind.VARIABLESTUDIO:
        if target is None:
            raise ValueError("--target-url (the Part Studio to receive the variables) is required.")
        source = VariableStudioBackend(client, loc, loc.require_element())
        return source, _backend(client, args.dst, target)

    source = _backend(client, args.src, loc)
    if args.dst == Kind.VARIABLESTUDIO:
        studio_loc = target or loc
        studio_eid = target.require_element() if target else None
        dest = VariableStudioBackend(
            client, studio_loc, studio_eid, studio_name=args.vs_name, link_to=loc.require_element()
        )
        return source, dest
    return source, _backend(client, args.dst, loc)


def run(args: argparse.Namespace, client: OnshapeClient | None = None) -> int:
    client = client or OnshapeClient()
    source, dest = build_backends(client, args)
    names = {n.strip() for n in args.names.split(",") if n.strip()} if args.names and not args.all else None
    report = convert(source, dest, names, args.dry_run)

    verb = "Would move" if report.dry_run else "Moved"
    print(f"{verb} {len(report.moved)} variable(s) from {args.src} to {args.dst}:")
    for v in report.moved:
        print(f"  {v.name} = {v.expression} [{v.vtype}]")
    for s in report.skipped:
        print(f"  skipped {s.name}: {s.reason}")
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except (ValueError, ConversionError, OnshapeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
