import sys
import subprocess
import unittest
from unittest.mock import patch

from pc import deploy


class DeployTests(unittest.TestCase):
    def test_explicit_s3_profile_is_written_after_files_and_before_reset(self):
        with patch.object(sys, "argv", ["deploy", "--port", "auto", "--board",
                                       "waveshare-s3-amoled-164"]), \
                patch.object(deploy.subprocess, "run") as run:
            deploy.main()
        preflight, transfer, reset = run.call_args_list
        self.assertIn("from amoled_qspi import Bus", preflight.args[0][-1])
        self.assertIn("board = 'waveshare-s3-amoled-164'", preflight.args[0][-1])
        command = transfer.args[0]
        self.assertIn(":co5300.py", command)
        self.assertEqual(command[-3:], ["+", "exec", "with open('openbuddy-board.txt', 'w') as f: f.write('waveshare-s3-amoled-164')"])
        self.assertEqual(reset.args[0][-1], "reset")

    def test_update_without_board_preserves_current_profile(self):
        with patch.object(sys, "argv", ["deploy", "--port", "auto"]), \
                patch.object(deploy.subprocess, "run") as run:
            deploy.main()
        preflight, transfer, reset = run.call_args_list
        self.assertNotIn("exec", transfer.args[0])
        script = preflight.args[0][-1]
        self.assertIn("board = None", script)
        self.assertIn("openbuddy-board.txt", script)

    def test_v2_profile_is_written_and_requires_versioned_native_api(self):
        with patch.object(sys, "argv", ["deploy", "--port", "auto", "--board",
                                       "waveshare-s3-amoled-164-v2"]), \
                patch.object(deploy.subprocess, "run") as run:
            deploy.main()
        preflight, transfer, reset = run.call_args_list
        self.assertIn("Bus, API_VERSION", preflight.args[0][-1])
        self.assertIn("API_VERSION < 2", preflight.args[0][-1])
        self.assertIn("waveshare-s3-amoled-164-v2", transfer.args[0][-1])
        self.assertEqual(reset.args[0][-1], "reset")

    def test_missing_native_module_prevents_all_writes_and_still_resets(self):
        for board in ([], ["--board", "waveshare-s3-amoled-164"]):
            with self.subTest(board=board), \
                    patch.object(sys, "argv", ["deploy", "--port", "auto"] + board), \
                    patch.object(deploy.subprocess, "run", side_effect=[
                        subprocess.CalledProcessError(1, "preflight"), None]) as run, \
                    patch.object(sys, "stderr"):
                with self.assertRaises(SystemExit) as error:
                    deploy.main()
                self.assertEqual(error.exception.code, 1)
                self.assertEqual(len(run.call_args_list), 2)
                self.assertNotIn("fs", run.call_args_list[0].args[0])
                self.assertEqual(run.call_args_list[-1].args[0][-1], "reset")

    def test_explicit_c6_does_not_require_native_module(self):
        with patch.object(sys, "argv", ["deploy", "--port", "auto", "--board",
                                       "waveshare-c6-lcd-147"]), \
                patch.object(deploy.subprocess, "run") as run:
            deploy.main()
        transfer, reset = run.call_args_list
        self.assertIn("fs", transfer.args[0])
        self.assertEqual(reset.args[0][-1], "reset")

    def test_preflight_checks_only_selected_or_persisted_s3_profile(self):
        import builtins
        import io
        from unittest.mock import Mock

        for selected, persisted, requires_native in (
                ("waveshare-s3-amoled-164", None, True),
                ("waveshare-s3-amoled-164-v2", None, True),
                (None, "waveshare-s3-amoled-164\n", True),
                (None, "waveshare-s3-amoled-164-v2\n", True),
                (None, "waveshare-c6-lcd-147\n", False),
                (None, None, False)):
            argv = ["deploy", "--port", "auto"]
            if selected:
                argv.extend(["--board", selected])
            with self.subTest(selected=selected, persisted=persisted), \
                    patch.object(sys, "argv", argv), \
                    patch.object(deploy.subprocess, "run") as run:
                deploy.main()
                script = run.call_args_list[0].args[0][-1]
                importer = Mock(side_effect=ImportError("Missing native module"))
                opener = (Mock(side_effect=OSError("No saved profile")) if persisted is None
                          else Mock(return_value=io.StringIO(persisted)))
                environment = {"__builtins__": dict(vars(builtins), __import__=importer,
                                                    open=opener)}
                if requires_native:
                    with self.assertRaisesRegex(ImportError, "Install.*native amoled_qspi"):
                        exec(script, environment)
                    importer.assert_called_once()
                else:
                    exec(script, environment)
                    self.assertEqual([item.args[0] for item in importer.call_args_list],
                                     ["openbuddy_build"] if persisted is None else [])

    def test_frozen_default_and_native_api_are_checked_without_instantiating_bus(self):
        import builtins
        from types import SimpleNamespace
        from unittest.mock import Mock

        with patch.object(sys, "argv", ["deploy", "--port", "auto"]), \
                patch.object(deploy.subprocess, "run") as run:
            deploy.main()
        script = run.call_args_list[0].args[0][-1]
        for version in (1, 2):
            bus = Mock(side_effect=AssertionError("Preflight must not initialize hardware"))
            modules = {
                "openbuddy_build": SimpleNamespace(BOARD_MODEL="waveshare-s3-amoled-164-v2"),
                "amoled_qspi": SimpleNamespace(Bus=bus, API_VERSION=version),
            }
            importer = Mock(side_effect=lambda name, *args: modules[name])
            environment = {"__builtins__": dict(vars(builtins), __import__=importer,
                                                open=Mock(side_effect=OSError("No saved profile")))}
            if version == 1:
                with self.assertRaisesRegex(ImportError, "API_VERSION >= 2"):
                    exec(script, environment)
            else:
                exec(script, environment)
                self.assertEqual(environment["board"], "waveshare-s3-amoled-164-v2")
            bus.assert_not_called()
