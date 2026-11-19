"""Fail closed on MicroPython-incompatible deployable Python sources."""

import ast
from importlib import metadata
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from pc.deploy import FILES


ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.29.0.post2"
# Only modules shipped by ESP32 MicroPython 1.29, our firmware, or the S3 build.
RUNTIME_MODULES = {"binascii", "bluetooth", "errno", "framebuf", "json", "machine",
                   "neopixel", "os", "select", "struct", "sys", "time", "vfs", "amoled_qspi",
                   "openbuddy_build"}
# These CPython methods compile as attribute lookups, but fail on MicroPython.
UNSUPPORTED_METHODS = {"isascii", "removeprefix", "removesuffix", "casefold",
                       "format_map", "isalnum", "ljust"}


def lint_source(source, filename, local_modules):
    """Check imports and known CPython-only methods; compilation is a separate step."""
    tree = ast.parse(source, filename=filename)
    errors = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names = (node.module,) if node.level == 0 else ()
        else:
            names = ()
        for name in names:
            # board_config has a CPython fallback for host imports.
            if name == "device.pet_format":
                continue
            if name not in RUNTIME_MODULES | local_modules:
                errors.append("%s:%d: module %s is not in the verified ESP32 module allowlist" %
                              (filename, node.lineno, name))
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in UNSUPPORTED_METHODS):
            errors.append("%s:%d: .%s() is not supported by MicroPython" %
                          (filename, node.lineno, node.func.attr))
    return errors


def check_sources(paths, runner=subprocess.run):
    """Compile exactly the files deployed to the board, without creating .mpy in device/."""
    try:
        installed = metadata.version("mpy-cross")
    except metadata.PackageNotFoundError as error:
        raise RuntimeError("Install pc/requirements-dev.txt (mpy-cross is required)") from error
    if installed != VERSION:
        raise RuntimeError("Expected mpy-cross %s, found %s" % (VERSION, installed))

    errors = []
    local_modules = {path.stem for path in paths}
    with TemporaryDirectory() as output:
        for path in paths:
            errors.extend(lint_source(path.read_text(encoding="utf-8"), str(path), local_modules))
            try:
                result = runner([sys.executable, "-m", "mpy_cross", "-o",
                                 str(Path(output) / (path.stem + ".mpy")), str(path)],
                                capture_output=True, text=True, timeout=30, check=False)
            except (OSError, subprocess.TimeoutExpired) as error:
                raise RuntimeError("Cannot run mpy-cross for %s: %s" % (path, error)) from error
            if result.returncode:
                errors.append("%s: mpy-cross: %s" %
                              (path, (result.stderr or result.stdout).strip()))
    return errors


def main():
    try:
        errors = check_sources([ROOT / "device" / name for name in FILES])
    except (RuntimeError, SyntaxError) as error:
        print("MicroPython check failed: %s" % error, file=sys.stderr)
        return 1
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("MicroPython 1.29: %d deployable files compiled and linted" % len(FILES))
    return 0


if __name__ == "__main__":
    sys.exit(main())
