"""Bounded, in-memory preview. Export still uses the full-resolution FFmpeg path."""
from functools import lru_cache
import io
import math

import numpy as np
from PIL import Image, ImageCms

from .core import Cancelled, inspect_source


def rotation(yaw, pitch, roll):
    """Camera-to-panorama rotation: x right, y down, z forward; v360 ypr order."""
    y, p, r = map(math.radians, (yaw, pitch, roll))
    cy, sy, cp, sp, cr, sr = math.cos(y), math.sin(y), math.cos(p), math.sin(p), math.cos(r), math.sin(r)
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], dtype=np.float32)
    rx = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]], dtype=np.float32)
    rz = np.array([[cr, -sr, 0], [sr, cr, 0], [0, 0, 1]], dtype=np.float32)
    return ry @ rx @ rz


@lru_cache(maxsize=2)
def camera_rays(width, height, fov, aspect):
    # Pixel centres, with the aspect of the export rather than rounded preview dimensions.
    scale = math.tan(math.radians(fov / 2))
    x = ((np.arange(width, dtype=np.float32) + 0.5) * (2 / width) - 1) * scale
    y = ((np.arange(height, dtype=np.float32) + 0.5) * (2 / height) - 1) * scale * aspect
    x, y = np.meshgrid(x, y)
    z = 1 / np.sqrt(x * x + y * y + 1)
    return x * z, y * z, z


def project(pixels, settings, size, face_yaw=0, face_pitch=0):
    """Bilinear spherical sampling, including the seam and reflection over both poles."""
    fov = 90 if settings.views == 6 else settings.fov
    aspect = 1 if settings.views == 6 else settings.height / settings.width
    x, y, z = camera_rays(*size, fov, aspect)
    matrix = rotation(settings.yaw, settings.pitch, settings.roll)
    if settings.views != 1:
        matrix = matrix @ rotation(face_yaw, face_pitch, 0)
    rx = matrix[0, 0] * x + matrix[0, 1] * y + matrix[0, 2] * z
    ry = matrix[1, 0] * x + matrix[1, 1] * y + matrix[1, 2] * z
    rz = matrix[2, 0] * x + matrix[2, 1] * y + matrix[2, 2] * z
    height, width = pixels.shape[:2]
    u = (np.arctan2(rx, rz) / (2 * np.pi) + 0.5) * width - 0.5
    v = (np.arcsin(np.clip(ry, -1, 1)) / np.pi + 0.5) * height - 0.5
    x0, y0 = np.floor(u).astype(np.int32), np.floor(v).astype(np.int32)
    dx, dy = (u - x0).astype(np.float32)[..., None], (v - y0).astype(np.float32)[..., None]

    def row(ys):
        # Crossing a pole continues on the opposite meridian.
        xs = (x0 + ((ys < 0) | (ys >= height)) * (width // 2)) % width
        base = np.clip(ys, 0, height - 1) * width
        flat = pixels.reshape(-1, 3)
        # A single linear index avoids NumPy's costly multidimensional gather for RGB.
        a = np.take(flat, base + xs, axis=0, mode="clip").astype(np.float32)
        b = np.take(flat, base + (xs + 1) % width, axis=0, mode="clip").astype(np.float32)
        return a + (b - a) * dx

    top, bottom = row(y0), row(y0 + 1)
    return Image.fromarray(np.clip(top + (bottom - top) * dy, 0, 255).astype(np.uint8))


class PreviewRenderer:
    """Owned by the single preview worker; caches only the most recent panorama."""
    def __init__(self):
        self.key = None
        self.pixels = None
        self.description = ""

    def render(self, path, settings, size, face_yaw=0, face_pitch=0, cancel=None):
        def check_cancel():
            if cancel and cancel.is_set():
                raise Cancelled("Отменено")

        check_cancel()
        stat = path.stat()
        key = (path, stat.st_mtime_ns, stat.st_size)
        if key != self.key:
            info = inspect_source(path)
            check_cancel()
            with Image.open(path) as source:
                source.thumbnail((2048, 1024), Image.Resampling.LANCZOS)
                image = source.convert("RGB")
            note = ""
            try:
                if info.icc:
                    try:
                        corrected = ImageCms.profileToProfile(image, ImageCms.ImageCmsProfile(io.BytesIO(info.icc)),
                                                              ImageCms.createProfile("sRGB"), outputMode="RGB")
                        image.close()
                        image = corrected
                    except Exception:
                        note = " • профиль не удалось применить к предпросмотру"
                pixels = np.asarray(image).copy()
            finally:
                image.close()
            check_cancel()
            self.pixels, self.key = pixels, key
            self.description = f"{path.name}  •  {info.width} × {info.height}  •  ICC: {len(info.icc or b'')} байт" + note
        image = project(self.pixels, settings, size, face_yaw, face_pitch)
        if cancel and cancel.is_set():
            image.close()
            raise Cancelled("Отменено")
        return image, self.description
