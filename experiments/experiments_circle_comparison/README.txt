实验数据霍夫圆开关对比

目录说明：
off/：关闭霍夫圆，内含每张图片的处理步骤、result.json、批次 summary.csv 和 summary.json。
on/：开启霍夫圆，结构同上。找圆阶段失败的图片可能仅有 result.json；识别失败不生成 09_result.png。
configuration/：运行时复制的原始逐图标定，以及从单张处理结果提取的逐图 parameters，供复现。
references.csv：人工参考值快照；来源为 user_provided_in_chat_unit_unconfirmed 的行，其单位尚未由用户确认。
comparison.csv：将两组结果按原图文件名匹配后的对比表，含人工值、读数、误差、support 与失败原因。

对比条件：
使用 experiments/experiments_image/image 中的 10 张原图。
两组使用相同的逐图标定、处理参数及人工参考值，仅改变 --auto-circle。
未修改原图、原标定及原单张结果。
关闭时 6 张输出读数，开启时 4 张输出读数；这是输出读数数量，不是准确率。
失败图片的参考值仍保存在 references.csv 和 comparison.csv；没有识别值时误差留空。
非线性仪表不适用于当前两端点线性映射。标定单位、倍率、未知量程和参考值仍需人工确认。
不同单位的绝对误差不能直接混合求平均，也不能仅凭输出数量判断哪个模式更准确。

复现命令（在项目根目录运行）：
.\.venv\Scripts\python.exe gauge_reader.py batch experiments/experiments_image/image --calibration-dir experiments/experiments_circle_comparison/configuration --references experiments/experiments_circle_comparison/references.csv --out experiments/experiments_circle_comparison/off
.\.venv\Scripts\python.exe gauge_reader.py batch experiments/experiments_image/image --calibration-dir experiments/experiments_circle_comparison/configuration --references experiments/experiments_circle_comparison/references.csv --out experiments/experiments_circle_comparison/on --auto-circle
