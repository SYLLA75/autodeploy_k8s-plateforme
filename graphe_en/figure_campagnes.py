"""
One figure for a report: the queue backlog, minute by minute, for the
reference and the four fault campaigns, injections shaded.

    ./.venv/bin/python figure_campagnes.py ../campagnes figure.png [name:title ...]

Reads campagnes/<name>/lecture.txt (queue table) and campagne.yaml (deroule:
injection / retrait instants). Without arguments, draws the campaigns listed
in CAMPAGNES; pass name:title pairs to draw others. matplotlib comes with the
venv that run.py installs.
"""
import re, sys
from datetime import datetime, timezone
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

root = Path(sys.argv[1]); out = sys.argv[2]
CAMPAGNES = [tuple(a.split(":", 1)) for a in sys.argv[3:]] or [("saine-08", "référence saine (10 / 25 / 20 voyageurs)"),
             ("charge-03", "charge : 25 → 35 voyageurs"),
             ("blocage-02", "blocage : une réplique sur trois gelée"),
             ("lenteur-01", "lenteur : +75 ms par échange avec la base"),
             ("hote-01", "hôte : un voisin sature la machine d'une réplique")]

def queue_rows(name):
    rows = []; inq = False
    for line in (root / name / "lecture.txt").read_text().splitlines():
        if line.startswith("queue:"): inq = True; continue
        if inq and not line.strip(): break
        if inq and re.match(r"\s*\d+\s+\d\d:\d\d:\d\d", line):
            p = line.split(); rows.append((p[1][:5], float(p[2])))
    return rows

def injections(name):
    text = (root / name / "campagne.yaml").read_text()
    ins, out_ = [], []
    for m in re.finditer(r"instant: (\S+), action: (injection|retrait)", text):
        (ins if m.group(2) == "injection" else out_).append(m.group(1)[11:16])
    return list(zip(ins, out_))

def minutes(hhmm, origin):
    h, m = map(int, hhmm.split(":")); t = h * 60 + m
    o = origin[0] * 60 + origin[1]
    return (t - o) % (24 * 60)

fig, axes = plt.subplots(len(CAMPAGNES), 1, figsize=(11, 9), sharex=True)
for ax, (name, title) in zip(axes, CAMPAGNES):
    rows = queue_rows(name)
    origin = tuple(map(int, rows[0][0].split(":")))
    xs = [minutes(t, origin) for t, _ in rows]; ys = [b for _, b in rows]
    for a, b in injections(name):
        ax.axvspan(minutes(a, origin), minutes(b, origin), color="#f4c7c3", alpha=0.6, lw=0)
    ax.plot(xs, ys, color="#1f4e79", lw=1.6)
    ax.set_ylim(0, 950); ax.set_ylabel("messages\nen attente", fontsize=9)
    ax.set_title(title, fontsize=10, loc="left")
    ax.grid(alpha=0.3)
axes[-1].set_xlabel("minutes depuis le début de la campagne (fenêtres de 60 s ; zones rouges = panne injectée)")
fig.suptitle("Le tas de la file food_delivery — 1 référence, 4 causes, 3 injections chacune", fontsize=12)
fig.tight_layout()
fig.savefig(out, dpi=150)
print("->", out)
