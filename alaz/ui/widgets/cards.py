"""SectionHeader, PendingCard, Banner, SensorPanel."""
from __future__ import annotations

from PyQt6.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from alaz.i18n import tr
from alaz.ui import theme
from alaz.ui.widgets._common import AccentMixin, IconButton, make_button
from alaz.ui.power_text import PowerView, compose_power, source_text
from alaz.ui.widgets.icons import draw_icon, icon_pixmap

DASH = "—"


class _IconLabel(QWidget):
    def __init__(self, name: str, color: str, px: int = 15, stroke: float = 2.2, parent: QWidget | None = None):
        super().__init__(parent)
        self._name, self._color, self._px, self._stroke = name, color, px, stroke
        self.setFixedSize(px, px)

    def set_color(self, color: str) -> None:
        self._color = color
        QWidget.update(self)

    def set_icon(self, name: str) -> None:
        self._name = name
        QWidget.update(self)

    def paintEvent(self, e):
        p = QPainter(self)
        draw_icon(p, self._name, QRectF(0, 0, self._px, self._px), self._color, self._stroke)


class SectionHeader(QWidget, AccentMixin):
    """Accent icon + uppercase letter-spaced title + right-aligned rich-text value (use `strong()` for bold bits)."""

    def __init__(self, icon: str, title: str, value_html: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self._icon = _IconLabel(icon, self._accent, 15, 2.2)
        self._title = QLabel(title.upper())
        self._title.setFont(theme.ui_font(11.5, 600, 1.15))
        self._title.setStyleSheet(f"color:{theme.TEXT2}; background:transparent")
        self._value = QLabel(value_html)
        self._value.setTextFormat(Qt.TextFormat.RichText)
        self._value.setStyleSheet(f"font-size:12px; color:{theme.TEXT3}; background:transparent")
        lay.addWidget(self._icon)
        lay.addWidget(self._title)
        lay.addStretch(1)
        lay.addWidget(self._value)
        self.setFixedHeight(20)

    def set_value(self, html: str) -> None:
        self._value.setText(html)

    def set_title(self, title: str) -> None:
        self._title.setText(title.upper())

    def _accent_changed(self) -> None:
        self._icon.set_color(self._accent)


class _Frame(QWidget):
    """Rounded panel painted by hand (solid or dashed border)."""

    def __init__(self, bg: str, border: str, radius: float, dashed: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self._bg, self._border, self._radius, self._dashed = bg, border, radius, dashed

    def set_colors(self, bg: str | None = None, border: str | None = None) -> None:
        self._bg = bg or self._bg
        self._border = border or self._border
        QWidget.update(self)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(self._border), 1)
        if self._dashed:
            pen.setStyle(Qt.PenStyle.CustomDashLine)
            pen.setDashPattern([4, 3])
        p.setPen(pen)
        p.setBrush(QColor(self._bg))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), self._radius, self._radius)


def _text_block(title_color: str = theme.TEXT, title_px: float = 12.5, sub_color: str = theme.TEXT2,
                sub_px: float = 12):
    box = QWidget()
    box.setStyleSheet("background:transparent")
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(1)
    t, s = QLabel(), QLabel()
    t.setStyleSheet(f"font-size:{title_px}px; font-weight:600; color:{title_color}; background:transparent")
    s.setStyleSheet(f"font-size:{sub_px}px; color:{sub_color}; background:transparent")
    for w in (t, s):
        w.setWordWrap(True)
        w.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    lay.addWidget(t)
    lay.addWidget(s)
    return box, t, s


class PendingCard(_Frame, AccentMixin):
    """Dashed card "X yeniden başlatınca etkin olacak" with [Yeniden başlat] [İptal]."""

    rebootClicked = pyqtSignal()
    cancelClicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(theme.PANEL, self._accent, 10, dashed=True, parent=parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 10, 10)
        lay.setSpacing(10)
        self._icon = _IconLabel("refresh", self._accent, 18, 2.0)
        lay.addWidget(self._icon)
        box, self._title, self._sub = _text_block()
        lay.addWidget(box, 1)
        self._reboot = make_button(tr("Yeniden başlat"), "primary", self._accent, 34, 12)
        self._cancel = make_button(tr("İptal"), "ghost", height=34, pad=12)
        self._reboot.clicked.connect(self.rebootClicked)
        self._cancel.clicked.connect(self.cancelClicked)
        lay.addWidget(self._reboot)
        lay.addWidget(self._cancel)

    def set_content(self, title: str, sub: str) -> None:
        self._title.setText(title)
        self._sub.setText(sub)

    def set_reboot_enabled(self, on: bool) -> None:
        self._reboot.setEnabled(on)

    def set_urgent(self, on: bool) -> None:
        """Warning tone: reboot is required (no way to cancel)."""
        self._cancel.setVisible(not on)
        self._icon.set_icon("warning" if on else "refresh")

    def set_color(self, hex_color: str) -> None:
        self.set_accent(hex_color)

    def _accent_changed(self) -> None:
        self._icon.set_color(self._accent)
        self.set_colors(border=self._accent)
        self._reboot.setStyleSheet(make_button("", "primary", self._accent).styleSheet())


class Banner(_Frame):
    """Amber warning banner with an action button and a close button."""

    actionClicked = pyqtSignal()
    closed = pyqtSignal()

    def __init__(self, title: str = "", sub: str = "", action_text: str = "", parent: QWidget | None = None):
        super().__init__(theme.WARN_BG, theme.WARN_BORDER, 10, parent=parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 9, 8, 9)
        lay.setSpacing(10)
        lay.addWidget(_IconLabel("warning", theme.WARN_ACCENT, 18, 2.0))
        box, self._title, self._sub = _text_block(theme.WARN_TEXT, 12.5, theme.WARN_SUB, 12)
        lay.addWidget(box, 1)
        self._action = make_button(action_text or tr("Düzelt"), "primary", theme.WARN_ACCENT, 32, 14)
        self._action.clicked.connect(self.actionClicked)
        lay.addWidget(self._action)
        self._close = IconButton("close", (32, 32), 14, theme.WARN_SUB, tooltip=tr("Uyarıyı kapat"))
        self._close.clicked.connect(self.closed)
        lay.addWidget(self._close)
        self.set_content(title, sub)

    def set_content(self, title: str, sub: str = "") -> None:
        self._title.setText(title)
        self._sub.setText(sub)
        self._sub.setVisible(bool(sub))

    def set_action_text(self, text: str) -> None:
        self._action.setText(text)

    def set_action_visible(self, on: bool) -> None:
        self._action.setVisible(on)

    def set_accent(self, hex_color: str) -> None:  # banner is always amber
        pass


class _Bar(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._frac: float | None = None
        self._color = theme.DEFAULT_ACCENT
        self.setFixedHeight(4)

    def set_state(self, frac: float | None, color: str) -> None:
        self._frac, self._color = (None if frac is None else max(0.0, min(1.0, frac))), color
        QWidget.update(self)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.BORDER))
        p.drawRoundedRect(QRectF(self.rect()), 2, 2)
        if self._frac:
            p.setBrush(QColor(self._color))
            p.drawRoundedRect(QRectF(0, 0, max(4.0, self.width() * self._frac), 4), 2, 2)


class _Stat(QWidget):
    """One column of the hero card: title, big value, bar, sub text."""

    def __init__(self, title: str, left: int, right: int, parent: QWidget | None = None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(left, 14, right, 12)
        lay.setSpacing(6)
        t = QLabel(title)
        t.setFont(theme.ui_font(11, 600, 1.1))
        t.setStyleSheet(f"color:{theme.TEXT3}; background:transparent")
        lay.addWidget(t)
        self.value_row = QHBoxLayout()
        self.value_row.setContentsMargins(0, 0, 0, 0)
        self.value_row.setSpacing(2)
        holder = QWidget()
        holder.setFixedHeight(32)
        holder.setLayout(self.value_row)
        lay.addWidget(holder)
        self.bar = _Bar()
        lay.addWidget(self.bar)
        self.sub = QLabel()
        self.sub.setStyleSheet(f"font-size:12px; color:{theme.TEXT2}; background:transparent")
        lay.addWidget(self.sub)
        self.big = QLabel(DASH)
        self.big.setFont(theme.ui_font(32, 600))
        self.big.setStyleSheet("background:transparent")
        self.unit = QLabel("")
        self.unit.setStyleSheet(f"font-size:16px; color:{theme.TEXT2}; background:transparent")
        self.icon = _IconLabel("moon", theme.TEXT2, 20, 2.0)
        self.icon.setVisible(False)
        self.value_row.addWidget(self.icon)
        self.value_row.addSpacing(5)
        self.value_row.addWidget(self.big, 0, Qt.AlignmentFlag.AlignBottom)
        self.value_row.addWidget(self.unit, 0, Qt.AlignmentFlag.AlignBottom)
        self.value_row.addStretch(1)

    def set_value(self, big: str, unit: str = "", unit_px: float = 16, big_px: float = 32, icon: str | None = None):
        self.big.setFont(theme.ui_font(big_px, 600))
        self.big.setText(big)
        self.unit.setText(unit)
        self.unit.setStyleSheet(f"font-size:{unit_px}px; color:{theme.TEXT2}; background:transparent;"
                                "padding-bottom:3px")
        self.icon.setVisible(icon is not None)
        if icon:
            self.icon.set_icon(icon)


_BATT = {"Charging": "Şarj oluyor", "Discharging": "Boşalıyor", "Full": "Dolu", "Not charging": "Şarj durdu"}


class SensorPanel(QWidget, AccentMixin):
    """The hero card: CPU / GPU / FAN columns plus the RAM - Pil - Prizde strip."""

    FAN_MAX_RPM = 6000.0

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._cpu_model = ""
        self._smoother = PowerView(5)
        root = QVBoxLayout(self)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)
        cols = QWidget()
        self._cols = cols
        grid = QHBoxLayout(cols)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)
        self._cpu = _Stat("CPU", 16, 14)
        self._gpu = _Stat("GPU", 14, 14)
        self._fan = _Stat(tr("FANLAR"), 14, 16)
        for w in (self._cpu, self._gpu, self._fan):
            grid.addWidget(w, 1)
        root.addWidget(cols)
        strip = QWidget()
        self._strip = strip
        sl = QHBoxLayout(strip)
        sl.setContentsMargins(16, 9, 16, 9)
        sl.setSpacing(14)
        self._ram = QLabel()
        self._bat = QLabel()
        for w in (self._ram, self._bat):
            w.setTextFormat(Qt.TextFormat.RichText)
            w.setStyleSheet(f"font-size:12px; color:{theme.TEXT2}; background:transparent")
        self._ac_icon = _IconLabel("plug", theme.TEXT2, 13, 2.0)
        self._ac = QLabel()
        self._ac.setTextFormat(Qt.TextFormat.RichText)
        self._ac.setStyleSheet(f"font-size:12px; color:{theme.TEXT2}; background:transparent")
        sl.addWidget(self._ram)
        sl.addWidget(self._bat)
        sl.addStretch(1)
        sl.addWidget(self._ac_icon)
        sl.addSpacing(-9)
        sl.addWidget(self._ac)
        root.addWidget(strip)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.update()  # no args -> repaint
        self._apply(None, None, None, None, None, None, None, None, None, None, None, None)

    def set_cpu_model(self, model: str) -> None:
        self._cpu_model = model

    # `update()` with no args behaves like QWidget.update(); with args it sets the sensor values.
    def update(self, *args, **kwargs):  # type: ignore[override]
        if not args and not kwargs:
            QWidget.update(self)
            return
        self._apply(*self._bind(*args, **kwargs))

    set_values = update

    @staticmethod
    def _bind(cpu_temp=None, cpu_load=None, gpu_state=None, gpu_temp=None, gpu_load=None, gpu_power_w=None,
              fans=None, ram_pct=None, battery_pct=None, battery_status=None, on_ac=None, battery_power_w=None,
              system_power_w=None):
        return (cpu_temp, cpu_load, gpu_state, gpu_temp, gpu_load, gpu_power_w, fans, ram_pct, battery_pct,
                battery_status, on_ac, battery_power_w, system_power_w)

    def _apply(self, cpu_temp, cpu_load, gpu_state, gpu_temp, gpu_load, gpu_power_w, fans, ram_pct, battery_pct,
               battery_status, on_ac, battery_power_w=None, system_power_w=None) -> None:
        a = self._accent
        # CPU
        self._cpu.set_value(DASH if cpu_temp is None else f"{cpu_temp:.0f}", "" if cpu_temp is None else "°C")
        self._cpu.bar.set_state(None if cpu_load is None else cpu_load / 100, a)
        parts = [tr("{value} % yük", value=DASH if cpu_load is None else f"{cpu_load:.0f}")]
        if self._cpu_model:
            parts.append(self._cpu_model)
        self._cpu.sub.setText(" · ".join(parts))
        # GPU
        if gpu_state == "sleep":
            self._gpu.set_value(tr("Uyku"), big_px=22, icon="moon")
            self._gpu.bar.set_state(None, a)
            self._gpu.sub.setText(tr("dGPU kapalı") + ("" if gpu_power_w is None else f" · {gpu_power_w:.0f} W"))
        elif gpu_state == "off":
            self._gpu.set_value(tr("Kapalı"), big_px=22, icon="moon")
            self._gpu.bar.set_state(None, a)
            self._gpu.sub.setText(tr("dGPU devre dışı"))
        elif gpu_state == "active":
            self._gpu.set_value(DASH if gpu_temp is None else f"{gpu_temp:.0f}", "" if gpu_temp is None else "°C")
            self._gpu.bar.set_state(None if gpu_load is None else gpu_load / 100, a)
            sub = tr("{value} % yük", value=DASH if gpu_load is None else f"{gpu_load:.0f}")
            sub += f" · {DASH} W" if gpu_power_w is None else f" · {gpu_power_w:.0f} W"
            self._gpu.sub.setText(sub)
        else:
            self._gpu.set_value(DASH, big_px=22)
            self._gpu.bar.set_state(None, a)
            self._gpu.sub.setText("")
        # fans
        fans = fans or {}
        cpu_rpm = fans.get("cpu")
        self._fan.set_value(DASH if cpu_rpm is None else f"{cpu_rpm:.0f}", "" if cpu_rpm is None else "rpm", 13)
        self._fan.bar.set_state(None if cpu_rpm is None else cpu_rpm / self.FAN_MAX_RPM, a)
        g, m = fans.get("gpu"), fans.get("mid")
        self._fan.sub.setText(f"GPU {DASH if g is None else int(g)} · MID {DASH if m is None else int(m)}")
        # bottom row
        self._ram.setText(f"RAM {strong_(DASH if ram_pct is None else f'{ram_pct:.0f} %')}")
        sys_w, chg_w = self._smoother.push(system_power_w, battery_power_w, battery_status)
        pil = tr("Pil {value}", value=strong_(DASH if battery_pct is None else f"{battery_pct:.0f} %"))
        if battery_status and chg_w is None:  # "Şarj +M W" already says it is charging; keep the row short
            pil += f" · {tr(_BATT.get(battery_status, battery_status))}"
        self._bat.setText(pil)
        self._ac_icon.setVisible(on_ac is not None)
        self._ac_icon.set_icon("plug" if on_ac else "battery")
        src, ptxt = source_text(on_ac), compose_power(sys_w, chg_w)
        self._ac.setText(" · ".join(p for p in (src, strong_(ptxt) if ptxt else None) if p))
        self._last = (cpu_temp, cpu_load, gpu_state)

    def _accent_changed(self) -> None:
        for s in (self._cpu, self._fan, self._gpu):
            s.bar.set_state(s.bar._frac, self._accent)

    def sizeHint(self) -> QSize:
        return QSize(448, 150)

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        clip = QPainterPath()
        clip.addRoundedRect(r, 14, 14)
        p.save()
        p.setClipPath(clip)
        p.fillRect(self.rect(), QColor(theme.PANEL))
        p.fillRect(self._strip.geometry(), QColor(theme.PANEL_DARK))
        p.setPen(QPen(QColor(theme.DIVIDER), 1))
        y = self._strip.geometry().top()
        p.drawLine(0, y, self.width(), y)
        top, bot = self._cols.geometry().top(), self._cols.geometry().bottom()
        p.drawLine(self._gpu.geometry().left() + self._cols.geometry().left(), top,
                   self._gpu.geometry().left() + self._cols.geometry().left(), bot)
        p.drawLine(self._fan.geometry().left() + self._cols.geometry().left() - 1, top,
                   self._fan.geometry().left() + self._cols.geometry().left() - 1, bot)
        p.restore()
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, 14, 14)


def strong_(text: str) -> str:
    return f'<b style="color:{theme.TEXT}; font-weight:600">{text}</b>'
