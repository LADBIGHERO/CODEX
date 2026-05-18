import html
import os
import zipfile
from datetime import datetime, timezone


OUT = "三峡大坝的历史与现在_初版.pptx"
IMG = "three_gorges_cover.png"

W, H = 12192000, 6858000


def emu(x):
    return int(x * 914400)


def esc(s):
    return html.escape(str(s), quote=True)


def color(hex_color):
    return hex_color.replace("#", "").upper()


def solid_fill(hex_color, alpha=None):
    a = f'<a:alpha val="{alpha}"/>' if alpha is not None else ""
    return f'<a:solidFill><a:srgbClr val="{color(hex_color)}">{a}</a:srgbClr></a:solidFill>'


def shape_xml(i, x, y, w, h, fill="#FFFFFF", line=None, radius=False, alpha=None):
    prst = "roundRect" if radius else "rect"
    line_xml = '<a:ln><a:noFill/></a:ln>' if line is None else f'<a:ln w="12700">{solid_fill(line)}</a:ln>'
    return f'''
<p:sp>
  <p:nvSpPr><p:cNvPr id="{i}" name="Shape {i}"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
  <p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm><a:prstGeom prst="{prst}"><a:avLst/></a:prstGeom>{solid_fill(fill, alpha)}{line_xml}</p:spPr>
  <p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody>
</p:sp>'''


def textbox_xml(i, x, y, w, h, paragraphs, font_size=20, bold=False, color_hex="#1F2D3A",
                align="l", valign="top", fill=None, line=None, margin=0.08):
    fill_xml = solid_fill(fill) if fill else "<a:noFill/>"
    line_xml = '<a:ln><a:noFill/></a:ln>' if line is None else f'<a:ln w="12700">{solid_fill(line)}</a:ln>'
    body = []
    for p in paragraphs:
        if isinstance(p, tuple):
            text, size, is_bold, c = p
        else:
            text, size, is_bold, c = p, font_size, bold, color_hex
        body.append(f'''
<a:p><a:pPr algn="{align}"/><a:r><a:rPr lang="zh-CN" sz="{int(size*100)}" b="{1 if is_bold else 0}"><a:latin typeface="Microsoft YaHei"/><a:ea typeface="Microsoft YaHei"/><a:cs typeface="Microsoft YaHei"/>{solid_fill(c)}</a:rPr><a:t>{esc(text)}</a:t></a:r></a:p>''')
    inset = int(margin * 914400)
    va = {"top": "t", "mid": "ctr", "bottom": "b"}.get(valign, "t")
    return f'''
<p:sp>
  <p:nvSpPr><p:cNvPr id="{i}" name="TextBox {i}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>
  <p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom>{fill_xml}{line_xml}</p:spPr>
  <p:txBody><a:bodyPr wrap="square" lIns="{inset}" tIns="{inset}" rIns="{inset}" bIns="{inset}" anchor="{va}"/><a:lstStyle/>{''.join(body)}</p:txBody>
</p:sp>'''


def picture_xml(i, rid, x, y, w, h):
    return f'''
<p:pic>
  <p:nvPicPr><p:cNvPr id="{i}" name="Picture {i}"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr>
  <p:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>
  <p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>
</p:pic>'''


def line_xml(i, x1, y1, x2, y2, line="#1E7F86", width=25400):
    x, y = min(x1, x2), min(y1, y2)
    w, h = abs(x2 - x1), abs(y2 - y1)
    return f'''
<p:cxnSp>
  <p:nvCxnSpPr><p:cNvPr id="{i}" name="Line {i}"/><p:cNvCxnSpPr/><p:nvPr/></p:nvCxnSpPr>
  <p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm><a:prstGeom prst="line"><a:avLst/></a:prstGeom><a:ln w="{width}">{solid_fill(line)}</a:ln></p:spPr>
</p:cxnSp>'''


def footer(n):
    return (
        textbox_xml(900 + n, emu(0.45), emu(7.05), emu(2.2), emu(0.25), [f"{n:02d}"], 9, False, "#6C7885")
        + textbox_xml(950 + n, emu(10.0), emu(7.05), emu(2.9), emu(0.25), ["三峡大坝的历史与现在"], 8, False, "#6C7885", align="r")
    )


def header(title):
    return (
        textbox_xml(11, emu(0.6), emu(0.28), emu(8.2), emu(0.55), [title], 26, True, "#12345A")
        + shape_xml(12, emu(0.62), emu(0.92), emu(1.7), emu(0.05), "#C51F2C")
    )


def slide_wrap(body, bg="#F6F8FB"):
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld>
    <p:bg><p:bgPr>{solid_fill(bg)}<a:effectLst/></p:bgPr></p:bg>
    <p:spTree>
      <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
      <p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{W}" cy="{H}"/><a:chOff x="0" y="0"/><a:chExt cx="{W}" cy="{H}"/></a:xfrm></p:grpSpPr>
      {body}
    </p:spTree>
  </p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sld>'''


def title_card(i, num, label, desc, x, y, w=2.15, accent="#1E7F86"):
    return (
        shape_xml(i, emu(x), emu(y), emu(w), emu(0.95), "#FFFFFF", "#DCE5EE", True)
        + shape_xml(i + 100, emu(x), emu(y), emu(0.08), emu(0.95), accent)
        + textbox_xml(i + 200, emu(x + 0.12), emu(y + 0.07), emu(w - 0.2), emu(0.36), [num], 22, True, accent)
        + textbox_xml(i + 300, emu(x + 0.12), emu(y + 0.45), emu(w - 0.2), emu(0.38), [f"{label}｜{desc}"], 8.5, False, "#2F3A45")
    )


slides = []
rels = []

# 1 Cover
body = (
    picture_xml(10, "rId2", 0, 0, W, H)
    + shape_xml(20, 0, 0, emu(5.4), H, "#0B2440", alpha=82000)
    + shape_xml(21, emu(0.78), emu(4.58), emu(2.4), emu(0.055), "#C51F2C")
    + textbox_xml(22, emu(0.72), emu(2.95), emu(5.2), emu(0.9), ["三峡大坝的历史与现在"], 32, True, "#FFFFFF")
    + textbox_xml(23, emu(0.76), emu(3.88), emu(4.9), emu(0.55), ["党领导下的国家重大水利工程实践"], 16, False, "#E9F2F7")
    + textbox_xml(24, emu(0.78), emu(5.05), emu(4.9), emu(0.45), ["从治水兴邦到现代化流域治理"], 13, False, "#CFE7EA")
)
slides.append(slide_wrap(body, "#0B2440"))
rels.append(True)

# 2 Background
body = header("一江安澜：三峡工程建设的时代背景")
for idx, t in enumerate(["防洪安全", "清洁能源", "黄金水道"]):
    x = 0.75 + idx * 2.15
    body += shape_xml(30 + idx, emu(x), emu(5.85), emu(1.75), emu(0.45), ["#C51F2C", "#1E7F86", "#12345A"][idx], None, True)
    body += textbox_xml(40 + idx, emu(x), emu(5.89), emu(1.75), emu(0.35), [t], 12, True, "#FFFFFF", align="ctr")
bullets = ["长江干流全长约6300公里，是我国重要经济轴线", "中下游人口密集、产业集中，防洪安全关系全局", "工程承担防洪、发电、航运、水资源调度等综合任务", "根本出发点是保障人民生命财产安全、服务国家发展大局"]
body += textbox_xml(50, emu(0.7), emu(1.35), emu(5.5), emu(3.7), [f"• {b}" for b in bullets], 16, False, "#263645")
body += shape_xml(60, emu(7.1), emu(1.18), emu(5.3), emu(4.65), "#FFFFFF", "#DDE6EE", True)
body += textbox_xml(61, emu(7.35), emu(1.42), emu(4.75), emu(0.38), ["长江流域与三峡位置示意"], 15, True, "#12345A", align="ctr")
body += line_xml(62, emu(7.65), emu(4.85), emu(11.65), emu(2.65), "#1E7F86", 76200)
body += line_xml(63, emu(8.15), emu(4.15), emu(10.1), emu(3.78), "#1E7F86", 38100)
body += shape_xml(64, emu(9.15), emu(3.45), emu(0.25), emu(0.25), "#C51F2C", None, True)
body += textbox_xml(65, emu(9.42), emu(3.34), emu(1.4), emu(0.35), ["三峡坝址"], 11, True, "#C51F2C")
body += textbox_xml(66, emu(7.55), emu(5.1), emu(4.4), emu(0.5), ["上游调蓄、下游防洪、全流域协同"], 12, False, "#637381", align="ctr")
body += footer(2)
slides.append(slide_wrap(body))
rels.append(False)

# 3 History
body = header("百年构想：从治水设想到国家决策")
items = [("早期设想", "围绕长江治水与水能开发，形成三峡工程构想"), ("系统论证", "新中国成立后持续开展勘测、规划与科学研究"), ("国家决策", "1992年全国人大审议通过兴建三峡工程决议"), ("正式开工", "1994年工程开工，百年构想进入实施阶段")]
for idx, (t, d) in enumerate(items):
    x = 0.9 + idx * 3.05
    body += shape_xml(70 + idx, emu(x), emu(2.15), emu(2.45), emu(2.25), "#FFFFFF", "#DDE6EE", True)
    body += shape_xml(80 + idx, emu(x), emu(2.15), emu(2.45), emu(0.12), "#1E7F86" if idx < 2 else "#C51F2C")
    body += textbox_xml(90 + idx, emu(x + 0.18), emu(2.48), emu(2.1), emu(0.45), [t], 18, True, "#12345A", align="ctr")
    body += textbox_xml(100 + idx, emu(x + 0.24), emu(3.1), emu(1.98), emu(0.88), [d], 12, False, "#3B4A59", align="ctr")
body += textbox_xml(120, emu(1.05), emu(5.15), emu(11.25), emu(0.65), ["从设想到落地，体现党和国家对重大工程、重大民生、重大安全问题的长期谋划能力。"], 18, True, "#12345A", align="ctr")
body += footer(3)
slides.append(slide_wrap(body))
rels.append(False)

# 4 Timeline
body = header("攻坚克难：三峡工程建设历程")
body += line_xml(130, emu(1.1), emu(3.4), emu(12.0), emu(3.4), "#1E7F86", 50800)
times = [("1992", "批准建设"), ("1994", "正式开工"), ("1997", "大江截流"), ("2003", "首批发电\n船闸通航"), ("2006", "主体完工"), ("2012", "主要任务完成")]
for idx, (year, label) in enumerate(times):
    x = 1.05 + idx * 2.15
    body += shape_xml(140 + idx, emu(x), emu(3.18), emu(0.44), emu(0.44), "#C51F2C" if idx in (0, 3, 5) else "#1E7F86", None, True)
    body += textbox_xml(150 + idx, emu(x - 0.45), emu(2.3 if idx % 2 == 0 else 3.8), emu(1.35), emu(0.35), [year], 18, True, "#12345A", align="ctr")
    body += textbox_xml(160 + idx, emu(x - 0.62), emu(2.72 if idx % 2 == 0 else 4.22), emu(1.75), emu(0.55), [label], 10.5, False, "#3B4A59", align="ctr")
body += textbox_xml(175, emu(1.05), emu(5.55), emu(11.0), emu(0.52), ["建设周期长、技术难度高、组织协同复杂，是我国重大工程建设能力的集中展示。"], 17, True, "#12345A", align="ctr")
body += footer(4)
slides.append(slide_wrap(body))
rels.append(False)

# 5 Party building
body = header("党建引领：重大工程背后的组织力量")
body += shape_xml(180, emu(0.75), emu(1.35), emu(5.5), emu(4.75), "#12345A", None, True)
body += shape_xml(181, emu(0.75), emu(1.35), emu(0.16), emu(4.75), "#C51F2C")
body += textbox_xml(182, emu(1.15), emu(2.12), emu(4.65), emu(1.15), ["党的领导贯穿工程建设、移民安置、生态保护和运行管理全过程"], 20, True, "#FFFFFF")
body += textbox_xml(183, emu(1.15), emu(3.55), emu(4.65), emu(1.15), ["工程涉及百万级移民安置，是一项复杂的工程建设任务，也是一项系统的社会治理任务。"], 14, False, "#DDECF2")
cards = [("领导", "统一部署\n统筹全局"), ("组织", "基层党组织\n战斗堡垒"), ("攻坚", "关键节点\n冲锋在前"), ("担当", "党员干部\n一线作为")]
for idx, (t, d) in enumerate(cards):
    x = 7.05 + (idx % 2) * 2.55
    y = 1.75 + (idx // 2) * 2.05
    body += shape_xml(190 + idx, emu(x), emu(y), emu(2.25), emu(1.55), "#FFFFFF", "#DDE6EE", True)
    body += textbox_xml(200 + idx, emu(x + 0.18), emu(y + 0.2), emu(1.9), emu(0.38), [t], 19, True, "#C51F2C", align="ctr")
    body += textbox_xml(210 + idx, emu(x + 0.22), emu(y + 0.75), emu(1.82), emu(0.6), [d], 12, False, "#344250", align="ctr")
body += footer(5)
slides.append(slide_wrap(body))
rels.append(False)

# 6 Scale
body = header("大国重器：三峡大坝的工程规模")
body += shape_xml(220, emu(0.72), emu(1.32), emu(11.88), emu(4.78), "#EEF3F6", "#DDE6EE", True)
body += shape_xml(221, emu(3.55), emu(3.58), emu(5.25), emu(0.82), "#8795A1")
body += shape_xml(222, emu(4.2), emu(2.55), emu(3.95), emu(1.05), "#6F7F8D")
body += line_xml(223, emu(3.8), emu(4.4), emu(8.55), emu(4.4), "#1E7F86", 63500)
params = [("2309米", "坝轴线全长", "混凝土重力坝"), ("181米", "最大坝高", "工程垂直尺度"), ("393亿m³", "水库总库容", "流域调蓄基础"), ("221.5亿m³", "防洪库容", "防洪核心能力"), ("2250万kW", "总装机容量", "世界级水电站")]
pos = [(0.95, 1.6), (3.25, 1.6), (9.95, 1.6), (1.55, 4.85), (9.05, 4.85)]
for idx, p in enumerate(params):
    body += title_card(230 + idx, p[0], p[1], p[2], *pos[idx], w=2.2, accent="#C51F2C" if idx in (3, 4) else "#1E7F86")
body += footer(6)
slides.append(slide_wrap(body))
rels.append(False)

# 7 Benefits
body = header("综合效益：防洪、发电、航运与调度")
benefits = [("防洪", "防洪库容约221.5亿立方米\n提升长江中下游安全保障"), ("发电", "多年平均年发电量约882亿千瓦时\n持续输出清洁电能"), ("航运", "双线五级船闸支撑万吨级船队\n改善川江航道条件"), ("调度", "汛期削峰、枯水补水\n服务流域水资源配置")]
for idx, (t, d) in enumerate(benefits):
    x = 0.85 + (idx % 2) * 6.0
    y = 1.35 + (idx // 2) * 2.55
    accent = ["#C51F2C", "#1E7F86", "#12345A", "#617586"][idx]
    body += shape_xml(260 + idx, emu(x), emu(y), emu(5.45), emu(2.05), "#FFFFFF", "#DDE6EE", True)
    body += shape_xml(270 + idx, emu(x), emu(y), emu(0.16), emu(2.05), accent)
    body += textbox_xml(280 + idx, emu(x + 0.38), emu(y + 0.28), emu(4.7), emu(0.45), [t], 22, True, accent)
    body += textbox_xml(290 + idx, emu(x + 0.4), emu(y + 0.9), emu(4.65), emu(0.75), [d], 13, False, "#344250")
body += footer(7)
slides.append(slide_wrap(body))
rels.append(False)

# 8 Today
body = header("今日三峡：现代化运行与长江大保护")
body += shape_xml(300, emu(0.75), emu(1.25), emu(11.8), emu(2.1), "#12345A", None, True)
body += textbox_xml(301, emu(1.05), emu(1.65), emu(10.95), emu(0.6), ["从工程建设转向高质量运行管理"], 25, True, "#FFFFFF", align="ctr")
body += textbox_xml(302, emu(1.2), emu(2.36), emu(10.65), emu(0.38), ["数字化、智能化调度服务国家能源安全、长江经济带发展和长江大保护"], 13, False, "#DDECF2", align="ctr")
today = [("1.8万亿kWh+", "截至2025年8月累计发电量突破"), ("22亿吨+", "三峡船闸累计货运量超过"), ("2003年以来", "首批机组投产、永久船闸通航")]
for idx, (n, lab) in enumerate(today):
    x = 0.9 + idx * 4.05
    body += shape_xml(310 + idx, emu(x), emu(4.0), emu(3.45), emu(1.45), "#FFFFFF", "#DDE6EE", True)
    body += textbox_xml(320 + idx, emu(x + 0.15), emu(4.2), emu(3.15), emu(0.42), [n], 23, True, "#C51F2C" if idx == 0 else "#1E7F86", align="ctr")
    body += textbox_xml(330 + idx, emu(x + 0.22), emu(4.78), emu(3.0), emu(0.4), [lab], 10.5, False, "#344250", align="ctr")
body += footer(8)
slides.append(slide_wrap(body))
rels.append(False)

# 9 Balanced view
body = header("辩证看待：成就、挑战与长期治理")
body += shape_xml(340, emu(0.9), emu(1.45), emu(5.3), emu(4.65), "#FFFFFF", "#DDE6EE", True)
body += shape_xml(341, emu(6.85), emu(1.45), emu(5.3), emu(4.65), "#FFFFFF", "#DDE6EE", True)
body += textbox_xml(342, emu(1.2), emu(1.82), emu(4.75), emu(0.5), ["综合成就"], 22, True, "#1E7F86", align="ctr")
body += textbox_xml(343, emu(7.15), emu(1.82), emu(4.75), emu(0.5), ["长期课题"], 22, True, "#C51F2C", align="ctr")
body += textbox_xml(344, emu(1.25), emu(2.6), emu(4.65), emu(2.5), ["• 防洪能力提升\n• 清洁能源供应\n• 航运条件改善\n• 水资源调度增强"], 16, False, "#344250")
body += textbox_xml(345, emu(7.2), emu(2.6), emu(4.65), emu(2.5), ["• 生态环境保护\n• 泥沙淤积监测\n• 库区发展与移民后续扶持\n• 文物保护与长期治理"], 16, False, "#344250")
body += line_xml(346, emu(5.95), emu(3.75), emu(6.85), emu(3.75), "#617586", 38100)
body += textbox_xml(347, emu(5.45), emu(4.05), emu(1.9), emu(0.4), ["系统治理"], 12, True, "#12345A", align="ctr")
body += footer(9)
slides.append(slide_wrap(body))
rels.append(False)

# 10 Close
body = (
    picture_xml(400, "rId2", 0, 0, W, H)
    + shape_xml(401, 0, 0, W, H, "#081A2E", alpha=76000)
    + textbox_xml(402, emu(0.85), emu(1.55), emu(10.9), emu(0.9), ["从一座大坝，看见中国式现代化的治理能力"], 30, True, "#FFFFFF", align="ctr")
    + shape_xml(403, emu(5.25), emu(2.62), emu(2.8), emu(0.055), "#C51F2C")
)
words = [("战略", "国家重大工程"), ("技术", "工程装备能力"), ("组织", "集中力量办大事"), ("人民", "安全与发展")]
for idx, (t, d) in enumerate(words):
    x = 1.25 + idx * 2.9
    body += shape_xml(410 + idx, emu(x), emu(3.55), emu(2.25), emu(1.1), "#FFFFFF", "#FFFFFF", True, alpha=30000)
    body += textbox_xml(420 + idx, emu(x + 0.15), emu(3.75), emu(1.95), emu(0.38), [t], 20, True, "#FFFFFF", align="ctr")
    body += textbox_xml(430 + idx, emu(x + 0.15), emu(4.18), emu(1.95), emu(0.32), [d], 9.5, False, "#E4EEF4", align="ctr")
body += textbox_xml(450, emu(4.6), emu(5.92), emu(4.1), emu(0.45), ["谢谢各位领导"], 20, True, "#FFFFFF", align="ctr")
slides.append(slide_wrap(body, "#081A2E"))
rels.append(True)


def rels_xml(slide_count):
    rel = ['<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>']
    for i in range(slide_count):
        rel.append(f'<Relationship Id="rId{i+2}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide{i+1}.xml"/>')
    rel.append(f'<Relationship Id="rId{slide_count+2}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="theme/theme1.xml"/>')
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{''.join(rel)}</Relationships>'''


def presentation_xml(slide_count):
    ids = ''.join([f'<p:sldId id="{256+i}" r:id="rId{i+2}"/>' for i in range(slide_count)])
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>
  <p:sldIdLst>{ids}</p:sldIdLst>
  <p:sldSz cx="{W}" cy="{H}" type="wide"/>
  <p:notesSz cx="6858000" cy="9144000"/>
  <p:defaultTextStyle/>
</p:presentation>'''


def content_types(slide_count):
    overrides = [
        '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>',
        '<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>',
        '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>',
        '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>',
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>',
        '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>',
    ]
    overrides += [f'<Override PartName="/ppt/slides/slide{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>' for i in range(1, slide_count + 1)]
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="png" ContentType="image/png"/>
  {''.join(overrides)}
</Types>'''


MASTER = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
<p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{W}" cy="{H}"/><a:chOff x="0" y="0"/><a:chExt cx="{W}" cy="{H}"/></a:xfrm></p:grpSpPr></p:spTree></p:cSld>
<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>
<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>
<p:txStyles><p:titleStyle/><p:bodyStyle/><p:otherStyle/></p:txStyles>
</p:sldMaster>'''

LAYOUT = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" type="blank" preserve="1">
<p:cSld name="Blank"><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{W}" cy="{H}"/><a:chOff x="0" y="0"/><a:chExt cx="{W}" cy="{H}"/></a:xfrm></p:grpSpPr></p:spTree></p:cSld>
<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sldLayout>'''

THEME = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="ThreeGorgesBriefing">
<a:themeElements><a:clrScheme name="Briefing"><a:dk1><a:srgbClr val="12345A"/></a:dk1><a:lt1><a:srgbClr val="FFFFFF"/></a:lt1><a:dk2><a:srgbClr val="2F3A45"/></a:dk2><a:lt2><a:srgbClr val="F6F8FB"/></a:lt2><a:accent1><a:srgbClr val="1E7F86"/></a:accent1><a:accent2><a:srgbClr val="C51F2C"/></a:accent2><a:accent3><a:srgbClr val="617586"/></a:accent3><a:accent4><a:srgbClr val="E8EDF2"/></a:accent4><a:accent5><a:srgbClr val="12345A"/></a:accent5><a:accent6><a:srgbClr val="8BA7AE"/></a:accent6><a:hlink><a:srgbClr val="1E7F86"/></a:hlink><a:folHlink><a:srgbClr val="617586"/></a:folHlink></a:clrScheme><a:fontScheme name="Microsoft YaHei"><a:majorFont><a:latin typeface="Microsoft YaHei"/><a:ea typeface="Microsoft YaHei"/><a:cs typeface="Microsoft YaHei"/></a:majorFont><a:minorFont><a:latin typeface="Microsoft YaHei"/><a:ea typeface="Microsoft YaHei"/><a:cs typeface="Microsoft YaHei"/></a:minorFont></a:fontScheme><a:fmtScheme name="Default"><a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst><a:lnStyleLst><a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst><a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst><a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst></a:fmtScheme></a:themeElements><a:objectDefaults/><a:extraClrSchemeLst/></a:theme>'''


def slide_rels(has_image):
    img_rel = '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/three_gorges_cover.png"/>' if has_image else ""
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>{img_rel}</Relationships>'''


def write_pptx():
    now = datetime.now(timezone.utc).isoformat()
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types(len(slides)))
        z.writestr("_rels/.rels", '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/></Relationships>''')
        z.writestr("docProps/core.xml", f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:title>三峡大坝的历史与现在</dc:title><dc:creator>Codex</dc:creator><cp:lastModifiedBy>Codex</cp:lastModifiedBy><dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created><dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified></cp:coreProperties>''')
        z.writestr("docProps/app.xml", f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"><Application>Codex</Application><PresentationFormat>宽屏</PresentationFormat><Slides>{len(slides)}</Slides></Properties>''')
        z.writestr("ppt/presentation.xml", presentation_xml(len(slides)))
        z.writestr("ppt/_rels/presentation.xml.rels", rels_xml(len(slides)))
        z.writestr("ppt/slideMasters/slideMaster1.xml", MASTER)
        z.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels", '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/></Relationships>''')
        z.writestr("ppt/slideLayouts/slideLayout1.xml", LAYOUT)
        z.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels", '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/></Relationships>''')
        z.writestr("ppt/theme/theme1.xml", THEME)
        for idx, s in enumerate(slides, 1):
            z.writestr(f"ppt/slides/slide{idx}.xml", s)
            z.writestr(f"ppt/slides/_rels/slide{idx}.xml.rels", slide_rels(rels[idx - 1]))
        if os.path.exists(IMG):
            z.write(IMG, "ppt/media/three_gorges_cover.png")


if __name__ == "__main__":
    write_pptx()
    print(os.path.abspath(OUT))
