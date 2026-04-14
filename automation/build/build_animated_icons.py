# -*- coding: utf-8 -*-
"""
Генерация анимированных GIF для ИИА_ДлительнаяОперация (спиннер в стиле ИИ Агент).

Создаёт GIF 85-400 px и zip-архив по формату ИИА_ДлительнаяОперация.

Требования: pip install Pillow

Использование:
    python build_animated_icons.py
"""
from __future__ import annotations

import math
import os
import zipfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
OUT_DIR = os.path.join(PROJECT_ROOT, "assets", "ИИА_ДлительнаяОперация")
ICON_SIZES = {85: 41, 100: 48, 125: 60, 150: 72, 175: 84, 200: 96, 300: 144, 400: 192}
FRAMES = 12
DURATION_MS = 80


def draw_dots_frame(size: int, frame: int) -> "Image.Image":
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    r = max(1, size // 6)
    gap = max(2, size // 5)
    cx, cy = size / 2, size / 2
    for i in range(3):
        phase = (frame + i * 4) % 12
        y_off = abs(6 - phase) * (size / 20)
        x = cx - gap + i * gap
        y = cy - y_off
        draw.ellipse([x - r, y - r, x + r, y + r], fill=(0, 0, 0, 255), outline=(60, 60, 60, 200))
    return img


def main() -> int:
    try:
        from PIL import Image
    except ImportError:
        print("Требуется Pillow: pip install Pillow")
        return 1

    os.makedirs(OUT_DIR, exist_ok=True)

    for density, px_size in ICON_SIZES.items():
        frames = []
        for i in range(FRAMES):
            frame = draw_dots_frame(px_size, i)
            frames.append(frame)
        gif_path = os.path.join(OUT_DIR, f"{density}.gif")
        frames[0].save(
            gif_path,
            save_all=True,
            append_images=frames[1:],
            duration=DURATION_MS,
            loop=0,
            disposal=2,
        )
        print(f"  {density}.gif ({px_size}x{px_size})")

    manifest = os.path.join(OUT_DIR, "manifest.xml")
    with open(manifest, "w", encoding="utf-8", newline="\n") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write("<Picture>\n")
        for d in ICON_SIZES:
            sd = {85: "bldpi", 100: "ldpi", 125: "aldpi", 150: "mdpi", 175: "amdpi", 200: "hdpi", 300: "xdpi", 400: "udpi"}[d]
            f.write(f'\t<PictureVariant name="{d}.gif" screenDensity="{sd}"/>\n')
        f.write(f'\t<PictureVariant name="Picture.gif" screenDensity="ldpi" interfaceVariant="version8_2"/>\n')
        f.write(f'\t<PictureVariant name="Picture.gif" screenDensity="ldpi" interfaceVariant="version8_2_OrdinaryApp"/>\n')
        f.write(f'\t<PictureVariant name="Picture.svg" screenDensity="ldpi" interfaceVariant="version8_5" theme="" isTemplate="false"/>\n')
        f.write("</Picture>\n")
    print("  manifest.xml")

    svg_src = os.path.join(PROJECT_ROOT, "assets", "icons", "ИИА_ДлительнаяОперация.svg")
    if os.path.isfile(svg_src):
        import shutil
        shutil.copy(svg_src, os.path.join(OUT_DIR, "Picture.svg"))
        print("  Picture.svg")

    zip_path = os.path.join(PROJECT_ROOT, "bin", "ИИА_ДлительнаяОперация.zip")
    os.makedirs(os.path.dirname(zip_path), exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in ["manifest.xml"] + [f"{d}.gif" for d in sorted(ICON_SIZES)]:
            path = os.path.join(OUT_DIR, name)
            if os.path.isfile(path):
                zf.write(path, name)
        gif_100 = os.path.join(OUT_DIR, "100.gif")
        if os.path.isfile(gif_100):
            zf.write(gif_100, "Picture.gif")
        svg_path = os.path.join(OUT_DIR, "Picture.svg")
        if os.path.isfile(svg_path):
            zf.write(svg_path, "Picture.svg")
    print(f"\nАрхив: {zip_path}")
    print(f"\nГотово. Папка: {OUT_DIR}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
