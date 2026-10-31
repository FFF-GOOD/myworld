"""Original vector icons inspired by familiar PDF editor tools; no external assets."""
from PySide6.QtCore import Qt,QPointF,QRectF
from PySide6.QtGui import QIcon,QPixmap,QPainter,QPen,QColor,QFont,QPolygonF


def icon(name):
    pix=QPixmap(28,28);pix.fill(Qt.transparent)
    p=QPainter(pix);p.setRenderHint(QPainter.Antialiasing)
    purple=QColor('#8e348c');grey=QColor('#5e6370')
    p.setPen(QPen(purple,1.8,Qt.SolidLine,Qt.RoundCap,Qt.RoundJoin))
    if name in ('highlight','underline','strike','text','select'):
        if name=='highlight': p.fillRect(QRectF(3,17,23,8),QColor('#ffe078'))
        font=QFont('Arial',20);font.setBold(name=='text');p.setFont(font)
        p.drawText(QRectF(0,-1,28,27),Qt.AlignCenter,'T' if name=='text' else 'A')
        if name=='underline': p.drawLine(4,25,24,25)
        if name=='strike': p.setPen(QPen(QColor('#dc5356'),2));p.drawLine(3,14,25,14)
        if name=='select': p.drawLine(24,4,24,25);p.drawLine(21,4,27,4);p.drawLine(21,25,27,25)
    elif name in ('rect','brush'):
        p.save();p.translate(14,14);p.rotate(-35)
        p.setBrush(QColor('#f3e4f2'));p.drawRoundedRect(QRectF(-9,-6,18,12),2,2);p.drawLine(0,-6,0,6);p.restore()
        if name=='rect':p.setPen(QPen(grey,1,Qt.DashLine));p.drawRect(2,2,24,24)
    elif name=='ink':
        path=QPolygonF([QPointF(3,22),QPointF(9,13),QPointF(13,19),QPointF(20,5),QPointF(25,9)])
        p.drawPolyline(path)
    elif name in ('undo','redo'):
        p.save()
        if name=='redo':p.translate(28,0);p.scale(-1,1)
        p.drawArc(QRectF(6,8,18,15),-60*16,230*16);p.drawPolyline(QPolygonF([QPointF(10,3),QPointF(4,9),QPointF(12,11)]));p.restore()
    elif name=='swap':
        p.drawLine(3,9,25,9);p.drawLine(20,4,25,9);p.drawLine(20,14,25,9)
        p.drawLine(25,20,3,20);p.drawLine(8,15,3,20);p.drawLine(8,25,3,20)
    elif name=='hand':
        p.drawRoundedRect(QRectF(7,9,15,16),6,6)
        for x,y in [(8,6),(12,2),(16,3),(20,6)]: p.drawLine(x,y,x,14)
        p.drawLine(7,16,3,11);p.drawLine(3,11,2,16);p.drawLine(2,16,9,25)
    elif name=='delete':
        p.drawRect(7,8,15,17);p.drawLine(5,6,24,6);p.drawLine(11,3,18,3)
        p.drawLine(12,12,12,22);p.drawLine(17,12,17,22)
    elif name in ('open','load'):
        p.drawPolyline(QPolygonF([QPointF(3,22),QPointF(3,7),QPointF(11,7),QPointF(14,10),QPointF(25,10)]))
        p.drawPolygon(QPolygonF([QPointF(3,23),QPointF(8,13),QPointF(27,13),QPointF(22,23)]))
        if name=='load':p.drawText(11,21,'↶')
    elif name in ('save','source','export'):
        p.drawRect(5,3,18,22);p.drawRect(9,3,10,7);p.drawRect(9,17,10,8)
        if name=='source':p.setPen(QPen(QColor('#31866e'),2.6));p.drawLine(15,19,20,24);p.drawLine(20,24,27,14)
        if name=='export':p.drawLine(15,12,27,12);p.drawLine(23,8,27,12);p.drawLine(23,16,27,12)
    elif name=='copy':
        p.drawRoundedRect(QRectF(4,3,16,19),2,2);p.setBrush(QColor('#fcfbfd'));p.drawRoundedRect(QRectF(9,8,16,18),2,2)
    elif name=='capture':
        p.setPen(QPen(purple,1.5,Qt.DashLine));p.drawRect(3,4,22,19)
        p.setPen(QPen(purple,2));p.drawLine(8,2,3,2);p.drawLine(1,4,1,9)
        p.drawLine(20,25,27,25);p.drawLine(27,20,27,25)
    elif name=='note':
        p.drawRoundedRect(QRectF(4,3,20,23),2,2)
        for y in (9,14,19):p.drawLine(9,y,20,y)
    else:
        p.drawRoundedRect(QRectF(5,4,18,21),2,2);p.drawLine(9,10,20,10);p.drawLine(9,16,19,16)
    p.end();return QIcon(pix)
