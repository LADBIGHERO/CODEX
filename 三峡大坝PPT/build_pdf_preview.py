import os
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SLIDE_DIR = ROOT / "visual_slides"
HTML = ROOT / "三峡大坝的历史与现在_预览.html"


def main():
    slides = sorted(SLIDE_DIR.glob("slide*.svg"))
    sections = []
    for slide in slides:
        svg = slide.read_text(encoding="utf-8")
        sections.append(f'<section class="page">{svg}</section>')
    html = f'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>三峡大坝的历史与现在</title>
<style>
  @page {{ size: 16in 9in; margin: 0; }}
  html, body {{ margin: 0; padding: 0; background: #111; }}
  .page {{ width: 16in; height: 9in; margin: 0; page-break-after: always; overflow: hidden; }}
  svg {{ width: 16in; height: 9in; display: block; }}
  @media screen {{
    body {{ display: flex; flex-direction: column; align-items: center; gap: 24px; padding: 24px; }}
    .page {{ box-shadow: 0 8px 32px rgba(0,0,0,.45); }}
  }}
</style>
</head>
<body>
{os.linesep.join(sections)}
</body>
</html>'''
    HTML.write_text(html, encoding="utf-8")
    print(HTML)


if __name__ == "__main__":
    main()
