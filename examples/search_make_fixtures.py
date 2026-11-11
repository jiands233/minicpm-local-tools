"""Generate clearly synthetic PDF fixtures for real local OCR/search smoke tests.

Run: uv run --extra pdf python examples/search_make_fixtures.py .local/search-fixtures
No user documents are read; existing files are never overwritten.
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def write_new(path, data):
    with path.open("xb") as stream:
        stream.write(data)


def text_pdf(lines):
    commands = ["BT /F1 16 Tf 40 740 Td"]
    for index, line in enumerate(lines):
        if index:
            commands.append("0 -30 Td")
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        commands.append(f"({escaped}) Tj")
    commands.append("ET")
    content = "\n".join(commands).encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream",
    ]
    result = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(result))
        result.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(result)
    result.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        result.extend(f"{offset:010d} 00000 n \n".encode())
    result.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(result)


def main():
    directory = Path(sys.argv[1] if len(sys.argv) > 1 else ".local/search-fixtures")
    directory.mkdir(parents=True, exist_ok=True)
    write_new(
        directory / "text-marine.pdf",
        text_pdf(
            [
                "SYNTHETIC DEMO: Marine biology notes",
                "Blue whales are ocean mammals. They breathe air.",
                "Blue whales eat krill and surface to breathe.",
            ]
        ),
    )
    image = Image.new("RGB", (1600, 1000), "white")
    font_path = Path("/System/Library/Fonts/STHeiti Medium.ttc")
    if not font_path.is_file():
        raise SystemExit("Chinese fixture requires macOS STHeiti font; supply a local CJK font.")
    font = ImageFont.truetype(str(font_path), 45)
    draw = ImageDraw.Draw(image)
    lines = [
        "演示用合成课程通知 / SYNTHETIC DEMO",
        "数学课程通知",
        "请在周五下午三点前提交矩阵求逆作业。",
        "负责人：张老师。",
        "Math homework is due Friday at 3 PM.",
    ]
    for i, line in enumerate(lines):
        draw.text((75, 90 + i * 140), line, font=font, fill="black")
    with (directory / "scan-notice.png").open("xb") as stream:
        image.save(stream, "PNG")
    with (directory / "scan-notice.pdf").open("xb") as stream:
        image.save(stream, "PDF", resolution=144)
    print(f"Generated synthetic fixtures in {directory.resolve()}")


if __name__ == "__main__":
    main()
