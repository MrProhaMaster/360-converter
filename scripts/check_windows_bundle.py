"""Exercise the actual frozen EXE without Python/FFmpeg on PATH, from another cwd."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

from PIL import Image, ImageCms, ImageDraw


def isolated_environment():
    env = os.environ.copy()
    env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    for key in list(env):
        if key.upper().startswith(("PYTHON", "IMAGEIO_", "PANO360_")) or key.upper() in ("TCL_LIBRARY", "TK_LIBRARY"):
            del env[key]
    return env


def check_export(command, env):
    with tempfile.TemporaryDirectory(prefix="pano360-portable-") as temp:
        work = Path(temp) / "проверка с пробелами"
        work.mkdir()
        source = work / "панорама.jpg"
        image = Image.new("RGB", (720, 360), "red")
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 719, 89), fill="magenta")
        draw.rectangle((0, 270, 719, 359), fill="cyan")
        icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
        exif = Image.Exif()
        exif[270] = "TEST ONLY"
        image.save(source, icc_profile=icc, exif=exif)
        before = source.read_bytes()
        for views in (1, 4, 6):
            output = work / f"out-{views}"
            result = subprocess.run([*command, str(source), "--output", str(output),
                                     "--views", str(views), "--width", "128", "--height", "96"],
                                    cwd=work, env=env, timeout=180, capture_output=True)
            assert result.returncode == 0, (result.returncode, result.stderr)
            reports = list(output.glob("*/report.json"))
            assert len(reports) == 1, f"Missing report for {views} views"
            report = json.loads(reports[0].read_text(encoding="utf-8"))
            assert not report["errors"] and not report["cancelled"], report
            assert len(report["files"]) == views, report
            for item in report["files"]:
                with Image.open(reports[0].parent / item["output"]) as frame:
                    assert frame.size == (128, 128 if views == 6 else 96)
                    assert frame.info["icc_profile"] == icc
                    assert len(frame.getexif()) == 0
        assert source.read_bytes() == before


def check(bundle: Path):
    executable = bundle / "Pano360.exe"
    ffmpeg = bundle / "bin" / "ffmpeg.exe"
    manifest = json.loads((bundle / "licenses" / "FFmpeg-provenance.json").read_text(encoding="utf-8"))
    with ffmpeg.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == manifest["sha256"]
    check_export([str(executable), "--cli"], isolated_environment())
    print("Portable EXE passed: 1/4/6 JPEG views, ICC, no EXIF, unchanged source, system-only PATH.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    check(parser.parse_args().bundle.resolve())
