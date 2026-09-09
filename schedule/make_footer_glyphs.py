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
ROW2_Y = LAND_H - FOOTER_H + 30
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

    probe = Image.new("L", (LAND_W, LAND_H), 255)
    probe.putpixel((10, ROW2_Y), 0)
    pr = _rotate90(probe)
    dark = [(x, y) for y in range(pr.height) for x in range(pr.width) if pr.getpixel((x, y)) < 128]
    if not dark:
        raise SystemExit("calibration probe failed")
    px, py_anchor = dark[0]

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

    # py0 = top of first glyph image for landscape x=10.
    # Image height after rotate equals the landscape advance of that glyph;
    # use space advance as the nominal first-cell height for the anchor.
    py0 = py_anchor - 5 + 1
    (out / "layout.txt").write_text(
        "\n".join(
            [
                f"px={px}",
                f"py0={py_anchor - 8 + 1}",
                f"advance=8",
                f"cell_h={CELL_H}",
                f"footer_h={FOOTER_H}",
                "",
            ]
        ),
        encoding="ascii",
    )
    (out / "widths.txt").write_text("\n".join(widths) + "\n", encoding="ascii")

    # Better py0 from a real 'B' glyph placed at x=10 in a full-frame rotate.
    full = Image.new("L", (LAND_W, LAND_H), 255)
    fd = ImageDraw.Draw(full)
    fd.text((10, ROW2_Y - 1), "Bat 84%  WiFi on  Act 17:50", font=font, fill=0)
    fr = _rotate90(full)
    # Find leftmost dark in footer row band near px
    band = fr.crop((px - 2, 0, px + CELL_H + 2, fr.height))
    # Keep reference composite for manual checks
    board = Image.new("L", (LAND_W, LAND_H), 255)
    g.draw_exit_footer(ImageDraw.Draw(board), LAND_W, LAND_H, None, 0, "Lluvia hoy 71%")
    ImageDraw.Draw(board).text((10, ROW2_Y - 1), "Bat 84%  WiFi on  Act 17:50", font=font, fill=0)
    ref = _rotate90(board)
    ref_strip = ref.crop((ref.width - FOOTER_H, 0, ref.width, ref.height)).transpose(Image.ROTATE_270)
    preview = Path(__file__).resolve().parent / "output" / "_stamp_footer.png"
    preview.parent.mkdir(parents=True, exist_ok=True)
    ref_strip.save(preview)

    # Recalibrate py0 using glyph paste simulation with proportional widths
    sim = _rotate90(Image.new("L", (LAND_W, LAND_H), 255))
    # start from empty rotated canvas sized like a board
    base = Image.new("L", (LAND_W, LAND_H), 255)
    g.draw_exit_footer(ImageDraw.Draw(base), LAND_W, LAND_H, None, 0, "Lluvia hoy 71%")
    sim = _rotate90(base)
    wmap = {line.split()[0]: int(line.split()[1]) for line in widths}
    # Exact mapping: landscape (lx, ROW2_Y) -> (ROW2_Y, LAND_W-1-lx)
    lx = 10
    line = "Bat 84%  WiFi on  Act 17:50"
    for ch in line:
        code = f"{ord(ch):02X}"
        adv = wmap[code]
        gimg = Image.open(out / f"{code}.png")
        # top-left of rotated glyph: py = LAND_W-1-lx - adv + 1? 
        # char occupies landscape [lx, lx+adv). After rotate, portrait y in
        # (LAND_W-1-(lx+adv-1)) .. (LAND_W-1-lx) = (LAND_W-lx-adv) .. (LAND_W-1-lx)
        py = LAND_W - lx - adv
        sim.paste(gimg, (ROW2_Y, py))
        lx += adv
    sim_strip = sim.crop((sim.width - FOOTER_H, 0, sim.width, sim.height)).transpose(Image.ROTATE_270)
    sim_strip.save(preview)

    py0 = LAND_W - 10 - wmap["42"]  # 'B' at lx=10
    (out / "layout.txt").write_text(
        "\n".join(
            [
                f"px={ROW2_Y}",
                f"py0={py0}",
                f"advance=8",
                f"cell_h={CELL_H}",
                f"footer_h={FOOTER_H}",
                "",
            ]
        ),
        encoding="ascii",
    )
    print(f"Wrote {len(CHARS)} glyphs + layout/widths -> {out}")
    print(f"layout: px={ROW2_Y} py0={py0}")


if __name__ == "__main__":
    main()
