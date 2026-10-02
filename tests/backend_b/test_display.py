import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from rog_control.backend import display as D


def mode(mid, w, h, hz, cur=False):
    props = {"is-current": True} if cur else {}
    return (mid, w, h, hz, 1.0, [1.0], props)


def raw(edp="eDP-2", primary_external=True):
    edp_modes = [mode("2560x1600@60.0", 2560, 1600, 60.0, True),
                 mode("2560x1600@240.0", 2560, 1600, 240.0),
                 mode("1920x1200@60.0", 1920, 1200, 60.0)]
    dp_modes = [mode("1920x1080@60.0", 1920, 1080, 60.0, True),
                mode("1920x1080@144.0", 1920, 1080, 144.0)]
    monitors = [((edp, "A", "p", "s"), edp_modes, {}), (("DP-1", "B", "q", "t"), dp_modes, {})]
    logical = [(0, 0, 1.0, 0, not primary_external, [(edp, "A", "p", "s")], {}),
               (2560, 0, 1.0, 0, primary_external, [("DP-1", "B", "q", "t")], {})]
    return (7, monitors, logical, {})


@pytest.mark.parametrize("edp", ["eDP-1", "eDP-2"])
def test_parse_picks_edp_even_if_dp_primary(edp):
    st = D.parse_mutter_state(raw(edp, primary_external=True))
    assert st == D.DisplayState(edp, 60, [60, 240])


def test_parse_no_internal():
    r = raw()
    assert D.parse_mutter_state((1, [m for m in r[1] if m[0][0] == "DP-1"], r[2], {})) is None


def test_apply_payload():
    serial, method, lms, props = D.build_apply_args(raw("eDP-1"), "eDP-1", 240)
    assert (serial, method, props) == (7, 1, {})
    assert lms == [
        (0, 0, 1.0, 0, False, [("eDP-1", "2560x1600@240.0", {})]),
        (2560, 0, 1.0, 0, True, [("DP-1", "1920x1080@60.0", {})]),
    ]


def test_apply_unknown_rate():
    with pytest.raises(D.DisplayError):
        D.build_apply_args(raw(), "eDP-2", 144)


def test_set_refresh_sends_payload_via_injected_bus():
    from PyQt6.QtCore import QCoreApplication, QEventLoop, QTimer
    app = QCoreApplication.instance() or QCoreApplication([])
    sent = []
    c = D.DisplayClient(get_state=lambda: raw("eDP-2"), apply=sent.append, use_mutter=True)
    got = []
    c.changed.connect(got.append)
    loop = QEventLoop()
    c.changed.connect(lambda _s: loop.quit())
    QTimer.singleShot(3000, loop.quit)
    c.set_refresh(240)
    loop.exec()
    assert len(sent) == 1 and sent[0][1] == 1
    assert sent[0][2][0][5] == [("eDP-2", "2560x1600@240.0", {})]
    assert got


def test_parse_xrandr():
    out = """Screen 0: minimum 16 x 16
DP-1 connected primary 1920x1080+2560+0
   1920x1080     60.00*+
eDP-2 connected 2560x1600+0+0
   2560x1600    240.00 +  60.00*
"""
    st = D.parse_xrandr(out)
    assert st == D.DisplayState("eDP-2", 60, [60, 240])


XRANDR_REAL = """Screen 0: minimum 16 x 16, current 4480 x 1600, maximum 32767 x 32767
DP-1 connected primary 1920x1080+2560+0 (normal left inverted right x axis y axis) 527mm x 296mm
   1920x1080     60.00*+  144.00   120.00
   1280x720     239.00   60.00
eDP-1 connected 2560x1600+0+0 (normal left inverted right x axis y axis) 344mm x 215mm
\tEDID:
\t\t00ffffffffffff00
   2560x1600    240.00*+  60.00
   2048x1280    239.00    60.00
   1920x1200    238.00    60.00
   1600x1000    240.00
"""


def test_xrandr_rates_current_mode_only_and_edp():
    st = D.parse_xrandr(XRANDR_REAL)
    assert st == D.DisplayState("eDP-1", 240, [60, 240])


def test_xrandr_edp_listed_after_external_and_rounding():
    out = "DP-1 connected primary 1920x1080+0+0\n   1920x1080 60.00*+\neDP-1 connected 2560x1600+0+0\n   2560x1600 239.99*+ 60.00\n"
    assert D.parse_xrandr(out) == D.DisplayState("eDP-1", 240, [60, 240])


def test_xrandr_no_edp():
    assert D.parse_xrandr("DP-1 connected primary 1920x1080+0+0\n   1920x1080 60.00*+\n") is None


def test_monitors_changed_triggers_refresh():
    from PyQt6.QtCore import QCoreApplication, QEventLoop, QTimer
    app = QCoreApplication.instance() or QCoreApplication([])
    hz = [240]
    hooks = []
    c = D.DisplayClient(get_state=lambda: raw("eDP-2"), use_mutter=True,
                        subscribe=lambda cb: hooks.append(cb) or (lambda: hooks.clear()))
    got = []
    c.changed.connect(got.append)
    c.start_watching()
    c.start_watching()  # idempotent
    assert len(hooks) == 1
    import threading
    loop = QEventLoop()
    c.changed.connect(lambda _s: loop.quit())
    QTimer.singleShot(3000, loop.quit)
    threading.Thread(target=hooks[0]).start()  # signal arrives from a foreign thread
    loop.exec()
    assert got and got[0].connector == "eDP-2"
    c.stop_watching()
    assert not hooks


def test_x11_poll_only_with_listener():
    from PyQt6.QtCore import QCoreApplication
    app = QCoreApplication.instance() or QCoreApplication([])
    c = D.DisplayClient(use_mutter=False)
    calls = []
    c.refresh = lambda: calls.append(1)
    c._poll_tick()
    assert not calls
    c.changed.connect(lambda _s: None)
    c._poll_tick()
    assert calls == [1]
    c.start_watching(); assert c._poll is not None
    c.stop_watching()
