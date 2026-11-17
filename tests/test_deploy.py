import sys
import subprocess
import unittest
from unittest.mock import patch

from pc import deploy


class DeployTests(unittest.TestCase):
    def test_all_mpremote_processes_have_bounded_timeouts(self):
        with patch.object(sys, "argv", ["deploy", "--port", "auto", "--timeout", "240"]), \
                patch.object(deploy.subprocess, "run") as run:
            deploy.main()
        self.assertEqual([call.kwargs["timeout"] for call in run.call_args_list],
                         [deploy.PREFLIGHT_TIMEOUT, 240, deploy.RESET_TIMEOUT])
        self.assertTrue(all(call.kwargs["check"] for call in run.call_args_list))

    def test_invalid_timeout_never_opens_the_port(self):
        for value in ("0", "-1"):
            with self.subTest(value=value), \
                    patch.object(sys, "argv", ["deploy", "--timeout", value]), \
                    patch.object(deploy.subprocess, "run") as run, patch.object(sys, "stderr"):
                with self.assertRaises(SystemExit) as error:
                    deploy.main()
                self.assertEqual(error.exception.code, 2)
                run.assert_not_called()

    def test_preflight_timeout_is_not_masked_by_reset_timeout(self):
        with patch.object(sys, "argv", ["deploy", "--port", "auto"]), \
                patch.object(deploy.subprocess, "run", side_effect=[
                    subprocess.TimeoutExpired("preflight", deploy.PREFLIGHT_TIMEOUT),
                    subprocess.TimeoutExpired("reset", deploy.RESET_TIMEOUT)]) as run, \
                patch.object(sys, "stderr") as stderr:
            with self.assertRaises(SystemExit) as error:
                deploy.main()
        self.assertEqual(error.exception.code, 1)
        self.assertEqual(run.call_count, 2)
        output = " ".join(str(call.args[0]) for call in stderr.write.call_args_list)
        self.assertIn("Deployment timed out after 30 seconds", output)
        self.assertIn("automatic reset failed", output)

    def test_transfer_failure_is_not_masked_by_reset_failure(self):
        with patch.object(sys, "argv", ["deploy", "--port", "auto"]), \
                patch.object(deploy.subprocess, "run", side_effect=[None,
                    subprocess.CalledProcessError(1, "transfer"), OSError("reset failed")]), \
                patch.object(sys, "stderr") as stderr:
            with self.assertRaises(SystemExit) as error:
                deploy.main()
        self.assertEqual(error.exception.code, 1)
        output = " ".join(str(call.args[0]) for call in stderr.write.call_args_list)
        self.assertIn("Deployment failed", output)
        self.assertIn("transfer", output)
        self.assertIn("automatic reset failed", output)

    def test_successful_transfer_with_failed_reset_is_not_reported_as_success(self):
        with patch.object(sys, "argv", ["deploy", "--port", "auto"]), \
                patch.object(deploy.subprocess, "run", side_effect=[None, None,
                    subprocess.CalledProcessError(1, "reset")]), patch.object(sys, "stderr"):
            with self.assertRaises(SystemExit) as error:
                deploy.main()
        self.assertEqual(error.exception.code, 1)

    def test_keyboard_interrupt_still_attempts_reset_and_is_preserved(self):
        interrupted = KeyboardInterrupt()
        with patch.object(sys, "argv", ["deploy", "--port", "auto"]), \
                patch.object(deploy.subprocess, "run", side_effect=[None, interrupted,
                    OSError("reset failed")]) as run, patch.object(sys, "stderr"):
            with self.assertRaises(KeyboardInterrupt) as error:
                deploy.main()
        self.assertIs(error.exception, interrupted)
        self.assertEqual(run.call_args.args[0][-1], "reset")

    def test_stalled_child_is_killed_and_reaped_before_reset(self):
        # Never launch mpremote or access hardware: substitute a sleeping Python child.
        real_run, real_popen = subprocess.run, subprocess.Popen
        children = []

        def popen(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            children.append(child)
            return child

        def run(command, **kwargs):
            if command[-1] == "reset":
                self.assertIsNotNone(children[0].returncode)
                return
            return real_run([sys.executable, "-c", "import threading; threading.Event().wait()"],
                            timeout=0.2, check=True)

        with patch.object(sys, "argv", ["deploy", "--port", "auto"]), \
                patch.object(deploy.subprocess, "run", side_effect=run), \
                patch.object(deploy.subprocess, "Popen", side_effect=popen), \
                patch.object(sys, "stderr"):
            with self.assertRaises(SystemExit) as error:
                deploy.main()
        self.assertEqual(error.exception.code, 1)
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].returncode)

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
