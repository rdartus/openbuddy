"""Deploy only known firmware files, leaving bonding keys and the SD untouched."""

import argparse
from pathlib import Path
import subprocess
import sys

FILES = ("board_config.py", "shared_spi.py", "sdcard_spi.py", "storage.py",
         "st7789.py", "co5300.py", "buddy_protocol.py", "buddy_ble.py", "buddy_usb.py", "pet_player.py",
         "buddy_ui.py", "companion.py", "orientation_demo.py", "main.py")


def main():
    parser = argparse.ArgumentParser(description="Deploy OpenBuddy MicroPython files without erasing flash")
    parser.add_argument("--port", default="COM9")
    parser.add_argument("--board", choices=("waveshare-c6-lcd-147", "waveshare-s3-amoled-164"),
                        help="Persist a board profile; omitted keeps the current profile (C6 on first install)")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / "c6lcd"
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
                "if board == 'waveshare-s3-amoled-164':\n"
                "    try:\n"
                "        from amoled_qspi import Bus\n"
                "    except ImportError:\n"
                "        raise ImportError('Install the OpenBuddy ESP32-S3 QSPI MicroPython "
                "firmware with native amoled_qspi and octal PSRAM before deploying; "
                "stock MicroPython cannot drive this panel')\n"
            )
            subprocess.run([sys.executable, "-m", "mpremote", "connect", args.port,
                            "exec", preflight], check=True)
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as error:
        parser.exit(1, "Deployment failed: %s\n" % error)
    finally:
        subprocess.run([sys.executable, "-m", "mpremote", "connect", args.port, "reset"],
                       timeout=20, check=False)


if __name__ == "__main__":
    main()
