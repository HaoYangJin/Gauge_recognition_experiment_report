# 详细使用与算法说明

[返回首页](../README.md) · [实验资料索引](EXPERIMENTS.md)

以下命令均在项目根目录运行，先按快速运行步骤安装依赖并激活虚拟环境。

## 1 快速运行

建议使用带 Tk 的 Python 3.12。项目无需 GPU、模型权重或在线服务。下载后先解压整个项目目录，再在目录内打开终端。

```bash
python -m venv .venv
```

Windows PowerShell 激活：

```powershell
.venv\Scripts\Activate.ps1
```

如果 PowerShell 不允许执行激活脚本，可以直接使用 `.venv\Scripts\python.exe` 替代下文的 `python`，无需修改系统执行策略。

macOS / Linux 激活：

```bash
source .venv/bin/activate
```

安装并打开界面：

```bash
python -m pip install -r requirements.txt
python gui.py
```

首次体验可选择 `demo/demo_image/images/04_middle.png`，载入 `demo/demo_image/calibration.json`，点击“识别并导出各步骤”。预期读数接近 0.8 MPa。

`opencv-python-headless` 不带 OpenCV 自带窗口，本项目使用 Tkinter 显示图片，所以可正常运行 GUI。请勿同时安装多个提供 `cv2` 的 OpenCV 包。运行 `python -m tkinter` 可检查 Tk 安装；Linux 缺少 Tk 时安装发行版对应的 `python3-tk`，远程无桌面机器使用命令行。

既有 README 记录过 Linux 虚拟显示环境的启动、四点标定、后台识别和结果显示检查；[2026-10-14 检查记录](RELEASE_CHECK.md)包含 Windows 启动及图片载入冒烟。以上是历史证据，不能代替当前提交的界面验证；macOS 尚未实机验证。无桌面环境下，GUI 初始化测试会明确跳过，CLI 成功不能代替交互检查。界面优先选择微软雅黑、苹方或 Noto 中文字体。Linux 如缺少中文字形，需安装系统中文字体；仅识别旧式 X11 字体的 Tk 构建可使用 `xfonts-wqy`。

## 2 真实照片的四点标定

1. 选择一张清晰、近似正视的照片，优先裁剪到一个表盘。照片应保留完整刻度、圆心和指针。
2. 点击“四点标定”，依次点击**指针旋转中心 → 表盘外圆边缘 → 最小刻度位置 → 最大刻度位置**。
3. 输入真实最小值、最大值与单位。`cw` 表示读数增大时顺时针旋转，`ccw` 表示逆时针旋转。可以按刻度数字的增加方向判断。
4. 选择 `dark` 深色指针或 `light` 浅色指针。默认 Otsu 二值化；光照不均时可试 `adaptive`。
5. 保存标定 JSON，然后识别。人工读数可选填；算法拒识（包括未找到表盘圆）时也会在结果 JSON 中保留该值，只有成功输出读数才计算绝对误差、相对误差和满量程误差。人工读数不写入标定 JSON。

**只允许同一表盘、同一机位和同一裁剪方式复用标定。** 归一化坐标允许图像等比例缩放，不代表支持任意裁剪、相机旋转或透视变化。改变这些条件应重新标定。

霍夫圆是可选的圆心、半径微调功能，仍依赖粗略标定及正确的起止角度；不能自动识别数字、量程或相机旋转。斜拍、强反光、多指针或非线性刻度暂不适用。

## 3 命令行操作

单张识别：

```bash
python gauge_reader.py read demo/demo_image/images/04_middle.png --calibration demo/demo_image/calibration.json --manual-value 0.8 --out outputs/single
```

文件夹批处理（当前层，不递归）：

```bash
python gauge_reader.py batch demo/demo_image/images --calibration demo/demo_image/calibration.json --references demo/demo_image/references.csv --out outputs/batch
```

不同照片使用各自的标定（扫描图片文件夹当前层，不递归）：

```powershell
.\.venv\Scripts\python.exe gauge_reader.py batch "experiments/experiments_image/image" --calibration-dir "experiments/experiments_image/calibration.json" --out "outputs/real-per-image"
```

这里 `experiments/experiments_image/calibration.json` 是**文件夹**。例如 `image/ammeter_low.png` 对应其中的 `ammeter_low.json`。也支持 `ammeter_low.png.json`，且完整文件名优先；如果同时有 `a.jpg` 和 `a.png`，必须分别提供 `a.jpg.json`、`a.png.json`，避免错配。`--calibration-dir` 与共用标定 `--calibration` 不能同时使用。

GUI 点击 **“批量识别（逐图标定 JSON）”**，依次选择原图文件夹、标定 JSON 文件夹、结果保存文件夹，无需先载入单张图片或标定。原来的“批量识别同机位图片”仍使用当前共用标定。开始前可选择二值化、指针颜色和是否修正霍夫圆；GUI 会为每次逐图标定批次创建独立的时间戳目录。

混合深色/亮色指针时，可在标定文件夹添加可选的 `speedgauge.params.json`（也支持 `speedgauge.png.params.json`），例如：

```json
{"polarity": "light"}
```

这些逐图参数覆盖 `--params` 或 GUI 当前设置中的同名字段，其余字段沿用当前设置。没有逐图参数文件时，所有图片使用同一组处理参数，默认深色指针；程序不会根据文件名猜测指针颜色。

输出结构为 `输出目录/原图完整文件名/`，包含过程图与 `result.json`；只有识别成功才生成 `09_result.png`。缺少或损坏的标定、识别失败等会记录在该图的 JSON 中，然后继续下一张。批次根目录生成 Excel 可打开的 `summary.csv` 和完整 `summary.json`，记录状态、读数、单位、标定路径、参数文件路径及失败原因。CLI 有任意失败时返回退出码 2，但已处理的结果仍会保存。

批处理不验证标定是否符合真实表盘；非线性刻度、多指针、单位或量程填写错误仍可能得到错误读数。`status=ok` 只表示算法输出了读数，不表示已验证准确。

批处理功能及已有边界回归测试：

```bash
python -m unittest test_batch_sequence_match test_heatmap test_verification_output algorithm_verify.BoundaryTests -v
```

参数覆盖与霍夫圆：

```bash
python gauge_reader.py read your_photo.jpg --calibration your_calibration.json --params params_default.json --auto-circle --out outputs/real
```

`--params` 接受只含需修改字段的 JSON，其余字段采用默认值。所有参数及实际 Otsu / 固定阈值均保存在 `result.json`。自适应阈值是局部阈值，没有单一全局阈值，相关字段为 `null`。

重新生成演示数据并运行完整验证：

```bash
python algorithm_verify.py --out outputs/verification/manual-run-001
```

`algorithm_verify.py` 在新验证目录内生成 `demo/demo_image`、`demo/demo_outputs` 和 `verification.json`，保留仓库内的实验档案。省略 `--out` 时，每次在 `outputs/verification/run-*` 创建独立目录；指定 `--out` 时，目录必须不存在或为空，不能位于项目根目录、其祖先、`demo/`、`experiments/`、`.docs/` 或 `.git/` 内。重复验证请省略 `--out` 或使用新目录。完整验证退出码 0 表示通过，1 表示验证未通过，参数或输出目录无效时返回 2。命令行识别全部成功返回 0；失败或批量存在失败返回 2。

## 4 文件说明

| 文件 | 用途 |
|---|---|
| `core.py` | 预处理、霍夫累加器、指针筛选、角度映射与结果导出 |
| `gauge_reader.py` | 命令行单张和批处理入口 |
| `gui.py` | Tkinter 界面与四点标定 |
| `demo_gauge_simulator.py` | 固定种子合成样例生成 |
| `algorithm_verify.py` | 10 张合成样例及关键边界验证 |
| `params_default.json` | 可修改的参数文件 |
| `demo/demo_image` | 带醒目标记的合成图片、示例标定、真值 CSV |
| `demo/demo_outputs` | 已运行的各步骤图片、读数和汇总 |
| `verification.json` | 历史合成验证摘要及当时运行环境 |
| `.docs/仪表识别实验.docx` | 已填写方法、代码、合成结果及分析的可编辑报告 |
| `experiments/experiments_circle_comparison/references.csv` | 真实实验人工参考值（使用前核对单位） |

每张图片的输出如下：

| 输出 | 内容 |
|---|---|
| `00_input.png` | 应用 EXIF 旋转后、必要时缩小的输入图 |
| `01_gray.png` / `02_filtered.png` | 灰度图 / 高斯滤波图 |
| `03_binary.png` / `04_morphology.png` | 二值图 / 形态学结果 |
| `05_roi.png` / `06_edges.png` | 环形候选区域 / 边缘图 |
| `07_hough_accumulator.png` | 标准霍夫累加器热图 |
| `hough_accumulator.npz` | 累加器原始数值、rho 和 theta 坐标 |
| `08_hough_candidates.png` | 检测出的霍夫线段 |
| `09_result.png` | 指针方向、角度和读数叠加图 |
| `result.json` | 校准、参数、读数、警告、误差或失败原因 |

批处理还会产生 `summary.csv` 和 `summary.json`。通过参考 CSV 传入的人工读数会保留在失败记录中。单张结果目录冲突或无写入权限时，该图标记为失败，具体写入错误记录在根目录汇总的 `write_error` 字段中，后续图片继续处理；这要求批次根目录本身可以写入。单张检测失败不会产生成功结果图；如果复用输出目录，旧的成功结果图会先删除。建议为每次正式实验使用新输出目录。输出图片的尺寸可能缩小至最长边 1000 像素，输入照片不会被修改。

示例 CSV 的 `manual_value` 列为统一导入接口命名；`source=synthetic_ground_truth_not_manual` 明确表示该列来自合成真值，不是人工读数。真实实验的 CSV 需要自行记录：

```csv
filename,manual_value,source
meter_001.jpg,0.72,human_reading
meter_002.jpg,1.10,human_reading
```

## 5 必须理解的原理

角度采用“右 0°、上 90°、左 180°、下 270°”，由 `atan2(cy-y, x-cx)` 计算。图像 y 轴向下，因此这里使用 `cy-y`。

数值递增方向为顺时针时：

```python
span = (start_angle - end_angle) % 360
delta = (start_angle - needle_angle) % 360
reading = min_value + delta / span * (max_value - min_value)
```

逆时针时，分别改成 `(end_angle-start_angle)%360` 和 `(needle_angle-start_angle)%360`。只有位于有效刻度弧段内才输出读数；端点外最多 2° 的估计误差允许吸附到端点，并写入警告。不支持起止角度重合的整圈表盘。

霍夫参数中的 theta 是**直线法线的角度**，不同于上述有向指针角度。代码先用 `HoughLinesP` 获得候选线段，再筛选圆心附近的长线段，并比较两侧径向前景支持来判断针尖朝向。

热图来自对同一边缘图单独计算的标准霍夫累加器，公式为 `rho=x*cos(theta)+y*sin(theta)`。它不是 OpenCV 概率霍夫函数的内部累加器。热图颜色为 `log(1+票数)`，原始票数保存在 NPZ 文件中。

`ray_support` 是候选方向上的前景支持比例，用于启发式筛选，**不等于识别正确概率**。程序对无指针、证据不足、方向歧义或量程之外的结果可拒绝输出，但这些规则不保证识别所有失败情况，仍须人工复核。

## 6 调参与误差分析

先检查标定和方向，再查看二值图与 ROI，最后调霍夫参数。建议一次只改变一类参数。

| 现象 | 优先检查 |
|---|---|
| 指针在二值图中消失 | 指针极性、阈值方式、滤波核是否过大 |
| 指针被形态学操作去掉 | 保持 `open_kernel=1`，减小闭运算核 |
| 数字或刻度被选中 | 缩小 `outer_ratio`，检查圆心，适当增大 `min_line_ratio` |
| 细针或短针识别失败 | 减小 `min_line_ratio`，调整 ROI；过度放宽会增加误检 |
| 量程之外 | 先核对 `cw/ccw`、起止点；再核对识别线段 |
| 光照不均 | 优先改善拍摄条件，再试自适应阈值；浅色指针可能还需调整 `adaptive_c` |
| 自动圆定位错误 | 关闭自动圆，重新手动标定 |

绝对误差为 `|R-Rref|`；相对误差为 `|R-Rref|/|Rref|*100%`，参考值为 0 时留空；满量程误差为 `|R-Rref|/(Rmax-Rmin)*100%`。失败样本应单独统计，不能从成功率分母中删除。

## 7 后续真实实验

建议至少收集 15～30 张覆盖低、中、高读数和不同光照的照片，保留输入原图与人工读数。相同机位分组处理；不同机位分别标定。提前确定容许误差，例如以最小分度值为依据，报告中可选用满量程误差作统一比较。调整参数的照片与最终评价照片应分开。

后续实验应在报告中记录：样本来源、机位、标定方法、人工读数依据、样本总数、拒识数、成功率、成功样本 MAE、最大误差及典型失败原因。程序无法区分输入是否为真实照片，数据来源必须由实验者准确记录。

## 8 参考资料

- OpenCV Hough Line Transform：https://docs.opencv.org/4.x/d6/d10/tutorial_py_houghlines.html
- OpenCV Image Thresholding：https://docs.opencv.org/4.x/d7/d4d/tutorial_py_thresholding.html
- OpenCV Morphological Transformations：https://docs.opencv.org/4.x/d9/d61/tutorial_py_morphological_ops.html
- OpenCV Hough Circle Transform：https://docs.opencv.org/4.x/da/d53/tutorial_py_houghcircles.html
- Python Tkinter：https://docs.python.org/3/library/tkinter.html
