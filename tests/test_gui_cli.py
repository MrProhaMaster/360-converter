import time
from dataclasses import asdict
from pathlib import Path
import pytest
from PIL import Image
from pano360.cli import main
from pano360.core import ConversionError, Settings


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
        app.geometry("1000x720")
        app.deiconify()
        app.update()
        export_bottom = app.export_frame.winfo_rooty() + app.export_frame.winfo_height()
        footer_top = app.progressbar.master.winfo_rooty()
        assert export_bottom <= footer_top
        assert app.canvas.winfo_height() >= 20
        buttons = [app.quick_export_button, app.export_button, app.cancel_button, app.result_button]
        for left, right in zip(buttons, buttons[1:]):
            assert left.winfo_rootx() + left.winfo_width() <= right.winfo_rootx()
        assert buttons[-1].winfo_rootx() + buttons[-1].winfo_width() <= app.winfo_rootx() + app.winfo_width()
        app.withdraw()
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


@pytest.fixture
def gui_app():
    import tkinter as tk
    from pano360.gui import App
    try:
        app = App()
    except tk.TclError as exc:
        pytest.skip(f"No Tk display: {exc}")
    app.withdraw()
    try:
        yield app
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


def test_quick_export_five_panoramas(gui_app, tmp_path, panorama, ffmpeg, monkeypatch):
    """The actual button produces 20 JPEGs even with mixed pinned view counts."""
    from pano360 import gui
    app = gui_app
    source_bytes = panorama[0].read_bytes()
    paths = [tmp_path / f"панорама {i}.jpg" for i in range(5)]
    for path in paths:
        path.write_bytes(source_bytes)
    app.ffmpeg.set(ffmpeg)
    # The shortcut supplies both missing selections, including paths with spaces/Cyrillic.
    monkeypatch.setattr(gui.filedialog, "askopenfilenames", lambda **kwargs: tuple(map(str, paths)))
    monkeypatch.setattr(gui.filedialog, "askdirectory", lambda: str(tmp_path / "результат"))
    app.apply_settings(Settings(width=96, height=64, views=1))
    app.per_file[paths[1]] = Settings(yaw=90, pitch=3, roll=2, fov=100,
                                    width=80, height=64, quality=87, views=6)
    app.per_file[paths[2]] = Settings(yaw=-90, width=64, height=80, views=1)
    pinned_before = dict(app.per_file)
    fields_before = {key: var.get() for key, var in app.vars.items()}
    app.quick_export_button.invoke()
    first_future = app.export_future
    assert first_future is not None
    assert app.quick_export_button.instate(["disabled"])
    assert app.export_button.instate(["disabled"])
    app.quick_export_button.invoke()
    assert app.export_future is first_future
    wait_ui(app, lambda: app.last_report is not None, timeout=40)
    report = app.last_report
    assert not report["errors"] and not report["cancelled"]
    assert len(report["files"]) == 20
    assert app.quick_export_button.instate(["!disabled"])
    assert app.export_button.instate(["!disabled"])
    assert app.per_file == pinned_before
    assert {key: var.get() for key, var in app.vars.items()} == fields_before
    for path in paths:
        assert path.read_bytes() == source_bytes
        frames = [item for item in report["files"] if item["source"] == path.name]
        assert [item["view"] for item in frames] == ["front", "right", "back", "left"]
        expected = asdict(pinned_before.get(path, app.settings())) | {"views": 4}
        for item in frames:
            assert item["settings"] == expected
            with Image.open(Path(report["folder"]) / item["output"]) as im:
                assert im.size == (expected["width"], expected["height"])
                assert im.info["icc_profile"] == panorama[1]
                assert not im.getexif()


@pytest.mark.parametrize("cancel_stage", ["files", "folder"])
def test_quick_export_dialog_cancel(gui_app, panorama, monkeypatch, cancel_stage):
    from pano360 import gui
    app = gui_app
    if cancel_stage == "folder":
        app.add_paths([panorama[0]])
    monkeypatch.setattr(gui.filedialog, "askopenfilenames", lambda **kwargs: ())
    folder_calls = []
    monkeypatch.setattr(gui.filedialog, "askdirectory", lambda: folder_calls.append(True) or "")
    app.quick_export_button.invoke()
    assert app.export_future is None
    assert app.quick_export_button.instate(["!disabled"])
    assert bool(folder_calls) == (cancel_stage == "folder")


@pytest.mark.parametrize("finish", ["cancel", "error"])
def test_quick_export_recovers_controls(gui_app, tmp_path, panorama, ffmpeg, monkeypatch, finish):
    from pano360 import gui
    app = gui_app
    app.add_paths([panorama[0]])
    app.ffmpeg.set(ffmpeg)
    app.output.set(str(tmp_path / "out"))
    errors = []
    monkeypatch.setattr(gui.messagebox, "showerror", lambda *args: errors.append(args))
    monkeypatch.setattr(gui, "check_ffmpeg", lambda path: None)

    def export(paths, output, settings, executable, cancel, progress, per_file):
        if finish == "error":
            raise ConversionError("Test export failure")
        assert cancel.wait(5), "Cancel button did not signal the current export"
        return {"files": [], "errors": [], "cancelled": True, "folder": str(output)}

    monkeypatch.setattr(gui, "batch_export", export)
    app.quick_export_button.invoke()
    if finish == "cancel":
        app.cancel_button.invoke()
    wait_ui(app, lambda: app.quick_export_button.instate(["!disabled"]))
    assert app.export_button.instate(["!disabled"])
    assert app.cancel_button.instate(["disabled"])
    if finish == "cancel":
        assert app.last_report["cancelled"]
        assert not errors
    else:
        assert errors and "Test export failure" in app.status.get()
