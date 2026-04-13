from __future__ import annotations

from pathlib import Path

import fitz
from PIL import Image, ImageDraw

BASE_DIR = Path(__file__).resolve().parent.parent
SAMPLE_DIR = BASE_DIR / "sample_data"
SAMPLE_DIR.mkdir(parents=True, exist_ok=True)

TXT_CONTENT = """2024-05-12 林栖：我还是喜欢冰美式，越苦越清醒。

2024-05-12 我：你又空腹喝咖啡。

2024-05-12 林栖：我讨厌太甜的东西，也受不了奶油味。

2024-05-13 林栖：如果要找我，微信 vx:linqi_2046，别在群里叫。

2024-06-02 我们在静安路车站口走到凌晨两点，她说下雨天最适合把话一次说清。"""

MD_CONTENT = """# 记忆碎片

2024-07-01 我们一起去看海，她穿着深灰色外套，整路都很安静。

2024-07-03 林栖说：“别在消息里兜圈子，直接说重点。”

2024-07-18 我们因为回消息太晚吵架，后来在便利店门口和好。

2024-07-18 我们因为回消息太晚吵架，后来在便利店门口和好。"""

JSON_CONTENT = """[
  {"timestamp": "2024-08-10", "speaker": "林栖", "content": "我最爱吃清汤面，不要香菜。"},
  {"timestamp": "2024-08-11", "speaker": "我", "content": "你昨天又失眠了吗？"},
  {"timestamp": "2024-08-11", "speaker": "林栖", "content": "睡不着的时候我只想一个人走路，别追着问。"},
  {"timestamp": "2024-08-12", "speaker": "林栖", "content": "别把我的手机号 13812345678 随便给别人。"}
]"""

CSV_CONTENT = """date,speaker,content
2024-09-04,林栖,我们每次吵完架都去江边走一圈。
2024-09-05,林栖,我不喜欢太闹的餐厅。
2024-09-05,我,那你下次自己选地方。
2024-09-06,林栖,阿迟，你别又把地址发到公开频道。
"""

DUPLICATE_JSON = """[
  {"timestamp": "2024-09-20", "speaker": "林栖", "content": "别在消息里兜圈子，直接说重点。"},
  {"timestamp": "2024-09-21", "speaker": "林栖", "content": "我们因为回消息太晚又差点吵起来。"}
]"""

PRIVATE_NOTES = """2024-10-05 她说周末可能会去虹桥站附近见朋友。

2024-10-06 她让我不要在微博@linqi_archive 下面留言。

2024-10-07 她说如果真的急，就打 13900001234。"""

PDF_LINES = [
    "2024-10-02 Linqi reviewed old photos and said she was nostalgic.",
    "2024-10-03 She preferred black, grey, and quieter seats.",
    "2024-10-09 At the station window she said: do not delay every important thing until tomorrow.",
]


def write_text_files() -> None:
    (SAMPLE_DIR / "chat_fragments.txt").write_text(TXT_CONTENT, encoding="utf-8")
    (SAMPLE_DIR / "memory_notes.md").write_text(MD_CONTENT, encoding="utf-8")
    (SAMPLE_DIR / "chat_export.json").write_text(JSON_CONTENT, encoding="utf-8")
    (SAMPLE_DIR / "chat_export.csv").write_text(CSV_CONTENT, encoding="utf-8")
    (SAMPLE_DIR / "duplicate_quotes.json").write_text(DUPLICATE_JSON, encoding="utf-8")
    (SAMPLE_DIR / "private_notes.txt").write_text(PRIVATE_NOTES, encoding="utf-8")


def write_pdf() -> None:
    document = fitz.open()
    page = document.new_page()
    y = 72
    for line in PDF_LINES:
        page.insert_text((72, y), line, fontsize=12)
        y += 28
    document.save(SAMPLE_DIR / "weekly_report.pdf")
    document.close()


def write_images() -> None:
    image = Image.new("RGB", (1400, 900), color=(18, 18, 18))
    draw = ImageDraw.Draw(image)
    draw.rectangle((110, 110, 1290, 790), outline=(95, 95, 95), width=3)
    draw.text((140, 160), "Night walk / 2024-11-12 23:41", fill=(190, 190, 190))
    exif = Image.Exif()
    exif[306] = "2024:11:12 23:41:00"
    exif[36867] = "2024:11:12 23:41:00"
    image.save(SAMPLE_DIR / "night_walk.jpg", exif=exif)

    image_png = Image.new("RGB", (1200, 800), color=(28, 28, 28))
    draw_png = ImageDraw.Draw(image_png)
    draw_png.text((140, 150), "Station window / no EXIF", fill=(220, 220, 220))
    image_png.save(SAMPLE_DIR / "station_window.png")


def main() -> None:
    write_text_files()
    write_pdf()
    write_images()
    print(f"Sample assets generated in {SAMPLE_DIR}")


if __name__ == "__main__":
    main()
