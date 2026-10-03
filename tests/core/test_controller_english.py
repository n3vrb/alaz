"""User-visible controller messages are translated."""
from __future__ import annotations

import re

import pytest

from rog_control import i18n
from rog_control.backend.types import GfxMode, Profile
from tests.core.test_controller import Env

TURKISH = re.compile("[çğıİöşüÇĞÖŞÜ]|\\b(Bekleyen|Geçersiz|Yeniden)\\b")


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path, policy=Profile.BALANCED)


def test_gpu_messages_english(env):
    i18n.set_language("en")
    env.ctl.start()
    env.ctl.request_gpu_mode("ultimate")
    assert env.msgs[-1] == ("warn", "This GPU mode isn't supported yet.")
    env.ctl.request_gpu_mode("eco")
    assert env.msgs[-1] == ("info", "Eco will take effect after restart.")
    env.gfx.reply = (False, "stderr")
    env.gfx.last_exit_code = 126
    env.ctl.request_gpu_mode("eco")
    assert env.msgs[-1][1] == "Authentication cancelled; nothing was changed."


def test_eco_exit_messages_english(env):
    i18n.set_language("en")
    env.gfx.mode = GfxMode.INTEGRATED
    env.gfx.boot = GfxMode.INTEGRATED
    env.ctl.start()
    env.ctl.request_gpu_mode("standard")
    assert "Restart NOW" in env.msgs[-1][1]
    for code in (7, 8, 127):
        env.gfx.reply = (False, "stderr")
        env.gfx.last_exit_code = code
        env.ctl.request_gpu_mode("standard")
        assert env.msgs[-1][0] == "error" and not TURKISH.search(env.msgs[-1][1]), env.msgs[-1]


def test_validation_messages_english(env):
    i18n.set_language("en")
    env.ctl.start()
    env.ctl.set_epp("balanced", 99)
    assert env.msgs[-1] == ("error", "Invalid EPP value: 99")
    env.ctl.set_auto_profile("x", "y")
    assert env.msgs[-1][1] == "Invalid auto-profile selection."
    env.ctl.apply_fan_curve("balanced", "CPU", [(20, 10)])
    assert env.msgs[-1][1] == "A fan curve must have exactly 8 points."
    env.ctl.apply_fan_curve("nope", "CPU", [])
    assert env.msgs[-1][1] == "Unknown mode: nope"
    env.ctl.apply_fan_curve("balanced", "CPU", [(40, 10)] * 8)
    assert env.msgs[-1][1] == "Fan curve temperatures must be in ascending order."


def test_turkish_still_default_in_tr_mode(env):
    env.ctl.start()
    env.ctl.request_gpu_mode("ultimate")
    assert env.msgs[-1] == ("warn", "Bu GPU modu henüz desteklenmiyor.")
