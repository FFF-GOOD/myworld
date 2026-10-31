"""One isolated MuPDF process. JSON header + raw RGB bytes, one in-flight request.
No Qt dependency, no shared document across threads. SPDX-License-Identifier: AGPL-3.0-only
"""
import json
import sys
import time
from collections import OrderedDict
from core import Session
import pymupdf as pdf
pdf.TOOLS.mupdf_display_errors(False)
pdf.TOOLS.mupdf_display_warnings(False)
from text_selection import index_to_wire


def run():
    incoming, outgoing = sys.stdin.buffer, sys.stdout.buffer
    session = None
    rasters = OrderedDict()
    for line in incoming:
        request = json.loads(line)
        answer = {'id':request['id'], 'bytes':0}
        payload = b''
        try:
            if request['type']=='open':
                if session: session.close()
                session = Session(request['path'],request.get('password',''),compute_digest=False)
                rasters.clear()
            elif request['type']=='render':
                number = request['page']
                session.history = request['ops']
                session.cursor = len(session.history)
                session._changed()
                key = (number,request['scale'],request['rotation'],json.dumps(request['ops'],sort_keys=True))
                started = time.perf_counter()
                if key not in rasters:
                    pix = session.render(number,request['scale'],request['rotation'],True,raster=True)
                    rasters[key] = (pix.width,pix.height,pix.stride,pix.samples)
                rasters.move_to_end(key)
                width,height,stride,payload = rasters[key]
                while len(rasters)>8 or (sum(len(r[3]) for r in rasters.values())>64_000_000 and len(rasters)>1):
                    rasters.popitem(last=False)
                answer.update(width=width,height=height,stride=stride,bytes=len(payload),ms=round((time.perf_counter()-started)*1000,2))
                if request.get('text',False): answer['text'] = index_to_wire(session.text_index(number))
        except Exception as exc:
            answer['error'] = str(exc)
        outgoing.write(json.dumps(answer,ensure_ascii=False,separators=(',',':')).encode()+b'\n')
        if payload: outgoing.write(payload)
        outgoing.flush()
    if session: session.close()


if __name__=='__main__':
    run()
