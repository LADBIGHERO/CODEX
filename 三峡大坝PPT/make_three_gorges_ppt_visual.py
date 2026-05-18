import base64
import html
import os
import zipfile
from datetime import datetime, timezone


OUT = "三峡大坝的历史与现在_视觉增强版.pptx"
ASSET_DIR = "visual_slides"
SW, SH = 1600, 900
W_EMU, H_EMU = 12192000, 6858000


BG = [
    "panorama_bg.png",
    "yangtze_basin_bg.png",
    "planning_bg.png",
    "milestone_bg.png",
    "construction_bg.png",
    "scale_bg.png",
    "benefits_bg.png",
    "modern_operation_bg.png",
    "ecology_bg.png",
    "ship_locks_bg.png",
]


def esc(s):
    return html.escape(str(s), quote=True)


def img_data(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def t(x, y, content, size=28, fill="#FFFFFF", weight=600, anchor="start", opacity=1, spacing=1.28):
    out = [f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" font-weight="{weight}" text-anchor="{anchor}" opacity="{opacity}" font-family="Microsoft YaHei, Noto Sans CJK SC, Arial">']
    for i, line in enumerate(str(content).split("\n")):
        dy = 0 if i == 0 else size * spacing
        out.append(f'<tspan x="{x}" dy="{dy}">{esc(line)}</tspan>')
    out.append("</text>")
    return "".join(out)


def bg(idx, dark_left=True):
    data = img_data(BG[idx - 1])
    if dark_left:
        mask = '<linearGradient id="mask" x1="0" x2="1"><stop stop-color="#06192F" stop-opacity=".94"/><stop offset=".47" stop-color="#06192F" stop-opacity=".70"/><stop offset="1" stop-color="#06192F" stop-opacity=".22"/></linearGradient>'
    else:
        mask = '<linearGradient id="mask" x1="0" x2="1"><stop stop-color="#06192F" stop-opacity=".30"/><stop offset="1" stop-color="#06192F" stop-opacity=".74"/></linearGradient>'
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{SW}" height="{SH}" viewBox="0 0 {SW} {SH}">
<defs>
{mask}
<filter id="shadow" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="10" stdDeviation="12" flood-color="#000000" flood-opacity=".24"/></filter>
<linearGradient id="panel" x1="0" x2="1"><stop stop-color="#08213C" stop-opacity=".88"/><stop offset="1" stop-color="#12345A" stop-opacity=".76"/></linearGradient>
</defs>
<image href="data:image/png;base64,{data}" x="0" y="0" width="{SW}" height="{SH}" preserveAspectRatio="xMidYMid slice"/>
<rect width="{SW}" height="{SH}" fill="url(#mask)"/>
'''


def end():
    return "</svg>"


def header(page, kicker="党建引领  工程报国"):
    return (
        f'<g opacity=".98"><path d="M72 95 L90 113 L72 131 L54 113Z" fill="#C51F2C"/>'
        + t(118, 121, kicker, 24, "#FF3B30", 800)
        + t(1530, 65, f"{page:02d}", 16, "#CFE7EA", 500, "end", .9)
        + "</g>"
    )


def title_block(title, subtitle=None, y=260, size=68):
    s = t(78, y, title, size, "#FFFFFF", 900)
    s += '<rect x="80" y="{}" width="180" height="7" rx="3.5" fill="#E73535"/>'.format(y + title.count("\n") * size * 1.28 + 36)
    if subtitle:
        s += t(80, y + title.count("\n") * size * 1.28 + 100, subtitle, 29, "#F0F7FA", 500)
    return s


def bullet_panel(x, y, w, h, title, bullets, accent="#E73535"):
    s = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="26" fill="url(#panel)" stroke="#7EA6B4" stroke-opacity=".38" filter="url(#shadow)"/>'
    s += f'<rect x="{x+28}" y="{y+34}" width="8" height="54" rx="4" fill="{accent}"/>'
    s += t(x + 52, y + 72, title, 34, "#FFFFFF", 900)
    yy = y + 136
    for b in bullets:
        s += f'<circle cx="{x+56}" cy="{yy-9}" r="6" fill="{accent}"/>'
        s += t(x + 76, yy, b, 23, "#ECF7FA", 600)
        yy += 56
    return s


def data_card(x, y, w, num, label, accent="#E73535"):
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="135" rx="20" fill="#06192F" fill-opacity=".58" stroke="#CFE7EA" stroke-opacity=".45"/>'
        + t(x + w / 2, y + 58, num, 46, "#FFFFFF", 900, "middle")
        + f'<rect x="{x+w/2-28}" y="{y+78}" width="56" height="5" rx="2.5" fill="{accent}"/>'
        + t(x + w / 2, y + 112, label, 22, "#F0F7FA", 600, "middle")
    )


def mini_metric(x, y, label, value, accent="#1ECDD1"):
    return (
        f'<rect x="{x}" y="{y}" width="178" height="74" rx="14" fill="#06192F" fill-opacity=".56" stroke="#CFE7EA" stroke-opacity=".28"/>'
        + t(x + 18, y + 29, label, 15, "#CFE7EA", 600)
        + t(x + 18, y + 58, value, 24, "#FFFFFF", 900)
        + f'<rect x="{x+142}" y="{y+18}" width="8" height="38" rx="4" fill="{accent}"/>'
    )


def donut(x, y, r, label, value, accent="#E73535"):
    c = 2 * 3.14159 * r
    dash = c * 0.74
    return (
        f'<circle cx="{x}" cy="{y}" r="{r}" fill="none" stroke="#CFE7EA" stroke-opacity=".25" stroke-width="16"/>'
        f'<circle cx="{x}" cy="{y}" r="{r}" fill="none" stroke="{accent}" stroke-width="16" stroke-linecap="round" stroke-dasharray="{dash} {c-dash}" transform="rotate(-90 {x} {y})"/>'
        + t(x, y - 2, value, 24, "#FFFFFF", 900, "middle")
        + t(x, y + 34, label, 15, "#DDECF2", 600, "middle")
    )


def bar_chart(x, y, values, labels, title, accent="#1ECDD1"):
    s = f'<rect x="{x}" y="{y}" width="430" height="190" rx="20" fill="#06192F" fill-opacity=".58" stroke="#CFE7EA" stroke-opacity=".30"/>'
    s += t(x + 24, y + 38, title, 22, "#FFFFFF", 900)
    maxv = max(values)
    for i, v in enumerate(values):
        bx = x + 46 + i * 90
        bh = 92 * v / maxv
        s += f'<rect x="{bx}" y="{y+142-bh}" width="42" height="{bh}" rx="6" fill="{accent}" opacity="{0.65 + i*0.08}"/>'
        s += t(bx + 21, y + 168, labels[i], 14, "#DDECF2", 600, "middle")
    return s


def grouped_dam_chart(x, y):
    dams = [
        ("三峡", 22500, 181, 2309, "#E73535"),
        ("伊泰普", 14000, 196, 7235, "#1ECDD1"),
        ("大古力", 6809, 168, 1592, "#F6C85F"),
        ("胡佛", 2080, 221, 379, "#9FB3C8"),
    ]
    s = f'<rect x="{x}" y="{y}" width="660" height="330" rx="24" fill="#06192F" fill-opacity=".66" stroke="#CFE7EA" stroke-opacity=".32"/>'
    s += t(x + 32, y + 48, "国际著名大坝对比", 27, "#FFFFFF", 900)
    s += t(x + 32, y + 82, "装机容量 / 坝高 / 坝长", 18, "#DDECF2", 600)
    base_y = y + 265
    x0 = x + 70
    gap = 135
    for i, (name, cap, height, length, c) in enumerate(dams):
        cx = x0 + i * gap
        cap_h = 150 * cap / 22500
        s += f'<rect x="{cx-28}" y="{base_y-cap_h}" width="26" height="{cap_h}" rx="6" fill="{c}"/>'
        s += f'<rect x="{cx+4}" y="{base_y-(150*height/221)}" width="18" height="{150*height/221}" rx="5" fill="{c}" opacity=".62"/>'
        s += f'<rect x="{cx+28}" y="{base_y-(150*length/7235)}" width="14" height="{150*length/7235}" rx="4" fill="{c}" opacity=".35"/>'
        s += t(cx + 8, base_y + 28, name, 17, "#FFFFFF", 800, "middle")
    s += f'<rect x="{x+470}" y="{y+35}" width="145" height="84" rx="12" fill="#FFFFFF" fill-opacity=".10"/>'
    s += t(x + 490, y + 62, "实心：装机", 14, "#FFFFFF", 700)
    s += t(x + 490, y + 86, "半透：坝高", 14, "#DDECF2", 600)
    s += t(x + 490, y + 110, "浅色：坝长", 14, "#DDECF2", 600)
    return s


def slide1():
    s = bg(1) + header(1) + title_block("三峡大坝的\n历史与现在", "党领导下的国家重大水利工程实践", 290, 78)
    s += data_card(705, 665, 260, "2309米", "大坝全长")
    s += data_card(995, 665, 240, "181米", "最大坝高")
    s += data_card(1265, 665, 265, "2250万kW", "装机容量")
    return s + end()


def slide2():
    s = bg(2) + header(2) + title_block("一江安澜", "三峡工程建设的时代背景", 210, 64)
    s += bullet_panel(78, 430, 700, 330, "为什么要建设三峡工程", [
        "长江干流全长约6300公里，是我国重要经济轴线",
        "中下游人口密集、产业集中，防洪安全关系全局",
        "承担防洪、发电、航运、水资源调度等综合任务",
        "根本出发点是保障人民生命财产安全",
    ])
    s += '<polygon points="1190,392 990,710 1390,710" fill="#06192F" fill-opacity=".52" stroke="#CFE7EA" stroke-opacity=".35" stroke-width="2"/>'
    s += '<line x1="1190" y1="392" x2="1190" y2="710" stroke="#CFE7EA" stroke-opacity=".22"/><line x1="990" y1="710" x2="1390" y2="710" stroke="#CFE7EA" stroke-opacity=".22"/><line x1="1090" y1="550" x2="1290" y2="550" stroke="#CFE7EA" stroke-opacity=".22"/>'
    s += data_card(1070, 358, 240, "防洪", "首要任务", "#E73535")
    s += data_card(930, 610, 220, "能源", "清洁电力", "#1ECDD1")
    s += data_card(1230, 610, 220, "航运", "黄金水道", "#F6C85F")
    s += t(1190, 760, "三大需求共同推动工程进入国家决策", 22, "#FFFFFF", 800, "middle")
    return s + end()


def slide3():
    s = bg(3) + header(3) + title_block("百年构想", "从治水设想到国家决策", 210, 64)
    items = [("长期酝酿", "围绕长江治水与水能开发形成构想"), ("系统论证", "新中国成立后持续开展勘测规划研究"), ("国家决策", "1992年全国人大审议通过兴建决议"), ("正式开工", "1994年工程进入全面实施阶段")]
    x = 720
    for i, (a, b) in enumerate(items):
        y = 205 + i * 138
        s += f'<rect x="{x}" y="{y}" width="690" height="100" rx="18" fill="#06192F" fill-opacity=".58" stroke="#CFE7EA" stroke-opacity=".28"/>'
        s += f'<circle cx="{x+48}" cy="{y+50}" r="25" fill="{"#E73535" if i>=2 else "#1ECDD1"}"/>'
        s += t(x + 48, y + 60, str(i + 1), 24, "#FFFFFF", 900, "middle")
        s += t(x + 92, y + 43, a, 27, "#FFFFFF", 900) + t(x + 92, y + 76, b, 20, "#DDECF2", 500)
        if i < 3:
            s += f'<path d="M{x+48} {y+83} V{y+138}" stroke="#CFE7EA" stroke-opacity=".45" stroke-width="4" stroke-dasharray="6 8"/>'
    s += '<rect x="82" y="620" width="540" height="92" rx="18" fill="#06192F" fill-opacity=".58" stroke="#CFE7EA" stroke-opacity=".30"/>'
    s += t(112, 657, "决策逻辑", 24, "#FFFFFF", 900)
    s += t(112, 694, "构想 → 论证 → 决策 → 实施", 25, "#1ECDD1", 900)
    return s + end()


def slide4():
    s = bg(4) + header(4) + title_block("攻坚克难", "三峡工程建设历程", 205, 64)
    s += '<rect x="88" y="555" width="1390" height="175" rx="26" fill="#06192F" fill-opacity=".68" stroke="#CFE7EA" stroke-opacity=".35" filter="url(#shadow)"/>'
    s += '<rect x="130" y="585" width="310" height="34" rx="17" fill="#E73535" fill-opacity=".92"/>' + t(285, 609, "决策准备", 18, "#FFFFFF", 800, "middle")
    s += '<rect x="470" y="585" width="585" height="34" rx="17" fill="#1ECDD1" fill-opacity=".78"/>' + t(762, 609, "主体建设", 18, "#06192F", 900, "middle")
    s += '<rect x="1085" y="585" width="310" height="34" rx="17" fill="#F6C85F" fill-opacity=".88"/>' + t(1240, 609, "投产运行", 18, "#06192F", 900, "middle")
    years = [("1992", "批准建设"), ("1994", "正式开工"), ("1997", "大江截流"), ("2003", "发电通航"), ("2006", "主体完工"), ("2012", "主要完成")]
    for i, (yr, lab) in enumerate(years):
        x = 150 + i * 250
        accent = "#E73535" if i == 0 else ("#F6C85F" if i >= 3 else "#1ECDD1")
        s += f'<circle cx="{x}" cy="650" r="20" fill="{accent}"/><path d="M{x+22} 650 H{x+205}" stroke="#CFE7EA" stroke-opacity=".35" stroke-width="4"/>'
        s += t(x, 685, yr, 31, "#FFFFFF", 900, "middle") + t(x, 716, lab, 18, "#DDECF2", 600, "middle")
    s += '<rect x="920" y="260" width="520" height="170" rx="24" fill="#06192F" fill-opacity=".62" stroke="#CFE7EA" stroke-opacity=".32"/>'
    s += t(955, 312, "这页重点表达", 26, "#FFFFFF", 900)
    s += t(955, 358, "三峡工程从国家决策、开工建设，\n到发电通航和主体完工的关键节点。", 23, "#DDECF2", 600)
    return s + end()


def slide5():
    s = bg(5) + header(5) + title_block("党建引领", "重大工程背后的组织力量", 205, 64)
    s += bullet_panel(76, 430, 610, 300, "党建主线", [
        "把党的领导贯穿工程建设全过程",
        "把组织优势转化为建设效率和治理能力",
        "把党员担当落实到关键节点、急难任务",
    ])
    chain = [
        ("党的领导", "统一部署\n统筹全局"),
        ("组织动员", "基层党组织\n战斗堡垒"),
        ("一线攻坚", "关键节点\n冲锋在前"),
        ("工程保障", "建设、移民\n生态、运行协同"),
    ]
    for i, (title, desc) in enumerate(chain):
        x = 760 + i * 195
        y = 475
        s += f'<rect x="{x}" y="{y}" width="165" height="170" rx="22" fill="#06192F" fill-opacity=".70" stroke="#FF6B6B" stroke-opacity=".42"/>'
        s += f'<circle cx="{x+82}" cy="{y+44}" r="24" fill="#E73535"/>'
        s += t(x + 82, y + 53, str(i + 1), 22, "#FFFFFF", 900, "middle")
        s += t(x + 82, y + 96, title, 25, "#FFFFFF", 900, "middle")
        s += t(x + 82, y + 137, desc, 17, "#DDECF2", 600, "middle")
        if i < 3:
            s += f'<path d="M{x+170} {y+85} H{x+190}" stroke="#CFE7EA" stroke-opacity=".62" stroke-width="5"/><path d="M{x+186} {y+75} L{x+202} {y+85} L{x+186} {y+95}" fill="none" stroke="#CFE7EA" stroke-opacity=".62" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>'
    s += '<rect x="760" y="690" width="750" height="54" rx="27" fill="#E73535" fill-opacity=".88"/>'
    s += t(1135, 726, "表达重点：党建不是口号，而是重大工程建设的组织保障体系", 22, "#FFFFFF", 900, "middle")
    return s + end()


def slide6():
    s = bg(6) + header(6) + title_block("大国重器", "三峡大坝的工程规模", 205, 64)
    s += bullet_panel(78, 420, 560, 280, "核心工程参数", [
        "混凝土重力坝，坝轴线全长约2309米",
        "最大坝高约181米，正常蓄水位175米",
        "水库总库容约393亿立方米",
    ])
    s += data_card(690, 585, 220, "393亿m³", "水库总库容", "#1ECDD1")
    s += data_card(930, 585, 238, "221.5亿m³", "防洪库容", "#E73535")
    s += data_card(1190, 585, 235, "2250万kW", "总装机容量", "#F6C85F")
    s += grouped_dam_chart(855, 235)
    return s + end()


def slide7():
    s = bg(7) + header(7) + title_block("综合效益", "防洪、发电、航运与水资源调度", 200, 58)
    items = [("防洪", "防洪库容约221.5亿立方米"), ("发电", "多年平均年发电量约882亿千瓦时"), ("航运", "双线五级船闸支撑万吨级船队"), ("调度", "汛期削峰、枯水补水，服务流域配置")]
    for i, (a, b) in enumerate(items):
        x = 90 + (i % 2) * 520
        y = 445 + (i // 2) * 130
        s += f'<rect x="{x}" y="{y}" width="470" height="96" rx="18" fill="#06192F" fill-opacity=".62" stroke="#CFE7EA" stroke-opacity=".32"/>'
        s += t(x + 30, y + 42, a, 30, "#FFFFFF", 900) + t(x + 118, y + 42, b, 21, "#DDECF2", 600)
    s += '<rect x="1120" y="410" width="350" height="315" rx="24" fill="#06192F" fill-opacity=".66" stroke="#CFE7EA" stroke-opacity=".32"/>'
    s += t(1295, 455, "能力具体化", 28, "#FFFFFF", 900, "middle")
    s += '<rect x="1150" y="485" width="290" height="92" rx="18" fill="#E73535" fill-opacity=".86"/>'
    s += t(1174, 520, "防洪标准", 19, "#FFFFFF", 800)
    s += t(1174, 557, "约10年一遇  →  约100年一遇", 23, "#FFFFFF", 900)
    s += t(1174, 584, "以荆江河段为代表", 15, "#FFE4E4", 600)
    s += '<rect x="1150" y="600" width="290" height="92" rx="18" fill="#1ECDD1" fill-opacity=".82"/>'
    s += t(1174, 635, "清洁发电", 19, "#06192F", 900)
    s += t(1174, 672, "882亿千瓦时/年", 25, "#06192F", 900)
    s += t(1174, 699, "多年平均年发电量", 15, "#12345A", 700)
    return s + end()


def slide8():
    s = bg(8) + header(8) + title_block("今日三峡", "现代化运行与长江大保护", 205, 64)
    s += '<rect x="80" y="470" width="1380" height="190" rx="28" fill="#06192F" fill-opacity=".66" stroke="#CFE7EA" stroke-opacity=".35" filter="url(#shadow)"/>'
    s += data_card(125, 498, 360, "1.8万亿kWh+", "截至2025年8月累计发电量突破", "#E73535")
    s += data_card(570, 498, 360, "22亿吨+", "三峡船闸累计货运量超过", "#1ECDD1")
    s += data_card(1015, 498, 360, "智能调度", "数字化、精细化运行管理", "#F6C85F")
    s += mini_metric(170, 710, "能源安全", "清洁电力", "#E73535")
    s += mini_metric(390, 710, "航运效率", "通江达海", "#1ECDD1")
    s += mini_metric(610, 710, "水资源", "枯水补水", "#F6C85F")
    s += mini_metric(830, 710, "生态治理", "长江大保护", "#7ED6A5")
    return s + end()


def slide9():
    s = bg(9) + header(9) + title_block("辩证看待", "成就、挑战与长期治理", 205, 64)
    s += bullet_panel(78, 420, 520, 292, "怎么看待三峡工程", [
        "既看防洪、发电、航运等综合效益",
        "也看生态、泥沙、库区发展的长期课题",
        "关键在于持续监测、动态优化、系统治理",
    ], "#1ECDD1")
    tasks = [
        ("生态监测", "水质、生境、岸线\n长期跟踪"),
        ("泥沙调度", "来沙变化、库区淤积\n滚动评估"),
        ("库区发展", "移民后扶、产业重建\n民生改善"),
    ]
    for i, (title, desc) in enumerate(tasks):
        x = 675 + i * 260
        y = 450
        s += f'<rect x="{x}" y="{y}" width="220" height="150" rx="20" fill="#06192F" fill-opacity=".66" stroke="#CFE7EA" stroke-opacity=".32"/>'
        s += f'<rect x="{x}" y="{y}" width="220" height="8" rx="4" fill="{"#1ECDD1" if i==0 else ("#F6C85F" if i==1 else "#E73535")}"/>'
        s += t(x + 110, y + 58, title, 26, "#FFFFFF", 900, "middle")
        s += t(x + 110, y + 100, desc, 17, "#DDECF2", 600, "middle")
    s += '<rect x="740" y="650" width="610" height="62" rx="31" fill="#E73535" fill-opacity=".88"/>'
    s += t(1045, 690, "长期治理闭环：监测 → 评估 → 优化 → 再监测", 23, "#FFFFFF", 900, "middle")
    return s + end()


def slide10():
    s = bg(10) + header(10) + title_block("从一座大坝，\n看见中国式现代化的治理能力", "谢谢各位领导", 220, 56)
    for i, (a, b) in enumerate([("战略", "国家重大工程"), ("技术", "工程装备能力"), ("组织", "集中力量办大事"), ("人民", "安全与发展")]):
        x = 115 + i * 360
        s += f'<rect x="{x}" y="645" width="265" height="118" rx="20" fill="#06192F" fill-opacity=".58" stroke="#CFE7EA" stroke-opacity=".35"/>'
        s += t(x + 132, 697, a, 34, "#FFFFFF", 900, "middle") + t(x + 132, 733, b, 20, "#DDECF2", 600, "middle")
    return s + end()


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
    z.writestr("docProps/core.xml", f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:title>三峡大坝的历史与现在</dc:title><dc:creator>Codex</dc:creator><cp:lastModifiedBy>Codex</cp:lastModifiedBy><dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created><dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified></cp:coreProperties>''')
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
    z.writestr("ppt/theme/theme1.xml", '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Visual"><a:themeElements><a:clrScheme name="Visual"><a:dk1><a:srgbClr val="06192F"/></a:dk1><a:lt1><a:srgbClr val="FFFFFF"/></a:lt1><a:dk2><a:srgbClr val="12345A"/></a:dk2><a:lt2><a:srgbClr val="F4F7FA"/></a:lt2><a:accent1><a:srgbClr val="E73535"/></a:accent1><a:accent2><a:srgbClr val="1ECDD1"/></a:accent2><a:accent3><a:srgbClr val="F6C85F"/></a:accent3><a:accent4><a:srgbClr val="CFE7EA"/></a:accent4><a:accent5><a:srgbClr val="12345A"/></a:accent5><a:accent6><a:srgbClr val="9FB3C8"/></a:accent6><a:hlink><a:srgbClr val="1ECDD1"/></a:hlink><a:folHlink><a:srgbClr val="9FB3C8"/></a:folHlink></a:clrScheme><a:fontScheme name="Microsoft YaHei"><a:majorFont><a:latin typeface="Microsoft YaHei"/><a:ea typeface="Microsoft YaHei"/><a:cs typeface="Microsoft YaHei"/></a:majorFont><a:minorFont><a:latin typeface="Microsoft YaHei"/><a:ea typeface="Microsoft YaHei"/><a:cs typeface="Microsoft YaHei"/></a:minorFont></a:fontScheme><a:fmtScheme name="Default"><a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst><a:lnStyleLst><a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst><a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst><a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst></a:fmtScheme></a:themeElements><a:objectDefaults/><a:extraClrSchemeLst/></a:theme>''')


def build():
    os.makedirs(ASSET_DIR, exist_ok=True)
    paths = []
    for i, fn in enumerate(SLIDES, 1):
        path = os.path.join(ASSET_DIR, f"slide{i:02d}.svg")
        with open(path, "w", encoding="utf-8") as f:
            f.write(fn())
        paths.append(path)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        write_common(z, len(paths))
        for i, path in enumerate(paths, 1):
            z.writestr(f"ppt/slides/slide{i}.xml", pic_slide(i))
            z.writestr(f"ppt/slides/_rels/slide{i}.xml.rels", f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/slide{i:02d}.svg"/></Relationships>''')
            z.write(path, f"ppt/media/slide{i:02d}.svg")
    print(os.path.abspath(OUT))


if __name__ == "__main__":
    build()
