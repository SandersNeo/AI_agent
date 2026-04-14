# -*- coding: utf-8 -*-
"""
Экспорт SVG-иконки ИИ Агент в PNG разных размеров (формат ПодсистемаНалоги).

Одна папка: manifest.xml + 85.png, 100.png, 125.png, 150.png, 175.png, 200.png, 300.png, 400.png.

Способы экспорта (по приоритету):
  1. resvg_py (pip install resvg_py) — работает на Windows без Cairo
  2. cairosvg (pip install cairosvg) — требует Cairo на Windows
  3. Inkscape (если установлен и в PATH)

Использование:
    python export_icons.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import zipfile
import sys

# density -> pixel size (как в ПодсистемаНалоги: 100.png=16x16, 400.png=64x64)
ICON_SIZES = {
    85: 14,
    100: 16,
    125: 20,
    150: 24,
    175: 28,
    200: 32,
    300: 48,
    400: 64,
}
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
ICON_SVG = os.path.join(PROJECT_ROOT, "assets", "icons", "ИИА_Агент.svg")
ICON_PNG_SOURCE = os.path.join(PROJECT_ROOT, "temp", "ИИ Агент.png")
ICONS_OUT = os.path.join(PROJECT_ROOT, "assets", "ПодсистемаИИАгент")


def _export_from_png(source_png: str, png_path: str, size: int) -> bool:
    """Экспорт из исходного PNG: светлый фон -> прозрачный, иконка масштабируется в кадр."""
    try:
        from PIL import Image
        img = Image.open(source_png).convert("RGBA")
        w, h = img.size
        s = min(w, h)
        left = (w - s) // 2
        top = (h - s) // 2
        img = img.crop((left, top, left + s, top + s))
        data = list(img.getdata())
        new_data = []
        for r, g, b, a in data:
            if r > 140 and g > 140 and b > 140:
                new_data.append((0, 0, 0, 0))
            else:
                new_data.append((r, g, b, a))
        img.putdata(new_data)

        non_transparent = [(i % s, i // s) for i, p in enumerate(new_data) if p[3] > 0 and (p[0] < 100 or p[1] < 100 or p[2] < 100)]
        if not non_transparent:
            return False
        xs = [x for x, _ in non_transparent]
        ys = [y for _, y in non_transparent]
        x1, x2 = max(0, min(xs)), min(s, max(xs) + 1)
        y1, y2 = max(0, min(ys)), min(s, max(ys) + 1)
        img = img.crop((x1, y1, x2, y2))
        cw, ch = img.size
        scale = max(size / cw, size / ch) * 1.18
        nw, nh = int(cw * scale), int(ch * scale)
        img = img.resize((nw, nh), Image.Resampling.LANCZOS)
        left = (nw - size) // 2
        top = max(0, (nh - size) // 2 - size // 8)
        img = img.crop((left, top, left + size, top + size))
        img.save(png_path, "PNG")
        return True
    except Exception:
        return False


def _export_resvg(svg_path: str, png_path: str, size: int) -> bool:
    """Экспорт через resvg_py (работает на Windows без Cairo)."""
    try:
        import resvg_py
        with open(svg_path, "r", encoding="utf-8") as f:
            svg = f.read()
        svg = "".join(c for c in svg if ord(c) >= 32 or c in "\n\r\t")
        png = resvg_py.svg_to_bytes(svg_string=svg, width=size, height=size, background=None)
        with open(png_path, "wb") as f:
            f.write(png)
        return True
    except Exception:
        return False


def _export_cairo(svg_path: str, png_path: str, size: int) -> bool:
    try:
        import cairosvg
        cairosvg.svg2png(url=svg_path, write_to=png_path, output_width=size, output_height=size)
        return True
    except Exception:
        return False


def _export_inkscape(svg_path: str, png_path: str, size: int) -> bool:
    ink = shutil.which("inkscape")
    if not ink:
        for p in (r"C:\Program Files\Inkscape\bin\inkscape.exe", r"C:\Program Files (x86)\Inkscape\bin\inkscape.exe"):
            if os.path.isfile(p):
                ink = p
                break
    if not ink:
        return False
    try:
        subprocess.run(
            [ink, "--export-type=png", f"--export-filename={png_path}", f"--export-width={size}", f"--export-height={size}", svg_path],
            capture_output=True,
            timeout=30,
        )
        return os.path.isfile(png_path)
    except Exception:
        return False


def main() -> int:
    test_png = os.path.join(PROJECT_ROOT, "assets", "_test.png")
    exporter_ok = False
    if os.path.isfile(ICON_PNG_SOURCE):
        if _export_from_png(ICON_PNG_SOURCE, test_png, 64):
            exporter_ok = True
            print("Используется temp/ИИ Агент.png")
    if not exporter_ok and os.path.isfile(ICON_SVG):
        if _export_resvg(ICON_SVG, test_png, 64):
            exporter_ok = True
            print("Используется resvg_py")
        elif _export_cairo(ICON_SVG, test_png, 64):
            exporter_ok = True
            print("Используется cairosvg")
        elif _export_inkscape(ICON_SVG, test_png, 64):
            exporter_ok = True
            print("Используется Inkscape")
    if os.path.isfile(test_png):
        os.remove(test_png)
    if not exporter_ok:
        print("Не найден: temp/ИИ Агент.png, resvg_py, cairosvg, Inkscape.")
        return 1

    os.makedirs(ICONS_OUT, exist_ok=True)

    use_png_source = os.path.isfile(ICON_PNG_SOURCE)
    for density, px_size in ICON_SIZES.items():
        png_path = os.path.join(ICONS_OUT, f"{density}.png")
        ok = _export_from_png(ICON_PNG_SOURCE, png_path, px_size) if use_png_source else False
        if not ok:
            ok = _export_resvg(ICON_SVG, png_path, px_size)
        if not ok:
            ok = _export_cairo(ICON_SVG, png_path, px_size)
        if not ok:
            ok = _export_inkscape(ICON_SVG, png_path, px_size)
        if ok:
            print(f"  {density}.png ({px_size}x{px_size})")
        else:
            print(f"  Ошибка {density}px")

    manifest_path = os.path.join(ICONS_OUT, "manifest.xml")
    with open(manifest_path, "w", encoding="utf-8", newline="\n") as f:
        f.write('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n')
        f.write("<Picture>\n")
        for density in ICON_SIZES:
            d = {85: "bldpi", 100: "ldpi", 125: "aldpi", 150: "mdpi", 175: "amdpi", 200: "hdpi", 300: "xdpi", 400: "udpi"}[density]
            f.write(f'\t<PictureVariant name="{density}.png" screenDensity="{d}"/>\n')
        f.write("</Picture>\n")
    print(f"  manifest.xml")

    zip_path = os.path.join(PROJECT_ROOT, "bin", "ПодсистемаИИАгент.zip")
    os.makedirs(os.path.dirname(zip_path), exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        mf_path = os.path.join(ICONS_OUT, "manifest.xml")
        if os.path.isfile(mf_path):
            zf.write(mf_path, "manifest.xml", compress_type=zipfile.ZIP_DEFLATED)
        for d in sorted(ICON_SIZES):
            name = f"{d}.png"
            path = os.path.join(ICONS_OUT, name)
            if os.path.isfile(path):
                zf.write(path, name, compress_type=zipfile.ZIP_DEFLATED)
    print(f"\nАрхив: {zip_path}")

    print(f"\nГотово. Папка: {ICONS_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
