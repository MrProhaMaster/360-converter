import time
import gc
import json
import os
import subprocess
import sys
import threading
from types import SimpleNamespace
from dataclasses import asdict
from pathlib import Path
import pytest
from PIL import Image
from converter_360.cli import main
from converter_360.core import ConversionError, Settings


def test_cli(tmp_path, panorama, ffmpeg, capsys):
    source, _ = panorama
    assert main([str(source), "--output", str(tmp_path / "cli"), "--ffmpeg", ffmpeg,
                 "--width", "64", "--height", "64"]) == 0
    assert '"errors": []' in capsys.readouterr().out
    assert main([str(source), "--output", str(tmp_path / "cli"), "--ffmpeg", ffmpeg, "--views", "5"]) == 2


def test_cli_unicode_report_on_western_windows_codepage(tmp_path, panorama, ffmpeg):
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "cp1252"
    result = subprocess.run([sys.executable, "-m", "converter_360.cli", str(panorama[0]),
                             "--output", str(tmp_path / "кадры"), "--ffmpeg", ffmpeg,
                             "--width", "64", "--height", "64"],
                            env=env, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.decode("utf-8"))
    assert report["files"][0]["source"] == panorama[0].name
    assert not report["errors"]


def test_cli_without_console(tmp_path, panorama, ffmpeg, monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    assert main([str(panorama[0]), "--output", str(tmp_path / "silent"), "--ffmpeg", ffmpeg,
                 "--width", "64", "--height", "64"]) == 0
    assert len(list((tmp_path / "silent").glob("*/report.json"))) == 1


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
    from converter_360.gui import App
    try:
        app = App()
    except tk.TclError as exc:
        pytest.skip(f"No Tk display: {exc}")
    app.withdraw()
    try:
        assert app.title().startswith("360-конвертер ")
        app.geometry("1000x720")
        app.deiconify()
        app.update()
        controls_bottom = app.presetbar.winfo_rooty() + app.presetbar.winfo_height()
        footer_top = app.progressbar.master.winfo_rooty()
        assert controls_bottom <= footer_top
        assert app.canvas.winfo_height() >= 20
        assert app.gizmo.winfo_y() + app.gizmo.winfo_height() <= app.canvas.winfo_height()
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
    from converter_360.gui import App
    # Retire previous Tk interpreters on the UI thread before starting another window.
    gc.collect()
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
    from converter_360 import gui
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
    from converter_360 import gui
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
    from converter_360 import gui
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


def test_drag_updates_before_release_and_keeps_latest_frame(gui_app, panorama, monkeypatch):
    app = gui_app
    app.ffmpeg.set("missing-ffmpeg.exe")  # Interactive preview does not require a subprocess.
    app.add_paths([panorama[0]])
    wait_ui(app, lambda: app.preview_image is not None)
    initial_frame = app.preview_image
    actual_render = app.preview_renderer.render
    requests = []

    def slow_render(path, settings, size, *args):
        requests.append((settings, size))
        time.sleep(0.04)  # Mouse events arrive faster than the renderer can finish.
        return actual_render(path, settings, size, *args)

    monkeypatch.setattr(app.preview_renderer, "render", slow_render)
    app.drag_start(SimpleNamespace(x=100, y=100))
    frames = []
    for step in range(60):
        app.drag_move(SimpleNamespace(x=100 + step * 2, y=100 + step))
        app.update()
        if app.preview_image is not initial_frame and (not frames or app.preview_image is not frames[-1]):
            frames.append(app.preview_image)
        time.sleep(0.015)
    # The former 280ms debounce would show no new frames throughout this gesture.
    assert app.dragging and len(frames) >= 2
    assert len(requests) < 60  # No backlog of one render per mouse event.
    app.drag_end(SimpleNamespace(x=230, y=165))
    wait_ui(app, lambda: not app.preview_busy and not app.preview_dirty and app.timer is None)
    assert not app.dragging
    assert requests[-1][0] == app.settings()
    assert requests[-1][1] == (613, 460)
    assert app.preview_image.size == (613, 460)
    assert float(app.vars["yaw"].get()) == -32.5
    assert float(app.vars["pitch"].get()) == 16.2


def test_switch_photo_discards_inflight_frame(gui_app, tmp_path, panorama, monkeypatch):
    app = gui_app
    blue = tmp_path / "blue.jpg"
    Image.new("RGB", (400, 200), "blue").save(blue)
    started, release = threading.Event(), threading.Event()
    actual_render = app.preview_renderer.render
    shown = []
    draw = app.draw_preview

    def delayed(path, *args):
        if path == panorama[0]:
            started.set()
            assert release.wait(5)
        return actual_render(path, *args)

    def record_frame():
        if app.preview_image:
            shown.append(app.meta.get())
        draw()

    monkeypatch.setattr(app.preview_renderer, "render", delayed)
    monkeypatch.setattr(app, "draw_preview", record_frame)
    app.add_paths([panorama[0], blue])
    try:
        wait_ui(app, started.is_set)
        app.filelist.selection_clear(0, "end")
        app.filelist.selection_set(1)
        app.select_file()
        release.set()
        wait_ui(app, lambda: app.preview_image is not None)
        assert shown and all("blue.jpg" in description for description in shown)
        assert app.preview_image.getpixel((0, 0))[2] > 240
    finally:
        release.set()


def test_gizmo_axes_presets_export_and_removed_fields(gui_app, panorama, tmp_path, ffmpeg):
    import numpy as np
    from converter_360.core import load_preset, save_preset
    from converter_360.gizmo import AXES, axis_rotation
    from converter_360.preview import rotation
    app = gui_app
    app.geometry("1000x720")
    app.deiconify()
    app.update()
    app.withdraw()
    app.add_paths([panorama[0]])
    app.apply_settings(Settings(width=96, height=64, views=6))
    app.face.set("Справа")
    expected = rotation(90, 0, 0).astype(float)
    for axis in "XYZ":
        app.gizmo.mode = axis
        app.gizmo.step(17)
        expected = axis_rotation(AXES[axis], 17) @ expected
        s = app.settings()
        np.testing.assert_allclose(rotation(s.yaw, s.pitch, s.roll) @ rotation(90, 0, 0), expected, atol=1e-6)
    preset = tmp_path / "orientation.json"
    save_preset(preset, app.settings())
    app.reset()
    app.apply_settings(load_preset(preset))
    np.testing.assert_allclose(app.gizmo.matrix, expected, atol=1e-6)
    app.pin_settings()
    app.ffmpeg.set(ffmpeg)
    app.output.set(str(tmp_path / "gizmo-export"))
    app.start_export()
    wait_ui(app, lambda: app.last_report is not None)
    assert not app.last_report["errors"] and len(app.last_report["files"]) == 6
    for item in app.last_report["files"]:
        assert item["settings"] == asdict(load_preset(preset))
    def entries(widget):
        for child in widget.winfo_children():
            if child.winfo_class() == "TEntry":
                yield str(child.cget("textvariable"))
            yield from entries(child)
    visible_variables = set(entries(app))
    assert visible_variables == {str(app.output)}
    assert not hasattr(app, "export_frame")


def test_gizmo_mouse_keyboard_refinement_and_sync(gui_app, panorama):
    import numpy as np
    app = gui_app
    app.deiconify()
    app.update()
    app.withdraw()
    app.add_paths([panorama[0]])
    wait_ui(app, lambda: app.preview_image is not None)
    gizmo = app.gizmo
    cx, cy, radius = gizmo.geometry_values()
    # Central free trackball gesture, then release: normal preview resolution returns.
    gizmo.press(SimpleNamespace(x=cx+8, y=cy+5))
    gizmo.move(SimpleNamespace(x=cx+15, y=cy+12, state=0))
    assert app.dragging
    gizmo.release(SimpleNamespace(x=cx+18, y=cy+15, state=0))
    assert not app.dragging
    wait_ui(app, lambda: not app.preview_busy and not app.preview_dirty and app.timer is None)
    assert app.preview_image.size == (613, 460)
    assert app.settings() != Settings()
    # Reset only the orientation with Home; focus navigation is not swallowed.
    app.vars["fov"].set("100")
    gizmo.key(SimpleNamespace(keysym="Home", state=0))
    np.testing.assert_allclose(gizmo.matrix, np.eye(3), atol=1e-7)
    assert app.settings().fov == 100
    assert gizmo.key(SimpleNamespace(keysym="Tab", state=0)) is None
    gizmo.key(SimpleNamespace(keysym="x", state=0))
    gizmo.key(SimpleNamespace(keysym="Right", state=1))
    assert app.settings().pitch == pytest.approx(.25, abs=1e-5)
    gizmo.wheel(SimpleNamespace(delta=-120, state=1))
    assert app.settings().pitch == pytest.approx(0, abs=1e-5)


@pytest.mark.parametrize("point", [(1, 0), (0, -1), (.8, .6)])
def test_sphere_rings_and_labels_do_not_select_axes(gui_app, point):
    """Starting on a colored ring or axis label must stay a free trackball drag."""
    import numpy as np
    app = gui_app
    app.deiconify()
    app.update()
    gizmo = app.gizmo
    cx, cy, radius = gizmo.geometry_values()
    start = SimpleNamespace(x=cx+radius*point[0], y=cy+radius*point[1], state=0)
    initial = gizmo.matrix.copy()
    gizmo.press(start)
    assert gizmo.mode == "Своб."
    assert gizmo.gesture[3] is None
    gizmo.move(SimpleNamespace(x=cx+8, y=cy+5, state=0))
    assert not np.allclose(gizmo.matrix, initial)
    # Passing over the mode buttons during the same gesture must not select one.
    x0, y0, x1, y1 = gizmo.buttons["X"]
    gizmo.release(SimpleNamespace(x=(x0+x1)/2, y=(y0+y1)/2, state=0))
    assert gizmo.mode == "Своб."
    assert gizmo.gesture is None


@pytest.mark.parametrize("axis", list("XYZ"))
def test_axis_lock_requires_explicit_button_and_can_be_released(gui_app, axis):
    import numpy as np
    from converter_360.gizmo import AXES, axis_rotation
    app = gui_app
    app.deiconify()
    app.update()
    gizmo = app.gizmo
    initial = gizmo.matrix.copy()
    x0, y0, x1, y1 = gizmo.buttons[axis]
    gizmo.press(SimpleNamespace(x=(x0+x1)/2, y=(y0+y1)/2))
    assert gizmo.mode == axis and gizmo.gesture is None
    np.testing.assert_allclose(gizmo.matrix, initial)
    cx, cy, _ = gizmo.geometry_values()
    gizmo.press(SimpleNamespace(x=cx+8, y=cy+5))
    assert gizmo.gesture[3] == axis
    gizmo.release(SimpleNamespace(x=cx+20, y=cy-2, state=0))
    np.testing.assert_allclose(gizmo.matrix, axis_rotation(AXES[axis], 9.5) @ initial, atol=1e-6)
    x0, y0, x1, y1 = gizmo.buttons["Своб."]
    gizmo.press(SimpleNamespace(x=(x0+x1)/2, y=(y0+y1)/2))
    gizmo.press(SimpleNamespace(x=cx+8, y=cy+5))
    assert gizmo.mode == "Своб." and gizmo.gesture[3] is None
    gizmo.release(SimpleNamespace(x=cx+12, y=cy+10, state=0))
