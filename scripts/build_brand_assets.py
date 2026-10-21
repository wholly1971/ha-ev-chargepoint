"""Prepare sized Home Assistant brand assets from the project's existing artwork.

Requires Pillow for this development-only packaging step; no runtime dependency.
"""

from pathlib import Path
from PIL import Image, ImageOps

root = Path(__file__).resolve().parents[1]
source = Image.open(root / "assets" / "ev-chargepoint-logo.png").convert("RGBA")
output = root / "custom_components" / "ev_chargepoint" / "brand"
output.mkdir(exist_ok=True)


def visible_bounds(image):
    # Ignore almost-transparent generation artifacts when trimming margins.
    return image.getchannel("A").point(lambda value: 255 if value > 64 else 0).getbbox()


logo = source.crop(visible_bounds(source))
# The established mark is above the wordmark in the original master image.
symbol = source.crop((0, 0, source.width, round(source.height * 0.72)))
symbol = symbol.crop(visible_bounds(symbol))


def dark_variant(image):
    result = image.copy()
    result.putdata(
        [
            (245, 250, 255, a) if g < 140 and b > r else (r, g, b, a)
            for r, g, b, a in image.get_flattened_data()
        ]
    )
    return result


for scale in (1, 2):
    suffix = "@2x" if scale == 2 else ""
    icon = Image.new("RGBA", (256 * scale, 256 * scale))
    mark = ImageOps.contain(symbol, icon.size, Image.Resampling.LANCZOS)
    icon.alpha_composite(mark, ((icon.width - mark.width) // 2, (icon.height - mark.height) // 2))
    sized_logo = logo.resize(
        (round(logo.width * 256 * scale / logo.height), 256 * scale), Image.Resampling.LANCZOS
    )
    for name, image in (("icon", icon), ("logo", sized_logo)):
        image.save(output / f"{name}{suffix}.png", optimize=True)
        dark_variant(image).save(output / f"dark_{name}{suffix}.png", optimize=True)
