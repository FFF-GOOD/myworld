"""0.5: contextual tools, nonmodal colors, comments, named notebooks and explicit caret."""
from pathlib import Path
import os,sys,tempfile,unittest,zipfile,json,hashlib
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pymupdf as pdf
from core import Session,quad_list,read_project
from test_core import make_pdf
from test_gui import GuiTests
from PySide6.QtCore import Qt,QRectF
from PySide6.QtGui import QImage,QPainter,QTextCursor
from PySide6.QtWidgets import QApplication,QStyleOptionGraphicsItem
from PySide6.QtTest import QTest

class ContextCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.path=self.root/'source.pdf';make_pdf(self.path);self.s=Session(self.path)
    def tearDown(self):self.s.close();self.tmp.cleanup()
    def quads(self):return [quad_list(q) for q in self.s.doc[0].search_for('HIGHLIGHT',quads=True)]

    def test_added_annotation_color_comment_undo_export(self):
        mark=self.s.add('highlight',0,quads=self.quads(),color=[1,.8,.1])
        self.s.add('update',0,target=mark['id'],changes={'color':[.8,.2,.3],'comment':'中文评论 Test'})
        self.assertEqual(self.s.annotations(0)[-1]['comment'],'中文评论 Test')
        self.s.undo();self.assertEqual(self.s.annotations(0)[-1]['comment'],'')
        self.s.redo();self.s.export(self.root/'out.pdf')
        with pdf.open(self.root/'out.pdf') as out:
            page=out[0];annot=next(a for a in page.annots() if a.type[0]==pdf.PDF_ANNOT_HIGHLIGHT)
            self.assertEqual(annot.info['content'],'中文评论 Test')
            self.assertAlmostEqual(annot.colors['stroke'][0],.8,places=4)

    def test_base_annotation_changes_preview_and_original_save(self):
        base=self.s.annotations(0)[0]
        self.s.add('update',0,scope='original',target=base['id'],changes={'color':[.7,.1,.5],'comment':'Base comment'})
        with self.s.preview_page(0,edited=False) as preview:
            page=preview[0];a=next(page.annots());self.assertEqual(a.info['content'],'Base comment')
        self.s.save_original()
        with pdf.open(self.path) as out:
            page=out[0];a=next(page.annots());self.assertEqual(a.info['content'],'Base comment')
            self.assertAlmostEqual(a.colors['stroke'][0],.7,places=4)

    def test_work_update_reference_rebased_after_original_save(self):
        mark=self.s.add('highlight',0,scope='original',quads=self.quads())
        self.s.add('update',0,target=mark['id'],changes={'comment':'Work only','color':[.2,.7,.4]})
        self.s.save_original()
        self.assertTrue(self.s.history[0]['target'].startswith('base:'))
        self.assertEqual(self.s.annotations(0,False)[-1]['comment'],'')
        self.assertEqual(self.s.annotations(0,True)[-1]['comment'],'Work only')
        target=self.root/'a.pdfwork';self.s.save_project(target,{})
        other=Session(self.path)
        try:other.restore(read_project(target));self.assertEqual(other.annotations(0)[-1]['comment'],'Work only')
        finally:other.close()

    def test_v4_record_migrates_old_notebook(self):
        data={'format':'studypdf-work','version':4,'source':'source.pdf','source_sha256':self.s.digest,
              'pages':3,'history':[],'cursor':0,'view':{},'notes_html':'<p>旧版笔记</p>'}
        path=self.root/'old.pdfwork'
        with path.open('wb') as f:
            f.write(b'STUDYPDF4\n')
            with zipfile.ZipFile(f,'w') as z:z.writestr('project.json',json.dumps(data))
        self.s.restore(read_project(path))
        self.assertEqual(len(self.s.notebooks),1);self.assertIn('旧版笔记',self.s.notebooks[0]['html'])

    def test_invalid_update_and_note_id_rejected(self):
        with self.assertRaises(ValueError):self.s.add('update',0,target='bad',changes={'color':[float('nan'),0,0]})
        self.s.save_project(self.root/'a.pdfwork',{})
        data=read_project(self.root/'a.pdfwork')
        data['notebooks']=[{'id':'same','title':'A','html':''},{'id':'same','title':'B','html':''}]
        with self.assertRaises(ValueError):self.s.restore(data)


class ContextGuiTests(GuiTests):
    def setUp(self):
        self.cfg=tempfile.TemporaryDirectory();self.config=patch.dict(os.environ,{'STUDYPDF_CONFIG_DIR':self.cfg.name});self.config.start()
        super().setUp()
    def tearDown(self):
        self.window.finish_inline(cancel=True);self.window.hide_context()
        super().tearDown();self.config.stop();self.cfg.cleanup()
    def select_first(self):
        v=self.window.edited.view
        self.drag(v,v.to_scene(0,(51,73)),v.to_scene(0,(250,73)))
        QTest.qWait(15)
        return v

    def test_selection_toolbar_then_annotation_toolbar_color_and_comment(self):
        w=self.window;self.select_first()
        self.assertTrue(w.floating.isVisible());self.assertEqual(w.floating.mode,'selection')
        QTest.mouseClick(w.floating.buttons['highlight'],Qt.LeftButton)
        self.assertEqual(w.floating.mode,'annotation');self.assertIn('comment',w.floating.buttons)
        QTest.mouseClick(w.floating.buttons['color'],Qt.LeftButton)
        self.assertTrue(w.palette.isVisible());self.assertEqual(w.palette.windowModality(),Qt.NonModal)
        QTest.mouseClick(w.palette.swatches['#E25759'],Qt.LeftButton)
        self.assertEqual(w.session.history[-1]['kind'],'update')
        QTest.mouseClick(w.floating.buttons['comment'],Qt.LeftButton)
        card=next(iter(w.edited.view.comments.cards.values()))
        card.editor.setPlainText('My comment');card.flush()
        self.assertEqual(w.session.annotations(0)[-1]['comment'],'My comment')
        self.assertFalse(w.floating.comment_panel.isVisible())
        self.assertFalse(self.errors)

    def test_context_copy_uses_original_selection(self):
        w=self.window;self.select_first();text=w.floating.payload['text']
        QTest.mouseClick(w.floating.buttons['copy'],Qt.LeftButton)
        self.assertEqual(QApplication.clipboard().text(),text)
        self.assertEqual(w.session.cursor,0)

    def test_custom_hex_palette_applies_without_dialog(self):
        w=self.window;w.set_tool('underline');w.choose_color()
        w.palette.hex.setText('#13A45F');QTest.mouseClick(w.palette.apply_button,Qt.LeftButton)
        self.assertAlmostEqual(w.colors['underline'][1],164/255,places=4)
        self.assertFalse(w.palette.isVisible())
        w.choose_color();w.palette.hex.setText('no');w.palette.apply_hex()
        self.assertTrue(w.palette.isVisible());self.assertTrue(w.palette.error.text())
        self.assertFalse(self.errors)

    def test_note_picker_targets_existing_note_and_each_quote_new_line(self):
        w=self.window
        first=w.session.active_note
        second=w.notebook.new_note('复习笔记')
        w.notebook.editor.setPlainText('Existing paragraph')
        w.notebook.select_note(first)
        self.select_first();QTest.mouseClick(w.floating.buttons['note'],Qt.LeftButton)
        menu=w.floating.note_picker
        action=next(a for a in menu.actions() if a.text()=='复习笔记')
        action.trigger();menu.close()
        self.assertEqual(w.session.active_note,second)
        text=w.notebook.editor.toPlainText()
        self.assertIn('Existing paragraph\n',text)
        self.assertIn('HIGHLIGHT',text)
        w.notebook.sync()
        self.assertNotIn('HIGHLIGHT',next(n['html'] for n in w.session.notebooks if n['id']==first))
        self.assertFalse(self.errors)

    def test_note_picker_new_note_and_multi_note_roundtrip(self):
        w=self.window;self.select_first()
        payload=dict(w.floating.payload);view=w.floating.view
        w.quote_payload(payload,view,create_new=True)
        second=w.session.active_note
        image=QImage(70,30,QImage.Format_RGB32);image.fill(Qt.green)
        w.notebook.insert_image(image)
        w.notebook.note_selector.setEditText('摘录与截图');w.notebook.rename_current()
        self.assertTrue(w.save_project(quiet=True))
        w.open_file(self.path)
        self.assertEqual(len(w.session.notebooks),2)
        self.assertEqual(w.session.active_note,second)
        self.assertEqual(w.notebook.note_selector.currentText(),'摘录与截图')
        self.assertEqual(len(w.session.note_assets),1)

    def test_inactive_note_images_retained_when_another_note_saved(self):
        w=self.window;first=w.session.active_note
        image=QImage(70,30,QImage.Format_RGB32);image.fill(Qt.green);w.notebook.insert_image(image)
        w.notebook.new_note('No images');w.notebook.editor.setPlainText('Second body')
        self.assertTrue(w.save_project(quiet=True))
        w.open_file(self.path);w.notebook.select_note(first)
        self.assertEqual(len(w.session.note_assets),1)
        self.assertIn('studypdf-image:',w.notebook.editor.toHtml())

    def test_clipboard_image_paste_separate_paragraph_and_undo(self):
        w=self.window;w.toggle_notebook()
        e=w.notebook.editor;e.setPlainText('BeforeAfter')
        cursor=e.textCursor();cursor.setPosition(6);e.setTextCursor(cursor)
        image=QImage(50,20,QImage.Format_RGB32);image.fill(Qt.blue);QApplication.clipboard().setImage(image)
        QTest.keyClick(e,Qt.Key_V,Qt.ControlModifier)
        lines=e.toPlainText().split('\n')
        self.assertIn('Before',lines);self.assertIn('After',lines);self.assertIn('\ufffc',lines)
        QTest.keyClick(e,Qt.Key_Z,Qt.ControlModifier)
        self.assertEqual(e.toPlainText(),'BeforeAfter')
        self.assertFalse(self.errors)

    def test_explicit_blinking_caret_and_position_reset(self):
        w=self.window;v=w.edited.view
        w.edit_text(v,0,[50,210,400,300]);QTest.keyClicks(v.viewport(),'VISIBLE')
        item=v.inline_editor;item.caret_timer.stop()
        self.assertEqual(item.editor.cursorWidth(),0)
        def render(visible):
            item.caret_on=visible
            image=QImage(350,90,QImage.Format_RGB32);image.fill(Qt.white)
            painter=QPainter(image);opt=QStyleOptionGraphicsItem();opt.exposedRect=item.boundingRect()
            item.paint(painter,opt);painter.end();return image
        before,after=render(False),render(True)
        diff=sum(before.pixel(x,y)!=after.pixel(x,y) for y in range(90) for x in range(350))
        self.assertGreater(diff,10)
        item.caret_on=False
        c=item.editor.textCursor();c.setPosition(1);item.editor.setTextCursor(c)
        self.assertTrue(item.caret_on)
        self.assertTrue(w.finish_inline())

    def test_header_swap_button_and_persistence(self):
        w=self.window
        QTest.mouseClick(w.original.swap_button,Qt.LeftButton)
        self.assertIs(w.panes.widget(0),w.edited)
        self.assertTrue(w.layout_dirty)
        w.autosave();self.assertFalse(w.layout_dirty)
        w.open_file(self.path)
        self.assertTrue(w.swapped);self.assertIs(w.panes.widget(0),w.edited)
        self.assertFalse(w.original.view.edited);self.assertTrue(w.edited.view.edited)

    def test_inline_palette_keeps_editor_and_caret_position(self):
        w=self.window;v=w.edited.view
        w.edit_text(v,0,[50,210,400,300]);QTest.keyClicks(v.viewport(),'CARET COLOR')
        item=v.inline_editor;pos=item.editor.textCursor().position()
        w.choose_color();w.palette.choose('#B52D74')
        self.assertIs(v.inline_editor,item);self.assertEqual(w.session.cursor,0)
        self.assertEqual(item.editor.textCursor().position(),pos)
        self.assertTrue(item.caret_on)
        self.assertAlmostEqual(item.result()['color'][0],181/255,places=4)
        self.assertTrue(w.finish_inline())

    def test_ime_input_recovers_after_palette_close(self):
        from PySide6.QtGui import QInputMethodEvent
        w=self.window;v=w.edited.view
        w.edit_text(v,0,[50,210,400,300]);QTest.qWait(20)
        w.choose_color();w.palette.choose('#13A45F');QTest.qWait(20)
        event=QInputMethodEvent();event.setCommitString('继续输入')
        QApplication.sendEvent(QApplication.focusObject(),event)
        self.assertEqual(v.inline_editor.editor.toPlainText(),'继续输入')
        self.assertTrue(v.inline_editor.caret_on)
        self.assertTrue(w.finish_inline())

    def test_original_popup_operations_stay_in_original_scope(self):
        w=self.window;v=w.original.view
        self.drag(v,v.to_scene(0,(51,73)),v.to_scene(0,(250,73)))
        QTest.mouseClick(w.floating.buttons['strike'],Qt.LeftButton)
        self.assertEqual(w.session.history[-1]['scope'],'original')
        w.choose_color();w.palette.choose('#2E6EE8')
        self.assertEqual(w.session.history[-1]['scope'],'original')
        self.assertEqual(w.session.annotations(0,False)[-1]['color'],w.session.annotations(0,True)[-1]['color'])
        self.assertFalse(self.errors)

    def test_switching_tool_color_does_not_recolor_previous_annotation(self):
        w=self.window;self.select_first();QTest.mouseClick(w.floating.buttons['highlight'],Qt.LeftButton)
        old_id=w.selected_annotation['id'];old_color=w.selected_annotation['color'];count=w.session.cursor
        w.set_tool('ink');self.assertIsNone(w.selected_annotation)
        w.choose_color();w.palette.choose('#13A45F')
        self.assertEqual(w.session.cursor,count)
        self.assertEqual(next(a['color'] for a in w.session.annotations(0) if a['id']==old_id),old_color)

    def test_scroll_hides_contextual_bar(self):
        w=self.window;v=self.select_first()
        self.assertTrue(w.floating.isVisible())
        v.verticalScrollBar().setValue(v.verticalScrollBar().value()+50)
        self.assertFalse(w.floating.isVisible())


for name in list(GuiTests.__dict__):
    if name.startswith('test_'):setattr(ContextGuiTests,name,None)
del GuiTests

if __name__=='__main__':unittest.main()
