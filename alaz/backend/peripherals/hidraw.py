"""hidraw discovery + a small request/response transport, plus a shared Qt client base.

Everything here is sysfs/hidraw only (no root; the udev rule grants the user access).
Tests inject fake I/O: they never open a real /dev node.
"""
from __future__ import annotations

import copy
import errno
import logging
import os
import select
import threading
import time
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, QTimer, pyqtSignal

log = logging.getLogger(__name__)

REPORT_LEN = 64
ERROR_MARK = b"\xff\xaa"
RESCAN_MS = 5_000


class HidError(OSError):
    pass


class HidPermissionError(HidError):
    pass


# ---- discovery ----------------------------------------------------------

def _parse_hid_id(uevent: str) -> tuple[int, int] | None:
    for line in uevent.splitlines():
        if line.startswith("HID_ID="):
            parts = line[7:].strip().split(":")
            if len(parts) == 3:
                try:
                    return int(parts[1], 16), int(parts[2], 16)
                except ValueError:
                    return None
    return None


def _node_index(name: str) -> int:
    digits = "".join(ch for ch in name if ch.isdigit())
    return int(digits) if digits else 1 << 30


def find_nodes(vid: int, pid_set: set[int], report_id: int, root: str | Path = "/sys/class/hidraw",
               dev_root: str | Path = "/dev") -> list[str]:
    """hidraw nodes of (vid, pid in pid_set) whose report descriptor contains ``85 <report_id>``."""
    base = Path(root)
    try:
        entries = sorted(base.iterdir(), key=lambda p: _node_index(p.name))
    except OSError:
        return []
    needle = bytes([0x85, report_id])
    found: list[str] = []
    for entry in entries:
        dev = entry / "device"
        try:
            ids = _parse_hid_id((dev / "uevent").read_text())
            if ids is None or ids[0] != vid or ids[1] not in pid_set:
                continue
            desc = (dev / "report_descriptor").read_bytes()
        except OSError:
            continue
        if needle in desc:
            found.append(str(Path(dev_root) / entry.name))
    return found


# ---- transport ----------------------------------------------------------

class RawIO:
    """Thin os/select wrapper; replaced by a fake in tests."""

    def open(self, path: str) -> int:
        return os.open(path, os.O_RDWR | os.O_NONBLOCK)

    def close(self, fd: int) -> None:
        os.close(fd)

    def read(self, fd: int) -> bytes | None:
        try:
            return os.read(fd, REPORT_LEN)
        except BlockingIOError:
            return None

    def write(self, fd: int, data: bytes) -> None:
        os.write(fd, data)

    def wait(self, fd: int, timeout: float) -> bool:
        r, _, _ = select.select([fd], [], [], max(0.0, timeout))
        return bool(r)


class HidTransport:
    """One hidraw node. All calls are expected on worker threads; a lock serialises them."""

    def __init__(self, path: str, report_id: int, io: RawIO | None = None,
                 clock: Callable[[], float] = time.monotonic):
        self.path = path
        self.report_id = report_id
        self._io = io or RawIO()
        self._clock = clock
        self._fd: int | None = None
        self._lock = threading.Lock()

    @property
    def is_open(self) -> bool:
        return self._fd is not None

    def open(self) -> None:
        with self._lock:
            if self._fd is not None:
                return
            try:
                self._fd = self._io.open(self.path)
            except PermissionError as exc:
                raise HidPermissionError(errno.EACCES, f"no permission for {self.path}") from exc

    def close(self) -> None:
        with self._lock:
            fd, self._fd = self._fd, None
            if fd is not None:
                try:
                    self._io.close(fd)
                except OSError:
                    pass

    def _frame(self, cmd: bytes) -> bytes:
        data = bytes([self.report_id]) + bytes(cmd)
        if len(data) > REPORT_LEN:
            raise ValueError("command too long")
        return data.ljust(REPORT_LEN, b"\x00")

    def _drain(self) -> None:
        for _ in range(256):
            if not self._io.read(self._fd):
                return

    def send(self, cmd: bytes) -> None:
        """Fire-and-forget write."""
        with self._lock:
            if self._fd is None:
                raise HidError(errno.EBADF, "transport not open")
            self._io.write(self._fd, self._frame(cmd))

    def write_acked(self, cmd: bytes, timeout: float) -> bool:
        """Write and wait for the device's echo of the command header (VERIFIED: mouse and headset echo
        every write, e.g. ``03 51 28 …`` / ``cc 51 28 …``). Not retried: a lost echo is only logged."""
        return self.request(cmd, bytes(cmd[:2]), timeout, retries=0) is not None

    def request(self, cmd: bytes, match: bytes, timeout: float, retries: int = 2) -> bytes | None:
        """Send ``cmd`` and return the matching reply (or an ``ff aa`` error reply).

        Returns None when nothing matched within ``timeout`` on every attempt.
        """
        frame = self._frame(cmd)
        n = len(match)
        with self._lock:
            if self._fd is None:
                raise HidError(errno.EBADF, "transport not open")
            for _attempt in range(retries + 1):
                self._drain()
                self._io.write(self._fd, frame)
                deadline = self._clock() + timeout
                while True:
                    remaining = deadline - self._clock()
                    if remaining <= 0 or not self._io.wait(self._fd, remaining):
                        break
                    r = self._io.read(self._fd)
                    if not r or r[0] != self.report_id:
                        continue
                    if r[1:3] == ERROR_MARK:
                        return bytes(r)
                    if r[1:1 + n] == match:
                        return bytes(r)
        return None


# ---- shared client base -------------------------------------------------

class _Gone(Exception):
    """The device node vanished / I/O failed mid-job."""


class _Task(QRunnable):
    def __init__(self, fn: Callable[[], None], on_error: Callable[[Exception], None]):
        super().__init__()
        self._fn = fn
        self._on_error = on_error

    def run(self) -> None:
        try:
            self._fn()
        except Exception as exc:  # noqa: BLE001
            log.exception("peripheral task failed")
            self._on_error(exc)


class HidClientBase(QObject):
    """Serialised worker + discovery/rescan/poll plumbing. Subclasses supply state + reads."""

    changed = pyqtSignal(object)
    error = pyqtSignal(str)
    _result = pyqtSignal(object)
    _failed = pyqtSignal(str)

    VID = 0
    PIDS: set[int] = set()
    REPORT_ID = 0
    TIMEOUT = 0.5

    def __init__(self, parent: QObject | None = None, *, finder: Callable[[], list[str]] | None = None,
                 transport_factory: Callable[[str], HidTransport] | None = None):
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._finder = finder or (lambda: find_nodes(self.VID, self.PIDS, self.REPORT_ID))
        self._factory = transport_factory or (lambda p: HidTransport(p, self.REPORT_ID))
        self._t = None
        self._state = self._fresh_state(False, True)
        self._published = copy.deepcopy(self._state)
        self._rescan_pending = False
        self._poll_timer: QTimer | None = None
        self._rescan_timer: QTimer | None = None
        self._result.connect(self._on_result)
        self._failed.connect(self.error)

    # subclass hooks
    def _fresh_state(self, present: bool, permission: bool):
        raise NotImplementedError

    def _read_all(self) -> None:
        raise NotImplementedError

    # public
    def state(self):
        return copy.deepcopy(self._published)

    def refresh(self) -> None:
        self._submit(lambda: self._do_refresh(True))

    def start_polling(self, interval_ms: int = 30_000) -> None:
        if self._poll_timer is None:
            self._poll_timer = QTimer(self)
            self._poll_timer.timeout.connect(self._poll_tick)
        self._poll_timer.start(interval_ms)
        if self._rescan_timer is None:
            self._rescan_timer = QTimer(self)
            self._rescan_timer.timeout.connect(self._rescan_tick)
        self._rescan_timer.start(RESCAN_MS)

    def stop_polling(self) -> None:
        for t in (self._poll_timer, self._rescan_timer):
            if t is not None:
                t.stop()

    def shutdown(self) -> None:
        self.stop_polling()
        self._pool.waitForDone(3000)
        if self._t is not None:
            self._t.close()
            self._t = None

    # internals (worker thread unless noted)
    def _submit(self, fn: Callable[[], None]) -> None:
        def guarded():
            try:
                fn()
            except _Gone:
                self._drop()
                self._publish()

        self._pool.start(_Task(guarded, lambda exc: self._failed.emit(str(exc))))

    def _on_result(self, st) -> None:  # GUI thread
        self._published = st
        self.changed.emit(copy.deepcopy(st))

    def _publish(self) -> None:
        self._result.emit(copy.deepcopy(self._state))

    def _poll_tick(self) -> None:  # GUI thread
        if self._published.present and self._published.permission:
            self.refresh()

    def _rescan_tick(self) -> None:  # GUI thread
        if (self._published.present and self._published.permission) or self._rescan_pending:
            return
        self._rescan_pending = True

        def job():
            try:
                self._do_refresh(False)
            finally:
                self._rescan_pending = False
        self._submit(job)

    def _drop(self) -> None:
        if self._t is not None:
            self._t.close()
            self._t = None
        self._state = self._fresh_state(False, True)

    def _do_refresh(self, force: bool) -> None:
        before = copy.deepcopy(self._state)
        if self._ensure():
            self._read_all()
        if force or self._state != before:
            self._publish()

    def _ensure(self) -> bool:
        if self._t is not None:
            return True
        nodes = self._finder()
        denied = False
        for path in nodes:
            t = self._factory(path)
            try:
                t.open()
            except HidPermissionError:
                denied = True
                continue
            except OSError as exc:
                log.warning("open %s failed: %s", path, exc)
                continue
            self._t = t
            if not (self._state.present and self._state.permission):
                self._state = self._fresh_state(True, True)
            return True
        self._state = self._fresh_state(bool(denied), not denied)
        return False

    def _ask(self, cmd: bytes, match: bytes) -> bytes | None:
        """One request; returns the reply (possibly an ff aa error) or None on timeout."""
        try:
            return self._t.request(cmd, match, self.TIMEOUT, 2)
        except OSError as exc:
            log.warning("hid I/O failed: %s", exc)
            raise _Gone() from exc

    def _tell(self, cmd: bytes) -> None:
        """Write one command and wait for its echo, so writes never pile up unacknowledged."""
        try:
            if not self._t.write_acked(cmd, self.TIMEOUT):
                log.warning("no echo for write %s", bytes(cmd[:3]).hex(" "))
        except OSError as exc:
            log.warning("hid write failed: %s", exc)
            raise _Gone() from exc


def is_error_reply(r: bytes | None) -> bool:
    return r is not None and r[1:3] == ERROR_MARK


def pad(r: bytes) -> bytes:
    return bytes(r).ljust(REPORT_LEN, b"\x00")
