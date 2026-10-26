"""Draw the as-built diagrams for Chapter 4 as SVG, in the style of the Chapter 3 figures.

    python docs/diagrams/make_diagrams.py          (writes docs/diagrams/*.svg)
    node frontend/scripts/render_diagrams.mjs      (turns them into PNG for Word)

Grayscale and serif type like Figures 3.2-3.5. A dashed outline marks what the built system
adds to the Chapter 3 design. Standard library only.
"""
from __future__ import annotations

import math
from html import escape
from pathlib import Path

HERE = Path(__file__).resolve().parent
FONT = "'Times New Roman', Times, serif"
INK = "#1a1a1a"
GREY = "#5a5a5a"
FILL = "#ececec"
FILL_DARK = "#dcdcdc"
BAND = "#f6f6f6"
DASH = "14 9"


class Svg:
    def __init__(self, width: int, height: int):
        self.width, self.height, self.items = width, height, []

    # ------------------------------------------------------------ primitives
    def rect(self, x, y, w, h, *, fill="#fff", stroke=INK, sw=3.0, rx=0, dash=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.items.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" '
                          f'stroke="{stroke}" stroke-width="{sw}"{d}/>')

    def ellipse(self, cx, cy, rx, ry, *, fill="#fff", sw=3.5, dash=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.items.append(f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="{fill}" stroke="{INK}" '
                          f'stroke-width="{sw}"{d}/>')

    def text(self, x, y, lines, *, size=30, weight="normal", style="normal", anchor="middle", fill=INK,
             lh=1.22, bg=False, rotate=0.0):
        """Draw `lines` (a string or a list) as a block whose vertical centre is y."""
        lines = [lines] if isinstance(lines, str) else lines
        step = size * lh
        top = y - step * (len(lines) - 1) / 2
        out = []
        if bg:
            width = max(len(s) for s in lines) * size * 0.47 + 14
            left = {"middle": x - width / 2, "start": x - 7, "end": x - width + 7}[anchor]
            out.append(f'<rect x="{left:.1f}" y="{top - size * 0.72:.1f}" width="{width:.1f}" '
                       f'height="{step * len(lines) + size * 0.1:.1f}" fill="#fff"/>')
        for i, line in enumerate(lines):
            out.append(f'<text x="{x}" y="{top + i * step + size * 0.34:.1f}" font-family="{FONT}" '
                       f'font-size="{size}" font-weight="{weight}" font-style="{style}" fill="{fill}" '
                       f'text-anchor="{anchor}" style="white-space:pre">{escape(line)}</text>')
        group = "".join(out)
        if rotate:
            group = f'<g transform="rotate({rotate:.2f} {x} {y})">{group}</g>'
        self.items.append(group)

    def path(self, d, *, start=None, end="arrow", dash=None, sw=3.0, color=INK):
        attrs = f' stroke-dasharray="{dash}"' if dash else ""
        if end:
            attrs += f' marker-end="url(#{end})"'
        if start:
            attrs += f' marker-start="url(#{start})"'
        self.items.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{sw}"{attrs}/>')

    def line(self, points, **kw):
        self.path("M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in points), **kw)

    def vline_hops(self, x, y1, y2, hops, **kw):
        """A vertical line from y1 down to y2 that hops over the lines it crosses at `hops`."""
        d = f"M {x} {y1}"
        for h in sorted(hops):
            d += f" L {x} {h - 11} A 11 11 0 0 1 {x} {h + 11}"
        self.path(d + f" L {x} {y2}", **kw)

    def save(self, name: str) -> None:
        defs = (
            '<defs>'
            '<marker id="arrow" viewBox="0 0 10 10" refX="9.5" refY="5" markerWidth="20" markerHeight="20" '
            'markerUnits="userSpaceOnUse" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#1a1a1a"/></marker>'
            '<marker id="grey" viewBox="0 0 10 10" refX="9.5" refY="5" markerWidth="20" markerHeight="20" '
            'markerUnits="userSpaceOnUse" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#5a5a5a"/></marker>'
            '<marker id="hollow" viewBox="0 0 12 12" refX="11.5" refY="6" markerWidth="30" markerHeight="30" '
            'markerUnits="userSpaceOnUse" orient="auto"><path d="M0,0 L12,6 L0,12 z" fill="#fff" stroke="#1a1a1a" '
            'stroke-width="1.2"/></marker>'
            '</defs>')
        body = "\n".join(self.items)
        (HERE / name).write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" height="{self.height}" '
            f'viewBox="0 0 {self.width} {self.height}">{defs}'
            f'<rect width="100%" height="100%" fill="#fff"/>\n{body}\n</svg>\n', encoding="utf-8")

    # ------------------------------------------------------------ DFD shapes
    def process(self, cx, cy, number, name, rx=175, ry=112, added=False):
        self.ellipse(cx, cy, rx, ry, dash=DASH if added else None)
        self.text(cx, cy - 46, number, size=34, weight="bold")
        self.text(cx, cy + 22, name, size=32)

    def store(self, x, y, w, ident, name, h=92, added=False):
        self.rect(x, y, w, h, fill=FILL, dash=DASH if added else None)
        self.line([(x + 105, y), (x + 105, y + h)], end=None)
        self.text(x + 52, y + h / 2, ident, size=32, weight="bold")
        self.text(x + 105 + (w - 105) / 2, y + h / 2, name, size=31)

    def entity(self, x, y, w, h, name):
        self.rect(x, y, w, h, fill=FILL_DARK)
        self.text(x + w / 2, y + h / 2, name, size=31)


def on_ellipse(cx, cy, rx, ry, tx, ty):
    dx, dy = tx - cx, ty - cy
    t = 1 / math.sqrt((dx / rx) ** 2 + (dy / ry) ** 2)
    return cx + dx * t, cy + dy * t


def ellipse_y(cx, cy, rx, ry, x, lower=True):
    off = ry * math.sqrt(max(0.0, 1 - ((x - cx) / rx) ** 2))
    return cy + off if lower else cy - off


def ellipse_x(cx, cy, rx, ry, y, right=True):
    off = rx * math.sqrt(max(0.0, 1 - ((y - cy) / ry) ** 2))
    return cx + off if right else cx - off


# =================================================================== Figure: as-built DFD
def dfd() -> None:
    s = Svg(2100, 1530)
    rx, ry = 175, 112
    P = {1: (680, 200), 2: (1390, 200), 3: (1390, 650), 4: (680, 650), 5: (680, 1100), 6: (1390, 1100)}
    P7 = (1810, 850, 150, 95)

    # flows first, so shapes sit on top of the line ends
    # Network -> 1.0
    s.line([(392, 200), (ellipse_x(*P[1], rx, ry, 200, right=False) - 2, 200)])
    s.text(420, 322, ["counters, statistics,", "flows, up/down events"], size=27, fill=GREY)
    # 1.0 -> 2.0
    s.line([(ellipse_x(*P[1], rx, ry, 200) + 2, 200), (ellipse_x(*P[2], rx, ry, 200, right=False) - 2, 200)])
    s.text(1035, 146, ["device and interface", "metrics, flow records"], size=27, fill=GREY)
    # 2.0 -> 3.0
    s.line([(1390, 314), (1390, 536)])
    s.text(1408, 412, ["validated,", "normalised data"], size=27, fill=GREY, anchor="start")
    # 3.0 -> D2 (state history)
    a = on_ellipse(*P[3], rx, ry, 1250, 440)
    s.line([a, (1253, 446)])
    s.text(1290, 494, "state history", size=27, fill=GREY, bg=True)
    # D2 -> 4.0 (historical series)
    b = on_ellipse(*P[4], rx, ry, 850, 454)
    s.line([(850, 454), (b[0] + 3, b[1] - 3)])
    s.text(788, 402, ["historical series", "(reloaded at start-up)"], size=27, fill=GREY, anchor="end")
    # 3.0 <-> D1
    s.line([(ellipse_x(*P[3], rx, ry, 606) + 2, 606), (1638, 606)], start="arrow")
    s.text(1558, 538, "topology / status changes", size=27, fill=GREY, anchor="start")
    # 3.0 -> 4.0
    s.line([(ellipse_x(*P[3], rx, ry, 650, right=False) - 2, 650), (ellipse_x(*P[4], rx, ry, 650) + 2, 650)])
    s.text(872, 622, "new state event", size=27, fill=GREY, anchor="start")
    # 4.0 -> D3
    s.line([(ellipse_x(*P[4], rx, ry, 650, right=False) - 2, 650), (382, 650)])
    s.text(450, 563, ["forecasts,", "warnings"], size=27, fill=GREY)
    # 4.0 -> 5.0 (added): new alerts, fixes to test
    s.line([(680, 763), (680, 986)], dash=DASH)
    s.text(698, 872, ["new alerts", "(fixes to test)"], size=27, fill=GREY, anchor="start")
    # 3.0 -> 5.0 (added): a copy of the model
    c, d = on_ellipse(*P[3], rx, ry, *P[5]), on_ellipse(*P[5], rx, ry, *P[3])
    s.line([c, d], dash=DASH)
    angle = math.degrees(math.atan2(c[1] - d[1], c[0] - d[0]))
    s.text(c[0] + 0.62 * (d[0] - c[0]), c[1] + 0.62 * (d[1] - c[1]), "copy of the model", size=27, fill=GREY,
           bg=True, rotate=angle)
    # D2 -> 6.0 (added): trend data, hopping over 3.0->4.0 and 3.0->5.0
    x = 1130
    crossing = c[1] + (c[0] - x) / (c[0] - d[0]) * (d[1] - c[1])
    s.vline_hops(x, 454, 1060, [650, crossing], end=None, dash=DASH)
    s.line([(x, 1060), (ellipse_x(*P[6], rx, ry, 1060, right=False) - 2, 1060)], dash=DASH)
    s.text(1146, 905, "trend data", size=27, fill=GREY, anchor="start")
    # D1 -> 6.0 (added)
    e = on_ellipse(*P[6], rx, ry, 1660, 654)
    s.line([(1660, 654), e], dash=DASH)
    s.text(1495, 845, ["topology,", "status"], size=27, fill=GREY, anchor="end")
    # D3 -> 6.0 (added), along the bottom
    s.line([(210, 694), (210, 1430), (1360, 1430), (1360, ellipse_y(*P[6], rx, ry, 1360) + 2)], dash=DASH)
    s.text(560, 1410, "predictions and alerts", size=27, fill=GREY)
    # 5.0 <-> D4 and 6.0 <-> D4 (added: runs are queued in D4)
    s.line([(740, ellipse_y(*P[5], rx, ry, 740) + 2), (740, 1296), (803, 1296)], start="arrow")
    s.line([(1252, 1296), (1290, 1296), (1290, ellipse_y(*P[6], rx, ry, 1290) + 2)], start="arrow", dash=DASH)
    s.text(1027, 1378, "queued runs and stored results", size=27, fill=GREY)
    # 6.0 <-> administrator
    f = on_ellipse(*P[6], rx, ry, 1650, 1245)
    s.line([f, (1648, 1245)], start="arrow")
    s.text(1600, 1326, ["requests /", "network state, alerts, results"], size=27, fill=GREY)
    # administrator -> 7.0 -> D1, D5 ; D5 <-> 6.0 (all added)
    s.line([(1962, 1245), (2035, 1245), (2035, 850), (1962, 850)], dash=DASH)
    s.text(2062, 1050, "imports, edits, accounts", size=27, fill=GREY, rotate=-90)
    s.line([(1810, 755), (1810, 654)], dash=DASH)
    s.text(1826, 704, ["devices, links,", "configuration"], size=26, fill=GREY, anchor="start")
    s.line([(1810, 945), (1810, 1008)], dash=DASH)
    s.text(1826, 978, "accounts, roles", size=26, fill=GREY, anchor="start")
    g = on_ellipse(*P[6], rx, ry, 1638, 1056)
    s.line([g, (1638, 1056)], start="arrow", dash=DASH)
    s.text(1572, 1118, "sign-in, roles", size=26, fill=GREY, anchor="start")

    # shapes
    s.entity(40, 145, 350, 110, ["Real Network", "(network emulator)"])
    s.entity(1650, 1190, 310, 110, ["Network", "Administrator"])
    s.process(*P[1], "1.0", ["Collect", "Monitoring Data"])
    s.process(*P[2], "2.0", ["Validate and", "Transform Data"])
    s.process(*P[3], "3.0", ["Update Digital", "Twin Model"])
    s.process(*P[4], "4.0", ["Generate", "Predictions"])
    s.process(*P[5], "5.0", ["Execute", "Simulation"])
    s.process(*P[6], "6.0", ["Render", "Dashboard"])
    s.ellipse(P7[0], P7[1], P7[2], P7[3], dash=DASH)
    s.text(P7[0], P7[1] - 40, "7.0", size=32, weight="bold")
    s.text(P7[0], P7[1] + 20, ["Manage Topology", "and Users"], size=30)
    s.store(805, 360, 445, "D2", ["Monitoring", "Records"])
    s.store(1640, 560, 320, "D1", ["Topology", "Store"])
    s.store(40, 600, 340, "D3", "Predictions")
    s.store(805, 1250, 445, "D4", ["Scenarios and", "Results"])
    s.store(1640, 1010, 320, "D5", "Users", added=True)
    s.text(1050, 1495, "Dashed = added in the as-built system.  Processes 3.0-5.0 run in the Digital Twin "
           "Engine; 6.0 is the REST API and dashboard; 7.0 is the admin site and topology import.",
           size=25, fill=GREY)
    s.save("dfd.svg")


# =================================================================== Figure: as-built ERD
def erd() -> None:
    s = Svg(2330, 1230)
    head, row = 64, 42

    def table(x, y, w, name, fields, added=False):
        h = head + len(fields) * row + 20
        s.rect(x, y, w, h, dash=DASH if added else None)
        s.rect(x, y, w, head, fill=FILL_DARK, dash=DASH if added else None)
        s.text(x + w / 2, y + head / 2, name, size=36, weight="bold")
        for i, (label, kind) in enumerate(fields):
            style = {"pk": ("bold", "normal", INK), "fk": ("normal", "italic", INK),
                     "": ("normal", "normal", INK), "extra": ("normal", "italic", GREY),
                     "extra_fk": ("normal", "italic", GREY)}[kind]
            s.text(x + 28, y + head + 30 + i * row, label, size=31, weight=style[0], style=style[1], fill=style[2],
                   anchor="start")
        return h

    def card(x, y, label):
        s.text(x, y, label, size=34, weight="bold")

    device = [("device_id (PK)", "pk"), ("name", ""), ("device_type", ""), ("ip_address", ""), ("location", ""),
              ("status", ""), ("configuration *", "extra")]
    link = [("link_id (PK)", "pk"), ("source_device_id (FK)", "fk"), ("dest_device_id (FK)", "fk"),
            ("capacity_mbps", ""), ("status", ""), ("routing_cost *", "extra")]
    scenario = [("scenario_id (PK)", "pk"), ("created_by (FK)", "fk"), ("scenario_name", ""), ("scenario_type", ""),
                ("parameters", ""), ("created_at", "")]
    record = [("record_id (PK)", "pk"), ("device_id (FK)", "fk"), ("link_id (FK)", "fk"), ("timestamp", ""),
              ("traffic_in / traffic_out", ""), ("utilisation_pct", ""), ("error_count", ""), ("cpu_util", ""),
              ("status *", "extra"), ("received_at *", "extra")]
    prediction = [("prediction_id (PK)", "pk"), ("link_id (FK)", "fk"), ("generated_at", ""), ("horizon_minutes", ""),
                  ("predicted_utilisation", ""), ("confidence_score", ""), ("is_warning", ""),
                  ("model_version *", "extra")]
    result = [("result_id (PK)", "pk"), ("scenario_id (FK)", "fk"), ("executed_at", ""),
              ("predicted_utilisation", ""), ("bottleneck_links", ""), ("result_summary", ""), ("status *", "extra"),
              ("run_by (FK) *", "extra_fk"), ("requested_at *", "extra")]
    user = [("id (PK)", "pk"), ("username", ""), ("password (Argon2 hash)", ""), ("is_active", ""),
            ("role: Senior or Junior", ""), ("last_login", "")]

    # relationships (drawn first)
    s.line([(530, 175), (660, 175)], end=None)
    s.text(595, 140, "connects", size=31, style="italic", fill=GREY)
    card(556, 205, "1")
    card(628, 205, "N")
    s.line([(215, 448), (215, 600)], end=None)
    s.text(245, 524, "is monitored by", size=31, style="italic", fill=GREY, anchor="start")
    card(190, 476, "1")
    card(190, 574, "N")
    s.line([(660, 330), (590, 330), (590, 660), (530, 660)], end=None)
    s.text(625, 495, "is monitored by", size=31, style="italic", fill=GREY, rotate=-90)
    card(633, 300, "1")
    card(560, 628, "N")
    s.line([(820, 406), (820, 600)], end=None)
    s.text(848, 503, "is forecast by", size=31, style="italic", fill=GREY, anchor="start")
    card(795, 436, "1")
    card(795, 574, "N")
    s.line([(1430, 406), (1430, 600)], end=None)
    s.text(1458, 503, "produces", size=31, style="italic", fill=GREY, anchor="start")
    card(1405, 436, "1")
    card(1405, 574, "N")
    s.line([(530, 1010), (658, 1010)], dash="10 8", color=GREY, end="grey")
    s.text(594, 975, "trains", size=31, style="italic", fill=GREY)
    s.line([(1880, 372), (1750, 372)], end=None, dash=DASH)
    s.text(1815, 338, "creates", size=31, style="italic", fill=GREY)
    card(1858, 402, "1")
    card(1772, 402, "N")
    s.line([(1880, 640), (1750, 640)], end=None, dash=DASH)
    s.text(1815, 606, "runs", size=31, style="italic", fill=GREY)
    card(1858, 670, "1")
    card(1772, 670, "N")

    table(60, 70, 470, "NetworkDevice", device)
    table(660, 70, 490, "NetworkLink", link)
    table(1280, 70, 470, "SimulationScenario", scenario)
    table(60, 600, 470, "MonitoringRecord", record)
    table(660, 600, 490, "Prediction", prediction)
    table(1280, 600, 470, "SimulationResult", result)
    table(1880, 300, 400, "User", user, added=True)
    s.text(1165, 1160, "PK = primary key     FK = foreign key     1 : N = one-to-many relationship     "
           "- - - arrow = data dependency", size=30, fill=GREY)
    s.text(1165, 1205, "* = field added in the as-built system (Table 3.1 lists principal fields only)     "
           "dashed = Django's user table and its two relationships", size=30, fill=GREY)
    s.save("erd.svg")


# =================================================================== Figure: as-built use cases
def use_cases() -> None:
    s = Svg(2120, 1800)
    cx, rx, ry = 1060, 345, 62
    ucs = {
        "auth": (225, ["Authenticate", "(log in)"], False),
        "uc1": (395, ["Monitor Network", "Topology in Real Time"], False),
        "uc1x": (560, "View Device / Link Detail", False),
        "uc2": (735, ["Receive Predictive", "Congestion Alert"], False),
        "uc2x": (900, ["View Trend and", "Forecast Chart"], False),
        "uc4": (1070, ["Analyse Historical Trends", "and Plan Capacity"], True),
        "uc3": (1245, ["Create and Run", "Simulation Scenario"], False),
        "uc3x": (1410, ["Compare Scenario Result", "with Current State"], False),
        "manage": (1580, ["Manage Topology", "and User Accounts"], True),
    }

    def left(key):
        return cx - rx, ucs[key][0]

    def right(key):
        return cx + rx, ucs[key][0]

    def actor(x, y, name):
        s.items.append(f'<circle cx="{x}" cy="{y - 112}" r="38" fill="#fff" stroke="{INK}" stroke-width="3.5"/>')
        s.line([(x, y - 74), (x, y + 18)], end=None, sw=3.5)
        s.line([(x - 66, y - 40), (x + 66, y - 40)], end=None, sw=3.5)
        s.line([(x - 56, y + 100), (x, y + 18), (x + 56, y + 100)], end=None, sw=3.5)
        s.text(x, y + 168, name, size=34)

    s.rect(560, 60, 1000, 1660, fill="#fbfbfb")
    s.text(cx, 118, ["Digital Twin-Based Network Monitoring", "and Optimization System"], size=34, weight="bold")

    junior, senior, source = (210, 600), (210, 1380), (1910, 600)
    jhand, shand, src_hand = (300, 580), (300, 1360), (1820, 580)
    for key in ("auth", "uc1", "uc2", "uc4"):
        s.line([jhand, left(key)], end=None)
    for key in ("uc3", "uc3x", "manage"):
        s.line([shand, left(key)], end=None)
    for key in ("uc1", "uc2"):
        s.line([src_hand, right(key)], end=None)
    # Senior Administrator specialises Junior Administrator: it can do everything the junior can
    s.line([(senior[0], senior[1] - 152), (junior[0], junior[1] + 222)], end="hollow")
    s.text(232, 1003, ["can also do", "everything a", "Junior can"], size=26, fill=GREY, style="italic", anchor="start")

    for key, (y, label, added) in ucs.items():
        s.ellipse(cx, y, rx, ry, dash=DASH if added else None)
        s.text(cx, y, label, size=32)

    def relation(upper, lower, kind):
        y1, y2 = ucs[upper][0] + ry, ucs[lower][0] - ry
        s.line([(cx, y2), (cx, y1 + 2)], end="grey", color=GREY, dash="9 6", sw=2.8)
        s.text(cx + 16, (y1 + y2) / 2, f"«{kind}»", size=29, style="italic", fill=GREY, anchor="start", bg=True)

    relation("auth", "uc1", "include")
    relation("uc1", "uc1x", "extend")
    relation("uc2", "uc2x", "extend")
    relation("uc3", "uc3x", "extend")

    actor(*junior, ["Junior", "Administrator"])
    actor(*senior, ["Senior", "Administrator"])
    actor(*source, ["Monitoring", "Data Source"])
    s.text(1910, 862, ["(network emulator", "or SNMP devices)"], size=26, fill=GREY)
    s.text(cx, 1770, "Dashed = added in the as-built system. Junior Administrators can look at everything "
           "but change nothing.", size=26, fill=GREY)
    s.save("use_cases.svg")


# =================================================================== Figure: as-built architecture
def architecture() -> None:
    s = Svg(2000, 2010)

    def band(y, h, title, note=None, x=70, w=1860):
        s.rect(x, y, w, h, fill=BAND, stroke="#555", sw=4)
        s.text(x + 48, y + 40, title, size=36, weight="bold", fill="#444", anchor="start")
        if note:
            s.text(x + w - 30, y + 40, note, size=32, style="italic", fill=GREY, anchor="end")

    def box(x, y, w, h, lines, fill="#fff", added=False, size=32, rx=14):
        s.rect(x, y, w, h, fill=fill, rx=rx, dash=DASH if added else None)
        s.text(x + w / 2, y + h / 2, lines, size=size)

    band(60, 400, "PRESENTATION LAYER", "Next.js Administrator Dashboard (web browser)")
    box(150, 130, 500, 110, ["Overview and", "Topology Map"])
    box(750, 130, 500, 110, ["Alerts and", "Predictions"])
    box(1350, 130, 500, 110, ["Simulation", "Console"])
    box(150, 290, 500, 110, ["Device / Link", "Detail"])
    box(750, 290, 500, 110, ["Trends and", "Capacity Planning"], added=True)
    box(1350, 290, 500, 110, ["System", "Status"], added=True)

    s.line([(710, 600), (710, 464)])
    s.line([(1290, 464), (1290, 600)])
    s.text(1000, 532, "REST API: JSON over HTTPS", size=31, fill=GREY)
    box(480, 600, 1040, 92, "Caddy web server: HTTPS, security headers, static files, proxy", added=True,
        size=30, fill=FILL)
    s.line([(1000, 692), (1000, 822)])
    s.text(1020, 726, "HTTP on 127.0.0.1 (/api, /admin)", size=29, fill=GREY, anchor="start")

    band(760, 640, "APPLICATION AND DIGITAL TWIN LAYER")
    box(150, 824, 1700, 104, ["Django REST Backend (Waitress)  |  Authentication · Roles · API Endpoints · "
                              "Input Validation · Audit Log"], size=31)
    s.rect(130, 1000, 1740, 360, fill="none", dash="16 10", sw=3.5)
    s.rect(760, 978, 480, 46, fill=BAND, stroke="none", sw=0)
    s.text(1000, 1000, "Digital Twin Engine (run_twin)", size=34, weight="bold")
    box(190, 1060, 500, 250, ["Network Model", "(NetworkX graph:", "nodes, edges,", "state, demands)"], fill=FILL)
    box(750, 1060, 500, 250, ["Prediction Engine", "(Random Forest", "forecasts and", "warning classifier)"],
        fill=FILL)
    box(1310, 1060, 500, 155, ["Simulation Engine", "(scenario registry)"], fill=FILL)
    box(1310, 1235, 500, 75, "Recommendations", fill=FILL, added=True, size=31)

    band(1480, 330, "DATA COLLECTION AND INTEGRATION LAYER", w=1170)
    box(130, 1570, 500, 200, ["Network Adapter", "(adapter registry:", "telemetry feed)"])
    box(690, 1570, 480, 200, ["Preprocessing", "Module (validate,", "clean, normalise)"])
    s.line([(632, 1670), (688, 1670)])
    s.line([(930, 1478), (930, 1402)])
    s.text(950, 1440, "validated state updates and up/down events", size=29, fill=GREY, anchor="start")

    box(1310, 1500, 620, 190, ["PostgreSQL Database", "(Neon or local fallback: topology ·", "monitoring · "
                               "predictions · simulations · users)"], fill=FILL, size=29)
    s.line([(1620, 1404), (1620, 1498)], start="arrow")
    s.text(1640, 1452, "read / write", size=29, fill=GREY, anchor="start")

    s.line([(380, 1900), (380, 1812)])
    s.text(400, 1856, "read-only telemetry: counters, flows, events", size=29, fill=GREY, anchor="start")
    s.rect(70, 1900, 1170, 92, fill=FILL_DARK, sw=4)
    s.text(655, 1946, "REAL NETWORK: network emulator (routers · switches · links)", size=30)
    box(1310, 1760, 620, 232, ["Supervisor", "starts and watches the emulator,", "engine, API and Caddy;",
                               "restarts any that stop"], added=True, size=29, rx=0)
    s.save("architecture.svg")


if __name__ == "__main__":
    dfd()
    erd()
    use_cases()
    architecture()
    print("wrote", ", ".join(sorted(p.name for p in HERE.glob("*.svg"))))
