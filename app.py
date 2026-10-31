"""myworld desktop application. SPDX-License-Identifier: AGPL-3.0-only"""
from __future__ import annotations
from collections import OrderedDict
from pathlib import Path
import json
import math
import sys
import time

import pymupdf as pdf
from PySide6.QtCore import QByteArray, QEvent, QEventLoop, QLibraryInfo, QPointF, QRectF, Qt, QTimer, QTranslator, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QFont, QFontDatabase, QIcon, QImage, QKeySequence, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QTransform
from PySide6.QtWidgets import QApplication, QComboBox, QDoubleSpinBox, QFileDialog, QGraphicsScene, QGraphicsView, QGraphicsTextItem, QGraphicsPolygonItem, QDockWidget, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QProgressDialog, QPushButton, QSpinBox, QSplitter, QTabWidget, QSizePolicy, QToolBar, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget
from core import Session, MARKUPS, LABELS, as_quad, display_matrix, quad_list, read_project
from rendering import RenderService
from icons import icon
from fonts import QT_FAMILIES
from text_dialog import available_fonts
from inline_text import InlineTextBox
from notebook import Notebook
from floating_tools import ColorPopover,SelectionTools
from project_links import discover, remember
from brand import APP_NAME, VERSION
from comment_cards import CommentManager


class HighlightItem(QGraphicsPolygonItem):
    def paint(self,painter,option,widget=None):
        painter.save()
        painter.setCompositionMode(QPainter.CompositionMode_Multiply)
        super().paint(painter,option,widget)
        painter.restore()


class ClippedTextItem(QGraphicsTextItem):
    def __init__(self, op):
        super().__init__()
        self.box = pdf.Rect(op['rect'])
        family = QT_FAMILIES.get(op['font'],op['font'])
        if family == '内置中文字体': family = 'sans-serif'
        self.document().setDocumentMargin(0)
        self.document().setDefaultStyleSheet(f'body {{font-family:"{family}";font-size:{op["size"]}px;line-height:125%;margin:0;}}')
        import html
        color = QColor.fromRgbF(*op['color']).name()
        self.setHtml(f'<body style="color:{color}">'+html.escape(op['text']).replace('\n','<br>')+'</body>')
        self.setTextWidth(self.box.width)

    def boundingRect(self):
        return QRectF(self.box.x0,self.box.y0,self.box.width,self.box.height)

    def paint(self, painter, option, widget=None):
        painter.save()
        painter.setClipRect(self.boundingRect())
        painter.translate(self.box.x0,self.box.y0)
        self.document().drawContents(painter,QRectF(0,0,self.box.width,self.box.height))
        painter.restore()


class PDFView(QGraphicsView):
    moved = Signal(object)
    operation = Signal(str, int, object)
    zoom_requested = Signal(float)
    selection_changed = Signal(str)
    annotation_selected = Signal(object)
    activated = Signal(object)
    text_requested = Signal(int, object)
    capture_requested = Signal(int, object)

    def __init__(self, edited=False):
        super().__init__()
        self.edited = edited
        self.session = None
        self.zoom = 1.
        self.rotation = 0
        self.tool = "select"
        self.color = (1., .78, .12)
        self.width = 2.
        self.pages = []
        self.cache = OrderedDict()
        self.overlays = {}
        self.wanted = {}
        self.temporary = []
        self.drag_items = []
        self.drag = None
        self.selection_text = ""
        self.selection_quads = []
        self.selection_page = None
        self.inline_editor = None
        self.editor_drag = None
        self.setScene(QGraphicsScene(self))
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setBackgroundBrush(QColor("#e5e8ee"))
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setMouseTracking(True)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.render_visible)
        for bar in (self.horizontalScrollBar(), self.verticalScrollBar()):
            bar.valueChanged.connect(self.scrolled)
        self.set_mode("select")

    def set_mode(self, mode):
        self.cancel_drag()
        self.tool = mode
        effective = self.effective_tool()
        self.setDragMode(QGraphicsView.ScrollHandDrag if effective == "hand" else QGraphicsView.NoDrag)
        self.setCursor(Qt.OpenHandCursor if effective == "hand" else Qt.IBeamCursor if effective in {"select", "highlight", "underline", "strike"} else Qt.CrossCursor)

    def effective_tool(self):
        return "hand" if not self.edited and self.tool in {"rect", "brush"} else self.tool

    def configure(self, session, rotation, zoom):
        self.cancel_drag()
        self.clear_selection()
        self.scene().clear()
        self.pages.clear()
        self.cache.clear()
        self.overlays.clear()
        self.wanted.clear()
        self.session, self.rotation, self.zoom = session, rotation, zoom
        if session is None:
            return
        sizes = [page.rect * pdf.Matrix(1, 1).prerotate(rotation) for page in session.doc]
        max_width = max(size.width for size in sizes)
        y = 24.
        for number, size in enumerate(sizes):
            rect = QRectF(24 + (max_width-size.width)/2, y, size.width, size.height)
            self.scene().addRect(rect, QPen(QColor("#c6cdd8")), QColor("white"))
            self.pages.append({"rect": rect, "matrix": display_matrix(session.doc[number], rotation), "pix": None, "loading":None})
            y += size.height + 20
        self.scene().setSceneRect(0, 0, max_width+48, y+4)
        self.setTransform(QTransform.fromScale(zoom, zoom))
        self.timer.start(0)
        if hasattr(self,"comments"):self.comments.schedule()

    def scrolled(self):
        if hasattr(self.window(),'hide_context'):self.window().hide_context()
        self.timer.start(35)
        self.moved.emit(self)

    def resizeEvent(self, event):
        if hasattr(self.window(),'hide_context'):self.window().hide_context()
        super().resizeEvent(event)
        if hasattr(self, "timer"):
            self.timer.start(65)

    def invalidate(self, number=None):
        for index in list(self.cache) if number is None else [number]:
            self.cache.pop(index, None)
            self.wanted.pop(index, None)
            item = self.pages[index]["pix"]
            if item is not None:
                self.scene().removeItem(item)
                self.pages[index]["pix"] = None
            self.remove_items(self.overlays.pop(index, []))

    def render_visible(self):
        if not self.session:
            return
        service = self.window().renderer
        if service.session is not self.session:
            return
        visible = self.mapToScene(self.viewport().rect()).boundingRect().adjusted(0, -100, 0, 100)
        numbers = {n for n,entry in enumerate(self.pages) if entry["rect"].intersects(visible)}
        service.retain(self, numbers)
        for number in list(self.overlays):
            if number not in numbers and number not in self.cache:
                self.remove_items(self.overlays.pop(number))
        for number in sorted(numbers, key=lambda n: abs(self.pages[n]["rect"].center().y()-visible.center().y())):
            entry = self.pages[number]
            rect = entry["rect"]
            scale = min(max(self.zoom*self.devicePixelRatioF(), .5), 2.5,
                        math.sqrt(8_000_000/(rect.width()*rect.height())),
                        12000/max(rect.width(), rect.height()))
            ops = self.session.raster_ops(number, self.edited)
            key = (round(scale,5), self.rotation, tuple(op["id"] for op in ops))
            self.wanted[number] = key
            if entry['pix'] is None and entry['loading'] is None:
                item = self.scene().addText(f'第 {number+1} 页 · 正在加载…')
                item.setDefaultTextColor(QColor('#8a8090'))
                item.setPos(rect.left()+20,rect.top()+20)
                item.setZValue(1)
                entry['loading'] = item
            if entry.get("key") != key or entry["pix"] is None:
                service.request(self, number, key, scale, self.rotation, ops)
            if number not in self.overlays:
                self.refresh_overlays(number)
            if number in self.cache:
                self.cache.move_to_end(number)
        while len(self.cache) > 12 or (sum(self.cache.values()) > 96_000_000 and len(self.cache) > 2):
            candidates = [n for n in self.cache if n not in numbers]
            if not candidates: break
            self.invalidate(candidates[0])

    def accept_render(self, number, key, image):
        if self.wanted.get(number) != key:
            self.window().renderer.metrics['obsolete'] += 1
            return
        entry = self.pages[number]
        if entry['loading'] is not None:
            self.scene().removeItem(entry['loading']);entry['loading']=None
        if entry['pix'] is not None:
            self.scene().removeItem(entry['pix'])
        item = self.scene().addPixmap(QPixmap.fromImage(image))
        item.setPos(entry['rect'].topLeft())
        item.setScale(1/key[0])
        item.setZValue(1)
        entry['pix'], entry['key'] = item, key
        self.cache[number] = image.width()*image.height()*4
        self.refresh_overlays(number)

    def refresh_overlays(self, number):
        self.remove_items(self.overlays.pop(number, []))
        if not self.session: return
        adds,hidden,regions = self.session.effective(number, self.edited)
        items = []
        # Erasing is visible immediately; the background process resolves complex objects separately.
        if regions:
            path = QPainterPath()
            path.setFillRule(Qt.WindingFill)
            for region in regions:
                quad = pdf.Quad(region.tl,region.tr,region.bl,region.br)
                path.addPolygon(QPolygonF([self.to_scene(number,p) for p in (quad.ul,quad.ur,quad.lr,quad.ll)]))
                path.closeSubpath()
            item = self.scene().addPath(path,QPen(Qt.NoPen),QColor('white'))
            item.setZValue(2);items.append(item)
        for op in adds.values():
            color = QColor.fromRgbF(*op['color'])
            kind = op['kind']
            if kind == 'text':
                if self.inline_editor and self.inline_editor.existing and self.inline_editor.existing['id']==op['id']:continue
                item = ClippedTextItem(op)
                m = self.pages[number]['matrix']
                item.setTransform(QTransform(m.a,m.b,m.c,m.d,m.e,m.f))
                item.setPos(self.pages[number]['rect'].topLeft())
                self.scene().addItem(item)
                item.setZValue(3);items.append(item)
            elif kind == 'ink':
                path = QPainterPath(self.to_scene(number,op['points'][0]))
                for point in op['points'][1:]:path.lineTo(self.to_scene(number,point))
                item = self.scene().addPath(path,QPen(color,op['width'],Qt.SolidLine,Qt.RoundCap,Qt.RoundJoin))
                item.setZValue(3);items.append(item)
            else:
                for values in op['quads']:
                    q = as_quad(values)
                    if kind == 'highlight':
                        color.setAlphaF(.38)
                        poly = QPolygonF([self.to_scene(number,p) for p in (q.ul,q.ur,q.lr,q.ll)])
                        item = HighlightItem(poly)
                        item.setPen(QPen(Qt.NoPen));item.setBrush(color);self.scene().addItem(item)
                    else:
                        start,end = (q.ll,q.lr) if kind=='underline' else ((q.ul+q.ll)/2,(q.ur+q.lr)/2)
                        a,b = self.to_scene(number,start),self.to_scene(number,end)
                        item = self.scene().addLine(a.x(),a.y(),b.x(),b.y(),QPen(color,1.1))
                    item.setZValue(3);items.append(item)
        self.overlays[number] = items

    def current_page(self):
        if not self.pages:
            return 0
        point = self.mapToScene(self.viewport().rect().center())
        return min(range(len(self.pages)), key=lambda i: abs(self.pages[i]["rect"].center().y()-point.y()))

    def goto(self, page):
        rect = self.pages[page]["rect"]
        self.centerOn(rect.center().x(), rect.top()+self.viewport().height()/self.zoom/2-10)

    def page_at(self, point):
        for number, entry in enumerate(self.pages):
            if entry["rect"].contains(point):
                return number
        return None

    def to_pdf(self, page, point):
        entry = self.pages[page]
        local = point-entry["rect"].topLeft()
        return pdf.Point(local.x(), local.y()) * ~entry["matrix"]

    def to_scene(self, page, point):
        result = pdf.Point(point) * self.pages[page]["matrix"]
        return QPointF(result.x, result.y)+self.pages[page]["rect"].topLeft()

    def draw_quad(self, page, values, fill, outline=None, temporary=True):
        quad = as_quad(values)
        poly = QPolygonF([self.to_scene(page, p) for p in (quad.ul, quad.ur, quad.lr, quad.ll)])
        pen = QPen(outline, 1.2/self.zoom) if outline else QPen(Qt.NoPen)
        item = self.scene().addPolygon(poly, pen, fill)
        item.setZValue(5)
        (self.temporary if temporary else self.drag_items).append(item)
        return item

    def draw_rect(self, page, coords, color, temporary=False, outline=None):
        rect = pdf.Rect(coords)
        quad = pdf.Quad(rect.tl, rect.tr, rect.bl, rect.br)
        return self.draw_quad(page, quad_list(quad), color, outline, temporary)

    def remove_items(self, items):
        for item in items:
            self.scene().removeItem(item)
        items.clear()

    def clear_selection(self):
        self.remove_items(self.temporary)
        self.selection_text = ""
        self.selection_quads = []
        self.selection_page = None

    def cancel_drag(self):
        self.remove_items(self.drag_items)
        self.drag = None

    def select_text(self, page, start, end):
        self.clear_selection()
        hidden = self.session.effective(page, self.edited)[2]
        index = self.session._text_cache.get(page)
        if index is None:
            self.window().statusBar().showMessage("本页文字正在后台加载，请稍后选择。")
            return [], ""
        quads, text = index.select(start, end, hidden)
        self.selection_page, self.selection_quads, self.selection_text = page, quads, text
        for quad in quads:
            self.draw_quad(page, quad, QColor(65, 125, 240, 65))
        return quads, text

    def erase_segment(self, point):
        drag = self.drag
        page = drag["page"]
        here = self.to_pdf(page, point)
        last = drag.get("last", here)
        radius = self.width/2
        steps = min(500, max(1, math.ceil(abs(here-last)/max(radius, 2))))
        bounds = self.session.doc[page].rect * self.session.doc[page].derotation_matrix
        for i in range(1, steps+1):
            p = last+(here-last)*(i/steps)
            region = pdf.Rect(p.x-radius, p.y-radius, p.x+radius, p.y+radius) & bounds
            if not region.is_empty:
                drag["rects"].append(list(region))
                if 'brush_path' not in drag:
                    drag['brush_path'] = QPainterPath()
                    drag['brush_path'].setFillRule(Qt.WindingFill)
                    drag['brush_item'] = self.scene().addPath(drag['brush_path'],QPen(Qt.NoPen),QColor('white'))
                    drag['brush_item'].setZValue(5)
                    self.drag_items.append(drag['brush_item'])
                q = pdf.Quad(region.tl,region.tr,region.bl,region.br)
                drag['brush_path'].addPolygon(QPolygonF([self.to_scene(page,p) for p in (q.ul,q.ur,q.lr,q.ll)]))
                drag['brush_path'].closeSubpath()
        if "brush_item" in drag: drag["brush_item"].setPath(drag["brush_path"])
        drag["last"] = here

    def mousePressEvent(self, event):
        if hasattr(self.window(),'hide_context'):self.window().hide_context()
        if self.inline_editor and event.button()==Qt.LeftButton:
            point=self.mapToScene(event.position().toPoint())
            editor=self.inline_editor;at=self.to_pdf(editor.page,point);r=pdf.Rect(editor.rect)
            margin=6/self.zoom
            if (r+(-margin,-margin,margin,margin)).contains(at):
                if abs(at.x-r.x1)<margin and abs(at.y-r.y1)<margin:
                    self.editor_drag={'kind':'resize','start':at,'rect':list(r)}
                    event.accept();return
                if min(abs(at.x-r.x0),abs(at.x-r.x1),abs(at.y-r.y0),abs(at.y-r.y1))<2/self.zoom:
                    self.editor_drag={'kind':'move','start':at,'rect':list(r)}
                    event.accept();return
                super().mousePressEvent(event);return
            if not self.window().finish_inline():event.accept();return
        if self.session: self.activated.emit(self)
        if event.button() == Qt.RightButton:
            self.cancel_drag()
        if self.session and event.button() == Qt.LeftButton and self.effective_tool() != "hand":
            self.setFocus()
            point = self.mapToScene(event.position().toPoint())
            page = self.page_at(point)
            if page is not None:
                self.clear_selection()
                self.drag = {"page": page, "start": point, "rects": [], "points": [list(self.to_pdf(page, point))]}
                if self.effective_tool() == "brush":
                    self.erase_segment(point)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.inline_editor and self.editor_drag:
            editor=self.inline_editor;drag=self.editor_drag
            at=self.to_pdf(editor.page,self.mapToScene(event.position().toPoint()));delta=at-drag['start']
            r=pdf.Rect(drag['rect']);bounds=self.session.doc[editor.page].rect*self.session.doc[editor.page].derotation_matrix
            if drag['kind']=='move':
                dx=max(bounds.x0-r.x0,min(delta.x,bounds.x1-r.x1));dy=max(bounds.y0-r.y0,min(delta.y,bounds.y1-r.y1))
                r=r+(dx,dy,dx,dy)
            else:r.x1=max(r.x0+24,min(bounds.x1,r.x1+delta.x));r.y1=max(r.y0+20,min(bounds.y1,r.y1+delta.y))
            editor.set_rect(list(r));event.accept();return
        if self.inline_editor:
            super().mouseMoveEvent(event);return
        if not self.drag:
            super().mouseMoveEvent(event)
            return
        drag = self.drag
        page = drag["page"]
        box = self.pages[page]["rect"]
        point = self.mapToScene(event.position().toPoint())
        point = QPointF(max(box.left(), min(point.x(), box.right())), max(box.top(), min(point.y(), box.bottom())))
        mode = self.effective_tool()
        if mode == "brush":
            if len(drag["rects"]) < 19500:
                self.erase_segment(point)
        elif mode in {"rect", "text", "capture"}:
            self.remove_items(self.drag_items)
            rect = pdf.Rect(self.to_pdf(page, drag["start"]), self.to_pdf(page, point)).normalize()
            drag["rects"] = [list(rect)]
            self.draw_rect(page, rect, QColor(142,52,140,20) if mode in {"text","capture"} else QColor("white"), outline=QColor("#8e348c") if mode in {"text","capture"} else None)
        elif mode == "ink":
            p = self.to_pdf(page, point)
            last = pdf.Point(drag["points"][-1])
            if abs(p-last) > .5 and len(drag["points"]) < 20000:
                drag["points"].append(list(p))
                path = QPainterPath(self.to_scene(page, last))
                path.lineTo(self.to_scene(page, p))
                item = self.scene().addPath(path, QPen(QColor.fromRgbF(*self.color), self.width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                item.setZValue(6)
                self.drag_items.append(item)
        else:
            self.select_text(page, self.to_pdf(page, drag["start"]), self.to_pdf(page, point))
        event.accept()

    def mouseReleaseEvent(self, event):
        if self.inline_editor:
            if self.editor_drag:
                self.editor_drag=None;event.accept();return
            super().mouseReleaseEvent(event);return
        if self.drag and event.button() == Qt.LeftButton:
            drag = self.drag
            page, mode = drag["page"], self.effective_tool()
            end = self.mapToScene(event.position().toPoint())
            moved = abs(end.x()-drag["start"].x())+abs(end.y()-drag["start"].y()) > 3/self.zoom
            if mode in {"select", "highlight", "underline", "strike"}:
                if moved:
                    self.select_text(page, self.to_pdf(page, drag["start"]), self.to_pdf(page, end))
                    if mode != "select":
                        quads = list(self.selection_quads)
                        if not quads and page in self.session._text_cache:
                            rect = pdf.Rect(self.to_pdf(page, drag["start"]), self.to_pdf(page, end)).normalize()
                            bounds = self.session.doc[page].rect * self.session.doc[page].derotation_matrix
                            rect &= bounds
                            if rect.width > 1 and rect.height > 1:
                                quads = [quad_list(pdf.Quad(rect.tl, rect.tr, rect.bl, rect.br))]
                        if quads:
                            self.operation.emit(mode, page, {"quads": quads, "color": self.color})
                        self.clear_selection()
                    else:
                        self.selection_changed.emit(self.selection_text)
                else:
                    p = self.to_pdf(page, end)
                    hits = [a for a in self.session.annotations(page, self.edited) if pdf.Rect(a["rect"]).contains(p)]
                    self.annotation_selected.emit(hits[-1] if hits else None)
            elif mode == "capture" and drag['rects']:
                rect=drag['rects'][0]
                self.cancel_drag()
                self.capture_requested.emit(page,rect)
            elif mode == "text":
                if moved and drag["rects"]:
                    rect = pdf.Rect(drag["rects"][0])
                else:
                    start = self.to_pdf(page, drag["start"])
                    bounds = self.session.doc[page].rect*self.session.doc[page].derotation_matrix
                    rect = pdf.Rect(start.x,start.y,min(start.x+260,bounds.x1),min(start.y+110,bounds.y1))
                existing = None
                if not moved:
                    at = self.to_pdf(page,drag['start'])
                    existing = next((op for op in reversed(list(self.session.effective(page,self.edited)[0].values())) if op['kind']=='text' and pdf.Rect(op['rect']).contains(at)),None)
                self.cancel_drag()
                if existing: self.window().edit_text(self,page,list(existing['rect']),existing)
                else: self.text_requested.emit(page,list(rect))
            elif mode in {"rect", "brush"} and drag["rects"]:
                self.operation.emit("erase", page, {"rects": drag["rects"]})
            elif mode == "ink" and len(drag["points"]) >= 2:
                self.operation.emit("ink", page, {"points": drag["points"], "color": self.color, "width": self.width})
            self.cancel_drag()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self.session and event.button()==Qt.LeftButton:
            self.cancel_drag()
            self.activated.emit(self)
            point = self.mapToScene(event.position().toPoint())
            number = self.page_at(point)
            if number is not None:
                p = self.to_pdf(number,point)
                for op in reversed(list(self.session.effective(number,self.edited)[0].values())):
                    if op['kind']=='text' and pdf.Rect(op['rect']).contains(p):
                        self.window().edit_text(self,number,list(op['rect']),op)
                        event.accept()
                        return
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            self.zoom_requested.emit(1.15 if event.angleDelta().y() > 0 else 1/1.15)
            event.accept()
        elif self.drag:
            event.accept()
        else:
            super().wheelEvent(event)

    def event(self,event):
        if event.type()==QEvent.ShortcutOverride and getattr(self,'inline_editor',None):
            if not event.modifiers()&Qt.ControlModifier or any(event.matches(seq) for seq in (QKeySequence.Copy,QKeySequence.Cut,QKeySequence.Paste,QKeySequence.SelectAll,QKeySequence.Undo,QKeySequence.Redo)) or event.key() in (Qt.Key_Return,Qt.Key_Enter,Qt.Key_Escape):
                event.accept();return True
        return super().event(event)

    def keyPressEvent(self, event):
        if self.inline_editor:
            super().keyPressEvent(event);return
        if event.matches(QKeySequence.Copy):
            self.copy_selection()
            event.accept()
        elif event.key() == Qt.Key_Escape:
            self.cancel_drag()
            self.clear_selection()
            event.accept()
        else:
            super().keyPressEvent(event)

    def copy_selection(self):
        if self.session and self.session.can_copy and self.selection_text:
            QApplication.clipboard().setText(self.selection_text)

    def contextMenuEvent(self, event):
        if self.inline_editor:
            super().contextMenuEvent(event);return
        menu = QMenu(self)
        copy = menu.addAction("复制所选文字", self.copy_selection)
        copy.setEnabled(bool(self.selection_text and self.session and self.session.can_copy))
        quote=menu.addAction('摘录到笔记',lambda:self.window().quote_selection(self))
        quote.setEnabled(bool(self.selection_text and self.session and self.session.can_copy))
        menu.exec(event.globalPos())


class Pane(QWidget):
    def __init__(self, edited):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        title = QLabel("工作副本  ·  批注与擦除" if edited else "原始 PDF  ·  支持批注，保存原稿后写回")
        self.title = title
        title.setObjectName("editedTitle" if edited else "originalTitle")
        title.setMargin(10)
        header=QWidget();row=QHBoxLayout(header);row.setContentsMargins(0,0,5,0);row.setSpacing(2)
        title.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred)
        row.addWidget(title,1)
        self.swap_button=QPushButton('⇄ 交换两栏');self.swap_button.setFlat(True)
        self.swap_button.setFocusPolicy(Qt.NoFocus)
        self.swap_button.setToolTip('交换原始 PDF 与工作副本的位置 · Ctrl+Shift+X')
        row.addWidget(self.swap_button)
        layout.addWidget(header)
        self.view = PDFView(edited)
        layout.addWidget(self.view)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.session = None
        self.renderer = RenderService(self)
        self.renderer.ready.connect(self.render_ready)
        self.renderer.failed.connect(lambda message:self.statusBar().showMessage("后台渲染："+message))
        self.zoom, self.rotation = 1., 0
        self.locked = False
        self.busy = False
        self.auto_save_blocked = False
        self.layout_dirty = False
        self.autosave_timer=QTimer(self)
        self.autosave_timer.setSingleShot(True)
        self.autosave_timer.timeout.connect(self.autosave)
        self.swapped = False
        self.tool = "select"
        self.selected_annotation = None
        self.last_page = -1
        self.search_results, self.search_at, self.search_query = [], -1, ""
        self.colors = {"highlight": (1., .78, .12), "underline": (.18, .43, .91),
                       "strike": (.92, .22, .23), "ink": (.18, .43, .91), "text": (.12,.14,.18)}
        self.text_defaults = {"font":available_fonts()[0],"size":14,"color":(.12,.14,.18)}
        self.widths = {"ink": 2., "brush": 18.}
        self.resize(1540, 980)
        self.setMinimumSize(1060, 650)
        self.build_toolbars()
        self.bookmarks = QTreeWidget()
        self.bookmarks.setHeaderLabel("目录 / 书签")
        self.bookmarks.itemClicked.connect(self.bookmark_jump)
        self.notes = QTreeWidget()
        self.notes.setHeaderLabel("本页批注 · 选择后可删除")
        self.notes.itemClicked.connect(self.note_clicked)
        tabs = QTabWidget()
        tabs.addTab(self.bookmarks, "书签")
        tabs.addTab(self.notes, "批注")
        tabs.setMinimumWidth(160)
        self.panes = QSplitter(Qt.Horizontal)
        self.original, self.edited = Pane(False), Pane(True)
        self.panes.addWidget(self.original)
        self.panes.addWidget(self.edited)
        self.panes.setChildrenCollapsible(False)
        self.panes.setSizes([650, 650])
        outer = QSplitter(Qt.Horizontal)
        outer.addWidget(tabs)
        outer.addWidget(self.panes)
        outer.setSizes([205, 1335])
        outer.setStretchFactor(1, 1)
        self.setCentralWidget(outer)
        self.notebook=Notebook(self)
        self.notebook.changed.connect(self.note_changed)
        self.notebook.jump.connect(self.center_region)
        self.notebook.failed.connect(self.error)
        self.note_dock=QDockWidget('阅读笔记',self)
        self.note_dock.setObjectName('readingNotebook')
        self.note_dock.setWidget(self.notebook)
        self.note_dock.setMinimumWidth(280)
        self.addDockWidget(Qt.RightDockWidgetArea,self.note_dock)
        self.note_dock.hide()
        self.floating=SelectionTools(self)
        self.palette=ColorPopover(self)
        self.palette.picked.connect(self.apply_chosen_color)
        self.color_target=None
        for view in self.views:view.comments=CommentManager(self,view)
        for pane in (self.original,self.edited):pane.swap_button.clicked.connect(self.swap)
        self.active_view = self.edited.view
        for view in self.views:
            view.activated.connect(self.activate_view)
            view.operation.connect(lambda kind,page,data,v=view:self.view_operation(kind,page,data,v))
            view.annotation_selected.connect(lambda annotation,v=view:self.select_annotation(annotation,v))
            view.capture_requested.connect(lambda page,rect,v=view:self.capture_note(v,page,rect))
            view.text_requested.connect(lambda page,rect,v=view:self.edit_text(v,page,rect))
            view.moved.connect(self.synchronize)
            view.zoom_requested.connect(lambda factor: self.set_zoom(self.zoom*factor))
            view.selection_changed.connect(lambda text,v=view:self.selected_text(text,v))
        self.statusBar().showMessage("打开 PDF 开始阅读。V 选择文字，H 拖动；Ctrl+滚轮缩放。")
        self.reading_status = QLabel("双栏同步")
        self.statusBar().addPermanentWidget(self.reading_status)
        self.setAcceptDrops(True)
        self.refresh()

    @property
    def views(self):
        return [self.original.view, self.edited.view]

    def action(self, label, slot, shortcut=None, symbol=None):
        result = QAction(label, self)
        result.triggered.connect(slot)
        if symbol: result.setIcon(icon(symbol))
        if shortcut:
            result.setShortcut(QKeySequence(shortcut))
        return result

    def build_toolbars(self):
        files = self.addToolBar("文件与阅读")
        files.setMovable(False)
        files.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.open_action = self.action("打开 PDF", self.open_dialog, "Ctrl+O", "open")
        self.load_action = self.action("打开记录", self.load_project, "Ctrl+Shift+O", "load")
        self.save_action = self.action("保存记录", self.save_project, "Ctrl+S", "save")
        self.save_original_action = self.action("保存原稿",self.save_original,"Ctrl+Alt+S","source")
        self.export_action = self.action("导出 PDF", self.export, "Ctrl+E", "export")
        for action in (self.open_action, self.load_action, self.save_action, self.save_original_action, self.export_action):
            files.addAction(action)
        files.addSeparator()
        self.undo_action = self.action("撤销", lambda: self.history(False), "Ctrl+Z", "undo")
        self.redo_action = self.action("重做", lambda: self.history(True), "Ctrl+Y", "redo")
        files.addActions([self.undo_action, self.redo_action])
        self.addAction(self.action("重做", lambda: self.history(True), "Ctrl+Shift+Z"))
        self.swap_action = self.action("交换原稿 / 副本", self.swap, "Ctrl+Shift+X", "swap")
        files.addAction(self.swap_action)
        files.addSeparator()
        self.page_input = QSpinBox()
        self.page_input.setRange(1, 1)
        self.page_input.setKeyboardTracking(False)
        self.page_input.setToolTip("物理页码；书内印刷页标签在底部显示")
        self.page_input.valueChanged.connect(lambda value: self.goto(value-1))
        files.addAction(self.action("‹", lambda: self.step(-1), "Alt+Left"))
        files.addWidget(self.page_input)
        self.page_total = QLabel(" / 0  ")
        files.addWidget(self.page_total)
        files.addAction(self.action("›", lambda: self.step(1), "Alt+Right"))
        files.addSeparator()
        files.addAction(self.action("−", lambda: self.set_zoom(self.zoom/1.2)))
        self.zoom_box = QComboBox()
        self.zoom_box.setEditable(True)
        self.zoom_box.addItems(["50%", "75%", "100%", "125%", "150%", "200%", "300%", "400%"])
        self.zoom_box.setCurrentText("100%")
        self.zoom_box.setMaximumWidth(90)
        self.zoom_box.activated.connect(self.parse_zoom)
        self.zoom_box.lineEdit().returnPressed.connect(self.parse_zoom)
        files.addWidget(self.zoom_box)
        files.addAction(self.action("＋", lambda: self.set_zoom(self.zoom*1.2)))
        files.addAction(self.action("适合宽度", self.fit_width, "Ctrl+0"))
        files.addAction(self.action("旋转", self.rotate, "Ctrl+R"))

        files.addAction(self.action("帮助", self.help))
        self.addToolBarBreak()
        tools = QToolBar("批注和擦除", self)
        tools.setMovable(False)
        tools.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.addToolBar(tools)
        self.copy_action=self.action('复制文字',self.copy_pdf_selection,symbol='copy')
        tools.addAction(self.copy_action)
        group = QActionGroup(self)
        self.tool_actions = {}
        for name, label, key in [("select", "选择文字", "V"), ("hand", "手形移动", "H"),
                                 ("highlight", "高亮", "A"), ("underline", "下划线", "U"),
                                 ("strike", "删除线", "D"), ("text", "添加文本", "T"), ("ink", "自由画笔", "P"),
                                 ("rect", "框选擦除", "R"), ("brush", "橡皮擦", "B"), ("capture", "截图到笔记", "S")]:
            act = self.action(label, lambda checked=False, n=name: self.set_tool(n), key, name)
            act.setCheckable(True)
            act.setChecked(name == "select")
            group.addAction(act)
            tools.addAction(act)
            self.tool_actions[name] = act
        self.quote_action=self.action('摘录到笔记',lambda:self.quote_selection(),'Ctrl+Shift+N','note')
        self.notebook_action=self.action('笔记',self.toggle_notebook,'F8','note')
        tools.addActions([self.quote_action,self.notebook_action])
        self.annotation_tools=tools
        self.addToolBarBreak()
        properties = QToolBar("工具属性",self)
        properties.setMovable(False)
        properties.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.addToolBar(properties)
        self.text_property_actions=[properties.addWidget(QLabel(" 字体 "))]
        self.font_input = QComboBox()
        self.font_input.addItems(available_fonts())
        self.font_input.setMaximumWidth(140)
        self.font_input.currentTextChanged.connect(lambda value:self.text_format_changed(font=value))
        self.text_property_actions.append(properties.addWidget(self.font_input))
        self.text_property_actions.append(properties.addWidget(QLabel(" 字号 ")))
        self.font_size = QDoubleSpinBox()
        self.font_size.setRange(4,144);self.font_size.setValue(14);self.font_size.setSuffix(" pt")
        self.font_size.setMaximumWidth(88)
        self.font_size.valueChanged.connect(lambda value:self.text_format_changed(size=value))
        self.text_property_actions.append(properties.addWidget(self.font_size))
        self.text_property_actions.append(properties.addSeparator())
        self.color_action = self.action("颜色", self.choose_color)
        properties.addAction(self.color_action)
        properties.addWidget(QLabel(" 笔宽 "))
        self.width_input = QDoubleSpinBox()
        self.width_input.setRange(.5, 120)
        self.width_input.setSingleStep(.5)
        self.width_input.setValue(2)
        self.width_input.setSuffix(" pt")
        self.width_input.setMaximumWidth(92)
        self.width_input.valueChanged.connect(self.width_changed)
        properties.addWidget(self.width_input)
        self.delete_action = self.action("删除批注", self.delete_annotation, "Delete", "delete")
        properties.addAction(self.delete_action)
        self.text_property_actions.append(properties.addSeparator())
        self.edit_text_action = self.action("编辑文本", self.edit_selected_text)
        properties.addAction(self.edit_text_action)
        self.finish_text_action=self.action('完成输入',self.finish_inline)
        properties.addAction(self.finish_text_action)
        properties.addSeparator()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索原稿文字  Ctrl+F")
        self.search_input.setMaximumWidth(220)
        self.search_input.setClearButtonEnabled(True)
        self.search_input.returnPressed.connect(self.find_next)
        properties.addWidget(self.search_input)
        properties.addAction(self.action("查找下一个", self.find_next, "F3"))
        self.addAction(self.action("查找", lambda: self.search_input.setFocus(), "Ctrl+F"))
        menu = self.menuBar().addMenu("文件")
        menu.addActions([self.open_action, self.load_action, self.save_action, self.save_original_action, self.export_action])
        menu.addAction(self.action("记录另存为",self.save_project_as,"Ctrl+Shift+S"))
        menu.addAction(self.action("退出", self.close, "Alt+F4"))
        edit = self.menuBar().addMenu("编辑")
        edit.addActions([self.undo_action, self.redo_action, self.delete_action, self.swap_action])

    def error(self, error):
        QMessageBox.warning(self, "操作未完成", str(error))

    def refresh(self):
        active = self.session is not None
        for item in (self.save_action, self.export_action, self.swap_action, self.page_input, self.zoom_box, self.search_input):
            item.setEnabled(active)
        for name, action in self.tool_actions.items():
            allowed = False
            if active:
                allowed = True if name in {"select", "hand"} else self.session.can_copy if name=="capture" else self.session.can_modify if name in {"rect", "brush"} else self.session.can_modify if name=="text" else self.session.can_annotate
            action.setEnabled(bool(allowed))
        self.copy_action.setEnabled(active and self.session.can_copy)
        self.quote_action.setEnabled(active and self.session.can_copy)
        self.finish_text_action.setEnabled(active and any(v.inline_editor for v in self.views))
        self.save_original_action.setEnabled(active and self.session.original_dirty)
        selected_text=bool(self.selected_annotation and self.selected_annotation.get('kind')=='text' and not self.selected_annotation['id'].startswith('base:'))
        text_context=active and (self.tool=='text' or selected_text or any(v.inline_editor for v in self.views))
        for action in self.text_property_actions:action.setVisible(text_context)
        self.edit_text_action.setVisible(text_context);self.finish_text_action.setVisible(text_context)
        self.font_input.setEnabled(text_context);self.font_size.setEnabled(text_context)
        self.edit_text_action.setEnabled(active and bool(self.selected_annotation and self.selected_annotation.get("kind")=="text"))
        self.undo_action.setEnabled(active and self.session.cursor > 0)
        self.redo_action.setEnabled(active and self.session.cursor < len(self.session.history))
        self.delete_action.setEnabled(active and self.selected_annotation is not None and (self.session.can_annotate or (self.session.can_modify and self.selected_annotation.get("kind")=="text")))
        self.color_action.setEnabled(active and (self.tool in MARKUPS or self.selected_annotation is not None))
        self.width_input.setEnabled(active and self.tool in {"ink", "brush"})
        name = self.session.source.name if active else "打开 PDF 开始阅读"
        star = " *" if active and (self.session.dirty or any(v.inline_editor for v in self.views)) else ""
        self.setWindowTitle(f"{name}{star} — {APP_NAME} {VERSION} 双栏编辑")
        if hasattr(self,"original"):
            self.original.title.setText("原始 PDF  ·  "+("有批注待写回（保存原稿）" if active and self.session.original_dirty else "支持批注与添加文本"))

    def maybe_save(self):
        if not self.flush_comments():return False
        if not self.finish_inline():return False
        self.notebook.sync()
        if not self.session or (not self.session.dirty and not self.layout_dirty):return True
        if self.save_project(quiet=True):return True
        answer=QMessageBox.question(self,'保存工作记录','自动保存未成功。是否选择其他位置保存工作记录？',QMessageBox.Save|QMessageBox.Discard|QMessageBox.Cancel,QMessageBox.Save)
        if answer==QMessageBox.Cancel:return False
        return self.save_project_as() if answer==QMessageBox.Save else True

    def open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "打开 PDF", "", "PDF (*.pdf)")
        if path:
            self.open_file(path)

    def create_session(self, path):
        password = ""
        with pdf.open(path) as probe:
            needs = probe.needs_pass
        if needs:
            password, ok = QInputDialog.getText(self, "PDF 密码", "输入密码（不会保存到工作记录）：", QLineEdit.Password)
            if not ok:
                return None
        return Session(path, password)

    def open_file(self, path, project_data=None, project_path=None):
        if not self.maybe_save():
            return
        candidate = None
        auto_loaded=None;auto_problems=[]
        self.autosave_timer.stop()
        self.hide_context()
        try:
            candidate = self.create_session(path)
            if candidate is None:
                return
            if project_data is None:
                auto_loaded,project_data,auto_problems=discover(candidate)
                if auto_loaded:project_path=auto_loaded
            state = project_data.get("view", {}) if project_data else {}
            if not isinstance(state, dict):
                raise ValueError("工作记录的阅读位置无效。")
            zoom = float(state.get("zoom", 1.))
            if not math.isfinite(zoom):
                raise ValueError("缩放记录无效。")
            rotation = int(state.get("rotation", 0)) % 360
            if rotation not in (0, 90, 180, 270):
                raise ValueError("旋转记录无效。")
            page = max(0, min(len(candidate.doc)-1, int(state.get("page", 0))))
            if project_data:
                candidate.restore(project_data)
                candidate.project = Path(project_path).resolve()
            if self.session:
                self.renderer.stop()
                self.session.close()
            self.session, candidate = candidate, None
            self.auto_save_blocked=bool(auto_problems and not project_data)
            for view in self.views:view.comments.reset()
            self.notebook.bind(self.session)
            self.renderer.open(self.session)
            self.zoom, self.rotation = max(.25, min(4., zoom)), rotation
            self.locked = True
            for view in self.views:
                view.configure(self.session, self.rotation, self.zoom)
            self.locked = False
            layouts=state.get("comments",{})
            if not isinstance(layouts,dict):layouts={}
            for view in self.views:view.comments.reset(layouts.get("work" if view.edited else "original",{}))
            self.selected_annotation = None
            self.last_page = -1
            self.search_results, self.search_at, self.search_query = [], -1, ""
            self.search_input.clear()
            self.bookmarks.clear()
            toc = self.session.doc.get_toc()
            parents = {0: self.bookmarks.invisibleRootItem()}
            for level, title, number in toc:
                item = QTreeWidgetItem([title])
                item.setData(0, Qt.UserRole, number-1)
                parents.get(level-1, parents[0]).addChild(item)
                parents[level] = item
            if not toc:
                for i in range(len(self.session.doc)):
                    item = QTreeWidgetItem([f"第 {i+1} 页"])
                    item.setData(0, Qt.UserRole, i)
                    self.bookmarks.addTopLevelItem(item)
            self.bookmarks.expandToDepth(0)
            self.page_input.blockSignals(True)
            self.page_input.setRange(1, len(self.session.doc))
            self.page_input.blockSignals(False)
            self.page_total.setText(f" / {len(self.session.doc)}  ")
            self.zoom_box.setCurrentText(f"{self.zoom:.0%}")
            if bool(state.get("swapped", False)) != self.swapped:
                self.swap()
            self.set_tool("select")
            self.goto(page)
            QTimer.singleShot(0, lambda: self.goto(page))
            self.refresh()
            if project_path:
                try:remember(self.session.source,project_path)
                except OSError:pass
            self.statusBar().showMessage(('已自动恢复 '+auto_loaded.name+'。' if auto_loaded else '')+('；'.join(auto_problems) if auto_problems else '两栏同步；工作记录会在编辑后自动保存。'))
            self.layout_dirty=False
            if self.session.notes_html:self.note_dock.show()
        except Exception as exc:
            if candidate:
                candidate.close()
            self.locked = False
            self.error(exc)

    def load_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "打开工作记录", "", "myworld 工作记录 (*.pdfwork)")
        if not path:
            return
        try:
            if Path(path).stat().st_size > 64_000_000:
                raise ValueError("工作记录文件过大。")
            data = read_project(path)
            source = (Path(path).parent/data["source"]).resolve()
            if not source.is_file():
                source, _ = QFileDialog.getOpenFileName(self, "定位此工作记录对应的原始 PDF", "", "PDF (*.pdf)")
                if not source:
                    return
            self.open_file(source, data, path)
        except Exception as exc:
            self.error(exc)

    def view_state(self):
        return {"zoom": self.zoom, "rotation": self.rotation, "page": self.original.view.current_page(), "swapped": self.swapped, "comments":{("work" if v.edited else "original"):v.comments.positions for v in self.views}}

    def save_project(self, checked=False, quiet=False, path=None, finish_text=True):
        if not self.session:return False
        if not self.flush_comments():return False
        if finish_text and not self.finish_inline():return False
        if self.auto_save_blocked and path is None:
            self.notebook.status.setText('同名记录不匹配，已暂停覆盖；请使用“记录另存为”。')
            return False
        target=path or self.session.project or self.session.source.with_suffix('.pdfwork')
        target=Path(target)
        if target.suffix.lower()!='.pdfwork':target=Path(str(target)+'.pdfwork')
        try:
            if path is None and self.session.project is None and target.exists():raise ValueError('该位置已有工作记录，未自动覆盖。请使用记录另存为。')
            self.notebook.sync()
            self.session.save_project(target,self.view_state())
            self.auto_save_blocked=False
            self.layout_dirty=False
            try:remember(self.session.source,target)
            except OSError:pass
            self.refresh();self.notebook.status.setText('已自动保存 · '+target.name)
            if not quiet:self.statusBar().showMessage('工作记录和笔记已保存：'+str(target))
            return True
        except Exception as exc:
            self.notebook.status.setText('自动保存失败：'+str(exc)+'；请使用“记录另存为”。')
            if not quiet:self.error(exc)
            return False

    def save_project_as(self):
        if not self.session:return False
        path,_=QFileDialog.getSaveFileName(self,'工作记录另存为',str(self.session.project or self.session.source.with_suffix('.pdfwork')),'工作记录 (*.pdfwork)')
        return self.save_project(path=path) if path else False

    def autosave(self):
        if self.session and (self.session.dirty or self.layout_dirty) and not self.busy:
            self.save_project(quiet=True,finish_text=False)

    def schedule_save(self):
        if self.session:self.autosave_timer.start(1800)

    def flush_comments(self):
        return all(v.comments.flush() for v in self.views) if hasattr(self,"original") and hasattr(self.original.view,"comments") else True

    def note_changed(self):
        self.schedule_save();self.refresh()

    def toggle_notebook(self):
        self.note_dock.setVisible(not self.note_dock.isVisible())
        if self.note_dock.isVisible():self.notebook.editor.setFocus()

    def copy_pdf_selection(self):
        for view in self.views:
            if view.inline_editor and view.inline_editor.editor.textCursor().hasSelection():
                view.inline_editor.editor.copy();return
        if self.notebook.editor.hasFocus() and self.notebook.editor.textCursor().hasSelection():
            self.notebook.editor.copy();return
        self.active_view.copy_selection()

    def quote_selection(self,view=None):
        view=view or self.active_view
        if not self.session or not self.session.can_copy:return
        if not view.selection_text or not view.selection_quads:
            self.statusBar().showMessage('先在 PDF 中选择文字，再点击“记笔记”。');return
        rect=pdf.Rect()
        for q in view.selection_quads:rect|=as_quad(q).rect
        self.quote_payload({'text':view.selection_text,'page':view.selection_page,'rect':list(rect),'edited':view.edited},view)

    def quote_payload(self,payload,view,note_id=None,create_new=False):
        if not self.session or not self.session.can_copy:return
        self.hide_context()
        if create_new:
            note_id=self.notebook.new_note()
            if not note_id:return
        elif note_id:self.notebook.select_note(note_id)
        self.note_dock.show()
        self.notebook.add_quote(payload['text'],payload['page'],payload['rect'],payload['edited'])
        title=next((t for n,t in self.notebook.choices() if n==self.session.active_note),'笔记')
        self.statusBar().showMessage('已另起一行加入“'+title+'”。可继续 Ctrl+V 粘贴截图。')

    def capture_note(self,view,page,rect):
        if not self.session or not self.session.can_copy:
            self.statusBar().showMessage('此 PDF 未授予内容提取权限。');return
        r=pdf.Rect(rect);points=[view.to_scene(page,p) for p in (r.tl,r.tr,r.br,r.bl)]
        box=view.mapFromScene(QPolygonF(points)).boundingRect().intersected(view.viewport().rect())
        if box.width()<3 or box.height()<3:return
        view.viewport().repaint()
        image=view.viewport().grab(box).toImage()
        self.note_dock.show();self.notebook.insert_image(image,page,rect,view.edited)
        self.statusBar().showMessage('截图已插入笔记，并附有可点击的页码来源。')

    def synchronize(self, source):
        if self.locked or self.session is None:
            return
        self.locked = True
        try:
            target = self.edited.view if source is self.original.view else self.original.view
            target.centerOn(source.mapToScene(source.viewport().rect().center()))
            self.update_page(source.current_page())
        finally:
            self.locked = False

    def update_page(self, page):
        self.page_input.blockSignals(True)
        self.page_input.setValue(page+1)
        self.page_input.blockSignals(False)
        label = self.session.doc[page].get_label()
        self.reading_status.setText(f"{self.zoom:.0%} · {self.rotation}° · 双栏同步"+(f" · 页标签 {label}" if label else ""))
        if page != self.last_page:
            self.last_page = page
            self.refresh_notes()

    def goto(self, page):
        if not self.finish_inline():return
        if not self.session:
            return
        page = max(0, min(len(self.session.doc)-1, page))
        self.locked = True
        for view in self.views:
            view.cancel_drag()
            view.goto(page)
        self.update_page(page)
        self.locked = False

    def center_region(self, page, rect):
        if not self.finish_inline():return
        self.goto(page)
        point = (pdf.Rect(rect).tl+pdf.Rect(rect).br)/2
        self.locked = True
        for view in self.views:
            view.centerOn(view.to_scene(page, point))
        self.locked = False

    def step(self, amount):
        if self.session:
            self.goto(self.original.view.current_page()+amount)

    def bookmark_jump(self, item, column=0):
        page = item.data(0, Qt.UserRole)
        if page is not None and page >= 0:
            self.goto(page)

    def set_tool(self, name):
        if not self.finish_inline():return
        if not hasattr(self, "edited"):
            return
        view = self.active_view
        # Also support selecting text first, then clicking a markup tool.
        created=None
        if name in {"highlight", "underline", "strike"} and view.selection_quads:
            page,quads=view.selection_page,list(view.selection_quads)
            view.clear_selection()
            created=self.commit(name,page,{"quads":quads,"color":self.colors[name]},view)
        if self.selected_annotation:
            for pane in self.views:pane.clear_selection()
        self.selected_annotation=None
        if not created:self.hide_context()
        self.tool = name
        self.tool_actions[name].setChecked(True)
        for pane in self.views:
            pane.set_mode(name)
            pane.color = self.colors.get(name, (.18, .43, .91))
            pane.width = self.widths.get(name, 2.)
        self.width_input.blockSignals(True)
        self.width_input.setValue(self.widths.get(name, 2.))
        self.width_input.blockSignals(False)
        swatch = QPixmap(16, 16)
        swatch.fill(QColor.fromRgbF(*self.colors.get(name, (.18, .43, .91))))
        self.color_action.setIcon(QIcon(swatch))
        self.refresh()
        if created:self.select_created(created,view)

    def choose_color(self,anchor=None):
        if not self.session:return
        if isinstance(anchor,bool):anchor=None
        inline=next((v.inline_editor for v in self.views if v.inline_editor),None)
        if inline:
            self.color_target='text';color=inline.current_format()['color']
        elif self.selected_annotation:
            self.color_target=(self.active_view,dict(self.selected_annotation))
            color=self.selected_annotation.get('color',[1,.78,.12])
        elif self.tool in MARKUPS:
            self.color_target=self.tool
            color=self.colors[self.tool]
        else:return
        if anchor is None:
            for bar in self.findChildren(QToolBar):
                widget=bar.widgetForAction(self.color_action)
                if widget:anchor=widget;break
        point=anchor.mapToGlobal(anchor.rect().bottomLeft()) if anchor else self.mapToGlobal(self.rect().center())
        self.palette.open_at(point,color)

    def apply_chosen_color(self,color):
        target=self.color_target
        swatch=QPixmap(16,16);swatch.fill(QColor.fromRgbF(*color));self.color_action.setIcon(QIcon(swatch))
        if isinstance(target,tuple):
            view,annotation=target
            if annotation.get('kind') in self.colors:self.colors[annotation['kind']]=color
            self.change_annotation({'color':color},view,annotation)
        elif target in MARKUPS:
            self.colors[target]=color
            for view in self.views:
                if view.tool==target:view.color=color
            if target=='text':self.text_format_changed(color=color)
        for view in self.views:
            if view.inline_editor:
                item=view.inline_editor;self.focus_inline(view,item)
                QTimer.singleShot(0,lambda v=view,i=item:self.focus_inline(v,i))

    def hide_context(self):
        if hasattr(self,'floating'):self.floating.hide()
        if hasattr(self,'palette'):self.palette.hide()

    def view_operation(self,kind,page,data,view):
        op=self.commit(kind,page,data,view)
        if op and kind in {'highlight','underline','strike'}:
            session=self.session
            QTimer.singleShot(0,lambda:self.select_created(op,view) if self.session is session else None)

    def select_created(self,op,view):
        annotation=next((a for a in self.session.annotations(op['page'],view.edited) if a['id']==op['id']),None)
        if annotation:self.select_annotation(annotation,view)

    def context_markup(self,kind):
        if self.floating.mode!='selection' or not self.floating.payload:return
        payload=dict(self.floating.payload);view=self.floating.view
        view.clear_selection()
        op=self.commit(kind,payload['page'],{'quads':payload['quads'],'color':self.colors[kind]},view)
        if op:self.select_created(op,view)

    def change_annotation(self,changes,view=None,annotation=None):
        view=view or self.active_view;annotation=annotation or self.selected_annotation
        if not self.session or not annotation:return
        current=next((a for a in self.session.annotations(annotation['page'],view.edited) if a['id']==annotation['id']),None)
        if not current:self.hide_context();return
        try:changes=self.session.validate({'kind':'update','page':annotation['page'],'scope':'work' if view.edited else 'original','target':annotation['id'],'changes':changes})['changes']
        except Exception as exc:self.error(exc);return
        if all(current.get(key)==value for key,value in changes.items()):
            self.floating.comment_panel.hide();return
        op=self.commit('update',annotation['page'],{'target':annotation['id'],'changes':changes},view)
        if op:
            updated=next((a for a in self.session.annotations(annotation['page'],view.edited) if a['id']==annotation['id']),None)
            if updated:self.select_annotation(updated,view)

    def width_changed(self, value):
        if self.tool in {"ink", "brush"}:
            self.widths[self.tool] = value
            for view in self.views: view.width = value

    def selected_text(self, text, view=None):
        if text:self.floating.show_selection(view or self.active_view)
        else:self.floating.hide()
        self.statusBar().showMessage(f"已选择 {len(text)} 个字符，Ctrl+C 复制。" if text else "此处没有可选择文字；扫描页可使用区域高亮或自由画笔。")

    def activate_view(self, view):
        if view is not self.active_view and not self.finish_inline():return
        if view is not self.active_view:
            self.selected_annotation = None
            for other in self.views:
                if other is not view: other.clear_selection()
        self.active_view = view
        for pane in (self.original,self.edited):
            pane.title.setStyleSheet("border-bottom:2px solid #983493;" if pane.view is view else "border-bottom:2px solid transparent;")
        self.refresh_notes()
        self.refresh()

    def render_ready(self, view, number, key, image):
        if view.session is self.session:
            view.accept_render(number,key,image)

    def text_format_changed(self,**values):
        self.text_defaults.update(values)
        if not any(v.inline_editor for v in self.views) and self.selected_annotation and self.selected_annotation.get('kind')=='text':
            a=self.selected_annotation
            op=self.session.effective(a['page'],self.active_view.edited)[0].get(a['id'])
            if op:self.edit_text(self.active_view,a['page'],op['rect'],op)
        for view in self.views:
            if view.inline_editor:view.inline_editor.apply_format(**values)

    def edit_text(self,view,page,rect,existing=None):
        if not self.session or not self.session.can_modify:return
        if not self.finish_inline():return
        self.activate_view(view)
        self.hide_context();self.selected_annotation=None
        defaults=dict(existing or self.text_defaults)
        defaults['color']=existing['color'] if existing else self.colors['text']
        bounds=self.session.doc[page].rect*self.session.doc[page].derotation_matrix
        r=pdf.Rect(rect).normalize()&bounds
        if r.width<8 or r.height<8:
            self.statusBar().showMessage('文本框太靠近页边，请重新选择位置。');return
        self.tool='text';self.tool_actions['text'].setChecked(True)
        for v in self.views:v.set_mode('text')
        self.font_input.blockSignals(True);self.font_size.blockSignals(True)
        self.font_input.setCurrentText(defaults['font']);self.font_size.setValue(defaults['size'])
        self.font_input.blockSignals(False);self.font_size.blockSignals(False)
        view.inline_editor=InlineTextBox(view,page,list(r),defaults,existing)
        view.scene().addItem(view.inline_editor)
        view.refresh_overlays(page)
        self.refresh()
        item=view.inline_editor
        self.focus_inline(view,item)
        QTimer.singleShot(0,lambda:self.focus_inline(view,item))
        self.statusBar().showMessage('直接输入文字 · Ctrl+Enter 完成 · Esc 取消 · 拖动边框移动，拖动右下角调整文本框。')

    def focus_inline(self,view,item):
        if view.inline_editor is not item:return
        self.activateWindow()
        view.setFocus(Qt.OtherFocusReason)
        view.scene().setFocusItem(item,Qt.OtherFocusReason)
        item.setFocus(Qt.OtherFocusReason)
        item.editor.setFocus(Qt.OtherFocusReason)
        item.reset_caret()

    def finish_inline(self, checked=False, cancel=False):
        if not hasattr(self,'original'):return True
        for view in self.views:
            item=view.inline_editor
            if not item:continue
            data=item.result()
            if not cancel and data['text'].strip():
                if len(data['text'])>20000:
                    self.statusBar().showMessage('单个文本框最多 20000 字，请拆分。');return False
                if item.editor.document().size().height()>data['rect'][3]-data['rect'][1]+.5:
                    self.statusBar().showMessage('文本框高度不足，请增大文本框或减小字号后完成。');return False
                try:
                    validated=self.session.validate({'kind':'text','page':item.page,'scope':'work' if view.edited else 'original',**data})
                    data={k:validated[k] for k in ('text','font','size','color','rect')}
                except Exception as exc:self.statusBar().showMessage(str(exc));return False
            page,existing=item.page,item.existing
            view.inline_editor=None;view.editor_drag=None
            view.scene().removeItem(item);item.deleteLater()
            if not cancel and data['text'].strip():
                self.text_defaults.update({k:data[k] for k in ('font','size','color')});self.colors['text']=data['color']
                same=existing and all(data[k]==existing[k] for k in ('text','font','size','color','rect'))
                if not same:
                    if existing:
                        data['replaces']=existing['id']
                        if existing.get('comment'):data['comment']=existing['comment']
                    self.commit('text',page,data,view)
            view.refresh_overlays(page)
            view.setFocus();self.refresh()
        return True

    def edit_selected_text(self):
        if not self.session or not self.selected_annotation: return
        a = self.selected_annotation
        op = self.session.effective(a['page'],self.active_view.edited)[0].get(a['id'])
        if op and op['kind']=='text': self.edit_text(self.active_view,a['page'],list(op['rect']),op)

    def update_edit(self, page):
        self.schedule_save()
        for view in self.views:
            if page in view.overlays or page in view.cache:
                view.refresh_overlays(page)
            view.timer.start(0)
            view.comments.schedule()
        self.selected_annotation = None
        self.refresh_notes()
        self.refresh()

    def commit(self, kind, page, data, view=None):
        if not self.session: return
        view = view or self.active_view
        try:
            self.hide_context()
            op=self.session.add(kind,page,scope='work' if view.edited else 'original',**data)
            self.update_edit(page)
            scope = '工作副本' if view.edited else '原稿（待保存）'
            self.statusBar().showMessage(f"{scope}已添加{LABELS[kind]}，Ctrl+Z 撤销。"+(" 相交的矢量图形可能被整体移除；后台正在更新预览。" if kind=='erase' else ''))
            return op
        except Exception as exc: self.error(exc)

    def history(self, redo):
        if not self.flush_comments():return
        if not self.finish_inline():return
        if not self.session: return
        self.hide_context()
        for view in self.views:
            view.cancel_drag();view.clear_selection()
        page = self.session.redo() if redo else self.session.undo()
        if page is not None:
            if self.original.view.current_page()!=page: self.goto(page)
            self.update_edit(page)
        self.selected_annotation = None
        self.refresh_notes();self.refresh()

    def refresh_notes(self):
        self.notes.clear()
        if not self.session: return
        view = self.active_view
        self.notes.setHeaderLabel(('工作副本' if view.edited else '原稿')+' · 本页批注')
        page = self.page_input.value()-1
        for annotation in self.session.annotations(page,view.edited):
            item = QTreeWidgetItem([annotation['label']])
            item.setData(0,Qt.UserRole,annotation)
            item.setToolTip(0,annotation.get('comment',''))
            self.notes.addTopLevelItem(item)

    def note_clicked(self, item, column=0):
        annotation = item.data(0,Qt.UserRole)
        self.center_region(annotation['page'],annotation['rect'])
        self.select_annotation(annotation,self.active_view)

    def select_annotation(self, annotation, view=None):
        view = view or self.active_view
        self.activate_view(view)
        for item in self.views: item.clear_selection()
        self.selected_annotation = annotation
        if annotation:
            view.draw_rect(annotation['page'],annotation['rect'],QColor(0,0,0,0),temporary=True,outline=QColor('#8e348c'))
        self.refresh()
        if annotation and annotation.get('kind')=='text':
            op=self.session.effective(annotation['page'],view.edited)[0].get(annotation['id'])
            if op:
                self.font_input.blockSignals(True);self.font_size.blockSignals(True)
                self.font_input.setCurrentText(op['font']);self.font_size.setValue(op['size'])
                self.font_input.blockSignals(False);self.font_size.blockSignals(False)
        if annotation:
            swatch=QPixmap(16,16);swatch.fill(QColor.fromRgbF(*annotation.get('color',[1,.78,.12])));self.color_action.setIcon(QIcon(swatch))
            self.floating.show_annotation(view,annotation)
        else:self.floating.hide()

    def delete_annotation(self):
        if not self.session or not self.selected_annotation: return
        a = self.selected_annotation
        self.active_view.clear_selection()
        self.commit('delete',a['page'],{'target':a['id']},self.active_view)

    def save_original(self):
        if not self.flush_comments():return
        if not self.finish_inline():return
        self.notebook.sync()
        if not self.session or not self.session.original_dirty: return
        progress = QProgressDialog('正在保存原稿批注…','',0,100,self)
        progress.setCancelButton(None);progress.setWindowModality(Qt.ApplicationModal)
        self.busy = True
        self.renderer.stop()
        try:
            def update(done,total):
                progress.setValue(round(100*done/max(total,1)))
                QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)
            backup = self.session.save_original(update)
            for view in self.views:view.comments.sync()
            if self.session.project:
                try: self.session.save_project(self.session.project,self.view_state())
                except Exception as exc:
                    self.error('原稿已经成功写回，但工作记录自动更新失败。请另存新的工作记录；旧记录与新版原稿校验值不同。\n'+str(exc))
            self.search_query=''
            self.selected_annotation=None
            for view in self.views:
                view.clear_selection();view.invalidate()
            self.refresh_notes();self.refresh()
            self.statusBar().showMessage('原稿批注已写回，工作副本擦除未写入原稿；上一版备份：'+str(backup)+'。已写回的原稿操作不再位于撤销历史中。')
        except Exception as exc: self.error(exc)
        finally:
            self.busy=False;progress.close()
            for view in self.views: view.invalidate()
            self.refresh_notes();self.refresh()
            self.renderer.open(self.session)
            for view in self.views: view.timer.start(0)

    def parse_zoom(self):
        try:
            self.set_zoom(float(self.zoom_box.currentText().strip().rstrip("%"))/100)
        except ValueError:
            self.zoom_box.setCurrentText(f"{self.zoom:.0%}")

    def set_zoom(self, zoom):
        if not self.session or not math.isfinite(zoom):
            return
        center = self.original.view.mapToScene(self.original.view.viewport().rect().center())
        self.zoom = max(.25, min(4., zoom))
        self.locked = True
        for view in self.views:
            view.cancel_drag()
            view.zoom = self.zoom
            view.setTransform(QTransform.fromScale(self.zoom, self.zoom))
            view.centerOn(center)
            view.timer.start(0)
        self.locked = False
        self.zoom_box.setCurrentText(f"{self.zoom:.0%}")
        self.update_page(self.original.view.current_page())

    def fit_width(self):
        if self.session:
            page = self.original.view.current_page()
            width = self.original.view.pages[page]["rect"].width()
            self.set_zoom(min(v.viewport().width()-48 for v in self.views)/width)

    def rotate(self):
        if not self.finish_inline():return
        if not self.session:
            return
        page = self.original.view.current_page()
        center = self.original.view.mapToScene(self.original.view.viewport().rect().center())
        anchor = self.original.view.to_pdf(page, center)
        self.rotation = (self.rotation+90) % 360
        self.locked = True
        for view in self.views:
            view.configure(self.session, self.rotation, self.zoom)
            view.centerOn(view.to_scene(page, anchor))
        self.locked = False
        self.update_page(self.original.view.current_page())

    def swap(self):
        if not self.finish_inline():return
        self.hide_context()
        if not self.session:
            return
        center = self.original.view.mapToScene(self.original.view.viewport().rect().center())
        self.locked = True
        self.edited.view.cancel_drag()
        self.panes.insertWidget(0, self.edited if not self.swapped else self.original)
        self.swapped = not self.swapped
        self.panes.setSizes([self.panes.width()//2]*2)
        for view in self.views:
            view.centerOn(center)
        self.locked = False
        self.layout_dirty=True
        self.schedule_save()
        self.statusBar().showMessage('原始 PDF 与工作副本的位置已交换；编辑身份保持不变。')

    def find_next(self):
        if not self.session:
            return
        query = self.search_input.text().strip()
        if not query:
            return
        if not self.session.can_copy:
            self.statusBar().showMessage("此 PDF 未授予文字提取权限。")
            return
        if query != self.search_query:
            self.search_query, self.search_results, self.search_at = query, [], -1
            progress = QProgressDialog("正在搜索原稿文字…", "", 0, len(self.session.doc), self)
            progress.setCancelButton(None)
            progress.setWindowModality(Qt.ApplicationModal)
            self.busy = True
            try:
                for page in self.session.doc:
                    self.search_results.extend((page.number, quad_list(q)) for q in page.search_for(query, quads=True))
                    if page.number % 20 == 0:
                        progress.setValue(page.number)
                        QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)
                    if len(self.search_results) >= 2000:
                        self.search_results = self.search_results[:2000]
                        break
            except Exception as exc:
                self.error(exc)
            finally:
                self.busy = False
                progress.close()
        if not self.search_results:
            self.statusBar().showMessage("原稿中没有找到该文字。扫描页需要先做 OCR 才能搜索。")
            return
        self.search_at = (self.search_at+1) % len(self.search_results)
        page, quad = self.search_results[self.search_at]
        self.center_region(page, as_quad(quad).rect)
        self.original.view.clear_selection()
        self.original.view.draw_quad(page, quad, QColor(255, 191, 36, 100), QColor("#e59b18"))
        self.statusBar().showMessage(f"原稿搜索：{self.search_at+1} / {len(self.search_results)}（最多显示 2000 处）")

    def export(self):
        if not self.flush_comments():return
        if not self.finish_inline():return
        if not self.session:
            return
        has_erasing = any(op["kind"] == "erase" for op in self.session.history[:self.session.cursor])
        if has_erasing:
            answer = QMessageBox.question(self, "导出区域脱敏 PDF", "导出会实际移除擦除区域的内容。复杂矢量图形相交时可能被按对象整体移除，编辑栏已预览此效果。\n\n导出后的区域删除不能恢复；原稿和工作记录仍可继续编辑。是否继续？",
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
        path, _ = QFileDialog.getSaveFileName(self, "导出批注和擦除结果", str(self.session.source.with_name(self.session.source.stem+"_edited.pdf")), "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        progress = QProgressDialog("正在生成 PDF…", "", 0, len(self.session.doc), self)
        progress.setCancelButton(None)
        progress.setWindowModality(Qt.ApplicationModal)
        progress.setMinimumDuration(0)
        self.busy = True
        try:
            def update(done, total):
                progress.setValue(done)
                QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)
            self.session.export(path, update)
            progress.close()
            QMessageBox.information(self, "导出完成", f"已生成：\n{path}\n\n标准批注可在其他 PDF 阅读器中查看。\n原稿未修改；要继续撤销，请另行保存工作记录。")
        except Exception as exc:
            progress.close()
            self.error(exc)
        finally:
            self.busy = False

    def help(self):
        QMessageBox.information(self,f'{APP_NAME} {VERSION}',
            '选中文字后，附近小栏可复制、高亮、下划线、删除线或记笔记。\n'
            '点中批注后，小栏可添加评论、展开颜色面板或删除。\n'
            '记笔记菜单可选择目标笔记或新建；每次摘录另起一行。\n'
            '右侧切换笔记、编辑名称后按 Enter 重命名；Ctrl+V 可直接粘贴系统截图。\n'
            'T 在页面输入文字，顶部设置字体/字号/颜色；Ctrl+Enter 完成，Esc 取消。\n'
            '拖边框移动文本框、拖右下角改大小；深色闪烁光标显示插入位置。\n'
            '两栏标题处的“交换两栏”或 Ctrl+Shift+X 可交换原稿与工作副本。\n'
            'A 高亮，U 下划线，D 删除线，P 画笔；R/B 在工作副本擦除。\n'
            'Ctrl+Z 撤销，Ctrl+Y 重做。F8 显示笔记，Ctrl+Shift+N 摘录到当前笔记。\n'
            '笔记图片：选中后拖右下角或输入宽度；评论卡片：拖动标题移动，悬停指向原文，点击继续编辑。\n'
            '打开 PDF 自动匹配工作记录；完成的操作和笔记约 2 秒后自动保存。\n'
            'Ctrl+S 保存记录，Ctrl+Shift+S 另存记录，Ctrl+Alt+S 保存原稿，Ctrl+E 导出副本。\n'
            '写回原稿后该次原稿操作退出撤销历史，保留上一版 .bak；工作副本历史保留。\n'
            '导出擦除会实际移除内容；复杂矢量图形相交时可能整体移除。')

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls()]
        if paths and paths[0].lower().endswith(".pdf"):
            self.open_file(paths[0])

    def closeEvent(self, event):
        if self.busy or not self.maybe_save():
            event.ignore()
            return
        self.autosave_timer.stop()
        if self.session:
            self.renderer.stop()
            self.session.close()
            self.session = None
        for view in self.views:
            view.timer.stop()
            view.comments.reset()
            view.comments.timer.stop()
            view.session = None
        event.accept()


def create_application():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    translator = QTranslator(app)
    if translator.load("qtbase_zh_CN", QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
        app.installTranslator(translator)
    app._studypdf_translator = translator
    if "Microsoft YaHei UI" in QFontDatabase.families():
        app.setFont(QFont("Microsoft YaHei UI", 10))
    else:
        QFontDatabase.addApplicationFontFromData(QByteArray(pdf.Font("cjk").buffer))
        app.setFont(QFont("DejaVu Sans", 10))
    app.setStyleSheet("""
        QMainWindow { background:#faf8fb; color:#34313b; }
        QMenuBar { background:#91328e; color:white; padding:3px; }
        QMenuBar::item:selected { background:#ad53a8; }
        QToolBar { background:#fcfbfd; border-bottom:1px solid #e5dde8; spacing:3px; padding:4px; }
        QToolButton { padding:7px 8px; border-radius:5px; color:#314566; }
        QToolButton:hover { background:#e8eefb; }
        QToolButton:checked { background:#f0dff1; color:#842c84; border-bottom:2px solid #9b3697; }
        #originalTitle { background:#f0f3f8; color:#52637c; font-weight:bold; }
        #editedTitle { background:#f1e5f3; color:#842c84; font-weight:bold; }
        QTreeWidget { background:#fbfcfe; border:0; padding:4px; }
        QTreeWidget::item { padding:5px; }
        QTabWidget::pane { border:0; }
        QTabBar::tab { padding:9px 18px; background:#f0f3f8; }
        QTabBar::tab:selected { background:#e4edfc; color:#2859a1; }
        QSplitter::handle { background:#d7dfeb; width:5px; }
        QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { min-height:25px; padding:2px; }
        QStatusBar { background:#f0f3f8; color:#52637c; }
    """)
    return app


def main():
    app = create_application()
    window = MainWindow()
    window.show()
    if len(sys.argv) > 1:
        QTimer.singleShot(0, lambda: window.open_file(sys.argv[1]))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
