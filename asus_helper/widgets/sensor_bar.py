"""Always-on sensor strip — mirrors the HTML .sbar / .sbar-it structure."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..sensors import SensorSnapshot
from ..theme import TX, TX2, TX3, WARN

_HOT_THRESHOLD = 72   # °C — matches HTML `s.cpuTemp > 72`


def _fmt(value, suffix: str = "", fallback: str = "—") -> str:
    if value is None:
        return fallback
    return f"{round(value)}{suffix}"


class _Item(QWidget):
    """One vertical chip: value on top, small ALL-CAPS label below."""

    def __init__(self, caption: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 8, 4, 8)
        lay.setSpacing(3)

        self._val = QLabel("—")
        self._val.setAlignment(Qt.AlignCenter)
        self._val.setStyleSheet(
            f"font-size:11.5px; font-weight:600; color:{TX}; "
            "letter-spacing:-0.2px; white-space:nowrap; background:transparent;"
        )

        cap = QLabel(caption)
        cap.setAlignment(Qt.AlignCenter)
        cap.setStyleSheet(
            f"font-size:8.5px; font-weight:600; color:{TX3}; "
            "text-transform:uppercase; letter-spacing:0.8px; background:transparent;"
        )

        lay.addWidget(self._val)
        lay.addWidget(cap)

    def set(self, text: str, hot: bool = False) -> None:
        self._val.setText(text)
        color = WARN if hot else TX
        self._val.setStyleSheet(
            f"font-size:11.5px; font-weight:600; color:{color}; "
            "letter-spacing:-0.2px; white-space:nowrap; background:transparent;"
        )


class SensorBar(QFrame):
    """Six-cell sensor strip pinned above the tab widget."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SensorBar")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._cpu    = _Item("CPU")
        self._gpu    = _Item("GPU")
        self._gpu_w  = _Item("GPU W")
        self._ram    = _Item("RAM")
        self._fan    = _Item("FAN RPM")
        self._bat    = _Item("BAT")

        items = [self._cpu, self._gpu, self._gpu_w, self._ram, self._fan, self._bat]
        for i, item in enumerate(items):
            if i:
                sep = QFrame()
                sep.setFrameShape(QFrame.VLine)
                sep.setFixedWidth(1)
                sep.setStyleSheet("background:#1f1f2c; border:none;")
                lay.addWidget(sep)
            # FAN column is wider (holds three numbers)
            lay.addWidget(item, 2 if item is self._fan else 1)

    def update_snapshot(self, snap: SensorSnapshot) -> None:
        cpu_t = snap.cpu_temp
        hot   = cpu_t is not None and cpu_t > _HOT_THRESHOLD

        cpu_str = f"{_fmt(cpu_t, '°')} · {_fmt(snap.cpu_pct, '%')}"
        self._cpu.set(cpu_str, hot=hot)

        gpu_str = f"{_fmt(snap.gpu_temp, '°')} · {_fmt(snap.gpu_util, '%')}"
        self._gpu.set(gpu_str)
        self._gpu_w.set(_fmt(snap.gpu_power_w, " W"))
        self._ram.set(_fmt(snap.ram_pct, "%"))

        fans = snap.fan_rpm or {}
        if fans:
            fan_str = "/".join(
                str(fans[k]) if k in fans else "—"
                for k in ("cpu", "gpu", "mid")
            )
        else:
            fan_str = "—"
        self._fan.set(fan_str)

        if snap.battery_pct is None:
            self._bat.set("—")
        else:
            status = (snap.battery_status or "").lower()
            if "charging" in status and "not" not in status:
                icon = " ⚡"      # actively charging
            elif snap.battery_plugged:
                icon = " ·"      # plugged but full / at limit
            else:
                icon = ""        # on battery
            self._bat.set(f"{round(snap.battery_pct)}%{icon}")

    @staticmethod
    def tooltip_text(snap: SensorSnapshot) -> str:
        lines = ["ASUS Helper"]
        lines.append(
            f"CPU  {_fmt(snap.cpu_temp, '°C')}  {_fmt(snap.cpu_pct, '%')}"
        )
        lines.append(
            f"GPU  {_fmt(snap.gpu_temp, '°C')}  {_fmt(snap.gpu_util, '%')}  {_fmt(snap.gpu_power_w, ' W')}"
        )
        lines.append(
            f"RAM  {_fmt(snap.ram_pct, '%')}  ({_fmt(snap.ram_used_gb, ' GB')})"
        )
        fans = snap.fan_rpm or {}
        if fans:
            lines.append("Fans  " + "  ".join(f"{k}={v}" for k, v in fans.items()))
        if snap.battery_pct is not None:
            st = (snap.battery_status or "").lower()
            if "charging" in st and "not" not in st:
                state = "charging"
            elif snap.battery_plugged:
                state = "plugged · not charging"
            else:
                state = "on battery"
            lines.append(f"BAT  {round(snap.battery_pct)}%  ({state})")
        return "\n".join(lines)
