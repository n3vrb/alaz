import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# One full QApplication for the whole session. Backend tests call
# QCoreApplication.instance() and reuse it; widget tests need a QApplication,
# and creating widgets on a bare QCoreApplication segfaults.
from PyQt6.QtWidgets import QApplication  # noqa: E402

_APP = QApplication.instance() or QApplication([])

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_quit_flag():
    # request_quit() sets an app-wide property; don't let it leak between tests.
    yield
    _APP.setProperty("rog_quitting", False)


@pytest.fixture(autouse=True)
def _no_real_systemd_unit(tmp_path, monkeypatch):
    # Never let a test see (or act through) the user's real systemd unit.
    monkeypatch.setattr("alaz.ui.windows.settings_window.DEFAULT_UNIT",
                        tmp_path / "no-such-config" / "alaz.service")


@pytest.fixture(autouse=True)
def _ui_language_tr():
    # Most tests assert the Turkish source strings; English-mode tests opt in via set_language("en").
    from alaz import i18n
    i18n.set_language("tr")
    yield
    i18n.set_language("tr")
