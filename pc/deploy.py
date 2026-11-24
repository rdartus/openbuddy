"""Deploy only known firmware files, leaving bonding keys and the SD untouched."""

import argparse
from pathlib import Path
import subprocess
import sys

FILES = ("pet_format.py", "board_config.py", "shared_spi.py", "sdcard_spi.py", "storage.py",
         "st7789.py", "co5300.py", "buddy_protocol.py", "buddy_ble.py", "buddy_usb.py", "buddy_prompt.py",
         "pet_player.py", "buddy_ui.py", "buddy_orientation.py", "qmi8658.py", "ft3168.py",
         "companion.py", "orientation_demo.py", "main.py")
PREFLIGHT_TIMEOUT = 30
DEPLOY_TIMEOUT = 180
RESET_TIMEOUT = 20


def main():
    parser = argparse.ArgumentParser(description="Deploy OpenBuddy MicroPython files without erasing flash")
    parser.add_argument("--port", default="COM9")
    parser.add_argument("--board", choices=("waveshare-c6-lcd-147", "waveshare-s3-amoled-164-v2"),
                        help="Persist a board profile; omitted keeps the saved profile or build default")
    parser.add_argument("--timeout", type=int, default=DEPLOY_TIMEOUT, metavar="SECONDS",
                        help="Maximum file transfer duration (default: %(default)s seconds)")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    root = Path(__file__).resolve().parents[1] / "device"
    command = [sys.executable, "-u", "-m", "mpremote", "connect", args.port]
    for index, name in enumerate(FILES):
        if index:
            command.append("+")
        command.extend(["fs", "cp", str(root / name), ":" + name])
    if args.board:
        command.extend(["+", "exec", "with open('openbuddy-board.txt', 'w') as f: f.write(%r)" % args.board])
    try:
        if args.board != "waveshare-c6-lcd-147":
            # Read the persisted identity directly, even on an older deployment.
            preflight = "board = %r\n" % args.board
            preflight += (
                "if board is None:\n"
                "    try:\n"
                "        with open('openbuddy-board.txt') as f: board = f.read(64).strip()\n"
                "    except OSError:\n"
                "        board = 'waveshare-c6-lcd-147'\n"
                "        try:\n"
                "            from openbuddy_build import BOARD_MODEL\n"
                "            board = BOARD_MODEL\n"
                "        except ImportError:\n"
                "            pass\n"
                "if board == 'waveshare-s3-amoled-164-v2':\n"
                "    try:\n"
                "        from amoled_qspi import Bus, API_VERSION\n"
                "        if API_VERSION < 4: raise ImportError('Outdated QSPI firmware')\n"
                "    except ImportError:\n"
                "        raise ImportError('Install the OpenBuddy ESP32-S3 QSPI MicroPython "
                "firmware with native amoled_qspi API_VERSION >= 4 and octal PSRAM before deploying; "
                "stock MicroPython cannot drive this panel')\n"
            )
            subprocess.run([sys.executable, "-m", "mpremote", "connect", args.port,
                            "exec", preflight], timeout=PREFLIGHT_TIMEOUT, check=True)
        # subprocess.run kills and waits for mpremote on timeout before resetting.
        subprocess.run(command, timeout=args.timeout, check=True)
    except subprocess.TimeoutExpired as error:
        parser.exit(1, "Deployment timed out after %s seconds; mpremote was stopped. "
                    "Check the board, stop other serial tools and retry.\n" % error.timeout)
    except (OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, "Deployment failed: %s\n" % error)
    finally:
        reset_ok = False
        try:
            subprocess.run([sys.executable, "-m", "mpremote", "connect", args.port, "reset"],
                           timeout=RESET_TIMEOUT, check=True)
            reset_ok = True
        except (OSError, subprocess.SubprocessError) as error:
            # Never replace the original deployment error with a reset failure.
            print("Warning: automatic reset failed (%s); press RST on the board." %
                  type(error).__name__, file=sys.stderr)
    if not reset_ok:
        parser.exit(1, "Files copied, but the board could not be restarted.\n")


if __name__ == "__main__":
    main()
