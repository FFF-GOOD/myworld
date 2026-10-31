"""Nonblocking Qt transport for the isolated renderer, with bounded latest-request scheduling."""
from collections import OrderedDict
import json
from pathlib import Path
import sys
import time
from PySide6.QtCore import QObject,QProcess,QTimer,Signal
from PySide6.QtGui import QImage
from text_selection import index_from_wire


class RenderService(QObject):
    ready = Signal(object, int, object, object)
    failed = Signal(str)

    def __init__(self,parent=None):
        super().__init__(parent)
        self.process = None
        self.session = None
        self.queue = OrderedDict()
        self.inflight = None
        self.buffer = bytearray()
        self.header = None
        self.serial = 0
        self.last_progress = 0.
        self.metrics = {'requests':0,'completed':0,'obsolete':0,'max_queue':0}
        self.watchdog = QTimer(self)
        self.watchdog.setInterval(1000)
        self.watchdog.timeout.connect(self.check_timeout)

    def open(self,session):
        self.stop()
        self.session = session
        if not session: return
        process = QProcess(self)
        self.process = process
        executable = Path(sys.executable)
        # Embedded Windows pythonw does not expose useful inherited stdio; use python.exe in the child.
        if executable.name.lower()=='pythonw.exe': executable = executable.with_name('python.exe')
        process.setProgram(str(executable))
        process.setArguments(['-u',str(Path(__file__).with_name('render_worker.py'))])
        process.setWorkingDirectory(str(Path(__file__).parent))
        process.readyReadStandardOutput.connect(self.receive)
        process.readyReadStandardError.connect(lambda: process.readAllStandardError())
        process.errorOccurred.connect(lambda error: self.on_error(process.errorString()))
        process.finished.connect(lambda code,status: self.on_finished(process,code))
        process.started.connect(self.send_next)
        self.serial += 1
        self.queue['open'] = {'type':'open','id':self.serial,'path':str(session.source),'password':session.password}
        self.last_progress = time.monotonic()
        self.watchdog.start()
        process.start()

    def request(self,view,number,key,scale,rotation,ops):
        slot = (view,number)
        if self.inflight and self.inflight.get('slot')==slot and self.inflight.get('key')==key: return
        if slot in self.queue and self.queue[slot].get('key')==key: return
        self.serial += 1
        self.queue[slot] = {'type':'render','id':self.serial,'page':number,'scale':scale,'rotation':rotation,
                            'ops':ops,'text':number not in self.session._text_cache,'slot':slot,'key':key,'view':view}
        while len(self.queue)>10:
            self.queue.popitem(last=False)
        self.metrics['max_queue'] = max(self.metrics['max_queue'],len(self.queue))
        self.send_next()

    def retain(self,view,visible):
        for slot,job in list(self.queue.items()):
            if job.get('view') is view and job['page'] not in visible: del self.queue[slot]

    def send_next(self):
        if self.inflight or not self.queue or not self.process or self.process.state()!=QProcess.Running: return
        _,self.inflight = self.queue.popitem(last=False)
        wire = {k:v for k,v in self.inflight.items() if k not in ('slot','key','view')}
        if wire['type']=='render': wire['text'] = wire['page'] not in self.session._text_cache
        self.process.write(json.dumps(wire,ensure_ascii=False,separators=(',',':')).encode()+b'\n')
        self.last_progress = time.monotonic()
        self.metrics['requests'] += 1

    def receive(self):
        if not self.process: return
        self.buffer.extend(bytes(self.process.readAllStandardOutput()))
        self.last_progress = time.monotonic()
        try:
            while True:
                if self.header is None:
                    at = self.buffer.find(b'\n')
                    if at<0: return
                    if at>16_000_000: raise ValueError('渲染响应过大')
                    self.header = json.loads(self.buffer[:at])
                    del self.buffer[:at+1]
                length = self.header.get('bytes',0)
                if length<0 or length>32_000_000: raise ValueError('渲染图像过大')
                if len(self.buffer)<length: return
                raw = bytes(self.buffer[:length])
                del self.buffer[:length]
                header,self.header = self.header,None
                job,self.inflight = self.inflight,None
                if job is None or job['id']!=header['id']: raise ValueError('渲染响应顺序错误')
                if header.get('error'):
                    self.failed.emit(header['error'])
                elif job['type']=='render' and self.session:
                    if 'text' in header: self.session.cache_text(job['page'],index_from_wire(header['text']))
                    image = QImage(raw,header['width'],header['height'],header['stride'],QImage.Format_RGB888).copy()
                    self.metrics['completed'] += 1
                    self.ready.emit(job['view'],job['page'],job['key'],image)
                self.send_next()
                if not self.buffer: return
        except Exception as exc:
            self.on_error(str(exc))

    def check_timeout(self):
        if self.inflight and time.monotonic()-self.last_progress>45:
            self.on_error('此页渲染超过 45 秒，后台渲染已停止；工作记录仍保留。请重新打开 PDF 或保存记录。')

    def on_finished(self,process,code):
        if process is self.process: self.on_error(f'PDF 后台进程已退出（{code}）；请保存工作记录并重新打开。')

    def on_error(self,message):
        self.stop()
        self.failed.emit(message)

    def stop(self):
        self.watchdog.stop()
        process,self.process = self.process,None
        self.queue.clear()
        self.inflight,self.header = None,None
        self.buffer.clear()
        self.session = None
        if process:
            process.blockSignals(True)
            if process.state()!=QProcess.NotRunning:
                process.kill()
                process.waitForFinished(1000)
            process.deleteLater()
