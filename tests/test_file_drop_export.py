"""0.6.2: actual Qt child-viewport drop routing and standalone working-PDF persistence."""
from pathlib import Path
import sys,os,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QMimeData,QPoint,QPointF,QUrl,Qt
from PySide6.QtGui import QDragEnterEvent,QDragMoveEvent,QDropEvent,QImage
from PySide6.QtWidgets import QApplication,QWidget,QDialog,QMessageBox
from PySide6.QtTest import QTest
import pymupdf as pdf
from app import create_application,MainWindow
from file_drop import local_pdf_paths
from core import as_quad,quad_list,sha256,read_project,Session
from test_core import make_pdf

class DropExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=create_application()
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.config=patch.dict(os.environ,{'STUDYPDF_CONFIG_DIR':str(self.root/'config')});self.config.start()
        self.path=self.root/'课程 PDF 中文.PDF';make_pdf(self.path)
        self.second=self.root/'second.pdf';make_pdf(self.second)
        self.w=MainWindow();self.errors=[];self.w.error=lambda e:self.errors.append(str(e))
        self.w.show();QTest.qWait(15)
    def tearDown(self):
        self.w.maybe_save=lambda:True;self.w.close()
        QTest.qWait(5);self.config.stop();self.tmp.cleanup()
    def mime(self,paths):
        m=QMimeData();m.setUrls([QUrl.fromLocalFile(str(p.resolve())) for p in paths]);return m
    def drag(self,target,mime,actions=Qt.CopyAction|Qt.MoveAction,wait=True):
        enter=QDragEnterEvent(QPoint(30,30),actions,mime,Qt.LeftButton,Qt.NoModifier)
        QApplication.sendEvent(target,enter)
        move=QDragMoveEvent(QPoint(35,35),actions,mime,Qt.LeftButton,Qt.NoModifier)
        QApplication.sendEvent(target,move)
        drop=QDropEvent(QPointF(35,35),actions,mime,Qt.LeftButton,Qt.NoModifier)
        QApplication.sendEvent(target,drop)
        if wait:QTest.qWait(30)
        return enter,move,drop
    def test_drop_blank_original_viewport_unicode_uppercase(self):
        self.assertTrue(self.w.original.view.drop_hint.isVisible())
        events=self.drag(self.w.original.view.viewport(),self.mime([self.path]))
        self.assertTrue(all(e.isAccepted() for e in events))
        self.assertEqual(events[-1].dropAction(),Qt.CopyAction)
        self.assertEqual(self.w.session.source,self.path.resolve())
        self.assertFalse(self.w.original.view.drop_hint.isVisible())
        self.assertTrue(self.path.is_file())
    def test_drop_blank_working_viewport_and_restore_project(self):
        s=Session(self.path)
        q=[quad_list(x) for x in s.doc[0].search_for('HIGHLIGHT',quads=True)]
        s.add('highlight',0,quads=q);s.save_project(self.path.with_suffix('.pdfwork'),{});s.close()
        self.drag(self.w.edited.view.viewport(),self.mime([self.path]))
        self.assertEqual(self.w.session.cursor,1)
        self.assertTrue(self.w.session.project)
        self.assertFalse(self.errors)
    def test_sidebar_header_and_note_viewport_open_pdf(self):
        self.w.note_dock.show()
        for widget in [self.w.bookmarks.viewport(),self.w.original.title,self.w.notebook.editor.viewport(),self.w]:
            with self.subTest(widget=type(widget).__name__):
                e,move,drop=self.drag(widget,self.mime([self.path]))
                self.assertTrue(e.isAccepted());self.assertTrue(drop.isAccepted())
                self.assertEqual(self.w.session.source,self.path.resolve())
    def test_invalid_remote_missing_and_directory_not_opened(self):
        missing=self.root/'missing.pdf';directory=self.root/'folder.pdf';directory.mkdir()
        text=self.root/'notes.txt';text.write_text('Hello')
        m=self.mime([missing,directory,text]);m.setUrls(m.urls()+[QUrl('https://example.com/file.pdf')])
        self.assertEqual(local_pdf_paths(m),[])
        self.drag(self.w.edited.view.viewport(),m)
        self.assertIsNone(self.w.session)
    def test_mixed_urls_deduplicate_and_first_pdf(self):
        text=self.root/'notes.txt';text.write_text('Hello')
        m=self.mime([text,self.path,self.path,self.second])
        self.assertEqual(local_pdf_paths(m),[str(self.path.resolve()),str(self.second.resolve())])
        self.drag(self.w.edited.view.viewport(),m)
        self.assertEqual(self.w.session.source,self.path.resolve())
        self.assertIn('第一个',self.w.statusBar().currentMessage())
    def test_switch_respects_unsaved_record_veto(self):
        self.w.open_file(self.path);old=self.w.session
        with patch.object(self.w,'maybe_save',return_value=False):
            self.drag(self.w.edited.view.viewport(),self.mime([self.second]))
        self.assertIs(self.w.session,old)
    def test_invalid_drop_preserves_current_edits(self):
        w=self.w;w.open_file(self.path);old=w.session
        q=[quad_list(x) for x in old.doc[0].search_for('HIGHLIGHT',quads=True)]
        w.commit('highlight',0,{'quads':q})
        text=self.root/'notes.txt';text.write_text('Not a PDF')
        self.drag(w.edited.view.viewport(),self.mime([text]))
        self.assertIs(w.session,old);self.assertEqual(w.session.cursor,1)

    def test_drag_switch_saves_current_work_record(self):
        w=self.w;w.open_file(self.path)
        q=[quad_list(x) for x in w.session.doc[0].search_for('HIGHLIGHT',quads=True)]
        w.commit('underline',0,{'quads':q});w.notebook.editor.setPlainText('Saved before drag switch')
        self.drag(w.original.view.viewport(),self.mime([self.second]))
        self.assertEqual(w.session.source,self.second.resolve())
        old=read_project(self.path.with_suffix('.pdfwork'))
        self.assertEqual(old['cursor'],1);self.assertIn('Saved before drag switch',old['notes_html'])

    def test_busy_and_move_only_drops_are_rejected(self):
        self.w.busy=True
        events=self.drag(self.w.original.view.viewport(),self.mime([self.path]))
        self.assertFalse(events[0].isAccepted());self.assertIsNone(self.w.session)
        self.w.busy=False
        events=self.drag(self.w.original.view.viewport(),self.mime([self.path]),Qt.MoveAction)
        self.assertFalse(events[0].isAccepted());self.assertIsNone(self.w.session)
    def test_child_dialog_file_drop_is_not_hijacked(self):
        dialog=QDialog(self.w)
        event=QDragEnterEvent(QPoint(20,20),Qt.CopyAction,self.mime([self.path]),Qt.LeftButton,Qt.NoModifier)
        self.assertFalse(self.w.file_drop.eventFilter(dialog,event))
        dialog.close()

    def test_other_window_unaffected_and_images_left_to_notebook(self):
        other=QWidget();other.setAcceptDrops(True)
        self.drag(other,self.mime([self.path]));other.close()
        self.assertIsNone(self.w.session)
        self.w.open_file(self.path);self.w.note_dock.show()
        image=QImage(60,40,QImage.Format_RGB32);image.fill(Qt.green)
        m=QMimeData();m.setImageData(image)
        self.assertFalse(self.w.file_drop.eventFilter(self.w.notebook.editor,QDragEnterEvent(QPoint(10,10),Qt.CopyAction,m,Qt.LeftButton,Qt.NoModifier)))
        self.w.notebook.editor.insertFromMimeData(m)
        self.assertEqual(len(self.w.session.note_assets),1)
    def test_pending_drop_is_cancelled_when_window_closes(self):
        with patch.object(self.w,'open_file') as opened:
            self.drag(self.w.original.view.viewport(),self.mime([self.path]),wait=False)
            self.w.close();QTest.qWait(15);opened.assert_not_called()
    def test_duplicate_drop_during_pending_is_not_reentrant(self):
        with patch.object(self.w,'open_file') as opened:
            self.drag(self.w.original.view.viewport(),self.mime([self.path]),wait=False)
            self.drag(self.w.edited.view.viewport(),self.mime([self.second]),wait=False)
            QTest.qWait(15);opened.assert_called_once_with(str(self.path.resolve()))
    def test_export_button_tracks_working_pane_after_swap(self):
        self.assertFalse(self.w.edited.export_button.isEnabled())
        self.w.open_file(self.path);self.w.swap()
        self.assertIs(self.w.panes.widget(0),self.w.edited)
        self.assertTrue(self.w.edited.export_button.isEnabled())
        with patch.object(self.w,'save_project') as saved,patch('app.QFileDialog.getSaveFileName',return_value=('','')):
            self.w.export();saved.assert_not_called()
    def test_export_working_pdf_flushes_live_text_and_record_for_other_readers(self):
        w=self.w;w.open_file(self.path);before=sha256(self.path)
        page=w.session.doc[0]
        q=[quad_list(x) for x in page.search_for('HIGHLIGHT',quads=True)]
        rect=list(as_quad(q[0]).rect)
        w.commit('erase',0,{'rects':[rect]},w.edited.view)
        for kind,word in [('highlight','Underline'),('underline','Keep')]:
            w.commit(kind,0,{'quads':[quad_list(x) for x in page.search_for(word,quads=True)],'color':[.8,.2,.3],'comment':'Portable comment'})
        w.notebook.editor.setPlainText('Notebook remains in the project')
        w.edit_text(w.edited.view,0,[50,210,350,245])
        w.edited.view.inline_editor.editor.insertPlainText('REPLACEMENT')
        target=self.root/'working.pdf'
        with patch('app.QFileDialog.getSaveFileName',return_value=(str(target),'PDF')),patch('app.QMessageBox.question',return_value=QMessageBox.Yes),patch('app.QMessageBox.information') as info:
            QTest.mouseClick(w.edited.export_button,Qt.LeftButton)
        self.assertTrue(target.is_file(),self.errors)
        self.assertIsNone(w.edited.view.inline_editor)
        with pdf.open(target) as d:
            text=d[0].get_text()
            self.assertNotIn('HIGHLIGHT',text);self.assertIn('REPLACEMENT',text)
            page=d[0];marks=list(page.annots())
            self.assertTrue(any(a.type[0]==pdf.PDF_ANNOT_HIGHLIGHT for a in marks))
            self.assertTrue(any(a.info['content']=='Portable comment' for a in marks))
        record=read_project(self.path.with_suffix('.pdfwork'))
        self.assertIn('Notebook remains',record['notes_html'])
        self.assertTrue(any(o['kind']=='text' and o['text']=='REPLACEMENT' for o in record['history']))
        self.assertEqual(sha256(self.path),before)
        self.assertIn('工作记录已保存',info.call_args[0][2]);self.assertFalse(self.errors)
    def test_export_still_works_if_project_cannot_be_saved(self):
        w=self.w;w.open_file(self.path)
        q=[quad_list(x) for x in w.session.doc[0].search_for('HIGHLIGHT',quads=True)]
        w.commit('strike',0,{'quads':q})
        target=self.root/'working.pdf'
        with patch.object(w,'save_project',return_value=False),patch('app.QFileDialog.getSaveFileName',return_value=(str(target),'PDF')),patch('app.QMessageBox.information') as info:
            w.export()
        self.assertTrue(target.is_file());self.assertTrue(w.session.dirty)
        self.assertIn('工作记录尚未保存成功',info.call_args[0][2])
    def test_export_refuses_overwriting_source(self):
        w=self.w;w.open_file(self.path);digest=sha256(self.path)
        with patch('app.QFileDialog.getSaveFileName',return_value=(str(self.path),'PDF')):
            w.export()
        self.assertEqual(sha256(self.path),digest);self.assertTrue(self.errors)

if __name__=='__main__':unittest.main()
