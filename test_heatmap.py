"""霍夫热图最高峰标注测试。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from core import save_heatmap


class HeatmapTests(unittest.TestCase):
    def render(self, acc):
        # 用真实 Matplotlib 渲染，但拦截 annotate 调用以核对标注坐标和文字。
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "heatmap.png"
            fig, ax = plt.subplots()
            with patch("matplotlib.pyplot.subplots", return_value=(fig, ax)), \
                    patch.object(ax, "annotate", wraps=ax.annotate) as annotate:
                save_heatmap(output, acc, np.array([-10, 0, 10]), np.array([0, 45, 90, 135]))
            self.assertGreater(output.stat().st_size, 0)
            return ax, annotate

    def test_peak_annotation_uses_raw_votes_and_correct_coordinates(self):
        # 峰放在非中心且 rho 为负的位置，防止把行列或坐标符号写反。
        acc = np.zeros((3, 4), dtype=np.uint32)
        acc[0, 3] = 149
        ax, annotate = self.render(acc)
        self.assertEqual(annotate.call_args.kwargs["xy"], (135.0, -10.0))
        self.assertIn("149 votes", annotate.call_args.args[0])
        self.assertIn("135", annotate.call_args.args[0])
        self.assertIn("-10", annotate.call_args.args[0])
        self.assertEqual(len(ax.collections), 1)

    def test_tied_peaks_are_explicit_and_first_is_marked(self):
        # 并列时允许只标第一个，但必须告知还有同票数峰值，避免误解为唯一峰。
        acc = np.zeros((3, 4), dtype=np.uint32)
        acc[0, 1] = acc[2, 3] = 8
        _, annotate = self.render(acc)
        self.assertEqual(annotate.call_args.kwargs["xy"], (45.0, -10.0))
        self.assertIn("2 tied", annotate.call_args.args[0])

    def test_empty_accumulator_has_no_false_peak(self):
        # 全零数据仍可渲染，但不能把 argmax 默认返回的首格当成有效峰。
        ax, annotate = self.render(np.zeros((3, 4), dtype=np.uint32))
        annotate.assert_not_called()
        self.assertEqual(len(ax.collections), 0)
        self.assertTrue(any("No votes" in text.get_text() for text in ax.texts))


if __name__ == "__main__":
    unittest.main()
