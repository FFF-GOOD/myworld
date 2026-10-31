"""Create synthetic content for exercising selection, annotations and redaction."""
from pathlib import Path
import pymupdf as pdf


def main():
    doc = pdf.open()
    for number, title in enumerate(["阅读、标注与擦除", "同步、旋转与工作记录"]):
        page = doc.new_page(width=595, height=842)
        page.draw_rect(pdf.Rect(0,0,595,12),color=None,fill=(.14,.31,.59))
        page.insert_text((48,76), title, fontname="china-s", fontsize=24, color=(.12,.23,.41))
        page.insert_text((48,108), f"MYWORLD / DEMO {number+1:02d}", fontsize=11, color=(.4,.47,.58))
        entries=[(154,"拖过这段文字，然后点击高亮、下划线或删除线。",13),
                 (184,"选中文字，使用附近的小工具条复制、标注、记笔记。",13),
                 (214,"点中批注，可在附近添加评论或选择颜色。",13),
                 (278,"试一试：把下面的答案擦掉，再按撤销恢复。",15),
                 (318,"问题：一个直角等于多少度？",13),
                 (358,"答案：90 度。",13),
                 (430,"用自由画笔在这里划线，或圈出你认为重要的地方。",13),
                 (500,"记笔记可选择目标，Ctrl+V 直接粘贴自己的截图。",13),
                 (530,"点击栏标题处的“交换两栏”，调整原稿与副本位置。",13)]
        for y,text,size in entries:
            page.insert_text((48,y),text,fontname="china-s",fontsize=size)
        page.insert_text((48,775),"SYNTHETIC CONTENT - NO PERSONAL DATA",fontsize=9,color=(.5,.56,.65))
        page.insert_text((520,775),str(number+1),fontsize=11)
    doc[1].set_rotation(90)
    scan = pdf.open()
    try:
        page = scan.new_page(width=595,height=842)
        page.insert_text((48,90),"扫描页区域标注示例",fontname="china-s",fontsize=24)
        page.insert_text((48,165),"此页是图像，没有可选择的文字层。",fontname="china-s",fontsize=15)
        page.insert_text((48,200),"可以拖出高亮区域，或使用自由画笔和擦除。",fontname="china-s",fontsize=15)
        page.insert_text((48,280),"答案：这是一份虚构的示例文档。",fontname="china-s",fontsize=15)
        pix = page.get_pixmap(matrix=pdf.Matrix(1.5,1.5))
        target = doc.new_page(width=595,height=842)
        target.insert_image(target.rect,pixmap=pix)
    finally:
        scan.close()
    doc.set_toc([[1,"标注与擦除",1],[1,"旋转页面",2],[1,"扫描页区域标注",3]])
    doc.set_metadata({"producer":"myworld / PyMuPDF 1.26.6 (GNU AGPLv3)"})
    path=Path(__file__).with_name("demo.pdf")
    doc.save(path,garbage=4,deflate=True)
    doc.close()
    print(path)


if __name__=='__main__':main()
