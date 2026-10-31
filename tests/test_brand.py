"""Public naming and pre-rename persistence compatibility."""
import unittest,tempfile,os
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pymupdf as pdf
from brand import APP_NAME,VERSION
from app import create_application,MainWindow
from core import Session,quad_list,read_project
from project_links import config_path
from test_core import make_pdf

class BrandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=create_application()
    def test_public_name_and_window_title(self):
        w=MainWindow()
        try:
            self.assertEqual(self.app.applicationName(),'myworld')
            self.assertIn('myworld '+VERSION,w.windowTitle())
        finally:w.close()
    def test_pdf_metadata_and_annotation_author_use_new_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'original.pdf';make_pdf(p);s=Session(p)
            try:
                qs=[quad_list(q) for q in s.doc[0].search_for('HIGHLIGHT',quads=True)]
                s.add('highlight',0,quads=qs,comment='Test')
                target=Path(tmp)/'new.pdf';s.export(target)
                with pdf.open(target) as d:
                    self.assertIn('myworld '+VERSION,d.metadata['producer'])
                    page=d[0];a=list(page.annots())[-1]
                    self.assertEqual(a.info['title'],'myworld')
                    self.assertTrue(a.info['id'].startswith('StudyPDF:'))
            finally:s.close()
    def test_legacy_record_format_still_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'original.pdf';make_pdf(p);s=Session(p)
            try:
                qs=[quad_list(q) for q in s.doc[0].search_for('HIGHLIGHT',quads=True)]
                s.add('highlight',0,quads=qs)
                project=p.with_suffix('.pdfwork');s.save_project(project,{})
                self.assertTrue(project.read_bytes().startswith(b'STUDYPDF5\n'))
                data=read_project(project);self.assertEqual(data['format'],'studypdf-work')
                s.restore(data);self.assertEqual(s.cursor,1)
            finally:s.close()
    def test_legacy_registry_path_preserved(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'STUDYPDF_CONFIG_DIR':tmp}):
            self.assertEqual(config_path(),Path(tmp)/'StudyPDF'/'associations.json')
