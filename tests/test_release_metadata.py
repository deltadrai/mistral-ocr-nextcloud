"""Guards that keep a release shippable.

The version is duplicated across the manifest, the JS package and the Python
package, and the app store requires ``<image-tag>`` to match ``<version>``.
These tests fail on drift instead of letting a release job discover it.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from mistral_ocr import __version__

REPO_ROOT = Path(__file__).resolve().parent.parent
INFO_XML = REPO_ROOT / "appinfo" / "info.xml"
PACKAGE_JSON = REPO_ROOT / "package.json"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
VALIDATOR = REPO_ROOT / "scripts" / "validate_info_xml.py"
BUMPER = REPO_ROOT / "scripts" / "bump_version.py"
VERSION_FILES = ("appinfo/info.xml", "package.json", "src/mistral_ocr/__init__.py", "CHANGELOG.md")

REQUIRED_ELEMENTS = ("id", "name", "summary", "description", "version", "licence", "category", "bugs")


@pytest.fixture(scope="module")
def info() -> ET.Element:
    return ET.parse(INFO_XML).getroot()


def test_manifest_has_the_elements_the_app_store_requires(info: ET.Element) -> None:
    missing = [tag for tag in REQUIRED_ELEMENTS if info.find(tag) is None]
    assert not missing, f"appinfo/info.xml is missing {missing}"


def test_manifest_declares_a_nextcloud_version_range(info: ET.Element) -> None:
    nextcloud = info.find("dependencies/nextcloud")
    assert nextcloud is not None, "appinfo/info.xml has no <dependencies><nextcloud>"
    min_version = int(nextcloud.get("min-version", "0"))
    max_version = int(nextcloud.get("max-version", "0"))
    assert 0 < min_version <= max_version


def test_version_is_identical_in_manifest_package_and_module(info: ET.Element) -> None:
    manifest_version = (info.findtext("version") or "").strip()
    package_version = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))["version"]
    assert manifest_version == package_version == __version__, (
        "version drift: info.xml=%r package.json=%r __init__.py=%r — run "
        "`python scripts/bump_version.py <version>`" % (manifest_version, package_version, __version__)
    )


def test_image_tag_is_pinned_to_the_version(info: ET.Element) -> None:
    image_tag = (info.findtext("external-app/docker-install/image-tag") or "").strip()
    assert image_tag == __version__, (
        f"<image-tag> is {image_tag!r} but the version is {__version__!r}; the app store refuses floating tags"
    )


def test_changelog_documents_the_current_version() -> None:
    changelog = CHANGELOG.read_text(encoding="utf-8")
    assert re.search(rf"^## \[{re.escape(__version__)}\]", changelog, flags=re.MULTILINE), (
        f"CHANGELOG.md has no '## [{__version__}]' section"
    )


def test_manifest_passes_the_app_store_schema() -> None:
    result = subprocess.run(
        [sys.executable, str(VALIDATOR)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"


def test_bump_version_updates_every_copy(tmp_path: Path) -> None:
    for relative in VERSION_FILES:
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / relative, destination)

    result = subprocess.run(
        [sys.executable, str(BUMPER), "9.9.9", "--date", "2030-01-02", "--root", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    bumped = ET.parse(tmp_path / "appinfo/info.xml").getroot()
    assert bumped.findtext("version") == "9.9.9"
    assert bumped.findtext("external-app/docker-install/image-tag") == "9.9.9"
    assert json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))["version"] == "9.9.9"
    assert '__version__ = "9.9.9"' in (tmp_path / "src/mistral_ocr/__init__.py").read_text(encoding="utf-8")
    changelog = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [9.9.9] - 2030-01-02" in changelog
    # The previous release section must survive the insertion.
    assert f"## [{__version__}]" in changelog


def test_bump_version_rejects_a_non_semver(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(BUMPER), "1.0", "--root", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "not a valid semantic version" in result.stderr
