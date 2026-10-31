"""0.4 integration: inline editing, highlight pixels, safe association, portable notes."""
from pathlib import Path
import sys,hashlib,io,json,zlib,zipfile,os
from unittest.mock import patch
import tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pymupdf as pdf
from PySide6.QtCore import Qt,QByteArray,QBuffer,QIODevice,QRectF,QMimeData
from PySide6.QtGui import QImage,QPainter,QInputMethodEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from core import Session,quad_list,read_project,PROJECT_MAGIC
from project_links import discover,remember
from test_core import make_pdf
from test_gui import GuiTests


def image_blob():
    image=QImage(200,80,QImage.Format_RGB32);image.fill(Qt.yellow)
    data=QByteArray();buffer=QBuffer(data);buffer.open(QIODevice.WriteOnly);image.save(buffer,'PNG')
    return bytes(data)


class NotebookCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.config=patch.dict(os.environ,{'STUDYPDF_CONFIG_DIR':str(self.root/'config')});self.config.start()
        self.path=self.root/'source.pdf';make_pdf(self.path);self.s=Session(self.path)
    def tearDown(self):self.s.close();self.config.stop();self.tmp.cleanup()

    def test_portable_zip_deduplicates_assets_and_restores(self):
        blob=image_blob();key=hashlib.sha256(blob).hexdigest()
        self.s.note_assets[key]=blob
        self.s.notes_html=f'<p>中文笔记</p><img src="studypdf-image:/{key}"><img src="studypdf-image:/{key}">'
        path=self.path.with_suffix('.pdfwork');self.s.save_project(path,{})
        with zipfile.ZipFile(path) as z:self.assertEqual(len([n for n in z.namelist() if n.startswith('images/')]),1)
        self.assertLess(path.stat().st_size,5000)
        other=Session(self.path)
        try:
            other.restore(read_project(path));self.assertEqual(other.notes_html,self.s.notes_html);self.assertEqual(other.note_assets[key],blob)
        finally:other.close()
        self.s.notes_html='No images now';self.s.save_project(path,{})
        with zipfile.ZipFile(path) as z:self.assertEqual(z.namelist(),['project.json'])

    def test_same_name_project_auto_match_and_custom_binding(self):
        self.s.add('erase',0,rects=[[40,50,280,95]])
        self.s.save_project(self.path.with_suffix('.pdfwork'),{'page':1})
        other=Session(self.path)
        try:
            path,data,problems=discover(other);self.assertEqual(data['view']['page'],1);self.assertEqual(other.cursor,1);self.assertEqual(problems,[])
        finally:other.close()
        custom=self.root/'other-name.pdfwork';self.s.save_project(custom,{})
        remember(self.path,custom)
        other=Session(self.path)
        try:self.assertEqual(discover(other)[0],custom)
        finally:other.close()

    def test_mismatched_source_never_auto_applies(self):
        data={'format':'studypdf-work','version':2,'source':'source.pdf','source_sha256':'wrong','pages':3,'history':[],'cursor':0,'view':{}}
        self.path.with_suffix('.pdfwork').write_text(json.dumps(data))
        path,data,problems=discover(self.s)
        self.assertIsNone(path);self.assertTrue(problems);self.assertEqual(self.s.cursor,0);self.assertFalse(self.s.dirty)

    def test_actual_legacy_v2_json_and_v3_zlib_read(self):
        data={'format':'studypdf-work','version':2,'source':'source.pdf','source_sha256':self.s.digest,'pages':3,'history':[],'cursor':0,'view':{}}
        for version in (2,3):
            data['version']=version
            raw=json.dumps(data).encode()
            if version==3:raw=b'STUDYPDF3\n'+zlib.compress(raw)
            p=self.root/f'old{version}.pdfwork';p.write_bytes(raw)
            self.s.restore(read_project(p));self.assertFalse(self.s.dirty)

    def test_broken_image_record_refused_without_mutating_session(self):
        self.s.save_project(self.root/'valid.pdfwork',{})
        data=read_project(self.root/'valid.pdfwork');data['notes_html']='<img src="studypdf-image:/'+'a'*64+'">'
        before=self.s.signature()
        with self.assertRaises(ValueError):self.s.restore(data)
        self.assertEqual(self.s.signature(),before)

    def test_export_highlight_keeps_black_text_black(self):
        quads=[quad_list(q) for q in self.s.doc[0].search_for('HIGHLIGHT',quads=True)]
        before=self.s.doc[0].get_pixmap()
        self.s.add('highlight',0,quads=quads,color=[1,.7,0]);self.s.export(self.root/'out.pdf')
        with pdf.open(self.root/'out.pdf') as out:
            page=out[0];after=page.get_pixmap()
            annot=next(a for a in page.annots() if a.type[0]==pdf.PDF_ANNOT_HIGHLIGHT)
            self.assertEqual(annot.blendmode,'Multiply')
            blacks=0;changed=0
            for y in range(61,82):
                for x in range(50,150):
                    if before.pixel(x,y)==(0,0,0):self.assertEqual(after.pixel(x,y),(0,0,0));blacks+=1
                    if before.pixel(x,y)==(255,255,255) and after.pixel(x,y)!=(255,255,255):changed+=1
            self.assertGreater(blacks,50);self.assertGreater(changed,50)


class NotebookGuiTests(GuiTests):
    def setUp(self):
        self.config_dir=tempfile.TemporaryDirectory()
        self.config=patch.dict(os.environ,{'STUDYPDF_CONFIG_DIR':self.config_dir.name});self.config.start()
        super().setUp()
    def tearDown(self):
        self.window.finish_inline(cancel=True)
        super().tearDown();self.config.stop();self.config_dir.cleanup()

    def test_inline_native_keyboard_ime_local_undo_and_cancel(self):
        w=self.window;v=w.edited.view
        # An existing PDF action makes the global undo shortcut active.
        q=[quad_list(q) for q in w.session.doc[0].search_for('HIGHLIGHT',quads=True)]
        w.commit('underline',0,{'quads':q},v)
        w.edit_text(v,0,[50,210,400,310])
        editor=v.inline_editor.editor
        QTest.keyClicks(v.viewport(),'HIGHLIGHT VALID')
        self.assertEqual(w.tool,'text');self.assertEqual(editor.toPlainText(),'HIGHLIGHT VALID')
        event=QInputMethodEvent();event.setCommitString('补充文字');QApplication.sendEvent(QApplication.focusObject(),event)
        self.assertIn('补充文字',editor.toPlainText())
        QTest.keyClick(v.viewport(),Qt.Key_Z,Qt.ControlModifier)
        self.assertEqual(w.session.cursor,1)
        QTest.keyClick(v.viewport(),Qt.Key_Escape)
        self.assertIsNone(v.inline_editor);self.assertEqual(w.session.cursor,1)

    def test_inline_move_resize_and_finish_shortcut(self):
        w=self.window;v=w.edited.view
        w.edit_text(v,0,[50,210,300,290]);QTest.keyClicks(v.viewport(),'ADDED')
        self.drag(v,v.to_scene(0,(50,240)),v.to_scene(0,(70,260)))
        self.assertAlmostEqual(v.inline_editor.rect[0],70,delta=2)
        r=v.inline_editor.rect
        self.drag(v,v.to_scene(0,(r[2]-1,r[3]-1)),v.to_scene(0,(r[2]+40,r[3]+20)))
        self.assertGreater(v.inline_editor.rect[2]-v.inline_editor.rect[0],280)
        QTest.keyClick(v.viewport(),Qt.Key_Return,Qt.ControlModifier)
        self.assertIsNone(v.inline_editor);self.assertEqual(w.session.history[-1]['text'],'ADDED')
        self.assertFalse(self.errors)

    def test_quote_notes_image_paste_autosave_and_open_pdf_restores(self):
        w=self.window;v=w.edited.view
        self.drag(v,v.to_scene(0,(51,73)),v.to_scene(0,(250,73)))
        w.quote_selection(v)
        self.assertIn('HIGHLIGHT',w.notebook.editor.toPlainText());self.assertIn('第 1 页',w.notebook.editor.toPlainText())
        mime=QMimeData();image=QImage(100,80,QImage.Format_RGB32);image.fill(Qt.red);mime.setImageData(image)
        w.notebook.editor.insertFromMimeData(mime)
        self.assertEqual(len(w.session.note_assets),1)
        w.autosave()
        export_path=Path(self.tmp.name)/'notes.html'
        with patch('notebook.QFileDialog.getSaveFileName',return_value=(str(export_path),'HTML')):w.notebook.export()
        exported=export_path.read_text('utf-8')
        self.assertIn('data:image/png;base64,',exported);self.assertIn('#page=1',exported);self.assertNotIn('studypdf-image:',exported)
        record=self.path.with_suffix('.pdfwork');self.assertTrue(record.is_file())
        w.notebook.sync();saved=w.session.notes_html
        w.open_file(self.path)
        self.assertEqual(w.session.project,record)
        self.assertEqual(w.session.notes_html,saved);self.assertEqual(len(w.session.note_assets),1)
        self.assertFalse(self.errors)

    def test_region_capture_inserts_image_and_source(self):
        w=self.window;v=w.edited.view
        w.set_tool('capture')
        self.drag(v,v.to_scene(0,(40,55)),v.to_scene(0,(280,100)))
        self.assertEqual(len(w.session.note_assets),1)
        self.assertIn('第 1 页',w.notebook.editor.toPlainText())
        self.assertEqual(w.session.cursor,0)
        self.assertTrue(w.save_project(quiet=True))
        self.assertFalse(self.errors)

    def test_highlight_pixels_not_gray_overlay(self):
        w=self.window;v=w.edited.view
        area=QRectF(v.to_scene(0,(45,55)),v.to_scene(0,(250,95)))
        def capture():
            image=QImage(205,40,QImage.Format_RGB32);image.fill(Qt.white)
            painter=QPainter(image);v.scene().render(painter,QRectF(0,0,205,40),area);painter.end();return image
        before=capture()
        q=[quad_list(q) for q in w.session.doc[0].search_for('HIGHLIGHT',quads=True)]
        w.commit('highlight',0,{'quads':q,'color':[1,.7,0]},v)
        after=capture();blacks=0;changed=0
        for y in range(40):
            for x in range(205):
                if before.pixelColor(x,y).getRgb()[:3]==(0,0,0):self.assertEqual(after.pixelColor(x,y).getRgb()[:3],(0,0,0));blacks+=1
                elif before.pixelColor(x,y)!=after.pixelColor(x,y):changed+=1
        self.assertGreater(blacks,30);self.assertGreater(changed,50)

    def test_note_undo_does_not_undo_pdf(self):
        w=self.window;v=w.edited.view
        q=[quad_list(q) for q in w.session.doc[0].search_for('HIGHLIGHT',quads=True)]
        w.commit('underline',0,{'quads':q},v)
        w.note_dock.show();w.notebook.editor.setFocus();QTest.keyClicks(w.notebook.editor,'NOTE TEXT')
        QTest.keyClick(w.notebook.editor,Qt.Key_Z,Qt.ControlModifier)
        self.assertEqual(w.session.cursor,1)
        self.assertFalse(self.errors)

    def test_inline_format_undo_matches_committed_style(self):
        w=self.window;v=w.edited.view
        w.edit_text(v,0,[50,210,400,310]);QTest.keyClicks(v.viewport(),'STYLE')
        w.font_size.setValue(22)
        self.assertEqual(v.inline_editor.result()['size'],22)
        QTest.keyClick(v.viewport(),Qt.Key_Z,Qt.ControlModifier)
        self.assertEqual(v.inline_editor.result()['size'],14)
        self.assertTrue(w.finish_inline());self.assertEqual(w.session.history[-1]['size'],14)

    def test_jpeg_import_resizes_and_embeds_portable_png(self):
        from notebook import checked_image
        image=QImage(2400,1200,QImage.Format_RGB32);image.fill(Qt.blue)
        path=Path(self.tmp.name)/'photo.jpg';self.assertTrue(image.save(str(path),'JPEG'))
        self.window.notebook.import_image(str(path))
        blob=next(iter(self.window.session.note_assets.values()))
        self.assertEqual(checked_image(blob).width(),1600)
        self.assertTrue(self.window.save_project(quiet=True))
        self.assertFalse(self.errors)

    def test_mismatched_record_not_overwritten(self):
        w=self.window;p=self.path.with_suffix('.pdfwork')
        p.write_text('{"format":"studypdf-work","version":2,"source_sha256":"wrong","pages":5}')
        old=p.read_bytes();w.open_file(self.path)
        self.assertTrue(w.auto_save_blocked)
        self.assertFalse(w.save_project(quiet=True));self.assertEqual(p.read_bytes(),old)


for name in list(GuiTests.__dict__):
    if name.startswith('test_'):setattr(NotebookGuiTests,name,None)

del GuiTests

if __name__=='__main__':unittest.main()
