"""Named user profiles — persisted via QSettings as JSON.

Each profile stores: display name, asusctl profile, supergfx GPU mode,
and battery charge limit. Applying a profile sets all three in sequence.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Optional

from PyQt5.QtCore import QSettings

from . import backend


@dataclass
class Profile:
    name:      str
    perf:      str   # asusctl name  e.g. "Balanced"
    gpu:       str   # supergfx name e.g. "Hybrid"
    bat_limit: int   # 20-100


_SETTINGS_KEY = "user_profiles_v1"


class ProfileManager:
    """Thin wrapper around QSettings storing profiles as a JSON object."""

    def __init__(self) -> None:
        self._s = QSettings("asus-helper", "asus-helper")

    # ── persistence helpers ──────────────────────────────────────────────

    def _load_all(self) -> dict:
        raw = self._s.value(_SETTINGS_KEY, "{}")
        try:
            return json.loads(raw)
        except Exception:
            return {}

    def _save_all(self, data: dict) -> None:
        self._s.setValue(_SETTINGS_KEY, json.dumps(data, ensure_ascii=False))

    # ── public API ───────────────────────────────────────────────────────

    def list_names(self) -> list[str]:
        return sorted(self._load_all().keys())

    def get(self, name: str) -> Optional[Profile]:
        d = self._load_all().get(name)
        if d is None:
            return None
        return Profile(
            name      = name,
            perf      = d.get("perf", "Balanced"),
            gpu       = d.get("gpu",  "Hybrid"),
            bat_limit = int(d.get("bat", 100)),
        )

    def save(self, profile: Profile) -> None:
        data = self._load_all()
        data[profile.name] = {
            "perf": profile.perf,
            "gpu":  profile.gpu,
            "bat":  profile.bat_limit,
        }
        self._save_all(data)

    def delete(self, name: str) -> None:
        data = self._load_all()
        data.pop(name, None)
        self._save_all(data)

    def rename(self, old: str, new: str) -> None:
        data = self._load_all()
        if old in data and new:
            data[new] = data.pop(old)
            self._save_all(data)

    # ── snapshot helper ──────────────────────────────────────────────────

    @staticmethod
    def snapshot_current(name: str) -> Optional[Profile]:
        """Read the live system state and build a Profile from it."""
        try:
            perf = backend.get_profile()
        except backend.BackendError:
            perf = "Balanced"
        try:
            gpu = backend.get_gpu_mode()
        except backend.BackendError:
            gpu = "Hybrid"
        try:
            bat = backend.read_charge_limit()
        except Exception:
            bat = 100
        return Profile(name=name, perf=perf, gpu=gpu, bat_limit=bat)

    @staticmethod
    def summary(profile: Profile) -> str:
        """One-line human-readable description of a profile."""
        perf_label = backend.ASUSCTL_TO_PROFILE_LABEL.get(profile.perf, profile.perf)
        gpu_label  = backend.SUPERGFX_TO_GPU_LABEL.get(profile.gpu,  profile.gpu)
        return f"{perf_label}  ·  {gpu_label}  ·  Bat {profile.bat_limit}%"
