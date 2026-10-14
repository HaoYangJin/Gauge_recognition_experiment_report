"""指针仪表读数核心。角度约定：右 0°、上 90°、逆时针为正。

只处理近似正视、单指针、线性刻度表盘。校准值必须来自实际仪表。
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps


# 所有单图输出集中声明，重跑前统一清理，避免混入上次的过程图。
OUTPUT_FILES = ("00_input.png", "01_gray.png", "02_filtered.png", "03_binary.png",
                "04_morphology.png", "05_roi.png", "06_edges.png",
                "07_hough_accumulator.png", "08_hough_candidates.png", "09_result.png",
                "hough_accumulator.npz", "result.json")


class DetectionError(RuntimeError):
    """无法可靠识别时显式报错，不返回伪造读数。"""


@dataclass
class Calibration:
    # 几何量按图片尺寸归一化；量程和角度来自实际仪表，不能由默认值推断。
    center_x: float = 0.5       # 横坐标 / 图像宽度
    center_y: float = 0.5       # 纵坐标 / 图像高度
    radius: float = 300 / 720   # 半径 / min(宽, 高)
    start_angle: float = 225.0
    end_angle: float = 315.0
    direction: str = "cw"      # 数值增大时的旋转方向
    min_value: float = 0.0
    max_value: float = 1.6
    unit: str = "MPa"

    def validate(self):
        if not isinstance(self.unit, str):
            raise ValueError("单位必须为字符串")
        nums = [self.center_x, self.center_y, self.radius, self.start_angle,
                self.end_angle, self.min_value, self.max_value]
        if not all(math.isfinite(x) for x in nums):
            raise ValueError("校准参数必须为有限数值")
        if not (0 <= self.center_x <= 1 and 0 <= self.center_y <= 1):
            raise ValueError("圆心归一化坐标应在 [0, 1] 内")
        if not 0 < self.radius <= 1:
            raise ValueError("归一化半径应在 (0, 1] 内")
        if self.direction not in ("cw", "ccw"):
            raise ValueError("direction 必须为 cw 或 ccw")
        if self.max_value <= self.min_value:
            raise ValueError("最大读数必须大于最小读数")
        if self.span < 1:
            raise ValueError("起止角度不能重合；本项目不支持整圈 360° 量程")

    @property
    def span(self):
        # 沿数值增大的方向计算有效弧长；取模使跨越 0° 的刻度也能正确处理。
        return ((self.start_angle - self.end_angle) if self.direction == "cw"
                else (self.end_angle - self.start_angle)) % 360

    def geometry(self, shape):
        # NumPy 图像 shape 是 (高, 宽, 通道)，圆心的 x/y 分别对应宽/高。
        h, w = shape[:2]
        return self.center_x * w, self.center_y * h, self.radius * min(w, h)

    @classmethod
    def load(cls, path):
        obj = cls(**json.loads(Path(path).read_text(encoding="utf-8")))
        obj.validate()
        return obj

    def save(self, path):
        self.validate()
        write_json(path, asdict(self))


@dataclass
class Params:
    # 默认处理参数；尺寸相关的线段长度、圆心容差等用半径比例表示。
    max_size: int = 1000
    blur_kernel: int = 5
    threshold_mode: str = "otsu"
    fixed_threshold: int = 110
    polarity: str = "dark"  # dark 深色指针；light 浅色指针
    adaptive_block: int = 31
    adaptive_c: float = 7.0
    close_kernel: int = 3
    open_kernel: int = 1
    # 只在环形区域内找指针：排除中心轴帽，并尽量避开外围刻度。
    inner_ratio: float = 0.13
    outer_ratio: float = 0.80
    center_tolerance: float = 0.10
    min_line_ratio: float = 0.24
    max_gap_ratio: float = 0.06
    min_ray_support: float = 0.45  # 图像证据的最低支持率，不是概率置信度。
    endpoint_tolerance: float = 2.0

    def validate(self):
        for name in ("blur_kernel", "close_kernel", "open_kernel", "adaptive_block"):
            x = getattr(self, name)
            if not isinstance(x, int) or x < 1 or x % 2 == 0:
                raise ValueError(f"{name} 必须为正奇数")
        if self.adaptive_block < 3 or self.max_size < 200:
            raise ValueError("adaptive_block >= 3，max_size >= 200")
        if not (0 <= self.inner_ratio < self.outer_ratio <= 0.98):
            raise ValueError("ROI 半径比例必须满足 0 <= inner < outer <= 0.98")
        if self.threshold_mode not in ("otsu", "fixed", "adaptive"):
            raise ValueError("不支持的二值化方式")
        if self.polarity not in ("dark", "light"):
            raise ValueError("polarity 应为 dark 或 light")
        if not 0 <= self.fixed_threshold <= 255:
            raise ValueError("阈值应在 0 到 255 内")
        if not 0 < self.center_tolerance < 0.5 or not 0 < self.min_line_ratio < 1:
            raise ValueError("圆心容差和线段长度比例不合法")
        if not 0 <= self.max_gap_ratio < 1 or not 0 < self.min_ray_support <= 1:
            raise ValueError("线段间隙或射线支持阈值不合法")
        if not 0 <= self.endpoint_tolerance <= 10 or not math.isfinite(self.adaptive_c):
            raise ValueError("端点容差或自适应阈值参数不合法")


def write_json(path, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    # 禁止写入 NaN/Infinity，避免生成其他 JSON 工具无法可靠读取的数据。
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def read_image(path):
    # Pillow 支持中文路径，并统一应用 EXIF 旋转信息。
    with Image.open(path) as im:
        rgb = np.asarray(ImageOps.exif_transpose(im).convert("RGB"))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def save_image(path, image):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(p.suffix or ".png", image)
    if not ok:
        raise OSError(f"图片编码失败: {p}")
    encoded.tofile(p)


def angle_at(cx, cy, x, y):
    # 图像 y 轴向下，需要取 cy-y。
    return math.degrees(math.atan2(cy - y, x - cx)) % 360


def circular_distance(a, b):
    # 返回圆周上两角的最短距离，例如 359° 与 1° 的距离是 2°。
    return abs((a - b + 180) % 360 - 180)


def angle_to_value(angle, cal, tolerance=2.0):
    """跨零点的有向弧长映射；区间外报错，只允许端点附近微小误差。"""
    cal.validate()
    if not math.isfinite(angle):
        raise ValueError("角度必须为有限值")
    # delta 是从最小刻度沿指定方向走到指针的角度，而非相对水平轴的角度。
    delta = ((cal.start_angle - angle) if cal.direction == "cw"
             else (angle - cal.start_angle)) % 360
    snapped = False
    if delta > cal.span:
        if circular_distance(angle, cal.start_angle) <= tolerance:
            delta, snapped = 0.0, True
        elif circular_distance(angle, cal.end_angle) <= tolerance:
            delta, snapped = cal.span, True
        else:
            raise DetectionError("指针角度位于标定量程之外，请复核量程方向或识别结果")
    # 仅适用于角度与读数成线性关系的刻度；非线性仪表需额外的映射模型。
    value = cal.min_value + delta / cal.span * (cal.max_value - cal.min_value)
    return float(value), float(delta), snapped


def auto_circle(gray, cal):
    """霍夫圆仅更新圆心与半径；量程角度仍需标定。"""
    h, w = gray.shape
    cx, cy, r = cal.geometry(gray.shape)
    # 按原标定半径限定搜索范围；这是局部修正，不是任意图片的自动标定。
    candidates = cv2.HoughCircles(
        cv2.medianBlur(gray, 5), cv2.HOUGH_GRADIENT, dp=1.2,
        minDist=min(h, w) * 0.25, param1=120, param2=45,
        minRadius=max(15, int(r * 0.65)), maxRadius=int(r * 1.35))
    if candidates is None:
        raise DetectionError("未找到合适的表盘圆；请使用四点手动标定")
    circles = candidates[0]
    # 在多个候选圆中，优先选择圆心和半径最接近原标定的一个。
    cost = np.hypot(circles[:, 0] - cx, circles[:, 1] - cy) / r + abs(circles[:, 2] - r) / r
    x, y, rad = map(float, circles[np.argmin(cost)])
    if math.hypot(x - cx, y - cy) > 0.35 * r:
        raise DetectionError("检测圆偏离标定圆心过远，请人工复核")
    return replace(cal, center_x=x / w, center_y=y / h, radius=rad / min(h, w))


def preprocess(image, cal, params):
    # 等比例缩小控制计算量；归一化标定会在新尺寸上重新换算成像素坐标。
    h, w = image.shape[:2]
    if max(h, w) > params.max_size:
        s = params.max_size / max(h, w)
        image = cv2.resize(image, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    filtered = cv2.GaussianBlur(gray, (params.blur_kernel,) * 2, 0)
    # 两种极性都把目标指针变为白色前景，方便后续统一统计支持率。
    flag = cv2.THRESH_BINARY_INV if params.polarity == "dark" else cv2.THRESH_BINARY
    threshold = None
    if params.threshold_mode == "adaptive":
        binary = cv2.adaptiveThreshold(filtered, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                       flag, params.adaptive_block, params.adaptive_c)
    else:
        th = params.fixed_threshold
        if params.threshold_mode == "otsu":
            th, flag = 0, flag | cv2.THRESH_OTSU
        threshold, binary = cv2.threshold(filtered, th, 255, flag)
    # 闭运算填补小间隙；可选开运算去除小前景噪点，核为 1 时相当于不处理。
    morphology = cv2.morphologyEx(binary, cv2.MORPH_CLOSE,
                                np.ones((params.close_kernel,) * 2, np.uint8))
    if params.open_kernel > 1:
        morphology = cv2.morphologyEx(morphology, cv2.MORPH_OPEN,
                                    np.ones((params.open_kernel,) * 2, np.uint8))
    cx, cy, r = cal.geometry(image.shape)
    yy, xx = np.ogrid[:image.shape[0], :image.shape[1]]
    dist = np.hypot(xx - cx, yy - cy)
    # ROI 掩模只保留标定圆心周围的有效环带，之后再在其中提取边缘。
    mask = ((dist >= params.inner_ratio * r) & (dist <= params.outer_ratio * r)).astype(np.uint8) * 255
    roi = cv2.bitwise_and(morphology, mask)
    edges = cv2.Canny(roi, 50, 150)
    return image, {"01_gray": gray, "02_filtered": filtered, "03_binary": binary,
                   "04_morphology": morphology, "05_roi": roi, "06_edges": edges}, threshold


def hough_accumulator(edges):
    """独立标准霍夫累加器，用于教学热图，不冒称 HoughLinesP 内部数组。"""
    h, w = edges.shape
    diag = int(np.ceil(np.hypot(h, w)))
    ys, xs = np.nonzero(edges)
    # theta 是图像坐标系中的直线法线角，不是“右 0°、上 90°”的针尖方向。
    thetas = np.arange(180, dtype=np.float64)
    # 行对应 rho、列对应 theta；用 diag 偏移把负 rho 转为非负数组下标。
    acc = np.zeros((2 * diag + 1, 180), dtype=np.uint32)
    for j, theta in enumerate(np.deg2rad(thetas)):
        rho_indices = np.rint(xs * np.cos(theta) + ys * np.sin(theta)).astype(int) + diag
        # 同一角度下落入相同 rho 格子的边缘点各投一票。
        acc[:, j] = np.bincount(rho_indices, minlength=2 * diag + 1)
    return acc, np.arange(-diag, diag + 1), thetas


def ray_evidence(mask, cx, cy, r, angle, params):
    """沿候选方向检查连续径向支持，消除霍夫直线的 180° 歧义。"""
    rad = np.deg2rad(angle)
    # 沿径向取 180 个位置，每处横向检查一条窄带，容忍指针宽度和小偏差。
    distances = np.linspace(max(params.inner_ratio + 0.025, 0.16) * r, params.outer_ratio * r, 180)
    half_width = max(2, int(r * 0.012))
    offsets = np.arange(-half_width, half_width + 1)
    xs = np.rint(cx + distances[:, None] * np.cos(rad) + offsets * np.sin(rad)).astype(int)
    ys = np.rint(cy - distances[:, None] * np.sin(rad) + offsets * np.cos(rad)).astype(int)
    valid = (xs >= 0) & (xs < mask.shape[1]) & (ys >= 0) & (ys < mask.shape[0])
    values = np.zeros_like(xs, dtype=bool)
    values[valid] = mask[ys[valid], xs[valid]] > 0
    # 窄带至少 20% 为前景时算命中；support 是径向位置命中的比例。
    hits = values.mean(axis=1) >= 0.20
    support = float(hits.mean())
    # 用命中距离的 95 分位数估计指针延伸长度，减小孤立远处像素的影响。
    extent = float(np.percentile(distances[hits], 95) / r) if hits.any() else 0.0
    return support, extent


def detect_pointer(stages, cal, params):
    # HoughLinesP 提供候选线段；是否为指针还要结合圆心和两侧前景证据判断。
    cx, cy, r = cal.geometry(stages["05_roi"].shape)
    lines = cv2.HoughLinesP(stages["06_edges"], 1, np.pi / 720,
                            threshold=max(15, int(0.12 * r)),
                            minLineLength=max(10, int(params.min_line_ratio * r)),
                            maxLineGap=max(2, int(params.max_gap_ratio * r)))
    if lines is None:
        raise DetectionError("未检测到足够长的直线；检查阈值、指针极性和 ROI")
    hypotheses = []
    for line in lines[:, 0]:
        x1, y1, x2, y2 = map(float, line)
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        if length == 0:
            continue
        # 点到线段所在无限直线的距离；指针轴线应经过旋转中心附近。
        center_dist = abs(dx * (cy - y1) - dy * (cx - x1)) / length
        if center_dist > params.center_tolerance * r:
            continue
        base = math.degrees(math.atan2(-dy, dx)) % 360
        # 先依据图像证据区分正反方向，不用量程把错误的反向强行选进来。
        for side in (base, (base + 180) % 360):
            for angle in np.arange(side - 3, side + 3.001, 0.25):
                support, extent = ray_evidence(stages["05_roi"], cx, cy, r, angle, params)
                # 启发式综合分：支持率为主，辅以延伸长度、线段长度和圆心偏差。
                score = support + 0.10 * extent + 0.03 * min(length / r, 1) - 0.08 * center_dist / r
                hypotheses.append((score, float(angle % 360), support, extent, list(map(int, line))))
    if not hypotheses:
        raise DetectionError("候选直线均未穿过圆心附近，请重新标定圆心")
    hypotheses.sort(reverse=True)
    best = hypotheses[0]
    # 稍宽的平顶取角度平均，避免仅因排序偏向角度较大一端。
    tied = [x for x in hypotheses if best[0] - x[0] < 0.005 and circular_distance(x[1], best[1]) < 3]
    angle = math.degrees(math.atan2(np.mean([math.sin(math.radians(x[1])) for x in tied]),
                                   np.mean([math.cos(math.radians(x[1])) for x in tied]))) % 360
    support, extent = ray_evidence(stages["05_roi"], cx, cy, r, angle, params)
    if support < params.min_ray_support or extent < 0.45:
        raise DetectionError("指针方向的前景支持不足，拒绝输出读数")
    # 方向明显不同但得分接近时拒识，避免在多指针或强干扰中强行选一个。
    rivals = [x for x in hypotheses if circular_distance(x[1], angle) > 15]
    if rivals and best[0] - rivals[0][0] < 0.10:
        raise DetectionError("存在强度相近的多个指针方向，请人工复核")
    return angle, support, extent, best[4], lines[:, 0]


def save_heatmap(path, acc, rhos, thetas):
    """绘制票数热图，标注全局最高峰；并列峰只标第一个并注明数量。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(7.8, 4.0), constrained_layout=True)
    # imshow 的 extent 描述格子边界，外扩半格让星标准确落在数据格中心。
    theta_step = float(thetas[1] - thetas[0]) if len(thetas) > 1 else 1.0
    rho_step = float(rhos[1] - rhos[0]) if len(rhos) > 1 else 1.0
    im = ax.imshow(np.log1p(acc), origin="lower", aspect="auto", cmap="magma",
                   interpolation="nearest",
                   extent=[thetas[0] - theta_step / 2, thetas[-1] + theta_step / 2,
                           rhos[0] - rho_step / 2, rhos[-1] + rho_step / 2])
    ax.set(xlabel="Normal angle (degrees, image coordinates)", ylabel="rho (pixels)",
           title="Standard Hough accumulator | log(1 + votes)")
    # 峰值必须从原始票数取；log1p 只用于显示，最高票数也不等于目标指针。
    peak_row, peak_col = np.unravel_index(np.argmax(acc), acc.shape)
    votes = int(acc[peak_row, peak_col])
    if votes > 0:
        theta, rho = float(thetas[peak_col]), float(rhos[peak_row])
        tied = int(np.count_nonzero(acc == votes))
        ax.scatter([theta], [rho], marker="*", s=145, c="cyan",
                   edgecolors="black", linewidths=0.7, zorder=5)
        ax.axvline(theta, color="cyan", linestyle="--", linewidth=0.65, alpha=0.6)
        ax.axhline(rho, color="cyan", linestyle="--", linewidth=0.65, alpha=0.6)
        label = f"Global max: {votes} votes\nNormal angle: {theta:g} deg\nrho: {rho:g} px"
        if tied > 1:
            label += f"\n{tied} tied maxima; first marked"
        # 文本放到峰值对面的角落，尽量避免遮挡峰值及其邻域。
        text_x = 0.98 if theta < (thetas[0] + thetas[-1]) / 2 else 0.02
        text_y = 0.96 if rho < (rhos[0] + rhos[-1]) / 2 else 0.04
        ax.annotate(label, xy=(theta, rho), xytext=(text_x, text_y),
                    textcoords="axes fraction", fontsize=8, color="white",
                    ha="right" if text_x > 0.5 else "left",
                    va="top" if text_y > 0.5 else "bottom",
                    bbox=dict(boxstyle="round,pad=0.4", fc="black", ec="cyan", alpha=0.85),
                    arrowprops=dict(arrowstyle="->", color="cyan", lw=1.0), zorder=6)
    else:
        ax.text(0.5, 0.5, "No votes: no peak", transform=ax.transAxes,
                ha="center", va="center", color="white")
    fig.colorbar(im, ax=ax, label="log(1 + votes)")
    fig.savefig(path, dpi=160)
    plt.close(fig)


def analyze(image_path, calibration, out_dir, params=None, manual_value=None, use_auto_circle=False):
    # 单图主流程：校验 → 可选圆修正 → 过程导出 → 指针检测 → 读数与误差。
    params = params or Params()
    params.validate()
    calibration.validate()
    if manual_value is not None and not math.isfinite(manual_value):
        raise ValueError("人工读数必须为有限数值")
    out = Path(out_dir)
    # 必须在清理和写入之前检查；resolve 同时识别相对路径和符号链接。
    source = Path(image_path).resolve()
    if any((out / name).resolve() == source for name in OUTPUT_FILES):
        raise ValueError("输出文件将覆盖输入图片，请选择独立的结果目录")
    out.mkdir(parents=True, exist_ok=True)
    # 同目录重复运行时，避免失败后还留下上次成功的结果图。
    for stale in OUTPUT_FILES:
        (out / stale).unlink(missing_ok=True)
    original = read_image(image_path)
    # 在可能拒识的步骤之前保存输入元数据，人工参考值不依赖识别成功与否。
    result = {"image": str(Path(image_path)), "status": "failed", "calibration": asdict(calibration),
              "parameters": asdict(params), "unit": calibration.unit,
              "original_size": [original.shape[1], original.shape[0]], "auto_circle": use_auto_circle}
    if manual_value is not None:
        result["manual_value"] = manual_value
    if use_auto_circle:
        # 在缩小图上找圆；参数为归一化值，与后续处理尺寸一致。
        h, w = original.shape[:2]
        s = min(1, params.max_size / max(h, w))
        small = cv2.resize(original, (round(w * s), round(h * s)))
        try:
            calibration = auto_circle(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), calibration)
        except DetectionError as exc:
            result["error"] = str(exc)
            write_json(out / "result.json", result)
            return result
    image, stages, threshold = preprocess(original, calibration, params)
    save_image(out / "00_input.png", image)
    for name, arr in stages.items():
        save_image(out / f"{name}.png", arr)
    acc, rhos, thetas = hough_accumulator(stages["06_edges"])
    # 保存原始投票矩阵，可用于重绘热图而不必重新运行识别算法。
    np.savez_compressed(out / "hough_accumulator.npz", accumulator=acc, rho=rhos, theta=thetas)
    save_heatmap(out / "07_hough_accumulator.png", acc, rhos, thetas)
    result.update(calibration=asdict(calibration), otsu_or_fixed_threshold=threshold,
                  processed_size=[image.shape[1], image.shape[0]])
    try:
        angle, support, extent, line, all_lines = detect_pointer(stages, calibration, params)
        value, delta, snapped = angle_to_value(angle, calibration, params.endpoint_tolerance)
    except DetectionError as exc:
        # 拒识时保留错误和已有过程文件，不生成可能误导使用者的最终读数图。
        result["error"] = str(exc)
        write_json(out / "result.json", result)
        return result
    cx, cy, r = calibration.geometry(image.shape)
    candidates = image.copy()
    for ln in all_lines:
        x1, y1, x2, y2 = map(int, ln)
        cv2.line(candidates, (x1, y1), (x2, y2), (0, 180, 255), 1, cv2.LINE_AA)
    save_image(out / "08_hough_candidates.png", candidates)
    overlay = image.copy()
    c = (round(cx), round(cy))
    tip = (round(cx + extent * r * math.cos(math.radians(angle))),
           round(cy - extent * r * math.sin(math.radians(angle))))
    cv2.circle(overlay, c, round(r), (180, 140, 40), 2, cv2.LINE_AA)
    cv2.arrowedLine(overlay, c, tip, (0, 0, 230), 3, cv2.LINE_AA, tipLength=0.07)
    cv2.circle(overlay, c, 5, (30, 160, 30), -1)
    # 英文标注避免 OpenCV 内置字体无法绘制中文；完整单位保存在 JSON / GUI。
    display_unit = calibration.unit if calibration.unit.isascii() else "[unit in JSON]"
    cv2.rectangle(overlay, (0, 0), (overlay.shape[1], 67), (250, 250, 250), -1)
    cv2.putText(overlay, f"Reading: {value:.4f} {display_unit}", (15, 27), cv2.FONT_HERSHEY_SIMPLEX,
                0.70, (10, 10, 10), 2, cv2.LINE_AA)
    cv2.putText(overlay, f"Angle: {angle:.2f} deg | support: {support:.3f}", (15, 53),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (50, 50, 50), 1, cv2.LINE_AA)
    save_image(out / "09_result.png", overlay)
    result.update(status="ok", angle_deg=angle, reading=value, unit=calibration.unit,
                  arc_delta_deg=delta, ray_support=support, needle_extent=extent,
                  selected_hough_line=line, endpoint_snapped=snapped,
                  warnings=["仅依据图像启发式评分；ray_support 不是正确概率。"])
    if snapped:
        result["warnings"].append("角度在量程端点容差内，已吸附到端点，请复核原图。")
    if use_auto_circle:
        result["warnings"].append("霍夫圆结果应人工复核；自动圆定位不识别刻度值或纠正相机旋转。")
    if manual_value is not None:
        # 人工参考值已在前面保存；只有识别成功才有条件计算误差。
        # 绝对误差保留原单位；参考值为 0 时，相对误差无定义，保存为 null。
        error = value - manual_value
        result.update(manual_value=manual_value, signed_error=error, absolute_error=abs(error),
                      relative_error_pct=None if manual_value == 0 else abs(error / manual_value) * 100,
                      full_scale_error_pct=abs(error) / (calibration.max_value - calibration.min_value) * 100)
    write_json(out / "result.json", result)
    return result
