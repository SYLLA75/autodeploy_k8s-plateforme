#!/usr/bin/env python3
"""
Architecture de train-ticket, reprise du schéma officiel, avec les composants
ajoutés par ce travail.

La grammaire visuelle est celle du schéma amont : hexagones pour les services,
barre verte pour la passerelle, panneaux latéraux pour les fonctions
transverses, magasins en bas. Seuls les libellés changent entre les deux
langues.

    python3 make_architecture.py  ->  architecture-fr.svg / architecture-en.svg
"""
import os

W, H = 2040, 1300

ORANGE, ORANGE_S = "#F2A73B", "#B77B1A"
GREEN, GREEN_S = "#3EA246", "#2E7D33"
YEL, YEL_S = "#FCF6B8", "#33322E"
WHT, WHT_S = "#FFFFFF", "#33322E"
BLUE, BLUE_S = "#C7DCF2", "#7FA8D4"
PURP, PURP_S = "#E9D5F3", "#B98FD1"
DB, DB_S = "#C8E6C9", "#7FBE86"
ADD, ADD_S = "#D8ECF5", "#2E7E9E"      # ajouté par ce travail
ARR = "#4A4A4A"
MQ = "#C06A00"

T = {
"fr": {
  "front": "Front End",
  "gw": "Gateway",
  "left1": "Service Discovery\nAnd Register\n(NACOS)",
  "left2": "Flow Control\n(sentinel)",
  "right1": "Métriques\n(Prometheus\nnode-exporter\nkube-state-metrics)",
  "right2": "Traces\n(OpenTelemetry\nagent + Collector)",
  "right3": "Stockage traces\n(Jaeger)",
  "lg": "Locust\n(charge)",
  "minio": "MinIO\n(archive)",
  "leg1": "train-ticket",
  "leg2": "ajouté",
  "leg3": "file de messages",
  "cap": "Figure 1 — Architecture de train-ticket et composants ajoutés pour l'observabilité.",
},
"en": {
  "front": "Front End",
  "gw": "Gateway",
  "left1": "Service Discovery\nAnd Register\n(NACOS)",
  "left2": "Flow Control\n(sentinel)",
  "right1": "Metrics\n(Prometheus\nnode-exporter\nkube-state-metrics)",
  "right2": "Traces\n(OpenTelemetry\nagent + Collector)",
  "right3": "Trace store\n(Jaeger)",
  "lg": "Locust\n(workload)",
  "minio": "MinIO\n(archive)",
  "leg1": "train-ticket",
  "leg2": "added",
  "leg3": "message queue",
  "cap": "Figure 1 — Train-ticket architecture and components added for observability.",
},
}

# nom, x, y, largeur, jaune ?
HEX = [
    ("auth",            268, 258, 120, 1), ("verificati\non-code", 398, 258, 120, 0),
    ("ticket-\noffice",  540, 258, 120, 1), ("avatar",           688, 258, 120, 0),
    ("news",             856, 258, 120, 0),
    ("payment",         1226, 258, 124, 1), ("inside-\npayment", 1368, 258, 128, 0),
    ("notificati\non",  1520, 258, 124, 1), ("delivery",         1670, 258, 120, 1),

    ("wait-\norder",     958, 362, 120, 1), ("preserve\n/other",  1098, 362, 128, 0),
    ("rebook",          1240, 362, 114, 0), ("execute",          1452, 362, 122, 0),
    ("cancel",          1610, 362, 114, 0),

    ("user",             226, 478, 114, 1), ("food",              344, 478, 114, 1),
    ("security",         462, 478, 122, 1), ("consign",           588, 478, 114, 1),
    ("contacts",         702, 478, 122, 1), ("assuran\nce",       818, 478, 114, 1),
    ("travel/2",        1118, 478, 114, 1), ("seat",             1318, 478, 114, 0),
    ("order/ot\nher",   1456, 478, 122, 1),

    ("station-\nfood",   298, 576, 114, 1), ("train-\nfood",      424, 576, 108, 1),
    ("consign\n-price",  592, 576, 114, 1), ("basic",             900, 576, 114, 0),
    ("voucher",         1596, 576, 114, 1),

    ("food-\ndelivery",  298, 700, 114, 1),
    ("price",            626, 700, 114, 1), ("route",             756, 700, 108, 1),
    ("station",          908, 700, 122, 1), ("train",            1036, 700, 114, 1),
    ("config",          1318, 700, 114, 1),

    ("admin-\nuser",     226, 822, 114, 0), ("admin-\nroute",     836, 822, 114, 0),
    ("admin-\ntravel",  1116, 822, 114, 0), ("admin-\norder",    1456, 822, 114, 0),

    ("route-\nplan",     910, 934, 114, 0), ("travel-\nplan",    1196, 934, 114, 0),
    ("admin-\nbasic-\ninfo", 1026, 1030, 114, 0),
]

# flèches principales du schéma amont : (x1,y1,x2,y2)
ARROWS = [
    (1016, 92, 1016, 138),                      # front end -> gateway
    (322, 192, 322, 258), (1582, 192, 1582, 258),
    (185, 470, 185, 300), (185, 300, 262, 300), # gateway -> auth (retour gauche)
    (388, 292, 394, 292),                       # auth -> verification-code
    (1364, 292, 1354, 292),                     # inside-payment -> payment
    (1516, 292, 1500, 292),                     # notification <- inside-payment
    (1666, 292, 1648, 292),                     # delivery -> notification
    (1288, 358, 1288, 320),                     # rebook -> payment
    (1054, 400, 1054, 470),                     # wait-order -> ...
    (1162, 400, 1162, 470),                     # preserve/other -> travel
    (283, 470, 283, 440), (283, 440, 1560, 440),
    (876, 512, 906, 560),                       # contacts -> basic
    (957, 612, 957, 694),                       # basic -> station
    (957, 612, 683, 694), (957, 612, 810, 694), (957, 612, 1093, 694),
    (1175, 512, 1175, 694),                     # travel -> train
    (1232, 512, 1314, 512),                     # travel -> seat
    (1432, 512, 1452, 512),                     # seat -> order
    (1375, 512, 1375, 694),                     # seat -> config
    (401, 512, 355, 570), (401, 512, 478, 570),
    (355, 694, 355, 640),                       # food-delivery -> station-food
    (283, 816, 283, 512),                       # admin-user -> user
    (645, 512, 645, 570),                       # consign -> consign-price
    (893, 816, 893, 738), (1173, 816, 1173, 738), (1513, 816, 1513, 738),
    (1653, 610, 1653, 512),                     # voucher -> order
    (1667, 400, 1667, 470), (1513, 400, 1513, 470),
]


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def hexagon(x, y, w, h, fill, stroke, sw=1.6):
    p = f"{x+w*0.16},{y} {x+w*0.84},{y} {x+w},{y+h/2} {x+w*0.84},{y+h} {x+w*0.16},{y+h} {x},{y+h/2}"
    return f'<polygon points="{p}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>\n'


def label(cx, cy, text, size=13, fill="#1a1a1a", weight="normal"):
    lines = text.split("\n")
    y0 = cy - (len(lines) - 1) * size * 0.62
    out = ""
    for i, ln in enumerate(lines):
        out += (f'<text x="{cx}" y="{y0 + i*size*1.24 + size*0.35}" font-size="{size}" fill="{fill}" '
                f'font-weight="{weight}" text-anchor="middle" '
                f'font-family="Helvetica, Arial, sans-serif">{esc(ln)}</text>\n')
    return out


def rect(x, y, w, h, fill, stroke, rx=3, sw=1.6, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{sw}"{d}/>\n')


def line(x1, y1, x2, y2, col=ARR, w=1.3, marker="arr", dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    m = f' marker-end="url(#{marker})"' if marker else ""
    return f'<path d="M {x1} {y1} L {x2} {y2}" fill="none" stroke="{col}" stroke-width="{w}"{m}{d}/>\n'


def cylinder(x, y, w, h, fill, stroke):
    ry = h * 0.13
    return (f'<path d="M {x} {y+ry} a {w/2} {ry} 0 0 1 {w} 0 v {h-2*ry} a {w/2} {ry} 0 0 1 {-w} 0 z" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="1.6"/>\n'
            f'<path d="M {x} {y+ry} a {w/2} {ry} 0 0 0 {w} 0" fill="none" stroke="{stroke}" stroke-width="1.6"/>\n')


def build(L):
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">\n<defs>\n']
    for n, c in (("arr", ARR), ("arrmq", MQ), ("arradd", ADD_S)):
        s.append(f'<marker id="{n}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
                 f'orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>\n')
    s.append(f'</defs>\n<rect width="{W}" height="{H}" fill="#ffffff"/>\n')

    # ---- Front End et générateur de charge --------------------------------
    s.append(rect(866, 32, 300, 60, ORANGE, ORANGE_S))
    s.append(label(1016, 62, L["front"], 17, "#1a1a1a", "bold"))

    s.append(rect(560, 32, 200, 60, ADD, ADD_S))
    s.append(label(660, 62, L["lg"], 14, "#123", "bold"))
    s.append(line(660, 92, 660, 138, ADD_S, 1.8, "arradd"))

    # ---- Gateway ----------------------------------------------------------
    s.append(rect(178, 138, 1680, 54, GREEN, GREEN_S))
    s.append(label(1018, 165, L["gw"], 17, "#ffffff", "bold"))

    # ---- panneaux latéraux ------------------------------------------------
    s.append(rect(22, 310, 148, 800, BLUE, BLUE_S, rx=4))
    s.append(label(96, 470, L["left1"], 14, "#123", "bold"))
    s.append(label(96, 760, L["left2"], 14, "#123", "bold"))

    s.append(rect(1866, 310, 152, 800, PURP, PURP_S, rx=4))
    s.append(label(1942, 440, L["right1"], 13, "#123", "bold"))
    s.append(label(1942, 690, L["right2"], 13, "#123", "bold"))
    s.append(label(1942, 900, L["right3"], 13, "#123", "bold"))

    # ---- flèches du schéma amont -----------------------------------------
    for (x1, y1, x2, y2) in ARROWS:
        s.append(line(x1, y1, x2, y2))

    # ---- services ---------------------------------------------------------
    for (name, x, y, w, yel) in HEX:
        h = 68
        s.append(hexagon(x, y, w, h, YEL if yel else WHT, YEL_S if yel else WHT_S))
        s.append(label(x + w / 2, y + h / 2, name, 13))

    # ---- magasins ---------------------------------------------------------
    s.append(cylinder(614, 1150, 280, 78, DB, DB_S))
    s.append(label(754, 1192, "mysql", 16))

    s.append(rect(1264, 1150, 232, 78, DB, DB_S, rx=6))
    s.append(label(1380, 1176, "rabbitmq", 16, "#1a1a1a", "bold"))
    s.append(label(1380, 1204, "food_delivery  ·  email", 11.5, "#3a3a3a"))

    s.append(rect(1596, 1150, 232, 78, ADD, ADD_S, rx=6))
    s.append(label(1712, 1189, L["minio"], 14, "#123", "bold"))
    s.append(line(1500, 1189, 1592, 1189, ADD_S, 1.8, "arradd", dash="6 4"))

    # ---- les deux files, en évidence --------------------------------------
    s.append(line(401, 546, 401, 1120, MQ, 2.2, None))
    s.append(line(401, 1120, 1258, 1120, MQ, 2.2, None))
    s.append(line(1258, 1120, 1330, 1146, MQ, 2.2, "arrmq"))
    s.append(label(700, 1112, "food_delivery", 12, MQ, "bold"))

    s.append(line(1450, 1146, 1730, 660, MQ, 2.2, "arrmq"))
    s.append(line(1582, 326, 1582, 292, MQ, 2.2, "arrmq"))
    s.append(line(1730, 660, 1730, 330, MQ, 2.2, None))
    s.append(line(1730, 330, 1648, 300, MQ, 2.2, None))
    s.append(label(1800, 620, "email", 12, MQ, "bold"))

    # ---- légende ----------------------------------------------------------
    ly = 1262
    s.append(hexagon(40, ly - 18, 46, 26, YEL, YEL_S, 1.3))
    s.append(f'<text x="96" y="{ly}" font-size="13" fill="#333" font-family="Helvetica, Arial, sans-serif">{esc(L["leg1"])}</text>\n')
    s.append(rect(240, ly - 18, 46, 26, ADD, ADD_S, rx=3, sw=1.3))
    s.append(f'<text x="296" y="{ly}" font-size="13" fill="#333" font-family="Helvetica, Arial, sans-serif">{esc(L["leg2"])}</text>\n')
    s.append(line(420, ly - 5, 466, ly - 5, MQ, 2.2, "arrmq"))
    s.append(f'<text x="476" y="{ly}" font-size="13" fill="#333" font-family="Helvetica, Arial, sans-serif">{esc(L["leg3"])}</text>\n')

    s.append(f'<text x="1080" y="{ly}" font-size="13" fill="#444" font-style="italic" '
             f'font-family="Helvetica, Arial, sans-serif">{esc(L["cap"])}</text>\n')
    s.append('</svg>\n')
    return "".join(s)


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    for lang in ("fr", "en"):
        p = os.path.join(here, f"architecture-{lang}.svg")
        open(p, "w", encoding="utf-8").write(build(T[lang]))
        print("écrit :", p)
