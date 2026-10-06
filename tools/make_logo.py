"""Render the Alaz logo from its vector definition (tools/alaz_logo_shape.py).

Outputs: app icons (all sizes) for assets/icons and alaz/ui/icons, per-GPU-mode variants
(alaz-<mode>-<size>.png, alaz/ui/icons only), assets/alaz.png (512 px icon), assets/logo.png (emblem + "Alaz" wordmark, for the README).  Usage: python3 tools/make_logo.py
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPainterPath, QPen, QPolygonF

sys.path.insert(0, str(Path(__file__).resolve().parent))
from alaz_logo_shape import COLOR, MODE_COLORS, outline  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SIZES = (16, 24, 32, 48, 64, 128, 256, 512)
TEAL, INK, EDGE = QColor(COLOR), QColor("#0E0F13"), QColor("#2A2E38")


def emblem_path() -> QPainterPath:
    p = QPainterPath()
    p.addPolygon(QPolygonF([QPointF(x, y) for x, y in outline()]))
    p.closeSubpath()
    return p


def draw_emblem(p: QPainter, box: QRectF, color: QColor = TEAL) -> None:
    path = emblem_path()
    r = path.boundingRect()
    k = min(box.width() / r.width(), box.height() / r.height())
    p.save()
    p.translate(box.center().x(), box.center().y())
    p.scale(k, k)
    p.translate(-r.center().x(), -r.center().y())
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawPath(path)
    p.restore()


def icon(size: int, color: QColor = TEAL) -> QImage:
    # render at 4x and downscale for crisp small sizes
    s = size * 4 if size < 128 else size
    img = QImage(s, s, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(INK)
    p.drawRoundedRect(QRectF(0, 0, s, s), s * 0.22, s * 0.22)
    p.setPen(QPen(EDGE, max(1.0, s * 0.006)))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(0.5, 0.5, s - 1, s - 1), s * 0.22, s * 0.22)
    pad = 0.17 if size >= 32 else 0.13          # small sizes: emblem a bit larger
    draw_emblem(p, QRectF(s * pad, s * pad, s * (1 - 2 * pad), s * (1 - 2 * pad)), color)
    p.end()
    if s != size:
        img = img.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    return img


def logo(w: int = 1200, h: int = 1200) -> QImage:
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(INK)
    p.drawRoundedRect(QRectF(0, 0, w, h), w * 0.16, w * 0.16)
    draw_emblem(p, QRectF(w * 0.22, h * 0.10, w * 0.56, h * 0.56))
    f = QFont("Inter")
    f.setPixelSize(int(h * 0.17))
    f.setWeight(QFont.Weight.Bold)
    f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 97)
    p.setFont(f)
    p.setPen(TEAL)
    p.drawText(QRectF(0, h * 0.70, w, h * 0.22), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, "Alaz")
    p.end()
    return img


def main() -> None:
    app = QGuiApplication.instance() or QGuiApplication([])  # keep a reference (fonts need it)
    for d in (ROOT / "assets" / "icons", ROOT / "alaz" / "ui" / "icons"):
        d.mkdir(parents=True, exist_ok=True)
        for s in SIZES:
            icon(s).save(str(d / f"alaz-{s}.png"))
    # mode variants follow the active GPU mode in the running app (title bar, tray, window icon);
    # the desktop/launcher icon stays the base colour
    for mode, col in MODE_COLORS.items():
        if mode == "eco":
            continue
        for s in SIZES:
            icon(s, QColor(col)).save(str(ROOT / "alaz" / "ui" / "icons" / f"alaz-{mode}-{s}.png"))
    icon(512).save(str(ROOT / "assets" / "alaz.png"))
    logo().save(str(ROOT / "assets" / "logo.png"))
    print("ok")


if __name__ == "__main__":
    main()
