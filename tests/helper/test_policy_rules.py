"""Static checks of the polkit policy and the udev rule files (no system access)."""
import xml.etree.ElementTree as ET
from pathlib import Path

HELPER = Path(__file__).resolve().parents[2] / "helper"
EXEC = "/usr/local/libexec/alaz-gfx-helper"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


def _actions():
    root = ET.parse(HELPER / "org.alaz.gfx.policy").getroot()
    return {a.get("id"): a for a in root.findall("action")}


def _ann(a):
    return {n.get("key"): n.text for n in a.findall("annotate")}


def test_set_boot_mode_action_only_matches_its_own_argv1():
    # pkexec picks the FIRST action whose exec.path (and exec.argv1, if set) matches. Without argv1 this
    # password-protected action also matched live-eco/live-hybrid (owner saw a prompt, 2026-10-24).
    a = _actions()["org.alaz.gfx.set-boot-mode"]
    assert _ann(a) == {"org.freedesktop.policykit.exec.path": EXEC,
                       "org.freedesktop.policykit.exec.argv1": "set-boot-mode"}
    assert a.find("defaults/allow_active").text == "auth_admin_keep"


def test_live_actions():
    acts = _actions()
    for name in ("eco", "hybrid"):
        a = acts["org.alaz.gfx.live-" + name]
        assert _ann(a) == {"org.freedesktop.policykit.exec.path": EXEC,
                           "org.freedesktop.policykit.exec.argv1": "live-" + name}
        d = a.find("defaults")
        assert d.find("allow_any").text == "auth_admin"
        assert d.find("allow_inactive").text == "auth_admin"
        assert d.find("allow_active").text == "yes"
        for tag in ("description", "message"):
            langs = [e.get(XML_LANG) for e in a.findall(tag)]
            assert None in langs and "tr" in langs
        tr = [e.text for e in a.findall("description") if e.get(XML_LANG) == "tr"][0]
        assert "ı" in tr or "ş" in tr or "ü" in tr or "'yu" in tr


def test_policy_element_order_matches_dtd():
    # DTD: description*, message*, defaults?, annotate*
    order = {"description": 0, "message": 1, "defaults": 2, "annotate": 3}
    for a in _actions().values():
        seq = [order[c.tag] for c in a]
        assert seq == sorted(seq)


def _rule_lines(name):
    return [l for l in (HELPER / name).read_text().splitlines() if l and not l.startswith("#")]


def test_rule_61():
    assert _rule_lines("61-alaz-mutter-ignore-nvidia.rules") == [
        'SUBSYSTEM=="drm", KERNEL=="card[0-9]*", DRIVERS=="nvidia", '
        'PROGRAM=="/usr/bin/cat /sys/devices/platform/asus-nb-wmi/gpu_mux_mode", '
        'RESULT=="1", TAG+="mutter-device-ignore"']


def test_rule_72():
    assert _rule_lines("72-alaz-nvidia-render-noaccess.rules") == [
        'SUBSYSTEM=="drm", KERNEL=="renderD*", DRIVERS=="nvidia", '
        'PROGRAM=="/usr/bin/cat /sys/devices/platform/asus-nb-wmi/gpu_mux_mode", '
        'RESULT=="1", TAG-="uaccess"']


def test_root_scripts_install_and_remove_rules():
    inst = (HELPER / "install.sh").read_text()
    uninst = (HELPER / "uninstall.sh").read_text()
    for r in ("61-alaz-mutter-ignore-nvidia.rules", "72-alaz-nvidia-render-noaccess.rules"):
        assert r in inst and r in uninst
    assert "subsystem-match=drm" not in inst and "subsystem-match=drm" not in uninst
