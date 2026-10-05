"""Regression: in a FRESH process the first typed D-Bus call used to fail to marshal
("Unregistered type PyQt_PyObject"), silently breaking the app's first write.
Runs a subprocess against a private dbus-daemon; nothing touches the real buses."""
import os
import shutil
import subprocess
import sys
import textwrap

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SCRIPT = textwrap.dedent("""
    import os, sys, subprocess
    sys.path.insert(0, sys.argv[1])
    d = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address"],
                         stdout=subprocess.PIPE, text=True)
    addr = d.stdout.readline().strip()
    from PyQt6.QtCore import QCoreApplication, QTimer
    from PyQt6.QtDBus import QDBusConnection
    app = QCoreApplication([])
    from alaz.backend import dbus_util as du
    bus = QDBusConnection.connectToBus(addr, "quirk")
    out = []
    du.async_call(bus, "org.example.Nope", "/x", "org.example.I", "M",
                  [du.Typed("y", 80)], lambda r, e: out.append(e or "OK"))
    QTimer.singleShot(1500, app.quit)
    app.exec()
    d.terminate()
    print("RESULT:", out[0] if out else "NONE")
""")


@pytest.mark.skipif(shutil.which("dbus-daemon") is None, reason="dbus-daemon not available")
def test_first_typed_call_in_fresh_process_reaches_the_bus():
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    r = subprocess.run([sys.executable, "-c", SCRIPT, ROOT], capture_output=True, text=True,
                       timeout=30, env=env)
    line = [l for l in r.stdout.splitlines() if l.startswith("RESULT:")]
    assert line, r.stdout + r.stderr
    # Reaching the bus gives ServiceUnknown; the bug gives "Marshalling failed".
    assert "Marshalling failed" not in line[0], line[0]
    assert "ServiceUnknown" in line[0], line[0]
