"""Windows portable launcher and local exception logging."""
from pathlib import Path
import sys
import tempfile
import traceback


def report_error(kind, error, trace):
    text = "".join(traceback.format_exception(kind, error, trace))
    path = Path(__file__).with_name("myworld_error.log")
    try:
        path.write_text(text, encoding="utf-8")
    except OSError:
        path = Path(tempfile.gettempdir())/"myworld_error.log"
        path.write_text(text, encoding="utf-8")
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, f"操作出现错误，详情已保存到：\n{path}\n\n请把日志内容发回以便排查。", "myworld", 0x10)
    elif sys.stderr:
        print(text, file=sys.stderr)


sys.excepthook = report_error
try:
    from app import main
    main()
except Exception:
    report_error(*sys.exc_info())
    sys.exit(1)
