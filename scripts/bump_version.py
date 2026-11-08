#!/usr/bin/env python3
"""Set the release version everywhere it is duplicated.

The version lives in four places and they must agree, otherwise the app store
rejects the release (``<image-tag>`` must match ``<version>``) or the container
reports a version that does not match the tag it was published under:

* ``appinfo/info.xml``          -> ``<version>`` and ``<image-tag>``
* ``package.json``              -> ``version``
* ``src/mistral_ocr/__init__.py`` -> ``__version__``
* ``CHANGELOG.md``              -> a ``## [<version>] - <date>`` section

Usage:
    python scripts/bump_version.py 0.2.0 [--date 2025-11-08] [--dry-run]

Afterwards: commit, then ``git tag v0.2.0 && git push --tags``. The release
workflow builds and publishes the matching container image and GitHub release.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-[0-9A-Za-z.-]+)?$")


def _paths(root: Path) -> dict[str, Path]:
    return {
        "info_xml": root / "appinfo" / "info.xml",
        "package_json": root / "package.json",
        "init_py": root / "src" / "mistral_ocr" / "__init__.py",
        "changelog": root / "CHANGELOG.md",
    }


def _sub_once(pattern: str, replacement: str, text: str, path: Path) -> str:
    new_text, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one match for {pattern!r}, found {count}")
    return new_text


def update_info_xml(path: Path, version: str) -> None:
    text = path.read_text(encoding="utf-8")
    text = _sub_once(r"^(\s*)<version>[^<]*</version>$", rf"\g<1><version>{version}</version>", text, path)
    text = _sub_once(r"^(\s*)<image-tag>[^<]*</image-tag>$", rf"\g<1><image-tag>{version}</image-tag>", text, path)
    path.write_text(text, encoding="utf-8")


def update_package_json(path: Path, version: str) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["version"] = version
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def update_init_py(path: Path, version: str) -> None:
    text = path.read_text(encoding="utf-8")
    text = _sub_once(r'^__version__ = "[^"]*"$', f'__version__ = "{version}"', text, path)
    path.write_text(text, encoding="utf-8")


def update_changelog(path: Path, version: str, date: str) -> None:
    text = path.read_text(encoding="utf-8")
    if re.search(rf"^## \[{re.escape(version)}\](?!\()", text, flags=re.MULTILINE):
        print(f"CHANGELOG.md: section for {version} already exists, leaving it untouched")
        return

    heading = f"## [{version}] - {date}"
    section = f"{heading}\n\n### Changed\n\n- Release {version}.\n"
    unreleased = re.search(r"^## \[Unreleased\][^\n]*$", text, flags=re.MULTILINE)
    if unreleased:
        # Insert directly above the newest existing release section, keeping exactly
        # one blank line between sections.
        insert_at = unreleased.end()
        text = f"{text[:insert_at]}\n\n{section}\n{text[insert_at:].lstrip(chr(10))}"
    else:
        text = text.rstrip("\n") + f"\n\n{section}"
    path.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version", help="new version, e.g. 0.2.0")
    parser.add_argument("--date", default=dt.date.today().isoformat(), help="changelog date (default: today)")
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="repository root (default: this checkout)")
    parser.add_argument("--dry-run", action="store_true", help="print what would change, write nothing")
    args = parser.parse_args(argv)

    if not SEMVER.match(args.version):
        return _fail(f"{args.version!r} is not a valid semantic version (expected MAJOR.MINOR.PATCH)")

    paths = _paths(args.root)

    if args.dry_run:
        print(f"would set version {args.version} in:")
        for path in paths.values():
            print(f"  - {path.relative_to(args.root)}")
        return 0

    update_info_xml(paths["info_xml"], args.version)
    update_package_json(paths["package_json"], args.version)
    update_init_py(paths["init_py"], args.version)
    update_changelog(paths["changelog"], args.version, args.date)

    print(f"version set to {args.version}")
    print(f"next: review CHANGELOG.md, commit, then `git tag v{args.version} && git push --tags`")
    return 0


def _fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
