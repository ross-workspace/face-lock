"""Small vector illustrations and icons for the desktop interface."""

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget


def icon(kind, color="#a4abb5"):
    pix = QPixmap(24, 24)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(
        QPen(
            QColor(color),
            1.7,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
    )
    if kind == "folder":
        path = QPainterPath(QPointF(3, 7))
        for x, y in [(3, 5), (10, 5), (12, 8), (21, 8), (21, 19), (3, 19), (3, 7)]:
            path.lineTo(x, y)
        p.drawPath(path)
    elif kind == "face":
        for x, y, dx, dy in [(3, 3, 5, 5), (21, 3, -5, 5), (3, 21, 5, -5), (21, 21, -5, -5)]:
            p.drawLine(x, y, x + dx, y)
            p.drawLine(x, y, x, y + dy)
        p.drawEllipse(QRectF(7, 5, 10, 14))
        p.drawPoint(10, 10)
        p.drawPoint(14, 10)
        p.drawArc(QRectF(9, 11, 6, 5), 190 * 16, 160 * 16)
    elif kind == "gesture":
        p.drawRoundedRect(QRectF(6, 11, 12, 10), 4, 4)
        for x, top in [(7, 7), (10, 3), (13, 4), (16, 7)]:
            p.drawLine(x, top, x, 13)
        p.drawLine(6, 14, 3, 10)
        p.drawLine(3, 10, 2, 13)
        p.drawLine(2, 13, 6, 19)
    elif kind == "arrow":
        p.drawLine(5, 12, 19, 12)
        p.drawLine(14, 7, 19, 12)
        p.drawLine(14, 17, 19, 12)
    elif kind == "lock":
        p.drawArc(QRectF(7, 3, 10, 14), 0, 180 * 16)
        p.drawRoundedRect(QRectF(5, 10, 14, 11), 3, 3)
        p.drawLine(12, 14, 12, 17)
    p.end()
    return QIcon(pix)


class VaultArt(QWidget):
    def __init__(self):
        super().__init__()
        self.readable = False
        self.setMinimumSize(230, 180)
        self.setMaximumWidth(280)

    def set_readable(self, readable):
        self.readable = readable
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(self.width() / 2, self.height() / 2)
        p.setPen(QPen(QColor("#303638"), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(-87, -87, 174, 174))
        p.drawEllipse(QRectF(-108, -108, 216, 216))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#c6f56d"))
        p.drawEllipse(QRectF(77, -44, 7, 7))
        p.setBrush(QColor("#454d40"))
        p.drawEllipse(QRectF(-93, 40, 5, 5))
        path = QPainterPath(QPointF(-65, -43))
        path.lineTo(-19, -43)
        path.lineTo(-8, -31)
        path.lineTo(65, -31)
        path.quadTo(75, -31, 75, -21)
        path.lineTo(75, 45)
        path.quadTo(75, 55, 65, 55)
        path.lineTo(-65, 55)
        path.quadTo(-75, 55, -75, 45)
        path.lineTo(-75, -33)
        path.quadTo(-75, -43, -65, -43)
        p.setPen(QPen(QColor("#556147"), 1.5))
        p.setBrush(QColor("#293027"))
        p.drawPath(path)
        p.setPen(QPen(QColor("#3b4532"), 1))
        p.drawLine(-61, -17, 60, -17)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#c6f56d"))
        p.drawRoundedRect(QRectF(-25, 0, 50, 39), 9, 9)
        p.setPen(QPen(QColor("#c6f56d"), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(-14 + (9 if self.readable else 0), -24, 28, 41), 0, 180 * 16)
        p.setPen(QPen(QColor("#293027"), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(0, 14, 0, 24)
        p.end()
