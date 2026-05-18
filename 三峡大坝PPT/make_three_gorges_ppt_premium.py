import base64
import html
import os
import zipfile
from datetime import datetime, timezone


OUT = "三峡大坝的历史与现在_精装版.pptx"
ASSET_DIR = "premium_slides"
COVER = "three_gorges_cover.png"
W_EMU, H_EMU = 12192000, 6858000
SW, SH = 1600, 900


def esc(s):
    return html.escape(str(s), quote=True)


def wrap_text(text, max_chars=22):
    lines, buf = [], ""
    for ch in text:
        buf += ch
        if len(buf) >= max_chars:
            lines.append(buf)
            buf = ""
    if buf:
        lines.append(buf)
    return lines


def text(x, y, content, size=30, fill="#102A43", weight=500, anchor="start", opacity=1, spacing=1.35):
    lines = content.split("\n")
    out = [f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" font-weight="{weight}" text-anchor="{anchor}" opacity="{opacity}">']
    for i, line in enumerate(lines):
        dy = 0 if i == 0 else size * spacing
        out.append(f'<tspan x="{x}" dy="{dy}">{esc(line)}</tspan>')
    out.append("</text>")
    return "".join(out)


def pill(x, y, w, h, label, fill, fg="#FFFFFF"):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{fill}"/>{text(x+w/2, y+h/2+8, label, 24, fg, 700, "middle")}'


def card(x, y, w, h, title, body, accent="#1E7F86", fill="#FFFFFF"):
    body_lines = body.split("\n")
    items = [
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="18" fill="{fill}" stroke="#D8E4EC" stroke-width="2"/>',
        f'<rect x="{x}" y="{y}" width="8" height="{h}" rx="4" fill="{accent}"/>',
        text(x + 34, y + 52, title, 30, accent, 800),
    ]
    yy = y + 95
    for line in body_lines:
        items.append(text(x + 34, yy, line, 20, "#334E68", 500))
        yy += 34
    return "".join(items)


def data_card(x, y, w, number, label, note="", accent="#C51F2C"):
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="126" rx="18" fill="#FFFFFF" stroke="#D8E4EC" stroke-width="2"/>'
        f'<rect x="{x}" y="{y}" width="{w}" height="8" rx="4" fill="{accent}"/>'
        + text(x + w / 2, y + 56, number, 38, accent, 900, "middle")
        + text(x + w / 2, y + 88, label, 18, "#243B53", 700, "middle")
        + (text(x + w / 2, y + 113, note, 14, "#718096", 500, "middle") if note else "")
    )


def base_svg(title, page, dark=False):
    bg = "#F4F7FA" if not dark else "#081A2E"
    title_color = "#102A43" if not dark else "#FFFFFF"
    subtitle_color = "#627D98" if not dark else "#CFE7EA"
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{SW}" height="{SH}" viewBox="0 0 {SW} {SH}">
<defs>
  <linearGradient id="navy" x1="0" x2="1" y1="0" y2="1"><stop stop-color="#08213C"/><stop offset="1" stop-color="#12345A"/></linearGradient>
  <linearGradient id="teal" x1="0" x2="1"><stop stop-color="#1E7F86"/><stop offset="1" stop-color="#42A5A9"/></linearGradient>
  <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="8" stdDeviation="10" flood-color="#0B1F33" flood-opacity=".12"/></filter>
  <pattern id="grid" width="42" height="42" patternUnits="userSpaceOnUse"><path d="M42 0H0V42" fill="none" stroke="#DDE6EE" stroke-width="1"/></pattern>
</defs>
<rect width="{SW}" height="{SH}" fill="{bg}"/>
<path d="M0 705 C260 650, 420 780, 705 720 C980 662, 1160 610, 1600 690 L1600 900 L0 900Z" fill="#E7F1F4"/>
<path d="M0 742 C300 690, 440 825, 710 760 C990 692, 1180 648, 1600 722" fill="none" stroke="#C9E2E6" stroke-width="7" opacity=".8"/>
<text x="70" y="70" font-size="18" fill="{subtitle_color}" font-weight="600">三峡大坝的历史与现在</text>
<text x="1530" y="70" font-size="16" fill="{subtitle_color}" text-anchor="end">{page:02d}</text>
<text x="70" y="128" font-size="44" fill="{title_color}" font-weight="900">{esc(title)}</text>
<rect x="72" y="150" width="168" height="7" rx="3.5" fill="#C51F2C"/>
'''


def finish():
    return "</svg>"


def slide1():
    img_tag = ""
    if os.path.exists(COVER):
        with open(COVER, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        img_tag = f'<image href="data:image/png;base64,{b64}" x="0" y="0" width="{SW}" height="{SH}" preserveAspectRatio="xMidYMid slice"/>'
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{SW}" height="{SH}" viewBox="0 0 {SW} {SH}">
<defs>
<linearGradient id="coverMask" x1="0" x2="1"><stop stop-color="#06192F" stop-opacity=".94"/><stop offset=".52" stop-color="#06192F" stop-opacity=".72"/><stop offset="1" stop-color="#06192F" stop-opacity=".22"/></linearGradient>
<linearGradient id="bottom" x1="0" x2="0" y1="0" y2="1"><stop stop-color="#06192F" stop-opacity="0"/><stop offset="1" stop-color="#06192F" stop-opacity=".76"/></linearGradient>
</defs>
{img_tag}<rect width="{SW}" height="{SH}" fill="url(#coverMask)"/><rect y="540" width="{SW}" height="360" fill="url(#bottom)"/>
<rect x="72" y="126" width="8" height="124" fill="#C51F2C"/>{text(108, 165, "三峡大坝的历史与现在", 58, "#FFFFFF", 900)}
{text(112, 228, "党领导下的国家重大水利工程实践", 30, "#D8EEF2", 600)}
<rect x="112" y="270" width="310" height="6" rx="3" fill="#C51F2C"/>
{text(112, 330, "从治水兴邦到现代化流域治理", 28, "#FFFFFF", 700)}
{data_card(112, 650, 255, "2309米", "坝轴线全长", accent="#FFFFFF").replace('#FFFFFF" stroke', '#FFFFFF" opacity=".92" stroke').replace('fill="#FFFFFF"', 'fill="#FFFFFF"', 1)}
{data_card(397, 650, 255, "181米", "最大坝高", accent="#1E7F86").replace('fill="#FFFFFF" stroke', 'fill="#FFFFFF" opacity=".92" stroke', 1)}
{data_card(682, 650, 290, "2250万kW", "总装机容量", accent="#C51F2C").replace('fill="#FFFFFF" stroke', 'fill="#FFFFFF" opacity=".92" stroke', 1)}
{text(70, 840, "汇报材料｜2026", 18, "#DDECF2", 500)}
</svg>'''


def slide2():
    s = base_svg("一江安澜：建设的时代背景", 2)
    s += '<rect x="70" y="195" width="620" height="430" rx="22" fill="#FFFFFF" filter="url(#shadow)"/>'
    bullets = ["长江干流全长约6300公里，是我国重要经济轴线", "中下游人口密集、产业集中，防洪安全关系全局", "工程承担防洪、发电、航运、水资源调度等综合任务", "根本出发点是保障人民生命财产安全、服务国家发展大局"]
    y = 255
    for b in bullets:
        s += f'<circle cx="112" cy="{y-8}" r="6" fill="#1E7F86"/>' + text(135, y, b, 25, "#243B53", 600)
        y += 75
    s += pill(95, 545, 155, 54, "防洪安全", "#C51F2C") + pill(280, 545, 155, 54, "清洁能源", "#1E7F86") + pill(465, 545, 155, 54, "黄金水道", "#12345A")
    s += '<rect x="765" y="180" width="720" height="500" rx="28" fill="#FFFFFF" filter="url(#shadow)"/>'
    s += text(1125, 240, "长江流域与三峡位置示意", 30, "#12345A", 900, "middle")
    s += '<path d="M895 528 C1010 470, 1025 370, 1145 405 C1265 440, 1315 345, 1430 300" fill="none" stroke="#1E7F86" stroke-width="34" stroke-linecap="round"/>'
    s += '<path d="M940 540 C1060 515, 1185 580, 1300 520" fill="none" stroke="#67B7BE" stroke-width="10" stroke-linecap="round"/>'
    s += '<path d="M1020 430 C1080 405, 1110 405, 1150 410" fill="none" stroke="#67B7BE" stroke-width="8" stroke-linecap="round"/>'
    s += '<circle cx="1166" cy="414" r="22" fill="#C51F2C"/>' + text(1200, 423, "三峡坝址", 25, "#102A43", 800)
    s += '<rect x="850" y="600" width="545" height="46" rx="23" fill="#EDF7F8"/>' + text(1122, 631, "上游调蓄　下游防洪　全流域协同", 23, "#1E7F86", 700, "middle")
    return s + finish()


def slide3():
    s = base_svg("百年构想：从设想到国家决策", 3)
    s += '<rect x="0" y="0" width="1600" height="900" fill="url(#grid)" opacity=".45"/>'
    nodes = [("早期设想", "围绕长江治水与水能开发\n形成三峡工程构想"), ("系统论证", "新中国成立后持续开展\n勘测、规划与科学研究"), ("国家决策", "1992年全国人大审议通过\n兴建三峡工程决议"), ("正式开工", "1994年工程正式开工\n百年构想进入实施阶段")]
    for i, (t, b) in enumerate(nodes):
        x = 105 + i * 370
        s += f'<rect x="{x}" y="250" width="300" height="260" rx="24" fill="#FFFFFF" filter="url(#shadow)"/>'
        s += f'<circle cx="{x+150}" cy="250" r="43" fill="{"#C51F2C" if i>=2 else "#1E7F86"}"/>' + text(x+150, 260, str(i+1), 34, "#FFFFFF", 900, "middle")
        s += text(x+150, 345, t, 31, "#12345A", 900, "middle") + text(x+150, 415, b, 21, "#334E68", 500, "middle")
        if i < 3:
            s += f'<path d="M{x+312} 375 H{x+365}" stroke="#9FB3C8" stroke-width="5" stroke-linecap="round"/><path d="M{x+358} 363 L{x+378} 375 L{x+358} 387" fill="none" stroke="#9FB3C8" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>'
    s += '<rect x="210" y="610" width="1180" height="88" rx="18" fill="#12345A"/>' + text(800, 665, "体现党和国家对重大工程、重大民生、重大安全问题的长期谋划能力", 30, "#FFFFFF", 800, "middle")
    return s + finish()


def slide4():
    s = base_svg("攻坚克难：三峡工程建设历程", 4)
    s += '<rect x="120" y="330" width="1360" height="16" rx="8" fill="#C9E2E6"/>'
    steps = [("1992", "批准建设"), ("1994", "正式开工"), ("1997", "大江截流"), ("2003", "首批发电\n船闸通航"), ("2006", "主体完工"), ("2012", "主要任务完成")]
    for i, (yr, lab) in enumerate(steps):
        x = 150 + i * 255
        accent = "#C51F2C" if i in (0, 3, 5) else "#1E7F86"
        s += f'<circle cx="{x}" cy="338" r="28" fill="{accent}" stroke="#FFFFFF" stroke-width="7"/>'
        ybox = 210 if i % 2 == 0 else 405
        s += f'<rect x="{x-86}" y="{ybox}" width="172" height="105" rx="16" fill="#FFFFFF" filter="url(#shadow)"/>'
        s += text(x, ybox + 42, yr, 31, accent, 900, "middle") + text(x, ybox + 78, lab, 19, "#334E68", 650, "middle")
    s += '<rect x="160" y="640" width="1280" height="82" rx="18" fill="#EDF7F8" stroke="#C9E2E6"/>' + text(800, 693, "建设周期长、技术难度高、组织协同复杂，是我国重大工程建设能力的集中展示", 29, "#12345A", 800, "middle")
    return s + finish()


def slide5():
    s = base_svg("党建引领：重大工程背后的组织力量", 5, dark=True)
    s += '<path d="M0 190 C300 120, 455 280, 760 210 C1050 145, 1280 115, 1600 170 L1600 900 L0 900Z" fill="#12345A" opacity=".35"/>'
    s += '<rect x="82" y="205" width="650" height="465" rx="28" fill="#FFFFFF" opacity=".10" stroke="#5F8AA5"/>'
    s += '<rect x="112" y="250" width="8" height="300" fill="#C51F2C"/>'
    s += text(152, 305, "党的领导贯穿工程建设、移民安置、\n生态保护和运行管理全过程", 37, "#FFFFFF", 900)
    s += text(152, 455, "工程涉及百万级移民安置，是复杂的工程建设任务，\n也是系统的社会治理任务。", 25, "#D8EEF2", 500)
    cards = [("领导", "统一部署\n统筹全局"), ("组织", "基层党组织\n战斗堡垒"), ("攻坚", "关键节点\n冲锋在前"), ("担当", "党员干部\n一线作为")]
    for i, (t, b) in enumerate(cards):
        x = 820 + (i % 2) * 305
        y = 250 + (i // 2) * 210
        s += f'<rect x="{x}" y="{y}" width="260" height="150" rx="22" fill="#FFFFFF" opacity=".96" filter="url(#shadow)"/>'
        s += f'<rect x="{x}" y="{y}" width="260" height="8" rx="4" fill="#C51F2C"/>'
        s += text(x + 130, y + 62, t, 34, "#C51F2C", 900, "middle") + text(x + 130, y + 112, b, 22, "#243B53", 650, "middle")
    s += text(800, 750, "集中力量办大事的制度优势，是工程顺利推进的重要保障", 33, "#FFFFFF", 800, "middle")
    return s + finish()


def slide6():
    s = base_svg("大国重器：三峡大坝的工程规模", 6)
    s += '<rect x="90" y="190" width="1420" height="500" rx="30" fill="#FFFFFF" filter="url(#shadow)"/>'
    s += '<path d="M440 530 L1060 530 L960 340 L560 340 Z" fill="#7B8794"/><path d="M505 340 H1015 L930 250 H590 Z" fill="#9AA5B1"/><rect x="380" y="530" width="740" height="54" rx="6" fill="#52606D"/><path d="M385 604 C610 560, 905 640, 1120 595" fill="none" stroke="#1E7F86" stroke-width="16" stroke-linecap="round"/>'
    params = [("2309米", "坝轴线全长", "混凝土重力坝"), ("181米", "最大坝高", "工程垂直尺度"), ("393亿m³", "水库总库容", "流域调蓄基础"), ("221.5亿m³", "防洪库容", "防洪核心能力"), ("2250万kW", "总装机容量", "世界级水电站")]
    xs = [115, 405, 695, 985, 1240]
    for i, p in enumerate(params):
        s += data_card(xs[i], 710, 245, p[0], p[1], p[2], "#C51F2C" if i >= 3 else "#1E7F86")
    s += text(800, 265, "大坝、水库、电站、船闸、升船机一体化构成世界级水利水电枢纽", 28, "#12345A", 800, "middle")
    return s + finish()


def slide7():
    s = base_svg("综合效益：防洪、发电、航运与调度", 7)
    items = [("防洪", "防洪库容约221.5亿立方米\n提升长江中下游安全保障", "#C51F2C"), ("发电", "多年平均年发电量约882亿千瓦时\n持续输出清洁电能", "#1E7F86"), ("航运", "双线五级船闸支撑万吨级船队\n改善川江航道条件", "#12345A"), ("调度", "汛期削峰、枯水补水\n服务流域水资源配置", "#617586")]
    for i, (t, b, c) in enumerate(items):
        x = 100 + (i % 2) * 710
        y = 205 + (i // 2) * 250
        s += card(x, y, 620, 190, t, b, c)
        s += f'<circle cx="{x+535}" cy="{y+82}" r="48" fill="{c}" opacity=".12"/><circle cx="{x+535}" cy="{y+82}" r="24" fill="{c}"/>'
    s += '<rect x="420" y="740" width="760" height="60" rx="30" fill="#12345A"/>' + text(800, 781, "一座工程，多重效益，服务流域治理全局", 27, "#FFFFFF", 800, "middle")
    return s + finish()


def slide8():
    s = base_svg("今日三峡：现代化运行与长江大保护", 8)
    s += '<rect x="80" y="190" width="1440" height="245" rx="30" fill="url(#navy)" filter="url(#shadow)"/>'
    s += text(800, 270, "从工程建设转向高质量运行管理", 42, "#FFFFFF", 900, "middle")
    s += text(800, 335, "数字化、智能化调度服务国家能源安全、长江经济带发展和长江大保护", 25, "#D8EEF2", 500, "middle")
    nums = [("1.8万亿kWh+", "截至2025年8月累计发电量突破"), ("22亿吨+", "三峡船闸累计货运量超过"), ("2003年以来", "首批机组投产、永久船闸通航")]
    for i, (n, lab) in enumerate(nums):
        x = 145 + i * 470
        s += data_card(x, 520, 370, n, lab, "", "#C51F2C" if i == 0 else "#1E7F86")
    s += '<path d="M200 470 H1400" stroke="#D8E4EC" stroke-width="2" stroke-dasharray="8 10"/>'
    return s + finish()


def slide9():
    s = base_svg("辩证看待：成就、挑战与长期治理", 9)
    s += '<rect x="95" y="205" width="610" height="470" rx="28" fill="#FFFFFF" filter="url(#shadow)"/><rect x="895" y="205" width="610" height="470" rx="28" fill="#FFFFFF" filter="url(#shadow)"/>'
    s += text(400, 280, "综合成就", 38, "#1E7F86", 900, "middle") + text(1200, 280, "长期课题", 38, "#C51F2C", 900, "middle")
    s += text(170, 360, "• 防洪能力提升\n• 清洁能源供应\n• 航运条件改善\n• 水资源调度增强", 27, "#334E68", 600)
    s += text(970, 360, "• 生态环境保护\n• 泥沙淤积监测\n• 库区发展与移民后续扶持\n• 文物保护与长期治理", 27, "#334E68", 600)
    s += '<circle cx="800" cy="440" r="82" fill="#12345A"/>' + text(800, 432, "系统", 29, "#FFFFFF", 900, "middle") + text(800, 470, "治理", 29, "#FFFFFF", 900, "middle")
    s += '<path d="M710 440 H624" stroke="#9FB3C8" stroke-width="6"/><path d="M890 440 H976" stroke="#9FB3C8" stroke-width="6"/>'
    s += '<rect x="260" y="730" width="1080" height="58" rx="29" fill="#EDF7F8"/>' + text(800, 769, "坚持历史、全面、辩证眼光，推动工程效益与生态保护相统一", 26, "#12345A", 800, "middle")
    return s + finish()


def slide10():
    img_tag = ""
    if os.path.exists(COVER):
        with open(COVER, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        img_tag = f'<image href="data:image/png;base64,{b64}" x="0" y="0" width="{SW}" height="{SH}" preserveAspectRatio="xMidYMid slice"/>'
    s = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{SW}" height="{SH}" viewBox="0 0 {SW} {SH}">
<defs><linearGradient id="mask" x1="0" x2="0" y1="0" y2="1"><stop stop-color="#06192F" stop-opacity=".88"/><stop offset="1" stop-color="#06192F" stop-opacity=".94"/></linearGradient></defs>
{img_tag}<rect width="{SW}" height="{SH}" fill="url(#mask)"/>
{text(800, 220, "从一座大坝，看见中国式现代化的治理能力", 50, "#FFFFFF", 900, "middle")}<rect x="615" y="260" width="370" height="7" rx="3.5" fill="#C51F2C"/>
'''
    words = [("战略", "国家重大工程"), ("技术", "工程装备能力"), ("组织", "集中力量办大事"), ("人民", "安全与发展")]
    for i, (t, b) in enumerate(words):
        x = 170 + i * 325
        s += f'<rect x="{x}" y="410" width="260" height="135" rx="24" fill="#FFFFFF" opacity=".13" stroke="#BFD7E3"/>'
        s += text(x + 130, 465, t, 36, "#FFFFFF", 900, "middle") + text(x + 130, 510, b, 22, "#D8EEF2", 600, "middle")
    s += text(800, 710, "谢谢各位领导", 38, "#FFFFFF", 900, "middle")
    return s + "</svg>"


SLIDES = [slide1, slide2, slide3, slide4, slide5, slide6, slide7, slide8, slide9, slide10]


def pic_slide(idx):
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
<p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{W_EMU}" cy="{H_EMU}"/><a:chOff x="0" y="0"/><a:chExt cx="{W_EMU}" cy="{H_EMU}"/></a:xfrm></p:grpSpPr>
<p:pic><p:nvPicPr><p:cNvPr id="2" name="slide{idx:02d}.svg"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr><p:blipFill><a:blip r:embed="rId2"/><a:stretch><a:fillRect/></a:stretch></p:blipFill><p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{W_EMU}" cy="{H_EMU}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>
</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>'''


def write_common(z, count):
    overrides = ''.join([f'<Override PartName="/ppt/slides/slide{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>' for i in range(1, count + 1)])
    z.writestr("[Content_Types].xml", f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="svg" ContentType="image/svg+xml"/><Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/><Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/><Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/><Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/><Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/><Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>{overrides}</Types>''')
    z.writestr("_rels/.rels", '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/></Relationships>''')
    now = datetime.now(timezone.utc).isoformat()
    z.writestr("docProps/core.xml", f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:title>三峡大坝的历史与现在</dc:title><dc:creator>Codex</dc:creator><cp:lastModifiedBy>Codex</cp:lastModifiedBy><dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created><dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified></cp:coreProperties>''')
    z.writestr("docProps/app.xml", f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"><Application>Codex</Application><PresentationFormat>宽屏</PresentationFormat><Slides>{count}</Slides></Properties>''')
    slide_ids = ''.join([f'<p:sldId id="{256+i}" r:id="rId{i+2}"/>' for i in range(count)])
    rels = ['<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>']
    rels += [f'<Relationship Id="rId{i+2}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide{i+1}.xml"/>' for i in range(count)]
    rels += [f'<Relationship Id="rId{count+2}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="theme/theme1.xml"/>']
    z.writestr("ppt/presentation.xml", f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst><p:sldIdLst>{slide_ids}</p:sldIdLst><p:sldSz cx="{W_EMU}" cy="{H_EMU}" type="wide"/><p:notesSz cx="6858000" cy="9144000"/><p:defaultTextStyle/></p:presentation>''')
    z.writestr("ppt/_rels/presentation.xml.rels", f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{''.join(rels)}</Relationships>''')
    z.writestr("ppt/slideMasters/slideMaster1.xml", f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sldMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{W_EMU}" cy="{H_EMU}"/><a:chOff x="0" y="0"/><a:chExt cx="{W_EMU}" cy="{H_EMU}"/></a:xfrm></p:grpSpPr></p:spTree></p:cSld><p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/><p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst><p:txStyles><p:titleStyle/><p:bodyStyle/><p:otherStyle/></p:txStyles></p:sldMaster>''')
    z.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels", '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/></Relationships>''')
    z.writestr("ppt/slideLayouts/slideLayout1.xml", f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" type="blank" preserve="1"><p:cSld name="Blank"><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{W_EMU}" cy="{H_EMU}"/><a:chOff x="0" y="0"/><a:chExt cx="{W_EMU}" cy="{H_EMU}"/></a:xfrm></p:grpSpPr></p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>''')
    z.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels", '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/></Relationships>''')
    z.writestr("ppt/theme/theme1.xml", '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Premium"><a:themeElements><a:clrScheme name="Premium"><a:dk1><a:srgbClr val="12345A"/></a:dk1><a:lt1><a:srgbClr val="FFFFFF"/></a:lt1><a:dk2><a:srgbClr val="243B53"/></a:dk2><a:lt2><a:srgbClr val="F4F7FA"/></a:lt2><a:accent1><a:srgbClr val="1E7F86"/></a:accent1><a:accent2><a:srgbClr val="C51F2C"/></a:accent2><a:accent3><a:srgbClr val="617586"/></a:accent3><a:accent4><a:srgbClr val="D8E4EC"/></a:accent4><a:accent5><a:srgbClr val="12345A"/></a:accent5><a:accent6><a:srgbClr val="9FB3C8"/></a:accent6><a:hlink><a:srgbClr val="1E7F86"/></a:hlink><a:folHlink><a:srgbClr val="617586"/></a:folHlink></a:clrScheme><a:fontScheme name="Microsoft YaHei"><a:majorFont><a:latin typeface="Microsoft YaHei"/><a:ea typeface="Microsoft YaHei"/><a:cs typeface="Microsoft YaHei"/></a:majorFont><a:minorFont><a:latin typeface="Microsoft YaHei"/><a:ea typeface="Microsoft YaHei"/><a:cs typeface="Microsoft YaHei"/></a:minorFont></a:fontScheme><a:fmtScheme name="Default"><a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst><a:lnStyleLst><a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst><a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst><a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst></a:fmtScheme></a:themeElements><a:objectDefaults/><a:extraClrSchemeLst/></a:theme>''')


def build():
    os.makedirs(ASSET_DIR, exist_ok=True)
    svgs = []
    for i, fn in enumerate(SLIDES, 1):
        svg = fn()
        path = os.path.join(ASSET_DIR, f"slide{i:02d}.svg")
        with open(path, "w", encoding="utf-8") as f:
            f.write(svg)
        svgs.append(path)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        write_common(z, len(svgs))
        for i, path in enumerate(svgs, 1):
            z.writestr(f"ppt/slides/slide{i}.xml", pic_slide(i))
            z.writestr(f"ppt/slides/_rels/slide{i}.xml.rels", f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/slide{i:02d}.svg"/></Relationships>''')
            z.write(path, f"ppt/media/slide{i:02d}.svg")
    print(os.path.abspath(OUT))


if __name__ == "__main__":
    build()
