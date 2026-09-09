"""Build pre-rotated footer glyphs for on-device FBInk blits.

FBInk cannot print text in the same orientation as our png_rotate=90 footer
(landscape board → right edge of the portrait PNG). Glyphs are drawn in
landscape, rotated like the boards, then stamped along that edge on the Kindle.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

import generate as g

CELL_H = 16
LAND_W = 1024
LAND_H = 758
FOOTER_H = g.FOOTER_H
# Vertically centered in the one-line footer.
ROW_Y = LAND_H - FOOTER_H + max(4, (FOOTER_H - CELL_H) // 2)
# Stay clear of the rain chip on the left.
LX0 = LAND_W - 280
CHARS = (
    "0123456789"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz"
    "%.:- "
)


def _rotate90(img: Image.Image) -> Image.Image:
    return img.rotate(90, expand=True)


def main() -> None:
    out = Path(__file__).resolve().parents[1] / "extensions" / "calendar" / "bin" / "glyphs"
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*"):
        old.unlink()

    font = g.pil_fonts(13, bold=False)
    widths: list[str] = []

    for ch in CHARS:
        if ch == " ":
            adv = 5
        else:
            adv = max(6, int(font.getlength(ch)) + 2)
        cell = Image.new("L", (adv, CELL_H), 255)
        d = ImageDraw.Draw(cell)
        if ch != " ":
            d.text((1, -1), ch, font=font, fill=0)
        glyph = _rotate90(cell)
        code = f"{ord(ch):02X}"
        glyph.save(out / f"{code}.png", format="PNG", optimize=True)
        widths.append(f"{code} {adv}")

    (out / "widths.txt").write_text("\n".join(widths) + "\n", encoding="ascii")
    (out / "layout.txt").write_text(
        "\n".join(
            [
                f"px={ROW_Y}",
                f"lx0={LX0}",
                f"land_w={LAND_W}",
                f"cell_h={CELL_H}",
                f"footer_h={FOOTER_H}",
                "",
            ]
        ),
        encoding="ascii",
    )

    # Preview: rain chip + status on one footer line.
    base = Image.new("L", (LAND_W, LAND_H), 255)
    g.draw_exit_footer(
        ImageDraw.Draw(base),
        LAND_W,
        LAND_H,
        None,
        0,
        "LLUVIA HOY 71% · MANANA 87%",
    )
    sim = _rotate90(base)
    wmap = {line.split()[0]: int(line.split()[1]) for line in widths}
    lx = LX0
    for ch in "Bat 84%  WiFi on  Act 17:50":
        code = f"{ord(ch):02X}"
        adv = wmap[code]
        gimg = Image.open(out / f"{code}.png")
        py = LAND_W - lx - adv
        if py < 0:
            break
        sim.paste(gimg, (ROW_Y, py))
        lx += adv
    preview = Path(__file__).resolve().parent / "output" / "_stamp_footer.png"
    preview.parent.mkdir(parents=True, exist_ok=True)
    strip = sim.crop((sim.width - FOOTER_H, 0, sim.width, sim.height)).transpose(Image.ROTATE_270)
    strip.save(preview)

    print(f"Wrote {len(CHARS)} glyphs + layout/widths -> {out}")
    print(f"layout: px={ROW_Y} lx0={LX0}")


if __name__ == "__main__":
    main()
