"""systemd autostart toggle, tray readiness polling, exit codes, D-Bus warm-up."""
from __future__ import annotations

import os
import stat
import time

import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication

from alaz import app as app_mod
from alaz.app import Shell
from alaz.ui.windows._fake import FakeController, FakeState
from alaz.ui.windows.settings_window import UNIT_NAME, SettingsWindow, run_systemctl


@pytest.fixture
def env(tmp_path):
    st = FakeState("balanced")
    return st, FakeController(st), QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)


def spin(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QApplication.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return cond()


class FakeSctl:
    def __init__(self, enabled=False, code=0):
        self.calls, self.enabled, self.code = [], enabled, code
        self.pending = []

    def __call__(self, args, cb):
        self.calls.append(list(args))
        self.pending.append((args, cb))

    def flush(self):
        while self.pending:
            args, cb = self.pending.pop(0)
            if args[0] == "is-enabled":
                cb(0 if self.enabled else 1, "enabled" if self.enabled else "disabled")
            else:
                cb(self.code, "")


# ------------------------------------------------------------ settings toggle
def test_toggle_uses_systemctl_and_removes_legacy(env, tmp_path):
    st, ctl, settings = env
    unit = tmp_path / "alaz.service"
    unit.write_text("[Unit]\n")
    legacy = tmp_path / "autostart" / "alaz.desktop"
    legacy.parent.mkdir()
    legacy.write_text("x")
    sctl = FakeSctl(enabled=False)
    w = SettingsWindow(st, ctl, settings, autostart_path=legacy, unit_path=unit, systemctl_runner=sctl)
    assert sctl.calls == [["is-enabled", UNIT_NAME]]          # real state queried on open
    sctl.flush()
    assert not w.sw_autostart.isChecked()
    w.sw_autostart.setChecked(True, emit=True)
    assert sctl.calls[-1] == ["enable", UNIT_NAME]
    assert legacy.exists()                                     # only removed after success
    sctl.flush()
    assert not legacy.exists()
    w.sw_autostart.setChecked(False, emit=True)
    assert sctl.calls[-1] == ["disable", UNIT_NAME]


def test_state_reflects_is_enabled_and_failure_reverts(env, tmp_path):
    st, ctl, settings = env
    unit = tmp_path / "u.service"
    unit.write_text("")
    sctl = FakeSctl(enabled=True)
    w = SettingsWindow(st, ctl, settings, autostart_path=tmp_path / "a.desktop", unit_path=unit,
                       systemctl_runner=sctl)
    sctl.flush()
    assert w.sw_autostart.isChecked()
    assert [c[0] for c in sctl.calls] == ["is-enabled"]       # opening did not toggle anything
    sctl.code = 1
    w.sw_autostart.setChecked(False, emit=True)
    sctl.flush()
    assert w.sw_autostart.isChecked() and w.note.text()


def test_no_unit_falls_back_to_xdg(env, tmp_path, monkeypatch):
    st, ctl, settings = env
    monkeypatch.setattr("alaz.ui.windows.settings_window._launcher", lambda: None)
    path = tmp_path / "autostart" / "alaz.desktop"
    sctl = FakeSctl()
    w = SettingsWindow(st, ctl, settings, autostart_path=path, unit_path=tmp_path / "missing.service",
                       systemctl_runner=sctl)
    w.sw_autostart.setChecked(True, emit=True)
    assert path.exists() and sctl.calls == []


def test_run_systemctl_is_async_with_fake_binary(tmp_path, monkeypatch):
    fake = tmp_path / "bin" / "systemctl"
    fake.parent.mkdir()
    fake.write_text("#!/bin/sh\n[ \"$1\" = --user ] || exit 9\necho \"$2\"; exit 3\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{fake.parent}:{os.environ['PATH']}")
    got = []
    run_systemctl(["is-enabled", UNIT_NAME], lambda c, o: got.append((c, o)))
    assert got == []                                           # returned immediately
    assert spin(lambda: got)
    assert got == [(3, "is-enabled")]
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    got.clear()
    run_systemctl(["x"], lambda c, o: got.append((c, o)))
    assert spin(lambda: got) and got[0][0] == -1               # missing systemctl is reported, not raised


# ------------------------------------------------------------ tray readiness
def make_shell(env, avail, monkeypatch):
    st, ctl, settings = env
    monkeypatch.setattr(Shell, "TRAY_POLL_MS", 10)
    monkeypatch.setattr(Shell, "TRAY_POLL_TIMEOUT_S", 0.2)
    monkeypatch.setattr(Shell, "TRAY_WATCH_MS", 10)
    shell = Shell(st, ctl, settings, tray_available_fn=lambda: avail["v"])
    shown = []
    shell.tray.icon.show = lambda: shown.append("icon")
    shell.main.show = lambda: shown.append("main")
    return shell, shown


def test_minimized_tray_ready_immediately(env, monkeypatch):
    shell, shown = make_shell(env, {"v": True}, monkeypatch)
    shell.start(minimized=True)
    assert shown == ["icon"]
    shell.quit()


def test_minimized_waits_for_tray_then_stays_hidden(env, monkeypatch):
    avail = {"v": False}
    shell, shown = make_shell(env, avail, monkeypatch)
    shell.start(minimized=True)
    assert shown == []
    spin(lambda: False, 0.05)
    assert "main" not in shown
    avail["v"] = True
    assert spin(lambda: "icon" in shown)
    spin(lambda: False, 0.3)                                   # past the timeout: window must stay hidden
    assert "main" not in shown
    shell.quit()


def test_minimized_shows_window_if_tray_never_comes(env, monkeypatch):
    shell, shown = make_shell(env, {"v": False}, monkeypatch)
    shell.start(minimized=True)
    assert spin(lambda: "main" in shown)
    shell.quit()


def test_tray_appearing_later_shows_icon(env, monkeypatch):
    avail = {"v": False}
    shell, shown = make_shell(env, avail, monkeypatch)
    shell.start(minimized=False)
    assert shown == ["main"]
    avail["v"] = True
    assert spin(lambda: "icon" in shown)
    shell.quit()


# ------------------------------------------------------------ exit codes
def test_already_running_exits_zero(monkeypatch):
    monkeypatch.setattr(app_mod.SingleInstance, "notify_existing", lambda self, timeout_ms=500: True)
    assert app_mod.main(["--fake"]) == 0


def test_normal_quit_exits_zero(monkeypatch, tmp_path):
    monkeypatch.setattr(app_mod, "QSettings", lambda *a: QSettings(str(tmp_path / "m.ini"), QSettings.Format.IniFormat))
    monkeypatch.setattr(app_mod.SingleInstance, "notify_existing", lambda self, timeout_ms=500: False)
    monkeypatch.setattr(app_mod.Shell, "start", lambda self, minimized=False: app_mod.QTimer.singleShot(
        0, self.quit))
    assert app_mod.main(["--fake", "--minimized"]) == 0


# ------------------------------------------------------------ D-Bus warm-up
def test_warm_up_targets_only_the_bus_daemon(monkeypatch):
    # The warm-up is a sacrificial typed call; it may only ever be addressed to the
    # bus daemon itself (never to ourselves: that logs policy rejections on the system bus).
    from alaz.backend import dbus_util
    sent = []

    class Bus:
        def asyncCall(self, msg, timeout):
            sent.append((msg.service(), msg.interface(), msg.member()))
            raise RuntimeError("stop here")  # don't need a real pending call
    monkeypatch.setattr(dbus_util, "_warmed_up", False)
    dbus_util._warm_up(Bus())
    assert dbus_util._warmed_up
    assert sent == [("org.freedesktop.DBus", "org.freedesktop.DBus", "GetNameOwner")]


def test_legacy_settings_migration(tmp_path, monkeypatch):
    old_dir = tmp_path / "rog-control"
    old_dir.mkdir()
    old = old_dir / "rog-control.conf"
    src = QSettings(str(old), QSettings.Format.IniFormat)
    src.setValue("lang", "en")
    src.setValue("ui/notify", True)
    src.sync()
    new = QSettings(str(tmp_path / "alaz" / "alaz.conf"), QSettings.Format.IniFormat)
    assert app_mod.migrate_legacy_settings(new, old) is True
    assert new.value("lang") == "en"
    assert new.value("ui/notify") is not None
    # the new file now exists -> never overwritten again
    new.setValue("lang", "tr")
    new.sync()
    assert app_mod.migrate_legacy_settings(new, old) is False
    assert new.value("lang") == "tr"


def test_legacy_settings_migration_no_old_file(tmp_path):
    new = QSettings(str(tmp_path / "alaz.conf"), QSettings.Format.IniFormat)
    assert app_mod.migrate_legacy_settings(new, tmp_path / "missing.conf") is False


def test_legacy_settings_file_uses_xdg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert app_mod.legacy_settings_file() == tmp_path / "rog-control" / "rog-control.conf"
