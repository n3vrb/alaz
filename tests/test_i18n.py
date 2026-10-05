"""i18n module: locale detection, fallback, formatting, catalogue sanity."""
from __future__ import annotations

import ast
import logging
import re
from pathlib import Path

import pytest
from PyQt6.QtCore import QSettings

from alaz import i18n
from alaz.i18n_en import EN

ROOT = Path(__file__).resolve().parent.parent
TURKISH_CHARS = re.compile("[çğıİöşüÇĞÖŞÜ]")


@pytest.mark.parametrize("locale,expect", [
    ("tr_TR", "tr"), ("tr_TR.UTF-8", "tr"), ("TR", "tr"), ("en_US", "en"), ("de_DE", "en"), ("C", "en"), ("", "en"),
])
def test_auto_detection_with_injected_locale(locale, expect):
    assert i18n.detect_system_language(locale) == expect
    assert i18n.set_language("auto", locale_name=locale) == expect
    assert i18n.current_language() == expect


def test_explicit_language_wins_over_locale():
    assert i18n.set_language("en", locale_name="tr_TR") == "en"
    assert i18n.set_language("tr", locale_name="en_US") == "tr"
    assert i18n.language_preference() == "tr"


def test_unknown_preference_falls_back_to_auto():
    assert i18n.set_language("klingon", locale_name="tr_TR") == "tr"
    assert i18n.language_preference() == "auto"


def test_translate_and_identity():
    i18n.set_language("en")
    assert i18n.tr("Sessiz") == "Silent"
    i18n.set_language("tr")
    assert i18n.tr("Sessiz") == "Sessiz"


def test_format_placeholders_both_languages():
    i18n.set_language("tr")
    assert i18n.tr("Sistem {w} W", w=26) == "Sistem 26 W"
    i18n.set_language("en")
    assert i18n.tr("Sistem {w} W", w=26) == "System 26 W"
    assert i18n.tr("Nokta {i}/{n} seçili · sürükle veya ok tuşlarıyla ayarla", i=6, n=8).startswith("Point 6/8 selected")


def test_missing_translation_returns_turkish_and_logs_once(caplog):
    i18n.set_language("en")
    text = "Bu çeviri yok {x}"
    i18n._missing_logged.discard(text)
    with caplog.at_level(logging.DEBUG, logger="alaz.i18n"):
        assert i18n.tr(text, x=1) == "Bu çeviri yok 1"
        assert i18n.tr(text, x=2) == "Bu çeviri yok 2"
    assert sum("no en translation" in r.message for r in caplog.records) == 1


def test_bad_placeholders_do_not_raise():
    i18n.set_language("tr")
    assert i18n.tr("Sistem {w} W", other=1) == "Sistem {w} W"
    assert i18n.tr("") == ""


def test_trmap_translates_on_access():
    m = i18n.TrMap({"quiet": "Sessiz"})
    i18n.set_language("tr")
    assert m["quiet"] == "Sessiz" and m.get("x", "?") == "?"
    i18n.set_language("en")
    assert m["quiet"] == "Silent" and m.items() == [("quiet", "Silent")] and "quiet" in m


def test_init_from_settings(tmp_path):
    s = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    assert i18n.init_from_settings(s, locale_name="tr_TR") == "tr"       # default "auto"
    assert i18n.init_from_settings(s, locale_name="en_US") == "en"
    s.setValue(i18n.KEY_LANGUAGE, "tr")
    assert i18n.init_from_settings(s, locale_name="en_US") == "tr"
    s.setValue(i18n.KEY_LANGUAGE, "en")
    assert i18n.init_from_settings(s, locale_name="tr_TR") == "en"


def _placeholders(s: str) -> set[str]:
    return set(re.findall(r"{(\w*)}", s))


def test_english_entries_clean_and_placeholders_match():
    for tr_text, en_text in EN.items():
        assert not TURKISH_CHARS.search(en_text), (tr_text, en_text)
        assert _placeholders(tr_text) == _placeholders(en_text), (tr_text, en_text)


def _literal_tr_keys() -> set[str]:
    keys = set()
    for p in (ROOT / "alaz").rglob("*.py"):
        if p.name in ("i18n.py", "i18n_en.py", "icons.py"):
            continue
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if (isinstance(n, ast.Call) and getattr(n.func, "id", None) == "tr" and n.args
                    and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)):
                keys.add(n.args[0].value)
    return keys


def test_every_literal_tr_key_has_english():
    missing = sorted(k for k in _literal_tr_keys() if k not in EN)
    assert not missing, missing


def test_tables_translated():
    """Strings that reach tr() through module-level tables / dialog arguments."""
    from alaz.ui.widgets import cards
    from alaz.ui.windows import dialogs, fans_window, keyboard_window, main_window, tray
    tables = [main_window.PERF_DESC.values(), main_window.GPU_DESC.values(), main_window.BAT_STATUS.values(),
              main_window.GPU_REBOOT_SUB.values(), [main_window.NOT_SUPPORTED, "Açık işlerini kaydet."],
              tray.BAT_STATUS.values(), cards._BATT.values(), [t for _k, t, _n in fans_window.EPP_KEYS],
              [t for _k, t in keyboard_window.BRIGHTNESS], dialogs.GPU_NAMES.values(), [dialogs.ECO_EXIT_TEXT],
              ["Sessiz", "Dengeli", "Turbo", "Özel", "Eco", "Standart", "Ultimate", "Optimize"],
              ["Tamam", "Sonra", "Vazgeç", "Devam", "Eco modundan çık", "Yeniden başlat", "Yeniden başlatma gerekli",
               "Bilgisayar şimdi yeniden başlatılacak. Açık işlerini kaydettiğinden emin ol.",
               "dGPU yeniden etkinleştirildi. Standart modun çalışması için bilgisayarı şimdi yeniden "
               "başlatman gerekiyor. Açık işlerini kaydettiğinden emin ol."]]
    missing = sorted({t for tbl in tables for t in tbl if t not in EN})
    assert not missing, missing
