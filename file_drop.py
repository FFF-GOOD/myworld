"""Open local PDF drops across child viewports without forwarding them to the scene.
SPDX-License-Identifier: AGPL-3.0-only
"""
from pathlib import Path
from PySide6.QtCore import QObject,QEvent,Qt,QTimer
from PySide6.QtWidgets import QApplication,QWidget

DRAG_EVENTS={QEvent.DragEnter,QEvent.DragMove,QEvent.Drop}

def local_pdf_paths(mime):
    """Preserve URL decoding, Unicode/UNC paths and order; never fetch remote URLs."""
    if not mime.hasUrls():return []
    paths=[];seen=set()
    for url in mime.urls():
        if not url.isLocalFile():continue
        path=Path(url.toLocalFile())
        if path.suffix.lower()!='.pdf' or not path.is_file():continue
        key=str(path.resolve())
        if key not in seen:seen.add(key);paths.append(key)
    return paths

class PDFFileDropFilter(QObject):
    def __init__(self,window):
        super().__init__(window)
        self.window=window;self.pending=None;self.attached=True
        QApplication.instance().installEventFilter(self)

    def eventFilter(self,obj,event):
        if event.type() not in DRAG_EVENTS:return False
        if not isinstance(obj,QWidget) or not (obj is self.window or self.window.isAncestorOf(obj)):return False
        surface=obj.window()
        if surface is not self.window and surface is not getattr(self.window,'note_dock',None):return False
        if QApplication.activeModalWidget() is not None:return False
        paths=local_pdf_paths(event.mimeData())
        if not paths:return False  # Leave notebook image/text drops to their native handlers.
        if (self.window.busy or self.pending is not None
                or not event.possibleActions()&Qt.CopyAction):
            event.ignore();return True
        event.setDropAction(Qt.CopyAction);event.accept()
        if event.type()==QEvent.Drop:
            self.pending=paths
            # Finish native drag/drop before replacing scenes or showing a save/password dialog.
            QTimer.singleShot(0,self.deliver)
        return True

    def deliver(self):
        paths,self.pending=self.pending,None
        if not paths or not self.attached or self.window.busy:return
        self.window.open_file(paths[0])  # Normal unsaved-record and source-hash guards still apply.
        if len(paths)>1:
            self.window.statusBar().showMessage('本次同时拖入多个 PDF，仅打开第一个文件。')

    def detach(self):
        self.attached=False;self.pending=None
        QApplication.instance().removeEventFilter(self)
