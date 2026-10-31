# 0.6.1 验证记录

- 95 项既有回归运行：Linux Qt 离屏环境通过。
- 4 项改名/兼容性检查：显示名、PDF 元数据/批注作者、历史项目格式、历史关联目录，均通过。
- 应用截图使用合成 demo.pdf，已检查中文和布局，不含私人资料。
- 示例 PDF 元数据、页数和图像已检查。
- Markdown 本地文件链接及 GitHub Actions YAML 已静态检查。
- Windows 完整包检查官方 wheel 哈希、PE x64 架构、依赖闭包、ZIP CRC 与源码一致性。
- 未在 Windows 实机完成系统性测试，未在 GitHub 远端运行工作流；线上结果以实际 Actions 为准。
