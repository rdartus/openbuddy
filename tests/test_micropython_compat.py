"""Keep CPython mocks from hiding MicroPython syntax and API regressions."""

import subprocess
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from pc.deploy import FILES
from tools import check_micropython as check


class MicroPythonCompatibilityTests(unittest.TestCase):
    def test_all_deployable_files_pass_actual_micropython_compiler(self):
        paths = [check.ROOT / "device" / name for name in FILES]
        self.assertEqual(check.check_sources(paths), [])

    def test_linter_rejects_host_only_imports_and_methods(self):
        source = "import pathlib\nfrom subprocess import run\nimport os.path\nname.isascii()\n"
        errors = check.lint_source(source, "bad.py", set())
        self.assertEqual(len(errors), 4)
        self.assertIn("bad.py:4: .isascii()", errors[3])
        self.assertEqual(check.lint_source("import machine\nfrom buddy_prompt import Prompt\n",
                                           "ok.py", {"buddy_prompt"}), [])
        failures = check.lint_source("token.isalnum()\ntext.ljust(24)\n", "bad.py", set())
        self.assertTrue(any("bad.py:1: .isalnum()" in error for error in failures))
        self.assertTrue(any("bad.py:2: .ljust()" in error for error in failures))

    def test_micropython_syntax_error_fails_even_if_cpython_accepts_it(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.py"
            path.write_text("match 1:\n    case 1: pass\n", encoding="utf-8")
            errors = check.check_sources([path])
        self.assertTrue(any("mpy-cross" in error for error in errors), errors)

    def test_missing_compiler_fails_closed(self):
        with patch.object(check.metadata, "version", side_effect=check.metadata.PackageNotFoundError):
            with self.assertRaisesRegex(RuntimeError, "mpy-cross is required"):
                check.check_sources([])

    def test_wrong_compiler_version_fails_closed(self):
        with patch.object(check.metadata, "version", return_value="1.30.0"):
            with self.assertRaisesRegex(RuntimeError, "Expected mpy-cross 1.29.0.post2"):
                check.check_sources([])

    def test_compiler_failure_is_not_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "example.py"
            path.write_text("pass\n", encoding="utf-8")

            def failing_runner(*args, **kwargs):
                return subprocess.CompletedProcess(args[0], 1, stderr="broken compiler")

            self.assertIn("broken compiler", check.check_sources([path], runner=failing_runner)[0])
