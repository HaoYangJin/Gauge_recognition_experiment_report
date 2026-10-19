# 指针仪表自动读数实验

基于 OpenCV 的指针仪表读数实验：提供单图与批处理命令行、Tkinter 四点标定界面、霍夫累加器可视化和可编辑实验报告。无需 GPU、模型权重或在线服务。

**先标定，再读数。** 当前算法按线性刻度映射角度，适用于单表盘、近似正视的图片。同一表盘、同一机位和裁剪方式才能复用标定；不支持无需量程标定的通用识别。合成验证结果不代表真实照片准确率。

## 从这里开始

| 你想做什么 | 入口 |
| --- | --- |
| 先跑一个样例 | 下方快速开始 |
| 处理自己的照片、逐图标定或批处理 | [详细使用与算法说明](docs/USAGE.md) |
| 查看真实实验、合成样例与对照结果 | [实验资料索引](docs/EXPERIMENTS.md) |
| 阅读实验报告 | [仪表识别实验.docx](.docs/仪表识别实验.docx) |
| 修改代码或复现验证 | [贡献与验证](CONTRIBUTING.md) · [架构说明](docs/ARCHITECTURE.md) |
| 查找其他资料 | [文档目录](docs/README.md) |

## 快速开始

推荐 Python 3.12。克隆或下载并完整解压仓库，在项目根目录打开终端：

```bash
python -m venv .venv
```

Windows PowerShell 激活 `.venv\Scripts\Activate.ps1`；macOS/Linux 激活 `source .venv/bin/activate`。如果 PowerShell 阻止激活，可直接用 `.venv\Scripts\python.exe` 替代下文的 `python`，无需修改系统执行策略。

```bash
python -m pip install -r requirements.txt
python gauge_reader.py read demo/demo_image/images/04_middle.png --calibration demo/demo_image/calibration.json --manual-value 0.8 --out outputs/single
```

样例预期接近 **0.8 MPa**；结果写入 `outputs/single/result.json`，过程图和成功结果图也保存在该目录。示例量程 0～1.6 MPa 只适用于演示，自己的表盘需要重新标定。

有桌面环境时可打开界面：

```bash
python gui.py
```

选择 `demo/demo_image/images/04_middle.png`，载入 `demo/demo_image/calibration.json`，点击“识别并导出各步骤”。处理真实照片时用“四点标定”依次选圆心、外圆边缘、最小和最大刻度位置，再填写量程、单位及递增方向。

`opencv-python-headless` 不提供 OpenCV 自带窗口，本项目使用 Tkinter 显示图片。可用 `python -m tkinter` 检查 Tk；Linux 缺少 Tk 时安装发行版对应的 `python3-tk`，无桌面环境使用 CLI。不要同时安装多个提供 `cv2` 的 OpenCV 包。中文字体和各平台已验证范围见[详细说明](docs/USAGE.md)。

## 验证与复现

```bash
python -m unittest test_batch_sequence_match test_heatmap test_verification_output algorithm_verify.BoundaryTests -v
python algorithm_verify.py
```

第一条执行回归测试，第二条执行 10 张合成样例的端到端验证及算法边界检查。完整验证每次写入独立的 `outputs/verification/run-*` 目录，保留已归档的演示数据、实验数据和根目录 `verification.json`。日志中的 `output_directory` 指明本轮结果位置。自选目录、真实实验复现与 CI 说明见[贡献与验证](CONTRIBUTING.md)。

## 仓库内容

| 位置 | 内容 |
| --- | --- |
| `core.py` | 图像预处理、霍夫候选、指针定向和线性读数 |
| `gauge_reader.py` / `gui.py` | 命令行与桌面界面入口，共用算法核心 |
| `demo/` | 10 张合成输入、真值、历史输出和霍夫圆演示对照 |
| `experiments/` | 10 张真实输入、标定、处理结果和霍夫圆开关对照 |
| `.docs/` | 可编辑实验报告及报告附件 |
| `docs/` | 使用、实验索引、架构及历史检查记录 |
| `verification.json` | 历史合成验证摘要及当时的环境版本 |
| `outputs/` | 本地新结果，已由 Git 忽略 |

## 如何理解实验结果

归档的真实对照实验中，关闭霍夫圆时 10 张图有 6 张输出读数、4 张拒识；开启时 4 张输出、6 张拒识。**输出读数不等于读数正确**，霍夫圆也并非总能改善结果。样本包含非线性刻度、单位和参考值待核对项，不能混合不同单位计算总体误差，也不能据此宣称通用准确率。逐批来源与限制见[实验资料索引](docs/EXPERIMENTS.md)。

`status=ok` 仅表示算法得到读数；`ray_support` 是启发式图像支持比例，不是正确概率。真实实验须人工复核，拒识样本也应保留在评价分母中。标定、输出字段、误差定义、调参和参考资料保留在[详细说明](docs/USAGE.md)。

仓库保留原始报告和实验档案供核查。第三方图片来源及授权以原提供方为准，目前未提供覆盖代码和数据的统一开源许可证。复用或再分发前请确认相应授权。
