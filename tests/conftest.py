from pathlib import Path
import os
import shutil
import pytest
from PIL import Image, ImageCms, ImageDraw


@pytest.fixture
def panorama(tmp_path):
    """Six directional colors; no external files or personal photos."""
    im = Image.new("RGB", (720, 360))
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, 719, 89), fill=(240, 0, 240))
    d.rectangle((0, 270, 719, 359), fill=(0, 240, 240))
    for a, b, color in [(0, 89, (240, 240, 0)), (90, 269, (0, 240, 0)),
                         (270, 449, (240, 0, 0)), (450, 629, (0, 0, 240)), (630, 719, (240, 240, 0))]:
        d.rectangle((a, 90, b, 269), fill=color)
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    exif = Image.Exif()
    exif[270] = "PRIVATE TEST METADATA"
    p = tmp_path / "панорама test.jpg"
    im.save(p, quality=100, subsampling=0, icc_profile=icc, exif=exif)
    return p, icc


@pytest.fixture
def ffmpeg():
    exe = os.environ.get("CONVERTER_360_TEST_FFMPEG") or shutil.which("ffmpeg")
    if not exe:
        try:
            import imageio_ffmpeg
            exe = imageio_ffmpeg.get_ffmpeg_exe()
        except ImportError:
            pytest.skip("Install .[dev] or set CONVERTER_360_TEST_FFMPEG")
    return exe
