#!/usr/bin/env python3
"""Make the small web copies of the logos that the dashboard inlines (needs Pillow; run once after
changing the hi-res files):  python fludash/assets/make_web_assets.py"""
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
OUT = HERE / "web"


def crop(im):
    return im.crop(im.getchannel("A").getbbox())


def main():
    OUT.mkdir(exist_ok=True)
    name = crop(Image.open(HERE / "FluSPARC_name_logo_hi-res.png").convert("RGBA"))
    h = 64                                                     # 2x a 32 px header
    name.resize((round(name.width * h / name.height), h), Image.LANCZOS).save(OUT / "logo-header.png", optimize=True)
    spark = crop(Image.open(HERE / "FluSPARC_spark_hi-res.png").convert("RGBA"))
    side = max(spark.size)
    sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    sq.paste(spark, ((side - spark.width) // 2, (side - spark.height) // 2))
    sq.resize((64, 64), Image.LANCZOS).save(OUT / "favicon.png", optimize=True)
    for f in sorted(OUT.glob("*.png")):
        print(f, f.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
