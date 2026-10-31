"""0.6 regression coverage: persistent comments, contextual formats and resizable notebook images."""
import sys,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pymupdf as pdf
from core import quad_list,Session,read_project
from test_gui import GuiTests as _GuiTests
from PySide6.QtCore import Qt,QPoint
from PySide6.QtGui import QImage,QTextCursor
from PySide6.QtTest import QTest

class CardsGuiTests(_GuiTests):
    def setUp(self):
        self.cfg=tempfile.TemporaryDirectory();self.config=patch.dict(os.environ,{'STUDYPDF_CONFIG_DIR':self.cfg.name});self.config.start()
        super().setUp()
    def tearDown(self):
        self.window.flush_comments()
        super().tearDown();self.config.stop();self.cfg.cleanup()
    def create(self,kind='highlight',original=False,comment='A comment'):
        w=self.window;v=w.original.view if original else w.edited.view
        qs=[quad_list(q) for q in w.session.doc[0].search_for('HIGHLIGHT',quads=True)]
        op=w.commit(kind,0,{'quads':qs,'color':[.9,.2,.3],'comment':comment},v)
        v.comments.sync()
        a=next(a for a in w.session.annotations(0,v.edited) if a['id']==op['id'])
        return v,a,v.comments.cards.get(op['id'])

    def test_toolbar_group_and_contextual_text_controls(self):
        w=self.window
        actions=w.annotation_tools.actions();i=actions.index(w.tool_actions['capture'])
        self.assertEqual(actions[i+1:i+3],[w.quote_action,w.notebook_action])
        self.assertTrue(all(not a.isVisible() for a in w.text_property_actions))
        w.set_tool('text');self.assertTrue(all(a.isVisible() for a in w.text_property_actions))
        w.set_tool('select');self.assertTrue(all(not a.isVisible() for a in w.text_property_actions))
        op=w.commit('text',0,{'rect':[40,200,400,270],'text':'Text','font':'内置中文字体','size':18,'color':[0,0,0]})
        a=next(a for a in w.session.annotations(0) if a['id']==op['id'])
        w.select_annotation(a)
        self.assertTrue(all(a.isVisible() for a in w.text_property_actions))
        self.assertEqual(w.font_size.value(),18)
        w.font_size.setValue(22)
        self.assertIsNotNone(w.active_view.inline_editor)
        self.assertEqual(w.active_view.inline_editor.result()['size'],22)

    def test_comment_persistent_hover_opacity_and_no_render(self):
        w=self.window;v,a,card=self.create()
        self.assertIsNotNone(card);w.hide_context();self.assertTrue(card.isVisible())
        before=w.renderer.metrics.copy()
        w.search_input.setFocus();QTest.qWait(20);self.assertAlmostEqual(card.effect.opacity(),.58)
        QTest.mouseMove(card.editor.viewport(),QPoint(20,20));QTest.qWait(20)
        self.assertIs(v.comments.hovered,card);self.assertTrue(v.comments.pointer.isVisible())
        QTest.mouseClick(card.editor.viewport(),Qt.LeftButton)
        self.assertAlmostEqual(card.effect.opacity(),1.)
        self.assertEqual(card.annotation['color'],[.9,.2,.3])
        self.assertEqual(w.renderer.metrics.get('requests'),before.get('requests'))

    def test_comment_typing_save_restore_and_scope(self):
        w=self.window;v,a,card=self.create(original=True)
        card.editor.setPlainText('Original edited comment')
        self.assertTrue(w.save_project(quiet=True))
        self.assertEqual(w.session.annotations(0,False)[-1]['comment'],'Original edited comment')
        w.open_file(self.path);QTest.qWait(25)
        v=w.original.view;v.comments.sync();card=v.comments.cards[a['id']]
        self.assertEqual(card.editor.toPlainText(),'Original edited comment')
        w.save_original()
        self.assertFalse(self.errors)
        with pdf.open(self.path) as d:
            page=d[0];self.assertIn('Original edited comment',[x.info['content'] for x in page.annots()])

    def test_moved_comment_survives_zoom_swap_and_original_save(self):
        w=self.window;v,a,card=self.create(original=True)
        card.move(35,75);v.comments.remember(card)
        expected=list(v.comments.positions[a['id']])
        w.set_zoom(1.1);w.swap();v.comments.sync()
        self.assertEqual(v.comments.positions[a['id']],expected)
        w.save_original();v.comments.sync()
        self.assertIn(a['id'],v.comments.cards)
        self.assertTrue(w.save_project(quiet=True))
        w.open_file(self.path);QTest.qWait(20)
        self.assertEqual(w.original.view.comments.positions[a['id']],expected)
        self.assertFalse(self.errors)

    def test_comment_undo_redo_and_delete(self):
        w=self.window;v,a,card=self.create('underline',comment='')
        self.assertIsNone(card)
        card=v.comments.open(a);card.editor.setPlainText('Underline comment');card.flush()
        w.history(False);v.comments.sync()
        self.assertEqual(w.session.annotations(0)[-1]['comment'],'')
        w.history(True);v.comments.sync()
        self.assertEqual(w.session.annotations(0)[-1]['comment'],'Underline comment')
        w.select_annotation(w.session.annotations(0)[-1],v);w.delete_annotation();v.comments.sync()
        self.assertNotIn(a['id'],v.comments.cards)

    def test_strike_comment_export_preserves_color_and_text(self):
        w=self.window;v,a,card=self.create('strike')
        target=Path(self.tmp.name)/'export.pdf';w.session.export(target)
        with pdf.open(target) as d:
            page=d[0];annot=next(x for x in page.annots() if x.type[0]==pdf.PDF_ANNOT_STRIKE_OUT)
            self.assertEqual(annot.info['content'],'A comment');self.assertAlmostEqual(annot.colors['stroke'][0],.9,places=4)

    def test_comment_scroll_releases_widgets_and_restores(self):
        w=self.window;v,a,card=self.create()
        w.goto(4);v.comments.sync();self.assertNotIn(a['id'],v.comments.cards)
        w.goto(0);v.comments.sync();self.assertIn(a['id'],v.comments.cards)
        self.assertEqual(v.comments.cards[a['id']].editor.toPlainText(),'A comment')

    def test_external_annotation_names_do_not_collide_between_pages(self):
        path=Path(self.tmp.name)/'external.pdf'
        d=pdf.open()
        for n in range(2):
            page=d.new_page();page.insert_text((50,70),'Text')
            mark=page.add_highlight_annot(page.search_for('Text'))
            d.xref_set_key(mark.xref,'NM',pdf.get_pdf_str('same-name'))
            mark.set_info(content='Page '+str(n));mark.update()
        d.save(path);d.close()
        w=self.window;w.open_file(path)
        first=w.session.annotations(0)[0];second=w.session.annotations(1)[0]
        self.assertNotEqual(first['anchor_id'],second['anchor_id'])

    def test_export_flushes_latest_comment_before_file_dialog(self):
        w=self.window;v,a,card=self.create()
        card.editor.setPlainText('Latest unflushed text')
        target=Path(self.tmp.name)/'latest.pdf'
        with patch('app.QFileDialog.getSaveFileName',return_value=(str(target),'PDF (*.pdf)')), patch('app.QMessageBox.information'):
            w.export()
        with pdf.open(target) as d:
            page=d[0]
            self.assertIn('Latest unflushed text',[x.info['content'] for x in page.annots()])
        self.assertFalse(self.errors)

    def test_title_drag_updates_record_and_keeps_editable_focus(self):
        w=self.window;v,a,card=self.create()
        start=QPoint(30,12);end=QPoint(70,50)
        QTest.mousePress(card.header,Qt.LeftButton,pos=start)
        QTest.mouseMove(card.header,end)
        QTest.mouseRelease(card.header,Qt.LeftButton,pos=end)
        self.assertIn(a['id'],v.comments.positions)
        self.assertTrue(card.editor.hasFocus())
        self.assertEqual(card.effect.opacity(),1.)

    def select_image(self):
        n=self.window.notebook;self.window.note_dock.show()
        image=QImage(300,150,QImage.Format_RGB32);image.fill(Qt.blue);n.insert_image(image)
        text=n.editor.toPlainText();pos=text.index('\ufffc')
        c=n.editor.image_cursor(pos);n.editor.setTextCursor(c);QTest.qWait(10)
        return n,c

    def test_image_resize_ratio_undo_dedup_and_roundtrip(self):
        w=self.window;n,c=self.select_image()
        before=c.charFormat().toImageFormat().width();assets=dict(w.session.note_assets)
        self.assertTrue(n.image_bar.isVisible())
        n.image_width.setValue(180)
        fmt=n.editor.selected_image.charFormat().toImageFormat()
        self.assertEqual(fmt.width(),180);self.assertEqual(fmt.height(),90)
        self.assertEqual(w.session.note_assets,assets)
        n.editor.undo()
        self.assertEqual(n.editor.image_cursor(c.selectionStart()).charFormat().toImageFormat().width(),before)
        n.editor.redo();self.assertTrue(w.save_project(quiet=True))
        w.open_file(self.path);e=w.notebook.editor
        cur=e.image_cursor(e.toPlainText().index('\ufffc'))
        self.assertEqual(cur.charFormat().toImageFormat().width(),180)
        self.assertEqual(len(w.session.note_assets),1)

    def test_image_handle_drag_one_undo_and_fit(self):
        w=self.window;n,c=self.select_image();e=n.editor
        original=e.selected_image.charFormat().toImageFormat().width();r=e.image_rect()
        start=QPoint(round(r.right()),round(r.bottom()));end=start-QPoint(60,30)
        QTest.mousePress(e.viewport(),Qt.LeftButton,pos=start)
        QTest.mouseMove(e.viewport(),end);QTest.mouseRelease(e.viewport(),Qt.LeftButton,pos=end)
        self.assertLess(e.selected_image.charFormat().toImageFormat().width(),original-40)
        e.undo()
        self.assertEqual(e.image_cursor(c.selectionStart()).charFormat().toImageFormat().width(),original)
        e.setTextCursor(e.image_cursor(c.selectionStart()));n.image_original()
        self.assertEqual(e.selected_image.charFormat().toImageFormat().width(),300)

    def test_invalid_layout_ignored_and_card_edit_keeps_cursor(self):
        w=self.window;v,a,card=self.create()
        card.editor.setFocus();card.editor.setPlainText('abcdef')
        c=card.editor.textCursor();c.setPosition(3);card.editor.setTextCursor(c);card.flush();v.comments.sync()
        self.assertEqual(card.editor.textCursor().position(),3)
        v.comments.reset({'bad':[0,float('nan'),0],'bad2':[0],'ok':[0,10,20]})
        self.assertEqual(v.comments.positions,{'ok':[0,10,20]})
        self.assertFalse(self.errors)

# Prevent discovery from running the imported base suite a second time.
del _GuiTests
