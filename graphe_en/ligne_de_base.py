"""
Les lignes de base sur les campagnes committées : ce qu'un modèle doit battre.

    ./.venv/bin/python ligne_de_base.py [options] [campagne ...]

Lit campagnes/<nom>/campagne.yaml (le déroulé) et lecture.txt (la file, les
répliques du consommateur, les hôtes) des campagnes nommées, ou, sans nom, de
chaque dossier de campagne qui porte les deux fichiers sauf les essais courts
(essai-*). Nomme les campagnes de l'étude : une campagne abandonnée laissée
dans le dossier y serait sinon mélangée. Rien n'est rapatrié et aucune grappe
n'est nécessaire : les machines peuvent déjà être libérées.

Trois des quatre lignes de base du protocole, jugées sur les mêmes fenêtres :

  1   seuil          un seul nombre, backlog_slope au-dessus d'une limite :
                     alarme, sans cause
  2a  file seule     les six composantes de la file, un arbre de décision et
                     une forêt aléatoire
  2b  tableau plat   seize nombres par fenêtre et aucune flèche : la file, les
                     répliques du consommateur et les hôtes résumés, les deux
                     mêmes apprenants
  3   règles à la main  quatre règles écrites d'après ce qu'on sait de la
                     plateforme, avec des limites prises sur la référence saine

La quatrième, l'auto-encodeur de graphe, est un modèle : elle vient avec la
modélisation.

Vérité d'une fenêtre, d'après le déroulé : entièrement dans une injection
confirmée, sa cause ; à cheval sur une injection ou un retrait, écartée ;
après un retrait tant que le tas dépasse --drain messages, plus une fenêtre de
garde, écartée comme vidange ; sinon normale. Une campagne sans injection est
entièrement normale.

Coupure par le temps, jamais au hasard : la dernière injection de chaque
campagne, avec les fenêtres depuis dix minutes avant elle, est le jeu de
test ; le reste apprend. Une campagne sans injection donne son dernier tiers.
Une cause est donc jugée sur une injection que les apprenants n'ont jamais vue.

Options :
  --campaigns <dossier>  le dossier des dossiers de campagne (défaut ../campagnes)
  --consumer <prefixe>   les répliques résumées (défaut ts-delivery-service-)
  --threshold <n>        ligne de base 1, la limite de backlog_slope (défaut 20)
  --drain <n>            tas sous lequel la file compte comme vidée (défaut 10)
  --depth <n>            questions à la suite permises à l'arbre (défaut 4)
  --trees <n>            arbres de la forêt (défaut 200)
  --no-install           n'installe jamais scikit-learn, même dans un
                         environnement virtuel
  --help                 ce texte

Écrit <dossier des campagnes>/lignes_de_base.txt et affiche le même texte.
Code de sortie 2 sur un mauvais argument, 1 quand aucune campagne n'est
utilisable ou qu'une bibliothèque manque.
"""
from __future__ import annotations

import contextlib
import io
import math
import re
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bootstrap

HERE = Path(__file__).resolve().parent

# En-têtes et colonnes : noms d'attributs du graphe, jamais traduits — ce sont
# ceux de lecture.txt et du lexique.
QUEUE_COLUMNS = ["backlog", "backlog_slope", "publish_rate", "consume_rate",
                 "rate_imbalance", "consumers"]
SUMMARY_COLUMNS = ["repliques_avec_temps", "process_time_p50_moyen", "process_time_p50_max",
                   "process_time_p95_max", "cpu_rate_min", "cpu_rate_max",
                   "hote_cpu_busy_max", "hote_cpu_pressure_max",
                   "hote_memory_pressure_max", "hote_io_pressure_max"]
NORMAL = "normal"

# Ligne de base 3, les règles à la main. Les noms de cause sont ceux de
# apps/panne.sh ; les deux facteurs s'appliquent aux médianes de la
# référence saine, les deux limites absolues sont en messages par seconde et
# en part d'un processeur.
RULE_CAUSES = {"load": "charge", "freeze": "blocage", "slow": "lenteur", "host": "hote"}
RULES = {"imbalance": 0.2, "host_cpu": 0.5, "slow_factor": 1.25, "load_factor": 1.2}


# ------------------------------------------------------------------------------
# Lire les deux fichiers d'une campagne
# ------------------------------------------------------------------------------
def number(token: str) -> float:
    return math.nan if token == "-" else float(token)


def read_readout(path: Path) -> tuple[int, dict, dict, dict]:
    """Les trois tableaux de lecture.txt, indexés par fenêtre : file, instances, hôtes."""
    width, header, section = 60, None, None
    queue: dict[int, dict] = {}
    instances: dict[int, list] = {}
    hosts: dict[int, list] = {}
    for line in path.read_text().splitlines():
        m = re.search(r"(?:fenêtres de|windows of) (\d+) s", line)
        if m:
            width = int(m.group(1))
        if line.startswith("queue:"):
            section, header = "queue", None
        elif line.startswith("instances containing"):
            section, header = "instances", None
        elif line.startswith("hosts"):
            section, header = "hosts", None
        elif section and line.startswith("window"):
            header = line.split()
        elif section and header and re.match(r"^\s*\d+\s+\d\d:\d\d:\d\d", line):
            fields = line.split()
            if len(fields) != len(header) or "(absent)" in line:
                continue
            row = dict(zip(header, fields))
            w = int(row["window"])
            values = {k: number(v) for k, v in row.items() if k not in ("window", "start_utc", "instance", "host")}
            if section == "queue":
                queue[w] = dict(start_utc=row["start_utc"], **values)
            elif section == "instances":
                instances.setdefault(w, []).append(dict(name=row["instance"], **values))
            else:
                hosts.setdefault(w, []).append(dict(name=row["host"], **values))
    return width, queue, instances, hosts


def read_timeline(path: Path) -> list[tuple[datetime, datetime, str, bool]]:
    """(injection, retrait, cause, confirmée) pour chaque injection du déroulé."""
    pattern = re.compile(r"instant: (\S+), action: (injection|retrait)(?:, cause: (\w+))?(?:, resultat: (\w+))?")
    pairs, open_ = [], None
    for line in path.read_text().splitlines():
        m = pattern.search(line)
        if not m:
            continue
        instant = datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if m.group(2) == "injection":
            open_ = (instant, m.group(3) or "?", (m.group(4) or "").lower() == "confirme")
        elif open_:
            pairs.append((open_[0], instant, open_[1], open_[2]))
            open_ = None
    return pairs


# ------------------------------------------------------------------------------
# Une ligne par fenêtre : la vérité, le jeu, les nombres
# ------------------------------------------------------------------------------
def summarise(replicas: list, hosts: list) -> list[float]:
    def clean(values):
        return [v for v in values if not math.isnan(v)]

    def agg(fn, values):
        v = clean(values)
        return fn(v) if v else math.nan

    p50 = [r.get("process_time_p50", math.nan) for r in replicas]
    p95 = [r.get("process_time_p95", math.nan) for r in replicas]
    cpu = [r.get("cpu_rate", math.nan) for r in replicas]
    return [float(len(clean(p50))), agg(statistics.fmean, p50), agg(max, p50), agg(max, p95),
            agg(min, cpu), agg(max, cpu),
            agg(max, [h.get("cpu_busy", math.nan) for h in hosts]),
            agg(max, [h.get("cpu_pressure", math.nan) for h in hosts]),
            agg(max, [h.get("memory_pressure", math.nan) for h in hosts]),
            agg(max, [h.get("io_pressure", math.nan) for h in hosts])]


def label_windows(name: str, folder: Path, consumer: str, drain: float, notes: list[str]) -> list[dict]:
    width, queue, instances, hosts = read_readout(folder / "lecture.txt")
    pairs = read_timeline(folder / "campagne.yaml")
    windows = sorted(queue)
    if not windows:
        notes.append(f"{name} : aucune ligne de file dans lecture.txt, campagne sautée")
        return []
    starts = {w: datetime.fromtimestamp(w * width, tz=timezone.utc) for w in windows}
    first = windows[0]
    if starts[first].strftime("%H:%M:%S") != queue[first]["start_utc"]:
        sys.exit(f"{name} : la fenêtre {first} ne commence pas à {queue[first]['start_utc']} "
                 f"avec des fenêtres de {width} s ; les lignes de base attendent pas = largeur")
    span = timedelta(seconds=width)

    truth = {}
    for w in windows:
        s, e = starts[w], starts[w] + span
        lab = NORMAL
        for (ti, tr, cause, confirmed) in pairs:
            if s >= ti and e <= tr:
                lab = cause if confirmed else "non_confirmee"
            elif s < ti < e or s < tr < e:
                lab = "a_cheval"
        truth[w] = lab
    for (ti, tr, cause, confirmed) in pairs:
        if not confirmed:
            notes.append(f"{name} : injection de {ti:%H:%M} non confirmée, ses fenêtres sont écartées")
        guard = 1
        for w in (w for w in windows if starts[w] >= tr):
            if truth[w] != NORMAL:
                continue
            if queue[w]["backlog"] > drain or guard > 0:
                truth[w] = "vidange"
                guard -= 1
            else:
                break

    if pairs:
        t_last = pairs[-1][0] - timedelta(minutes=10)
        in_test = lambda w: starts[w] >= t_last
        if len(pairs) == 1:
            notes.append(f"{name} : une seule injection, testée sur elle et rien de cette cause à l'apprentissage")
    else:
        cut = windows[len(windows) * 2 // 3]
        in_test = lambda w: w >= cut

    rows = []
    for w in windows:
        q = queue[w]
        replicas = [r for r in instances.get(w, []) if r["name"].startswith(consumer)]
        rows.append(dict(campaign=name, window=w, start=q["start_utc"], truth=truth[w],
                         test=in_test(w),
                         queue=[q.get(c, math.nan) for c in QUEUE_COLUMNS],
                         table=[q.get(c, math.nan) for c in QUEUE_COLUMNS] + summarise(replicas, hosts.get(w, []))))
    return rows


# ------------------------------------------------------------------------------
# Les lignes de base
# ------------------------------------------------------------------------------
def per_cause(rows: list[dict], pred: list[str], causes: list[str]) -> list[str]:
    out = [f"{'vérité':<10}{'fenêtres':>9}{'justes':>8}   confondues avec"]
    for k in causes:
        n = sum(1 for r in rows if r["truth"] == k)
        ok = sum(1 for r, p in zip(rows, pred) if r["truth"] == k and p == k)
        wrong: dict[str, int] = {}
        for r, p in zip(rows, pred):
            if r["truth"] == k and p != k:
                wrong[p] = wrong.get(p, 0) + 1
        out.append((f"{k:<10}{n:>9}{ok:>8}   " + ", ".join(f"{v} {kk}" for kk, v in wrong.items())).rstrip())
    return out


def learners(train: list[dict], test: list[dict], key: str, columns: list[str],
             causes: list[str], depth: int, trees: int) -> list[str]:
    import numpy as np
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.tree import DecisionTreeClassifier, export_text

    x_tr = np.array([r[key] for r in train]); y_tr = [r["truth"] for r in train]
    x_te = np.array([r[key] for r in test]); y_te = [r["truth"] for r in test]
    out = []
    for title, model in [(f"arbre de décision, {depth} questions à la suite", DecisionTreeClassifier(max_depth=depth, random_state=0)),
                         (f"forêt aléatoire, {trees} arbres", RandomForestClassifier(n_estimators=trees, random_state=0))]:
        model.fit(x_tr, y_tr)
        pred = list(model.predict(x_te))
        right = sum(1 for p, y in zip(pred, y_te) if p == y)
        out.append(f"-- {title} : {right} / {len(y_te)} fenêtres de test bien nommées")
        out += per_cause(test, pred, causes)
        if isinstance(model, DecisionTreeClassifier):
            out.append("   les questions choisies par l'arbre :")
            out += ["   " + l for l in export_text(model, feature_names=columns, decimals=2).rstrip().splitlines()]
        out.append("")
    return out


def hand_rules(train: list[dict], test: list[dict], causes: list[str]) -> list[str]:
    col = {c: i for i, c in enumerate(QUEUE_COLUMNS + SUMMARY_COLUMNS)}
    healthy = [r["table"] for r in train if r["truth"] == NORMAL]

    def median(name):
        v = [t[col[name]] for t in healthy if not math.isnan(t[col[name]])]
        return statistics.median(v) if v else math.nan

    p_ref, t_ref, c_ref = median("publish_rate"), median("process_time_p50_max"), median("consumers")
    limits = dict(imbalance=RULES["imbalance"], host=RULES["host_cpu"],
                  slow=RULES["slow_factor"] * t_ref, load=RULES["load_factor"] * p_ref, consumers=c_ref)

    def rule(t):
        if not (t[col["rate_imbalance"]] > limits["imbalance"]):
            return RULE_CAUSES["host"] if t[col["hote_cpu_busy_max"]] > limits["host"] else NORMAL
        if t[col["process_time_p50_max"]] > limits["slow"]:
            return RULE_CAUSES["slow"]
        if t[col["publish_rate"]] > limits["load"]:
            return RULE_CAUSES["load"]
        if t[col["consumers"]] < limits["consumers"] or t[col["repliques_avec_temps"]] < limits["consumers"]:
            return RULE_CAUSES["freeze"]
        return "inconnue"

    out = [f"limites : rate_imbalance > {limits['imbalance']} veut dire que la file se remplit ; "
           f"hote_cpu_busy_max > {limits['host']} nomme l'hôte ;",
           f"          process_time_p50_max > {limits['slow']:.0f} ms ({RULES['slow_factor']} x les {t_ref:.0f} de la référence) nomme la lenteur ;",
           f"          publish_rate > {limits['load']:.2f} msg/s ({RULES['load_factor']} x les {p_ref:.2f} de la référence) nomme la charge ;",
           f"          moins de {c_ref:.0f} consommateurs, ou une réplique sans temps de traitement, nomme le blocage."]
    pred = [rule(r["table"]) for r in test]
    right = sum(1 for r, p in zip(test, pred) if p == r["truth"])
    out.append(f"-- règles à la main : {right} / {len(test)} fenêtres de test bien nommées")
    out += per_cause(test, pred, causes)
    return out


def threshold(test: list[dict], limit: float, causes: list[str]) -> list[str]:
    slope = QUEUE_COLUMNS.index("backlog_slope")
    out = [f"{'vérité':<10}{'fenêtres':>9}{'alarmes':>8}"]
    for k in causes:
        rows = [r for r in test if r["truth"] == k]
        alarms = sum(1 for r in rows if not math.isnan(r["queue"][slope]) and r["queue"][slope] > limit)
        out.append(f"{k:<10}{len(rows):>9}{alarms:>8}")
    return out


# ------------------------------------------------------------------------------
def report(campaigns_dir: Path, names: list[str], opts: dict) -> int:
    notes: list[str] = []
    rows: list[dict] = []
    for name in names:
        rows += label_windows(name, campaigns_dir / name, opts["consumer"], opts["drain"], notes)
    if not rows:
        print("aucune campagne utilisable", file=sys.stderr)
        return 1
    names = sorted(names, key=lambda n: min(r["window"] for r in rows if r["campaign"] == n))
    rows.sort(key=lambda r: r["window"])
    causes = [NORMAL] + sorted({r["truth"] for r in rows} - {NORMAL, "a_cheval", "vidange", "non_confirmee"})
    kept = [r for r in rows if r["truth"] in causes]
    train = [r for r in kept if not r["test"]]
    test = [r for r in kept if r["test"]]

    print(f"# Lignes de base sur les campagnes committées — écrit par {HERE.name}/{Path(__file__).name}")
    print(f"# campagnes : {' '.join(names)}")
    print(f"# répliques du consommateur : {opts['consumer']}*   seuil : {opts['threshold']:g}   "
          f"vidée sous : {opts['drain']:g}   profondeur de l'arbre : {opts['depth']}   arbres : {opts['trees']}")
    print(f"# fenêtres lues : {len(rows)}   gardées : {len(kept)}   écartées, à cheval ou vidange : {len(rows) - len(kept)}")
    if opts.get("skipped"):
        print(f"# note : essais laissés de côté : {' '.join(opts['skipped'])}")
    for n in notes:
        print(f"# note : {n}")
    print()
    print(f"{'campagne':<14}{'apprentissage':<34}test")
    for name in names:
        def counts(subset):
            return "  ".join(f"{k}={sum(1 for r in subset if r['campaign'] == name and r['truth'] == k)}"
                            for k in causes if any(r["campaign"] == name and r["truth"] == k for r in subset))
        print(f"{name:<14}{counts(train):<34}{counts(test)}")
    print(f"{'total':<14}{len(train):<34}{len(test)}")
    print()

    print(f"== 1  seuil : alarme quand backlog_slope > {opts['threshold']:g} (trouve la panne, jamais la cause)")
    print("\n".join(threshold(test, opts["threshold"], causes)))
    print()
    print(f"== 2a file seule : {len(QUEUE_COLUMNS)} nombres par fenêtre")
    print("\n".join(learners(train, test, "queue", QUEUE_COLUMNS, causes, opts["depth"], opts["trees"])))
    print(f"== 2b tableau plat : {len(QUEUE_COLUMNS) + len(SUMMARY_COLUMNS)} nombres par fenêtre, aucune flèche")
    print("\n".join(learners(train, test, "table", QUEUE_COLUMNS + SUMMARY_COLUMNS, causes, opts["depth"], opts["trees"])))
    print("== 3  règles à la main, limites prises sur la référence saine")
    print("\n".join(hand_rules(train, test, causes)))
    return 0


def usage(code: int) -> int:
    print(__doc__.strip(), file=sys.stdout if code == 0 else sys.stderr)
    return code


def main(argv: list[str]) -> int:
    opts = dict(campaigns=HERE.parent / "campagnes", consumer="ts-delivery-service-",
                threshold=20.0, drain=10.0, depth=4, trees=200, install=True)
    names: list[str] = []
    args = argv[1:]
    try:
        while args:
            a = args.pop(0)
            if a == "--help":
                return usage(0)
            elif a == "--no-install":
                opts["install"] = False
            elif a in ("--campaigns", "--consumer", "--threshold", "--drain", "--depth", "--trees"):
                v = args.pop(0)
                key = a[2:]
                opts[key] = (Path(v) if key == "campaigns" else v if key == "consumer"
                             else int(v) if key in ("depth", "trees") else float(v))
            elif a.startswith("-"):
                print(f"option inconnue : {a}", file=sys.stderr)
                return usage(2)
            else:
                names.append(a)
    except (IndexError, ValueError):
        return usage(2)

    campaigns_dir = Path(opts["campaigns"]).resolve()
    if not names:
        found = sorted(p.name for p in campaigns_dir.iterdir()
                       if (p / "campagne.yaml").is_file() and (p / "lecture.txt").is_file()) if campaigns_dir.is_dir() else []
        names = [n for n in found if not n.startswith("essai-")]
        opts["skipped"] = [n for n in found if n.startswith("essai-")]
    if not names:
        print(f"aucune campagne avec campagne.yaml et lecture.txt sous {campaigns_dir}", file=sys.stderr)
        return 1
    for name in names:
        for f in ("campagne.yaml", "lecture.txt"):
            if not (campaigns_dir / name / f).is_file():
                print(f"manque {campaigns_dir / name / f}", file=sys.stderr)
                return 1

    req = bootstrap.REQUIREMENTS["baseline"]
    if not bootstrap.is_available(req.module):
        if opts["install"] and bootstrap.in_virtualenv():
            done, detail = bootstrap.install(req)
            print(f"installé {req.package} {detail}" if done else f"impossible d'installer {req.package} : {detail}",
                  file=sys.stderr)
            if not done:
                return 1
        else:
            print(f"{req.package} manque, nécessaire pour {req.purpose} : {bootstrap.manual_command(req)}",
                  file=sys.stderr)
            return 1

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = report(campaigns_dir, names, opts)
    text = out.getvalue()
    print(text, end="")
    if code == 0:
        target = campaigns_dir / "lignes_de_base.txt"
        target.write_text(text)
        print(f"-> {target}")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
