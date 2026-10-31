# 开发、测试与打包

推荐 Python 3.12 x64。运行依赖见 requirements.txt，构建工具见 requirements-dev.txt。

## 源码运行（Windows PowerShell）

~~~powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe app.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
~~~

Linux 可用 python3.12 创建虚拟环境，安装同样依赖，设置 QT_QPA_PLATFORM=offscreen 后运行测试。Qt 可能需要系统 EGL、OpenGL、xkbcommon 等库，CI 文件包含 Ubuntu 安装示例。

测试使用合成 PDF；GUI 测试有继承的回归用例，运行总数也包含它们。基准：python benchmark.py --output qa/performance.json，使用 800 页模拟文档，不代表所有设备的保证值。

GitHub Actions 提供 Ubuntu 离屏测试与 Windows 依赖导入/窗口构造检查，不自动发布 Release。

## Windows 完整包构建

在仓库根目录执行：

~~~powershell
.\.venv\Scripts\python.exe build_portable.py
~~~

默认缓存 .build-cache/win_wheels，Python 包 .build-cache/python-3.12.10-embed-amd64.zip，输出 dist/myworld_0.6.2_Windows_x64.zip（版本随 brand.py 变化）。

首次联网获取固定官方 Windows wheel 与 Python 嵌入式发行包。检查 wheel RECORD、x64 PE 头及本机库依赖闭包；构建过程不运行 Windows 程序。完整包包含应用源码、文档、测试、示例、许可与运行环境。

已有缓存可指定：

~~~powershell
.\.venv\Scripts\python.exe build_portable.py --cache .build-cache/win_wheels --python-zip .build-cache/python-3.12.10-embed-amd64.zip --output dist
~~~

dist、runtime、缓存均不提交到仓库。完整 ZIP 放 Releases。

## 发版

更新 brand.py、CHANGELOG、docs/releases/对应版本.md；跑测试，在真实 Windows 验证基本操作和中文输入；构建并检查无私人资料；保存依赖清单与许可；生成对应源码和 SHA-256；让 tag 指向同版源码。按 PUBLISH_TO_GITHUB.md 发布。

正式稳定版应在真实 Windows 验证后再移除预览标记。引擎升级应另行检查高亮像素、真实脱敏、中文字体嵌入与存档兼容。
