"""myworld. Compact scoped history, fast overlays and safe PDF persistence.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations
from collections import OrderedDict
from pathlib import Path
import hashlib
import json
import math
import os
import shutil
import tempfile
import uuid
import zlib
import io
import zipfile
import re
import base64
import pymupdf as pdf
from brand import APP_NAME, VERSION
from fonts import FONT_FILES, insert_text

MARKUPS = {'highlight', 'underline', 'strike', 'ink', 'text'}
LABELS = {'highlight':'高亮', 'underline':'下划线', 'strike':'删除线', 'ink':'画笔',
          'text':'添加文本', 'erase':'擦除', 'delete':'删除批注','update':'修改批注'}
PROJECT_MAGIC = b'STUDYPDF5\n'
V4_MAGIC = b'STUDYPDF4\n'
V3_MAGIC = b'STUDYPDF3\n'


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for part in iter(lambda: stream.read(1024*1024), b''):
            h.update(part)
    return h.hexdigest()


def atomic_write(path, data):
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix='.studypdf-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def read_project(path):
    raw = Path(path).read_bytes()
    if len(raw)>64_000_000: raise ValueError('工作记录文件过大。')
    assets={}
    if raw.startswith((PROJECT_MAGIC,V4_MAGIC)):
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries=archive.infolist()
            if len(entries)>402 or len({e.filename for e in entries})!=len(entries): raise ValueError('笔记附件目录无效。')
            if sum(e.file_size for e in entries)>56_000_000: raise ValueError('笔记内容解压后过大。')
            info=archive.getinfo('project.json')
            if info.file_size>40_000_000: raise ValueError('工作记录内容过大。')
            data=json.loads(archive.read(info).decode('utf-8'))
            for entry in entries:
                if entry.filename=='project.json':continue
                if not re.fullmatch(r'images/[0-9a-f]{64}\.png',entry.filename) or entry.file_size>8_000_000: raise ValueError('笔记图片无效。')
                blob=archive.read(entry)
                if not blob.startswith(b'\x89PNG\r\n\x1a\n') or hashlib.sha256(blob).hexdigest()!=Path(entry.filename).stem: raise ValueError('笔记图片校验失败。')
                assets[Path(entry.filename).stem]=blob
            if sum(map(len,assets.values()))>16_000_000:raise ValueError('笔记图片总量超过 16 MB。')
            data['_note_assets']=assets
            return data
    if raw.startswith(V3_MAGIC):
        dec = zlib.decompressobj()
        raw = dec.decompress(raw[len(V3_MAGIC):], 40_000_001)
        if len(raw)>40_000_000 or not dec.eof or dec.unused_data: raise ValueError('工作记录解压长度超限或格式损坏。')
    if len(raw)>40_000_000:raise ValueError('工作记录内容过大。')
    return json.loads(raw.decode('utf-8'))


def display_matrix(page, rotation):
    extra = pdf.Matrix(1, 1).prerotate(rotation)
    bounds = page.rect * extra
    return page.rotation_matrix * extra * pdf.Matrix(1,0,0,1,-bounds.x0,-bounds.y0)


def quad_list(quad): return [float(v) for point in quad for v in point]
def as_quad(values): return pdf.Quad([pdf.Point(values[i],values[i+1]) for i in range(0,8,2)])
def annotation_key(annot): return (annot.type[0],*(round(v,2) for v in annot.rect))


class Session:
    def __init__(self, path, password='', compute_digest=True):
        self.source = Path(path).resolve()
        self.doc = pdf.open(self.source)
        try:
            if not self.doc.is_pdf or not len(self.doc): raise ValueError('请选择包含页面的 PDF 文件。')
            auth = self.doc.authenticate(password) if self.doc.needs_pass else 0
            if self.doc.needs_pass and not auth: raise ValueError('PDF 密码不正确。')
            self.can_annotate = bool(auth & 4 or self.doc.permissions & pdf.PDF_PERM_ANNOTATE)
            self.can_modify = bool(auth & 4 or self.doc.permissions & pdf.PDF_PERM_MODIFY)
            self.can_copy = bool(auth & 4 or self.doc.permissions & pdf.PDF_PERM_COPY)
            self.password = password
            self.digest = sha256(self.source) if compute_digest else ''
            self.history, self.cursor, self.generation = [], 0, 0
            self.committed_original = []
            self.notes_html = ""
            self.notebooks = []
            self.active_note = None
            self.note_assets = {}
            self.notes_revision = 0
            self.saved = (0,0,0)
            self.project = None
            self.revision = 0
            self._text_cache, self._effective_cache = OrderedDict(), OrderedDict()
            self._page_history = {}
        except Exception:
            self.doc.close()
            raise

    def close(self):
        if not self.doc.is_closed: self.doc.close()
    def signature(self): return self.generation, self.cursor, self.notes_revision
    @property
    def dirty(self): return self.signature() != self.saved
    @property
    def original_dirty(self):
        return any(op['scope']=='original' for op in self.history[:self.cursor])

    def validate(self, op):
        if not isinstance(op,dict) or op.get('kind') not in MARKUPS|{'erase','delete','update'}:
            raise ValueError('无效的工作记录类型。')
        page, kind, scope = op.get('page'), op['kind'], op.get('scope','work')
        if type(page) is not int or not 0 <= page < len(self.doc): raise ValueError('工作记录页码越界。')
        if scope not in ('original','work'): raise ValueError('无效的操作栏。')
        if kind == 'erase' and (scope != 'work' or not self.can_modify): raise ValueError('此处不允许擦除页面内容。')
        if kind == 'text' and not self.can_modify: raise ValueError('此 PDF 未授予修改内容权限。')
        deleting_own_text = kind in ('delete','update') and self.can_modify and not str(op.get('target','base:')).startswith('base:')
        if kind not in ('erase','text') and not (self.can_annotate or deleting_own_text): raise ValueError('此 PDF 未授予批注权限。')
        out = {'id':str(op.get('id') or uuid.uuid4().hex), 'kind':kind,'page':page,'scope':scope}
        if not 1 <= len(out['id']) <= 100: raise ValueError('无效的操作标识。')
        if kind in ('delete','update'):
            target = op.get('target')
            if not isinstance(target,str) or not 1 <= len(target) <= 120: raise ValueError('无效的批注引用。')
            out['target'] = target
            if kind=='update':
                changes=op.get('changes')
                if not isinstance(changes,dict) or not changes or set(changes)-{'color','comment'}:raise ValueError('无效的批注修改。')
                out['changes']={}
                if 'color' in changes:
                    c=changes['color']
                    if not isinstance(c,(list,tuple)) or len(c)!=3 or any(not math.isfinite(float(v)) or not 0<=float(v)<=1 for v in c):raise ValueError('批注颜色无效。')
                    out['changes']['color']=[round(float(v),5) for v in c]
                if 'comment' in changes:
                    text=changes['comment']
                    if not isinstance(text,str) or len(text)>20000:raise ValueError('评论超过 20000 字或格式无效。')
                    out['changes']['comment']=text
            return out
        color = op.get('color',[1,.78,.12])
        if not isinstance(color,(list,tuple)) or len(color)!=3 or any(not math.isfinite(float(v)) or not 0<=float(v)<=1 for v in color): raise ValueError('颜色无效。')
        out['color'] = [round(float(v),5) for v in color]
        width = float(op.get('width',2))
        if not math.isfinite(width) or not .3<=width<=120: raise ValueError('笔宽无效。')
        out['width'] = round(width,3)
        comment=op.get('comment','')
        if not isinstance(comment,str) or len(comment)>20000:raise ValueError('评论格式或长度无效。')
        if comment:out['comment']=comment
        bounds = self.doc[page].rect*self.doc[page].derotation_matrix
        def numbers(row,length):
            if not isinstance(row,(list,tuple)) or len(row)!=length or any(not math.isfinite(float(v)) for v in row): raise ValueError('坐标无效。')
            return [round(float(v),3) for v in row]
        if kind == 'text':
            text = op.get('text')
            size = float(op.get('size',14))
            family = op.get('font','内置中文字体')
            if not isinstance(text,str) or not text.strip() or len(text)>20000: raise ValueError('文本为空或超过 20000 字。')
            if not math.isfinite(size) or not 4<=size<=144: raise ValueError('字号须为 4–144 pt。')
            if family not in FONT_FILES and family!='内置中文字体': raise ValueError('不支持的字体。')
            rect = pdf.Rect(numbers(op.get('rect'),4)).normalize() & bounds
            if rect.width < size or rect.height < size: raise ValueError('文本框过小，请重新框选。')
            out.update(text=text, size=size, font=family, rect=list(rect))
            if op.get('replaces'):
                if not isinstance(op['replaces'],str) or len(op['replaces'])>120: raise ValueError('文本引用无效。')
                out['replaces'] = op['replaces']
        elif kind == 'erase':
            rows = op.get('rects',[])
            if not 1<=len(rows)<=20000: raise ValueError('单笔擦除记录过大或为空。')
            out['rects'] = []
            for row in rows:
                rect = pdf.Rect(numbers(row,4)).normalize() & bounds
                if rect.width>=.1 and rect.height>=.1:
                    values = [round(v,3) for v in rect]
                    if not out['rects'] or values != out['rects'][-1]: out['rects'].append(values)
            if not out['rects']: raise ValueError('擦除区域位于页面之外。')
        elif kind == 'ink':
            rows = op.get('points',[])
            if not 2<=len(rows)<=20000: raise ValueError('画笔记录过大或过短。')
            out['points'] = []
            for row in rows:
                x,y = numbers(row,2)
                out['points'].append([max(bounds.x0,min(x,bounds.x1)),max(bounds.y0,min(y,bounds.y1))])
        else:
            rows = op.get('quads',[])
            if not 1<=len(rows)<=2000: raise ValueError('文字标注区域过大或为空。')
            out['quads'] = []
            for row in rows:
                values = numbers(row,8)
                q = as_quad(values)
                if not q.is_convex or q.rect.is_empty or not (bounds+(-2,-2,2,2)).contains(q.rect): raise ValueError('文字标注四边形无效。')
                out['quads'].append(values)
        return out

    def _changed(self):
        self.revision += 1
        self._effective_cache.clear()
        self._page_history = {}
        # Index operations once per edit, never once per render or mouse move.
        for index,op in enumerate(self.history[:self.cursor]):
            self._page_history.setdefault(op['page'],[]).append(op)

    def add(self, kind, page, **data):
        op = self.validate({'kind':kind,'page':page,**data})
        if self.cursor < len(self.history):
            self.generation += 1
        self.history[self.cursor:] = [op]
        self.cursor += 1
        self._changed()
        return op
    def undo(self):
        if not self.cursor: return None
        self.cursor -= 1
        self._changed()
        return self.history[self.cursor]['page']
    def redo(self):
        if self.cursor==len(self.history): return None
        page = self.history[self.cursor]['page']
        self.cursor += 1
        self._changed()
        return page

    def page_ops(self, page, edited=True):
        ops = self._page_history.get(page,[])
        return [op for op in ops if op['scope']=='original'] + ([op for op in ops if op['scope']=='work'] if edited else [])

    def effective(self, page, edited=True):
        key = page,edited
        if key not in self._effective_cache:
            adds, hidden, regions = {},set(),[]
            for op in self.page_ops(page,edited):
                kind = op['kind']
                if kind=='erase':
                    rs = [pdf.Rect(r) for r in op['rects']]
                    regions.extend(rs)
                    adds = {k:v for k,v in adds.items() if not any(op_bounds(v).intersects(r) for r in rs)}
                elif kind=='update':
                    if op['target'] in adds:adds[op['target']]={**adds[op['target']],**op['changes']}
                elif kind=='delete':
                    if op['target'].startswith('base:'): hidden.add(op['target'])
                    else: adds.pop(op['target'],None)
                else:
                    if op.get('replaces'): adds.pop(op['replaces'],None)
                    adds[op['id']] = op
            self._effective_cache[key] = adds,hidden,regions
            while len(self._effective_cache)>32: self._effective_cache.popitem(last=False)
        return self._effective_cache[key]

    def raster_ops(self, page, edited=True):
        # New marks/text are lightweight Qt overlays. Only source deletion/redaction changes the raster.
        return [op for op in self.page_ops(page,edited) if op['kind']=='erase' or (op['kind'] in ('delete','update') and op['target'].startswith('base:') and (op['kind']=='delete' or 'color' in op['changes']))]

    def base_updates(self,page,edited=True):
        changes={}
        for op in self.page_ops(page,edited):
            if op['kind']=='update' and op['target'].startswith('base:'):
                changes.setdefault(op['target'],{}).update(op['changes'])
        return changes

    def annotations(self, page, edited=True):
        adds,hidden,regions = self.effective(page,edited)
        result = []
        source_page = self.doc[page]
        updates=self.base_updates(page,edited)
        for annot in source_page.annots() or []:
            ident = f'base:{page}:{annot.xref}'
            if ident not in hidden and not any(annot.rect.intersects(r) for r in regions):
                name=annot.info.get('id','')
                vertices=annot.vertices or []
                quads=[quad_list(pdf.Quad(vertices[i:i+4])) for i in range(0,len(vertices),4)] if annot.type[0] in (8,9,11) else []
                result.append({'id':ident,'anchor_id':name[9:] if name.startswith('StudyPDF:') else ident,
                               'quads':quads,'page':page,'label':annot.type[1],'rect':list(annot.rect),
                               'kind':{8:'highlight',9:'underline',11:'strike',15:'ink',2:'text'}.get(annot.type[0],'annotation'),
                               'color':annotation_color(annot),'comment':annot.info.get('content',''),**updates.get(ident,{})})
        for op in adds.values():
            result.append({'id':op['id'],'anchor_id':op['id'],'quads':op.get('quads',[]),'page':page,'label':LABELS[op['kind']], 'rect':list(op_bounds(op)), 'kind':op['kind'],'color':op.get('color',[1,.78,.12]),'comment':op.get('comment','')})
        return result

    def _apply(self, page, number, cloned=False, edited=True, raster=False):
        adds, hidden, regions = self.effective(number,edited)
        updates=self.base_updates(number,edited)
        mapping = {}
        if cloned and (hidden or updates):
            groups = {}
            for annot in page.annots() or []: groups.setdefault(annotation_key(annot),[]).append(annot.xref)
            source_page = self.doc[number]
            for annot in source_page.annots() or []:
                matches = groups.get(annotation_key(annot),[])
                if matches: mapping[f'base:{number}:{annot.xref}'] = matches.pop(0)
        for ident in hidden:
            xref = mapping.get(ident) if cloned else int(ident.rsplit(':',1)[1])
            if xref is None: raise ValueError('原有批注无法安全对应，未执行删除。')
            annot = page.load_annot(xref)
            if annot: page.delete_annot(annot)
        if regions: redact(page,regions)
        remaining={a.xref for a in page.annots() or []}
        for ident,changes in updates.items():
            if ident in hidden:continue
            xref=mapping.get(ident) if cloned else int(ident.rsplit(':',1)[1])
            if xref in remaining:apply_annotation_changes(page.load_annot(xref),changes)
        if not raster:
            for op in adds.values(): add_annotation(page,op)

    def preview_page(self, number, edited=True, raster=False):
        scratch = pdf.open()
        try:
            scratch.insert_pdf(self.doc,from_page=number,to_page=number,annots=True,widgets=True)
            self._apply(scratch[0],number,cloned=True,edited=edited,raster=raster)
            return scratch
        except Exception:
            scratch.close()
            raise

    def render(self, number, scale, rotation, edited, raster=False):
        adds,hidden,regions = self.effective(number,edited)
        matrix = pdf.Matrix(scale,scale).prerotate(rotation)
        if not(hidden or regions or self.base_updates(number,edited) or (adds and not raster)):
            return self.doc[number].get_pixmap(matrix=matrix,alpha=False)
        with self.preview_page(number,edited,raster) as scratch:
            return scratch[0].get_pixmap(matrix=matrix,alpha=False)

    def text_index(self, number):
        if number not in self._text_cache:
            from text_selection import TextIndex
            self.cache_text(number,TextIndex(self.doc[number]))
        self._text_cache.move_to_end(number)
        return self._text_cache[number]
    def cache_text(self, number, index):
        self._text_cache[number] = index
        self._text_cache.move_to_end(number)
        while len(self._text_cache)>12: self._text_cache.popitem(last=False)

    def save_project(self, path, view):
        target = Path(path).resolve()
        if target==self.source or target.suffix.lower()!='.pdfwork': raise ValueError('请选择单独的 .pdfwork 工作记录文件。')
        try: source_ref = os.path.relpath(self.source,target.parent)
        except ValueError: source_ref = str(self.source)
        for note in self.notebooks:
            if note['id']==self.active_note:note['html']=self.notes_html
        all_html=[self.notes_html]+[note['html'] for note in self.notebooks]
        data = {'format':'studypdf-work','version':5,'source':source_ref,
                'source_sha256':self.digest,'pages':len(self.doc),'history':self.history,'cursor':self.cursor,'view':view,
                'committed_original':self.committed_original,'notes_html':self.notes_html,'notebooks':self.notebooks,'active_note':self.active_note}
        payload = json.dumps(data,ensure_ascii=False,separators=(',',':')).encode('utf-8')
        if len(payload)>40_000_000: raise ValueError('工作记录过大，请另建工作记录。')
        buffer=io.BytesIO();buffer.write(PROJECT_MAGIC)
        used=set(re.findall(r'studypdf-image:/([0-9a-f]{64})','\n'.join(all_html)))
        if not used.issubset(self.note_assets):raise ValueError('笔记中有丢失的图片，已停止保存，避免损坏记录。')
        with zipfile.ZipFile(buffer,'w') as archive:
            archive.writestr('project.json',payload,compress_type=zipfile.ZIP_DEFLATED,compresslevel=6)
            for key in sorted(used):archive.writestr('images/'+key+'.png',self.note_assets[key],compress_type=zipfile.ZIP_STORED)
        atomic_write(target,buffer.getvalue())
        self.project, self.saved = target,self.signature()

    def restore(self,data):
        if data.get('format')!='studypdf-work' or data.get('version') not in (2,3,4,5): raise ValueError('不支持的工作记录格式。')
        if data.get('source_sha256')!=self.digest or data.get('pages')!=len(self.doc): raise ValueError('原 PDF 内容与工作记录不匹配，已停止套用，避免位置错位。')
        ops,cursor = data.get('history'),data.get('cursor')
        if not isinstance(ops,list) or len(ops)>50000 or type(cursor) is not int or not 0<=cursor<=len(ops): raise ValueError('工作记录历史无效。')
        validated = [self.validate(op) for op in ops]
        if len({op['id'] for op in validated})!=len(validated): raise ValueError('工作记录操作标识重复。')
        seen = {}
        for op in validated:
            target = op.get('target') or op.get('replaces')
            if target:
                if target.startswith('base:'):
                    if target not in {x['id'] for x in self._source_annotations(op['page'])}: raise ValueError('找不到原有批注。')
                else:
                    ref = seen.get(target)
                    if not ref or ref['page']!=op['page'] or (op['scope']=='original' and ref['scope']!='original'): raise ValueError('找不到引用的批注或文本。')
            if op['kind'] in MARKUPS: seen[op['id']] = op
        committed = data.get('committed_original',[])
        if not isinstance(committed,list) or len(committed)>50000: raise ValueError('原稿编辑记录无效。')
        validated_committed = [self.validate(op) for op in committed]
        if any(op['scope']!='original' for op in validated_committed): raise ValueError('原稿记录作用域无效。')
        notes=data.get('notes_html','')
        books=data.get('notebooks',[])
        if not isinstance(books,list) or len(books)>100:raise ValueError('笔记数量无效。')
        validated_books=[]
        for book in books:
            if not isinstance(book,dict) or not isinstance(book.get('id'),str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',book['id']) or not isinstance(book.get('title'),str) or not book['title'].strip() or len(book['title'])>120 or not isinstance(book.get('html'),str):raise ValueError('命名笔记格式无效。')
            validated_books.append({k:book[k] for k in ('id','title','html')})
        if len({b['id'] for b in validated_books})!=len(validated_books):raise ValueError('笔记标识重复。')
        if not validated_books:validated_books=[{'id':'main','title':self.source.stem[:120],'html':notes}]
        active=data.get('active_note') or validated_books[0]['id']
        if active not in {b['id'] for b in validated_books}:raise ValueError('当前笔记不存在。')
        if sum(len(b['html'].encode('utf-8')) for b in validated_books)>2_000_000:raise ValueError('笔记正文总量超过 2 MB。')
        notes=next(b['html'] for b in validated_books if b['id']==active)
        assets=data.get('_note_assets',{})
        if not isinstance(notes,str) or len(notes.encode('utf-8'))>2_000_000 or not isinstance(assets,dict):raise ValueError('笔记格式或大小无效。')
        if len(assets)>400 or any(not isinstance(k,str) or not re.fullmatch('[0-9a-f]{64}',k) or not isinstance(v,bytes) or len(v)>8_000_000 or not v.startswith(b'\x89PNG\r\n\x1a\n') or hashlib.sha256(v).hexdigest()!=k for k,v in assets.items()):raise ValueError('笔记图片无效。')
        if sum(map(len,assets.values()))>16_000_000:raise ValueError('笔记图片总量过大。')
        used=set(re.findall(r'studypdf-image:/([0-9a-f]{64})','\n'.join(b['html'] for b in validated_books)))
        if not used.issubset(assets):raise ValueError('笔记图片缺失。')
        self.committed_original=validated_committed
        self.notebooks,self.active_note=validated_books,active
        self.notes_html,self.note_assets=notes,dict(assets)
        self.notes_revision=0
        self.history,self.cursor = validated,cursor
        self.generation += 1
        self._changed()
        self.saved = self.signature()

    def _source_annotations(self,page):
        source_page = self.doc[page]
        return [{'id':f'base:{page}:{a.xref}'} for a in source_page.annots() or []]

    def assert_source_unchanged(self):
        if sha256(self.source)!=self.digest: raise ValueError('原始 PDF 已被其他程序修改，已停止保存，避免覆盖。请先保存工作记录，再重新打开并核对。')

    def export(self,path,progress=None):
        target = Path(path).resolve()
        if target==self.source or (target.exists() and os.path.samefile(target,self.source)): raise ValueError('导出请选择新文件名；保存原稿请使用“保存原始 PDF”。')
        if target.suffix.lower()!='.pdf': raise ValueError('导出文件必须是 .pdf。')
        self.assert_source_unchanged()
        self._write_pdf(target,True,progress,redacted=True)

    def _write_pdf(self,target,edited,progress=None,redacted=False):
        output,tmp = pdf.open(self.source),None
        try:
            if output.needs_pass and not output.authenticate(self.password): raise ValueError('无法重新打开加密 PDF。')
            pages = sorted({op['page'] for op in self.history[:self.cursor] if edited or op['scope']=='original'})
            for i,number in enumerate(pages):
                self._apply(output[number],number,edited=edited)
                if progress: progress(i+1,len(pages))
            if redacted:
                output.scrub(attached_files=True,embedded_files=True,javascript=True,metadata=True,xml_metadata=True,
                             thumbnails=True,hidden_text=False,redactions=False,remove_links=False,reset_fields=False,
                             reset_responses=True,clean_pages=False)
                output.set_metadata({'producer':f'{APP_NAME} {VERSION} / PyMuPDF 1.26.6 (GNU AGPLv3)'})
            if any(op["kind"]=="text" and (edited or op["scope"]=="original") for op in self.history[:self.cursor]):
                output.subset_fonts()
            fd,tmp = tempfile.mkstemp(prefix='.studypdf-export-',suffix='.pdf',dir=target.parent)
            os.close(fd)
            # Source save uses garbage=0 so pending working base:xref references stay stable.
            output.save(tmp,garbage=4 if redacted else 0,deflate=True,
                        encryption=pdf.PDF_ENCRYPT_NONE if redacted else pdf.PDF_ENCRYPT_KEEP)
            with pdf.open(tmp) as check:
                if check.needs_pass: check.authenticate(self.password)
                if len(check)!=len(self.doc): raise ValueError('页数校验失败。')
            output.close()
            os.replace(tmp,target)
            tmp = None
        finally:
            if not output.is_closed: output.close()
            if tmp and os.path.exists(tmp): os.unlink(tmp)

    def save_original(self,progress=None):
        """Commit the original scope only; atomically rebase work without embedding a PDF in the project."""
        if not self.original_dirty: return None
        self.assert_source_unchanged()
        # A work operation referencing pending original text cannot survive flattening text into source content.
        all_original = {op['id']:op for op in self.history if op['scope']=='original' and op['kind'] in MARKUPS}
        active_original = {op['id']:op for op in self.history[:self.cursor] if op['scope']=='original' and op['kind'] in MARKUPS}
        for op in self.history:
            ref = op.get('target') or op.get('replaces')
            if op['scope']=='work' and ref in active_original and active_original[ref]['kind']=='text':
                raise ValueError('工作副本修改或删除了尚未写入原稿的新增文本。请先撤销该跨栏文本修改，再保存原稿。')
        fd, staged = tempfile.mkstemp(prefix='.studypdf-source-',suffix='.pdf',dir=self.source.parent)
        os.close(fd)
        staged = Path(staged)
        try:
            self._write_pdf(staged,False,progress)
            # Stable NM values allow pending work deletion references to be remapped before committing.
            mapping = {}
            valid_base = set()
            with pdf.open(staged) as check:
                if check.needs_pass: check.authenticate(self.password)
                for number in {op['page'] for op in self.history}:
                    page = check[number]
                    for a in page.annots() or []:
                        valid_base.add(f'base:{number}:{a.xref}')
                        name = a.info.get('id','')
                        if name.startswith('StudyPDF:'): mapping[name[9:]] = f'base:{number}:{a.xref}'
            work = []
            cursor = 0
            for index,op in enumerate(self.history):
                if op['scope']!='work': continue
                item = dict(op)
                ref = item.get('target')
                if ref and ref.startswith('base:') and ref not in valid_base: continue
                if ref in all_original:
                    if ref not in mapping: continue  # Original annotation was itself removed before save.
                    item['target'] = mapping[ref]
                work.append(item)
                if index<self.cursor: cursor += 1
            # Write one rolling backup; never grow a directory of backup copies.
            backup = self.source.with_name(self.source.name+'.studypdf.bak')
            backup_fd, backup_tmp = tempfile.mkstemp(prefix='.studypdf-backup-',dir=self.source.parent)
            os.close(backup_fd)
            try:
                shutil.copyfile(self.source,backup_tmp)
                os.replace(backup_tmp,backup)
            finally:
                if os.path.exists(backup_tmp): os.unlink(backup_tmp)
            self.assert_source_unchanged()
            self.doc.close()  # Windows requires releasing the source handle before replacing it.
            try:
                os.replace(staged,self.source)
            finally:
                self.doc = pdf.open(self.source)
                if self.doc.needs_pass: self.doc.authenticate(self.password)
            self.digest = sha256(self.source)
            self.committed_original.extend(op for op in self.history[:self.cursor] if op['scope']=='original')
            self.history,self.cursor = work,min(cursor,len(work))
            self.generation += 1
            self._text_cache.clear()
            self._changed()
            return backup
        finally:
            if staged.exists(): staged.unlink()


def op_bounds(op):
    if op['kind']=='text': return pdf.Rect(op['rect'])
    if op['kind']=='ink':
        points,margin = op['points'],op.get('width',2)*2
        return pdf.Rect(min(p[0] for p in points)-margin,min(p[1] for p in points)-margin,
                        max(p[0] for p in points)+margin,max(p[1] for p in points)+margin)
    rect = pdf.Rect()
    for values in op['quads']: rect |= as_quad(values).rect
    return rect


def add_annotation(page,op):
    kind = op['kind']
    if kind=='text':
        insert_text(page,op)
        return None
    if kind=='ink':
        annot = page.add_ink_annot([op['points']])
        annot.set_border(width=op.get('width',2))
    else:
        method = {'highlight':page.add_highlight_annot,'underline':page.add_underline_annot,'strike':page.add_strikeout_annot}[kind]
        annot = method([as_quad(q) for q in op['quads']])
    annot.set_colors(stroke=op['color'])
    annot.set_opacity(.38 if kind=='highlight' else 1)
    if kind=='highlight': annot.set_blendmode('Multiply')
    annot.set_info(title=APP_NAME,subject=LABELS[kind],content=op.get('comment',''))
    page.parent.xref_set_key(annot.xref,'NM',pdf.get_pdf_str('StudyPDF:'+op['id']))
    annot.update()
    return annot


def annotation_color(annot):
    color=annot.colors.get('stroke') or [1,.78,.12]
    if len(color)==1:return [color[0]]*3
    if len(color)==4:return [1-min(1,c+color[3]) for c in color[:3]]
    return list(color[:3])


def apply_annotation_changes(annot,changes):
    if 'color' in changes:
        if annot.type[0]==pdf.PDF_ANNOT_FREE_TEXT:annot.update(text_color=changes['color'])
        else:annot.set_colors(stroke=changes['color'])
    if 'comment' in changes:annot.set_info(content=changes['comment'])
    if annot.type[0]==pdf.PDF_ANNOT_HIGHLIGHT:annot.set_blendmode('Multiply')
    annot.update()


def redact(page,regions):
    for link in page.get_links():
        if any(pdf.Rect(link['from']).intersects(r) for r in regions): page.delete_link(link)
    for widget in list(page.widgets() or []):
        if any(widget.rect.intersects(r) for r in regions): page.delete_widget(widget)
    for annot in list(page.annots() or []):
        if annot.type[0]==pdf.PDF_ANNOT_REDACT or any(annot.rect.intersects(r) for r in regions): page.delete_annot(annot)
    for rect in regions: page.add_redact_annot(rect,fill=(1,1,1),cross_out=False)
    page.apply_redactions(images=2,graphics=2,text=0)
