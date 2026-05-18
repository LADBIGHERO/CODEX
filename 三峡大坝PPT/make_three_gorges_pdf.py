import math
import re
import struct
from pathlib import Path


OUT = "三峡大坝的历史与现在_预览稿.pdf"
PAGE_W, PAGE_H = 1152.0, 648.0  # 16:9, 72 dpi
ROOT = Path(__file__).resolve().parent

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


def rgb(hex_color):
    h = hex_color.strip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def png_info(path):
    data = Path(path).read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"Not PNG: {path}")
    pos = 8
    width = height = bit = ctype = None
    idat = []
    while pos < len(data):
        ln = struct.unpack(">I", data[pos:pos + 4])[0]
        typ = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + ln]
        if typ == b"IHDR":
            width, height, bit, ctype, *_ = struct.unpack(">IIBBBBB", chunk)
        elif typ == b"IDAT":
            idat.append(chunk)
        elif typ == b"IEND":
            break
        pos += 12 + ln
    if bit != 8 or ctype != 2:
        raise ValueError(f"Only 8-bit RGB PNG supported: {path}, bit={bit}, type={ctype}")
    return width, height, b"".join(idat)


def esc_text(s):
    return str(s).encode("utf-16-be").hex().upper()


class PDF:
    def __init__(self):
        self.objects = []
        self.pages = []
        self.images = []
        self.font_obj = self.add("<< /Type /Font /Subtype /Type0 /BaseFont /STSong-Light /Encoding /UniGB-UCS2-H /DescendantFonts [ << /Type /Font /Subtype /CIDFontType0 /BaseFont /STSong-Light /CIDSystemInfo << /Registry (Adobe) /Ordering (GB1) /Supplement 2 >> /FontDescriptor << /Type /FontDescriptor /FontName /STSong-Light /Flags 4 /Ascent 880 /Descent -120 /CapHeight 700 /StemV 80 >> >> ] >>")
        self.gs = {}
        for name, alpha in [("GS25", .25), ("GS45", .45), ("GS55", .55), ("GS65", .65), ("GS75", .75), ("GS85", .85)]:
            self.gs[name] = self.add(f"<< /Type /ExtGState /ca {alpha} /CA {alpha} >>")

    def add(self, data):
        self.objects.append(data)
        return len(self.objects)

    def stream(self, dict_text, data):
        if isinstance(data, str):
            data = data.encode("utf-8")
        return self.add(f"{dict_text} /Length {len(data)} >>\nstream\n".encode() + data + b"\nendstream")

    def image_obj(self, path):
        w, h, data = png_info(ROOT / path)
        obj = self.stream(
            f"<< /Type /XObject /Subtype /Image /Width {w} /Height {h} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /DecodeParms << /Predictor 15 /Colors 3 /BitsPerComponent 8 /Columns {w} >>",
            data,
        )
        self.images.append((obj, w, h))
        return obj, w, h

    def page(self, img_path, ops):
        im_obj, iw, ih = self.image_obj(img_path)
        resources = f"<< /Font << /F1 {self.font_obj} 0 R >> /XObject << /Im1 {im_obj} 0 R >> /ExtGState << " + " ".join([f"/{k} {v} 0 R" for k, v in self.gs.items()]) + " >> >>"
        content = []
        scale = max(PAGE_W / iw, PAGE_H / ih)
        dw, dh = iw * scale, ih * scale
        x, y = (PAGE_W - dw) / 2, (PAGE_H - dh) / 2
        content.append(f"q 0 0 {PAGE_W:.2f} {PAGE_H:.2f} re W n {dw:.2f} 0 0 {dh:.2f} {x:.2f} {y:.2f} cm /Im1 Do Q")
        content.extend(ops)
        cont_obj = self.stream("<<", "\n".join(content))
        page_obj = self.add(f"<< /Type /Page /Parent 0 0 R /MediaBox [0 0 {PAGE_W:.2f} {PAGE_H:.2f}] /Resources {resources} /Contents {cont_obj} 0 R >>")
        self.pages.append(page_obj)

    def save(self, path):
        pages_obj = len(self.objects) + 1
        catalog_obj = len(self.objects) + 2
        for i, obj in enumerate(self.objects):
            if isinstance(obj, str) and "/Parent 0 0 R" in obj:
                self.objects[i] = obj.replace("/Parent 0 0 R", f"/Parent {pages_obj} 0 R")
        kids = " ".join([f"{p} 0 R" for p in self.pages])
        self.objects.append(f"<< /Type /Pages /Kids [ {kids} ] /Count {len(self.pages)} >>")
        self.objects.append(f"<< /Type /Catalog /Pages {pages_obj} 0 R >>")
        out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for idx, obj in enumerate(self.objects, 1):
            offsets.append(len(out))
            out.extend(f"{idx} 0 obj\n".encode())
            if isinstance(obj, bytes):
                out.extend(obj)
            else:
                out.extend(obj.encode("utf-8"))
            out.extend(b"\nendobj\n")
        xref = len(out)
        out.extend(f"xref\n0 {len(self.objects)+1}\n0000000000 65535 f \n".encode())
        for off in offsets[1:]:
            out.extend(f"{off:010d} 00000 n \n".encode())
        out.extend(f"trailer\n<< /Size {len(self.objects)+1} /Root {catalog_obj} 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
        Path(path).write_bytes(out)


def rect(x, y, w, h, fill="#06192F", gs="GS65", stroke=None):
    r, g, b = rgb(fill)
    ops = [f"q /{gs} gs {r:.3f} {g:.3f} {b:.3f} rg {x:.2f} {y:.2f} {w:.2f} {h:.2f} re f Q"]
    if stroke:
        sr, sg, sb = rgb(stroke)
        ops.append(f"q {sr:.3f} {sg:.3f} {sb:.3f} RG 1.2 w {x:.2f} {y:.2f} {w:.2f} {h:.2f} re S Q")
    return ops


def text(x, y, s, size=24, color="#FFFFFF", align="left", leading=1.25):
    r, g, b = rgb(color)
    ops = []
    for i, line in enumerate(str(s).split("\n")):
        tx = x
        if align == "center":
            tx = x - len(line) * size * .26
        elif align == "right":
            tx = x - len(line) * size * .52
        ty = PAGE_H - y - i * size * leading
        ops.append(f"BT /F1 {size:.1f} Tf {r:.3f} {g:.3f} {b:.3f} rg 1 0 0 1 {tx:.2f} {ty:.2f} Tm <{esc_text(line)}> Tj ET")
    return ops


def line(x1, y1, x2, y2, color="#CFE7EA", width=2, gs=None):
    r, g, b = rgb(color)
    gso = f"/{gs} gs " if gs else ""
    return [f"q {gso}{r:.3f} {g:.3f} {b:.3f} RG {width:.2f} w {x1:.2f} {PAGE_H-y1:.2f} m {x2:.2f} {PAGE_H-y2:.2f} l S Q"]


def title_ops(page, title, subtitle="", y=180, size=48):
    ops = []
    ops += text(56, 72, "◆ 党建引领  工程报国", 18, "#FF3B30")
    ops += text(1088, 52, f"{page:02d}", 12, "#CFE7EA", "right")
    ops += text(56, y, title, size, "#FFFFFF")
    ops += rect(58, y + 56 + title.count("\n") * size * 1.25, 132, 5, "#E73535", "GS85")
    if subtitle:
        ops += text(58, y + 104 + title.count("\n") * size * 1.25, subtitle, 22, "#F0F7FA")
    return ops


def bullet_panel(x, y, w, h, title, bullets, accent="#E73535"):
    ops = rect(x, PAGE_H - y - h, w, h, "#06192F", "GS75", "#CFE7EA")
    ops += text(x + 28, y + 45, title, 26, "#FFFFFF")
    yy = y + 90
    for b in bullets:
        ops += rect(x + 30, PAGE_H - yy + 4, 7, 7, accent, "GS85")
        ops += text(x + 50, yy, b, 16, "#F0F7FA")
        yy += 42
    return ops


def data_card(x, y, w, num, label, accent="#E73535"):
    ops = rect(x, PAGE_H - y - 88, w, 88, "#06192F", "GS65", "#CFE7EA")
    ops += text(x + w / 2, y + 38, num, 30, "#FFFFFF", "center")
    ops += rect(x + w / 2 - 22, PAGE_H - y - 60, 44, 4, accent, "GS85")
    ops += text(x + w / 2, y + 76, label, 15, "#F0F7FA", "center")
    return ops


def make_pdf():
    pdf = PDF()

    ops = title_ops(1, "三峡大坝的\n历史与现在", "党领导下的国家重大水利工程实践", 230, 56)
    ops += data_card(520, 500, 185, "2309米", "大坝全长")
    ops += data_card(730, 500, 170, "181米", "最大坝高")
    ops += data_card(930, 500, 190, "2250万kW", "装机容量")
    pdf.page(BG[0], ops)

    ops = title_ops(2, "一江安澜", "三峡工程建设的时代背景", 160, 48)
    ops += bullet_panel(56, 310, 520, 250, "为什么要建设三峡工程", [
        "长江干流全长约6300公里，是我国重要经济轴线",
        "中下游人口密集、产业集中，防洪安全关系全局",
        "承担防洪、发电、航运、水资源调度等综合任务",
        "根本出发点是保障人民生命财产安全",
    ])
    ops += data_card(650, 455, 160, "防洪", "首要任务")
    ops += data_card(830, 455, 160, "能源", "清洁电力", "#1ECDD1")
    ops += data_card(1010, 455, 160, "航运", "黄金水道", "#F6C85F")
    pdf.page(BG[1], ops)

    ops = title_ops(3, "百年构想", "从治水设想到国家决策", 160, 48)
    ops += bullet_panel(560, 150, 520, 360, "决策路径", [
        "长期酝酿：围绕长江治水与水能开发形成构想",
        "系统论证：持续开展勘测、规划与科学研究",
        "国家决策：1992年全国人大审议通过兴建决议",
        "正式开工：1994年工程进入全面实施阶段",
    ], "#1ECDD1")
    ops += rect(62, 96, 400, 62, "#06192F", "GS65", "#CFE7EA")
    ops += text(86, 516, "构想 → 论证 → 决策 → 实施", 22, "#1ECDD1")
    pdf.page(BG[2], ops)

    ops = title_ops(4, "攻坚克难", "三峡工程建设历程", 160, 48)
    ops += rect(62, 110, 1028, 132, "#06192F", "GS75", "#CFE7EA")
    years = [("1992", "批准建设"), ("1994", "正式开工"), ("1997", "大江截流"), ("2003", "发电通航"), ("2006", "主体完工"), ("2012", "主要完成")]
    for i, (yr, lab) in enumerate(years):
        x = 105 + i * 175
        ops += line(x, 495, x + 130, 495, "#CFE7EA", 2, "GS45")
        ops += rect(x - 8, PAGE_H - 503, 16, 16, "#E73535" if i in (0, 3, 5) else "#1ECDD1", "GS85")
        ops += text(x, 540, yr, 22, "#FFFFFF", "center")
        ops += text(x, 568, lab, 13, "#DDECF2", "center")
    ops += bullet_panel(690, 225, 360, 130, "这页重点表达", ["从国家决策、开工建设，到发电通航和主体完工的关键节点。"], "#E73535")
    pdf.page(BG[3], ops)

    ops = title_ops(5, "党建引领", "重大工程背后的组织力量", 160, 48)
    ops += bullet_panel(56, 315, 455, 220, "党建主线", [
        "把党的领导贯穿工程建设全过程",
        "把组织优势转化为建设效率和治理能力",
        "把党员担当落实到关键节点、急难任务",
    ])
    chain = [("党的领导", "统一部署"), ("组织动员", "基层堡垒"), ("一线攻坚", "冲锋在前"), ("工程保障", "协同推进")]
    for i, (a, b) in enumerate(chain):
        x = 560 + i * 145
        ops += data_card(x, 390, 120, a, b, "#E73535")
        if i < 3:
            ops += line(x + 125, 435, x + 142, 435, "#CFE7EA", 2, "GS65")
    ops += rect(560, 90, 535, 48, "#E73535", "GS85")
    ops += text(828, 532, "表达重点：党建是重大工程建设的组织保障体系", 18, "#FFFFFF", "center")
    pdf.page(BG[4], ops)

    ops = title_ops(6, "大国重器", "三峡大坝的工程规模", 160, 48)
    ops += bullet_panel(56, 305, 410, 205, "核心工程参数", [
        "坝轴线全长约2309米",
        "最大坝高约181米，正常蓄水位175米",
        "水库总库容约393亿立方米",
    ])
    ops += rect(630, 250, 470, 240, "#06192F", "GS75", "#CFE7EA")
    ops += text(655, 192, "国际著名大坝对比", 22, "#FFFFFF")
    ops += text(655, 222, "装机容量 / 坝高 / 坝长", 14, "#DDECF2")
    dams = [("三峡", 22500, 181, 2309, "#E73535"), ("伊泰普", 14000, 196, 7235, "#1ECDD1"), ("大古力", 6809, 168, 1592, "#F6C85F"), ("胡佛", 2080, 221, 379, "#9FB3C8")]
    base_y = 440
    for i, (name, cap, height, length, c) in enumerate(dams):
        x = 690 + i * 95
        ops += rect(x, PAGE_H - base_y, 20, 115 * cap / 22500, c, "GS85")
        ops += text(x + 10, 475, name, 12, "#FFFFFF", "center")
    ops += data_card(520, 500, 165, "393亿m³", "总库容", "#1ECDD1")
    ops += data_card(705, 500, 175, "221.5亿m³", "防洪库容")
    ops += data_card(900, 500, 180, "2250万kW", "总装机容量", "#F6C85F")
    pdf.page(BG[5], ops)

    ops = title_ops(7, "综合效益", "防洪、发电、航运与水资源调度", 155, 44)
    items = [("防洪", "荆江河段约10年一遇 → 约100年一遇"), ("发电", "多年平均年发电量约882亿千瓦时"), ("航运", "双线五级船闸支撑万吨级船队"), ("调度", "汛期削峰、枯水补水，服务流域配置")]
    for i, (a, b) in enumerate(items):
        x = 64 + (i % 2) * 380
        y = 340 + (i // 2) * 92
        ops += rect(x, PAGE_H - y - 70, 340, 70, "#06192F", "GS65", "#CFE7EA")
        ops += text(x + 24, y + 34, a, 22, "#FFFFFF")
        ops += text(x + 92, y + 34, b, 15, "#DDECF2")
    ops += bullet_panel(815, 320, 275, 185, "能力具体化", [
        "防洪：约10年一遇提升至约100年一遇",
        "发电：882亿千瓦时/年，多年平均",
    ], "#E73535")
    pdf.page(BG[6], ops)

    ops = title_ops(8, "今日三峡", "现代化运行与长江大保护", 160, 48)
    ops += rect(70, 180, 1005, 155, "#06192F", "GS75", "#CFE7EA")
    ops += data_card(105, 350, 270, "1.8万亿kWh+", "累计发电量突破")
    ops += data_card(425, 350, 270, "22亿吨+", "累计货运量超过", "#1ECDD1")
    ops += data_card(745, 350, 270, "智能调度", "数字化精细化运行", "#F6C85F")
    ops += text(120, 520, "能源安全　航运效率　水资源调度　长江大保护", 21, "#FFFFFF")
    pdf.page(BG[7], ops)

    ops = title_ops(9, "辩证看待", "成就、挑战与长期治理", 160, 48)
    ops += bullet_panel(56, 315, 390, 230, "怎么看待三峡工程", [
        "既看防洪、发电、航运等综合效益",
        "也看生态、泥沙、库区发展的长期课题",
        "关键在持续监测、动态优化、系统治理",
    ], "#1ECDD1")
    for i, (a, b, c) in enumerate([("生态监测", "水质、生境、岸线", "#1ECDD1"), ("泥沙调度", "来沙变化、库区淤积", "#F6C85F"), ("库区发展", "移民后扶、产业重建", "#E73535")]):
        ops += data_card(520 + i * 185, 370, 160, a, b, c)
    ops += rect(545, 85, 455, 46, "#E73535", "GS85")
    ops += text(772, 536, "长期治理闭环：监测 → 评估 → 优化 → 再监测", 17, "#FFFFFF", "center")
    pdf.page(BG[8], ops)

    ops = title_ops(10, "从一座大坝，\n看见中国式现代化的治理能力", "谢谢各位领导", 185, 42)
    for i, (a, b) in enumerate([("战略", "国家重大工程"), ("技术", "工程装备能力"), ("组织", "集中力量办大事"), ("人民", "安全与发展")]):
        ops += data_card(88 + i * 255, 480, 180, a, b, "#E73535" if i == 2 else "#1ECDD1")
    pdf.page(BG[9], ops)

    pdf.save(ROOT / OUT)
    print(ROOT / OUT)


if __name__ == "__main__":
    make_pdf()
