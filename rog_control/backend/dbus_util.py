"""Small asynchronous helpers over PyQt6.QtDBus.

Every call is asynchronous (QDBusPendingCallWatcher); nothing here blocks the
GUI thread.  Replies are normalised to plain Python values (D-Bus ``y`` comes
back from PyQt as 1-byte ``bytes`` and is converted to ``int``).

Typing of outgoing values
-------------------------
PyQt marshals a plain Python ``int`` as ``i`` (int32), which asusd rejects for
``y``/``u`` properties.  Values that need an explicit D-Bus type are therefore
described with :class:`Typed` (method arguments) or :class:`Variant`
(``v`` arguments such as the value of ``Properties.Set``) and converted at send
time into a ``QDBusArgument`` built with explicit metatype ids.

Quirk (reproduced in a fresh process on a private bus): the very first message
carrying a ``QDBusArgument`` that goes through ``QDBusConnection.asyncCall`` in a
process fails to marshal locally ("Unregistered type PyQt_PyObject") and is never
sent; every later one works.  Building a QDBusArgument/QDBusMessage locally does
NOT avoid it.  So the first call performs a one-time sacrificial call that is
addressed to the bus daemon itself (``org.freedesktop.DBus``): normally it fails
locally and nothing is sent; if the quirk is ever fixed it reaches the bus
daemon, which answers with a harmless error and never logs a policy rejection
(unlike a self-addressed call on the system bus).
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, Callable

from PyQt6.QtCore import QObject, QMetaType, QTimer, pyqtSlot
from PyQt6.QtDBus import (
    QDBusArgument,
    QDBusConnection,
    QDBusMessage,
    QDBusPendingCallWatcher,
    QDBusPendingReply,
    QDBusServiceWatcher,
    QDBusVariant,
)

log = logging.getLogger(__name__)

PROPERTIES_IFACE = "org.freedesktop.DBus.Properties"
INTROSPECTABLE_IFACE = "org.freedesktop.DBus.Introspectable"
DEFAULT_TIMEOUT_MS = 5000

Callback = Callable[[Any, "str | None"], None]


# --------------------------------------------------------------------------
# Typed values
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Typed:
    """A method argument with an explicit D-Bus signature, e.g. Typed("u", 0)."""

    sig: str
    value: Any


@dataclass(frozen=True)
class Variant:
    """A ``v`` argument whose content has signature ``sig``."""

    sig: str
    value: Any


_BASIC_IDS = {
    "y": QMetaType.Type.UChar,
    "n": QMetaType.Type.Short,
    "q": QMetaType.Type.UShort,
    "i": QMetaType.Type.Int,
    "u": QMetaType.Type.UInt,
    "x": QMetaType.Type.LongLong,
    "t": QMetaType.Type.ULongLong,
    "b": QMetaType.Type.Bool,
    "d": QMetaType.Type.Double,
    "s": QMetaType.Type.QString,
}
# Types PyQt already marshals correctly when passed as plain Python values.
_PLAIN = {"b", "d", "i", "s"}


def split_signature(sig: str) -> list[str]:
    """Split a signature into its complete types: "u(yy)as" -> ["u", "(yy)", "as"]."""
    out: list[str] = []
    i = 0
    while i < len(sig):
        start = i
        while sig[i] == "a":
            i += 1
        if sig[i] == "(":
            depth = 0
            while True:
                if sig[i] == "(":
                    depth += 1
                elif sig[i] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
        i += 1
        out.append(sig[start:i])
    return out


def _append(arg: QDBusArgument, sig: str, value: Any) -> None:
    """Append ``value`` as D-Bus type ``sig`` to ``arg``."""
    if sig in _BASIC_IDS:
        if sig == "b":
            value = bool(value)
        elif sig == "d":
            value = float(value)
        elif sig != "s":
            value = int(value)
        arg.add(value, _BASIC_IDS[sig].value)
    elif sig.startswith("("):
        parts = split_signature(sig[1:-1])
        if len(parts) != len(value):
            raise ValueError(f"struct {sig} needs {len(parts)} members, got {len(value)}")
        arg.beginStructure()
        for part, item in zip(parts, value):
            _append(arg, part, item)
        arg.endStructure()
    elif sig.startswith("a") and sig[1:] in _BASIC_IDS:
        elem = _BASIC_IDS[sig[1:]].value
        arg.beginArray(elem)
        for item in value:
            _append(arg, sig[1:], item)
        arg.endArray()
    else:
        raise ValueError(f"unsupported D-Bus signature: {sig}")


def to_qt(sig: str, value: Any) -> Any:
    """Convert a Python value to something QDBusMessage.setArguments accepts."""
    if sig in _PLAIN:
        return {"b": bool, "d": float, "i": int, "s": str}[sig](value)
    arg = QDBusArgument()
    _append(arg, sig, value)
    return arg


def _marshal_args(args: list[Any]) -> list[Any]:
    out = []
    for a in args:
        if isinstance(a, Typed):
            out.append(to_qt(a.sig, a.value))
        elif isinstance(a, Variant):
            out.append(QDBusVariant(to_qt(a.sig, a.value)))
        else:
            out.append(a)
    return out


def normalize(value: Any) -> Any:
    """Make PyQt-unmarshalled values plain: 1-byte ``bytes`` (D-Bus y) -> int."""
    if isinstance(value, (bytes, bytearray)):
        return value[0] if len(value) == 1 else bytes(value)
    if isinstance(value, QDBusVariant):
        return normalize(value.variant())
    if isinstance(value, dict):
        return {k: normalize(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return tuple(normalize(v) for v in value)
    if isinstance(value, list):
        return [normalize(v) for v in value]
    return value


# --------------------------------------------------------------------------
# Async calls
# --------------------------------------------------------------------------
_warmed_up = False
_pending: set[QDBusPendingCallWatcher] = set()


def _warm_up(bus: QDBusConnection) -> None:
    """One-time sacrificial typed call to the bus daemon (see module docstring)."""
    global _warmed_up
    if _warmed_up:
        return
    _warmed_up = True
    try:
        msg = QDBusMessage.createMethodCall(
            "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "GetNameOwner")
        msg.setArguments(_marshal_args([Typed("y", 0)]))
        pending = bus.asyncCall(msg, 2000)
        watcher = QDBusPendingCallWatcher(pending)
        _pending.add(watcher)
        watcher.finished.connect(lambda w: (_pending.discard(w), w.deleteLater()))
    except Exception:  # pragma: no cover - defensive
        log.debug("QDBus warm-up failed", exc_info=True)


def _defer(callback: Callback, result: Any, error: str | None) -> None:
    QTimer.singleShot(0, lambda: _safe_call(callback, result, error))


def _safe_call(callback: Callback | None, result: Any, error: str | None) -> None:
    if callback is None:
        return
    try:
        callback(result, error)
    except Exception:
        log.exception("D-Bus callback raised")


def async_call(
    bus: QDBusConnection,
    service: str,
    path: str,
    interface: str,
    method: str,
    args: list[Any] | None = None,
    callback: Callback | None = None,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> None:
    """Call a method asynchronously.

    ``callback(result, error)``: ``result`` is the list of normalised reply
    arguments (``None`` on error); ``error`` is a message string or ``None``.
    """
    if not bus.isConnected():
        _defer(callback, None, "D-Bus is not connected")
        return
    _warm_up(bus)
    msg = QDBusMessage.createMethodCall(service, path, interface, method)
    try:
        msg.setArguments(_marshal_args(list(args or [])))
    except (ValueError, TypeError) as exc:
        _defer(callback, None, f"bad arguments for {method}: {exc}")
        return
    msg.setInteractiveAuthorizationAllowed(True)
    pending = bus.asyncCall(msg, timeout_ms)
    watcher = QDBusPendingCallWatcher(pending)
    _pending.add(watcher)

    def done(w: QDBusPendingCallWatcher) -> None:
        _pending.discard(w)
        reply = QDBusPendingReply(pending).reply()
        if reply.type() == QDBusMessage.MessageType.ErrorMessage:
            result, error = None, f"{reply.errorName()}: {reply.errorMessage()}"
        else:
            result, error = normalize(list(reply.arguments())), None
        w.deleteLater()
        _safe_call(callback, result, error)

    watcher.finished.connect(done)


def get_all(bus, service, path, interface, callback: Callback) -> None:
    """Properties.GetAll -> callback(dict | None, error)."""

    def cb(result, error):
        callback(result[0] if result else None, error)

    async_call(bus, service, path, PROPERTIES_IFACE, "GetAll", [interface], cb)


def get_property(bus, service, path, interface, name, callback: Callback) -> None:
    """Properties.Get -> callback(value | None, error)."""

    def cb(result, error):
        callback(result[0] if result else None, error)

    async_call(bus, service, path, PROPERTIES_IFACE, "Get", [interface, name], cb)


def set_property(
    bus, service, path, interface, name, sig: str, value, callback: Callback | None = None
) -> None:
    """Properties.Set with an explicit variant signature (y/u/b/s/structs)."""
    async_call(
        bus, service, path, PROPERTIES_IFACE, "Set",
        [interface, name, Variant(sig, value)], callback,
    )


def introspect(bus, service, path, callback: Callback) -> None:
    """Introspect -> callback(xml string | None, error)."""

    def cb(result, error):
        callback(result[0] if result else None, error)

    async_call(bus, service, path, INTROSPECTABLE_IFACE, "Introspect", [], cb)


def parse_introspection(xml: str) -> tuple[list[str], list[str]]:
    """Return (child node names, interface names) from introspection XML."""
    root = ET.fromstring(xml)
    children = [n.get("name", "") for n in root.findall("node")]
    ifaces = [i.get("name", "") for i in root.findall("interface")]
    return children, ifaces


# --------------------------------------------------------------------------
# Signals
# --------------------------------------------------------------------------
class SignalSink(QObject):
    """Receives D-Bus signals and forwards ``(QDBusMessage)`` to a callable."""

    def __init__(self, handler: Callable[[QDBusMessage], None], parent: QObject | None = None):
        super().__init__(parent)
        self._handler = handler

    @pyqtSlot(QDBusMessage)
    def on_signal(self, msg: QDBusMessage) -> None:
        try:
            self._handler(msg)
        except Exception:
            log.exception("D-Bus signal handler raised")


def subscribe_signal(
    bus: QDBusConnection,
    service: str,
    path: str,
    interface: str,
    name: str,
    handler: Callable[[list[Any]], None],
    parent: QObject,
) -> SignalSink | None:
    """Subscribe to a signal; ``handler`` gets the normalised argument list."""
    sink = SignalSink(lambda m: handler(normalize(list(m.arguments()))), parent)
    if not bus.connect(service, path, interface, name, sink.on_signal):
        log.warning("could not subscribe to %s.%s on %s", interface, name, path)
        sink.deleteLater()
        return None
    return sink


def subscribe_properties_changed(
    bus: QDBusConnection,
    service: str,
    path: str,
    handler: Callable[[str, dict[str, Any], list[str]], None],
    parent: QObject,
) -> SignalSink | None:
    """Subscribe to Properties.PropertiesChanged on ``path``.

    ``handler(interface, changed: dict, invalidated: list[str])``.
    """

    def on_args(args: list[Any]) -> None:
        if len(args) < 2:
            return
        invalidated = list(args[2]) if len(args) > 2 and args[2] else []
        handler(str(args[0]), dict(args[1] or {}), invalidated)

    return subscribe_signal(bus, service, path, PROPERTIES_IFACE, "PropertiesChanged", on_args, parent)


def watch_service(
    bus: QDBusConnection, service: str, on_change: Callable[[bool], None], parent: QObject
) -> QDBusServiceWatcher:
    """Call ``on_change(True/False)`` when ``service`` appears/disappears."""
    watcher = QDBusServiceWatcher(
        service, bus, QDBusServiceWatcher.WatchModeFlag.WatchForOwnerChange, parent
    )

    def changed(_name: str, _old: str, new: str) -> None:
        on_change(bool(new))

    watcher.serviceOwnerChanged.connect(changed)
    return watcher
