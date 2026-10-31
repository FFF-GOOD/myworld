"""Page-linked, lightweight comment cards; no PDF render is needed to edit or hover."""
import math
import pymupdf as pdf
from PySide6.QtCore import QObject,QEvent,QPoint,QPointF,Qt,QTimer
from PySide6.QtGui import QColor,QPainter,QPen,QPolygonF
from PySide6.QtWidgets import QWidget,QFrame,QVBoxLayout,QLabel,QTextEdit,QGraphicsOpacityEffect,QApplication

COMMENT_KINDS={'highlight','underline','strike'}

class CommentPointer(QWidget):
    def __init__(self,manager):
        super().__init__(manager.view.viewport());self.manager=manager
        self.setAttribute(Qt.WA_TransparentForMouseEvents);self.hide()
    def paintEvent(self,event):
        card=self.manager.hovered
        if not card or card.isHidden():return
        v=self.manager.view;a=card.annotation
        painter=QPainter(self);painter.setRenderHint(QPainter.Antialiasing)
        color=QColor.fromRgbF(*a.get('color',[1,.78,.12]))
        painter.setPen(QPen(color,2))
        quads=a.get('quads') or []
        if quads:
            for values in quads:
                pts=[(values[i],values[i+1]) for i in (0,2,6,4)]
                poly=QPolygonF([QPointF(v.mapFromScene(v.to_scene(a['page'],p))) for p in pts])
                painter.drawPolygon(poly)
        else:
            r=pdf.Rect(a['rect'])
            poly=QPolygonF([QPointF(v.mapFromScene(v.to_scene(a['page'],p))) for p in (r.tl,r.tr,r.br,r.bl)])
            painter.drawPolygon(poly)
        target=v.mapFromScene(v.to_scene(a['page'],pdf.Rect(a['rect']).tl))
        box=card.geometry()
        start=QPoint(max(box.left(),min(target.x(),box.right())),max(box.top(),min(target.y(),box.bottom())))
        painter.drawLine(start,target)
        painter.setBrush(color);painter.drawEllipse(target,4,4)

class CommentCard(QFrame):
    def __init__(self,manager,annotation):
        super().__init__(manager.view.viewport())
        self.manager=manager;self.annotation=dict(annotation);self.dirty=False
        self.drag_start=None;self.dragged=False
        self.setObjectName('commentCard');self.setFixedSize(248,155)
        self.effect=QGraphicsOpacityEffect(self);self.effect.setOpacity(.58);self.setGraphicsEffect(self.effect)
        layout=QVBoxLayout(self);layout.setContentsMargins(2,2,2,2);layout.setSpacing(0)
        self.header=QLabel();self.header.setCursor(Qt.SizeAllCursor);self.header.setMargin(6)
        self.header.setToolTip('拖动标题移动批注；悬停指向原文')
        layout.addWidget(self.header)
        self.editor=QTextEdit();self.editor.setAcceptRichText(False);self.editor.setFrameShape(QFrame.NoFrame)
        self.editor.setPlaceholderText('输入评论，自动保存…')
        self.editor.setPlainText(annotation.get('comment',''));layout.addWidget(self.editor,1)
        self.save_timer=QTimer(self);self.save_timer.setSingleShot(True);self.save_timer.timeout.connect(self.flush)
        self.editor.textChanged.connect(self.changed)
        self.header.installEventFilter(self);self.editor.installEventFilter(self)
        self.editor.viewport().installEventFilter(self)
        self.update_annotation(annotation)
    def update_annotation(self,a):
        self.annotation=dict(a)
        color=QColor.fromRgbF(*a.get('color',[1,.78,.12]));name=color.name()
        ink='#171923' if color.lightnessF()>.48 else '#ffffff'
        self.setStyleSheet(f'#commentCard {{background:{name};border:2px solid {name};border-radius:4px;}}')
        self.header.setStyleSheet(f'background:{name};color:{ink};border:0;')
        self.editor.setStyleSheet('QTextEdit {background:#fffdf8;color:#20232b;border:0;padding:5px;}')
        self.header.setText({'highlight':'高亮','underline':'下划线','strike':'删除线'}.get(a['kind'],'批注')+' · 第 '+str(a['page']+1)+' 页  ⠿')
        if not self.dirty and self.editor.toPlainText()!=a.get('comment',''):
            cursor=self.editor.textCursor();pos=cursor.position()
            self.editor.blockSignals(True);self.editor.setPlainText(a.get('comment',''))
            cursor=self.editor.textCursor();cursor.setPosition(min(pos,len(self.editor.toPlainText())))
            self.editor.setTextCursor(cursor);self.editor.blockSignals(False)
    def changed(self):
        self.dirty=True;self.save_timer.start(900)
        self.manager.main.layout_dirty=True;self.manager.main.schedule_save()
    def flush(self):
        self.save_timer.stop()
        if not self.dirty:return
        text=self.editor.toPlainText()
        if len(text)>20000:
            self.manager.main.statusBar().showMessage('单条评论最多 20000 个字符，请缩短后保存。');return False
        self.dirty=False
        if not self.manager.commit(self,text):self.dirty=True;return False
        return True
    def enterEvent(self,event):
        self.manager.hovered=self;self.manager.pointer.show();self.manager.pointer.update()
        super().enterEvent(event)
    def leaveEvent(self,event):
        if self.manager.hovered is self:self.manager.hovered=None;self.manager.pointer.hide()
        super().leaveEvent(event)
    def eventFilter(self,obj,event):
        kind=event.type()
        if kind==QEvent.FocusIn:
            self.effect.setOpacity(1.)
        elif kind==QEvent.FocusOut:
            QTimer.singleShot(0,self.manager.focus_changed)
        if obj is self.header:
            if kind==QEvent.MouseButtonPress and event.button()==Qt.LeftButton:
                self.drag_start=event.globalPosition().toPoint()-self.pos();self.dragged=False
                self.effect.setOpacity(1.);return True
            if kind==QEvent.MouseMove and self.drag_start is not None:
                pos=event.globalPosition().toPoint()-self.drag_start
                area=self.parentWidget().rect()
                self.move(max(0,min(pos.x(),area.width()-self.width())),max(0,min(pos.y(),area.height()-self.height())))
                self.dragged=True;self.manager.pointer.update();return True
            if kind==QEvent.MouseButtonRelease and self.drag_start is not None:
                self.drag_start=None
                if self.dragged:self.manager.remember(self)
                self.editor.setFocus()
                self.manager.focus_changed();return True
        return super().eventFilter(obj,event)

class CommentManager(QObject):
    def __init__(self,main,view):
        super().__init__(view);self.main=main;self.view=view;self.cards={};self.positions={}
        self.hovered=None;self.pointer=CommentPointer(self)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(self.sync)
        view.viewport().installEventFilter(self)
        view.moved.connect(lambda *_:self.schedule())
        QApplication.instance().focusChanged.connect(lambda *_:self.focus_changed())
    def eventFilter(self,obj,event):
        if event.type()==QEvent.Resize:self.schedule()
        return False
    def schedule(self):
        self.timer.start(0)
    @staticmethod
    def key(a):return a.get('anchor_id',a['id'])
    def reset(self,positions=None):
        self.timer.stop()
        for card in self.cards.values():card.save_timer.stop();card.hide();card.deleteLater()
        self.cards={};self.positions={};self.hovered=None;self.pointer.hide()
        if isinstance(positions,dict):
            for key,value in list(positions.items())[:50000]:
                if isinstance(key,str) and len(key)<150 and isinstance(value,list) and len(value)==3 and type(value[0]) is int and 0<=value[0]<len(self.main.session.doc) and all(isinstance(n,(int,float)) and math.isfinite(n) and abs(n)<1000000 for n in value[1:]):
                    self.positions[key]=list(value)
        self.schedule()
    def visible_pages(self):
        v=self.view
        bounds=v.mapToScene(v.viewport().rect()).boundingRect()
        return [n for n,p in enumerate(v.pages) if p['rect'].intersects(bounds)]
    def sync(self):
        v=self.view
        if not self.main.session or v.session is not self.main.session:return
        visible=set(self.visible_pages());found=set()
        for page in visible:
            for a in self.main.session.annotations(page,v.edited):
                if a['kind'] not in COMMENT_KINDS:continue
                key=self.key(a);card=self.cards.get(key)
                if not a.get('comment') and card is None:continue
                found.add(key)
                if card is None:card=CommentCard(self,a);self.cards[key]=card
                else:card.update_annotation(a)
                self.place(card);card.show();card.raise_()
        for key,card in list(self.cards.items()):
            if key in found:continue
            # Keep a dirty draft while it scrolls out; flush before releasing it.
            if card.dirty:card.flush()
            card.save_timer.stop();card.hide();card.deleteLater();del self.cards[key]
            if self.hovered is card:self.hovered=None;self.pointer.hide()
        self.pointer.setGeometry(v.viewport().rect());self.pointer.update()
    def place(self,card):
        a=card.annotation;v=self.view;key=self.key(a)
        stored=self.positions.get(key)
        if stored and stored[0]==a['page']:point=v.mapFromScene(v.to_scene(a['page'],stored[1:]))
        else:
            r=pdf.Rect(a['rect'])
            point=v.mapFromScene(v.to_scene(a['page'],(r.x1,r.y0)))
            point+=QPoint(12,-card.height()-16)
            # Stagger new cards so nearby comments remain reachable.
            offset=sum(1 for c in self.cards.values() if c is not card and c.annotation['page']==a['page'])%5
            point+=QPoint(-offset*16,offset*28)
        area=v.viewport().rect()
        card.move(max(2,min(point.x(),area.width()-card.width()-2)),max(2,min(point.y(),area.height()-card.height()-2)))
    def open(self,a):
        if a['kind'] not in COMMENT_KINDS:return
        key=self.key(a)
        if key not in self.cards:self.cards[key]=CommentCard(self,a)
        card=self.cards[key];card.update_annotation(a);self.place(card)
        card.show();card.raise_();card.editor.setFocus();card.effect.setOpacity(1.)
        return card
    def remember(self,card):
        a=card.annotation;point=self.view.to_pdf(a['page'],self.view.mapToScene(card.pos()))
        self.positions[self.key(a)]=[a['page'],round(point.x,3),round(point.y,3)]
        self.main.layout_dirty=True;self.main.schedule_save()
    def focus_changed(self):
        focus=QApplication.focusWidget()
        for card in list(self.cards.values()):
            active=focus is card or (focus and card.isAncestorOf(focus))
            card.effect.setOpacity(1. if active else .58)
            if not active and card.dirty:card.flush()
    def commit(self,card,text):
        a=card.annotation
        current=next((x for x in self.main.session.annotations(a['page'],self.view.edited) if x['id']==a['id']),None)
        if not current:return False
        if current.get('comment','')==text:return True
        try:
            self.main.session.add('update',a['page'],scope='work' if self.view.edited else 'original',target=a['id'],changes={'comment':text})
            card.annotation['comment']=text
            self.main.update_edit(a['page'])
            return True
        except Exception as exc:self.main.error(exc);return False
    def flush(self):
        return all(card.flush() is not False for card in list(self.cards.values()))
