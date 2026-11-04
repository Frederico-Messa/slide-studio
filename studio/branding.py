from __future__ import annotations

import html
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}\Z")


@dataclass(frozen=True)
class Branding:
    name: str = "Slide Studio"
    mark: str = ""
    logo: str = ""
    accent_light: str = "#346b99"
    accent_dark: str = "#317cae"
    slide_accent: str = "#346b99"

    @classmethod
    def load(cls, root: Path) -> Branding:
        path = root / "branding.toml"
        if not path.is_file():
            return cls()
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        allowed = set(cls.__dataclass_fields__)
        if not isinstance(data, dict) or set(data) - allowed:
            raise ValueError("Unknown branding configuration keys")
        if any(not isinstance(value, str) for value in data.values()):
            raise ValueError("Branding values must be strings")
        result = cls(**data)
        if not result.name.strip() or len(result.name) > 100 or len(result.mark) > 24:
            raise ValueError("Invalid application name or mark")
        for color in (result.accent_light, result.accent_dark, result.slide_accent):
            if not HEX_COLOR.fullmatch(color):
                raise ValueError("Branding colors must be #RRGGBB")
        result.logo_path(root)
        return result

    def logo_path(self, root: Path) -> Path | None:
        if not self.logo:
            return None
        logo = Path(self.logo)
        if logo.is_absolute() or ".." in logo.parts or len(logo.parts) != 2 or logo.parts[0] != "branding" or logo.suffix.lower() not in (".svg", ".png", ".webp"):
            raise ValueError("Branding logo must be a file under branding/")
        resolved = (root / logo).resolve()
        if not resolved.is_relative_to((root / "branding").resolve()) or not resolved.is_file():
            raise ValueError("Branding logo not found")
        return resolved

    def mark_html(self) -> str:
        if self.logo:
            return f'<img class="brand-logo" src="/branding/logo" alt="{html.escape(self.mark or self.name, quote=True)}">'
        mark = html.escape(self.mark)
        if mark.endswith("."):
            return mark[:-1] + "<span>.</span>"
        return mark

    def favicon(self) -> bytes:
        mark = html.escape(self.mark)
        size = 23 if len(mark) >= 4 else 30
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="12" fill="{self.accent_light}"/><text x="32" y="34" font-family="sans-serif" font-size="{size}" font-weight="700" fill="white" text-anchor="middle" dominant-baseline="middle">{mark}</text></svg>'''
        return svg.encode("utf-8")

    def stylesheet(self) -> str:
        return f""":root {{
  --accent: {self.accent_light};
  --accent-hover: color-mix(in srgb, var(--accent), black 15%);
  --accent-text: color-mix(in srgb, var(--accent), black 10%);
  --accent-soft: color-mix(in srgb, var(--accent), white 28%);
  --border-accent: color-mix(in srgb, var(--accent), white 52%);
  --surface-accent: color-mix(in srgb, var(--accent), white 96%);
}}
:root[data-theme="dark"] {{
  --accent: {self.accent_dark};
  --accent-hover: color-mix(in srgb, var(--accent), white 12%);
  --accent-text: color-mix(in srgb, var(--accent), white 20%);
  --accent-soft: color-mix(in srgb, var(--accent), black 15%);
  --border-accent: color-mix(in srgb, var(--accent), black 42%);
  --surface-accent: color-mix(in srgb, var(--accent), #20242e 85%);
}}
"""

    def presentation_stylesheet(self) -> str:
        return """.reveal { font-family: 'Liberation Sans', Arial, sans-serif; color: #171717; }
.reveal h1, .reveal h2, .reveal h3 { font-family: 'Liberation Sans', Arial, sans-serif; color: #171717; text-transform: none; font-weight: 700; letter-spacing: -.035em; }
""" + f""".reveal h2 {{ border-left: .12em solid {self.slide_accent}; padding-left: .35em; }}
.reveal a {{ color: {self.slide_accent}; }}
.reveal .progress {{ color: {self.slide_accent}; }}
""" + """.reveal .slide-number { color: #777; font-size: 15px; }
.reveal .slides section { text-align: left; }
.reveal .slides section img { border: 0; box-shadow: none; }
"""
