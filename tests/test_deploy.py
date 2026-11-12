import sys
import unittest
from unittest.mock import patch

from pc import deploy


class DeployTests(unittest.TestCase):
    def test_explicit_s3_profile_is_written_after_files_and_before_reset(self):
        with patch.object(sys, "argv", ["deploy", "--port", "auto", "--board",
                                       "waveshare-s3-amoled-164"]), \
                patch.object(deploy.subprocess, "run") as run:
            deploy.main()
        transfer, reset = run.call_args_list
        command = transfer.args[0]
        self.assertIn(":co5300.py", command)
        self.assertEqual(command[-3:], ["+", "exec", "with open('openbuddy-board.txt', 'w') as f: f.write('waveshare-s3-amoled-164')"])
        self.assertEqual(reset.args[0][-1], "reset")

    def test_update_without_board_preserves_current_profile(self):
        with patch.object(sys, "argv", ["deploy", "--port", "auto"]), \
                patch.object(deploy.subprocess, "run") as run:
            deploy.main()
        self.assertNotIn("exec", run.call_args_list[0].args[0])
