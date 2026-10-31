from pathlib import Path
import json
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pymupdf as pdf
from core import Session, as_quad, quad_list, display_matrix, sha256, read_project
from text_selection import TextIndex


def make_pdf(path, count=3):
    doc = pdf.open()
    for i in range(count):
        page = doc.new_page(width=600, height=800)
        page.insert_text((50, 80), "HIGHLIGHT THIS LINE", fontsize=18)
        page.insert_text((50, 130), "Underline this sentence.", fontsize=18)
        page.insert_text((50, 180), "Keep this sentence.", fontsize=18)
        page.draw_rect(pdf.Rect(60, 270, 160, 330), color=(0, 0, 1), fill=(0, 0, 1))
        pix = pdf.Pixmap(pdf.csRGB, pdf.IRect(0, 0, 100, 100), False)
        pix.clear_with(20)
        page.insert_image(pdf.Rect(300, 250, 400, 350), pixmap=pix)
    page = doc[0]
    page.add_underline_annot(page.search_for("Keep this sentence.", quads=True))
    doc[1].set_cropbox(pdf.Rect(20, 25, 575, 770))
    doc[1].set_rotation(90)
    doc.set_toc([[1, "Chapter one", 1], [1, "Chapter two", 2]])
    doc.embfile_add("private.txt", b"attachment secret")
    doc.set_metadata({"title": "private metadata"})
    doc.save(path)
    doc.close()


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root/"source.pdf"
        make_pdf(self.source)
        self.session = Session(self.source)

    def tearDown(self):
        self.session.close()
        self.tmp.cleanup()

    def quads(self, text, page=0):
        return [quad_list(q) for q in self.session.doc[page].search_for(text, quads=True)]

    def test_standard_markups_and_ink_survive_export(self):
        digest = sha256(self.source)
        for kind, text in [("highlight", "HIGHLIGHT"), ("underline", "Underline"), ("strike", "sentence.")]:
            self.session.add(kind, 0, quads=self.quads(text), color=(.2, .5, .8))
        self.session.add("ink", 0, points=[[50, 220], [80, 230], [120, 215]], width=2, color=(.8,.2,.1))
        target = self.root/"annotated.pdf"
        self.session.export(target)
        with pdf.open(target) as doc:
            page = doc[0]
            types = [a.type[0] for a in page.annots()]
            self.assertEqual(types.count(pdf.PDF_ANNOT_HIGHLIGHT), 1)
            self.assertGreaterEqual(types.count(pdf.PDF_ANNOT_UNDERLINE), 2)
            self.assertEqual(types.count(pdf.PDF_ANNOT_STRIKE_OUT), 1)
            self.assertEqual(types.count(pdf.PDF_ANNOT_INK), 1)
            self.assertIn("HIGHLIGHT", page.get_text())
            self.assertIn("AGPL", doc.metadata["producer"])
            self.assertEqual(doc.embfile_count(), 0)
        self.assertEqual(digest, sha256(self.source))

    def test_existing_and_new_annotation_delete_undo(self):
        base = self.session.annotations(0)[0]
        self.session.add("delete", 0, target=base["id"])
        with self.session.preview_page(0) as doc:
            self.assertEqual(list(doc[0].annots() or []), [])
        self.session.undo()
        self.assertEqual(len(self.session.annotations(0)), 1)
        added = self.session.add("highlight", 0, quads=self.quads("HIGHLIGHT"))
        self.session.add("delete", 0, target=added["id"])
        self.assertEqual(len(self.session.annotations(0)), 1)
        self.session.undo()
        self.assertEqual(len(self.session.annotations(0)), 2)
        self.session.redo()
        self.assertEqual(len(self.session.annotations(0)), 1)

    def test_redaction_removes_text_image_pixels_vector_and_intersecting_markup(self):
        self.session.add("highlight", 0, quads=self.quads("HIGHLIGHT"))
        self.session.add("erase", 0, rects=[[40, 55, 280, 95], [80, 280, 90, 290], [320, 270, 350, 300]])
        target = self.root/"redacted.pdf"
        self.session.export(target)
        with pdf.open(target) as doc:
            page = doc[0]
            self.assertNotIn("HIGHLIGHT", page.get_text())
            self.assertIn("Underline", page.get_text())
            self.assertFalse(any(a.type[0] == pdf.PDF_ANNOT_HIGHLIGHT for a in page.annots() or []))
            self.assertFalse(any(d.get("fill") == (0.,0.,1.) for d in page.get_drawings()))
            pix = page.get_pixmap()
            self.assertEqual(pix.pixel(330, 280), (255,255,255))
            self.assertLess(pix.pixel(380, 320)[0], 100)
            self.assertIn("HIGHLIGHT", doc[1].get_text())
        self.assertIn("HIGHLIGHT", self.session.doc[0].get_text())

    def test_preview_matches_export_on_rotated_cropped_page(self):
        self.session.add("highlight", 1, quads=self.quads("Underline", 1))
        self.session.add("erase", 1, rects=[list(self.session.doc[1].search_for("HIGHLIGHT THIS LINE")[0])])
        self.session.export(self.root/"result.pdf")
        with pdf.open(self.root/"result.pdf") as output:
            for rotation in (0,90,180,270):
                pix = self.session.render(1, 1, rotation, True)
                expected = output[1].get_pixmap(matrix=pdf.Matrix(1,1).prerotate(rotation))
                self.assertEqual(pix.samples, expected.samples)
                matrix = display_matrix(self.session.doc[1], rotation)
                p = pdf.Point(50, 80)
                self.assertLess(abs(p - (p*matrix*~matrix)), .001)

    def test_character_selection_multi_line_and_hidden_text(self):
        index = TextIndex(self.session.doc[0])
        start = index.glyphs[0].box.tl+pdf.Point(2,2)
        # Select from first line into the second line using actual character centers.
        line_ids = list(dict.fromkeys(g.line for g in index.glyphs))
        second_line = [g for g in index.glyphs if g.line == line_ids[1]]
        end = (second_line[-1].box.tl+second_line[-1].box.br)/2
        quads, text = index.select(start, end)
        self.assertEqual(len(quads), 2)
        self.assertIn("HIGHLIGHT THIS LINE\nUnderline", text)
        self.assertTrue(all(as_quad(q).is_convex for q in quads))
        hidden = self.session.doc[0].search_for("HIGHLIGHT THIS LINE")
        _, redacted_text = index.select(start, end, hidden)
        self.assertNotIn("HIGHLIGHT", redacted_text)

    def test_oriented_text_quad(self):
        doc = pdf.open()
        try:
            page = doc.new_page()
            page.insert_text((150,300), "VERTICAL WORDS", rotate=90, fontsize=20)
            index = TextIndex(page)
            start = (index.glyphs[0].box.tl+index.glyphs[0].box.br)/2
            end = (index.glyphs[-1].box.tl+index.glyphs[-1].box.br)/2
            quads, text = index.select(start,end)
            self.assertIn("VERTICAL WORDS", text)
            self.assertTrue(as_quad(quads[0]).is_convex)
            page.add_highlight_annot([as_quad(q) for q in quads])
            self.assertEqual(len(list(page.annots())), 1)
        finally:
            doc.close()

    def test_project_restores_undo_redo_and_rejects_other_source(self):
        self.session.add("highlight", 0, quads=self.quads("HIGHLIGHT"))
        self.session.add("erase", 1, rects=[[30,30,70,70]])
        self.session.undo()
        project = self.root/"study.pdfwork"
        self.session.save_project(project, {"zoom":1.25,"rotation":90,"swapped":True})
        data = read_project(project)
        another = Session(self.source)
        try:
            another.restore(data)
            self.assertEqual(another.cursor, 1)
            self.assertEqual(another.redo(), 1)
            another.undo()
            another.add("underline", 0, quads=self.quads("Underline"))
            self.assertIsNone(another.redo())
            data["source_sha256"] = "changed"
            with self.assertRaises(ValueError): another.restore(data)
        finally: another.close()

    def test_invalid_coordinates_rejected_without_mutation(self):
        with self.assertRaises(ValueError):
            self.session.add("erase", 0, rects=[[float('nan'),0,5,5]])
        self.assertEqual(self.session.cursor, 0)
        with self.assertRaises(ValueError):
            self.session.add("highlight", 0, quads=[[0]*8])

    def test_source_overwrite_and_external_change_protection(self):
        with self.assertRaises(ValueError): self.session.export(self.source)
        target = self.root/"existing.pdf"
        target.write_bytes(b"existing output")
        with open(self.source,"ab") as stream: stream.write(b"\n% external change")
        with self.assertRaises(ValueError): self.session.export(target)
        self.assertEqual(target.read_bytes(), b"existing output")

    def test_encrypted_pdf_permissions(self):
        target = self.root/"encrypted.pdf"
        with pdf.open(self.source) as doc:
            doc.save(target,encryption=pdf.PDF_ENCRYPT_AES_256,owner_pw="owner",user_pw="user",permissions=pdf.PDF_PERM_PRINT)
        with self.assertRaises(ValueError): Session(target,"wrong")
        user = Session(target,"user")
        try:
            self.assertFalse(user.can_modify)
            with self.assertRaises(ValueError): user.add("erase",0,rects=[[40,50,100,90]])
        finally: user.close()
        owner = Session(target,"owner")
        try:
            self.assertTrue(owner.can_modify)
            owner.add("erase",0,rects=[[40,50,280,90]])
        finally: owner.close()


if __name__ == '__main__': unittest.main()
