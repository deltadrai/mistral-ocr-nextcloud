"""Guards the bundled translation catalogues.

The settings page is translated by looking English source strings up in a
catalogue bundled with the JS (see js/src/l10n/index.js), because AppAPI's native
<translations_folder> only works for archive installs. A string added to the page
without a catalogue entry would silently fall back to English, so this test
fails the build instead.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PAGE = REPO_ROOT / "js" / "src" / "admin_page.js"
CATALOG_DIR = REPO_ROOT / "js" / "src" / "l10n"

# t('...') with an optional second argument; single-quoted source strings only.
T_CALL = re.compile(r"\bt\(\s*'((?:[^'\\]|\\.)*)'\s*(?:,|\))")


@pytest.fixture(scope="module")
def page_strings() -> list[str]:
    return T_CALL.findall(PAGE.read_text(encoding="utf-8"))


def test_page_uses_translatable_strings(page_strings: list[str]) -> None:
    assert page_strings, "no t('...') calls found in the settings page"


@pytest.mark.parametrize("language", ["de"])
def test_every_page_string_is_translated(language: str, page_strings: list[str]) -> None:
    catalog = json.loads((CATALOG_DIR / f"{language}.json").read_text(encoding="utf-8"))
    missing = sorted(set(page_strings) - set(catalog))
    assert not missing, f"{language}.json is missing {len(missing)} strings: {missing}"


def test_catalogue_values_are_non_empty_and_differ_from_the_source() -> None:
    catalog = json.loads((CATALOG_DIR / "de.json").read_text(encoding="utf-8"))
    for source, translated in catalog.items():
        assert translated.strip(), f"empty German translation for {source!r}"
        assert translated != source, f"German translation identical to source: {source!r}"


def test_placeholders_in_catalogue_match_the_source() -> None:
    """A {var} present in the source must survive translation, and vice versa."""
    catalog = json.loads((CATALOG_DIR / "de.json").read_text(encoding="utf-8"))
    placeholders = re.compile(r"\{(\w+)\}")
    for source, translated in catalog.items():
        assert sorted(placeholders.findall(source)) == sorted(placeholders.findall(translated)), (
            f"placeholder mismatch for {source!r}: {translated!r}"
        )
