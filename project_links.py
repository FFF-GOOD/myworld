"""Exact-file associations; no folder scans or heuristic application to changed PDFs."""
from pathlib import Path
import json,os
from core import atomic_write,read_project


def config_path():
    # Historical folder and override preserve existing PDF/project associations.
    root=Path(os.environ.get('STUDYPDF_CONFIG_DIR') or os.environ.get('LOCALAPPDATA') or Path(__file__).parent/'user_data')
    return root/'StudyPDF'/'associations.json'


def read_links():
    try:
        path=config_path()
        if path.stat().st_size>2_000_000:return {}
        data=json.loads(path.read_text('utf-8'))
        return data if isinstance(data,dict) else {}
    except (OSError,ValueError):return {}


def remember(source,project):
    links=read_links();key=str(Path(source).resolve())
    links.pop(key,None);links[key]=str(Path(project).resolve())
    if len(links)>2000:links=dict(list(links.items())[-2000:])
    path=config_path();path.parent.mkdir(parents=True,exist_ok=True)
    atomic_write(path,json.dumps(links,ensure_ascii=False).encode())


def candidates(source):
    source=Path(source).resolve();paths=[]
    mapped=read_links().get(str(source))
    if isinstance(mapped,str):paths.append(Path(mapped))
    paths.extend([source.with_suffix('.pdfwork'),source.with_name(source.name+'.pdfwork')])
    seen=set()
    for path in paths:
        try:
            path=path.resolve()
            if path not in seen and path.is_file():yield path
            seen.add(path)
        except OSError:continue


def discover(session):
    problems=[]
    for path in candidates(session.source):
        try:
            data=read_project(path)
            if data.get('source_sha256')!=session.digest or data.get('pages')!=len(session.doc):
                problems.append(f'{path.name} 与当前 PDF 不匹配，未加载')
                continue
            # Full operation validation occurs before the session is displayed.
            session.restore(data)
            session.project=path
            return path,data,problems
        except Exception as exc:problems.append(f'{path.name} 未加载：{exc}')
    return None,None,problems
