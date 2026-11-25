"""Tk UI: all widget access stays on the main thread; workers send queue events."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
import io
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageCms, ImageTk

from .core import (Settings, ConversionError, Cancelled, batch_export, check_ffmpeg,
                   find_ffmpeg, inspect_source, load_preset, render, save_preset)

BG, PANEL, TEXT, MUTED, ACCENT = "#0f172a", "#192134", "#f1f5f9", "#b8c4d7", "#7c3aed"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Pano360 • Панорама в кадр")
        self.geometry("1240x850")
        self.minsize(1000, 720)
        self.configure(bg=BG)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.paths = []
        self.per_file = {}
        self.events = queue.Queue()
        self.preview_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="preview")
        self.export_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="export")
        self.preview_cancel = threading.Event()
        self.export_cancel = threading.Event()
        self.generation = 0
        self.preview_future = None
        self.export_future = None
        self.timer = None
        self.closing = False
        self.suspend = False
        self.last_report = None
        self.vars = {key: tk.StringVar(value=str(value)) for key, value in asdict(Settings()).items()}
        self.ffmpeg = tk.StringVar()
        self.output = tk.StringVar()
        self.status = tk.StringVar(value="Добавьте панорамы JPEG 2:1. Все фотографии остаются на компьютере.")
        self.meta = tk.StringVar(value="Нет выбранной панорамы")
        self.face = tk.StringVar(value="Основной")
        self._style()
        self._layout()
        for variable in self.vars.values():
            variable.trace_add("write", self.schedule_preview)
        self.face.trace_add("write", self.schedule_preview)
        self.ffmpeg.trace_add("write", self.schedule_preview)
        self.bind("<Control-o>", lambda e: self.add_files())
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(80, self.poll)
        try:
            self.ffmpeg.set(find_ffmpeg())
        except ConversionError:
            pass

    def _style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure(".", background=BG, foreground=TEXT, font=("Segoe UI", 10))
        s.configure("TButton", padding=(10, 7), background=PANEL)
        s.map("TButton", background=[("active", "#334155"), ("disabled", "#253044")],
              foreground=[("disabled", "#94a3b8")])
        s.configure("Accent.TButton", background=ACCENT, font=("Segoe UI", 10, "bold"))
        s.map("Accent.TButton", background=[("active", "#6d28d9"), ("disabled", "#334155")])
        s.configure("TEntry", fieldbackground=PANEL, foreground=TEXT, insertcolor=TEXT)
        s.configure("TCombobox", fieldbackground=PANEL, foreground=TEXT, arrowcolor=TEXT)
        s.map("TCombobox", fieldbackground=[("readonly", PANEL)], foreground=[("readonly", TEXT)])
        s.configure("TLabelframe", bordercolor="#475569")
        s.configure("TLabelframe.Label", foreground=MUTED)
        s.configure("Title.TLabel", font=("Segoe UI", 22, "bold"))
        s.configure("Muted.TLabel", foreground=MUTED)
        s.configure("TProgressbar", background=ACCENT)

    def _layout(self):
        header = ttk.Frame(self, padding=(20, 16))
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text="Pano360", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="  /  Панорама в кадр", style="Muted.TLabel").pack(side="left", pady=8)
        ttk.Label(header, text="ЛОКАЛЬНО · БЕЗ ОБЛАКА", style="Muted.TLabel").pack(side="right")

        body = ttk.Frame(self, padding=(20, 0, 20, 12))
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        left = ttk.Frame(body, width=230)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 16))
        ttk.Label(left, text="01  ПАНОРАМЫ", style="Muted.TLabel").pack(anchor="w", pady=(0, 10))
        ttk.Button(left, text="Добавить фотографии…", command=self.add_files).pack(fill="x")
        ttk.Button(left, text="Добавить папку…", command=self.add_folder).pack(fill="x", pady=(6, 10))
        self.filelist = tk.Listbox(left, width=27, bg=PANEL, fg=TEXT, selectbackground=ACCENT,
                                   font=("Segoe UI", 10), activestyle="dotbox", exportselection=False,
                                   borderwidth=0, highlightthickness=1, highlightcolor=ACCENT)
        self.filelist.pack(fill="both", expand=True)
        self.filelist.bind("<<ListboxSelect>>", self.select_file)
        ttk.Button(left, text="Убрать из списка", command=self.remove_file).pack(fill="x", pady=8)
        ttk.Label(left, text="* Индивидуальные настройки\nсохранены для этой панорамы", style="Muted.TLabel").pack(anchor="w")

        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        preview_header = ttk.Frame(right)
        preview_header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(preview_header, text="02  ПРЕДПРОСМОТР", style="Muted.TLabel").pack(side="left")
        ttk.Combobox(preview_header, textvariable=self.face, width=13, state="readonly",
                     values=["Основной", "Справа", "Сзади", "Слева", "Сверху", "Снизу"]).pack(side="right")
        self.canvas = tk.Canvas(right, bg="#070d18", highlightthickness=1, highlightbackground="#334155", height=280)
        self.canvas.grid(row=1, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", lambda e: self.draw_preview())
        self.canvas.bind("<ButtonPress-1>", self.drag_start)
        self.canvas.bind("<B1-Motion>", self.drag_move)
        self.preview_image = None
        self.canvas.create_text(300, 120, text="Откройте панораму, чтобы выбрать ракурс", fill=MUTED)
        ttk.Label(right, textvariable=self.meta, style="Muted.TLabel").grid(row=2, column=0, sticky="w", pady=6)

        controls = ttk.LabelFrame(right, text="Ракурс • градусы   |   Перетаскивайте изображение для поворота", padding=10)
        controls.grid(row=3, column=0, sticky="ew")
        labels = {"yaw": "Поворот / yaw", "pitch": "Наклон / pitch", "roll": "Крен / roll", "fov": "Угол обзора / FOV"}
        for col, (key, label) in enumerate(labels.items()):
            controls.columnconfigure(col, weight=1)
            ttk.Label(controls, text=label).grid(row=0, column=col, sticky="w", padx=5)
            ttk.Entry(controls, textvariable=self.vars[key], width=12).grid(row=1, column=col, sticky="ew", padx=5, pady=5)
        presetbar = ttk.Frame(right)
        presetbar.grid(row=4, column=0, sticky="ew", pady=8)
        for text, command in [("Сбросить", self.reset), ("Открыть пресет…", self.open_preset),
                              ("Сохранить пресет…", self.write_preset), ("Закрепить за фото", self.pin_settings)]:
            ttk.Button(presetbar, text=text, command=command).pack(side="left", padx=(0, 5))

        export = ttk.LabelFrame(right, text="03  ЭКСПОРТ", padding=10)
        self.export_frame = export
        export.grid(row=5, column=0, sticky="ew")
        for col, (key, label) in enumerate((("views", "Видов"), ("width", "Ширина"), ("height", "Высота"), ("quality", "Качество JPEG"))):
            ttk.Label(export, text=label).grid(row=0, column=col, sticky="w", padx=5)
            widget = ttk.Combobox(export, textvariable=self.vars[key], values=[1, 4, 6], state="readonly", width=9) if key == "views" else ttk.Entry(export, textvariable=self.vars[key], width=12)
            widget.grid(row=1, column=col, sticky="ew", padx=5, pady=5)
            export.columnconfigure(col, weight=1)
        ttk.Label(export, text="6 видов: квадратные грани 90°; высота равна ширине.\n4 вида: шаг 90°; при FOV < 90° между кадрами будут пропуски.", style="Muted.TLabel").grid(row=2, column=0, columnspan=4, sticky="w", pady=(4, 0))

        footer = ttk.Frame(self, padding=(20, 0, 20, 14))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(1, weight=1)
        ttk.Label(footer, text="FFmpeg").grid(row=0, column=0, sticky="w", padx=(0, 10))
        ttk.Entry(footer, textvariable=self.ffmpeg).grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Button(footer, text="Выбрать…", command=self.choose_ffmpeg).grid(row=0, column=2, padx=(8, 0))
        ttk.Label(footer, text="Папка экспорта").grid(row=1, column=0, sticky="w", padx=(0, 10))
        ttk.Entry(footer, textvariable=self.output).grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Button(footer, text="Выбрать…", command=self.choose_output).grid(row=1, column=2, padx=(8, 0))
        buttons = ttk.Frame(footer)
        buttons.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(10, 8))
        self.export_button = ttk.Button(buttons, text="Экспортировать все панорамы", style="Accent.TButton", command=self.start_export)
        self.export_button.pack(side="left")
        self.cancel_button = ttk.Button(buttons, text="Отменить", state="disabled", command=self.export_cancel.set)
        self.cancel_button.pack(side="left", padx=8)
        self.result_button = ttk.Button(buttons, text="Открыть результат", state="disabled", command=self.open_result)
        self.result_button.pack(side="right")
        self.progressbar = ttk.Progressbar(footer, maximum=100)
        self.progressbar.grid(row=3, column=0, columnspan=3, sticky="ew")
        ttk.Label(footer, textvariable=self.status, wraplength=1120).grid(row=4, column=0, columnspan=3, sticky="w", pady=(8, 0))

    def settings(self):
        try:
            return Settings(**{k: (int(v.get()) if k in ("width", "height", "quality", "views") else float(v.get())) for k, v in self.vars.items()}).validate()
        except ValueError as exc:
            raise ConversionError("Введите числовые значения; десятичный разделитель — точка.") from exc

    def apply_settings(self, settings):
        self.suspend = True
        for key, value in asdict(settings).items():
            self.vars[key].set(str(value))
        self.suspend = False
        self.schedule_preview()

    def current_path(self):
        selection = self.filelist.curselection()
        return self.paths[selection[0]] if selection else None

    def add_paths(self, paths):
        for path in paths:
            p = Path(path).resolve()
            if p not in self.paths and p.suffix.lower() in (".jpg", ".jpeg"):
                self.paths.append(p)
                self.filelist.insert("end", p.name)
        if self.paths and not self.filelist.curselection():
            self.filelist.selection_set(0)
            self.select_file()

    def add_files(self):
        self.add_paths(filedialog.askopenfilenames(filetypes=[("JPEG panoramas", "*.jpg *.jpeg *.JPG *.JPEG")]))

    def add_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.add_paths(sorted(Path(folder).iterdir()))

    def remove_file(self):
        path = self.current_path()
        if path:
            index = self.paths.index(path)
            self.paths.remove(path)
            self.per_file.pop(path, None)
            self.filelist.delete(index)
            if self.paths:
                self.filelist.selection_set(min(index, len(self.paths)-1))
            self.select_file()

    def select_file(self, event=None):
        path = self.current_path()
        if path in self.per_file:
            self.apply_settings(self.per_file[path])
        self.preview_image = None
        self.draw_preview()
        self.schedule_preview()

    def reset(self):
        self.apply_settings(Settings())

    def pin_settings(self):
        path = self.current_path()
        if not path:
            return
        try:
            self.per_file[path] = self.settings()
            index = self.paths.index(path)
            self.filelist.delete(index)
            self.filelist.insert(index, "* " + path.name)
            self.filelist.selection_set(index)
            self.status.set("Настройки закреплены за фото до закрытия приложения. Для переноса сохраните пресет.")
        except ConversionError as exc:
            messagebox.showerror("Настройки", str(exc))

    def open_preset(self):
        path = filedialog.askopenfilename(filetypes=[("JSON preset", "*.json")])
        if path:
            try:
                self.apply_settings(load_preset(Path(path)))
            except ConversionError as exc:
                messagebox.showerror("Пресет", str(exc))

    def write_preset(self):
        try:
            settings = self.settings()
            path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON preset", "*.json")])
            if path:
                save_preset(Path(path), settings)
        except (ConversionError, OSError) as exc:
            messagebox.showerror("Пресет", str(exc))

    def choose_ffmpeg(self):
        path = filedialog.askopenfilename(filetypes=[("FFmpeg", "*.exe"), ("Все файлы", "*")])
        if path:
            self.ffmpeg.set(path)

    def choose_output(self):
        path = filedialog.askdirectory()
        if path:
            self.output.set(path)

    def schedule_preview(self, *args):
        if self.suspend or self.closing:
            return
        self.generation += 1
        self.preview_cancel.set()
        if self.preview_future:
            self.preview_future.cancel()
        if self.timer:
            self.after_cancel(self.timer)
        self.timer = self.after(280, self.start_preview)

    def start_preview(self):
        self.timer = None
        path = self.current_path()
        if not path:
            return
        try:
            settings = self.settings()
            ffmpeg = find_ffmpeg(self.ffmpeg.get())
        except ConversionError as exc:
            self.status.set(str(exc))
            return
        # Preserve aspect ratio while limiting preview cost. Export uses full resolution.
        height = settings.width if settings.views == 6 else settings.height
        scale = min(1, 720 / settings.width, 460 / height)
        settings = replace(settings, width=max(64, round(settings.width * scale)), height=max(64, round(height * scale)))
        face_index = ["Основной", "Справа", "Сзади", "Слева", "Сверху", "Снизу"].index(self.face.get())
        yaw, pitch = [(0, 0), (90, 0), (180, 0), (-90, 0), (0, 90), (0, -90)][face_index]
        if settings.views == 1:
            yaw, pitch = 0, 0
        elif settings.views == 4 and face_index > 3:
            yaw, pitch = 0, 0
        self.preview_cancel = threading.Event()
        token, cancel = self.generation, self.preview_cancel
        self.meta.set("Рассчитываю предпросмотр…")

        def worker():
            try:
                info = inspect_source(path)
                im = render(path, settings, ffmpeg, cancel, yaw, pitch)
                note = ""
                if info.icc:
                    try:
                        im = ImageCms.profileToProfile(im, ImageCms.ImageCmsProfile(io.BytesIO(info.icc)), ImageCms.createProfile("sRGB"), outputMode="RGB")
                    except Exception:
                        note = " • профиль не удалось применить к предпросмотру"
                self.events.put(("preview", token, im, f"{path.name}  •  {info.width} × {info.height}  •  ICC: {len(info.icc or b'')} байт" + note))
            except Cancelled:
                pass
            except Exception as exc:
                self.events.put(("preview_error", token, str(exc)))
        self.preview_future = self.preview_pool.submit(worker)

    def draw_preview(self):
        self.canvas.delete("all")
        w, h = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        if self.preview_image:
            im = self.preview_image.copy()
            im.thumbnail((w, h), Image.Resampling.LANCZOS)
            self.tk_preview = ImageTk.PhotoImage(im)
            self.canvas.create_image(w / 2, h / 2, image=self.tk_preview)
            self.canvas.create_line(w / 2-10, h / 2, w / 2+10, h / 2, fill="white")
            self.canvas.create_line(w / 2, h / 2-10, w / 2, h / 2+10, fill="white")
        else:
            self.canvas.create_text(w / 2, h / 2, text="Добавьте панораму JPEG 2:1\nи выберите FFmpeg", justify="center", fill=MUTED, font=("Segoe UI", 13))

    def drag_start(self, event):
        try:
            s = self.settings()
            self.drag_origin = (event.x, event.y, s.yaw, s.pitch)
        except ConversionError:
            self.drag_origin = None

    def drag_move(self, event):
        if getattr(self, "drag_origin", None):
            x, y, yaw, pitch = self.drag_origin
            self.vars["yaw"].set(str(round((yaw - (event.x-x)*0.25 + 180) % 360 - 180, 1)))
            self.vars["pitch"].set(str(round(max(-90, min(90, pitch + (event.y-y)*0.25)), 1)))

    def start_export(self):
        if self.export_future and not self.export_future.done():
            return
        try:
            settings = self.settings()
            ffmpeg = find_ffmpeg(self.ffmpeg.get())
            if not self.paths or not self.output.get().strip():
                raise ConversionError("Добавьте фотографии и выберите папку экспорта.")
            paths, output, per_file = list(self.paths), Path(self.output.get()), dict(self.per_file)
        except ConversionError as exc:
            messagebox.showerror("Экспорт", str(exc))
            return
        self.export_cancel = threading.Event()
        self.export_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.progressbar["value"] = 0
        self.status.set("Экспорт начат. Настройки этого запуска зафиксированы.")
        def worker():
            try:
                check_ffmpeg(ffmpeg)
                report = batch_export(paths, output, settings, ffmpeg, self.export_cancel,
                                      lambda done, total, name: self.events.put(("progress", done, total, name)), per_file)
                self.events.put(("done", report))
            except Exception as exc:
                self.events.put(("export_error", str(exc)))
        self.export_future = self.export_pool.submit(worker)

    def poll(self):
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "preview" and event[1] == self.generation:
                    self.preview_image = event[2]
                    self.meta.set(event[3])
                    self.draw_preview()
                elif kind == "preview_error" and event[1] == self.generation:
                    self.preview_image = None
                    self.draw_preview()
                    self.meta.set(event[2][:160])
                elif kind == "progress":
                    self.progressbar["value"] = event[1] / event[2] * 100
                    self.status.set(f"{event[1]} / {event[2]}  •  {event[3]}")
                elif kind in ("done", "export_error"):
                    self.export_button.configure(state="normal")
                    self.cancel_button.configure(state="disabled")
                    if kind == "done":
                        self.last_report = event[1]
                        r = event[1]
                        self.result_button.configure(state="normal")
                        self.status.set(f"{'Отменено' if r['cancelled'] else 'Готово'}: {len(r['files'])} JPEG, ошибок: {len(r['errors'])}. Подробности в report.json.")
                        if r["errors"] and not self.closing:
                            messagebox.showwarning("Ошибки экспорта", "\n".join(f"{x['source']}: {x['error']}" for x in r["errors"])[:3000])
                    else:
                        self.status.set(event[1])
                        if not self.closing:
                            messagebox.showerror("Экспорт", event[1])
        except queue.Empty:
            pass
        if self.closing and (not self.export_future or self.export_future.done()) and (not self.preview_future or self.preview_future.done()):
            self.preview_pool.shutdown(wait=False, cancel_futures=True)
            self.export_pool.shutdown(wait=False, cancel_futures=True)
            self.destroy()
        else:
            self.after(80, self.poll)

    def open_result(self):
        if self.last_report and os.name == "nt":
            os.startfile(self.last_report["folder"])

    def close(self):
        self.closing = True
        self.preview_cancel.set()
        self.export_cancel.set()
        if self.timer:
            self.after_cancel(self.timer)
        self.status.set("Завершаю обработку и сохраняю отчёт…")


def main():
    App().mainloop()
