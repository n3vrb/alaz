"""Internal-panel refresh rate control (Mutter D-Bus on Wayland, xrandr on X11)."""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Callable

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, QTimer, pyqtSignal

try:
    import gi

    gi.require_version("Gio", "2.0")
    gi.require_version("GLib", "2.0")
    from gi.repository import Gio, GLib

    _HAVE_GIO = True
except Exception:  # noqa: BLE001
    _HAVE_GIO = False

log = logging.getLogger(__name__)

MUTTER_NAME = "org.gnome.Mutter.DisplayConfig"
MUTTER_PATH = "/org/gnome/Mutter/DisplayConfig"
X11_POLL_MS = 10_000
APPLY_TEMPORARY = 1


class DisplayError(RuntimeError):
    pass


@dataclass
class DisplayState:
    connector: str
    current_hz: int
    rates: list[int] = field(default_factory=list)


def is_internal(connector: str) -> bool:
    return connector.startswith("eDP")


def _is_wayland() -> bool:
    return os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" or bool(
        os.environ.get("WAYLAND_DISPLAY"))


# ---- Mutter -------------------------------------------------------------

def mutter_get_state():
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    res = bus.call_sync(MUTTER_NAME, MUTTER_PATH, MUTTER_NAME, "GetCurrentState",
                        None, None, Gio.DBusCallFlags.NONE, 3000, None)
    return res.unpack()  # (serial, monitors, logical_monitors, props)


def parse_mutter_state(raw) -> DisplayState | None:
    """Pick the internal eDP-* panel (never the primary/external monitor)."""
    _serial, monitors, _logical, _props = raw
    for (spec, modes, _mprops) in monitors:
        conn = spec[0]
        if not is_internal(conn):
            continue
        cur = next(((m[1], m[2], m[3]) for m in modes if m[6].get("is-current")), None)
        if cur is None:
            continue
        w, h, refresh = cur
        rates = sorted({int(round(m[3])) for m in modes if (m[1], m[2]) == (w, h)})
        return DisplayState(conn, int(round(refresh)), rates)
    return None


def build_apply_args(raw, connector: str, hz: int):
    """Return (serial, method, logical_monitors, props) for ApplyMonitorsConfig."""
    serial, monitors, logical, _props = raw
    current_mode: dict[str, str] = {}
    target = None
    for (spec, modes, _mp) in monitors:
        conn = spec[0]
        cw = ch = None
        for m in modes:
            if m[6].get("is-current"):
                current_mode[conn] = m[0]
                cw, ch = m[1], m[2]
        if conn == connector:
            for m in modes:
                if (m[1], m[2]) == (cw, ch) and int(round(m[3])) == hz:
                    target = m[0]
                    break
    if target is None:
        raise DisplayError(f"no {hz} Hz mode for {connector} at current resolution")
    entries = []
    for (x, y, scale, transform, primary, mons, _lp) in logical:
        mon_entries = []
        for mref in mons:
            conn = mref[0]
            mode_id = target if conn == connector else current_mode.get(conn)
            if mode_id is not None:
                mon_entries.append((conn, mode_id, {}))
        entries.append((int(x), int(y), float(scale), int(transform), bool(primary), mon_entries))
    return serial, APPLY_TEMPORARY, entries, {}


def mutter_apply(args) -> None:
    params = GLib.Variant("(uua(iiduba(ssa{sv}))a{sv})", args)
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    bus.call_sync(MUTTER_NAME, MUTTER_PATH, MUTTER_NAME, "ApplyMonitorsConfig",
                  params, None, Gio.DBusCallFlags.NONE, 5000, None)


# ---- xrandr -------------------------------------------------------------

def parse_xrandr(out: str) -> DisplayState | None:
    """Internal eDP* output only; rates come from its CURRENT mode line (the one with '*')."""
    conn = None
    rates: set[int] = set()
    current = 0
    found = False
    for line in out.splitlines():
        m = re.match(r"^(\S+) (connected|disconnected)", line)
        if m:
            if found:
                break
            if m.group(2) == "connected" and is_internal(m.group(1)):
                conn, found = m.group(1), True
            continue
        if found and re.match(r"^\s+\d+x\d+", line) and "*" in line:
            for rate, star in re.findall(r"(\d+(?:\.\d+)?)(\*?)", line.split(None, 1)[1]):
                r = int(round(float(rate)))
                rates.add(r)
                if star:
                    current = r
    if not found:
        return None
    return DisplayState(conn, current, sorted(rates))


def xrandr_state() -> DisplayState | None:
    out = subprocess.run(["xrandr"], capture_output=True, text=True, timeout=5).stdout
    return parse_xrandr(out)


def xrandr_set(connector: str, hz: int) -> None:
    try:
        subprocess.run(["xrandr", "--output", connector, "--rate", str(hz)],
                       capture_output=True, text=True, timeout=8, check=True)
    except subprocess.CalledProcessError as exc:
        raise DisplayError(exc.stderr or str(exc)) from exc


def mutter_subscribe(callback: Callable[[], None]) -> Callable[[], None]:
    """Subscribe to Mutter's MonitorsChanged on a private GLib loop thread.

    ``callback`` runs on that helper thread (never the GUI thread). Returns a stop function.
    """
    ctx = GLib.MainContext.new()
    loop = GLib.MainLoop.new(ctx, False)

    def run():
        ctx.push_thread_default()
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            bus.signal_subscribe(MUTTER_NAME, MUTTER_NAME, "MonitorsChanged", MUTTER_PATH,
                                 None, Gio.DBusSignalFlags.NONE,
                                 lambda *_a: callback(), None)
            loop.run()
        except Exception:  # noqa: BLE001
            log.exception("MonitorsChanged subscription failed")
        finally:
            ctx.pop_thread_default()

    threading.Thread(target=run, name="mutter-monitors", daemon=True).start()
    return loop.quit


# ---- client -------------------------------------------------------------

class _Task(QRunnable):
    def __init__(self, fn: Callable[[], None]):
        super().__init__()
        self._fn = fn

    def run(self) -> None:
        try:
            self._fn()
        except Exception:  # noqa: BLE001
            log.exception("display task failed")


class DisplayClient(QObject):
    changed = pyqtSignal(object)  # DisplayState | None
    error = pyqtSignal(str)
    _result = pyqtSignal(object)
    _failed = pyqtSignal(str)
    _external = pyqtSignal()  # MonitorsChanged (emitted from the helper thread, queued to GUI)

    def __init__(self, parent: QObject | None = None, *, get_state=None, apply=None,
                 use_mutter: bool | None = None, subscribe=None):
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._mutter = (_HAVE_GIO and (_is_wayland() or shutil.which("xrandr") is None)
                        if use_mutter is None else use_mutter)
        self._get_state = get_state or mutter_get_state
        self._apply = apply or mutter_apply
        self._result.connect(self.changed)
        self._failed.connect(self.error)
        self._subscribe = subscribe or mutter_subscribe
        self._unsubscribe: Callable[[], None] | None = None
        self._poll: QTimer | None = None
        self._external.connect(self.refresh)

    def start_watching(self) -> None:
        """Keep state fresh after external changes (call once; refresh stays off the GUI thread).

        Wayland: re-read on Mutter ``MonitorsChanged``. X11: re-read every 10 s, only while a
        listener is connected to ``changed``. ``refresh()`` may also be called directly
        (the controller does so before comparing).
        """
        if self._mutter:
            if self._unsubscribe is None:
                self._unsubscribe = self._subscribe(self._external.emit)
        elif self._poll is None:
            self._poll = QTimer(self)
            self._poll.setInterval(X11_POLL_MS)
            self._poll.timeout.connect(self._poll_tick)
            self._poll.start()

    def stop_watching(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        if self._poll is not None:
            self._poll.stop()
            self._poll = None

    def _poll_tick(self) -> None:
        if self.receivers(self.changed) > 0:
            self.refresh()

    def _read_state(self) -> DisplayState | None:
        if self._mutter:
            return parse_mutter_state(self._get_state())
        return xrandr_state()

    def refresh(self) -> None:
        def job():
            try:
                self._result.emit(self._read_state())
            except Exception as exc:  # noqa: BLE001
                log.warning("display refresh failed: %s", exc)
                self._result.emit(None)
        self._pool.start(_Task(job))

    def set_refresh(self, hz: int) -> None:
        def job():
            try:
                if self._mutter:
                    raw = self._get_state()
                    st = parse_mutter_state(raw)
                    if st is None:
                        raise DisplayError("no internal panel found")
                    self._apply(build_apply_args(raw, st.connector, hz))
                else:
                    st = xrandr_state()
                    if st is None:
                        raise DisplayError("no internal panel found")
                    xrandr_set(st.connector, hz)
                self._result.emit(self._read_state())
            except Exception as exc:  # noqa: BLE001
                log.warning("set_refresh(%s) failed: %s", hz, exc)
                self._failed.emit(str(exc))
        self._pool.start(_Task(job))
