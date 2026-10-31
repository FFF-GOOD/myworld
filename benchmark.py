"""Reproducible local benchmark; synthetic content, no user document needed."""
from pathlib import Path
import argparse,json,statistics,tempfile,time
import pymupdf as pdf
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from app import create_application,MainWindow
from core import quad_list


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='../qa/performance_03.json');args=parser.parse_args()
    app=create_application()
    with tempfile.TemporaryDirectory() as tmp:
        source=Path(tmp)/'long.pdf'
        doc=pdf.open()
        for i in range(800):
            page=doc.new_page(width=600,height=800)
            page.insert_text((40,65),f'Page {i+1} - HIGHLIGHT THIS TEXT',fontsize=15)
            if i==0:
                for line in range(45):page.insert_text((40,90+line*12),'Dense selectable text. '+str(line)+' Annotation responsiveness sample. '*2,fontsize=8)
                for n in range(1200):
                    x=40+n%50*10;y=660+n//50*4
                    page.draw_line((x,y),(x+9,y+3),color=(.4,.5,.6),width=.3)
        doc.set_toc([[1,'First chapter',1],[1,'Last chapter',797]])
        doc.save(source,deflate=True);doc.close()
        w=MainWindow();w.show()
        started=time.perf_counter();w.open_file(source);setup=time.perf_counter()-started
        w.set_zoom(1);w.goto(0)
        end=time.monotonic()+15
        while time.monotonic()<end and not all(0 in v.cache for v in w.views):QTest.qWait(10)
        if not all(0 in v.cache for v in w.views):raise RuntimeError('Renderer did not load synthetic document')
        ready=time.perf_counter()-started
        q=[quad_list(x) for x in w.session.doc[0].search_for('HIGHLIGHT THIS TEXT',quads=True)]
        before=w.renderer.metrics['requests'];latency=[]
        for n in range(120):
            start=time.perf_counter()
            w.commit(('highlight','underline','strike')[n%3],0,{'quads':q,'color':[.7,.2,.6]},w.original.view if n%4==0 else w.edited.view)
            app.processEvents()
            latency.append((time.perf_counter()-start)*1000)
        after=w.renderer.metrics['requests']
        project=Path(tmp)/'study.pdfwork';w.session.save_project(project,w.view_state())
        gaps=[];last=[time.perf_counter()]
        timer=QTimer()
        def beat():
            now=time.perf_counter();gaps.append((now-last[0])*1000);last[0]=now
        timer.timeout.connect(beat);timer.start(5)
        w.commit('erase',0,{'rects':[[80,660,130,740],[150,662,180,730]]},w.edited.view)
        QTest.qWait(1000);timer.stop()
        w.goto(796);end=time.monotonic()+15
        while time.monotonic()<end and not all(796 in v.cache for v in w.views):QTest.qWait(10)
        result={'platform':'Linux Qt offscreen; not a Windows measurement','pages':800,
                'setup_ms':round(setup*1000,2),'both_first_pages_ready_ms':round(ready*1000,2),
                'annotation_count':120,'includes_qt_events_and_painting':True,
                'annotation_median_ms':round(statistics.median(latency),2),
                'annotation_p95_ms':round(sorted(latency)[int(len(latency)*.95)-1],2),'annotation_max_ms':round(max(latency),2),
                'extra_raster_requests_for_120_markups':after-before,
                'pdfwork_120_operations_bytes':project.stat().st_size,
                'max_heartbeat_gap_during_background_redaction_ms':round(max(gaps),2),
                'heartbeat_count':len(gaps),'both_panes_page_797':[v.current_page()+1 for v in w.views],
                'cached_pages':[len(v.cache) for v in w.views], 'renderer':w.renderer.metrics}
        w.maybe_save=lambda:True;w.close()
        target=Path(args.output);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(result,indent=2))
        print(json.dumps(result,indent=2))


if __name__=='__main__':main()
