"""逐图标定批处理的匹配、失败隔离、CLI 和 GUI 路径测试。"""
import contextlib
import io
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import cv2

from core import Calibration, Params, save_image, write_json
from demo_gauge_simulator import draw_gauge
from gauge_reader import batch_read, main


class BatchTests(unittest.TestCase):
    def setUp(self):
        # 每个测试使用独立临时目录，不读写使用者的原图、标定或实际结果。
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.images = self.root / "图片"
        self.cals = self.root / "calibration.json"
        self.out = self.root / "结果"
        self.images.mkdir()
        self.cals.mkdir()

    def image(self, name):
        # 匹配测试只需文件名；完整识别测试会另行写入真正的图像像素。
        (self.images / name).touch()

    def cal(self, name, **changes):
        replace(Calibration(), **changes).save(self.cals / name)

    def run_batch(self, **kwargs):
        return batch_read(self.images, None, self.out, calibration_dir=self.cals, **kwargs)

    @staticmethod
    def fake_analyze(path, cal, dest, params, manual, circle):
        # 用标定量程和处理参数构造可预测返回值，隔离图像算法对调度测试的影响。
        return {"image": str(path), "status": "ok", "reading": cal.max_value,
                "unit": cal.unit, "polarity": params.polarity}

    def test_output_cannot_be_input_or_ancestor(self):
        self.image("a.png")
        for destination in (self.images, self.root):
            with self.assertRaises(ValueError):
                batch_read(self.images, Calibration(), destination)
        self.assertTrue((self.images / "a.png").is_file())

    def test_invalid_reference_csv_has_clear_error(self):
        self.image("a.png")
        refs = self.root / "bad.csv"
        for content in ("manual_value\n1\n", "filename,manual_value\na.png\n", "manual_value,filename\n0.8\n"):
            refs.write_text(content, encoding="utf-8")
            with self.assertRaises(ValueError):
                self.run_batch(references=refs)

    def test_each_image_uses_its_own_calibration_and_summary(self):
        for name, value in (("甲", 10), ("乙", 20)):
            self.image(name + ".png")
            self.cal(name + ".json", max_value=value)
        with patch("gauge_reader.analyze", side_effect=self.fake_analyze):
            results = self.run_batch()
        self.assertEqual({r["reading"] for r in results}, {10, 20})
        for r in results:
            self.assertEqual(Path(r["calibration_file"]).stem, Path(r["filename"]).stem)
            saved = json.loads((self.out / r["filename"] / "result.json").read_text("utf-8"))
            self.assertEqual(saved["calibration_file"], r["calibration_file"])
        self.assertEqual(len(json.loads((self.out / "summary.json").read_text("utf-8"))), 2)
        self.assertIn("calibration_file", (self.out / "summary.csv").read_text("utf-8-sig"))

    def test_unwritable_single_result_does_not_abort_batch(self):
        import csv
        for name in ("a", "b"):
            self.image(name + ".png")
            self.cal(name + ".json")
        self.out.mkdir()
        # 用普通文件占据预期的结果子目录，复现真实路径冲突而不是 mock。
        conflict = self.out / "a.png"
        conflict.write_text("keep this file", encoding="utf-8")
        refs = self.root / "refs.csv"
        refs.write_text("filename,manual_value\na.png,0\nb.png,0.8\n", encoding="utf-8")
        with patch("gauge_reader.analyze", side_effect=self.fake_analyze):
            results = self.run_batch(references=refs)
        self.assertEqual([r["status"] for r in results], ["failed", "ok"])
        self.assertEqual(results[0]["manual_value"], 0)
        self.assertIn("write_error", results[0])
        self.assertEqual(conflict.read_text("utf-8"), "keep this file")
        saved = json.loads((self.out / "summary.json").read_text("utf-8"))
        self.assertEqual(saved[0]["manual_value"], 0)
        with (self.out / "summary.csv").open(encoding="utf-8-sig", newline="") as file:
            rows = list(csv.DictReader(file))
        self.assertEqual(len(rows), 2)
        self.assertIn("write_error", rows[0])
        self.assertTrue((self.out / "b.png" / "result.json").is_file())

    def test_json_write_permission_error_preserves_result_in_summary(self):
        for name in ("a", "b"):
            self.image(name + ".png")
            self.cal(name + ".json")

        def selective_write(path, data):
            if Path(path) == self.out / "a.png" / "result.json":
                raise PermissionError("test permission denied")
            write_json(path, data)

        with patch("gauge_reader.analyze", side_effect=self.fake_analyze), \
                patch("gauge_reader.write_json", side_effect=selective_write):
            results = self.run_batch()
        self.assertEqual([r["status"] for r in results], ["failed", "ok"])
        self.assertIn("test permission denied", results[0]["write_error"])
        self.assertEqual(len(json.loads((self.out / "summary.json").read_text("utf-8"))), 2)

    def test_missing_calibration_keeps_manual_value_in_failure(self):
        self.image("missing.png")
        refs = self.root / "refs.csv"
        refs.write_text("filename,manual_value\nmissing.png,0.8\n", encoding="utf-8")
        result = self.run_batch(references=refs)[0]
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["manual_value"], 0.8)

    def test_nonfinite_references_are_rejected_before_writing_results(self):
        self.image("a.png")
        self.cal("a.json")
        refs = self.root / "refs.csv"
        for value in ("NaN", "Infinity", "-Infinity"):
            refs.write_text(f"filename,manual_value\na.png,{value}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "有限数值"):
                self.run_batch(references=refs)
        self.assertFalse((self.out / "summary.json").exists())

    def test_missing_and_invalid_calibration_do_not_abort_batch(self):
        for name in ("a", "b", "c", "d"):
            self.image(name + ".png")
        (self.cals / "a.json").write_text("{broken", encoding="utf-8")
        write_json(self.cals / "b.json", {"center_x": "bad"})
        self.cal("d.json")
        with patch("gauge_reader.analyze", side_effect=self.fake_analyze):
            results = self.run_batch()
        self.assertEqual([r["status"] for r in results], ["failed"] * 3 + ["ok"])
        self.assertIn("标定", results[2]["error"])

    def test_null_unit_is_rejected_without_aborting(self):
        for name in ("a", "b"):
            self.image(name + ".png")
            self.cal(name + ".json")
        data = json.loads((self.cals / "a.json").read_text("utf-8"))
        data["unit"] = None
        write_json(self.cals / "a.json", data)
        with patch("gauge_reader.analyze", side_effect=self.fake_analyze):
            results = self.run_batch()
        self.assertEqual([r["status"] for r in results], ["failed", "ok"])

    def test_exact_filename_wins_and_ambiguous_stem_is_rejected(self):
        self.image("same.png")
        self.image("same.jpg")
        self.cal("same.json", max_value=99)
        self.cal("same.png.json", max_value=10)
        with patch("gauge_reader.analyze", side_effect=self.fake_analyze):
            results = self.run_batch()
        self.assertEqual(results[0]["status"], "failed")
        self.assertEqual(results[1]["reading"], 10)

    def test_per_image_params_override_common_defaults(self):
        self.image("light.png")
        self.cal("light.json")
        write_json(self.cals / "light.params.json", {"polarity": "light"})
        with patch("gauge_reader.analyze", side_effect=self.fake_analyze) as analyze:
            r = self.run_batch(params=Params(blur_kernel=7))[0]
        self.assertEqual(r["polarity"], "light")
        self.assertEqual(analyze.call_args.args[3].blur_kernel, 7)

    def test_invalid_per_image_params_fail_only_that_image(self):
        for name in ("a", "b"):
            self.image(name + ".png")
            self.cal(name + ".json")
        write_json(self.cals / "a.params.json", {"polarity": "wrong"})
        with patch("gauge_reader.analyze", side_effect=self.fake_analyze):
            results = self.run_batch()
        self.assertEqual([r["status"] for r in results], ["failed", "ok"])

    def test_missing_calibration_removes_stale_success_image(self):
        self.image("a.png")
        dest = self.out / "a.png"
        dest.mkdir(parents=True)
        (dest / "09_result.png").touch()
        (dest / "00_input.png").touch()
        (dest / "hough_accumulator.npz").touch()
        (dest / "keep.txt").touch()
        self.assertEqual(self.run_batch()[0]["status"], "failed")
        self.assertFalse((dest / "09_result.png").exists())
        self.assertFalse((dest / "00_input.png").exists())
        self.assertFalse((dest / "hough_accumulator.npz").exists())
        self.assertTrue((dest / "keep.txt").exists())

    def test_common_calibration_still_supported_and_references_forwarded(self):
        self.image("a.png")
        refs = self.root / "refs.csv"
        refs.write_text("filename,manual_value\na.png,0.8\n", encoding="utf-8")
        with patch("gauge_reader.analyze", side_effect=self.fake_analyze) as analyze:
            results = batch_read(self.images, Calibration(), self.out,
                                 references=refs, use_auto_circle=True)
        self.assertEqual(results[0]["status"], "ok")
        self.assertEqual(analyze.call_args.args[4:], (0.8, True))

    def test_invalid_folder_or_modes_fail_before_processing(self):
        self.image("a.png")
        for kwargs in ({"calibration_dir": self.root / "absent"}, {}):
            with self.assertRaises(ValueError):
                batch_read(self.images, None, self.out, **kwargs)
        with self.assertRaises(ValueError):
            batch_read(self.images, Calibration(), self.out, calibration_dir=self.cals)

    def test_cli_directory_mode_and_failed_exit_code(self):
        self.image("missing.png")
        args = ["gauge_reader.py", "batch", str(self.images), "--calibration-dir",
                str(self.cals), "--out", str(self.out)]
        with patch("sys.argv", args), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(), 2)
        self.assertTrue((self.out / "summary.csv").exists())

    def test_cli_directory_mode_success_and_common_mode(self):
        self.image("a.png")
        self.cal("a.json")
        for flag, source in (("--calibration-dir", self.cals),
                             ("--calibration", self.cals / "a.json")):
            args = ["gauge_reader.py", "batch", str(self.images), flag,
                    str(source), "--out", str(self.out)]
            with patch("sys.argv", args), contextlib.redirect_stdout(io.StringIO()), \
                    patch("gauge_reader.analyze", side_effect=self.fake_analyze):
                self.assertEqual(main(), 0)

    def test_cli_single_mode_remains_compatible(self):
        self.cal("a.json")
        args = ["gauge_reader.py", "read", "a.png", "--calibration",
                str(self.cals / "a.json"), "--out", str(self.out)]
        with patch("sys.argv", args), contextlib.redirect_stdout(io.StringIO()), \
                patch("gauge_reader.analyze", return_value={"status": "ok"}):
            self.assertEqual(main(), 0)

    def test_cli_rejects_both_calibration_modes(self):
        args = ["gauge_reader.py", "batch", str(self.images), "--calibration-dir",
                str(self.cals), "--calibration", "other.json"]
        with patch("sys.argv", args), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                main()
        self.assertEqual(raised.exception.code, 2)

    def test_analysis_exception_is_saved_and_next_image_runs(self):
        for name in ("a", "b"):
            self.image(name + ".png")
            self.cal(name + ".json")
        with patch("gauge_reader.analyze", side_effect=[OSError("bad image"), {"status": "ok"}]):
            results = self.run_batch()
        self.assertEqual([r["status"] for r in results], ["failed", "ok"])
        self.assertEqual(results[0]["error"], "bad image")

    def test_opencv_exception_is_isolated(self):
        for name in ("a", "b"):
            self.image(name + ".png")
            self.cal(name + ".json")
        with patch("gauge_reader.analyze", side_effect=[cv2.error("bad OpenCV image"), {"status": "ok"}]):
            results = self.run_batch()
        self.assertEqual([r["status"] for r in results], ["failed", "ok"])

    def test_missing_image_folder_and_empty_folder(self):
        for folder in (self.root / "missing", self.images):
            with self.assertRaises(ValueError):
                batch_read(folder, None, self.out, calibration_dir=self.cals)

    def test_real_dark_and_light_images_generate_results(self):
        # 与上面的 mock 测试互补：实际执行预处理、识别和导出，检查完整调用链。
        for name, light in (("dark", False), ("light", True)):
            save_image(self.images / (name + ".png"), draw_gauge(0.8, light=light))
            self.cal(name + ".json")
        write_json(self.cals / "light.params.json", {"polarity": "light"})
        results = self.run_batch()
        for r in results:
            self.assertEqual(r["status"], "ok", r)
            self.assertLess(abs(r["reading"] - 0.8), 0.016)
            self.assertTrue((self.out / r["filename"] / "09_result.png").is_file())

    def test_gui_directory_batch_needs_no_current_calibration(self):
        # 不创建真实窗口，只验证按钮处理函数是否把目录和参数传到后台任务。
        from gui import GaugeApp
        from unittest.mock import Mock
        app = GaugeApp.__new__(GaugeApp)
        app.current_params = Mock(return_value=Params())
        app.use_circle = Mock()
        app.use_circle.get.return_value = False
        app.start_job = Mock()
        with patch("gui.filedialog.askdirectory", side_effect=[str(self.images), str(self.cals), str(self.out)]):
            app.run_batch_calibrations()
        job = app.start_job.call_args.args[0]
        with patch("gui.batch_read", return_value=[]) as batch:
            self.assertEqual(job()[0], "batch")
        self.assertEqual(batch.call_args.kwargs["calibration_dir"], str(self.cals))

    def test_gui_cancel_at_any_directory_does_not_start_job(self):
        from gui import GaugeApp
        from unittest.mock import Mock
        for responses in ([""], [str(self.images), ""],
                          [str(self.images), str(self.cals), ""]):
            app = GaugeApp.__new__(GaugeApp)
            app.start_job = Mock()
            with patch("gui.filedialog.askdirectory", side_effect=responses):
                app.run_batch_calibrations()
            app.start_job.assert_not_called()

    def test_gui_initializes_with_new_batch_button(self):
        # 隐藏窗口做实际控件初始化检查；无桌面环境时跳过这一项。
        import tkinter as tk
        from gui import GaugeApp
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"无可用桌面：{exc}")
        self.addCleanup(root.destroy)
        root.withdraw()
        app = GaugeApp(root)
        root.update_idletasks()
        self.assertIn("批量识别（逐图标定 JSON）", [b.cget("text") for b in app.buttons])
        self.assertLessEqual(root.grid_slaves(row=0, column=1)[0].winfo_reqheight(), 830)


if __name__ == "__main__":
    unittest.main()
