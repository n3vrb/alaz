"""FanCurveChart — 8-point editable fan curve (X 20-100 degC, Y 0-100 %)."""
from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics, QLinearGradient, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QSizePolicy, QWidget

from alaz.i18n import tr
from alaz.ui import theme
from alaz.ui.widgets._common import AccentMixin

T_MIN, T_MAX = 20, 100
SENTINEL = 255


def _disp(t: int) -> int:
    """Temperature as drawn: clamped into the X range (255 'above' sentinel -> 100)."""
    return max(T_MIN, min(T_MAX, int(t)))


class FanCurveChart(QWidget, AccentMixin):
    edited = pyqtSignal()
    selectionChanged = pyqtSignal(int)

    ML, MR, MT, MB = 40, 14, 20, 36  # plot margins, taken from the 454x236 SVG

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._pts: list[list[int]] = []
        self._sel = 0
        self._cur_temp: float | None = None
        self._editable = True
        self._drag = False
        self._moved = False
        self.setMinimumSize(300, 190)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAccessibleName(tr("Fan eğrisi"))

    # ---- API ------------------------------------------------------------
    def set_points(self, points) -> None:
        self._pts = [[int(t), max(0, min(100, int(p)))] for t, p in points]
        self._sel = min(self._sel, max(0, len(self._pts) - 1))
        QWidget.update(self)

    def points(self) -> list[tuple[int, int]]:
        return [(t, p) for t, p in self._pts]

    def set_current_temp(self, t: float | None) -> None:
        self._cur_temp = t
        QWidget.update(self)

    def set_editable(self, on: bool) -> None:
        self._editable = bool(on)
        self._drag = False
        self.setCursor(Qt.CursorShape.ArrowCursor)
        QWidget.update(self)

    def is_editable(self) -> bool:
        return self._editable

    def selected_index(self) -> int:
        return self._sel

    def set_selected(self, i: int) -> None:
        if self._pts and 0 <= i < len(self._pts) and i != self._sel:
            self._sel = i
            self.selectionChanged.emit(i)
            QWidget.update(self)

    def sizeHint(self) -> QSize:
        return QSize(454, 236)

    # ---- geometry ---------------------------------------------------------
    def _plot(self) -> QRectF:
        return QRectF(self.ML, self.MT, self.width() - self.ML - self.MR, self.height() - self.MT - self.MB)

    def _x(self, t: float) -> float:
        r = self._plot()
        return r.left() + (max(T_MIN, min(T_MAX, t)) - T_MIN) / (T_MAX - T_MIN) * r.width()

    def _y(self, pct: float) -> float:
        r = self._plot()
        return r.top() + (100 - pct) / 100 * r.height()

    def _pos(self, i: int) -> QPointF:
        return QPointF(self._x(_disp(self._pts[i][0])), self._y(self._pts[i][1]))

    def _hit(self, pos: QPointF) -> int:
        best, bd = -1, 14.0 ** 2
        for i in range(len(self._pts)):
            c = self._pos(i)
            d = (c.x() - pos.x()) ** 2 + (c.y() - pos.y()) ** 2
            if d <= bd:
                best, bd = i, d
        return best

    # ---- editing ----------------------------------------------------------
    def _bounds(self, i: int) -> tuple[int, int]:
        lo = _disp(self._pts[i - 1][0]) + 1 if i > 0 else T_MIN
        hi = _disp(self._pts[i + 1][0]) - 1 if i < len(self._pts) - 1 else T_MAX
        return lo, hi

    def _set_point(self, i: int, temp: int | None, pct: int | None) -> bool:
        changed = False
        if temp is not None:
            lo, hi = self._bounds(i)
            if lo <= hi:
                new = max(lo, min(hi, temp))
                # keep the raw value (255 / 0) while the drawn position is unchanged
                if new != _disp(self._pts[i][0]):
                    self._pts[i][0] = new
                    changed = True
        if pct is not None:
            new = max(0, min(100, pct))
            if new != self._pts[i][1]:
                self._pts[i][1] = new
                changed = True
        if changed:
            QWidget.update(self)
        return changed

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton or not self._pts:
            return
        i = self._hit(e.position())
        if i < 0:
            return
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self.set_selected(i)
        if self._editable:
            self._drag, self._moved = True, False
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if self._drag and self._pts:
            r = self._plot()
            t = round(T_MIN + (e.position().x() - r.left()) / r.width() * (T_MAX - T_MIN))
            pct = round(100 - (e.position().y() - r.top()) / r.height() * 100)
            if self._set_point(self._sel, t, pct):
                self._moved = True
        elif self._editable and self._pts:
            self.setCursor(Qt.CursorShape.OpenHandCursor if self._hit(e.position()) >= 0
                           else Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, e):
        if self._drag:
            self._drag = False
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            if self._moved:
                self._moved = False
                self.edited.emit()

    def keyPressEvent(self, e):
        k = e.key()
        if not self._pts:
            return super().keyPressEvent(e)
        if k in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down) and self._editable:
            i = self._sel
            if k == Qt.Key.Key_Left:
                ch = self._set_point(i, _disp(self._pts[i][0]) - 1, None)
            elif k == Qt.Key.Key_Right:
                ch = self._set_point(i, _disp(self._pts[i][0]) + 1, None)
            elif k == Qt.Key.Key_Up:
                ch = self._set_point(i, None, self._pts[i][1] + 1)
            else:
                ch = self._set_point(i, None, self._pts[i][1] - 1)
            if ch:
                self.edited.emit()
        else:
            super().keyPressEvent(e)

    def focusNextPrevChild(self, nxt: bool) -> bool:
        """Tab / Shift+Tab walk through the points; past the first/last point focus leaves the chart."""
        if self.hasFocus() and self._pts:
            j = self._sel + (1 if nxt else -1)
            if 0 <= j < len(self._pts):
                self.set_selected(j)
                return True
        return super().focusNextPrevChild(nxt)

    def focusInEvent(self, e):
        QWidget.update(self)
        super().focusInEvent(e)

    def focusOutEvent(self, e):
        QWidget.update(self)
        super().focusOutEvent(e)

    # ---- paint --------------------------------------------------------------
    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self._plot()
        accent = QColor(self._accent)
        # grid
        p.setPen(QPen(QColor(theme.DIVIDER), 1))
        for v in (100, 75, 50, 25):
            y = round(self._y(v)) + 0.5
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
        for t in (20, 40, 60, 80, 100):
            x = round(self._x(t)) + 0.5
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
        p.setPen(QPen(QColor(theme.GRID_AXIS), 1))
        y0 = round(r.bottom()) + 0.5
        p.drawLine(QPointF(r.left(), y0), QPointF(r.right(), y0))
        # labels
        p.setFont(theme.ui_font(11, 400))
        p.setPen(QColor(theme.TEXT3))
        for v in (100, 75, 50, 25, 0):
            p.drawText(QRectF(0, self._y(v) - 8, self.ML - 8, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, str(v))
        for t in (20, 40, 60, 80, 100):
            p.drawText(QRectF(self._x(t) - 20, r.bottom() + 6, 40, 14), Qt.AlignmentFlag.AlignCenter, str(t))
        p.drawText(QRectF(r.right() - 120, self.height() - 16, 120, 14), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, tr("Sıcaklık °C"))
        p.drawText(QRectF(4, 0, 80, 14), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, tr("Fan %"))
        # current temperature
        if self._cur_temp is not None:
            x = round(self._x(self._cur_temp)) + 0.5
            c = QColor(theme.TEXT)
            c.setAlphaF(0.6)
            pen = QPen(c, 1, Qt.PenStyle.CustomDashLine)
            pen.setDashPattern([3, 4])
            p.setPen(pen)
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            txt = tr("Şu an {t}°", t=f"{self._cur_temp:.0f}")
            f = theme.ui_font(11, 600)
            p.setFont(f)
            w = QFontMetrics(f).horizontalAdvance(txt) + 16
            px = max(r.left(), min(r.right() - w, x - w / 2))
            pill = QRectF(px, r.top() + 4, w, 18)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.BORDER))
            p.drawRoundedRect(pill, 9, 9)
            p.setPen(QColor(theme.TEXT))
            p.drawText(pill, Qt.AlignmentFlag.AlignCenter, txt)
        if not self._pts:
            return
        pts = [self._pos(i) for i in range(len(self._pts))]
        # area
        grad = QLinearGradient(0, r.top(), 0, r.bottom())
        top_c, bot_c = QColor(accent), QColor(accent)
        top_c.setAlphaF(0.28)
        bot_c.setAlphaF(0.02)
        grad.setColorAt(0, top_c)
        grad.setColorAt(1, bot_c)
        poly = QPolygonF(pts + [QPointF(pts[-1].x(), r.bottom()), QPointF(pts[0].x(), r.bottom())])
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawPolygon(poly)
        # line
        pen = QPen(accent, 2.5)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolyline(QPolygonF(pts))
        # points
        for i, c in enumerate(pts):
            on = i == self._sel
            rad = 7 if on else 5
            p.setPen(QPen(accent, 2))
            p.setBrush(accent if on else QColor(theme.BG))
            p.drawEllipse(c, rad, rad)
        if self.hasFocus():
            p.setPen(QPen(QColor(theme.TEXT), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(pts[self._sel], 10, 10)
        # tooltip box
        t, pct = self._pts[self._sel]
        ttxt = f"{'100+' if t >= 100 else t}° → {pct}%"
        tf = theme.ui_font(11.5, 700)
        p.setFont(tf)
        tw = max(72, QFontMetrics(tf).horizontalAdvance(ttxt) + 16)
        sp = pts[self._sel]
        tx = max(r.left() + 2, min(r.right() - tw - 2, sp.x() - tw / 2))
        ty = sp.y() + 12 if sp.y() - 34 < 22 else sp.y() - 34
        box = QRectF(tx, ty, tw, 22)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(accent)
        p.drawRoundedRect(box, 6, 6)
        p.setPen(QColor(theme.INK))
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, ttxt)
