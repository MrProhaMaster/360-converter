import threading

import numpy as np
from PIL import Image
import pytest

from pano360.core import Cancelled, Settings, render
from pano360.preview import PreviewRenderer, project


@pytest.fixture
def direction_panorama(tmp_path):
    # Continuous RGB encoding of world direction: meaningful across the seam and poles.
    lon = ((np.arange(720) + 0.5) / 720 - 0.5) * 2 * np.pi
    lat = ((np.arange(360) + 0.5) / 360 - 0.5) * np.pi
    lon, lat = np.meshgrid(lon, lat)
    rgb = np.stack([np.sin(lon) * np.cos(lat), np.sin(lat), np.cos(lon) * np.cos(lat)], axis=-1)
    pixels = np.rint(127 + 100 * rgb).astype(np.uint8)
    path = tmp_path / "directions.jpg"
    Image.fromarray(pixels).save(path, quality=100, subsampling=0)
    return path


@pytest.mark.parametrize("views,yaw,pitch,roll,face_yaw,face_pitch", [
    (1, 31, -18, 42, 0, 0), (1, -179.9, 0, -15, 0, 0),
    (1, 0, 90, 0, 0, 0), (1, 0, -90, 0, 0, 0),
    (4, 31, -18, 42, 90, 0), (4, -68, 20, -30, 180, 0),
    (6, 31, -18, 42, 0, 90), (6, 31, -18, 42, 0, -90),
])
def test_preview_matches_export_geometry(direction_panorama, ffmpeg, views, yaw, pitch, roll, face_yaw, face_pitch):
    options = Settings(width=129, height=97, fov=120, views=views, yaw=yaw, pitch=pitch, roll=roll)
    size = (options.width, options.width if views == 6 else options.height)
    preview, _ = PreviewRenderer().render(direction_panorama, options, size, face_yaw, face_pitch)
    with render(direction_panorama, options, ffmpeg, face_yaw=face_yaw, face_pitch=face_pitch) as expected:
        difference = np.abs(np.asarray(preview).astype(float) - np.asarray(expected))
    # Independent FFmpeg oracle; tolerate JPEG/color conversion and interpolation differences.
    assert difference.mean() < 2
    assert np.percentile(difference, 99) < 5


def test_preview_seam_continuity(direction_panorama):
    with Image.open(direction_panorama) as image:
        pixels = np.asarray(image)
    a = np.asarray(project(pixels, Settings(yaw=179.99), (321, 241))).astype(float)
    b = np.asarray(project(pixels, Settings(yaw=-179.99), (321, 241))).astype(float)
    assert np.abs(a-b).max() <= 2


def test_preview_cache_and_cancel(panorama, monkeypatch):
    from pano360 import preview
    inspect = preview.inspect_source
    calls = []

    def counted(path):
        calls.append(path)
        return inspect(path)

    monkeypatch.setattr(preview, "inspect_source", counted)
    renderer = PreviewRenderer()
    for yaw in (0, 15, 30):
        image, description = renderer.render(panorama[0], Settings(yaw=yaw), (80, 60))
        image.close()
    assert calls == [panorama[0]]
    assert "ICC:" in description and "не удалось" not in description
    # File replacement under the same name must invalidate the cached source.
    Image.new("RGB", (400, 200), "blue").save(panorama[0])
    image, _ = renderer.render(panorama[0], Settings(), (80, 60))
    assert len(calls) == 2 and image.getpixel((40, 30))[2] > 240
    event = threading.Event()
    event.set()
    with pytest.raises(Cancelled):
        renderer.render(panorama[0], Settings(), (80, 60), cancel=event)


def test_preview_bounded_cache_and_invalid_icc(tmp_path):
    path = tmp_path / "large.jpg"
    Image.new("RGB", (4096, 2048), "red").save(path, icc_profile=b"invalid profile")
    renderer = PreviewRenderer()
    image, description = renderer.render(path, Settings(), (80, 60))
    assert renderer.pixels.shape == (1024, 2048, 3)
    assert "профиль не удалось" in description
    assert image.getpixel((40, 30))[0] > 240
