# 贡献与验证

本项目保留直接运行的 Python 模块结构，CLI 与 GUI 共用 `core.py`。修改前阅读 [架构说明](docs/ARCHITECTURE.md) 和 [实验资料索引](docs/EXPERIMENTS.md)，按 README 创建虚拟环境并安装依赖。

## 哪些文件属于什么

- 应用源码：`core.py`、`gauge_reader.py`、`gui.py`；合成与验证工具：`demo_gauge_simulator.py`、`algorithm_verify.py`。
- 实验档案：`demo/`、`experiments/`、`.docs/` 和根目录 `verification.json`。报告、原图、标定、参数和历史结果共同构成可核查记录。
- 新运行输出：`outputs/`、`.release_check/` 或仓库外独立临时目录，不提交虚拟环境、缓存或本轮生成的中间图。

不要仅为使测试通过而重写参考值、删除拒识样本或覆盖历史结果。确需更新实验档案时，应单独记录数据来源、配置、环境、人工参考依据和结果变化；未经相应授权不为第三方数据新增许可证。

## 本地检查

在项目根目录、已激活虚拟环境中运行：

```bash
python -m pip check
python -m unittest test_batch_sequence_match test_heatmap test_verification_output algorithm_verify.BoundaryTests -v
python algorithm_verify.py
git diff --check
```

单元测试覆盖批次匹配、文件保护、热图、读数边界及验证输出隔离；完整验证另外生成 10 张合成图并运行批处理和边界检查。只有进程返回 0 且样例全部输出、最大满量程误差小于 1% 才表示该合成验证通过。它不测量真实照片准确率。

完整验证默认每次创建独立的 `outputs/verification/run-*`，打印的 `output_directory` 是本轮结果根目录，包含：

```text
<本轮目录>/
├── demo/demo_image/       # 本轮合成输入、标定和真值
├── demo/demo_outputs/     # 本轮过程图、逐图结果和批次汇总
└── verification.json     # 本轮指标、环境和边界测试结果
```

指定固定位置时使用新目录，例如 `python algorithm_verify.py --out outputs/verification/check-001`。目录必须不存在或为空；不能指向项目根目录、其祖先、实验归档或 Git 元数据目录。重复运行请使用新目录。此行为取代旧命令直接覆盖归档的方式；根目录原 `verification.json` 继续表示历史记录。

`python -m unittest discover` 不能自动找到不以 `test` 开头的 `algorithm_verify.BoundaryTests`，所以请使用上述显式模块列表。测试中如有平台权限导致的跳过，应报告具体原因，不能计为已执行通过。

## CI 与界面验证

[Python tests](.github/workflows/tests.yml) 在 Windows、Ubuntu 的 Python 3.12 环境安装依赖、检查依赖、运行相同回归和合成验证，并检查受跟踪文件未被验证过程改写。修复后核对当前提交的 CI，不能复用旧提交的成功结果。

GUI 修改需要在有桌面和 Tk 的环境中实际启动、载入图片，并验证受影响的交互；CLI/单元测试不能替代 GUI 操作。没有显示环境时应说明未验证项。Windows/Linux 的自动测试也不代表 macOS GUI 已实机验证。

## 提交前

检查 `git status --short`、暂存差异和 Markdown 本地链接，确保提交仅包含本轮修改，结果、日志和实验档案的变更均有明确依据。使用描述结果的提交说明；报告实际执行的命令、成功/失败/跳过情况及尚未验证的能力。图像或算法修改应同时比较成功输出、拒识和读数误差，保留失败证据。
