"""Local PDF-linked rich-text notebook, quotes, image paste and bounded deduplicated assets."""
import hashlib,html,base64,re,math,uuid
from urllib.parse import urlparse,parse_qs
from PySide6.QtCore import Qt,QUrl,QByteArray,QBuffer,QIODevice,QSize,QRectF,QPoint,QSizeF,Signal
from PySide6.QtGui import (QImage,QImageReader,QTextDocument,QTextImageFormat,QTextCursor,QTextCharFormat,
                           QFont,QTextListFormat,QTextBlockFormat,QKeySequence,QPainter,QPen,QColor)
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QTextEdit,QPushButton,QLabel,QFileDialog,QToolBar,QComboBox,QApplication,QSpinBox,QRubberBand
from core import atomic_write


def checked_image(blob,preview=False):
    buffer=QBuffer();buffer.setData(QByteArray(blob));buffer.open(QIODevice.ReadOnly)
    reader=QImageReader(buffer)
    size=reader.size()
    if not size.isValid() or size.width()*size.height()>16_000_000:return QImage()
    if preview and (size.width()>600 or size.height()>600):reader.setScaledSize(size.scaled(QSize(600,600),Qt.KeepAspectRatio))
    return reader.read()


class NoteEditor(QTextEdit):
    source_clicked=Signal(str)
    def __init__(self,panel):
        super().__init__();self.panel=panel
        self.selected_image=None;self.image_drag=None
        self.rubber=QRubberBand(QRubberBand.Rectangle,self.viewport())
        self.cursorPositionChanged.connect(self.image_cursor_changed)
        self.setMouseTracking(True)
        self.setAcceptRichText(True)
        note_font=self.font();note_font.setPointSize(12);self.setFont(note_font)
        self.setPlaceholderText('阅读时选中文字，点击“摘录到笔记”。\n也可直接输入、粘贴截图，或插入图片。\n点击摘录页码可回到 PDF。')

    def loadResource(self,kind,name):
        if name.scheme()=='studypdf-image' and self.panel.session:
            key=name.path().lstrip("/")
            blob=self.panel.session.note_assets.get(key)
            if blob:return checked_image(blob,preview=True)
        return None

    def canInsertFromMimeData(self,source):return source.hasImage() or source.hasText() or source.hasUrls()
    def insertFromMimeData(self,source):
        if source.hasImage():
            image=source.imageData()
            if not isinstance(image,QImage):image=image.toImage() if hasattr(image,"toImage") else QImage()
            self.panel.insert_image(image)
        elif source.hasUrls():
            for url in source.urls():
                if url.isLocalFile():self.panel.import_image(url.toLocalFile())
        elif source.hasText():
            # External HTML may reference missing/local/network images; paste text, add images explicitly.
            self.textCursor().insertText(source.text())

    def keyPressEvent(self,event):
        if event.matches(QKeySequence.Paste):
            mime=QApplication.clipboard().mimeData()
            if mime and mime.hasImage():
                self.panel.insert_image(QApplication.clipboard().image())
                event.accept();return
        super().keyPressEvent(event)

    def image_cursor(self,pos):
        if not 0<=pos<self.document().characterCount()-1:return None
        c=QTextCursor(self.document());c.setPosition(pos);c.movePosition(QTextCursor.NextCharacter,QTextCursor.KeepAnchor)
        return c if c.selectedText()=='\ufffc' and c.charFormat().isImageFormat() else None

    def image_cursor_changed(self):
        c=self.textCursor()
        if c.hasSelection() and c.selectionEnd()-c.selectionStart()==1:
            candidate=self.image_cursor(c.selectionStart())
            if candidate:self.selected_image=candidate;self.panel.image_controls();self.viewport().update();return
        self.selected_image=None
        if hasattr(self.panel,'image_bar'):self.panel.image_controls()
        self.viewport().update()

    def image_rect(self,cursor=None):
        cursor=cursor or self.selected_image
        if not cursor or self.image_cursor(cursor.selectionStart()) is None:return QRectF()
        fmt=cursor.charFormat().toImageFormat()
        c=QTextCursor(cursor);c.setPosition(cursor.selectionStart())
        r=self.cursorRect(c)
        return QRectF(r.left(),r.bottom()-fmt.height()+1,fmt.width(),fmt.height())

    def paintEvent(self,event):
        super().paintEvent(event)
        r=self.image_rect()
        if r.isEmpty():return
        painter=QPainter(self.viewport());painter.setPen(QPen(QColor('#8e348c'),1.5))
        painter.drawRect(r)
        painter.fillRect(QRectF(r.right()-5,r.bottom()-5,10,10),QColor('#8e348c'))

    def mousePressEvent(self,event):
        r=self.image_rect()
        if event.button()==Qt.LeftButton and not r.isEmpty() and QRectF(r.right()-9,r.bottom()-9,18,18).contains(event.position()):
            self.image_drag=(QRectF(r),r.width()/r.height())
            self.rubber.setGeometry(r.toAlignedRect());self.rubber.show();event.accept();return
        c=self.cursorForPosition(event.position().toPoint())
        for pos in (c.position(),c.position()-1):
            candidate=self.image_cursor(pos)
            if candidate and self.image_rect(candidate).adjusted(-2,-2,2,2).contains(event.position()):
                self.selected_image=candidate;self.setTextCursor(candidate)
                self.panel.image_controls();self.viewport().update();event.accept();return
        super().mousePressEvent(event)

    def mouseMoveEvent(self,event):
        if self.image_drag:
            r,ratio=self.image_drag
            width=max(40,min(3200,event.position().x()-r.left()))
            self.rubber.setGeometry(QRectF(r.topLeft(),QSizeF(width,width/ratio)).toAlignedRect())
            event.accept();return
        r=self.image_rect()
        if not r.isEmpty() and QRectF(r.right()-9,r.bottom()-9,18,18).contains(event.position()):
            self.viewport().setCursor(Qt.SizeFDiagCursor)
        else:self.viewport().setCursor(Qt.IBeamCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self,event):
        if self.image_drag:
            width=self.rubber.width();self.rubber.hide();self.image_drag=None
            self.panel.resize_image(width);event.accept();return
        if self.selected_image and self.image_rect().contains(event.position()):
            event.accept();return
        anchor=self.anchorAt(event.position().toPoint())
        if anchor.startswith('studypdf://'):
            self.source_clicked.emit(anchor);event.accept();return
        super().mouseReleaseEvent(event)


class Notebook(QWidget):
    changed=Signal()
    jump=Signal(int,object)
    failed=Signal(str)
    def __init__(self,parent=None):
        super().__init__(parent);self.session=None;self.loading=False
        layout=QVBoxLayout(self);layout.setContentsMargins(8,8,8,6)
        self.title=QLabel('本 PDF 笔记');self.title.setWordWrap(True);layout.addWidget(self.title)
        chooser=QHBoxLayout();layout.addLayout(chooser)
        self.note_selector=QComboBox();self.note_selector.setEditable(True);self.note_selector.setInsertPolicy(QComboBox.NoInsert)
        self.note_selector.setToolTip('选择笔记；编辑名称后按 Enter 重命名')
        chooser.addWidget(self.note_selector,1)
        self.new_button=QPushButton('＋ 新建');self.new_button.clicked.connect(lambda:self.new_note());chooser.addWidget(self.new_button)
        self.note_selector.activated.connect(self.choose_index)
        self.note_selector.lineEdit().editingFinished.connect(self.rename_current)
        tools=QToolBar();tools.setIconSize(QSize(16,16));layout.addWidget(tools)
        self.editor=NoteEditor(self)
        for label,slot in [('B',lambda:self.font_format('bold')),('I',lambda:self.font_format('italic')),('U',lambda:self.font_format('underline')),('标题',self.heading),('正文',self.body),('• 列表',self.bullet)]:tools.addAction(label,slot)
        row=QHBoxLayout();layout.addLayout(row)
        insert=QPushButton('插入图片');insert.clicked.connect(lambda:self.import_image());row.addWidget(insert)
        export=QPushButton('导出笔记');export.clicked.connect(self.export);row.addWidget(export)
        self.image_bar=QWidget();image_row=QHBoxLayout(self.image_bar);image_row.setContentsMargins(0,0,0,0)
        image_row.addWidget(QLabel('图片宽度'))
        self.image_width=QSpinBox();self.image_width.setRange(40,3200);self.image_width.setSuffix(' px');self.image_width.setKeyboardTracking(False)
        self.image_width.valueChanged.connect(self.resize_image);image_row.addWidget(self.image_width)
        fit=QPushButton('适合笔记');fit.clicked.connect(lambda:self.resize_image(max(40,self.editor.viewport().width()-24)));image_row.addWidget(fit)
        original=QPushButton('原尺寸');original.clicked.connect(self.image_original);image_row.addWidget(original)
        self.image_bar.setToolTip('选中图片后拖动右下角，或修改宽度；保持宽高比，Ctrl+Z 撤销')
        layout.addWidget(self.image_bar);self.image_bar.hide()
        layout.addWidget(self.editor,1)
        self.status=QLabel('随工作记录自动保存');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.editor.textChanged.connect(self.on_changed)
        self.editor.source_clicked.connect(self.follow_link)
        self.setEnabled(False)

    def image_controls(self):
        c=self.editor.selected_image
        valid=c is not None and self.editor.image_cursor(c.selectionStart()) is not None
        self.image_bar.setVisible(valid)
        if valid:
            self.image_width.blockSignals(True);self.image_width.setValue(round(c.charFormat().toImageFormat().width()));self.image_width.blockSignals(False)

    def resize_image(self,width):
        c=self.editor.selected_image
        if c is None or self.editor.image_cursor(c.selectionStart()) is None:return
        fmt=c.charFormat().toImageFormat()
        if fmt.width()<=0 or fmt.height()<=0:return
        width=max(40,min(3200,float(width)))
        if abs(width-fmt.width())<.1:return
        ratio=fmt.height()/fmt.width();fmt.setWidth(width);fmt.setHeight(width*ratio)
        c.beginEditBlock();c.setCharFormat(fmt);c.endEditBlock()
        self.editor.setTextCursor(c);self.editor.selected_image=c
        self.image_controls();self.editor.viewport().update()

    def image_original(self):
        c=self.editor.selected_image
        if c is None:return
        key=QUrl(c.charFormat().toImageFormat().name()).path().lstrip('/')
        blob=self.session.note_assets.get(key)
        if blob:
            image=checked_image(blob)
            if not image.isNull():self.resize_image(image.width())

    def bind(self,session):
        self.loading=True;self.session=session
        self.editor.clear();self.editor.document().clearUndoRedoStacks()
        if session:
            if not session.notebooks:
                session.notebooks=[{'id':'main','title':session.source.stem[:120],'html':session.notes_html}]
                session.active_note='main'
            self.refresh_selector()
            for key,blob in session.note_assets.items():
                image=checked_image(blob,preview=True)
                if image.isNull():raise ValueError('笔记中的图片无法读取或尺寸过大。')
                self.editor.document().addResource(QTextDocument.ImageResource,QUrl('studypdf-image:/'+key),image)
            self.editor.setHtml(session.notes_html)
            self.title.setText(session.source.stem+' · 笔记')
        self.editor.document().clearUndoRedoStacks()
        self.loading=False;self.setEnabled(session is not None)

    def refresh_selector(self):
        self.note_selector.blockSignals(True)
        self.note_selector.clear()
        if self.session:
            for note in self.session.notebooks:self.note_selector.addItem(note['title'],note['id'])
            index=self.note_selector.findData(self.session.active_note)
            self.note_selector.setCurrentIndex(max(0,index))
        self.note_selector.blockSignals(False)

    def choices(self):
        return [(note['id'],note['title']) for note in self.session.notebooks] if self.session else []

    def choose_index(self,index):
        ident=self.note_selector.itemData(index)
        if ident:self.select_note(ident)

    def select_note(self,ident):
        if not self.session or ident==self.session.active_note:return
        self.sync()
        note=next((n for n in self.session.notebooks if n['id']==ident),None)
        if note is None:return
        self.loading=True
        self.session.active_note=ident;self.session.notes_html=note['html']
        self.editor.setHtml(note['html']);self.editor.document().clearUndoRedoStacks()
        self.refresh_selector();self.loading=False
        self.on_changed()

    def new_note(self,title=None):
        if not self.session:return None
        if len(self.session.notebooks)>=100:self.failed.emit('每份 PDF 最多 100 篇笔记。');return None
        self.sync()
        note={'id':uuid.uuid4().hex,'title':(title or f'笔记 {len(self.session.notebooks)+1}')[:120],'html':''}
        self.session.notebooks.append(note)
        self.select_note(note['id'])
        self.editor.setFocus()
        return note['id']

    def rename_current(self):
        if self.loading or not self.session:return
        if self.note_selector.currentData()!=self.session.active_note:return
        title=self.note_selector.currentText().strip()
        note=next((n for n in self.session.notebooks if n['id']==self.session.active_note),None)
        if not title or len(title)>120:self.refresh_selector();return
        if note and note['title']!=title:
            note['title']=title;self.refresh_selector();self.on_changed()

    def on_changed(self):
        if not self.loading and self.session:
            self.session.notes_revision+=1
            self.status.setText('正在等待自动保存…')
            self.changed.emit()

    def sync(self):
        if self.session:
            text="" if self.editor.document().isEmpty() else self.editor.toHtml()
            total=len(text.encode('utf-8'))+sum(len(n['html'].encode('utf-8')) for n in self.session.notebooks if n['id']!=self.session.active_note)
            if total>2_000_000:raise ValueError('笔记正文总量超过 2 MB，请先导出并精简。')
            self.session.notes_html=text
            for note in self.session.notebooks:
                if note['id']==self.session.active_note:note['html']=text

    def font_format(self,name):
        fmt=QTextCharFormat();current=self.editor.currentCharFormat()
        if name=='bold':fmt.setFontWeight(QFont.Normal if current.fontWeight()>=QFont.Bold else QFont.Bold)
        elif name=='italic':fmt.setFontItalic(not current.fontItalic())
        else:fmt.setFontUnderline(not current.fontUnderline())
        self.editor.mergeCurrentCharFormat(fmt);self.editor.setFocus()

    def heading(self):
        fmt=QTextCharFormat();fmt.setFontPointSize(16);fmt.setFontWeight(QFont.Bold)
        self.editor.mergeCurrentCharFormat(fmt);self.editor.setFocus()

    def body(self):
        fmt=QTextCharFormat();fmt.setFontPointSize(12);fmt.setFontWeight(QFont.Normal);fmt.setFontItalic(False);fmt.setFontUnderline(False)
        self.editor.mergeCurrentCharFormat(fmt);self.editor.setFocus()

    def bullet(self):
        cursor=self.editor.textCursor()
        if cursor.currentList():
            block=cursor.blockFormat();block.setObjectIndex(-1);block.setIndent(0);cursor.setBlockFormat(block)
        else:cursor.insertList(QTextListFormat.ListDisc)
        self.editor.setFocus()

    def source_html(self,page,rect,edited):
        coords=','.join(f'{float(v):.3f}' for v in rect)
        url=f'studypdf://page/{page}?rect={coords}&scope={"work" if edited else "original"}'
        return f'<p><a href="{url}">↗ 第 {page+1} 页 · {"工作副本" if edited else "原稿"}</a></p>'

    def add_quote(self,text,page,rect,edited):
        cursor=self.editor.textCursor();cursor.movePosition(QTextCursor.End)
        cursor.beginEditBlock()
        if cursor.block().length()>1:cursor.insertBlock(QTextBlockFormat(),QTextCharFormat())
        cursor.setCharFormat(QTextCharFormat())
        cursor.insertHtml(self.source_html(page,rect,edited)+'<p style="margin:0 0 8px 0;">'+html.escape(text).replace('\n','<br>')+'</p>')
        cursor.insertBlock(QTextBlockFormat(),QTextCharFormat());cursor.endEditBlock()
        self.editor.setTextCursor(cursor);self.editor.ensureCursorVisible();self.editor.setFocus()

    def insert_image(self,image,page=None,rect=None,edited=True):
        try:
            if self.session is None:return
            if image.isNull():raise ValueError('无法读取这张图片。')
            if image.width()>1600 or image.height()>1600:image=image.scaled(1600,1600,Qt.KeepAspectRatio,Qt.SmoothTransformation)
            data=QByteArray();buffer=QBuffer(data);buffer.open(QIODevice.WriteOnly)
            if not image.save(buffer,'PNG'):raise ValueError('无法保存笔记图片。')
            blob=bytes(data);key=hashlib.sha256(blob).hexdigest()
            pool=self.session.note_assets
            if key not in pool and (len(pool)>=400 or len(blob)>8_000_000 or sum(map(len,pool.values()))+len(blob)>16_000_000):
                raise ValueError('笔记图片已达到容量限制（16 MB / 400 张），请先导出笔记并减少图片。')
            pool[key]=blob
            name=QUrl('studypdf-image:/'+key)
            self.editor.document().addResource(QTextDocument.ImageResource,name,image.scaled(600,600,Qt.KeepAspectRatio,Qt.SmoothTransformation) if max(image.width(),image.height())>600 else image)
            cursor=self.editor.textCursor()
            cursor.beginEditBlock()
            if cursor.hasSelection():cursor.removeSelectedText()
            if page is not None:
                cursor.movePosition(QTextCursor.End)
                if cursor.block().length()>1:cursor.insertBlock()
                cursor.insertHtml(self.source_html(page,rect,edited));cursor.insertBlock()
            if cursor.block().length()>1:cursor.insertBlock(QTextBlockFormat(),QTextCharFormat())
            cursor.setCharFormat(QTextCharFormat())
            fmt=QTextImageFormat();fmt.setName(name.toString())
            width=min(image.width(),max(120,self.editor.viewport().width()-24))
            fmt.setWidth(width);fmt.setHeight(width*image.height()/image.width())
            cursor.insertImage(fmt);cursor.insertBlock(QTextBlockFormat(),QTextCharFormat());cursor.endEditBlock()
            self.editor.setTextCursor(cursor);self.editor.ensureCursorVisible();self.editor.setFocus()
        except Exception as exc:self.failed.emit(str(exc))

    def import_image(self,path=None):
        if not path:path,_=QFileDialog.getOpenFileName(self,'插入笔记图片','','图片 (*.png *.jpg *.jpeg *.bmp)')
        if not path:return
        try:
            reader=QImageReader(path);reader.setAutoTransform(True);size=reader.size()
            if not size.isValid():raise ValueError('图片格式无法读取。')
            if size.width()*size.height()>64_000_000:raise ValueError('原图超过 6400 万像素，请先缩小图片。')
            if size.width()>1600 or size.height()>1600:reader.setScaledSize(size.scaled(QSize(1600,1600),Qt.KeepAspectRatio))
            self.insert_image(reader.read())
        except Exception as exc:self.failed.emit(str(exc))

    def follow_link(self,url):
        try:
            parsed=urlparse(url);page=int(parsed.path.strip('/'))
            rect=[float(v) for v in parse_qs(parsed.query)['rect'][0].split(',')]
            if self.session and 0<=page<len(self.session.doc) and len(rect)==4 and all(math.isfinite(v) for v in rect):self.jump.emit(page,rect)
        except (ValueError,KeyError):pass

    def export(self):
        if not self.session:return
        path,_=QFileDialog.getSaveFileName(self,'导出独立笔记',str(self.session.source.with_name(self.session.source.stem+'_笔记.html')),'HTML (*.html)')
        if not path:return
        if not path.lower().endswith('.html'):path+='.html'
        try:
            self.sync();body=self.session.notes_html
            for key,blob in self.session.note_assets.items():
                body=body.replace('studypdf-image:/'+key,'data:image/png;base64,'+base64.b64encode(blob).decode())
            def link(match):
                parsed=urlparse(match.group(1));page=int(parsed.path.strip('/'))+1
                return 'href="'+html.escape(self.session.source.as_uri()+f'#page={page}',quote=True)+'"'
            body=re.sub(r'href="(studypdf://[^"]+)"',link,body)
            atomic_write(path,body.encode('utf-8'));self.status.setText('笔记已导出为包含图片的独立 HTML 文件。')
        except Exception as exc:self.failed.emit(str(exc))
