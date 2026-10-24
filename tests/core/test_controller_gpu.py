"""Live GPU switching, Optimize and Ultimate in the controller (fakes only; nothing touches the system)."""
from __future__ import annotations

import pytest
from PyQt6.QtCore import QSettings

from alaz.backend.gfx import Holder, LiveResult
from alaz.backend.sensors import SensorSnapshot
from alaz.backend.types import GfxMode, Profile
from alaz.core import controller as ctlmod
from alaz.core.controller import Controller
from tests.core.test_controller import Env


class GEnv(Env):
    def __init__(self, tmp_path, **kw):
        super().__init__(tmp_path, policy=Profile.BALANCED)
        self.gfx.live = kw.get("live", True)
        for k, v in kw.get("settings", {}).items():
            self.settings.setValue(k, v)
            self.ctl._optimize = self.settings.value("gpu/optimize", False, type=bool)
        self.busy_calls, self.failed, self.reboots, self.ultimate = [], [], [], []
        self.ctl.gpuBusy.connect(lambda h: self.busy_calls.append(h))
        self.ctl.gpuSwitchFailed.connect(lambda m, r: self.failed.append((m, r)))
        self.ctl.gpuRebootRequired.connect(lambda: self.reboots.append(1))
        self.ctl.gpuUltimateConfirm.connect(lambda: self.ultimate.append(1))

    def power(self, on_ac):
        self.sensors.updated.emit(SensorSnapshot(on_ac=on_ac))


def H(comm="firefox", pid=10):
    return Holder(pid=pid, comm=comm, user="enes", exe=f"/usr/bin/{comm}", nodes=["/dev/nvidia0"])


BUSY = LiveResult(False, 9, "busy", [H("firefox"), H("steam", 11)], False, "busy")


@pytest.fixture
def env(tmp_path):
    e = GEnv(tmp_path)
    e.ctl.start()
    return e


def mux(env, value):
    env.mux.write_text(f"{value}\n")


# ------------------------------------------------------------------ live switch
def test_view_fields_defaults(env):
    g = env.state.gfx
    assert g.live_ready is True and g.switching is False and g.waiting is None
    assert g.holders == [] and g.optimize is False and g.selected == "standard"


def test_live_eco_ok(env):
    env.ctl.request_gpu_mode("eco")
    assert env.gfx.live_requests == [GfxMode.INTEGRATED] and env.gfx.requests == []
    assert env.busy == [("gpu", True), ("gpu", False)]
    g = env.state.gfx
    assert g.active == "eco" and g.selected == "eco" and not g.switching and g.pending is None
    assert env.msgs[-1][0] == "info" and "Eco" in env.msgs[-1][1]
    assert env.reboots == [] and env.failed == []


def test_live_standard_ok(env):
    env.gfx.mode = env.gfx.boot = GfxMode.INTEGRATED
    env.gfx.dgpu = True
    env.ctl.start()
    env.ctl._rebuild_gfx()
    env.ctl.request_gpu_mode("standard")
    assert env.gfx.live_requests == [GfxMode.HYBRID]
    assert env.state.gfx.active == "standard" and env.reboots == []


def test_switching_flag_and_second_request_refused(env):
    env.gfx.live_hold = True
    env.ctl.request_gpu_mode("eco")
    assert env.state.gfx.switching is True
    env.ctl.request_gpu_mode("standard")
    env.ctl.cancel_gpu_pending()
    assert env.gfx.live_requests == [GfxMode.INTEGRATED]
    assert env.msgs[-1][0] == "warn"
    env.gfx.live_cb()
    assert env.state.gfx.switching is False


def test_active_hint_masks_stale_supergfxd_then_clears(env):
    env.gfx.live_updates_mode = False          # supergfxd still reports Hybrid
    before = env.gfx.refreshes
    env.ctl.request_gpu_mode("eco")
    assert env.state.gfx.active == "eco"       # hint
    assert env.gfx.refreshes > before and env.ctl._refresh_timer.isActive()
    env.gfx.mode = GfxMode.INTEGRATED          # supergfxd came back
    env.gfx.modeChanged.emit(int(GfxMode.INTEGRATED))
    assert env.state.gfx.active == "eco" and env.ctl._expect_active is None
    assert not env.ctl._hint_timer.isActive()


def test_hint_expires(env):
    env.gfx.live_updates_mode = False
    env.ctl.request_gpu_mode("eco")
    env.ctl._hint_timer.timeout.emit()
    assert env.state.gfx.active == "standard"


def test_supergfxd_availability_change_rebuilds_without_error(env):
    env.gfx.availableChanged.emit(False)
    env.gfx.availableChanged.emit(True)
    assert env.msgs == [] and env.failed == []


def test_already_in_target_mode_makes_no_request(env):
    env.ctl.request_gpu_mode("standard")
    assert env.gfx.live_requests == [] and env.gfx.requests == []
    assert env.msgs[-1][0] == "info"


def test_not_live_ready_uses_boot_path(tmp_path):
    e = GEnv(tmp_path, live=False)
    e.ctl.start()
    e.ctl.request_gpu_mode("eco")
    assert e.gfx.live_requests == [] and e.gfx.requests == [GfxMode.INTEGRATED]
    assert e.state.gfx.pending == "eco" and e.state.gfx.live_ready is False
    assert e.state.gfx.selected == "eco"          # the choice is shown while it is pending


def test_unknown_active_mode_uses_boot_path(env):
    env.gfx.mode = None
    env.ctl._rebuild_gfx()
    env.ctl.request_gpu_mode("eco")
    assert env.gfx.live_requests == [] and env.gfx.requests == [GfxMode.INTEGRATED]


# ------------------------------------------------------------------------- busy
def test_busy_emits_gpuBusy_and_nothing_else(env):
    env.gfx.live_reply = BUSY
    env.ctl.request_gpu_mode("eco")
    assert len(env.busy_calls) == 1 and [h.comm for h in env.busy_calls[0]] == ["firefox", "steam"]
    assert env.failed == [] and env.state.gfx.switching is False and env.state.gfx.waiting is None
    assert [h.comm for h in env.state.gfx.holders] == ["firefox", "steam"]


def test_resolve_busy_wait_then_poll_then_switch(env):
    env.gfx.live_reply = BUSY
    env.ctl.request_gpu_mode("eco")
    env.ctl.resolve_busy("wait")
    g = env.state.gfx
    assert g.waiting == "eco" and env.ctl._poll_timer.isActive() and env.ctl._poll_timer.interval() == 5000
    assert env.msgs[-1][1] == "firefox, steam dGPU kullanıyor; kapanınca Eco'ya geçilecek"
    # still held: poll does not switch
    env.ctl._poll_timer.timeout.emit()
    env.gfx.holder_cbs.pop()([H()])
    assert env.gfx.live_requests == [GfxMode.INTEGRATED] and env.state.gfx.waiting == "eco"
    # released: switch happens
    env.gfx.live_reply = LiveResult(True, 0)
    env.ctl._poll_timer.timeout.emit()
    env.gfx.holder_cbs.pop()([])
    assert env.gfx.live_requests == [GfxMode.INTEGRATED] * 2
    g = env.state.gfx
    assert g.active == "eco" and g.waiting is None and g.holders == []
    assert not env.ctl._poll_timer.isActive()


def test_poll_does_not_stack_queries(env):
    env.gfx.live_reply = BUSY
    env.ctl.request_gpu_mode("eco")
    env.ctl.resolve_busy("wait")
    env.ctl._poll_timer.timeout.emit()
    env.ctl._poll_timer.timeout.emit()
    assert len(env.gfx.holder_cbs) == 1


def test_waiting_busy_again_stays_waiting_silently(env):
    env.gfx.live_reply = BUSY
    env.ctl.request_gpu_mode("eco")
    env.ctl.resolve_busy("wait")
    n = len(env.msgs)
    env.ctl._poll_timer.timeout.emit()
    env.gfx.holder_cbs.pop()([])                # empty by the query, but busy again at switch time
    assert env.state.gfx.waiting == "eco" and len(env.busy_calls) == 1 and len(env.msgs) == n


def test_poll_result_ignored_after_cancel(env):
    env.gfx.live_reply = BUSY
    env.ctl.request_gpu_mode("eco")
    env.ctl.resolve_busy("wait")
    env.ctl._poll_timer.timeout.emit()
    env.ctl.cancel_gpu_pending()
    assert env.state.gfx.waiting is None and not env.ctl._poll_timer.isActive()
    env.gfx.holder_cbs.pop()([])
    assert env.gfx.live_requests == [GfxMode.INTEGRATED]


def test_resolve_busy_reboot_uses_boot_path(env):
    env.gfx.live_reply = BUSY
    env.ctl.request_gpu_mode("eco")
    env.ctl.resolve_busy("reboot")
    assert env.gfx.requests == [GfxMode.INTEGRATED] and env.state.gfx.pending == "eco"
    assert env.state.gfx.waiting is None and env.reboots == []        # never reboots automatically
    assert "yeniden başlatınca" in env.msgs[-1][1]


def test_resolve_busy_cancel(env):
    env.gfx.live_reply = BUSY
    env.ctl.request_gpu_mode("eco")
    env.ctl.resolve_busy("cancel")
    g = env.state.gfx
    assert g.waiting is None and g.holders == [] and g.selected == "standard"
    assert env.gfx.requests == [] and len(env.gfx.live_requests) == 1


def test_resolve_busy_without_pending_busy_is_ignored(env):
    env.ctl.resolve_busy("wait")
    env.ctl.resolve_busy("bogus")
    assert env.state.gfx.waiting is None and env.gfx.requests == []


def test_new_request_discards_pending_busy_dialog(env):
    env.gfx.live_reply = BUSY
    env.ctl.request_gpu_mode("eco")
    env.ctl.request_gpu_mode("standard")
    env.ctl.resolve_busy("reboot")
    assert env.gfx.requests == []


# ---------------------------------------------------------------------- failures
@pytest.mark.parametrize("result,reboot,needle", [
    (LiveResult(False, 10, "failed", [], True, "x [modprobe]"), True, "yarıda kaldı"),
    (LiveResult(False, 7, "supergfxd", message="m"), False, "supergfxd durdurulamadı"),
    (LiveResult(False, 4, "mux", message="m"), False, "Ultimate"),
    (LiveResult(False, 11, "precondition", message="rule 61"), False, "rule 61"),
    (LiveResult(False, 12, "aborted", message="modprobe -r"), False, "durduruldu"),
    (LiveResult(False, 127, "unavailable", message="m"), False, "yardımcısı"),
    (LiveResult(False, None, "start", message="could not start pkexec"), False, "could not start pkexec"),
])
def test_failures_emit_gpuSwitchFailed(env, result, reboot, needle):
    env.gfx.live_reply = result
    env.ctl.request_gpu_mode("eco")
    assert len(env.failed) == 1 and env.failed[0][1] is reboot and needle in env.failed[0][0]
    g = env.state.gfx
    assert g.switching is False and g.waiting is None and g.selected == "standard"
    assert env.busy[-1] == ("gpu", False)


def test_auth_cancelled_is_an_info_not_a_failure(env):
    env.gfx.live_reply = LiveResult(False, 126, "cancelled", message="x")
    env.ctl.request_gpu_mode("eco")
    assert env.failed == [] and env.msgs[-1][0] == "info" and "iptal" in env.msgs[-1][1]


# ---------------------------------------------------------------------- Optimize
def test_optimize_enable_on_battery_goes_eco(env):
    env.power(False)
    env.ctl.request_gpu_mode("optimize")
    assert env.gfx.live_requests == [GfxMode.INTEGRATED]
    g = env.state.gfx
    assert g.optimize and g.selected == "optimize" and g.active == "eco"
    assert env.settings.value("gpu/optimize", False, type=bool) is True


def test_optimize_enable_on_ac_when_already_standard_does_nothing(env):
    env.power(True)
    env.ctl.request_gpu_mode("optimize")
    assert env.gfx.live_requests == [] and env.state.gfx.optimize


def test_optimize_enable_before_first_snapshot_applies_on_it(env):
    env.ctl.request_gpu_mode("optimize")
    assert env.gfx.live_requests == []
    env.power(False)
    assert env.gfx.live_requests == [GfxMode.INTEGRATED]


def test_optimize_requires_live_ready(tmp_path):
    e = GEnv(tmp_path, live=False)
    e.ctl.start()
    e.ctl.request_gpu_mode("optimize")
    assert not e.state.gfx.optimize and e.msgs[-1][0] == "warn"
    assert e.settings.value("gpu/optimize", False, type=bool) is False


def test_optimize_transitions_are_debounced(env):
    env.power(True)
    env.ctl.request_gpu_mode("optimize")
    env.power(False)
    t = env.ctl._opt_timer
    assert t.isActive() and t.interval() == 5000 and t.isSingleShot()
    assert env.gfx.live_requests == []             # nothing before the debounce fires
    t.timeout.emit()
    assert env.gfx.live_requests == [GfxMode.INTEGRATED] and env.state.gfx.active == "eco"
    env.power(True)
    t.timeout.emit()
    assert env.gfx.live_requests == [GfxMode.INTEGRATED, GfxMode.HYBRID]
    assert env.state.gfx.active == "standard"


def test_optimize_flapping_back_to_same_source_does_nothing(env):
    env.power(True)
    env.ctl.request_gpu_mode("optimize")
    env.power(False)
    env.power(True)
    env.ctl._opt_timer.timeout.emit()
    assert env.gfx.live_requests == []


def test_optimize_repeated_same_snapshot_does_not_restart_timer(env):
    env.power(True)
    env.ctl.request_gpu_mode("optimize")
    env.power(True)
    assert not env.ctl._opt_timer.isActive()


def test_optimize_applied_once_at_start(tmp_path):
    e = GEnv(tmp_path, settings={"gpu/optimize": True})
    e.ctl.start()
    assert e.state.gfx.optimize and e.state.gfx.selected == "optimize"
    e.power(False)                                   # first snapshot: immediate, no debounce
    assert e.gfx.live_requests == [GfxMode.INTEGRATED]
    e.power(False)
    assert e.gfx.live_requests == [GfxMode.INTEGRATED]


def test_optimize_waits_for_active_mode_at_start(tmp_path):
    e = GEnv(tmp_path, settings={"gpu/optimize": True})
    e.gfx.mode = None
    e.ctl.start()
    e.power(False)
    assert e.gfx.live_requests == []
    e.gfx.mode = GfxMode.HYBRID
    e.gfx.modeChanged.emit(int(GfxMode.HYBRID))
    assert e.gfx.live_requests == [GfxMode.INTEGRATED]


def test_optimize_busy_waits_without_dialog_and_never_reboots(env):
    env.power(False)
    env.gfx.live_reply = BUSY
    env.ctl.request_gpu_mode("optimize")
    assert env.busy_calls == [] and env.failed == [] and env.reboots == []
    assert env.state.gfx.waiting == "eco" and env.ctl._poll_timer.isActive()
    assert env.msgs[-1][1] == "firefox, steam dGPU kullanıyor; kapanınca Eco'ya geçilecek"
    env.gfx.live_reply = LiveResult(True, 0)
    env.ctl._poll_timer.timeout.emit()
    env.gfx.holder_cbs.pop()([])
    assert env.state.gfx.active == "eco" and env.state.gfx.waiting is None and env.state.gfx.optimize


def test_optimize_waiting_cancelled_when_power_source_flips(env):
    env.power(False)
    env.gfx.live_reply = BUSY
    env.ctl.request_gpu_mode("optimize")
    assert env.state.gfx.waiting == "eco"
    env.power(True)
    assert env.state.gfx.waiting is None and not env.ctl._poll_timer.isActive()
    env.ctl._opt_timer.timeout.emit()
    assert len(env.gfx.live_requests) == 1             # already Standard: nothing to do


def test_optimize_failure_does_not_retry_in_a_loop(env):
    env.power(False)
    env.gfx.live_reply = LiveResult(False, 12, "aborted", message="m")
    env.ctl.request_gpu_mode("optimize")
    assert len(env.gfx.live_requests) == 1 and len(env.failed) == 1


def test_optimize_off_by_choosing_a_mode(env):
    env.power(False)
    env.gfx.live_reply = BUSY
    env.ctl.request_gpu_mode("optimize")
    assert env.state.gfx.waiting == "eco"
    env.gfx.live_reply = LiveResult(True, 0)
    env.ctl.request_gpu_mode("standard")                 # already standard: just turns Optimize off
    g = env.state.gfx
    assert not g.optimize and g.waiting is None and g.selected == "standard"
    assert env.settings.value("gpu/optimize", True, type=bool) is False
    env.power(True)
    env.power(False)
    assert not env.ctl._opt_timer.isActive()


def test_selecting_eco_turns_optimize_off_and_switches(env):
    env.power(True)
    env.ctl.request_gpu_mode("optimize")
    env.ctl.request_gpu_mode("eco")
    assert not env.state.gfx.optimize and env.gfx.live_requests == [GfxMode.INTEGRATED]


def test_cancel_clears_waiting_but_keeps_optimize(env):
    env.power(False)
    env.gfx.live_reply = BUSY
    env.ctl.request_gpu_mode("optimize")
    env.ctl.cancel_gpu_pending()
    g = env.state.gfx
    assert g.waiting is None and g.optimize and env.gfx.requests == []


# ---------------------------------------------------------------------- Ultimate
def test_ultimate_request_asks_for_confirmation_only(env):
    env.ctl.request_gpu_mode("ultimate")
    assert env.ultimate == [1] and env.asusd.sets == [] and env.gfx.requests == []


def test_ultimate_declined_changes_nothing(env):
    env.ctl.request_gpu_mode("ultimate")
    env.ctl.confirm_ultimate(False)
    assert env.asusd.sets == [] and env.reboots == [] and env.state.gfx.mux_direct is False


def test_ultimate_confirmed_writes_mux_and_prompts_reboot(env):
    env.ctl.request_gpu_mode("ultimate")
    env.ctl.confirm_ultimate(True)
    assert env.asusd.sets == [("GpuMuxMode", 0)] and env.reboots == [1]
    g = env.state.gfx
    assert g.mux_direct is True and g.selected == "ultimate"
    assert "yeniden başlat" in env.msgs[-1][1]


def test_ultimate_turns_optimize_off(env):
    env.power(True)
    env.ctl.request_gpu_mode("optimize")
    env.ctl.request_gpu_mode("ultimate")
    env.ctl.confirm_ultimate(True)
    assert not env.state.gfx.optimize
    assert env.settings.value("gpu/optimize", True, type=bool) is False


def test_eco_and_optimize_disabled_while_mux_direct_pending(env):
    env.ctl.request_gpu_mode("ultimate")
    env.ctl.confirm_ultimate(True)
    for mode in ("eco", "optimize"):
        env.ctl.request_gpu_mode(mode)
        assert env.msgs[-1][0] == "warn" and "Ultimate" in env.msgs[-1][1]
    assert env.gfx.live_requests == [] and env.gfx.requests == [] and not env.state.gfx.optimize


def test_eco_and_optimize_disabled_while_ultimate_active(tmp_path):
    e = GEnv(tmp_path)
    mux(e, 0)
    e.gfx.mode = e.gfx.boot = GfxMode.ASUS_MUX_DGPU
    e.ctl.start()
    assert e.state.gfx.active == "ultimate" and e.state.gfx.mux_direct is True
    for mode in ("eco", "optimize"):
        e.ctl.request_gpu_mode(mode)
        assert e.msgs[-1][0] == "warn"
    assert e.gfx.live_requests == [] and e.gfx.requests == []
    e.ctl.request_gpu_mode("ultimate")                    # already active
    assert e.ultimate == []


def test_leave_ultimate_to_standard_writes_mux_1_and_reboot(tmp_path):
    e = GEnv(tmp_path)
    mux(e, 0)
    e.gfx.mode = e.gfx.boot = GfxMode.ASUS_MUX_DGPU
    e.ctl.start()
    e.ctl.request_gpu_mode("standard")
    assert e.asusd.sets == [("GpuMuxMode", 1)] and e.reboots == [1]
    assert e.gfx.live_requests == [] and e.gfx.requests == []
    assert e.state.gfx.selected == "standard"
    # until the reboot nothing else may run live
    e.ctl.request_gpu_mode("eco")
    assert e.gfx.live_requests == [] and e.msgs[-1][0] == "warn"


def test_cancel_reverts_a_pending_mux_change(env):
    env.ctl.request_gpu_mode("ultimate")
    env.ctl.confirm_ultimate(True)
    env.ctl.cancel_gpu_pending()
    assert env.asusd.sets == [("GpuMuxMode", 0), ("GpuMuxMode", 1)]
    assert env.state.gfx.mux_direct is False and env.state.gfx.selected == "standard"
    assert len(env.reboots) == 1                          # no second prompt for the revert
    env.ctl.request_gpu_mode("eco")                       # live works again
    assert env.gfx.live_requests == [GfxMode.INTEGRATED]


def test_standard_after_pending_ultimate_reverts(env):
    env.ctl.request_gpu_mode("ultimate")
    env.ctl.confirm_ultimate(True)
    env.ctl.request_gpu_mode("standard")
    assert env.asusd.sets[-1] == ("GpuMuxMode", 1) and env.state.gfx.mux_direct is False


def test_mux_write_error_restores_state(env):
    env.ctl.request_gpu_mode("ultimate")
    env.ctl.confirm_ultimate(True)
    env.asusd.error.emit("set_platform:GpuMuxMode", "denied")
    assert env.state.gfx.mux_direct is False
    env.ctl.request_gpu_mode("eco")
    assert env.gfx.live_requests == [GfxMode.INTEGRATED]


def test_ultimate_not_while_switching(env):
    env.gfx.live_hold = True
    env.ctl.request_gpu_mode("eco")
    env.ctl.request_gpu_mode("ultimate")
    env.ctl.confirm_ultimate(True)
    assert env.ultimate == [] and env.asusd.sets == []


def test_optimize_setting_dropped_when_booted_in_ultimate(tmp_path):
    e = GEnv(tmp_path, settings={"gpu/optimize": True})
    mux(e, 0)
    e.gfx.mode = e.gfx.boot = GfxMode.ASUS_MUX_DGPU
    e.ctl.start()
    assert not e.state.gfx.optimize
    assert e.settings.value("gpu/optimize", True, type=bool) is False


def test_module_constants():
    assert ctlmod.OPT_DEBOUNCE_MS == 5000 and ctlmod.HOLDER_POLL_MS == 5000
    assert ctlmod.K_GPU_OPTIMIZE == "gpu/optimize"


def test_no_pending_while_live_hybrid_runs(env):
    """Regression (owner test 2026-10-24): the helper writes the boot config to Hybrid first; while the
    switch runs, active=eco + boot=standard + dgpu_disable=0 must NOT show the "reboot required" card."""
    env.gfx.mode = env.gfx.boot = GfxMode.INTEGRATED
    env.gfx.dgpu = True
    env.ctl.start()
    env.ctl._rebuild_gfx()
    env.gfx.live_hold = True
    env.ctl.request_gpu_mode("standard")
    env.gfx.boot = GfxMode.HYBRID              # helper already rewrote /etc/supergfxd.conf
    env.gfx.dgpu = False                       # ... and dgpu_disable=0
    env.ctl._rebuild_gfx()
    g = env.state.gfx
    assert g.switching is True and g.active == "eco" and g.pending is None
    env.gfx.live_cb()
    assert env.state.gfx.pending is None and env.reboots == []
