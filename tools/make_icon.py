"""Draws assets/icon.ico and icon.png: an orange tile with waveform bars and a download arrow."""

from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 1024
ORANGE_TOP = (255, 112, 26)
ORANGE_BOTTOM = (240, 64, 0)
WHITE = (255, 255, 255, 255)
BAR_HEIGHTS = (0.22, 0.38, 0.30, 0.50, 0.30, 0.38, 0.22)  # fraction of the tile


def gradient_tile() -> Image.Image:
    tile = Image.new("RGBA", (SIZE, SIZE))
    draw = ImageDraw.Draw(tile)
    for y in range(SIZE):
        t = y / (SIZE - 1)
        color = tuple(round(a + (b - a) * t) for a, b in zip(ORANGE_TOP, ORANGE_BOTTOM))
        draw.line([(0, y), (SIZE, y)], fill=(*color, 255))
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=int(SIZE * 0.22), fill=255)
    tile.putalpha(mask)
    return tile


def draw_glyph(tile: Image.Image) -> None:
    draw = ImageDraw.Draw(tile)
    bar_w = SIZE * 0.07
    gap = SIZE * 0.045
    total = len(BAR_HEIGHTS) * bar_w + (len(BAR_HEIGHTS) - 1) * gap
    x = (SIZE - total) / 2
    mid = SIZE * 0.40
    for height in BAR_HEIGHTS:
        h = SIZE * height
        draw.rounded_rectangle([x, mid - h / 2, x + bar_w, mid + h / 2], radius=bar_w / 2, fill=WHITE)
        x += bar_w + gap
    # download arrow under the waveform
    cx, top, bottom = SIZE / 2, SIZE * 0.66, SIZE * 0.86
    stem = SIZE * 0.035
    draw.rounded_rectangle([cx - stem, top, cx + stem, bottom - SIZE * 0.05], radius=stem, fill=WHITE)
    head = SIZE * 0.11
    draw.polygon([(cx - head, bottom - head), (cx + head, bottom - head), (cx, bottom + SIZE * 0.02)], fill=WHITE)


def main() -> None:
    assets = Path(__file__).resolve().parent.parent / "assets"
    assets.mkdir(exist_ok=True)
    tile = gradient_tile()
    draw_glyph(tile)
    tile.resize((512, 512), Image.LANCZOS).save(assets / "icon.png")
    tile.save(assets / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"Wrote {assets / 'icon.ico'}")


if __name__ == "__main__":
    main()
