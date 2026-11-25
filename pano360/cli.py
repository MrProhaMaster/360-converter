import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

from .core import Settings, batch_export, find_ffmpeg, check_ffmpeg, load_preset, ConversionError


def main(argv=None):
    p = argparse.ArgumentParser(description="Офлайн-конвертер эквиректангулярных JPEG 360°")
    p.add_argument("input", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--ffmpeg", default="")
    p.add_argument("--preset", type=Path)
    for name in ("yaw", "pitch", "roll", "fov"):
        p.add_argument("--" + name, type=float)
    for name in ("width", "height", "quality", "views"):
        p.add_argument("--" + name, type=int)
    args = p.parse_args(argv)
    try:
        base = asdict(load_preset(args.preset) if args.preset else Settings())
        base.update({k: getattr(args, k) for k in base if getattr(args, k) is not None})
        options = Settings(**base).validate()
        ffmpeg = find_ffmpeg(args.ffmpeg)
        check_ffmpeg(ffmpeg)
        sources = sorted(x for x in args.input.iterdir() if x.suffix.lower() in (".jpg", ".jpeg")) if args.input.is_dir() else [args.input]
        report = batch_export(sources, args.output, options, ffmpeg)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if report["errors"] else 0
    except (ConversionError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
