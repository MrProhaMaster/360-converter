from dataclasses import replace
import json
from pathlib import Path
import sys
import threading
import time

from PIL import Image
import pytest

from converter_360.core import (Settings, ConversionError, Cancelled, inspect_source, render,
                          batch_export, save_jpeg, save_preset, load_preset, check_ffmpeg,
                          run_process, projection_filter)


@pytest.mark.parametrize("options", [{"fov": float("nan")}, {"yaw": float("inf")}, {"width": 0},
    {"height": 9000}, {"views": 3}, {"quality": 101}, {"width": True}, {"pitch": 91}, {"roll": -181}, {"width": 8192, "height": 8192}])
def test_invalid_settings(options):
    with pytest.raises(ConversionError):
        Settings(**options).validate()


def test_presets(tmp_path):
    path = tmp_path / "preset.json"
    expected = Settings(yaw=13.5, roll=-6, views=6)
    save_preset(path, expected)
    assert load_preset(path) == expected
    path.write_text('{"schema_version":2,"settings":{}}')
    with pytest.raises(ConversionError):
        load_preset(path)
    path.write_text('{"schema_version":1,"settings":{"width":"oops"}}')
    with pytest.raises(ConversionError):
        load_preset(path)


def test_source_validation(tmp_path, panorama):
    source, icc = panorama
    assert inspect_source(source).icc == icc
    broken = tmp_path / "broken.jpg"
    broken.write_bytes(b"not an image")
    with pytest.raises(ConversionError):
        inspect_source(broken)
    Image.new("RGB", (100, 100)).save(broken)
    with pytest.raises(ConversionError):
        inspect_source(broken)
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (200, 100)).save(broken, exif=exif)
    with pytest.raises(ConversionError):
        inspect_source(broken)


def test_no_overwrite_and_metadata(tmp_path, panorama):
    source, icc = panorama
    original = source.read_bytes()
    image = Image.new("RGB", (64, 64), "red")
    with pytest.raises(ConversionError):
        save_jpeg(image, source, 95, icc, [source])
    dest = tmp_path / "frame.jpg"
    save_jpeg(image, dest, 95, icc, [source])
    before = dest.read_bytes()
    with pytest.raises(ConversionError):
        save_jpeg(image, dest, 95, icc, [source])
    assert source.read_bytes() == original and dest.read_bytes() == before
    assert not list(tmp_path.glob(".360_converter-*"))
    with Image.open(dest) as im:
        assert im.info["icc_profile"] == icc
        assert len(im.getexif()) == 0


def test_encoder_failure_leaves_no_output(tmp_path, monkeypatch):
    def fail(*a, **kw):
        raise OSError("disk full")
    monkeypatch.setattr(Image.Image, "save", fail)
    with pytest.raises(OSError):
        save_jpeg(Image.new("RGB", (64, 64)), tmp_path / "frame.jpg", 95, None)
    assert list(tmp_path.iterdir()) == []


def test_cube_pixel_limit():
    with pytest.raises(ConversionError):
        Settings(width=8192, height=64, views=6).validate()


def test_publish_race(tmp_path, monkeypatch):
    from converter_360 import core
    original = core.publish_new
    def concurrent_writer(temp, destination):
        destination.write_bytes(b"another writer")
        original(temp, destination)
    monkeypatch.setattr(core, "publish_new", concurrent_writer)
    target = tmp_path / "frame.jpg"
    with pytest.raises(OSError):
        save_jpeg(Image.new("RGB", (64, 64)), target, 95, None)
    assert target.read_bytes() == b"another writer"
    assert not list(tmp_path.glob(".360_converter-*"))


def test_cancel_and_timeout():
    event = threading.Event()
    timer = threading.Timer(0.25, event.set)
    timer.start()
    start = time.monotonic()
    with pytest.raises(Cancelled):
        run_process([sys.executable, "-c", "import time;time.sleep(30)"], event)
    timer.join()
    assert time.monotonic() - start < 5
    with pytest.raises(ConversionError):
        run_process([sys.executable, "-c", "import time;time.sleep(30)"], timeout=0.2)


@pytest.mark.parametrize("views", [1, 4, 6])
def test_batch_real_ffmpeg(tmp_path, panorama, ffmpeg, views):
    source, icc = panorama
    check_ffmpeg(ffmpeg)
    before = source.read_bytes()
    report = batch_export([source], tmp_path / "out", Settings(width=128, height=96, views=views), ffmpeg)
    assert not report["errors"]
    assert len(report["files"]) == views
    assert source.read_bytes() == before
    for item in report["files"]:
        with Image.open(Path(report["folder"]) / item["output"]) as im:
            assert im.size == (128, 128 if views == 6 else 96)
            assert im.info["icc_profile"] == icc
            assert not im.getexif()
    again = batch_export([source], tmp_path / "out", Settings(width=64, height=64), ffmpeg)
    assert again["folder"] != report["folder"]


def test_cube_direction_geometry(panorama, ffmpeg):
    source, _ = panorama
    options = Settings(width=65, height=65, views=6)
    centers = []
    from converter_360.core import view_plan
    for _, yaw, pitch in view_plan(options):
        with render(source, options, ffmpeg, face_yaw=yaw, face_pitch=pitch) as im:
            centers.append(im.getpixel((32, 32)))
    # v360 positive yaw turns right, positive pitch looks up.
    expected = [(240, 0, 0), (0, 0, 240), (240, 240, 0), (0, 240, 0), (240, 0, 240), (0, 240, 240)]
    for actual, target in zip(centers, expected):
        assert max(abs(a-b) for a, b in zip(actual, target)) < 15


def test_rotation_and_fov(panorama, ffmpeg):
    source, _ = panorama
    a = render(source, Settings(width=65, height=65, yaw=90), ffmpeg)
    b = render(source, Settings(width=65, height=65, pitch=90), ffmpeg)
    assert a.getpixel((32, 32))[2] > 220
    assert b.getpixel((32, 32))[0] > 220 and b.getpixel((32, 32))[2] > 220
    assert "h_fov=90" in projection_filter(Settings(views=6, fov=35))
    assert "roll=15" in projection_filter(Settings(roll=15))


def test_bad_file_continues_and_cancel(tmp_path, panorama, ffmpeg):
    source, _ = panorama
    broken = tmp_path / "bad.jpg"
    broken.write_text("bad")
    report = batch_export([broken, source], tmp_path / "out", Settings(width=64, height=64), ffmpeg)
    assert len(report["errors"]) == 1 and len(report["files"]) == 1
    event = threading.Event()
    report = batch_export([source], tmp_path / "out", Settings(width=64, height=64, views=6), ffmpeg,
                          event, lambda *args: event.set())
    assert report["cancelled"] and len(report["files"]) == 1
    assert (Path(report["folder"]) / "report.json").is_file()


def test_same_names_and_per_file(tmp_path, panorama, ffmpeg):
    source, _ = panorama
    folder = tmp_path / "second"
    folder.mkdir()
    second = folder / source.name
    second.write_bytes(source.read_bytes())
    report = batch_export([source, second], tmp_path / "out", Settings(width=64, height=64), ffmpeg,
                          per_file={second.resolve(): Settings(width=64, height=64, views=4)})
    assert len(report["files"]) == 5
    assert len({x["output"] for x in report["files"]}) == 5
