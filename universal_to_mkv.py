#!/usr/bin/env python3
"""Universal video-to-MKV converter. Requires FFmpeg and ffprobe."""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

EXTENSIONS = {".avi", ".mp4", ".mov", ".wmv", ".flv", ".webm", ".mpeg", ".mpg", ".ts", ".mts", ".m2ts", ".vob", ".m4v", ".3gp", ".ogv", ".mkv"}

def executable(name, configured):
    path = configured or shutil.which(name)
    if not path or not (shutil.which(str(path)) or Path(path).is_file()):
        raise RuntimeError(f"No se encontró {name}. Instala FFmpeg o indica --{name}.")
    return str(path)

def probe(ffprobe, source):
    p = subprocess.run([ffprobe, "-v", "error", "-show_streams", "-show_format",
                        "-of", "json", str(source)], capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(p.stderr.strip() or "ffprobe falló")
    return json.loads(p.stdout)

def convert(ffmpeg, ffprobe, source, destination, mode):
    metadata = probe(ffprobe, source)
    streams = metadata.get("streams", [])
    if not any(s.get("codec_type") == "video" for s in streams):
        raise RuntimeError("El archivo no contiene una pista de video")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name(destination.stem + ".partial.mkv")
    if temp.exists():
        raise RuntimeError(f"Existe un archivo temporal previo: {temp}")
    args = [ffmpeg, "-hide_banner", "-nostdin", "-n", "-i", str(source),
            "-map", "0:v?", "-map", "0:a?", "-map", "0:s?",
            "-map_metadata", "0", "-map_chapters", "0"]
    if mode == "copy":
        args += ["-c", "copy"]
    else:
        args += ["-c:v", "libx264", "-preset", "medium", "-crf", "20",
                 "-c:a", "aac", "-b:a", "192k", "-c:s", "srt"]
    args += ["-f", "matroska", str(temp)]
    try:
        p = subprocess.run(args)
        if p.returncode:
            raise RuntimeError(f"FFmpeg terminó con código {p.returncode}")
        check = probe(ffprobe, temp)
        if not any(s.get("codec_type") == "video" for s in check.get("streams", [])):
            raise RuntimeError("La salida no contiene video")
        temp.replace(destination)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise

def main():
    parser = argparse.ArgumentParser(description="Convierte videos a MKV sin sobrescribir originales.")
    parser.add_argument("inputs", nargs="+", type=Path, help="Archivos o carpetas")
    parser.add_argument("--mode", choices=["copy", "encode"], default="copy",
                        help="copy: remux sin pérdida; encode: H.264 + AAC")
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--output", type=Path, help="Carpeta de salida (por defecto junto al original)")
    parser.add_argument("--ffmpeg", default="", help="Ruta a ffmpeg")
    parser.add_argument("--ffprobe", default="", help="Ruta a ffprobe")
    args = parser.parse_args()
    try:
        ffmpeg = executable("ffmpeg", args.ffmpeg)
        ffprobe = executable("ffprobe", args.ffprobe)
    except RuntimeError as error:
        parser.error(str(error))
    candidates = []
    for item in args.inputs:
        if item.is_file():
            candidates.append(item)
        elif item.is_dir():
            iterator = item.rglob("*") if args.recursive else item.glob("*")
            candidates.extend(p for p in iterator if p.is_file() and p.suffix.lower() in EXTENSIONS)
        else:
            print(f"No existe: {item}", file=sys.stderr)
    seen = set()
    failures = 0
    for source in candidates:
        if source.suffix.lower() not in EXTENSIONS:
            print(f"Omitido (extensión no reconocida): {source}")
            continue
        key = source.resolve()
        if key in seen:
            continue
        seen.add(key)
        destination = (args.output or source.parent) / (source.stem + ".mkv")
        if source.resolve() == destination.resolve() or destination.exists():
            print(f"Omitido (destino existente o igual al origen): {destination}")
            continue
        print(f"Convirtiendo: {source} -> {destination}", flush=True)
        try:
            convert(ffmpeg, ffprobe, source, destination, args.mode)
            print(f"OK: {destination}")
        except (RuntimeError, OSError, ValueError) as error:
            failures += 1
            print(f"ERROR: {source}: {error}", file=sys.stderr)
    return 1 if failures else 0

if __name__ == "__main__":
    sys.exit(main())
