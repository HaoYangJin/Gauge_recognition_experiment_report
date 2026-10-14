"""确定性合成仪表，用于流程验证，不代表真实照片识别性能。"""
import csv
import math
from pathlib import Path

import cv2
import numpy as np

from core import Calibration, save_image


def draw_gauge(value, cal=None, noise=0, blur=0, gradient=False, needle=True, light=False, size=720):
    # value 是绘图时已知的真值；生成器用于验证流程，不模拟所有真实仪表缺陷。
    cal = cal or Calibration()
    bg, fg = ((28, 225) if light else (246, 28))
    im = np.full((size, size, 3), bg, np.uint8)
    cx, cy, r = cal.geometry(im.shape)
    c = (round(cx), round(cy))
    def point(angle, ratio):
        # 将角度和半径比例转成图像坐标；图像 y 轴向下，所以正弦项取负。
        rad = math.radians(angle)
        return round(cx + r * ratio * math.cos(rad)), round(cy - r * ratio * math.sin(rad))
    def direction_at(t):
        # t 是量程内的位置比例，沿标定的顺/逆时针方向换成角度。
        return (cal.start_angle + (-1 if cal.direction == "cw" else 1) * cal.span * t) % 360
    cv2.circle(im, c, round(r), (fg,) * 3, 3, cv2.LINE_AA)
    for i in range(41):
        # 绘制 40 个等角度小区间，每 5 个间隔显示长刻度和数字。
        theta = direction_at(i / 40)
        cv2.line(im, point(theta, 0.87 if i % 5 == 0 else 0.92), point(theta, 0.98),
                 (fg,) * 3, 3 if i % 5 == 0 else 1, cv2.LINE_AA)
        if i % 5 == 0:
            label = f"{cal.min_value + i / 40 * (cal.max_value - cal.min_value):.1f}"
            x, y = point(theta, 0.79)
            cv2.putText(im, label, (x - 16, y + 5), cv2.FONT_HERSHEY_SIMPLEX,
                        0.45, (fg,) * 3, 1, cv2.LINE_AA)
    cv2.putText(im, cal.unit if cal.unit.isascii() else "unit", (c[0] - 22, c[1] + 100),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (fg,) * 3, 1, cv2.LINE_AA)
    if needle:
        # 针尖长、针尾短，便于验证“同一直线两端中哪端是针尖”的判断。
        angle = direction_at((value - cal.min_value) / (cal.max_value - cal.min_value))
        tip, tail = point(angle, 0.72), point(angle + 180, 0.18)
        cv2.line(im, tail, tip, (fg,) * 3, 7, cv2.LINE_AA)
        cv2.circle(im, c, round(0.065 * r), (fg,) * 3, -1, cv2.LINE_AA)
    cv2.putText(im, "SYNTHETIC DEMO - NOT A REAL PHOTO", (45, size - 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (fg,) * 3, 1, cv2.LINE_AA)
    im = im.astype(np.float32)
    # 先在浮点图像上叠加扰动，再裁剪回 8 位范围，避免整数溢出回绕。
    if gradient:
        im -= np.linspace(0, 75, size)[None, :, None]
    if noise:
        # 固定随机种子，让相同参数每次生成相同噪声，便于复现误差。
        im += np.random.default_rng(20261012).normal(0, noise, im.shape)
    im = np.clip(im, 0, 255).astype(np.uint8)
    if blur:
        im = cv2.GaussianBlur(im, (blur, blur), 0)
    return im


def make_demo(out_dir):
    # 同步输出图片、配套标定和真值表，避免验证时把识别值误当成参考值。
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cal = Calibration()
    cal.save(out / "calibration.json")
    cases = [("01_zero", 0, {}), ("02_low", 0.2, {}), ("03_midlow", 0.64, {}),
             ("04_middle", 0.8, {}), ("05_high", 1.2, {}), ("06_full", 1.6, {}),
             ("07_noise", 1.12, {"noise": 12}), ("08_blur", 0.32, {"blur": 7}),
             ("09_gradient", 0.96, {"gradient": True}), ("10_wrap", 1.44, {})]
    with (out / "references.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["filename", "manual_value", "source"])
        writer.writeheader()
        for name, value, opts in cases:
            save_image(out / "images" / f"{name}.png", draw_gauge(value, cal, **opts))
            # 兼容人工参考值 CSV 的字段名，但明确标注来源是合成真值。
            writer.writerow({"filename": f"{name}.png", "manual_value": value,
                             "source": "synthetic_ground_truth_not_manual"})
    return out


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="demo/demo_image")
    print(make_demo(parser.parse_args().out))
