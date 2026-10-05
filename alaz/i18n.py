"""Tiny i18n layer (no Qt Linguist toolchain).

The source text in the code is Turkish and doubles as the catalogue key, so diffs stay readable:

    tr("Yeniden başlat")                       -> "Yeniden başlat" (tr) / "Restart" (en)
    tr("Nokta {i}/{n} seçili", i=3, n=8)       -> placeholders use str.format

Two catalogues exist: ``tr`` (identity; Turkish is the source language) and ``en`` (Turkish -> English, in
``alaz/i18n_en.py``). A missing English entry returns the Turkish text and is logged once at debug level.

Language preference lives in QSettings ``ui/language``: "auto" (default) | "en" | "tr". Auto picks Turkish when the
system locale starts with "tr", English otherwise. The language is applied at startup; changing it in Settings takes
effect after a restart.
"""
from __future__ import annotations

import logging
import os
import re

from alaz.i18n_en import EN

log = logging.getLogger(__name__)

KEY_LANGUAGE = "ui/language"
LANGUAGES = ("auto", "en", "tr")
CATALOGUES: dict[str, dict[str, str]] = {"tr": {}, "en": EN}

_preference = "auto"
_effective: str | None = None   # resolved lazily so the first tr() sees the real system locale
_missing_logged: set[str] = set()
_HAS_LETTER = re.compile(r"[^\W\d_]")


def system_locale_name() -> str:
    """Best guess of the system locale ('tr_TR', 'en_US', ...); Qt first, then the usual env variables."""
    name = ""
    try:
        from PyQt6.QtCore import QLocale
        name = QLocale.system().name()
    except Exception:  # noqa: BLE001 - Qt missing/unusable: fall back to the environment
        pass
    if name and name != "C":
        return name
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        val = os.environ.get(var, "")
        if val and val != "C":
            return val
    return name


def detect_system_language(locale_name: str | None = None) -> str:
    """'tr' if the (injected or system) locale starts with 'tr', else 'en'."""
    name = system_locale_name() if locale_name is None else locale_name
    return "tr" if name.lower().startswith("tr") else "en"


def resolve(preference: str, locale_name: str | None = None) -> str:
    return preference if preference in ("en", "tr") else detect_system_language(locale_name)


def set_language(preference: str = "auto", locale_name: str | None = None) -> str:
    """Select the UI language ("auto" | "en" | "tr"). Returns the effective language ("en" | "tr")."""
    global _preference, _effective
    _preference = preference if preference in LANGUAGES else "auto"
    _effective = resolve(_preference, locale_name)
    return _effective


def language_preference() -> str:
    return _preference


def current_language() -> str:
    global _effective
    if _effective is None:
        _effective = resolve(_preference)
    return _effective


def init_from_settings(settings, locale_name: str | None = None) -> str:
    """Read ``ui/language`` from QSettings and apply it. Call once at startup, before any window exists."""
    pref = str(settings.value(KEY_LANGUAGE, "auto") or "auto")
    return set_language(pref, locale_name)


def tr(text: str, **fmt) -> str:
    """Translate `text` (Turkish source) into the current language, then apply ``str.format(**fmt)``."""
    out = text
    if text and current_language() != "tr":
        out = CATALOGUES.get(current_language(), {}).get(text)
        if out is None:
            out = text
            if text not in _missing_logged and _HAS_LETTER.search(text):
                _missing_logged.add(text)
                log.debug("no %s translation for %r", current_language(), text)
    if fmt:
        try:
            return out.format(**fmt)
        except (KeyError, IndexError, ValueError):
            log.debug("bad format placeholders in %r", out)
    return out


class TrMap:
    """Read-only mapping whose values are translated on access (module-level label tables)."""

    def __init__(self, base: dict[str, str]):
        self._base = dict(base)

    def __getitem__(self, key: str) -> str:
        return tr(self._base[key])

    def get(self, key, default=None):
        return tr(self._base[key]) if key in self._base else default

    def __contains__(self, key) -> bool:
        return key in self._base

    def __iter__(self):
        return iter(self._base)

    def __len__(self) -> int:
        return len(self._base)

    def keys(self):
        return self._base.keys()

    def items(self):
        return [(k, tr(v)) for k, v in self._base.items()]

    def values(self):
        return [tr(v) for v in self._base.values()]
