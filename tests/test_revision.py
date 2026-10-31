"""Regression tests for 0.3: text, scoped edits, compact work files, async UI."""
from pathlib import Path
import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pymupdf as pdf
from core import Session,quad_list,read_project,sha256,PROJECT_MAGIC
from test_core import make_pdf


class RevisionCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.path=self.root/'source.pdf';make_pdf(self.path)
        self.s=Session(self.path)
    def tearDown(self):self.s.close();self.tmp.cleanup()
    def quads(self,text):return [quad_list(q) for q in self.s.doc[0].search_for(text,quads=True)]
    def text(self,**extra):
        data={'rect':[45,50,400,120],'text':'补充内容 Added text','font':'内置中文字体','size':16,'color':[.8,.1,.2]}
        data.update(extra);return data

    def test_erase_then_add_text_survives_export_and_roundtrip(self):
        self.s.add('erase',0,rects=[[40,50,410,130]])
        text=self.s.add('text',0,**self.text())
        self.s.export(self.root/'out.pdf')
        with pdf.open(self.root/'out.pdf') as out:
            body=out[0].get_text()
            self.assertIn('补充内容',body);self.assertIn('Added text',body);self.assertNotIn('HIGHLIGHT',body)
            spans=[x for b in out[0].get_text('dict')['blocks'] for l in b.get('lines',[]) for x in l['spans']]
            self.assertTrue(any(abs(span['size']-16)<.1 and span['color']==0xcc1a33 for span in spans))
        self.s.save_project(self.root/'a.pdfwork',{})
        other=Session(self.path)
        try:
            other.restore(read_project(self.root/'a.pdfwork'))
            self.assertEqual(other.history[-1]['text'],text['text'])
        finally:other.close()

    def test_text_edit_is_one_undo_and_later_erasing_removes_text(self):
        original=self.s.add('text',0,**self.text(text='FIRST'))
        updated=self.s.add('text',0,replaces=original['id'],**self.text(text='SECOND',size=20))
        self.assertEqual(list(self.s.effective(0)[0]),[updated['id']])
        self.s.undo();self.assertEqual(list(self.s.effective(0)[0]),[original['id']])
        self.s.redo()
        self.s.add('erase',0,rects=[[45,50,80,80]])
        self.assertEqual(self.s.effective(0)[0],{})

    def test_original_scope_persists_without_work_erasure(self):
        before=sha256(self.path)
        mark=self.s.add('underline',0,scope='original',quads=self.quads('HIGHLIGHT'))
        self.s.add('erase',0,rects=[[40,50,300,95]])
        self.assertIn(mark['id'],self.s.effective(0,False)[0])
        self.assertNotIn(mark['id'],self.s.effective(0,True)[0])
        backup=self.s.save_original()
        self.assertEqual(sha256(backup),before)
        self.assertNotEqual(sha256(self.path),before)
        self.assertFalse(self.s.original_dirty)
        self.assertEqual(self.s.cursor,1)
        with pdf.open(self.path) as source:
            page=source[0]
            self.assertIn('HIGHLIGHT',page.get_text())
            self.assertEqual(len(list(page.annots())),2)
        self.s.export(self.root/'out.pdf')
        with pdf.open(self.root/'out.pdf') as out:self.assertNotIn('HIGHLIGHT',out[0].get_text())
        self.s.save_project(self.root/'new.pdfwork',{})
        restored=Session(self.path)
        try:restored.restore(read_project(self.root/'new.pdfwork'));self.assertEqual(restored.cursor,1)
        finally:restored.close()

    def test_original_text_save_embeds_text_and_keeps_backup(self):
        self.s.add('text',0,scope='original',**self.text(rect=[40,210,500,250]))
        backup=self.s.save_original()
        self.assertTrue(backup.is_file())
        with pdf.open(self.path) as source:self.assertIn('补充内容',source[0].get_text())
        self.assertEqual(self.s.cursor,0)
        self.assertIn('补充内容',self.s.doc[0].get_text())

    def test_work_deletion_of_original_pending_markup_remapped(self):
        mark=self.s.add('highlight',0,scope='original',quads=self.quads('HIGHLIGHT'))
        self.s.add('delete',0,target=mark['id'])
        self.s.save_original()
        self.assertTrue(self.s.history[0]['target'].startswith('base:'))
        self.assertEqual(len(self.s.annotations(0,False)),2)
        self.assertEqual(len(self.s.annotations(0,True)),1)
        self.s.undo();self.assertEqual(len(self.s.annotations(0,True)),2)
        self.s.redo()
        self.s.save_project(self.root/'a.pdfwork',{})
        other=Session(self.path)
        try:other.restore(read_project(self.root/'a.pdfwork'))
        finally:other.close()

    def test_original_annotation_deletion_survives_work_rebase(self):
        base=self.s.annotations(0)[0]
        self.s.add('delete',0,scope='original',target=base['id'])
        self.s.add('strike',0,quads=self.quads('HIGHLIGHT'))
        self.s.save_original()
        self.assertEqual(len(self.s.annotations(0,False)),0)
        self.assertEqual(len(self.s.annotations(0,True)),1)
        self.s.save_project(self.root/'a.pdfwork',{})
        other=Session(self.path)
        try:other.restore(read_project(self.root/'a.pdfwork'))
        finally:other.close()

    def test_old_json_projects_compatible_and_new_stores_small(self):
        for i in range(1000):self.s.add('underline',0,quads=self.quads('HIGHLIGHT'))
        self.s.save_project(self.root/'a.pdfwork',{})
        raw=(self.root/'a.pdfwork').read_bytes()
        self.assertTrue(raw.startswith(PROJECT_MAGIC));self.assertLess(len(raw),60000)
        data=read_project(self.root/'a.pdfwork');data['version']=2
        for op in data['history']:op.pop('scope')
        other=Session(self.path)
        try:other.restore(data);self.assertEqual(other.cursor,1000)
        finally:other.close()

    def test_local_font_is_embedded_as_subset(self):
        font=Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
        if not font.is_file():self.skipTest('Test font unavailable')
        self.s.add('text',0,**self.text(text='Custom Font ABC',font='Arial'))
        with patch('fonts.font_file',return_value=font):self.s.export(self.root/'out.pdf')
        with pdf.open(self.root/'out.pdf') as out:
            self.assertIn('Custom Font ABC',out[0].get_text())
            self.assertTrue(any('DejaVu' in str(f) for f in out[0].get_fonts()))
            self.assertLess((self.root/'out.pdf').stat().st_size,200000)

    def test_reject_text_clipping_without_overwriting_export(self):
        self.s.add('text',0,**self.text(rect=[40,50,70,70],text='TOO MUCH TEXT '*20,size=16))
        target=self.root/'out.pdf';target.write_bytes(b'prior output')
        with self.assertRaises(ValueError):self.s.export(target)
        self.assertEqual(target.read_bytes(),b'prior output')

    def test_save_original_conflict_leaves_source_and_history(self):
        self.s.add('underline',0,scope='original',quads=self.quads('HIGHLIGHT'))
        with self.path.open('ab') as f:f.write(b'\n% external')
        current=sha256(self.path)
        with self.assertRaises(ValueError):self.s.save_original()
        self.assertEqual(sha256(self.path),current);self.assertTrue(self.s.original_dirty)

    def test_committed_original_log_retained_without_reapplying(self):
        self.s.add('underline',0,scope='original',quads=self.quads('HIGHLIGHT'))
        self.s.save_original()
        self.s.save_project(self.root/'a.pdfwork',{})
        other=Session(self.path)
        try:
            data=read_project(self.root/'a.pdfwork')
            self.assertEqual(len(data['committed_original']),1)
            other.restore(data)
            self.assertEqual(other.cursor,0)
            self.assertEqual(len(other.annotations(0)),2)
        finally:other.close()

    def test_source_save_drops_dangling_work_redo_references_safely(self):
        self.s.add('underline',0,scope='original',quads=self.quads('Underline'))
        first=self.s.add('highlight',0,scope='original',quads=self.quads('HIGHLIGHT'))
        self.s.add('delete',0,target=first['id'])
        self.s.undo();self.s.undo()
        self.s.save_original()
        self.assertEqual(self.s.history,[])
        self.s.save_project(self.root/'a.pdfwork',{})
        other=Session(self.path)
        try:other.restore(read_project(self.root/'a.pdfwork'))
        finally:other.close()

    def test_repeated_original_saves_keep_work_base_refs_stable(self):
        old=self.s.annotations(0)[0]
        self.s.add('delete',0,target=old['id'])
        for kind in ('highlight','underline','strike'):
            self.s.add(kind,0,scope='original',quads=self.quads('HIGHLIGHT'))
            self.s.save_original()
        self.assertEqual(len(self.s.annotations(0,False)),4)
        self.assertEqual(len(self.s.annotations(0,True)),3)
        self.assertEqual(len(self.s.committed_original),3)
        self.assertEqual(len(list(self.root.glob('*.bak'))),1)

    def test_source_save_keeps_encryption(self):
        target=self.root/'encrypted.pdf'
        with pdf.open(self.path) as doc:
            doc.save(target,encryption=pdf.PDF_ENCRYPT_AES_256,owner_pw='owner',user_pw='user')
        encrypted=Session(target,'owner')
        try:
            encrypted.add('highlight',0,scope='original',quads=self.quads('HIGHLIGHT'))
            encrypted.save_original()
            with pdf.open(target) as doc:
                self.assertTrue(doc.needs_pass)
                self.assertTrue(doc.authenticate('user'))
                page=doc[0]
                self.assertEqual(len(list(page.annots())),2)
        finally:encrypted.close()


if __name__=='__main__':unittest.main()
