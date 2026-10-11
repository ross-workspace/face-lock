from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget


class LockStrip(QWidget):
    def __init__(self):
        super().__init__()
        self.names = []
        self.opened = 0
        self.setMinimumHeight(95)

    def configure(self, names, opened=0):
        self.names, self.opened = names, opened
        self.update()

    def paintEvent(self, event):
        if not self.names:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = self.width() / len(self.names)
        for i, name in enumerate(self.names):
            x = width * (i + 0.5)
            color = QColor(
                "#c6f56d" if i < self.opened else "#c6f56d" if i == self.opened else "#626d7b"
            )
            p.setPen(QPen(color, 2))
            p.setBrush(QColor("#33402a" if i < self.opened else "#1a2028"))
            p.drawEllipse(QRectF(x - 23, 5, 46, 46))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(QRectF(x - 8 + (5 if i < self.opened else 0), 14, 16, 17), 0, 180 * 16)
            p.setBrush(color)
            p.drawRoundedRect(QRectF(x - 10, 24, 20, 15), 3, 3)
            p.setPen(QColor("#12271b" if i < self.opened else "#17212a"))
            p.drawLine(int(x), 29, int(x), 34)
            p.setPen(color)
            p.setFont(QFont("Helvetica Neue", 10))
            caption = p.fontMetrics().elidedText(
                f"{i + 1}. {name}", Qt.TextElideMode.ElideRight, max(20, int(width) - 8)
            )
            p.drawText(QRectF(x - width / 2, 56, width, 24), Qt.AlignmentFlag.AlignCenter, caption)
        p.end()
