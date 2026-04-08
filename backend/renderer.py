"""Subtitle renderer — generates ASS subtitles and burns them into video via FFmpeg."""

import os
import subprocess
import tempfile
from pathlib import Path
from typing import List

DEFAULT_FONT_CONFIG = {
    "family": "Noto Sans TC",
    "size": 48,
    "color": "#FFFFFF",
    "outline_color": "#000000",
    "outline_width": 2,
    "position": "bottom",
    "margin_bottom": 40,
}


def hex_to_ass_color(hex_color: str) -> str:
    """Convert #RRGGBB hex color to ASS &H00BBGGRR format."""
    hex_color = hex_color.lstrip("#")
    r = hex_color[0:2]
    g = hex_color[2:4]
    b = hex_color[4:6]
    return f"&H00{b.upper()}{g.upper()}{r.upper()}"


def seconds_to_ass_time(seconds: float) -> str:
    """Convert seconds to ASS time format H:MM:SS.cc (centiseconds)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds % 1) * 100))
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


class SubtitleRenderer:
    def __init__(self, renders_dir: Path):
        self._renders_dir = Path(renders_dir)
        self._renders_dir.mkdir(parents=True, exist_ok=True)

    def generate_ass(self, segments: List[dict], font_config: dict) -> str:
        """Generate an ASS subtitle file string from segments and font config."""
        family = font_config.get("family", DEFAULT_FONT_CONFIG["family"])
        size = font_config.get("size", DEFAULT_FONT_CONFIG["size"])
        primary = hex_to_ass_color(font_config.get("color", DEFAULT_FONT_CONFIG["color"]))
        outline = hex_to_ass_color(font_config.get("outline_color", DEFAULT_FONT_CONFIG["outline_color"]))
        outline_width = font_config.get("outline_width", DEFAULT_FONT_CONFIG["outline_width"])
        margin_v = font_config.get("margin_bottom", DEFAULT_FONT_CONFIG["margin_bottom"])

        lines = []
        lines.append("[Script Info]")
        lines.append("Title: Broadcast Subtitles")
        lines.append("ScriptType: v4.00+")
        lines.append("PlayResX: 1920")
        lines.append("PlayResY: 1080")
        lines.append("")
        lines.append("[V4+ Styles]")
        lines.append(
            "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, "
            "Bold, Italic, BorderStyle, Outline, Shadow, Alignment, "
            "MarginL, MarginR, MarginV"
        )
        lines.append(
            f"Style: Default,{family},{size},{primary},{outline},"
            f"0,0,1,{outline_width},0,2,10,10,{margin_v}"
        )
        lines.append("")
        lines.append("[Events]")
        lines.append(
            "Format: Layer, Start, End, Style, Name, "
            "MarginL, MarginR, MarginV, Effect, Text"
        )

        for seg in segments:
            start = seconds_to_ass_time(seg["start"])
            end = seconds_to_ass_time(seg["end"])
            text = seg.get("zh_text", "")
            lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")

        return "\n".join(lines) + "\n"

    def render(
        self,
        video_path: str,
        ass_content: str,
        output_path: str,
        output_format: str,
    ) -> bool:
        """Burn ASS subtitles into video using FFmpeg. Returns True on success."""
        ass_file = None
        try:
            fd, ass_file = tempfile.mkstemp(suffix=".ass")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(ass_content)

            if output_format == "mxf":
                cmd = [
                    "ffmpeg", "-y", "-i", video_path,
                    "-vf", f"ass={ass_file}",
                    "-c:v", "prores_ks", "-profile:v", "3",
                    "-c:a", "pcm_s16le",
                    output_path,
                ]
            else:
                cmd = [
                    "ffmpeg", "-y", "-i", video_path,
                    "-vf", f"ass={ass_file}",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                    "-c:a", "aac", "-b:a", "192k",
                    output_path,
                ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            return result.returncode == 0
        except Exception as e:
            print(f"Render error: {e}")
            return False
        finally:
            if ass_file and os.path.exists(ass_file):
                os.remove(ass_file)
