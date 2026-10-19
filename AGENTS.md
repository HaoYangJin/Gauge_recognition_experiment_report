# 本仓库维护约定

适用于本仓库代码、文档与实验资料维护。先阅读 README.md、CONTRIBUTING.md 和 docs/ARCHITECTURE.md，保留用户现有工作。

- 使用简体中文说明使用方式与验证结果。根目录 Python 入口保留现有运行习惯，CLI 与 GUI 共用 core.py 中的算法。
- demo/、experiments/、.docs/ 和根目录 verification.json 是实验档案。常规开发验证使用 outputs/、.release_check/ 或仓库外新目录；修改档案必须有相应任务依据并记录来源、配置与变化。
- 不将合成样例指标写成真实照片准确率；输出读数、拒识、容差内正确率分别统计，不混合不同单位误差。保留单位不确定和非线性刻度限制。
- 不因仓库公开而推断第三方图片授权，不自行添加覆盖代码或数据的许可证。
- 按 CONTRIBUTING.md 的显式模块列表执行回归；BoundaryTests 不会被默认 unittest discover 自动找到。完整验证使用独立输出目录，保留实际失败和跳过情况。
- 修改 GUI 后在支持 Tk 和显示环境的机器验证相关交互，无法运行时明确说明，不以 CLI 成功替代。
- 提交前检查 Markdown 链接、git diff --check、暂存范围及档案差异。不得提交凭据、虚拟环境、缓存或未说明的新实验输出。

本文件是项目维护约定，不授予发布、改写历史或操作外部服务的额外权限。
