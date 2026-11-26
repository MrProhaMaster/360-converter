"""Conversion engine. No UI, network, shell interpolation or persistent photo cache."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import warnings
from datetime import datetime

from PIL import Image

MAX_PIXELS = 80_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


class ConversionError(Exception):
    pass


class Cancelled(ConversionError):
    pass


@dataclass(frozen=True)
class Settings:
    yaw: float = 0
    pitch: float = 0
    roll: float = 0
    fov: float = 90
    width: int = 1024
    height: int = 768
    quality: int = 95
    views: int = 1

    def validate(self):
        for key, low, high in (("yaw", -180, 180), ("pitch", -90, 90),
                               ("roll", -180, 180), ("fov", 20, 140)):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not low <= value <= high:
                raise ConversionError(f"{key}: допустимо от {low} до {high}.")
        for key, low, high in (("width", 64, 8192), ("height", 64, 8192), ("quality", 1, 100)):
            value = getattr(self, key)
            if type(value) is not int or not low <= value <= high:
                raise ConversionError(f"{key}: требуется целое число от {low} до {high}.")
        if self.width * (self.width if self.views == 6 else self.height) > 32_000_000:
            raise ConversionError("Кадр ограничен 32 миллионами пикселей.")
        if type(self.views) is not int or self.views not in (1, 4, 6):
            raise ConversionError("Число видов: 1, 4 или 6.")
        return self


@dataclass(frozen=True)
class SourceInfo:
    width: int
    height: int
    icc: bytes | None


def inspect_source(path: Path) -> SourceInfo:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as im:
                if im.format != "JPEG":
                    raise ConversionError("Поддерживаются готовые панорамы JPEG 2:1.")
                if im.width != 2 * im.height or im.width * im.height > MAX_PIXELS:
                    raise ConversionError("Нужна полная эквиректангулярная панорама 2:1, не более 80 Мп.")
                if im.mode != "RGB":
                    raise ConversionError("Поддерживается RGB JPEG; сначала преобразуйте CMYK/серый JPEG в RGB.")
                if im.getexif().get(274, 1) != 1:
                    raise ConversionError("Сначала нормализуйте EXIF Orientation панорамы во внешнем редакторе.")
                info = SourceInfo(im.width, im.height, im.info.get("icc_profile"))
                im.load()  # Detect truncated data before launching the renderer.
                return info
    except ConversionError:
        raise
    except Exception as exc:
        raise ConversionError(f"Не удалось прочитать JPEG: {exc}") from exc


def bundled_ffmpeg() -> str | None:
    """Resolve the portable copy independently of cwd, PATH and Python installs."""
    if not getattr(sys, "frozen", False):
        return None
    roots = [Path(sys.executable).resolve().parent]
    if hasattr(sys, "_MEIPASS"):
        roots.append(Path(sys._MEIPASS))
    for root in roots:
        candidate = root / "bin" / "ffmpeg.exe"
        if candidate.is_file():
            return str(candidate.resolve())
    return None


def installed_ffmpeg() -> str | None:
    """The normal Python install includes FFmpeg in the imageio-ffmpeg wheel."""
    if getattr(sys, "frozen", False):
        return None  # Frozen builds have their own verified bin/ffmpeg.exe.
    try:
        import imageio_ffmpeg
        candidate = Path(imageio_ffmpeg.get_ffmpeg_exe())
        if candidate.is_file():
            return str(candidate.resolve())
    except (ImportError, RuntimeError, OSError):
        pass
    return None


def find_ffmpeg(explicit: str = "") -> str:
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise ConversionError("Указанный FFmpeg не найден.")
        return str(path.resolve())
    bundled = bundled_ffmpeg()
    if bundled:
        return bundled
    roots = [Path(sys.executable).parent, Path(__file__).resolve().parent.parent]
    if getattr(sys, "frozen", False):
        roots.insert(0, Path(getattr(sys, "_MEIPASS", roots[0])))
    for root in roots:
        for candidate in (root / "ffmpeg.exe", root / "bin" / "ffmpeg.exe"):
            if candidate.is_file():
                return str(candidate)
    installed = installed_ffmpeg()
    if installed:
        return installed
    found = shutil.which("ffmpeg")
    if found:
        return found
    if getattr(sys, "frozen", False):
        raise ConversionError("FFmpeg не найден. Распакуйте всю папку 360-конвертер из архива, включая bin и _internal.")
    raise ConversionError("FFmpeg не найден в зависимостях приложения. В папке исходников выполните: python -m pip install --upgrade .")


def run_process(args: list[str], cancel: threading.Event | None = None, timeout=180) -> bytes:
    if cancel and cancel.is_set():
        raise Cancelled("Отменено")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, creationflags=flags)
    except OSError as exc:
        raise ConversionError(f"Не удалось запустить FFmpeg: {exc}") from exc
    started = time.monotonic()
    try:
        while True:
            if cancel and cancel.is_set():
                raise Cancelled("Отменено")
            if time.monotonic() - started > timeout:
                raise ConversionError("FFmpeg превысил время ожидания (180 секунд).")
            try:
                data, error = proc.communicate(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                pass
        if proc.returncode:
            raise ConversionError(error.decode("utf-8", errors="replace")[-2000:].strip() or "Ошибка FFmpeg")
        return data
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.communicate()


def check_ffmpeg(executable: str) -> str:
    version = run_process([executable, "-version"], timeout=15).decode(errors="replace").splitlines()[0]
    filters = run_process([executable, "-hide_banner", "-filters"], timeout=15)
    if b" v360 " not in filters:
        raise ConversionError("В этой сборке FFmpeg отсутствует фильтр v360.")
    return version


def view_plan(settings: Settings):
    settings.validate()
    if settings.views == 1:
        return [("main", 0, 0)]
    result = [("front", 0, 0), ("right", 90, 0), ("back", 180, 0), ("left", -90, 0)]
    if settings.views == 6:
        result += [("up", 0, 90), ("down", 0, -90)]
    return result


def projection_filter(settings: Settings, face_yaw=0, face_pitch=0) -> str:
    settings.validate()
    w, h = settings.width, settings.height
    fov = settings.fov
    if settings.views == 6:
        h, fov = w, 90
    vfov = math.degrees(2 * math.atan(math.tan(math.radians(fov / 2)) * h / w))
    rotation = f"yaw={settings.yaw}:pitch={settings.pitch}:roll={settings.roll}:rorder=ypr"
    prefix = ""
    if settings.views != 1:
        # Correct the whole sphere first. All six faces share the same orientation.
        prefix = f"v360=input=e:output=e:interp=cubic:{rotation},"
        rotation = f"yaw={face_yaw}:pitch={face_pitch}:roll=0:rorder=ypr"
    return prefix + f"v360=input=e:output=flat:interp=cubic:w={w}:h={h}:h_fov={fov}:v_fov={vfov}:{rotation}"


def render(path: Path, settings: Settings, ffmpeg: str, cancel=None, face_yaw=0, face_pitch=0) -> Image.Image:
    data = run_process([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
                        "-noautorotate", "-i", str(path.resolve()), "-map", "0:v:0", "-an",
                        "-vf", projection_filter(settings, face_yaw, face_pitch), "-frames:v", "1",
                        "-threads", "1", "-f", "image2pipe", "-vcodec", "png", "-"], cancel)
    try:
        with Image.open(io.BytesIO(data)) as im:
            return im.convert("RGB")
    except Exception as exc:
        raise ConversionError("FFmpeg не вернул корректный кадр.") from exc


def publish_new(temp: Path, destination: Path):
    # Never use os.replace for photos: it would silently overwrite existing files.
    if os.name == "nt":
        os.rename(temp, destination)  # Windows rename fails when destination exists.
    else:
        os.link(temp, destination)
        temp.unlink()


def save_jpeg(image: Image.Image, destination: Path, quality: int, icc: bytes | None, sources=()):
    destination = Path(destination)
    resolved = destination.resolve()
    for source in sources:
        if resolved == Path(source).resolve() or (destination.exists() and os.path.samefile(destination, source)):
            raise ConversionError("Экспорт поверх исходной панорамы запрещён.")
    if destination.exists():
        raise ConversionError("Выходной файл уже существует.")
    fd, name = tempfile.mkstemp(prefix=".360_converter-", suffix=".tmp", dir=destination.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            # A fresh RGB image has no EXIF/XMP/IPTC inherited from the source.
            image.save(stream, "JPEG", quality=quality, subsampling=0, icc_profile=icc)
            stream.flush()
            os.fsync(stream.fileno())
        publish_new(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def save_preset(path: Path, settings: Settings):
    settings.validate()
    payload = {"schema_version": 1, "settings": asdict(settings)}
    path = Path(path)
    fd, name = tempfile.mkstemp(prefix=".preset-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def load_preset(path: Path) -> Settings:
    try:
        if Path(path).stat().st_size > 64_000:
            raise ValueError("Слишком большой файл пресета")
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        if data["schema_version"] != 1 or set(data) != {"schema_version", "settings"}:
            raise ValueError("Неизвестная схема пресета")
        return Settings(**data["settings"]).validate()
    except (ValueError, TypeError, KeyError, OSError) as exc:
        raise ConversionError(f"Некорректный пресет: {exc}") from exc


def batch_export(sources: list[Path], output: Path, settings: Settings, ffmpeg: str,
                 cancel=None, progress=None, per_file: dict[Path, Settings] | None = None) -> dict:
    settings.validate()
    if not sources:
        raise ConversionError("Добавьте хотя бы одну панораму.")
    sources = list(dict.fromkeys(Path(p).resolve() for p in sources))
    chosen = [((per_file or {}).get(p, settings)).validate() for p in sources]
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix=datetime.now().strftime("360-конвертер-%Y%m%d-%H%M%S-"), dir=output))
    report = {"schema_version": 1, "folder": str(folder), "files": [], "errors": [], "cancelled": False}
    total = sum(s.views for s in chosen)
    done = 0
    try:
        for index, (source, options) in enumerate(zip(sources, chosen), 1):
            try:
                if cancel and cancel.is_set():
                    raise Cancelled("Отменено")
                info = inspect_source(source)
                stem = re.sub(r'[^\w.-]', '_', source.stem, flags=re.UNICODE)[:70].strip(". ") or "panorama"
                for label, yaw, pitch in view_plan(options):
                    if cancel and cancel.is_set():
                        raise Cancelled("Отменено")
                    image = render(source, options, ffmpeg, cancel, yaw, pitch)
                    target = folder / f"{index:04d}_{stem}_{label}.jpg"
                    try:
                        if cancel and cancel.is_set():
                            raise Cancelled("Отменено")
                        save_jpeg(image, target, options.quality, info.icc, sources)
                    finally:
                        image.close()
                    report["files"].append({"source": source.name, "output": target.name,
                                            "view": label, "settings": asdict(options),
                                            "icc_bytes": len(info.icc or b"")})
                    done += 1
                    if progress:
                        progress(done, total, target.name)
            except Cancelled:
                report["cancelled"] = True
                break
            except (ConversionError, OSError) as exc:
                report["errors"].append({"source": source.name, "error": str(exc)})
                done += options.views - sum(1 for f in report["files"] if f["output"].startswith(f"{index:04d}_"))
                if progress:
                    progress(done, total, f"Ошибка: {source.name}")
    finally:
        # Manifest is local only. Absolute source paths are never recorded.
        (folder / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report
