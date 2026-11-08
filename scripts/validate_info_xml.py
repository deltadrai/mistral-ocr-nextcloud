#!/usr/bin/env python3
"""Validate ``appinfo/info.xml`` the way the Nextcloud App Store does.

The store does not validate ``info.xml`` as-is. It first runs
``pre-info.xslt``, which reorders the elements and drops everything the store
does not understand (for example the ``<routes>`` block that AppAPI needs and
the store ignores), and only then validates the result against ``info.xsd``.

This script reproduces that pipeline locally so a broken manifest fails in CI
instead of at release time. It additionally checks the invariants that the
schema cannot express:

* ``<image-tag>`` must equal ``<version>`` (the store refuses floating tags).
* every ``<external-app><routes><route>`` must be complete enough for AppAPI
  (``url``, ``verb`` and an ``access_level`` of PUBLIC/USER/ADMIN).

The schema files in ``scripts/schema/`` are vendored from
https://github.com/nextcloud/appstore (``nextcloudappstore/api/v1/release/``)
and can be refreshed with ``make update-schema``.

Usage:
    python scripts/validate_info_xml.py [--info-xml PATH] [--schema-dir PATH]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from lxml import etree
except ImportError:  # pragma: no cover - dependency is in requirements-dev.txt
    sys.exit("lxml is required: pip install -r requirements-dev.txt")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INFO_XML = REPO_ROOT / "appinfo" / "info.xml"
DEFAULT_SCHEMA_DIR = REPO_ROOT / "scripts" / "schema"

ACCESS_LEVELS = {"PUBLIC", "USER", "ADMIN"}


def _parse(path: Path) -> etree._ElementTree:
    parser = etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False)
    return etree.parse(str(path), parser)


def validate_schema(info_xml: Path, schema_dir: Path) -> list[str]:
    """Run the store's pre-xslt + xsd pipeline. Returns a list of error strings."""
    errors: list[str] = []
    pre_xslt = etree.XSLT(_parse(schema_dir / "pre-info.xslt"))
    schema = etree.XMLSchema(_parse(schema_dir / "info.xsd"))

    doc = _parse(info_xml)
    transformed = pre_xslt(doc)
    if not schema.validate(transformed):
        for entry in schema.error_log:
            errors.append(f"info.xml:{entry.line}: {entry.message}")
    return errors


def validate_appapi_routes(root: etree._Element) -> list[str]:
    """Check the AppAPI-only parts the store's schema strips away."""
    errors: list[str] = []
    for index, route in enumerate(root.findall("external-app/routes/route")):
        url = (route.findtext("url") or "").strip()
        verb = (route.findtext("verb") or "").strip()
        access = (route.findtext("access_level") or "").strip()
        if not url:
            errors.append(f"route #{index}: <url> is required")
        if not verb:
            errors.append(f"route #{index}: <verb> is required")
        if access not in ACCESS_LEVELS:
            errors.append(f"route #{index}: <access_level> must be one of {sorted(ACCESS_LEVELS)}, got {access!r}")
        if url and not url.startswith("^"):
            errors.append(f"route #{index}: <url> should be an anchored regex (start with '^'), got {url!r}")
    return errors


def validate_versions(root: etree._Element) -> list[str]:
    version = (root.findtext("version") or "").strip()
    image_tag = (root.findtext("external-app/docker-install/image-tag") or "").strip()
    if not version:
        return ["<version> is missing"]
    if image_tag != version:
        return [f"<image-tag> ({image_tag!r}) must equal <version> ({version!r}); the app store refuses floating tags"]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--info-xml", type=Path, default=DEFAULT_INFO_XML)
    parser.add_argument("--schema-dir", type=Path, default=DEFAULT_SCHEMA_DIR)
    args = parser.parse_args(argv)

    root = _parse(args.info_xml).getroot()
    errors = validate_schema(args.info_xml, args.schema_dir)
    errors += validate_appapi_routes(root)
    errors += validate_versions(root)

    if errors:
        print(f"{args.info_xml} is NOT release-ready:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(f"{args.info_xml}: OK (app-store schema + AppAPI routes + pinned image tag)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
