from pathlib import Path
import shutil
import sys

import pytest

from pano360 import core
from test_gui_cli import gui_app, wait_ui


@pytest.fixture
def frozen_layout(tmp_path, monkeypatch):
    folder = tmp_path / "приложение с пробелами"
    internal = folder / "_internal"
    internal.mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(folder / "Pano360.exe"))
    monkeypatch.setattr(sys, "_MEIPASS", str(internal), raising=False)
    monkeypatch.setattr(core, "__file__", str(internal / "pano360" / "core.py"))
    monkeypatch.setenv("PATH", "")
    return folder


@pytest.mark.parametrize("location", ["bin", "_internal/bin"])
def test_frozen_discovery_ignores_cwd_and_environment(frozen_layout, tmp_path, monkeypatch, location):
    binary = frozen_layout / location / "ffmpeg.exe"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.touch()
    other = tmp_path / "unrelated"
    other.mkdir()
    (other / "ffmpeg.exe").touch()
    monkeypatch.chdir(other)
    monkeypatch.setenv("IMAGEIO_FFMPEG_EXE", str(other / "ffmpeg.exe"))
    monkeypatch.setattr(core.shutil, "which", lambda name: str(other / "ffmpeg.exe"))
    assert core.find_ffmpeg() == str(binary.resolve())


def test_explicit_override_and_missing_path(frozen_layout, tmp_path):
    binary = frozen_layout / "bin" / "ffmpeg.exe"
    binary.parent.mkdir()
    binary.touch()
    custom = tmp_path / "custom.exe"
    custom.touch()
    assert core.find_ffmpeg(str(custom)) == str(custom.resolve())
    with pytest.raises(core.ConversionError, match="Указанный"):
        core.find_ffmpeg(str(tmp_path / "missing.exe"))


def test_incomplete_bundle_has_recovery_message(frozen_layout):
    with pytest.raises(core.ConversionError, match="Распакуйте всю папку"):
        core.find_ffmpeg()


def test_source_install_keeps_external_ffmpeg(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python.exe"))
    monkeypatch.setattr(core, "__file__", str(tmp_path / "pano360" / "core.py"))
    monkeypatch.setattr(core.shutil, "which", lambda name: "external-ffmpeg")
    assert core.bundled_ffmpeg() is None
    assert core.find_ffmpeg() == "external-ffmpeg"


def test_gui_uses_bundled_ffmpeg_without_configuration(frozen_layout, ffmpeg, request, panorama, tmp_path):
    # The fixture starts App only AFTER the frozen layout has been installed.
    binary = frozen_layout / "bin" / "ffmpeg.exe"
    binary.parent.mkdir()
    shutil.copyfile(ffmpeg, binary)
    app = request.getfixturevalue("gui_app")
    assert Path(app.ffmpeg.get()) == binary
    app.add_paths([panorama[0]])
    app.vars["width"].set("64")
    app.vars["height"].set("64")
    app.output.set(str(tmp_path / "automatic-export"))
    app.quick_export_button.invoke()
    wait_ui(app, lambda: app.last_report is not None)
    assert not app.last_report["errors"]
    assert len(app.last_report["files"]) == 4
