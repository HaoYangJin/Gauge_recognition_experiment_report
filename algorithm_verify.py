"""复现合成验证及关键失败边界。只用标准库 unittest。"""
import argparse
import json
import math
import platform
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np
import PIL
import matplotlib

from core import (Calibration, DetectionError, Params, analyze, angle_to_value,
                  auto_circle, detect_pointer, preprocess, save_image, write_json)
from demo_gauge_simulator import draw_gauge, make_demo
from gauge_reader import batch_read


class BoundaryTests(unittest.TestCase):
    # 边界测试检查计算和拒识规则；不等于真实照片数据集上的准确率评价。
    def test_clockwise_angles(self):
        cal = Calibration()
        for angle, value in [(225, 0), (90, 0.8), (315, 1.6), (0, 4/3)]:
            self.assertAlmostEqual(angle_to_value(angle, cal)[0], value)

    def test_cross_zero_both_directions(self):
        # 使用跨 0° 的量程，检查取模运算是否同时适用于两种旋转方向。
        ccw = replace(Calibration(), start_angle=300, end_angle=60, direction="ccw", max_value=100)
        cw = replace(ccw, start_angle=60, end_angle=300, direction="cw")
        self.assertEqual(angle_to_value(0, ccw)[0], 50)
        self.assertEqual(angle_to_value(0, cw)[0], 50)

    def test_out_of_range_and_endpoint_tolerance(self):
        with self.assertRaises(DetectionError):
            angle_to_value(270, Calibration())
        value, _, snapped = angle_to_value(225.8, Calibration())
        self.assertEqual(value, 0)
        self.assertTrue(snapped)

    def test_invalid_calibration(self):
        for cal in [replace(Calibration(), end_angle=225), replace(Calibration(), radius=-1),
                    replace(Calibration(), max_value=0), replace(Calibration(), center_x=float("nan"))]:
            with self.assertRaises(ValueError):
                cal.validate()

    def test_no_needle(self):
        cal, params = Calibration(), Params()
        _, stages, _ = preprocess(draw_gauge(0, needle=False), cal, params)
        with self.assertRaises(DetectionError):
            detect_pointer(stages, cal, params)

    def test_opposite_directions_ambiguous(self):
        cal, params = Calibration(), Params()
        im = draw_gauge(0.8)
        # 竖直指针加上等长下半轴，制造方向不可辨识的双向线。
        cv2.line(im, (360, 360), (360, 576), (28, 28, 28), 7, cv2.LINE_AA)
        _, stages, _ = preprocess(im, cal, params)
        with self.assertRaises(DetectionError):
            detect_pointer(stages, cal, params)

    def test_light_pointer(self):
        cal, params = Calibration(), Params(polarity="light")
        _, stages, _ = preprocess(draw_gauge(0.64, light=True), cal, params)
        angle, *_ = detect_pointer(stages, cal, params)
        self.assertLess(abs(angle_to_value(angle, cal)[0] - 0.64), 0.016)

    def test_counterclockwise_image(self):
        cal = replace(Calibration(), start_angle=315, end_angle=225, direction="ccw")
        _, stages, _ = preprocess(draw_gauge(0.4, cal), cal, Params())
        angle, *_ = detect_pointer(stages, cal, Params())
        self.assertLess(abs(angle_to_value(angle, cal)[0] - 0.4), 0.016)

    def test_auto_circle(self):
        gray = cv2.cvtColor(draw_gauge(0.8), cv2.COLOR_BGR2GRAY)
        cal = auto_circle(gray, Calibration())
        x, y, r = cal.geometry(gray.shape)
        self.assertLess(math.hypot(x-360, y-360), 12)
        self.assertLess(abs(r-300), 15)

    def test_failure_removes_stale_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_image(root / "blank.png", np.full((720, 720, 3), 255, np.uint8))
            (root / "09_result.png").write_bytes(b"old-result")
            result = analyze(root / "blank.png", Calibration(), root)
            self.assertEqual(result["status"], "failed")
            self.assertFalse((root / "09_result.png").exists())

    def test_batch_continues_after_corrupt_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "inputs"
            source.mkdir()
            (source / "broken.png").write_bytes(b"not-an-image")
            save_image(source / "valid.png", draw_gauge(0.8))
            result = batch_read(source, Calibration(), root / "outputs")
            self.assertEqual([x["status"] for x in result], ["failed", "ok"])

    def test_rejection_keeps_manual_value_without_fake_error_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_image(root / "blank.png", np.full((720, 720, 3), 255, np.uint8))
            for manual in (0.0, 0.8):
                result = analyze(root / "blank.png", Calibration(), root / str(manual),
                                 manual_value=manual)
                saved = json.loads((root / str(manual) / "result.json").read_text("utf-8"))
                self.assertEqual(result["status"], "failed")
                self.assertEqual(saved["manual_value"], manual)
                self.assertNotIn("reading", saved)
                self.assertNotIn("absolute_error", saved)

    def test_input_with_output_name_is_never_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "09_result.png"
            source.write_bytes(b"original-photo")
            with self.assertRaises(ValueError):
                analyze(source, Calibration(), Path(tmp))
            self.assertEqual(source.read_bytes(), b"original-photo")

    def test_early_rejection_removes_old_intermediate_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, out = root / "blank.png", root / "out"
            save_image(source, np.full((720, 720, 3), 255, np.uint8))
            out.mkdir()
            for name in ("00_input.png", "07_hough_accumulator.png", "hough_accumulator.npz"):
                (out / name).write_bytes(b"old")
            result = analyze(source, Calibration(), out, use_auto_circle=True)
            self.assertEqual(result["status"], "failed")
            self.assertFalse((out / "00_input.png").exists())
            self.assertFalse((out / "hough_accumulator.npz").exists())

    def test_auto_circle_rejection_keeps_manual_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_image(root / "blank.png", np.full((720, 720, 3), 255, np.uint8))
            result = analyze(root / "blank.png", Calibration(), root / "out",
                             manual_value=0.8, use_auto_circle=True)
            saved = json.loads((root / "out" / "result.json").read_text("utf-8"))
            self.assertEqual(result["status"], "failed")
            self.assertEqual(saved["manual_value"], 0.8)
            self.assertIn("error", saved)


def verification_directory(destination=None):
    """验证写入独立新目录，避免覆盖源代码和已归档实验。"""
    source = Path(__file__).resolve().parent
    target = (Path(destination) if destination is not None
              else source / "outputs" / "verification").resolve()
    protected = [source / name for name in ("demo", "experiments", ".docs", ".git")]
    if target == source or target in source.parents or any(
            target == p.resolve() or target.is_relative_to(p.resolve())
            or p.resolve().is_relative_to(target) for p in protected):
        raise ValueError("验证输出不能位于项目根目录、其祖先或实验归档/Git 目录中")
    if destination is None:
        target.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix="run-", dir=target))
    # 新目录不包含可将 demo/summary 等子路径重定向到原始数据的符号链接。
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ValueError("--out 必须是不存在或为空的目录；请为每次验证使用新目录")
    target.mkdir(parents=True, exist_ok=True)
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="新的或空的验证目录；默认在 outputs/verification 下创建独立目录")
    args = parser.parse_args(argv)
    try:
        root = verification_directory(args.out)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    demos = make_demo(root / "demo" / "demo_image")
    results = batch_read(demos / "images", Calibration(), root / "demo" / "demo_outputs",
                         references=demos / "references.csv")
    # 误差只在输出读数的样例上计算，但保留总数；通过条件要求全部样例成功。
    successes = [r for r in results if r["status"] == "ok"]
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(BoundaryTests)
    outcome = unittest.TextTestRunner(verbosity=2).run(suite)
    # 环境版本是本次验证的快照，不能当作之后任意时刻的当前安装状态。
    summary = {
        "output_directory": str(root),
        "evidence_type": "synthetic_only_not_real_photo_accuracy",
        "seed": 20261012, "demo_count": len(results), "successful": len(successes),
        "mean_absolute_error": float(np.mean([r["absolute_error"] for r in successes])) if successes else None,
        "max_full_scale_error_pct": max((r["full_scale_error_pct"] for r in successes), default=None),
        "boundary_tests": outcome.testsRun,
        "boundary_failures": len(outcome.failures) + len(outcome.errors),
        "environment": {"python": platform.python_version(), "opencv": cv2.__version__,
                        "numpy": np.__version__, "pillow": PIL.__version__, "matplotlib": matplotlib.__version__},
    }
    write_json(root / "verification.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    # 通过要求：边界测试无失败、全部合成样例有读数、最大满量程误差小于 1%。
    passed = (outcome.wasSuccessful() and len(successes) == len(results)
              and summary["max_full_scale_error_pct"] < 1.0)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
