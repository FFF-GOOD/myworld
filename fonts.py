"""Local font resolution. Font files stay out of .pdfwork and the app bundle."""
from pathlib import Path
import os
import html
import pymupdf as pdf

FONT_FILES = {
    '微软雅黑': ('msyh.ttc', 'msyh.ttf'), '黑体': ('simhei.ttf',),
    '宋体': ('simsun.ttc', 'simsun.ttf'), '仿宋': ('simfang.ttf',),
    '楷体': ('simkai.ttf',), 'Arial': ('arial.ttf',),
    'Times New Roman': ('times.ttf',), 'Courier New': ('cour.ttf',),
}
QT_FAMILIES = {'微软雅黑': 'Microsoft YaHei', '黑体': 'SimHei', '宋体': 'SimSun',
               '仿宋': 'FangSong', '楷体': 'KaiTi'}


def font_file(family):
    roots = [Path(os.environ.get('WINDIR', 'C:/Windows'))/'Fonts']
    local = os.environ.get('LOCALAPPDATA')
    if local:
        roots.append(Path(local)/'Microsoft/Windows/Fonts')
    for root in roots:
        for name in FONT_FILES.get(family, ()):
            path = root/name
            if path.is_file():
                return path
    return None


def insert_text(page, op):
    """Embed a subset of the selected local font; fail if the text cannot fit."""
    family = op['font']
    path = font_file(family)
    if family != '内置中文字体' and path is None:
        raise ValueError(f'本机找不到“{family}”字体。请编辑该文本并改用可用字体或“内置中文字体”。')
    color = '#' + ''.join(f'{round(c*255):02x}' for c in op['color'])
    css = f'* {{margin:0;padding:0;}} body {{font-size:{op["size"]}pt;line-height:1.25;color:{color};}}'
    archive = None
    if path:
        archive = pdf.Archive(str(path.parent))
        css += f'@font-face {{font-family:studyfont;src:url({path.name});}} body {{font-family:studyfont;}}'
    else:
        css += 'body {font-family:sans-serif;}'
    text = html.escape(op['text']).replace('\n', '<br>')
    spare, scale = page.insert_htmlbox(pdf.Rect(op['rect']), '<div>'+text+'</div>', css=css,
                                       archive=archive, scale_low=1)
    if spare < 0:
        raise ValueError('添加文本的文本框高度不足，未保存。请增大文本框、减少内容或调小字号。')
