"""Reproducible Windows x64 bundle builder; no Windows execution is implied.

Run from any OS with Python 3.12, pip and pefile installed. Downloaded wheels
are verified against their RECORD entries. Only required Qt binaries ship.
SPDX-License-Identifier: AGPL-3.0-only
"""
from pathlib import Path
import argparse
import base64
import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
import pefile
from brand import APP_NAME, VERSION


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", default=".build-cache/win_wheels")
    parser.add_argument("--python-zip", default=".build-cache/python-3.12.10-embed-amd64.zip")
    parser.add_argument("--output", default="dist")
    args = parser.parse_args()
    source = Path(__file__).resolve().parent
    cache, python_zip, out = (Path(v).resolve() for v in (args.cache,args.python_zip,args.output))
    cache.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    if len(list(cache.glob("*.whl"))) < 3:
        subprocess.check_call([sys.executable,"-m","pip","download","--dest",str(cache),
            "--only-binary=:all:","--platform","win_amd64","--python-version","312",
            "--implementation","cp","--abi","cp312","-r",str(source/"requirements.txt")])
    if not python_zip.is_file():
        urllib.request.urlretrieve("https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip",python_zip)
    root = out/APP_NAME
    if root.exists():
        shutil.rmtree(root)
    root.mkdir()
    for item in source.rglob("*"):
        relative = item.relative_to(source)
        allowed = ((len(relative.parts)==1 and (item.name in {'LICENSE','NOTICE','demo.pdf'} or item.suffix in {'.py','.md','.txt','.bat'}))
                   or (len(relative.parts)>1 and relative.parts[0] in {'tests','docs','assets'}))
        if not allowed or not item.is_file() or any(x in {"__pycache__",".venv",".git","user_data"} for x in relative.parts):
            continue
        target = root/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        data=item.read_bytes()
        if item.suffix == ".bat":
            data=data.replace(b"\r\n",b"\n").replace(b"\n",b"\r\n")
        target.write_bytes(data)
    runtime=root/"runtime"
    runtime.mkdir()
    with zipfile.ZipFile(python_zip) as z:
        assert z.testzip() is None
        z.extractall(runtime)
    site=runtime/"Lib/site-packages"
    site.mkdir(parents=True)
    archives=[]
    for wheel in sorted(cache.glob("*.whl")):
        if not wheel.name.lower().startswith(("pyside6_essentials-6.8.3-","pymupdf-1.26.6-","shiboken6-6.8.3-")):
            continue
        with zipfile.ZipFile(wheel) as z:
            record=next(n for n in z.namelist() if n.endswith(".dist-info/RECORD"))
            for name,encoded,size in csv.reader(io.StringIO(z.read(record).decode())):
                if not encoded: continue
                normalized="/".join(p for p in name.replace("\\","/").split("/") if p)
                algorithm,expected=encoded.split("=",1)
                actual=base64.urlsafe_b64encode(hashlib.new(algorithm,z.read(normalized)).digest()).rstrip(b"=").decode()
                if actual != expected:raise ValueError("Wheel integrity failed: "+name)
            z.extractall(site)
        archives.append({"archive":wheel.name,"sha256":hashlib.sha256(wheel.read_bytes()).hexdigest()})
    if len(archives)!=3:raise ValueError("Expected all three pinned Windows wheels")
    pyside=site/"PySide6"
    all_dlls={p.name.lower():p for p in runtime.rglob("*.dll")}
    roots=[pyside/(name+".pyd") for name in ("QtCore","QtGui","QtWidgets","QtTest")]
    roots.append(pyside/"plugins/platforms/qwindows.dll")
    roots.append(pyside/"plugins/platforms/qoffscreen.dll")
    roots.append(pyside/"plugins/imageformats/qjpeg.dll")
    # Include all Python and PDF extension modules, plus the Shiboken runtime.
    roots += list(runtime.glob("*.pyd"))+list(runtime.glob("*.exe"))
    roots += list((site/"pymupdf").rglob("*.pyd"))+list((site/"pymupdf").rglob("*.dll"))
    roots += list((site/"shiboken6").glob("*.pyd"))+list((site/"shiboken6").glob("*.dll"))
    keep, pending, external = set(),list(roots),set()
    while pending:
        item=pending.pop()
        if item in keep:continue
        if not item.is_file():raise FileNotFoundError(item)
        keep.add(item)
        pe=pefile.PE(str(item),fast_load=True)
        if pe.FILE_HEADER.Machine != 0x8664:raise ValueError("Non-x64 binary: "+str(item))
        pe.parse_data_directories(directories=[1,13])
        for attr in ("DIRECTORY_ENTRY_IMPORT","DIRECTORY_ENTRY_DELAY_IMPORT"):
            for entry in getattr(pe,attr,[]):
                name=entry.dll.decode().lower()
                if name in all_dlls:pending.append(all_dlls[name])
                else:external.add(name)
        pe.close()
    # Keep the Qt Python support code and all third-party license records unchanged.
    for path in list(pyside.rglob("*")):
        if not path.is_file():continue
        lower=path.name.lower()
        if path.suffix.lower() in {".dll",".pyd",".exe"} and path not in keep:
            path.unlink()
        elif any(part in {"qml","glue","include","typesystems","doc"} for part in path.relative_to(pyside).parts):
            path.unlink()
        elif path.suffix.lower() in {".pyi",".lib",".prl"}:
            path.unlink()
        elif path.suffix==".qm" and path.name!="qtbase_zh_CN.qm":
            path.unlink()
    # C++ runtime must be discoverable before PyMuPDF is imported.
    for dll in (site/"shiboken6").glob("msvcp140*.dll"):
        shutil.copy2(dll,runtime/dll.name)
    (runtime/"python312._pth").write_text("python312.zip\n.\nLib/site-packages\n..\nimport site\n",encoding="utf-8")
    # System imports must not hide missing Qt / binding / PDF dependencies.
    suspicious=[name for name in external if name.startswith(("qt6","pyside","shiboken","libmupdf","mupdf"))]
    if suspicious:raise ValueError("Missing application DLLs: "+repr(suspicious))
    manifest={"application":f"{APP_NAME} {VERSION}","platform":"Windows 10/11 x64",
        "archives":archives,"python_zip_sha256":hashlib.sha256(python_zip.read_bytes()).hexdigest(),
        "selected_binary_count":len(keep),"system_imports":sorted(external),
        "validation":"Wheel hashes, x64 headers, and native dependency closure checked; Windows execution NOT performed.",
        "source":"Complete application Python sources are included at bundle root.",
        "dependency_sources":{
            "PyMuPDF":"https://github.com/pymupdf/PyMuPDF/tree/1.26.6",
            "Qt for Python":"https://code.qt.io/cgit/pyside/pyside-setup.git/?h=v6.8.3",
            "Qt":"https://code.qt.io/cgit/qt/qtbase.git/?h=v6.8.3",
            "Python":"https://github.com/python/cpython/tree/v3.12.10"}}
    (root/"BUNDLE_MANIFEST.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    target=out/f"{APP_NAME}_{VERSION}_Windows_x64.zip"
    with zipfile.ZipFile(target,"w",zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for path in sorted(root.rglob("*")):
            if path.is_file() and not any(part.startswith(".") for part in path.relative_to(root).parts):
                z.write(path,Path(APP_NAME)/path.relative_to(root))
    with zipfile.ZipFile(target) as z:
        assert z.testzip() is None
    print(json.dumps({"file":str(target),"bytes":target.stat().st_size,"selected_binaries":len(keep),
                      "sha256":hashlib.sha256(target.read_bytes()).hexdigest()},indent=2))


if __name__=="__main__":main()
