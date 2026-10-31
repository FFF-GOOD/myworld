import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from pathlib import Path
import sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QPointF,Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from app import MainWindow,create_application
from test_core import make_pdf
from core import quad_list


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=create_application()

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'source.pdf'
        make_pdf(self.path,count=5)
        self.window=MainWindow()
        self.errors=[]
        self.window.error=lambda error:self.errors.append(str(error))
        self.window.show()
        self.window.open_file(self.path)
        self.window.set_zoom(.8)
        self.window.goto(0)
        self.wait_page(0)
        self.assertFalse(self.errors)

    def tearDown(self):
        self.window.maybe_save=lambda:True
        self.window.close()
        self.tmp.cleanup()

    def wait_page(self,number):
        import time
        until=time.monotonic()+8
        while time.monotonic()<until:
            QTest.qWait(15)
            if number in self.window.session._text_cache and all(number in v.cache for v in self.window.views): return
        self.fail('Renderer did not finish: '+self.window.statusBar().currentMessage())

    def drag(self,view,start,end):
        QTest.mousePress(view.viewport(),Qt.LeftButton,pos=view.mapFromScene(start))
        QTest.mouseMove(view.viewport(),view.mapFromScene(end),delay=20)
        QTest.mouseRelease(view.viewport(),Qt.LeftButton,pos=view.mapFromScene(end))

    def assert_synced(self):
        a,b=self.window.views
        pa=a.mapToScene(a.viewport().rect().center());pb=b.mapToScene(b.viewport().rect().center())
        self.assertLess(abs(pa.y()-pb.y()),3)
        self.assertEqual(a.current_page(),b.current_page())
        self.assertEqual(a.transform(),b.transform())

    def test_text_selection_copy_then_highlight_and_delete(self):
        w=self.window;v=w.edited.view
        self.drag(v,v.to_scene(0,(51,73)),v.to_scene(0,(250,73)))
        self.assertIn('HIGHLIGHT',v.selection_text)
        QTest.keyClick(v.viewport(),Qt.Key_C,Qt.ControlModifier)
        self.assertIn('HIGHLIGHT',QApplication.clipboard().text())
        w.set_tool('highlight')
        self.assertEqual(w.session.cursor,1)
        new=[a for a in w.session.annotations(0) if not a['id'].startswith('base:')][0]
        w.select_annotation(new);w.delete_annotation()
        self.assertEqual(len(w.session.annotations(0)),1)
        w.history(False)
        self.assertEqual(len(w.session.annotations(0)),2)
        self.assertFalse(self.errors)

    def test_drag_underline_both_scopes_and_shortcuts(self):
        w=self.window;v=w.edited.view
        w.set_tool('underline')
        self.drag(v,v.to_scene(0,(51,123)),v.to_scene(0,(220,123)))
        self.assertEqual(w.session.cursor,1)
        original=w.original.view
        self.drag(original,original.to_scene(0,(51,73)),original.to_scene(0,(220,73)))
        self.assertEqual(w.session.cursor,2)
        self.assertEqual(w.session.history[-1]['scope'],'original')
        QTest.keyClick(v.viewport(),Qt.Key_Z,Qt.ControlModifier)
        self.assertEqual(w.session.cursor,1)
        QTest.keyClick(v.viewport(),Qt.Key_Y,Qt.ControlModifier)
        self.assertEqual(w.session.cursor,2)

    def test_rectangle_and_brush_are_undoable(self):
        w=self.window;v=w.edited.view
        w.set_tool('rect')
        self.drag(v,v.to_scene(0,(40,55)),v.to_scene(0,(260,95)))
        self.assertEqual(w.session.cursor,1)
        w.history(False)
        self.assertEqual(w.session.effective(0)[2],[])
        w.set_tool('brush')
        self.drag(v,v.to_scene(0,(50,70)),v.to_scene(0,(220,70)))
        self.assertEqual(w.session.cursor,1)
        self.assertGreater(len(w.session.effective(0)[2]),5)
        w.history(False)
        self.assertEqual(w.session.effective(0)[2],[])

    def test_freehand_is_standard_ink(self):
        w=self.window;v=w.edited.view
        w.set_tool('ink')
        self.drag(v,v.to_scene(0,(80,220)),v.to_scene(0,(200,235)))
        self.assertEqual(w.session.history[-1]['kind'],'ink')
        self.assertFalse(self.errors)

    def test_sync_rotate_swap_and_search(self):
        w=self.window
        w.goto(2);self.assert_synced()
        w.edited.view.verticalScrollBar().setValue(1500);self.assert_synced()
        w.set_zoom(1.5);self.assert_synced()
        for _ in range(4):
            w.rotate();self.assert_synced()
        w.swap();self.assertIs(w.panes.widget(0),w.edited);self.assert_synced()
        w.search_input.setText('HIGHLIGHT');w.find_next()
        self.assertEqual(len(w.search_results),5)
        self.assertFalse(self.errors)

    def test_drawing_on_rotated_cropped_page(self):
        w=self.window;w.goto(1);v=w.edited.view
        w.set_tool('highlight')
        glyphs=w.session.text_index(1).glyphs
        first=(glyphs[0].box.tl+glyphs[0].box.br)/2
        last=(glyphs[8].box.tl+glyphs[8].box.br)/2
        self.drag(v,v.to_scene(1,first),v.to_scene(1,last))
        self.assertEqual(w.session.cursor,1)
        self.assertEqual(w.session.history[0]['page'],1)
        self.assertFalse(self.errors)

    def test_image_only_page_region_highlight(self):
        import pymupdf as pdf
        path=Path(self.tmp.name)/'scan.pdf'
        doc=pdf.open();page=doc.new_page(width=600,height=800)
        pix=pdf.Pixmap(pdf.csRGB,pdf.IRect(0,0,100,100),False);pix.clear_with(200)
        page.insert_image(page.rect,pixmap=pix);doc.save(path);doc.close()
        w=self.window;w.open_file(path);w.set_zoom(.8);w.goto(0)
        self.wait_page(0)
        w.set_tool('highlight');v=w.edited.view
        self.drag(v,v.to_scene(0,(50,100)),v.to_scene(0,(230,140)))
        self.assertEqual(w.session.cursor,1)
        self.assertEqual(w.session.history[0]['kind'],'highlight')
        self.assertFalse(self.errors)

    def test_search_typing_keeps_text_and_tools(self):
        w=self.window
        w.search_input.setFocus()
        QTest.keyClicks(w.search_input,'HIGHLIGHT')
        self.assertEqual(w.search_input.text(),'HIGHLIGHT')
        self.assertEqual(w.tool,'select')




class RevisionGuiTests(GuiTests):
    # Reuse setup helpers without running the inherited suite twice.
    def test_text_overlay_edit_delete_and_undo(self):
        w=self.window;v=w.edited.view
        w.set_tool('text')
        self.drag(v,v.to_scene(0,(50,210)),v.to_scene(0,(400,280)))
        self.assertIsNotNone(v.inline_editor)
        QTest.keyClicks(v.inline_editor.editor,'ADDED TEXT')
        w.font_size.setValue(18)
        self.assertTrue(w.finish_inline())
        self.assertEqual(w.session.cursor,1)
        first=w.session.history[-1]
        self.assertEqual(first['kind'],'text');self.assertEqual(first['size'],18)
        self.assertTrue(v.overlays[0])
        w.edit_text(v,0,first['rect'],first)
        v.inline_editor.editor.setPlainText('UPDATED')
        self.assertTrue(w.finish_inline())
        self.assertEqual(w.session.cursor,2)
        self.assertEqual(len(w.session.effective(0)[0]),1)
        w.history(False)
        self.assertIn(first['id'],w.session.effective(0)[0])
        a=[a for a in w.session.annotations(0) if a.get('kind')=='text'][0]
        w.select_annotation(a,v);w.delete_annotation()
        self.assertEqual(len(w.session.effective(0)[0]),0)
        self.assertFalse(self.errors)

    def test_lightweight_annotation_does_not_call_pdf_render_on_ui(self):
        from unittest.mock import patch
        from core import quad_list
        w=self.window
        quads=[quad_list(q) for q in w.session.doc[0].search_for('HIGHLIGHT',quads=True)]
        before=w.renderer.metrics['requests']
        import time
        timings=[]
        with patch.object(w.session,'render',side_effect=AssertionError('UI rendering must be isolated')),patch.object(w.session,'preview_page',side_effect=AssertionError('UI must not copy PDF pages')):
            for i in range(60):
                start=time.perf_counter()
                w.commit('strike' if i%2 else 'highlight',0,{'quads':quads},w.original.view if i%3==0 else w.edited.view)
                timings.append(time.perf_counter()-start)
            QTest.qWait(50)
        self.assertFalse(self.errors)
        self.assertLess(max(timings),.25)
        self.assertEqual(w.renderer.metrics['requests'],before)

    def test_original_save_updates_existing_work_record(self):
        from core import quad_list,read_project
        w=self.window
        quads=[quad_list(q) for q in w.session.doc[0].search_for('HIGHLIGHT',quads=True)]
        w.commit('underline',0,{'quads':quads},w.original.view)
        w.commit('erase',0,{'rects':[[40,50,280,95]]},w.edited.view)
        work=Path(self.tmp.name)/'a.pdfwork';w.session.save_project(work,w.view_state())
        w.save_original()
        self.wait_page(0)
        self.assertFalse(w.session.original_dirty)
        self.assertEqual(read_project(work)['source_sha256'],w.session.digest)
        self.assertEqual(w.session.cursor,1)
        self.assertFalse(self.errors)

    def test_switching_pane_clears_annotation_selection(self):
        w=self.window
        a=w.session.annotations(0)[0]
        w.select_annotation(a,w.edited.view)
        self.assertIsNotNone(w.selected_annotation)
        w.activate_view(w.original.view)
        self.assertIsNone(w.selected_annotation)
        self.assertFalse(w.delete_action.isEnabled())

    def test_text_dialog_shortcuts_do_not_trigger_annotation_actions(self):
        from text_dialog import TextDialog
        from PySide6.QtCore import QTimer
        w=self.window
        dialog=TextDialog(w)
        def type_text():
            # Offscreen Qt may not activate a modal window before a short timer fires.
            dialog.activateWindow();QApplication.setActiveWindow(dialog)
            dialog.editor.setFocus(Qt.OtherFocusReason)
            QTest.keyClicks(dialog.editor,'HIGHLIGHT VALID TEXT')
            QTest.keyClick(dialog.editor,Qt.Key_Return,Qt.ControlModifier)
        deadline=QTimer(dialog);deadline.setSingleShot(True);deadline.timeout.connect(dialog.reject)
        dialog.finished.connect(deadline.stop);deadline.start(2000)
        QTimer.singleShot(20,type_text)
        self.assertEqual(dialog.exec(),1)
        self.assertEqual(w.session.cursor,0)
        self.assertEqual(w.tool,'select')
        self.assertEqual(dialog.data()['text'],'HIGHLIGHT VALID TEXT')

    def test_async_render_latest_request_wins_on_rapid_zoom_and_undo(self):
        w=self.window
        for zoom in (.6,1.4,.9,1.2,1):
            w.set_zoom(zoom)
            w.edited.view.render_visible();w.original.view.render_visible()
        w.commit('erase',0,{'rects':[[40,50,280,95]]},w.edited.view)
        w.edited.view.render_visible()
        w.history(False)
        w.edited.view.render_visible()
        import time
        end=time.monotonic()+8
        while time.monotonic()<end:
            QTest.qWait(20)
            if not w.renderer.queue and not w.renderer.inflight:break
        for v in w.views:
            self.assertEqual(v.pages[0]['key'],v.wanted[0])
            self.assertEqual(v.pages[0]['key'][0],1)
        self.assertEqual(w.session.effective(0)[2],[])
        self.assertFalse(self.errors)

    def test_text_dialog_detects_insufficient_height(self):
        from text_dialog import TextDialog
        from PySide6.QtWidgets import QDialogButtonBox
        dialog=TextDialog(self.window,rect=[40,40,150,60],bounds=[0,0,600,800])
        dialog.editor.setPlainText('Too much text. '*20)
        self.assertFalse(dialog.buttons.button(QDialogButtonBox.Ok).isEnabled())
        dialog.box_height.setValue(600)
        self.assertTrue(dialog.buttons.button(QDialogButtonBox.Ok).isEnabled())
        self.assertEqual(dialog.data()['rect'],[40,40,150,640])
        dialog.close()

    def test_text_tool_click_existing_text_edits_instead_of_duplicate(self):
        w=self.window;v=w.edited.view
        w.commit('text',0,{'rect':[50,210,400,280],'text':'OLD','font':'内置中文字体','size':16,'color':[.2,.3,.4]},v)
        original=w.session.history[0]
        w.set_tool('text')
        QTest.mouseClick(v.viewport(),Qt.LeftButton,pos=v.mapFromScene(v.to_scene(0,(80,230))))
        self.assertIsNotNone(v.inline_editor)
        v.inline_editor.editor.setPlainText('NEW');self.assertTrue(w.finish_inline())
        self.assertEqual(w.session.cursor,2)
        self.assertEqual(w.session.history[-1]['replaces'],original['id'])
        self.assertEqual(len(w.session.effective(0)[0]),1)
        self.assertFalse(self.errors)


# Do not rerun inherited tests in the revision subclass; setup/helpers remain inherited.
for _name in list(GuiTests.__dict__):
    if _name.startswith('test_'):
        setattr(RevisionGuiTests,_name,None)

if __name__=='__main__':unittest.main()
