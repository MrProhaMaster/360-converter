"""Verify a normal pip install (no dev extras) without an external FFmpeg."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from check_windows_bundle import check_export, isolated_environment


def check():
    env = isolated_environment()
    # Use an unrelated working directory so imports cannot come from the checkout.
    probe = """
import json
from pathlib import Path
import imageio_ffmpeg
import pano360
from pano360.core import find_ffmpeg, check_ffmpeg
binary = Path(find_ffmpeg())
assert Path(imageio_ffmpeg.__file__).resolve().parent in binary.parents
print(json.dumps({'app': pano360.__version__, 'python': __import__('sys').version.split()[0],
                  'ffmpeg': check_ffmpeg(str(binary)), 'module': pano360.__file__}))
"""
    with tempfile.TemporaryDirectory(prefix="pano360-source-install-") as temp:
        result = subprocess.run([sys.executable, "-c", probe], cwd=temp, env=env,
                                capture_output=True, timeout=30)
        assert result.returncode == 0, result.stderr
        info = json.loads(result.stdout)
        assert "site-packages" in Path(info["module"]).parts, info
    check_export([sys.executable, "-m", "pano360.cli"], env)
    print(f"Normal pip install passed: Python {info['python']}, Pano360 {info['app']}; "
          "packaged FFmpeg, 1/4/6 JPEG views, ICC, unchanged source, system-only PATH.")


if __name__ == "__main__":
    check()
