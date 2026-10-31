"""Small contextual PDF controls. All panels are anchored, with no modal color dialog."""
from PySide6.QtCore import Qt,QPoint,Signal,QRect
from PySide6.QtGui import QColor,QPixmap,QIcon,QKeySequence,QShortcut
from PySide6.QtWidgets import (QFrame,QVBoxLayout,QHBoxLayout,QGridLayout,QLabel,QToolButton,
                              QLineEdit,QPushButton,QTextEdit,QMenu)
from icons import icon

PALETTE=['#FFE277','#FFF2A0','#FFB85C','#FF8D8D','#FFA9D3','#D7A6F5',
         '#B5DFA7','#7EDAC6','#8FC5FF','#A9B6FC','#E25759','#FF771D',
         '#E9B900','#4EA649','#1C9C93','#2E6EE8','#7D42C2','#AE2B83',
         '#171923','#505866','#9299A5','#FFFFFF']

class ColorPopover(QFrame):
    picked=Signal(object)
    def __init__(self,parent):
        super().__init__(parent,Qt.Popup|Qt.FramelessWindowHint)
        self.setObjectName('colorPopover')
        self.setStyleSheet('#colorPopover {background:white;border:1px solid #d8d5df;border-radius:7px;}')
        layout=QVBoxLayout(self);layout.setContentsMargins(12,10,12,12)
        layout.addWidget(QLabel('颜色'))
        grid=QGridLayout();grid.setSpacing(5);layout.addLayout(grid)
        self.swatches={}
        for i,code in enumerate(PALETTE):
            b=QToolButton();b.setFixedSize(27,25);b.setFocusPolicy(Qt.NoFocus);b.setToolTip(code)
            b.setStyleSheet(f'background:{code};border:1px solid #ccc;border-radius:4px;')
            b.clicked.connect(lambda checked=False,c=code:self.choose(c));grid.addWidget(b,i//6,i%6)
            self.swatches[code]=b
        row=QHBoxLayout();layout.addLayout(row)
        self.hex=QLineEdit();self.hex.setMaximumWidth(113);self.hex.setPlaceholderText('#RRGGBB');row.addWidget(self.hex)
        self.apply_button=QPushButton('应用');self.apply_button.clicked.connect(self.apply_hex);row.addWidget(self.apply_button)
        self.error=QLabel();self.error.setStyleSheet('color:#b23248;');layout.addWidget(self.error)
        self.hex.returnPressed.connect(self.apply_hex)

    def open_at(self,point,color):
        self.hex.setText(QColor.fromRgbF(*color).name().upper());self.error.clear()
        self.adjustSize()
        screen=self.parentWidget().screen().availableGeometry()
        self.move(max(screen.left()+4,min(point.x(),screen.right()-self.width()-4)),
                  max(screen.top()+4,min(point.y(),screen.bottom()-self.height()-4)))
        self.show();self.raise_()

    def apply_hex(self):
        code=self.hex.text().strip()
        if len(code)!=7 or not code.startswith('#') or not QColor(code).isValid():
            self.error.setText('请输入 #RRGGBB，例如 #FFCC00');self.adjustSize();return
        self.choose(code)

    def choose(self,code):
        color=QColor(code);self.hide()
        self.picked.emit((color.redF(),color.greenF(),color.blueF()))


class SelectionTools(QFrame):
    def __init__(self,main):
        super().__init__(main)
        self.main=main;self.mode=None;self.view=None;self.payload=None;self.annotation=None
        self.setObjectName('pdfContextTools')
        self.setStyleSheet('#pdfContextTools {background:#fff;border:1px solid #d9d4e0;border-radius:7px;} QToolButton {padding:6px 7px;}')
        self.outer=QVBoxLayout(self);self.outer.setContentsMargins(5,4,5,4);self.outer.setSpacing(4)
        self.row=QHBoxLayout();self.row.setSpacing(1);self.outer.addLayout(self.row)
        self.comment_panel=QFrame();column=QVBoxLayout(self.comment_panel);column.setContentsMargins(5,0,5,4)
        self.comment_edit=QTextEdit();self.comment_edit.setAcceptRichText(False)
        self.comment_edit.setPlaceholderText('为这条批注添加评论…');self.comment_edit.setFixedHeight(85);self.comment_edit.setMinimumWidth(280)
        column.addWidget(self.comment_edit)
        buttons=QHBoxLayout();column.addLayout(buttons);buttons.addStretch()
        self.cancel_comment=QPushButton('取消');self.cancel_comment.clicked.connect(self.comment_panel.hide);buttons.addWidget(self.cancel_comment)
        self.save_comment=QPushButton('保存评论');self.save_comment.clicked.connect(self.submit_comment);buttons.addWidget(self.save_comment)
        self.outer.addWidget(self.comment_panel);self.comment_panel.hide()
        self.comment_shortcut=QShortcut(QKeySequence('Ctrl+Return'),self.comment_edit)
        self.comment_shortcut.activated.connect(self.submit_comment)
        self.buttons={};self.hide()

    def clear_row(self):
        self.comment_panel.hide()
        while self.row.count():
            item=self.row.takeAt(0)
            if item.widget():item.widget().hide();item.widget().deleteLater()
        self.buttons={}

    def button(self,key,label,slot,symbol=None):
        b=QToolButton(self);b.setText(label);b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon);b.setFocusPolicy(Qt.NoFocus)
        if symbol:b.setIcon(icon(symbol))
        b.clicked.connect(slot);self.row.addWidget(b);self.buttons[key]=b;return b

    def place(self,view,page,rect):
        import pymupdf as pdf
        from PySide6.QtGui import QPolygonF
        r=pdf.Rect(rect);poly=QPolygonF([view.to_scene(page,p) for p in (r.tl,r.tr,r.br,r.bl)])
        bounds=view.mapFromScene(poly).boundingRect().intersected(view.viewport().rect())
        if bounds.isEmpty():self.hide();return
        anchor=view.viewport().mapTo(self.main,bounds.topLeft())
        below=view.viewport().mapTo(self.main,bounds.bottomLeft())
        self.adjustSize()
        x=max(8,min(anchor.x(),self.main.width()-self.width()-8))
        y=anchor.y()-self.height()-8
        if y<self.main.centralWidget().geometry().top():y=below.y()+8
        self.move(x,max(8,min(y,self.main.height()-self.height()-25)))
        self.show();self.raise_()

    def show_selection(self,view):
        if not view.selection_text or not view.selection_quads:self.hide();return
        import pymupdf as pdf
        from core import as_quad
        rect=pdf.Rect()
        for q in view.selection_quads:rect|=as_quad(q).rect
        self.mode='selection';self.view=view;self.annotation=None
        self.payload={'page':view.selection_page,'rect':list(rect),'quads':[list(q) for q in view.selection_quads],
                      'text':view.selection_text,'edited':view.edited}
        self.clear_row()
        self.button('copy','复制',self.copy)
        for kind,label in [('highlight','高亮'),('underline','下划线'),('strike','删除线')]:
            self.button(kind,label,lambda checked=False,k=kind:self.main.context_markup(k),kind)
        self.button('note','记笔记 ▾',self.note_menu,'note')
        self.place(view,self.payload['page'],self.payload['rect'])

    def show_annotation(self,view,annotation):
        self.mode='annotation';self.view=view;self.annotation=dict(annotation);self.payload=None
        self.clear_row()
        if annotation.get('kind')!='text':self.button('comment','评论',self.edit_comment,'note')
        elif not annotation['id'].startswith('base:'):self.button('edit','编辑文本',self.main.edit_selected_text,'text')
        b=self.button('color','颜色 ▾',lambda:self.main.choose_color(self.buttons['color']))
        pix=QPixmap(15,15);pix.fill(QColor.fromRgbF(*annotation.get('color',[1,.78,.12])));b.setIcon(QIcon(pix))
        self.button('delete','删除',self.main.delete_annotation,'delete')
        self.place(view,annotation['page'],annotation['rect'])

    def copy(self):
        from PySide6.QtWidgets import QApplication
        if self.payload and self.main.session.can_copy:
            QApplication.clipboard().setText(self.payload['text'])
            self.main.statusBar().showMessage('已复制所选文字。')
        self.hide()

    def note_menu(self):
        if not self.payload:return
        # Snapshot before showing a menu, so clicks and dock layout cannot change the quotation.
        payload=dict(self.payload);view=self.view
        menu=QMenu(self)
        menu.addAction('＋ 新建笔记',lambda:self.main.quote_payload(payload,view,create_new=True))
        menu.addSeparator()
        for ident,title in self.main.notebook.choices():
            action=menu.addAction(title.replace('&','&&'))
            action.setCheckable(True);action.setChecked(ident==self.main.session.active_note)
            action.triggered.connect(lambda checked=False,n=ident:self.main.quote_payload(payload,view,note_id=n))
        self.note_picker=menu
        button=self.buttons['note'];menu.popup(button.mapToGlobal(QPoint(0,button.height())))

    def edit_comment(self):
        if not self.annotation:return
        if self.annotation.get('kind') in {'highlight','underline','strike'}:
            self.hide()
            self.view.comments.open(self.annotation)
            return
        self.comment_edit.setPlainText(self.annotation.get('comment',''))
        self.comment_panel.show()
        self.place(self.view,self.annotation['page'],self.annotation['rect'])
        self.comment_edit.setFocus()

    def submit_comment(self):
        if not self.annotation:return
        text=self.comment_edit.toPlainText()
        self.main.change_annotation({'comment':text},self.view,self.annotation)
