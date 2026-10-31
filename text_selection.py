"""Character-based selection and oriented text quads, without an OCR dependency."""
from dataclasses import dataclass
import pymupdf as pdf
from core import quad_list


@dataclass
class Glyph:
    char: str
    box: pdf.Rect
    quad: pdf.Quad
    line: tuple
    direction: tuple


class TextIndex:
    def __init__(self, page):
        self.glyphs = []
        flags = pdf.TEXTFLAGS_RAWDICT & ~pdf.TEXT_PRESERVE_IMAGES
        raw = page.get_text("rawdict", flags=flags)
        for bi, block in enumerate(raw["blocks"]):
            for li, line in enumerate(block.get("lines", [])):
                for span in line["spans"]:
                    for char in span["chars"]:
                        quad = pdf.recover_char_quad(line["dir"], span, char)
                        self.glyphs.append(Glyph(char["c"], pdf.Rect(char["bbox"]), quad, (bi, li), tuple(line["dir"])))

    def nearest(self, point):
        if not self.glyphs:
            return None
        def distance(g):
            return max(g.box.x0-point.x, 0, point.x-g.box.x1)**2 + max(g.box.y0-point.y, 0, point.y-g.box.y1)**2
        number = min(range(len(self.glyphs)), key=lambda i: distance(self.glyphs[i]))
        return number if distance(self.glyphs[number]) <= 32**2 else None

    def select(self, start, end, hidden=()):
        first, last = self.nearest(start), self.nearest(end)
        if first is None or last is None:
            return [], ""
        first, last = sorted((first, last))
        groups, current, line_id = [], [], None
        text = []
        for glyph in self.glyphs[first:last+1]:
            if any(glyph.box.intersects(region) for region in hidden):
                if current:
                    groups.append(current)
                    current = []
                continue
            if glyph.line != line_id:
                if current:
                    groups.append(current)
                    current = []
                if text:
                    text.append("\n")
                line_id = glyph.line
            current.append(glyph)
            text.append(glyph.char)
        if current:
            groups.append(current)
        return [quad_list(merge(group)) for group in groups], "".join(text)


def merge(glyphs):
    dx, dy = glyphs[0].direction
    nx, ny = -dy, dx
    points = [p for g in glyphs for p in g.quad]
    along = [p.x*dx+p.y*dy for p in points]
    across = [p.x*nx+p.y*ny for p in points]
    a, b, c, d = min(along), max(along), min(across), max(across)
    def point(u, v):
        return pdf.Point(u*dx+v*nx, u*dy+v*ny)
    return pdf.Quad(point(a,c), point(b,c), point(a,d), point(b,d))


def index_to_wire(index):
    return [[g.char, list(g.box), quad_list(g.quad), list(g.line), list(g.direction)] for g in index.glyphs]


def index_from_wire(rows):
    index = TextIndex.__new__(TextIndex)
    index.glyphs = [Glyph(r[0], pdf.Rect(r[1]), pdf.Quad([pdf.Point(r[2][i],r[2][i+1]) for i in range(0,8,2)]), tuple(r[3]), tuple(r[4])) for r in rows]
    return index
