# 从 GitHub 网页开始发布 myworld

本流程只用浏览器，不需要安装 Git。按钮可能随网页语言略有变化。核对日期：2026-10-31。

## 一、准备文件

| 文件 | 用途 | 上传位置 |
| --- | --- | --- |
| myworld_0.6.1_GitHub_Source.zip | 源码、说明、许可、测试、CI | 解压，把里面的文件上传仓库 |
| myworld_0.6.1_Windows_x64.zip | 带运行环境的完整程序 | 原样上传 Releases 的 Assets |
| myworld_0.6.1_SHA256SUMS.txt | 两个 ZIP 的校验值 | 同一 Release 的 Assets |

本指南另有 HTML 版本，可直接用浏览器打开。

## 二、注册和创建公开仓库

1. 打开 https://github.com ，有账号点 **Sign in**，没有账号点 **Sign up** 并完成邮箱验证。
2. 登录后点右上角 **＋ → New repository**，也可打开 https://github.com/new 。
3. **Owner** 选择自己的账号，**Repository name** 填 **myworld**。若你自己的账号已有同名仓库，可填 myworld-pdf；应用名称不变。
4. **Description** 可复制：A local dual-pane PDF reader, annotator, redaction editor and notebook for Windows. 本地双栏 PDF 阅读、批注、擦除与图文笔记工具。
5. **Choose visibility / Visibility** 选择 **Public**，让所有人可以查看。
6. 不自动创建 README、.gitignore、License：这些已在源码包准备好，尤其不要另选 MIT 许可证。
7. 点 **Create repository**。创建成功后地址类似 https://github.com/你的用户名/myworld 。中文“你的用户名”是占位说明，换成你自己的用户名。

参考：[GitHub 创建仓库](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-new-repository)。

## 三、把源码上传到仓库

1. 在电脑上解压 **myworld_0.6.1_GitHub_Source.zip**。
2. 打开解压得到的 **myworld** 文件夹。此时应直接看到 README.md、app.py、LICENSE、docs、tests、.github 等。
3. 回 GitHub 的空仓库页面，点 **uploading an existing file**。如果仓库已有文件，点 **Add file → Upload files**。
4. 把 **myworld 文件夹里面的全部内容**拖到上传区域；保留 docs、tests、assets、.github 等子文件夹结构。
5. 不要把最外层 myworld 文件夹一起拖进去。正确结果是仓库根目录直接有 README.md，而不是 myworld/README.md。
6. 包含 .github、.gitignore、.gitattributes 等点开头文件。若文件管理器没显示，可在“查看 → 显示 → 隐藏的项目”检查。
7. **Commit message** 填 **Initial public release: myworld v0.6.1**。
8. 在你自己的新仓库直接提交到 **main**，点 **Commit changes**。
9. 若界面显示 **Propose changes** 并要求新分支，创建 Pull Request 后再点 **Merge pull request → Confirm merge**，确保文件最终进入 main。
10. 返回 **Code** 页面，确认下方出现完整 README、功能表和截图。

浏览器上传单文件上限 25 MiB，一次最多 100 个文件。源码已控制在该范围；约 50 MB 的 Windows 完整包放到 Releases，不能放这里。GitHub 不会自动解压上传的 ZIP，所以不能仅把源码 ZIP 拖进仓库。网页上传不执行 .gitattributes 的转换，本包 BAT 已预先使用 Windows 行尾。

参考：[GitHub 上传文件](https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository)。

## 四、检查源码和首页

- 根目录有 README.md、LICENSE、app.py；截图 assets/workspace.png 能显示。
- README 中的使用手册等链接可以打开。
- 没有私人 PDF、.pdfwork、笔记、个人截图、日志和本地配置；demo.pdf 是合成示例，可以公开。
- .github/workflows/ci.yml 已上传。顶部 **Actions** 可查看测试；首次可能需要启用工作流。未运行或失败时不要宣称线上 CI 已通过。
- 许可被识别为 **AGPL-3.0**；保留原文件，不重新选择其他许可。
- CI 的 Windows 构造检查不等于真实 Windows 输入法、长文档等全面验证。

## 五、新建 Release 草稿

1. 仓库 **Code** 页右侧找到 **Releases**。
2. 首次点 **Create a new release**，以后点 **Draft a new release**。找不到时，在自己的仓库地址后加 **/releases/new**。
3. 点 **Choose a tag / Select tag**，输入 **v0.6.1**，选择 **Create new tag: v0.6.1 on publish** 或相应选项。
4. **Target** 选已有本版源码的 **main**。
5. **Release title** 填 **myworld v0.6.1 · 首个公开预览版**。
6. 打开源码目录 **docs/releases/v0.6.1.md**，把正文复制到 **Describe this release**。保留源码及第三方来源入口。
7. 建议勾选 **This is a pre-release**：这是首次公开版本，尚未完成 Windows 实机系统性测试。
8. 可以先点 **Save draft** 保存草稿。若页面允许直接继续添加附件，也可以先完成下一节。

参考：[GitHub 管理 Releases](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository)。

## 六、上传下载附件

在 Release 编辑页找到 **Attach binaries by dropping them here or selecting them** 或附件区域，上传：

1. **myworld_0.6.1_Windows_x64.zip**：原样上传，别解压、别改名。
2. **myworld_0.6.1_GitHub_Source.zip**：对应版本源码副本。
3. **myworld_0.6.1_SHA256SUMS.txt**：校验文件。

等三个文件的上传进度完成，逐一检查名称和大小。下载按钮应指向 GitHub Release 附件，不能用自己电脑的路径或聊天附件地址。

Release 单个附件必须小于 2 GiB，本包符合。GitHub 还会自动添加 **Source code (zip)** / **Source code (tar.gz)**，那是 tag 对应的源码，不带运行环境。

参考：[GitHub 关于 Releases](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)。

## 七、正式点击发布

1. 确认 tag **v0.6.1** 对应本版源码，三个附件传完。
2. 发布说明注明预览版与实际测试范围，不写“已全面 Windows 验证”。
3. 点 **Publish release**。
4. 预览版也是公开发布，所有人能下载；它不一定成为 GitHub 的 latest stable。README 因此指向 Releases 列表，而非固定 latest。
5. 若启用了 immutable releases，发布后附件可能不能替换，务必先传齐再发布。

## 八、从其他人的角度验收

1. 复制项目地址，在浏览器无痕窗口打开，不登录也应能看到源码。
2. 打开 **https://github.com/你的用户名/myworld/releases/tag/v0.6.1**；仓库名不同时一并替换。
3. 展开 **Assets**，确认三个附件可下载。
4. 下载完整 Windows 包到新文件夹，完整解压，双击 **Start_myworld.bat**。
5. 打开 demo.pdf，检查两栏、交换、高亮/划线、擦除、添加文本和笔记。
6. 如需核对文件，在 Windows PowerShell 执行：

~~~powershell
Get-FileHash .\myworld_0.6.1_Windows_x64.zip -Algorithm SHA256
~~~

结果应与 SHA256SUMS 对应一行一致，大小写无关。

## 九、完善介绍并分享

仓库右侧 **About → 齿轮** 可以填写介绍和 Topics。建议：pdf、pdf-editor、pdf-reader、annotation、redaction、notes、windows、pyside6。

分享两个地址：

- 项目主页：https://github.com/你的用户名/myworld
- 本版下载页：https://github.com/你的用户名/myworld/releases/tag/v0.6.1

这里不需要 GitHub Pages。README 展示项目，Releases 分发 Windows 程序。发给朋友时说明：“进入 Assets，下载 Windows_x64.zip，完整解压后运行 Start_myworld.bat。”

## 十、以后更新

1. 本地修改并验证，更新 brand.py 的 VERSION、CHANGELOG 与发布说明。
2. 把同版本源码提交到 main。
3. 按开发文档构建新的 Windows ZIP，生成新校验值。
4. 新建版本 tag（例如 v0.6.2）和 Release，上传同版程序与源码。
5. 保留旧版，方便回退；不要在旧 tag 下换成另一版程序。
6. 持续维护应用与依赖的对应源码入口；若上游链接失效，补充可下载副本。见 THIRD_PARTY_NOTICES.md。

## 常见卡点

| 问题 | 处理 |
| --- | --- |
| 文件太大 | Windows ZIP 放 Releases，源码解压后放普通文件区 |
| README 没展示 | 根目录应直接有 README.md，避免多套一层文件夹 |
| 截图不显示 | 把 assets/workspace.png 一起上传，大小写不变 |
| 别人看不到 Release | 草稿仅自己可见，附件齐全后点 Publish release |
| 只有 Source code | 编辑 Release，把完整 Windows ZIP 传到附件区 |
| .github 缺失 | 检查点开头文件，重新拖入整个 .github 文件夹 |
| 程序无法启动 | 完整解压并保留 runtime；运行 Diagnostic.bat 查看错误 |
| 系统提示未知发布者 | 当前未代码签名；核对来源与 SHA-256，自行决定是否运行 |
| 旧存档不匹配 | 一起保留原 PDF 和 .pdfwork，校验失败不要强行套用 |
