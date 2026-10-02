"""Stroke icons from the mockups (24x24 viewBox), drawn with QPainterPath (QtSvg is not installed)."""
from __future__ import annotations

import math
import re
from functools import lru_cache

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap

PATHS: dict[str, str] = {
    "logo": "M3 17l6-10 4 6 2-3 6 7",
    "moon": "M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z",
    "gauge": "M4 16a8 8 0 1 1 16 0M12 16l4-5",
    "bolt": "M13 2L4 14h7l-1 8 9-12h-7z",
    "sliders": "M4 7h10M18 7h2M4 17h2M10 17h10M14 5v4M6 15v4",
    "leaf": "M5 19c0-9 5-14 15-14 0 9-5 14-13 14M5 19l8-8",
    "layers": "M12 3l9 5-9 5-9-5zM3 13l9 5 9-5",
    "chip": "M7 7h10v10H7zM10 3v4M14 3v4M10 17v4M14 17v4M3 10h4M3 14h4M17 10h4M17 14h4",
    "refresh": "M20 11a8 8 0 0 0-14-4M4 4v4h4M4 13a8 8 0 0 0 14 4M20 20v-4h-4",
    "monitor": "M3 5h18v12H3zM8 21h8M12 17v4",
    "battery": "M3 8h15v8H3zM18 11h3v2h-3z",
    "plug": "M9 2v6M15 2v6M6 8h12v4a6 6 0 0 1-12 0zM12 18v4",
    "warning": "M12 3l10 18H2z M12 10v5M12 18v.5",
    "shield": "M12 3l8 4v5c0 5-3.5 8-8 9-4.5-1-8-4-8-9V7z",
    "check": "M5 12l5 5 9-10",
    "close": "M6 6l12 12M18 6L6 18",
    "minimize": "M5 12h14",
    "back": "M15 6l-6 6 6 6",
    "chevron_down": "M6 9l6 6 6-6",
    "fan": "M12 12m-2 0a2 2 0 1 0 4 0a2 2 0 1 0-4 0M12 10c0-6-6-6-6-3s4 3 6 3M14 12c6 0 6 6 3 6s-3-4-3-6M12 14c0 6 6 6 6 3s-4-3-6-3M10 12c-6 0-6-6-3-6s3 4 3 6",
    "keyboard": "M3 8h18v9H3zM7 12h.5M11 12h.5M15 12h.5M7 15h10",
    "settings": "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z",
    "expand": "M4 14h6v6M20 10h-6V4M14 10l7-7M3 21l7-7",
}

_NUM = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_TOKEN = re.compile(r"([MmLlHhVvCcSsAaZz])|([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)")


def _arc(path: QPainterPath, x1, y1, rx, ry, phi_deg, fa, fs, x2, y2) -> None:
    if rx == 0 or ry == 0 or (x1 == x2 and y1 == y2):
        path.lineTo(x2, y2)
        return
    rx, ry = abs(rx), abs(ry)
    phi = math.radians(phi_deg)
    cp, sp = math.cos(phi), math.sin(phi)
    dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
    x1p, y1p = cp * dx + sp * dy, -sp * dx + cp * dy
    lam = x1p ** 2 / rx ** 2 + y1p ** 2 / ry ** 2
    if lam > 1:
        s = math.sqrt(lam)
        rx, ry = rx * s, ry * s
    num = rx ** 2 * ry ** 2 - rx ** 2 * y1p ** 2 - ry ** 2 * x1p ** 2
    den = rx ** 2 * y1p ** 2 + ry ** 2 * x1p ** 2
    co = math.sqrt(max(0.0, num / den)) * (-1 if fa == fs else 1)
    cxp, cyp = co * rx * y1p / ry, -co * ry * x1p / rx
    cx = cp * cxp - sp * cyp + (x1 + x2) / 2
    cy = sp * cxp + cp * cyp + (y1 + y2) / 2

    def ang(ux, uy, vx, vy):
        a = math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
        return a

    th1 = ang(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dth = ang((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not fs and dth > 0:
        dth -= 2 * math.pi
    elif fs and dth < 0:
        dth += 2 * math.pi
    n = max(1, int(math.ceil(abs(dth) / (math.pi / 2))))
    d = dth / n
    t = 4 / 3 * math.tan(d / 4)
    a = th1
    for _ in range(n):
        ca, sa, cb, sb = math.cos(a), math.sin(a), math.cos(a + d), math.sin(a + d)
        p1 = (ca - t * sa, sa + t * ca)
        p2 = (cb + t * sb, sb - t * cb)
        p3 = (cb, sb)

        def tr(p):
            x, y = p[0] * rx, p[1] * ry
            return cp * x - sp * y + cx, sp * x + cp * y + cy

        e1, e2, e3 = tr(p1), tr(p2), tr(p3)
        path.cubicTo(e1[0], e1[1], e2[0], e2[1], e3[0], e3[1])
        a += d


@lru_cache(maxsize=None)
def parse_path(d: str) -> QPainterPath:
    path = QPainterPath()
    toks = _TOKEN.findall(d)
    i = 0
    cmd = ""
    x = y = sx = sy = 0.0
    lcx = lcy = None  # last cubic control point, for S

    def nums(n):
        nonlocal i
        vals = []
        for _ in range(n):
            while toks[i][1] == "":
                i += 1
            vals.append(float(toks[i][1]))
            i += 1
        return vals

    while i < len(toks):
        if toks[i][0]:
            cmd = toks[i][0]
            i += 1
            if cmd in "Zz":
                path.closeSubpath()
                x, y = sx, sy
                continue
        elif cmd in "Mm":
            cmd = "L" if cmd == "M" else "l"
        rel = cmd.islower()
        c = cmd.upper()
        if c == "M":
            a, b = nums(2)
            x, y = (x + a, y + b) if rel else (a, b)
            sx, sy = x, y
            path.moveTo(x, y)
            lcx = None
        elif c == "L":
            a, b = nums(2)
            x, y = (x + a, y + b) if rel else (a, b)
            path.lineTo(x, y)
            lcx = None
        elif c == "H":
            (a,) = nums(1)
            x = x + a if rel else a
            path.lineTo(x, y)
            lcx = None
        elif c == "V":
            (b,) = nums(1)
            y = y + b if rel else b
            path.lineTo(x, y)
            lcx = None
        elif c in "CS":
            if c == "C":
                x1, y1, x2, y2, ex, ey = nums(6)
                if rel:
                    x1, y1, x2, y2, ex, ey = x1 + x, y1 + y, x2 + x, y2 + y, ex + x, ey + y
            else:
                x2, y2, ex, ey = nums(4)
                if rel:
                    x2, y2, ex, ey = x2 + x, y2 + y, ex + x, ey + y
                x1, y1 = (2 * x - lcx, 2 * y - lcy) if lcx is not None else (x, y)
            path.cubicTo(x1, y1, x2, y2, ex, ey)
            lcx, lcy = x2, y2
            x, y = ex, ey
        elif c == "A":
            rx, ry, phi, fa, fs, ex, ey = nums(7)
            if rel:
                ex, ey = ex + x, ey + y
            _arc(path, x, y, rx, ry, phi, int(fa), int(fs), ex, ey)
            x, y = ex, ey
            lcx = None
        else:
            break
    return path


def draw_icon(p: QPainter, name: str, rect: QRectF, col, stroke: float = 2.0) -> None:
    """Draw icon `name` fitted into rect; stroke width is in 24-unit viewBox space (as in the SVGs)."""
    path = parse_path(PATHS[name])
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.translate(rect.topLeft())
    s = min(rect.width(), rect.height()) / 24.0
    p.scale(s, s)
    pen = QPen(QColor(col), stroke)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    p.restore()


def icon_pixmap(name: str, col, size: int = 16, stroke: float = 2.0, dpr: float = 2.0) -> QPixmap:
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    draw_icon(p, name, QRectF(0, 0, size, size), col, stroke)
    p.end()
    return pm
