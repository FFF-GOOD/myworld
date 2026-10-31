"""Text entry/edit dialog with local-font and PDF-point controls."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor,QFont,QKeySequence,QShortcut,QTextDocument
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QDoubleSpinBox,
                              QPushButton,QTextEdit,QDialogButtonBox,QColorDialog)
from fonts import FONT_FILES,QT_FAMILIES,font_file


def available_fonts():
    return [name for name in FONT_FILES if font_file(name)] + ['内置中文字体']


class TextDialog(QDialog):
    def __init__(self,parent,defaults=None,rect=None,bounds=None):
        super().__init__(parent)
        defaults=defaults or {}
        self.setWindowTitle('添加 / 编辑文本')
        self.resize(650,400)
        self.rect = rect
        self.bounds = bounds
        layout=QVBoxLayout(self)
        row=QHBoxLayout();layout.addLayout(row)
        row.addWidget(QLabel('字体'))
        self.font_box=QComboBox();self.font_box.addItems(available_fonts());row.addWidget(self.font_box,1)
        if defaults.get('font') not in [self.font_box.itemText(i) for i in range(self.font_box.count())] and defaults.get('font'):
            self.font_box.addItem(defaults['font'])
        self.font_box.setCurrentText(defaults.get('font',self.font_box.itemText(0)))
        row.addWidget(QLabel('字号'))
        self.size_box=QDoubleSpinBox();self.size_box.setRange(4,144);self.size_box.setSuffix(' pt');self.size_box.setValue(defaults.get('size',14));row.addWidget(self.size_box)
        self.color=QColor.fromRgbF(*defaults.get('color',(0.12,0.14,0.18)))
        self.color_button=QPushButton('字体颜色');self.color_button.clicked.connect(self.pick_color);row.addWidget(self.color_button)
        if rect is not None:
            box_row=QHBoxLayout();layout.addLayout(box_row)
            box_row.addWidget(QLabel('文本框宽'))
            self.box_width=QDoubleSpinBox();self.box_width.setRange(4,max(4,bounds[2]-rect[0]));self.box_width.setValue(rect[2]-rect[0]);self.box_width.setSuffix(' pt');box_row.addWidget(self.box_width)
            box_row.addWidget(QLabel('高'))
            self.box_height=QDoubleSpinBox();self.box_height.setRange(4,max(4,bounds[3]-rect[1]));self.box_height.setValue(rect[3]-rect[1]);self.box_height.setSuffix(' pt');box_row.addWidget(self.box_height)
            box_row.addStretch()
            self.fit_label=QLabel();layout.addWidget(self.fit_label)
            self.box_width.valueChanged.connect(self.refresh_fit);self.box_height.valueChanged.connect(self.refresh_fit)
        self.editor=QTextEdit();self.editor.setAcceptRichText(False);self.editor.setPlainText(defaults.get('text',''));layout.addWidget(self.editor,1)
        note=QLabel('Enter 换行 · Ctrl+Enter 确定 · 双击新增文本可再次编辑。文本框大小在页面上拖动框选。')
        note.setWordWrap(True);layout.addWidget(note)
        self.buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText('确定')
        self.buttons.button(QDialogButtonBox.Cancel).setText('取消')
        self.buttons.accepted.connect(self.accept);self.buttons.rejected.connect(self.reject);layout.addWidget(self.buttons)
        self.font_box.currentTextChanged.connect(self.preview);self.size_box.valueChanged.connect(self.preview)
        self.editor.textChanged.connect(self.refresh_fit)
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(bool(self.editor.toPlainText().strip()))
        self.shortcut=QShortcut(QKeySequence('Ctrl+Return'),self);self.shortcut.activated.connect(self.accept_if_text)
        self.preview();self.editor.setFocus()

    def accept_if_text(self):
        if self.buttons.button(QDialogButtonBox.Ok).isEnabled():self.accept()

    def pick_color(self):
        color=QColorDialog.getColor(self.color,self,'字体颜色')
        if color.isValid():self.color=color;self.preview()

    def preview(self):
        family=QT_FAMILIES.get(self.font_box.currentText(),self.font_box.currentText())
        if family=='内置中文字体':family='sans-serif'
        font=QFont(family);font.setPointSizeF(self.size_box.value());self.editor.setFont(font)
        self.editor.setStyleSheet(f'QTextEdit {{ color:{self.color.name()}; background:white; }}')
        self.color_button.setStyleSheet(f'color:{self.color.name()};')
        self.refresh_fit()

    def refresh_fit(self):
        if not hasattr(self,'buttons'):return
        valid = bool(self.editor.toPlainText().strip())
        if self.rect is not None:
            import html
            family=QT_FAMILIES.get(self.font_box.currentText(),self.font_box.currentText())
            if family=='内置中文字体':family='sans-serif'
            doc=QTextDocument();doc.setDocumentMargin(0)
            doc.setDefaultStyleSheet(f'body {{font-family:"{family}";font-size:{self.size_box.value()}px;line-height:125%;margin:0;}}')
            doc.setHtml('<body>'+html.escape(self.editor.toPlainText()).replace('\n','<br>')+'</body>')
            doc.setTextWidth(self.box_width.value())
            height=doc.size().height()
            fits=height<=self.box_height.value()
            self.fit_label.setText(f'预计正文高度 {height:.1f} pt'+(' · 文本框可容纳' if fits else ' · 高度不足，请增大文本框或调小字号'))
            self.fit_label.setStyleSheet('color:#6a6570;' if fits else 'color:#c33e4b;')
            valid = valid and fits
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(valid)

    def data(self):
        data={'text':self.editor.toPlainText(),'font':self.font_box.currentText(),'size':self.size_box.value(),
                'color':(self.color.redF(),self.color.greenF(),self.color.blueF())}
        if self.rect is not None:
            data['rect']=[self.rect[0],self.rect[1],self.rect[0]+self.box_width.value(),self.rect[1]+self.box_height.value()]
        return data
