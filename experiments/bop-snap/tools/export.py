#!/usr/bin/env python3
"""Export the 72 transparent BOP frames to MP4, VP9/WebM and GIF."""

from __future__ import annotations

import argparse
import base64
import io
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

# PowerShell-launched Python can inherit a legacy Windows code page that cannot
# print Russian diagnostics or the Unicode range in argparse help.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

FPS = 24
FRAME_COUNT = 72
ROOT = Path(__file__).resolve().parents[1]
BG_COLOR = "0x20283a"
EMBEDDED_FRAME_MAX_SIZE = (256, 256)


def fail(message: str) -> None:
    raise SystemExit(f"Ошибка экспорта: {message}")


def tool_path(name: str, override: str | None) -> str:
    found = override or shutil.which(name)
    if not found:
        fail(f"не найден {name}. Установите FFmpeg локально и повторите запуск.")
    return found


def run(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        fail(f"команда завершилась с кодом {result.returncode}:\n{result.stderr[-5000:]}")
    return result.stdout


def inspect_frames(folder: Path) -> tuple[int, int, bool]:
    expected = [folder / f"{n:04d}.png" for n in range(FRAME_COUNT)]
    missing = [p.name for p in expected if not p.is_file()]
    if missing:
        fail(f"ожидаются PNG {expected[0].name}–{expected[-1].name}; отсутствуют: {', '.join(missing[:8])}")
    unexpected = sorted(p.name for p in folder.glob("*.png") if p.name not in {f"{n:04d}.png" for n in range(FRAME_COUNT)})
    if unexpected:
        fail(f"в папке найдены лишние PNG: {', '.join(unexpected[:8])}")
    size: tuple[int, int] | None = None
    transparent = False
    for path in expected:
        try:
            with Image.open(path) as image:
                image.load()
                if image.mode != "RGBA":
                    fail(f"{path.name}: нужен PNG RGBA, получен режим {image.mode}")
                if image.width != image.height:
                    fail(f"{path.name}: кадр должен быть квадратным, получено {image.width}×{image.height}")
                if size is None:
                    size = image.size
                elif image.size != size:
                    fail(f"{path.name}: размер {image.width}×{image.height} отличается от {size[0]}×{size[1]}")
                if image.getchannel("A").getextrema()[0] < 255:
                    transparent = True
        except OSError as exc:
            fail(f"не удалось прочитать {path.name}: {exc}")
    assert size is not None
    return size[0], size[1], transparent


def probe_json(ffprobe: str, path: Path, *extra: str) -> dict:
    output = run([ffprobe, "-v", "error", *extra, "-of", "json", str(path)])
    return json.loads(output)


def verify_video(ffprobe: str, path: Path, codec: str, fps: str, count: int, duration: float, width: int, height: int) -> None:
    data = probe_json(ffprobe, path, "-count_frames", "-show_streams", "-show_format")
    streams = [stream for stream in data.get("streams", []) if stream.get("codec_type") == "video"]
    if not streams:
        fail(f"{path.name}: видеопоток не найден")
    stream = streams[0]
    if stream.get("codec_name") != codec:
        fail(f"{path.name}: ожидался кодек {codec}, получен {stream.get('codec_name')}")
    if stream.get("avg_frame_rate") != fps:
        fail(f"{path.name}: ожидалась частота {fps}, получена {stream.get('avg_frame_rate')}")
    if int(stream.get("width", 0)) != width or int(stream.get("height", 0)) != height:
        fail(f"{path.name}: размер {stream.get('width')}×{stream.get('height')}, ожидался {width}×{height}")
    frames = int(stream.get("nb_read_frames", -1))
    if frames != count:
        fail(f"{path.name}: ожидалось {count} кадров, прочитано {frames}")
    actual = float(data.get("format", {}).get("duration", 0))
    if abs(actual - duration) > 0.03:
        fail(f"{path.name}: длительность {actual:.3f} с, ожидалось {duration:.2f} с")


def verify_webm_alpha(ffmpeg: str, ffprobe: str, path: Path, source_has_alpha: bool, tmp: Path) -> None:
    # Decode the encoded alpha plane itself; ffprobe's pix_fmt often omits VP9 alpha.
    raw = tmp / "webm-alpha.gray"
    # FFmpeg's native VP9 decoder does not expose the WebM alpha payload;
    # force libvpx for this QA decode, as it does preserve yuva420p.
    run([ffmpeg, "-v", "error", "-c:v", "libvpx-vp9", "-i", str(path), "-vf", "alphaextract", "-f", "rawvideo", "-pix_fmt", "gray", "-y", str(raw)])
    data = raw.read_bytes()
    pixels_per_frame = 0
    stream_data = probe_json(ffprobe, path, "-show_streams")
    stream = next((s for s in stream_data.get("streams", []) if s.get("codec_type") == "video"), None)
    if not stream:
        fail("greeting.webm: видеопоток не найден")
    if stream.get("tags", {}).get("alpha_mode") != "1":
        fail("greeting.webm: контейнер не помечает видеопоток как содержащий прозрачность")
    pixels_per_frame = int(stream["width"]) * int(stream["height"])
    if len(data) != pixels_per_frame * FRAME_COUNT:
        fail("greeting.webm: не удалось декодировать alpha-plane всех 72 кадров")
    lo, hi = min(data), max(data)
    if source_has_alpha and lo >= 250:
        fail(f"greeting.webm: прозрачность потеряна (alpha {lo}..{hi})")


def write_gallery(webm: Path, frames: Path, output: Path) -> None:
    template = Path(__file__).parent / "delivery" / "gallery-template.html"
    if not template.is_file():
        fail(f"не найден шаблон автономной галереи: {template}")
    video_uri = "data:video/webm;base64," + base64.b64encode(webm.read_bytes()).decode("ascii")
    frame_uris: list[str] = []
    for index in range(FRAME_COUNT):
        image_path = frames / f"{index:04d}.png"
        with Image.open(image_path) as source:
            preview = source.copy()
            preview.thumbnail(EMBEDDED_FRAME_MAX_SIZE, Image.Resampling.LANCZOS)
            payload = io.BytesIO()
            preview.save(payload, format="PNG", optimize=True, compress_level=9)
        frame_uris.append("data:image/png;base64," + base64.b64encode(payload.getvalue()).decode("ascii"))
    html = template.read_text(encoding="utf-8")
    html = html.replace("__WEBM_DATA_URI__", video_uri)
    html = html.replace("__FRAME_DATA_JSON__", json.dumps(frame_uris, separators=(",", ":")))
    if "__WEBM_DATA_URI__" in html or "__FRAME_DATA_JSON__" in html:
        fail("шаблон галереи содержит незаполненные встроенные ресурсы")
    gallery_path = output / "gallery.html"
    gallery_path.write_text(html, encoding="utf-8", newline="\n")
    print(f"Автономная галерея создана: {gallery_path.resolve()} ({gallery_path.stat().st_size:,} байт).")


def export(frames: Path, output: Path, ffmpeg: str, ffprobe: str) -> None:
    width, height, source_has_alpha = inspect_frames(frames)
    output.mkdir(parents=True, exist_ok=True)
    sequence = str(frames / "%04d.png")
    with tempfile.TemporaryDirectory(prefix="bop-export-", dir=output) as temp_dir:
        tmp = Path(temp_dir)
        mp4, webm, gif = (tmp / "greeting.mp4", tmp / "greeting.webm", tmp / "greeting.gif")
        common = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-framerate", str(FPS), "-start_number", "0", "-i", sequence, "-frames:v", str(FRAME_COUNT)]
        run(common + ["-vf", f"color=c={BG_COLOR}:s={width}x{height}:r={FPS}[bg];[bg][0:v]overlay=shortest=1:format=auto,format=yuv420p", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-an", "-movflags", "+faststart", str(mp4)])
        run(common + ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-lossless", "1", "-auto-alt-ref", "0", "-deadline", "good", "-cpu-used", "2", "-threads", "1", "-row-mt", "0", "-flags:v", "+bitexact", "-fflags", "+bitexact", "-an", str(webm)])
        # GIF time is quantized to 1/100 s. 25 fps makes 75 × 0.04 s = 3.00 s.
        gif_filter = "fps=25,split[a][b];[a]palettegen=stats_mode=full[p];[b][p]paletteuse=dither=sierra2_4a"
        gif_input = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-framerate", str(FPS), "-start_number", "0", "-i", sequence]
        run(gif_input + ["-filter_complex", gif_filter, "-loop", "0", "-an", str(gif)])

        verify_video(ffprobe, mp4, "h264", "24/1", FRAME_COUNT, 3.0, width, height)
        verify_video(ffprobe, webm, "vp9", "24/1", FRAME_COUNT, 3.0, width, height)
        verify_video(ffprobe, gif, "gif", "25/1", 75, 3.0, width, height)
        verify_webm_alpha(ffmpeg, ffprobe, webm, source_has_alpha, tmp)
        for artifact in (mp4, webm, gif):
            destination = output / artifact.name
            destination_temp = destination.with_suffix(destination.suffix + ".tmp")
            shutil.copy2(artifact, destination_temp)
            destination_temp.replace(destination)
        write_gallery(output / "greeting.webm", frames, output)
    print(f"Экспорт проверен: {output.resolve()}")
    print(f"Кадры: {FRAME_COUNT}, {FPS} fps, {width}×{height}, видео 3.000 с, GIF 75 кадров / 3.000 с.")
    print(f"WebM VP9 alpha: {'прозрачные пиксели найдены' if source_has_alpha else 'alpha-plane декодируется; исходник непрозрачен'}.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=Path, default=ROOT / "frames", help="папка с 0000.png…0071.png (RGBA)")
    parser.add_argument("--output", type=Path, default=ROOT, help="папка для greeting.*")
    parser.add_argument("--ffmpeg", help="путь к локальному ffmpeg.exe")
    parser.add_argument("--ffprobe", help="путь к локальному ffprobe.exe")
    args = parser.parse_args()
    ffmpeg = tool_path("ffmpeg", args.ffmpeg)
    ffprobe = tool_path("ffprobe", args.ffprobe or (str(Path(ffmpeg).with_name("ffprobe.exe")) if Path(ffmpeg).suffix.lower() == ".exe" else None))
    export(args.frames.resolve(), args.output.resolve(), ffmpeg, ffprobe)


if __name__ == "__main__":
    main()
