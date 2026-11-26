"""Bundle a pinned Windows x64 FFmpeg; never use PATH or IMAGEIO_FFMPEG_EXE."""
import argparse
import hashlib
from importlib.metadata import distribution
import json
from pathlib import Path
import shutil
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from converter_360.core import check_ffmpeg, run_process

PACKAGE_VERSION = "0.8.1"
BINARY_NAME = "ffmpeg-win-x86_64-v9.0.2.exe"
BINARY_SHA256 = "3256173f3f8bffd7df12227c68adf68025edb1832273a9530688a7bb1ed8edec"


def bundle(destination: Path):
    if sys.platform != "win32" or struct.calcsize("P") != 8:
        raise RuntimeError("The portable build requires Windows x64 Python.")
    package = distribution("imageio-ffmpeg")
    if package.version != PACKAGE_VERSION:
        raise RuntimeError(f"Install imageio-ffmpeg=={PACKAGE_VERSION} for the verified binary.")
    source = Path(package.locate_file(f"imageio_ffmpeg/binaries/{BINARY_NAME}"))
    with source.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != BINARY_SHA256:
        raise RuntimeError("FFmpeg checksum differs from the verified build.")
    version = check_ffmpeg(str(source))  # Also checks the required v360 filter.
    info = run_process([str(source), "-version"], timeout=15).decode("utf-8", errors="replace")
    notice = run_process([str(source), "-hide_banner", "-L"], timeout=15).decode("utf-8", errors="replace")
    binary_dir = destination / "bin"
    license_dir = destination / "licenses"
    binary_dir.mkdir(parents=True, exist_ok=True)
    license_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, binary_dir / "ffmpeg.exe")
    shutil.copyfile(ROOT / "licenses" / "FFmpeg-GPLv3.txt", license_dir / "FFmpeg-GPLv3.txt")
    package_license = next(p for p in package.files if str(p).endswith(".dist-info/licenses/LICENSE"))
    shutil.copyfile(package.locate_file(package_license), license_dir / "imageio-ffmpeg-BSD.txt")
    (license_dir / "FFmpeg-build.txt").write_text(info + "\n" + notice, encoding="utf-8")
    (license_dir / "FFmpeg-provenance.json").write_text(json.dumps({
        "binary": "bin/ffmpeg.exe", "sha256": digest, "version": version,
        "package": f"imageio-ffmpeg=={PACKAGE_VERSION}", "modified": False,
        "license": "GPL-3.0-or-later",
        "upstream_build": "https://www.gyan.dev/ffmpeg/builds/",
        "binary_origin": "https://github.com/GyanD/codexffmpeg/releases/tag/9.0.2",
        "ffmpeg_source": "https://github.com/FFmpeg/FFmpeg/tree/n9.0.2",
        "ffmpeg_source_archive": "https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz",
        "package_source": "https://github.com/imageio/imageio-ffmpeg/tree/v0.8.1",
    }, indent=2) + "\n", encoding="utf-8")
    print(f"Bundled {version}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    bundle(parser.parse_args().destination.resolve())
