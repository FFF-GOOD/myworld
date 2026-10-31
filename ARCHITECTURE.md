# 架构与存档兼容

| 模块 | 职责 |
| --- | --- |
| app.py | Qt 主界面、双栏同步、命令 |
| core.py | 历史、原稿/副本作用域、PDF 保存与导出 |
| rendering.py / render_worker.py | 独立 QProcess 后台渲染 |
| text_selection.py | 字符与选区缓存 |
| inline_text.py / fonts.py | 页内文字、光标、字体查找与嵌入 |
| floating_tools.py / comment_cards.py | 小栏、颜色、常驻评论 |
| notebook.py | 图文笔记、图片去重、来源链接 |
| project_links.py | PDF 与记录的精确关联 |
| file_drop.py | 窗口范围的文件拖放过滤，覆盖子视图且保留普通笔记图片操作 |
| brand.py | 产品显示名称与版本 |
| build_portable.py | Windows 打包 |

轻量标注走 Qt 覆盖层，真实 PDF 更新走独立进程；丢弃过期结果，限制队列与缓存。常驻评论只维护可见页面窗口。

原 PDF、工作副本操作与 .pdfwork 是不同数据层。工作记录存源哈希、历史、笔记、PNG 与阅读状态，不复制整份 PDF。保存原稿使用暂存、校验、备份和替换；不匹配文件拒绝自动套用。

## 保留的历史标识

显示名称改为 myworld，以下保留以兼容旧数据：

- STUDYPDF5 等文件头和 studypdf-work JSON 标记；
- studypdf-image: 和 studypdf:// 笔记资源、来源链接；
- StudyPDF: PDF 批注 NM 标识；
- StudyPDF/associations.json 与 STUDYPDF_CONFIG_DIR；
- .studypdf.bak 备份扩展名。

这些不是用户可见品牌。不要全局替换它们；变更须另做迁移。0.6.2 未更改项目格式版本，仍兼容 0.2–0.6 记录。
