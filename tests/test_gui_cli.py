import time
from pathlib import Path
import pytest
from pano360.cli import main


def test_cli(tmp_path, panorama, ffmpeg, capsys):
    source, _ = panorama
    assert main([str(source), "--output", str(tmp_path / "cli"), "--ffmpeg", ffmpeg,
                 "--width", "64", "--height", "64"]) == 0
    assert '"errors": []' in capsys.readouterr().out
    assert main([str(source), "--output", str(tmp_path / "cli"), "--ffmpeg", ffmpeg, "--views", "5"]) == 2


def wait_ui(app, predicate, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.update()
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("GUI worker timeout")


def test_gui_preview_export_and_close(tmp_path, panorama, ffmpeg):
    import tkinter as tk
    from pano360.gui import App
    try:
        app = App()
    except tk.TclError as exc:
        pytest.skip(f"No Tk display: {exc}")
    app.withdraw()
    try:
        app.ffmpeg.set(ffmpeg)
        app.add_paths([panorama[0]])
        wait_ui(app, lambda: app.preview_image is not None)
        assert "ICC" in app.meta.get()
        app.vars["width"].set("64")
        app.vars["height"].set("64")
        app.vars["views"].set("4")
        app.pin_settings()
        app.output.set(str(tmp_path / "gui-export"))
        app.start_export()
        wait_ui(app, lambda: app.last_report is not None)
        assert len(app.last_report["files"]) == 4
        assert not app.last_report["errors"]
        app.vars["yaw"].set("bad")
        app.start_preview()
        assert "числовые" in app.status.get()
    finally:
        app.close()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                app.update()
                if not app.winfo_exists():
                    break
            except tk.TclError:
                break
            time.sleep(0.02)
