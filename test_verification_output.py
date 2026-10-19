"""验证目录隔离及实验归档保护；不改变识别算法的预期。"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import algorithm_verify


class VerificationOutputTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / "project"
        self.source.mkdir()
        for name in ("demo", "experiments", ".docs", ".git"):
            (self.source / name).mkdir()
        self.sentinel = self.source / "demo" / "original.txt"
        self.sentinel.write_bytes(b"original-experiment")
        override = patch.object(algorithm_verify, "__file__", str(self.source / "algorithm_verify.py"))
        override.start()
        self.addCleanup(override.stop)

    def test_default_runs_are_independent_and_preserve_old_results(self):
        first = algorithm_verify.verification_directory()
        (first / "verification.json").write_bytes(b"previous-result")
        second = algorithm_verify.verification_directory()
        self.assertNotEqual(first, second)
        self.assertTrue(second.is_relative_to(self.source / "outputs" / "verification"))
        self.assertEqual((first / "verification.json").read_bytes(), b"previous-result")
        self.assertEqual(self.sentinel.read_bytes(), b"original-experiment")

    def test_protected_directories_and_nonempty_output_are_rejected(self):
        for target in (self.source, self.root, self.source / "demo" / "new",
                       self.source / "experiments", self.source / ".docs" / "new", self.source / ".git" / "new"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                algorithm_verify.verification_directory(target)
        out = self.root / "used-output"
        out.mkdir()
        (out / "verification.json").write_bytes(b"preserve")
        with self.assertRaises(ValueError):
            algorithm_verify.verification_directory(out)
        self.assertEqual((out / "verification.json").read_bytes(), b"preserve")
        self.assertEqual(self.sentinel.read_bytes(), b"original-experiment")

    def test_links_cannot_redirect_output_into_archives(self):
        alias = self.root / "alias"
        try:
            alias.symlink_to(self.source / "demo", target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("Directory symlinks unavailable")
        with self.assertRaises(ValueError):
            algorithm_verify.verification_directory(alias / "new")
        out = self.root / "prelinked-output"
        out.mkdir()
        (out / "demo").symlink_to(self.source / "demo", target_is_directory=True)
        with self.assertRaises(ValueError):
            algorithm_verify.verification_directory(out)
        self.assertEqual(self.sentinel.read_bytes(), b"original-experiment")


class VerificationCLITests(unittest.TestCase):
    def test_actual_cli_generates_ten_samples_in_selected_new_directory(self):
        script = Path(algorithm_verify.__file__).resolve()
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "verification"
            result = subprocess.run([sys.executable, str(script), "--out", str(out)],
                                    cwd=temporary, capture_output=True, text=True,
                                    encoding="utf-8", timeout=180)
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads((out / "verification.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["demo_count"], 10)
            self.assertEqual(summary["successful"], 10)
            self.assertEqual(summary["boundary_failures"], 0)
            self.assertEqual(summary["evidence_type"], "synthetic_only_not_real_photo_accuracy")
            self.assertEqual(len(list((out / "demo/demo_image/images").glob("*.png"))), 10)
            self.assertEqual(len(list((out / "demo/demo_outputs").glob("*/result.json"))), 10)


if __name__ == "__main__":
    unittest.main()
