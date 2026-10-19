# 实验资料索引

[返回首页](../README.md) · [详细使用](USAGE.md) · [贡献与验证](../CONTRIBUTING.md)

## 先分清三类资料

| 资料 | 输入与配置 | 结果与用途 |
| --- | --- | --- |
| 合成演示 | [demo/demo_image](../demo/demo_image)，10 张固定种子图、标定与真值 CSV | [demo/demo_outputs](../demo/demo_outputs) 与根目录 [verification.json](../verification.json)，用于核对合成样例和实现，不能替代真实准确率 |
| 真实仪表实验 | [experiments_image/image](../experiments/experiments_image/image)，10 张原图；[逐图标定目录](../experiments/experiments_image/calibration.json) | [experiments_outputs](../experiments/experiments_outputs) 保留历史单图、逐图批次与汇总，不同批次配置不同 |
| 霍夫圆开关对照 | 使用同一组真实原图；[configuration](../experiments/experiments_circle_comparison/configuration) 与 [references.csv](../experiments/experiments_circle_comparison/references.csv) 固定两组共有的标定、参数、参考值 | [off](../experiments/experiments_circle_comparison/off)、[on](../experiments/experiments_circle_comparison/on) 及 [comparison.csv](../experiments/experiments_circle_comparison/comparison.csv)，只有霍夫圆开关不同 |

`experiments/experiments_image/calibration.json` 是**目录**，不是一个 JSON 文件。`ammeter_low.png` 等图片在其中对应同名标定。逐图参数规则与完整文件名优先级见[使用说明](USAGE.md)。

合成演示另有 [demo_circle_comparison](../demo/demo_circle_comparison)，请与真实图片对照区分。可编辑报告为 [仪表识别实验.docx](../.docs/仪表识别实验.docx)，其 [报告附件](../.docs/报告附件) 保留框图和结果截图。

## 归档结果如何解读

下表来自对应目录中的 `summary.json`，不是本次重新训练、测得的真实准确率或通用性能指标：

| 历史批次 | 总数 | 输出读数 | 拒识 |
| --- | ---: | ---: | ---: |
| [逐图批次 batch_per_image](../experiments/experiments_outputs/batch_per_image/summary.json) | 10 | 5 | 5 |
| [霍夫圆关闭 off](../experiments/experiments_circle_comparison/off/summary.json) | 10 | 6 | 4 |
| [霍夫圆开启 on](../experiments/experiments_circle_comparison/on/summary.json) | 10 | 4 | 6 |

`batch_per_image` 与对照实验使用的参数并不相同，不能将其输出数量变化全部归因于霍夫圆。对照实验两组的共同配置和原始说明见[原始对照记录](../experiments/experiments_circle_comparison/README.txt)。

- `status=ok` 表示算法输出了读数，仍可能读错。`ray_support` 不代表正确概率。
- 对照参考值中 `source=user_provided_in_chat_unit_unconfirmed` 的行，其单位尚未确认；非线性刻度不适用于当前两端点线性映射。
- 不同单位的绝对误差不能混合求均值，拒识样本必须计入总样本数。图片数量少且参考值存在不确定性，不能据此宣称真实通用识别准确率。
- JSON/CSV 中保留了当时的绝对路径和环境信息。下载仓库后应按下方相对路径重新运行，而不是复用其中的机器路径。

## 安全复现真实对照

在项目根目录、已安装依赖的环境中执行。每次使用新的输出目录，保留原始档案：

```bash
python gauge_reader.py batch experiments/experiments_image/image --calibration-dir experiments/experiments_circle_comparison/configuration --references experiments/experiments_circle_comparison/references.csv --out outputs/real-circle-off
python gauge_reader.py batch experiments/experiments_image/image --calibration-dir experiments/experiments_circle_comparison/configuration --references experiments/experiments_circle_comparison/references.csv --out outputs/real-circle-on --auto-circle
```

两条命令预计包含拒识，因此 CLI 返回 **2**；仍会保存已处理结果、失败原因、`summary.csv` 与 `summary.json`。这不是全批次未执行，也不能只读取进程退出码后丢弃结果。请按运行后的实际记录统计，不把预期数量当成新结果。

原始对照记录中的命令曾直接写入归档目录；它们保留为当时操作快照。日常复现使用上面的 `outputs/` 路径。要改变版本化实验资料，应单独说明原因、数据来源、配置、参考值与差异。

## 资料与许可

报告和第三方图片按现有档案保留。图片来源及授权以原提供方为准，仓库没有为整个数据集授予统一开源许可。复用、再分发和新增数据前应确认相应授权，不根据仓库公开性推断许可。
