"""In-page native Qt text entry with IME, resize/move support and local undo."""
from PySide6.QtCore import Qt,Signal,QRectF,QTimer,QPoint
from PySide6.QtGui import QColor,QFont,QPainter,QPen,QTextCursor,QTextBlockFormat,QKeySequence
from PySide6.QtWidgets import QGraphicsProxyWidget,QTextEdit,QFrame
from fonts import QT_FAMILIES


class PageTextEdit(QTextEdit):
    accepted=Signal()
    cancelled=Signal()
    def keyPressEvent(self,event):
        self.owner.reset_caret()
        if event.key() in (Qt.Key_Return,Qt.Key_Enter) and event.modifiers()&Qt.ControlModifier:
            self.accepted.emit();event.accept();return
        if event.key()==Qt.Key_Escape:self.cancelled.emit();event.accept();return
        super().keyPressEvent(event)
        if event.matches(QKeySequence.Undo) or event.matches(QKeySequence.Redo):self.owner.sync_format()


class InlineTextBox(QGraphicsProxyWidget):
    def __init__(self,view,page,rect,defaults,existing=None):
        super().__init__()
        self.view,self.page,self.rect,self.existing=view,page,list(rect),existing
        self.data=dict(defaults)
        self.editor=PageTextEdit()
        self.editor.owner=self
        self.editor.setCursorWidth(0)
        self.editor.setAcceptRichText(False)
        self.editor.setFrameShape(QFrame.NoFrame)
        self.editor.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.editor.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.editor.document().setDocumentMargin(0)
        self.editor.setStyleSheet('QTextEdit {background:transparent;border:0;padding:0;}')
        self.setWidget(self.editor)
        family=QT_FAMILIES.get(self.data['font'],self.data['font'])
        if family=='内置中文字体':family='sans-serif'
        base_font=QFont(family);base_font.setPointSizeF(self.data['size']*72/self.editor.logicalDpiY())
        self.setFont(base_font);self.editor.setFont(base_font);self.editor.document().setDefaultFont(base_font)
        self.setZValue(30)
        self.editor.setPlainText(defaults.get('text',''))
        self.editor.accepted.connect(lambda:view.window().finish_inline())
        self.editor.cancelled.connect(lambda:view.window().finish_inline(cancel=True))
        self.editor.textChanged.connect(self.grow)
        self.apply_format()
        self.set_rect(rect)
        self.editor.document().clearUndoRedoStacks()
        self.editor.setFocus()
        cursor=self.editor.textCursor();cursor.movePosition(QTextCursor.End);self.editor.setTextCursor(cursor)
        self.apply_format()
        self.editor.document().clearUndoRedoStacks()
        self.caret_on=True
        self.caret_timer=QTimer(self);self.caret_timer.setInterval(500);self.caret_timer.timeout.connect(self.blink_caret)
        self.editor.cursorPositionChanged.connect(self.reset_caret)
        self.editor.selectionChanged.connect(self.reset_caret)
        self.editor.textChanged.connect(self.reset_caret)
        self.caret_timer.start()

    def caret_rect(self):
        rect=self.editor.cursorRect()
        offset=self.editor.viewport().mapTo(self.editor,QPoint(0,0))
        return QRectF(rect.translated(offset))

    def reset_caret(self):
        self.caret_on=True
        if hasattr(self,'caret_timer'):self.caret_timer.start()
        self.update()

    def blink_caret(self):
        self.caret_on=not self.caret_on;self.update()

    def apply_format(self,**values):
        self.data.update(values)
        family=QT_FAMILIES.get(self.data['font'],self.data['font'])
        if family=='内置中文字体':family='sans-serif'
        font=QFont(family)
        font.setPointSizeF(self.data['size']*72/self.editor.logicalDpiY())
        cursor=self.editor.textCursor();position,anchor=cursor.position(),cursor.anchor()
        group=self.editor.textCursor();group.beginEditBlock()
        self.editor.selectAll();self.editor.setCurrentFont(font)
        self.editor.setTextColor(QColor.fromRgbF(*self.data['color']))
        block=QTextBlockFormat();block.setLineHeight(125,QTextBlockFormat.ProportionalHeight.value)
        self.editor.textCursor().mergeBlockFormat(block)
        group.endEditBlock()
        cursor=self.editor.textCursor();cursor.setPosition(min(anchor,self.editor.document().characterCount()-1));cursor.setPosition(min(position,self.editor.document().characterCount()-1),QTextCursor.KeepAnchor)
        self.editor.setTextCursor(cursor)
        if not self.editor.toPlainText():
            self.editor.setCurrentFont(font)
            self.editor.setTextColor(QColor.fromRgbF(*self.data['color']))
        self.grow()

    def set_rect(self,rect):
        self.rect=list(rect)
        m=self.view.pages[self.page]['matrix']
        from PySide6.QtGui import QTransform
        self.setTransform(QTransform(m.a,m.b,m.c,m.d,0,0))
        self.setPos(self.view.to_scene(self.page,(rect[0],rect[1])))
        self.resize(max(8,rect[2]-rect[0]),max(8,rect[3]-rect[1]))
        self.update()

    def grow(self):
        if not hasattr(self,'rect'):return
        bounds=self.view.session.doc[self.page].rect*self.view.session.doc[self.page].derotation_matrix
        height=self.editor.document().size().height()+2
        if height>self.rect[3]-self.rect[1] and self.rect[3]<bounds.y1:
            rect=list(self.rect);rect[3]=min(bounds.y1,rect[1]+height)
            self.set_rect(rect)

    def paint(self,painter,option,widget=None):
        super().paint(painter,option,widget)
        painter.save();painter.setPen(QPen(QColor('#92358f'),1/max(self.view.zoom,.25)))
        painter.drawRect(self.boundingRect().adjusted(.5,.5,-.5,-.5))
        if getattr(self,'caret_on',True) and not self.editor.textCursor().hasSelection():
            caret=self.caret_rect();caret.setWidth(1.8/max(self.view.zoom,.25))
            painter.fillRect(caret,QColor('#171923'))
        r=self.boundingRect();size=6/max(self.view.zoom,.25);painter.fillRect(QRectF(r.right()-size,r.bottom()-size,size,size),QColor('#92358f'));painter.restore()

    def current_format(self):
        if not self.editor.toPlainText():return {k:self.data[k] for k in ('font','size','color')}
        cursor=QTextCursor(self.editor.document());cursor.movePosition(QTextCursor.Start);cursor.movePosition(QTextCursor.NextCharacter,QTextCursor.KeepAnchor)
        fmt=cursor.charFormat();font=fmt.font();family=font.families()[0] if font.families() else ''
        inverse={v:k for k,v in QT_FAMILIES.items()}
        family=inverse.get(family,family)
        from fonts import FONT_FILES
        if family not in FONT_FILES:family='内置中文字体' if self.data['font']=='内置中文字体' else self.data['font']
        size=font.pixelSize() if font.pixelSize()>0 else font.pointSizeF()*self.editor.logicalDpiY()/72
        return {'font':family,'size':round(size,3) if size>0 else self.data['size'],
                'color':tuple(round(v,5) for v in fmt.foreground().color().getRgbF()[:3])}

    def sync_format(self):
        self.data.update(self.current_format())
        main=self.view.window()
        main.font_input.blockSignals(True);main.font_size.blockSignals(True)
        main.font_input.setCurrentText(self.data['font']);main.font_size.setValue(self.data['size'])
        main.font_input.blockSignals(False);main.font_size.blockSignals(False)
        main.colors['text']=self.data['color']

    def result(self):
        return self.current_format()|{'rect':self.rect,'text':self.editor.toPlainText()}
