from __future__ import annotations

import re
import struct
from pathlib import Path
from xml.etree import ElementTree


def image_dimensions(path: Path) -> tuple[int | None, int | None]:
    with path.open('rb') as stream:
        header = stream.read(64)
        if header.startswith(b'\x89PNG\r\n\x1a\n') and len(header) >= 24:
            return struct.unpack('>II', header[16:24])
        if header[:6] in (b'GIF87a', b'GIF89a') and len(header) >= 10:
            return struct.unpack('<HH', header[6:10])
        if header[:2] == b'\xff\xd8':
            stream.seek(2)
            while True:
                marker = stream.read(1)
                if not marker:
                    break
                if marker != b'\xff':
                    continue
                code = stream.read(1)
                while code == b'\xff':
                    code = stream.read(1)
                if not code or code in (b'\xd8', b'\xd9'):
                    continue
                size_bytes = stream.read(2)
                if len(size_bytes) < 2:
                    break
                size = int.from_bytes(size_bytes, 'big')
                if size < 2:
                    break
                if code[0] in (0xC0,0xC1,0xC2,0xC3,0xC5,0xC6,0xC7,0xC9,0xCA,0xCB,0xCD,0xCE,0xCF):
                    block = stream.read(5)
                    if len(block) == 5:
                        return int.from_bytes(block[3:5], 'big'), int.from_bytes(block[1:3], 'big')
                    break
                stream.seek(size - 2, 1)
        if header[:4] == b'RIFF' and header[8:12] == b'WEBP':
            if header[12:16] == b'VP8X' and len(header) >= 30:
                return int.from_bytes(header[24:27], 'little') + 1, int.from_bytes(header[27:30], 'little') + 1
            if header[12:16] == b'VP8 ' and len(header) >= 30 and header[23:26] == b'\x9d\x01\x2a':
                return int.from_bytes(header[26:28], 'little') & 0x3fff, int.from_bytes(header[28:30], 'little') & 0x3fff
            if header[12:16] == b'VP8L' and len(header) >= 25 and header[20] == 0x2f:
                packed = int.from_bytes(header[21:25], 'little')
                return (packed & 0x3fff) + 1, ((packed >> 14) & 0x3fff) + 1
    if path.suffix.lower() == '.svg':
        try:
            root = ElementTree.parse(path).getroot()
            def dimension(name: str) -> int | None:
                value = root.get(name, '')
                match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*(?:px)?\s*', value)
                return round(float(match.group(1))) if match else None
            width, height = dimension('width'), dimension('height')
            if width and height:
                return width, height
            box = root.get('viewBox', '').replace(',', ' ').split()
            if len(box) == 4:
                return width or round(float(box[2])), height or round(float(box[3]))
        except (ValueError, ElementTree.ParseError):
            pass
    return None, None
