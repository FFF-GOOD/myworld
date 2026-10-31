# 第三方许可与对应源码

应用源码使用 AGPL-3.0-only，完整正文见 LICENSE。依赖保留各自版权和许可，未因产品改名转归 myworld，也不宣称获得商业 SDK 许可。

| 组件 | 版本 | 说明 |
| --- | --- | --- |
| PyMuPDF / MuPDF | PyMuPDF 1.26.6，内含 MuPDF | 使用 AGPL 开源分发，非商业授权 |
| PySide6-Essentials / shiboken6 | 6.8.3 | 保留上游 LGPL/GPL 等许可选项与组件声明 |
| Qt 动态库及插件 | 来自固定 6.8.3 wheel | 保留在 runtime，可合法替换和调试 |
| CPython 嵌入式包 | 3.12.10 x64 | 原始许可见 runtime/LICENSE.txt |
| wheel 附带 Microsoft 运行库等 | 固定上游 Windows wheel | 保留原分发 notices，不另行重新授权 |
| pefile | 2024.8.26，仅构建 | MIT，应用运行不依赖它 |

完整包保留原始 dist-info、COPYING、许可文件和 BUNDLE_MANIFEST.json。应用不捆绑系统字体、福昕或 ima 图标。

## 对应源码

应用源码就在 Release 的 GitHub_Source ZIP / tag 源码中；完整 Windows 包也包含应用 .py、测试与构建脚本。

- PyMuPDF 1.26.6 完整 source distribution：https://pypi.org/project/PyMuPDF/1.26.6/#files
- PyMuPDF 固定版本代码：https://github.com/pymupdf/PyMuPDF/tree/1.26.6
- Qt for Python / Shiboken：https://code.qt.io/cgit/pyside/pyside-setup.git/?h=v6.8.3
- Qt 6.8.3 源码归档：https://download.qt.io/archive/qt/6.8/6.8.3/single/
- CPython：https://www.python.org/downloads/release/python-31210/
- pefile：https://github.com/erocarrera/pefile/tree/v2024.8.26

PyMuPDF 请取完整 source distribution 及其构建资料，不用可能缺少依赖子模块的通用 GitHub ZIP 取代。wheel 文件名、哈希与 Python ZIP 哈希在发行包的 BUNDLE_MANIFEST.json。

发布者在下载旁保留这些源码指向并维护其可用性；若上游失效，应提供同版源码副本。不要只分发运行包而删除源码、许可与依赖说明。

## 上游说明

- AGPLv3：https://www.gnu.org/licenses/agpl-3.0.html
- PyMuPDF 许可：https://pypi.org/project/PyMuPDF/1.26.6/
- Qt for Python：https://doc.qt.io/qtforpython-6/licenses.html
- 不同服务器提供源码：https://www.gnu.org/licenses/gpl-faq.html#SourceAndBinaryOnDifferentSites
