#!/usr/bin/env python3
# ==============================================================================
#  suivi.py — le cœur de suivi.sh : l'état de la collecte en un écran
# ==============================================================================
#
#  CE QUE FAIT CE SCRIPT
#
#  Il lit, sur vms0 SEULEMENT, les fichiers que le gardien (garde.py) et le
#  pilote (campagne.sh) écrivent, et en tire un écran d'au plus 40 lignes et
#  110 colonnes, dans cet ordre :
#    1. l'heure UTC, l'âge de la dernière ligne de garde.tsv (« GARDIEN MUET »
#       au-delà de 3 min), le mode du gardien (AGIR ou PROPOSE) ;
#    2. la campagne en cours (pilote vivant ?), la dernière ligne de son journal ;
#    3. la panne déclarée ;
#    4. la dernière minute (état, causes, notes) et ses valeurs clés ;
#    5. les 30 dernières minutes en une ligne de lettres ;
#    6. les alertes ouvertes (DEBUT sans FIN) et les 5 dernières lignes d'alertes.txt ;
#    7. le drapeau de pause et les 3 dernières actions ;
#    8. les 5 dernières lignes FIN de fins.tsv, et le bilan depuis minuit UTC.
#  Avec --journal, il suit le journal du pilote en cours (comme tail -F) et passe
#  au journal suivant quand une nouvelle campagne démarre.
#
#  POURQUOI
#
#  Pendant les 7 jours de collecte, on doit pouvoir regarder à tout moment sans
#  risque : ce script n'écrit RIEN, ne lance ni ssh ni kubectl, ne charge pas le
#  cluster. Un fichier absent, vide, coupé en cours d'écriture donne « (pas
#  encore de données) », jamais une erreur. Il ne code aucune règle sur un nom
#  de panne ni sur un code de cause : il recopie ce que le gardien a écrit.
#
#  Le pilote vivant est cherché comme le fait le gardien : la fonction
#  trouver_pilotes de garde.py (même dossier) est réutilisée ; si garde.py ne se
#  charge pas, une recherche simple dans /proc la remplace.
#
#  Usage (normalement par suivi.sh) :
#      python3 suivi.py [--une-fois]          un écran, puis s'arrête (défaut)
#      python3 suivi.py --boucle <secondes>   efface et redessine (Ctrl-C pour sortir)
#      python3 suivi.py --journal             suit le journal du pilote en cours
#      options : --dossier <d>  (défaut : GARDE_DOSSIER, sinon ~/journaux-hors-campagne/garde)
#      internes (pour collecte-tmux.sh) :
#                --age-garde    la dernière minute de garde.tsv et son âge, sur une ligne
#                --pilotes      les pilotes vivants, « nom<TAB>pid », un par ligne
#
#  Variables reconnues :
#      GARDE_DOSSIER     le dossier du gardien
#      GARDE_PROC        (défaut: /proc) où chercher le pilote (essais)
#      SUIVI_MAINTENANT  (essais seulement) l'heure du suivi, AAAA-MM-JJTHH:MM:SSZ
#      SUIVI_ATTENTE     (défaut: 2) secondes entre deux lectures du journal (--journal)
#      NO_COLOR          pas de couleur, même dans un terminal
# ==============================================================================
import glob
import json
import os
import re
import signal
import sys
import threading
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

sys.dont_write_bytecode = True   # charger garde.py ne laisse rien dans le dépôt

ICI = os.path.dirname(os.path.abspath(__file__))
DEPOT = ICI                      # le dépôt sur vms0 = le dossier de ce script
ACCUEIL = os.path.expanduser("~")
LARGEUR, HAUTEUR = 110, 40
MUET_MIN = 3                     # au-delà : « GARDIEN MUET »
BANDE_MIN = 30
LIGNES_TSV = 1700                # de quoi couvrir la journée depuis minuit (1 440 minutes)
VIDE = "(pas encore de données)"
RE_MINUTE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\dZ$")
RE_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07|\r")
LETTRES = {"OK": "O", "MALADE": "M", "DOUTEUX": "D"}
# Des colonnes de garde.tsv remplies seulement quand le master a répondu.
COLONNES_MASTER = ("en_panne", "noeuds_prets", "voyageurs_demandes", "req_s", "duree_sonde_s")
# L'ordre des alertes ouvertes : les plus graves d'abord (2e colonne d'alertes.txt).
RANG_NIVEAU = {"MALADE": 0, "DOUTEUX": 1}


# ------------------------------------------------------------------------------
# L'heure et les petits textes
# ------------------------------------------------------------------------------
def maintenant():
    f = os.environ.get("SUIVI_MAINTENANT")
    if f:
        try:
            return datetime.strptime(f, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def lire_minute(s):
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def lire_instant(s):
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def hm(t, ref):
    """« HH:MM », précédé du jour si ce n'est pas le jour de ref."""
    if t is None:
        return "?"
    return t.strftime("%H:%M") if t.date() == ref.date() else t.strftime("%d/%m %H:%M")


def duree(minutes):
    """5 → « 5 min » ; 135 → « 2 h 15 » ; 3000 → « 2 j 2 h »."""
    if minutes is None:
        return "?"
    m = int(max(0, minutes))
    if m < 60:
        return f"{m} min"
    if m < 1440:
        return f"{m // 60} h {m % 60:02d}"
    return f"{m // 1440} j {(m % 1440) // 60} h"


def minutes_entre(avant, apres):
    return (apres - avant).total_seconds() / 60


def couper(texte, largeur=LARGEUR):
    texte = RE_ANSI.sub("", texte).replace("\t", " ")
    return texte if len(texte) <= largeur else texte[:largeur - 1] + "…"


def v(ligne, col, defaut="?"):
    x = (ligne or {}).get(col, "")
    return x if x != "" else defaut


# ------------------------------------------------------------------------------
# Les lectures : jamais d'erreur, au pire « rien »
# ------------------------------------------------------------------------------
def lire_fin(chemin, n, completes=False, bloc=65536, plafond=8 * 2**20):
    """Les n dernières lignes d'un fichier, lu par la fin ([] s'il manque).
    completes=True : une dernière ligne sans fin de ligne (en cours d'écriture) est laissée."""
    try:
        with open(chemin, "rb") as f:
            f.seek(0, os.SEEK_END)
            taille = pos = f.tell()
            donnees = b""
            while pos > 0 and donnees.count(b"\n") <= n and taille - pos < plafond:
                lu = min(bloc, pos)
                pos -= lu
                f.seek(pos)
                donnees = f.read(lu) + donnees
    except OSError:
        return []
    lignes = donnees.decode("utf-8", "replace").split("\n")
    if pos > 0:
        lignes = lignes[1:]          # la première ligne lue est sans doute coupée
    if lignes and lignes[-1] == "":
        lignes.pop()
    elif completes and lignes:
        lignes.pop()                 # pas de fin de ligne : ligne en cours d'écriture
    return lignes[-n:]


def lire_json(chemin):
    try:
        with open(chemin, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def lire_tsv(chemin, n=LIGNES_TSV):
    """garde.tsv : les n dernières lignes complètes, en dictionnaires (colonnes lues
    dans l'en-tête : un ajout de colonne ne casse rien). Rend {} si rien."""
    try:
        with open(chemin, encoding="utf-8", errors="replace") as f:
            entete = f.readline().rstrip("\n").split("\t")
    except OSError:
        return {}
    if not entete or entete[0] != "minute":
        return {}
    lignes = {}
    for l in lire_fin(chemin, n, completes=True):
        c = l.split("\t")
        if len(c) != len(entete) or not RE_MINUTE.match(c[0]):
            continue                 # en-tête, ligne coupée ou abîmée
        lignes[c[0]] = dict(zip(entete, c))
    return lignes


def lire_cles(chemin):
    """Un fichier CLE=valeur (le drapeau de pause). None s'il manque."""
    try:
        with open(chemin, encoding="utf-8", errors="replace") as f:
            texte = f.read(65536)
    except OSError:
        return None
    res = {}
    for l in texte.splitlines():
        if "=" in l:
            k, _, x = l.partition("=")
            res[k.strip()] = x.strip()
    return res


# ------------------------------------------------------------------------------
# Le pilote : comme le gardien le cherche
# ------------------------------------------------------------------------------
_GARDE = []   # [module] une fois chargé ([None] s'il ne se charge pas)


def module_garde():
    if not _GARDE:
        m = None
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("garde_pour_suivi", os.path.join(DEPOT, "garde.py"))
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            if not callable(getattr(m, "trouver_pilotes", None)):
                m = None
        except BaseException as e:   # même un SystemExit de garde.py ne doit pas arrêter le suivi
            if isinstance(e, KeyboardInterrupt):
                raise
            m = None
        _GARDE.append(m)
    return _GARDE[0]


def pilotes_simples(racine):
    """Secours si garde.py ne se charge pas : tout processus dont un argument est
    campagne.sh (les racines seulement : pas les sous-shells du même pilote)."""
    trouves = {}
    for pid in os.listdir(racine):
        if not pid.isdigit():
            continue
        try:
            with open(f"{racine}/{pid}/cmdline", "rb") as f:
                argv = [a.decode("utf-8", "replace") for a in f.read().split(b"\0") if a]
            with open(f"{racine}/{pid}/stat") as f:
                champs = f.read().rsplit(")", 1)[1].split()
        except (OSError, IndexError):
            continue
        if champs[0] == "Z":
            continue
        for i, a in enumerate(argv):
            if os.path.basename(a) == "campagne.sh":
                nom = argv[i + 1] if len(argv) > i + 1 and not argv[i + 1].startswith("-") else ""
                trouves[int(pid)] = {"pid": int(pid), "nom": nom, "ppid": int(champs[1]),
                                     "debut": int(champs[19])}
                break
    return [x for p, x in sorted(trouves.items()) if x["ppid"] not in trouves]


def pilotes(strict=False):
    """Les pilotes vivants. strict=True (pour collecte-tmux.sh --pilotes) : si
    aucune des deux recherches ne marche, l'erreur remonte au lieu de « aucun »."""
    racine = os.environ.get("GARDE_PROC", "/proc")
    try:
        m = module_garde()
        if m is not None:
            return m.trouver_pilotes(racine)
        return pilotes_simples(racine)
    except Exception:
        try:
            return pilotes_simples(racine)
        except Exception:
            if strict:
                raise
            return []


def depart_processus(debut_tops):
    """La date de démarrage d'un processus (champ starttime) en datetime UTC, ou None."""
    try:
        with open("/proc/stat") as f:
            btime = next(int(l.split()[1]) for l in f if l.startswith("btime "))
        return datetime.fromtimestamp(btime + debut_tops / os.sysconf("SC_CLK_TCK"), timezone.utc)
    except Exception:
        return None


def journaux():
    return glob.glob(os.path.join(DEPOT, "journaux", "campagne-*.log"))


def plus_recent(fichiers):
    meilleur, cle = None, None
    for f in fichiers:
        try:
            k = (os.path.getmtime(f), f)
        except OSError:
            continue
        if cle is None or k > cle:
            meilleur, cle = f, k
    return meilleur


# ------------------------------------------------------------------------------
# L'écran, rubrique par rubrique (chacune rend une liste de lignes)
# ------------------------------------------------------------------------------
class Lecture:
    """Tout ce que l'écran lit, lu une fois."""

    def __init__(self, dossier):
        self.t = maintenant()
        self.dossier = dossier
        self.lignes = lire_tsv(os.path.join(dossier, "garde.tsv"))
        self.minutes = sorted(self.lignes)
        self.derniere = self.lignes[self.minutes[-1]] if self.minutes else None
        self.dernier = lire_json(os.path.join(dossier, "dernier.json"))
        # La dernière minute MESURÉE sur le master : une minute MEASURE_GAP n'a
        # aucune valeur, une minute MEASURE_FAILED:ssh n'a que les colonnes de vms0
        # (pilote, place libre). en_panne est écrite à chaque mesure du master.
        self.mesuree = None
        for m in reversed(self.minutes):
            l = self.lignes[m]
            if any(l.get(c, "") != "" for c in COLONNES_MASTER):
                self.mesuree = l
                break
        # La place libre sur vms0 est mesurée sur vms0 : lue à part, la plus récente.
        self.libre = next((self.lignes[m] for m in reversed(self.minutes)
                           if self.lignes[m].get("vms0_libre_go", "") != ""), None)
        self.fins = [l.split("\t") for l in lire_fin(os.path.join(DEPOT, "journaux", "fins.tsv"), 400)
                     if l.startswith("FIN_CAMPAGNE\t")]


def texte_mode(L):
    """Le mode du gardien : dans dernier.json ; à défaut dans memoire.json. garde.py
    n'écrit la clé « mode » de memoire.json qu'en passant en AGIR (ou en revenant
    à PROPOSE) : sans elle, c'est PROPOSE — sauf si la mémoire a été remise à neuf
    (memoire_cassee : clé repartie_a, ou un memoire.json.*.casse à côté), où elle
    est perdue même en AGIR."""
    noms = {"agir": "AGIR (gestes du niveau 1)", "propose": "PROPOSE (aucun geste)"}
    if L.dernier and L.dernier.get("mode") in noms:
        return noms[L.dernier["mode"]]
    chemin = os.path.join(L.dossier, "memoire.json")
    mem = lire_json(chemin)
    if mem is None:
        return "inconnu (dernier.json et memoire.json absents ou illisibles)"
    if mem.get("mode") in noms:
        return f"{noms[mem['mode']]}, lu dans memoire.json"
    if mem.get("repartie_a") or glob.glob(glob.escape(chemin) + ".*.casse"):
        return "inconnu (dernier.json illisible, memoire.json remise à neuf sans mode)"
    return "PROPOSE (déduit de memoire.json, sans clé mode)"


def rubrique_gardien(L, couleur):
    t = L.t
    res = [f"SUIVI DE LA COLLECTE      {t:%Y-%m-%d %H:%M:%S} UTC      (lecture seule : ni ssh ni kubectl)"]
    mode = texte_mode(L)
    if L.derniere is None:
        res.append(f"gardien    : {VIDE} — garde.tsv absent ou vide dans {L.dossier}")
        return res
    m = lire_minute(L.derniere["minute"])
    age = minutes_entre(m, t)
    ligne = f"gardien    : dernière minute écrite {hm(m, t)} (il y a {duree(age)}) ; mode {mode}"
    if len(ligne) <= LARGEUR:
        res.append(ligne)
    else:   # un mode expliqué longuement : sur sa propre ligne, pour ne pas le couper
        res += [f"gardien    : dernière minute écrite {hm(m, t)} (il y a {duree(age)})", couper(f"             mode {mode}")]
    if age > MUET_MIN:
        bandeau = f"!!!!!!  GARDIEN MUET depuis {duree(age)} (dernière minute écrite : {hm(m, t)})  !!!!!!"
        res.append(couleur(bandeau.center(LARGEUR - 2, "!"), "muet"))
    return res


def rubrique_campagne(L):
    t = L.t
    res = []
    vivants = pilotes()
    if vivants:
        p = vivants[0]
        dep = depart_processus(p.get("debut", 0)) if p.get("debut") is not None else None
        depuis = ""
        if dep is not None:
            age = minutes_entre(dep, t)
            depuis = f", partie à {hm(dep, t)}" + (f" (il y a {duree(age)})" if age >= 0 else "")
        autres = "".join(f" + {x['nom']}({x['pid']})" for x in vivants[1:])
        res.append(f"campagne   : {p.get('nom') or '?'} (pid {p['pid']}) VIVANTE{depuis}"
                   + (f" ; AUTRES PILOTES : {autres}" if autres else ""))
    else:
        texte = "aucun pilote vivant"
        if L.fins:
            f = L.fins[-1] + [""] * 5
            texte += f" ; dernière fin : {f[1]} ({f[4] or '?'}, code {f[2]}) à {hm(lire_instant(f[3]), t)}"
        res.append(f"campagne   : {texte}")
    j = plus_recent(journaux())
    if j is None:
        res.append(f"journal    : {VIDE} (aucun journaux/campagne-*.log)")
    else:
        derniere = next((RE_ANSI.sub("", l).strip() for l in reversed(lire_fin(j, 30)) if RE_ANSI.sub("", l).strip()),
                        "(vide)")
        try:
            age = duree(minutes_entre(datetime.fromtimestamp(os.path.getmtime(j), timezone.utc), t))
        except OSError:
            age = "?"
        res.append(f"journal    : {os.path.basename(j)} (il y a {age}) : « {derniere} »")
    return res


def rubrique_panne(L):
    t = L.t
    l = L.mesuree
    if l is None:
        return [f"panne      : {VIDE}"]
    if l.get("en_panne") == "0":
        return ["panne      : aucune" + (f" (à la dernière minute mesurée, {hm(lire_minute(l['minute']), t)})"
                                          if l is not L.derniere else "")]
    if l.get("en_panne") != "1":
        return ["panne      : inconnue (la dernière minute mesurée ne le dit pas)"]
    cause = l.get("panne_declaree") or "?"
    contenu = {}
    try:
        contenu = ((L.dernier or {}).get("mesure") or {}).get("panne_etat", {}).get("contenu") or {}
    except AttributeError:
        contenu = {}
    debut = lire_instant(contenu.get("DEBUT")) if contenu.get("CAUSE") == cause else None
    if debut is None:
        # Pas de panne.etat (objets Chaos Mesh seuls) : depuis la première minute de la suite en panne.
        for m in reversed(L.minutes):
            if L.lignes[m].get("en_panne") == "1":
                debut = lire_minute(m)
            elif L.lignes[m].get("en_panne") == "0":
                break
        origine = "vue depuis"
    else:
        origine = "depuis"
    texte = f"panne      : « {cause} » {origine} {hm(debut, t)} ({duree(minutes_entre(debut, t)) if debut else '?'})"
    try:
        d = float(contenu.get("DUREE")) if contenu.get("CAUSE") == cause else None
    except (TypeError, ValueError):
        d = None
    if d is not None and debut is not None:
        texte += f", durée déclarée {d:g} min → fin prévue {hm(debut + timedelta(minutes=d), t)}"
    return [texte]


def rubrique_minute(L, couleur):
    t = L.t
    l = L.derniere
    if l is None:
        return [f"── dernière minute : {VIDE}"]
    res = []
    details = {}
    if L.dernier and L.dernier.get("minute") == l["minute"]:
        for cle in ("causes", "notes"):
            x = L.dernier.get(cle)
            if isinstance(x, dict):
                details.update(x)

    def codes(texte):
        if not texte:
            return "—"
        return " ; ".join(c + (f" ({details[c]})" if details.get(c) else "") for c in texte.split(","))
    etat = l.get("etat") or "?"
    premiere = couper(f"── dernière minute {hm(lire_minute(l['minute']), t)} : {etat}   "
                      f"causes : {codes(l.get('causes'))}")
    # La couleur après la coupe : les codes invisibles ne comptent pas dans la largeur.
    res.append(premiere.replace(f" : {etat}   ", f" : {couleur(etat, etat)}   ", 1))
    res.append(f"   notes  : {codes(l.get('notes'))}")
    m = L.mesuree
    if m is None:
        res.append(f"   valeurs : {VIDE}")
        return res
    if m is not l:
        # Sur sa propre ligne : coupée au bout d'une autre, l'heure disparaîtrait.
        res.append(f"   ATTENTION : valeurs de {hm(lire_minute(m['minute']), t)}, dernière minute mesurée "
                   f"(le master n'a rien rendu depuis) :")
    res.append(f"   voyageurs {v(m, 'voyageurs_demandes')} demandés / {v(m, 'voyageurs_reels')} réels   "
               f"req/s {v(m, 'req_s')} (seuil {v(m, 'req_s_min')})   échecs {v(m, 'echecs_pct')} %")
    res.append(f"   file d'attente  dépôt {v(m, 'depot')} msg/s   retrait {v(m, 'retrait')} msg/s   "
               f"tas {v(m, 'tas')}   consommateurs {v(m, 'consommateurs')}")
    res.append(f"   commandes CPU {v(m, 'cpu_commandes')} cœur   {v(m, 'commandes')} en table "
               f"(lue il y a {v(m, 'commandes_age_min')} min)   140 ms : {v(m, 'reglage_140ms')}")
    libre = f"vms0 libre {v(L.libre, 'vms0_libre_go')} Go"
    if L.libre is not None and L.libre is not m:
        libre += f" (à {hm(lire_minute(L.libre['minute']), t)})"
    res.append(f"   cluster   leader {v(m, 'leader')}   nœuds prêts {v(m, 'noeuds_prets')}   "
               f"âge S3 {v(m, 's3_age_s')} s   {libre}")
    return res


def bande(L):
    """Les BANDE_MIN dernières minutes, la plus ancienne à gauche. La dernière est la
    minute en cours si elle est déjà écrite, sinon la précédente."""
    t = L.t.replace(second=0, microsecond=0)
    fin = t if t.strftime("%Y-%m-%dT%H:%MZ") in L.lignes else t - timedelta(minutes=1)
    debut = fin - timedelta(minutes=BANDE_MIN - 1)
    lettres = []
    for i in range(BANDE_MIN):
        l = L.lignes.get((debut + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%MZ"))
        lettres.append("·" if l is None else LETTRES.get(l.get("etat"), "?"))
    return debut, fin, "".join(lettres)


def rubrique_bande(L):
    if not L.lignes:
        return [f"── 30 min : {VIDE}"]
    debut, fin, s = bande(L)
    groupes = " ".join(s[i:i + 10] for i in range(0, len(s), 10))
    n = Counter(s)
    return [f"── 30 min  {debut:%H:%M} {groupes} {fin:%H:%M}  "
            f"(O=OK {n['O']}, M=MALADE {n['M']}, D=DOUTEUX {n['D']}, ·=trou {n['·']}"
            + (f", ?=inconnu {n['?']}" if n['?'] else "") + ")"]


def alertes_ouvertes(chemin):
    """Les codes avec une ligne DEBUT et pas de FIN après : {code: (minute, niveau, texte)}."""
    ouvertes = {}
    try:
        with open(chemin, encoding="utf-8", errors="replace") as f:
            for l in f:
                p = l.split()
                if len(p) >= 4 and p[1] == "DEBUT":
                    reste = l.split(p[3], 1)[1].strip() if p[3] in l else ""
                    ouvertes[p[3]] = (p[0], p[2], reste)
                elif len(p) >= 4 and p[1] == "FIN":
                    ouvertes.pop(p[3], None)
    except OSError:
        return None
    return ouvertes


def rubrique_alertes(L, place):
    t = L.t
    chemin = os.path.join(L.dossier, "alertes.txt")
    ouvertes = alertes_ouvertes(chemin)
    res = []
    if ouvertes is None:
        res.append(f"── alertes ouvertes : {VIDE} (alertes.txt absent)")
    elif not ouvertes:
        res.append("── alertes ouvertes : aucune")
    else:
        res.append(f"── alertes ouvertes (DEBUT sans FIN) : {len(ouvertes)}")
        liste = sorted(ouvertes.items(), key=lambda x: (RANG_NIVEAU.get(x[1][1], 2), x[1][0], x[0]))
        montrees = liste if len(liste) <= place else liste[:max(0, place - 1)]
        for code, (h, niveau, reste) in montrees:
            debut = lire_minute(h)
            age = f"depuis {hm(debut, t)} ({duree(minutes_entre(debut, t))})" if debut else f"depuis {h}"
            res.append(couper(f"   {niveau:<7} {code:<24} {age:<22} {reste}"))
        if len(montrees) < len(liste):
            res.append(f"   … et {len(liste) - len(montrees)} autres (voir alertes.txt)")
    return res


def rubrique_alertes_recentes(L):
    lignes = [l for l in lire_fin(os.path.join(L.dossier, "alertes.txt"), 40) if l.strip() and not l.startswith("#")]
    if not lignes:
        return [f"── alertes.txt, 5 dernières lignes : {VIDE}"]
    return ["── alertes.txt, 5 dernières lignes :"] + [couper("   " + l) for l in lignes[-5:]]


def texte_action(ligne, t):
    """Une ligne d'actions.tsv : chaque colonne à sa place (« - » si vide), l'heure
    HH:MM:SS, une cible qui est un chemin réduite à son nom de fichier."""
    c = (ligne.split("\t") + [""] * 6)[:6]
    quand = lire_instant(c[0])
    c[0] = (quand.strftime("%H:%M:%S") if quand.date() == t.date() else quand.strftime("%d/%m %H:%M:%S")) \
        if quand else c[0]
    if "/" in c[3]:
        c[3] = os.path.basename(c[3].rstrip("/")) or c[3]
    return "   " + "  ".join(x if x != "" else "-" for x in c)


def rubrique_pause_actions(L, n_actions=3):
    t = L.t
    d = lire_cles(os.path.join(L.dossier, "pause"))
    if d is None:
        texte = "non (pas de drapeau)"
    elif d.get("POSE_PAR") == "garde":
        texte = (f"POSÉE par la garde depuis {hm(lire_instant(d.get('DEPUIS')), t)} — motifs {d.get('MOTIFS') or '?'}"
                 + (f" ({d['VALEURS']})" if d.get("VALEURS") else ""))
    else:
        texte = "POSÉE À LA MAIN (pas de POSE_PAR=garde) : seul un humain l'efface" + (
            f" — {d.get('MOTIFS')}" if d.get("MOTIFS") else "")
    res = [couper(f"── pause : {texte}")]
    actions = [l for l in lire_fin(os.path.join(L.dossier, "actions.tsv"), 10)
               if l.strip() and not l.startswith("instant\t")]
    if not actions:
        res.append(f"── actions (actions.tsv) : {VIDE}")
    else:
        res.append(f"── actions, {'dernière' if n_actions == 1 else f'{n_actions} dernières'} "
                   "(heure  geste  motif  cible  résultat  durée en s) :")
        res += [couper(texte_action(l, t)) for l in actions[-n_actions:]]
    return res


def rubrique_fins(L, liste=True):
    """liste=False (écran trop bas) : seulement la ligne de bilan du jour."""
    t = L.t
    jour = t.strftime("%Y-%m-%d")
    aujourdhui = [f for f in L.fins if len(f) > 3 and f[3].startswith(jour)]
    motifs = Counter((f + [""] * 5)[4] or "?" for f in aujourdhui)
    detail = ", ".join(f"{m} {n}" for m, n in sorted(motifs.items()))
    lignes_jour = [l for m, l in L.lignes.items() if m.startswith(jour)]
    malades = sum(1 for l in lignes_jour if l.get("etat") == "MALADE")
    bilan = (f"── depuis 00:00 UTC : {len(aujourdhui)} campagne(s) finie(s)" + (f" ({detail})" if detail else "")
             + (f" ; {malades} min MALADE sur {len(lignes_jour)} écrites" if L.lignes else " ; minutes MALADE : ?"))
    if not liste:
        return [couper(bilan)]
    if not L.fins:
        return [couper(f"── fins de campagne : {VIDE}"), couper(bilan)]
    res = ["── fins de campagne, 5 dernières (fins.tsv) :"]
    for f in L.fins[-5:]:
        f = f + [""] * 5
        quand = lire_instant(f[3])
        res.append(couper(f"   {hm(quand, t) if quand else f[3]:<11}  {f[1]:<32} code {f[2]:<4} motif {f[4] or '?'}"))
    return res + [couper(bilan)]


def proteger(fonction, *args):
    """Une rubrique qui échoue (imprévu) ne coûte qu'elle-même."""
    try:
        return fonction(*args)
    except Exception as e:
        return [couper(f"   {VIDE} — rubrique illisible pour l'instant ({type(e).__name__}: {e})")]


def ecran(dossier, hauteur=HAUTEUR, couleur=None):
    couleur = couleur or (lambda texte, _quoi: texte)
    L = Lecture(dossier)
    haut = (proteger(rubrique_gardien, L, couleur) + proteger(rubrique_campagne, L) + proteger(rubrique_panne, L)
            + proteger(rubrique_minute, L, couleur) + proteger(rubrique_bande, L))
    try:
        besoin = len(alertes_ouvertes(os.path.join(dossier, "alertes.txt")) or {}) or 1   # sous leur titre
    except Exception:
        besoin = 1
    # Écran trop bas : on retire, dans cet ordre, (1) les 5 dernières lignes
    # d'alertes.txt (le volet du milieu les montre), (2) la liste des fins (la
    # ligne de bilan du jour reste), (3) deux des trois actions. Les alertes
    # ouvertes prennent ensuite la place qui reste.
    reglages = [(True, True, 3), (False, True, 3), (False, False, 3), (False, False, 1)]
    for avec_recentes, avec_fins, n_actions in reglages:
        recentes = proteger(rubrique_alertes_recentes, L) if avec_recentes else []
        pause = proteger(rubrique_pause_actions, L, n_actions)
        fins = proteger(rubrique_fins, L, avec_fins)
        place = hauteur - len(haut) - 1 - len(recentes) - len(pause) - len(fins)
        if place >= besoin:
            break
    ouvertes = proteger(rubrique_alertes, L, max(1, place))
    lignes = haut + ouvertes + recentes + pause + fins
    lignes = [couper(l) if "\x1b" not in l else l for l in lignes]
    if len(lignes) > hauteur:
        lignes = lignes[:hauteur - 1] + ["… (écran coupé : agrandir la fenêtre, ou lancer ./suivi.sh seul)"]
    return lignes


# ------------------------------------------------------------------------------
# Les modes
# ------------------------------------------------------------------------------
def coloriste():
    if not sys.stdout.isatty() or os.environ.get("NO_COLOR") or os.environ.get("TERM", "dumb") == "dumb":
        return None
    codes = {"muet": "\033[1;7;31m", "MALADE": "\033[1;31m", "DOUTEUX": "\033[1;33m", "OK": "\033[32m"}
    return lambda texte, quoi: f"{codes[quoi]}{texte}\033[0m" if quoi in codes else texte


def arreter_sur_signal():
    def sortir(*_):
        sys.exit(0)
    for s in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(s, sortir)


def une_fois(dossier):
    sys.stdout.write("\n".join(ecran(dossier, couleur=coloriste())) + "\n")


def boucle(dossier, periode):
    arreter_sur_signal()
    # Fenêtre redimensionnée (un client tmux qui s'attache) : redessiner tout de
    # suite, à la nouvelle hauteur, sans attendre la fin de la période.
    redessiner = threading.Event()
    try:
        signal.signal(signal.SIGWINCH, lambda *_: redessiner.set())
    except (AttributeError, ValueError, OSError):
        pass
    while True:
        hauteur = HAUTEUR
        if sys.stdout.isatty():
            try:
                hauteur = max(10, min(HAUTEUR, os.get_terminal_size().lines - 1))
            except OSError:
                pass
        try:
            lignes = ecran(dossier, hauteur, coloriste())
        except Exception as e:
            lignes = [f"suivi : erreur imprévue ({type(e).__name__}: {e}) — nouvel essai dans {periode:g} s"]
        efface = "\033[H\033[2J" if sys.stdout.isatty() else "\n"
        sys.stdout.write(efface + "\n".join(lignes) + "\n")
        sys.stdout.flush()
        redessiner.wait(periode)
        if redessiner.is_set():
            redessiner.clear()
            time.sleep(0.2)   # laisser tmux finir de poser les tailles


def ecrire_brut(octets):
    sys.stdout.buffer.write(octets)
    sys.stdout.buffer.flush()


def lire_suite(chemin, pos):
    """Écrit ce qui a été ajouté à chemin depuis pos ; rend la nouvelle position."""
    try:
        with open(chemin, "rb") as f:
            f.seek(0, os.SEEK_END)
            taille = f.tell()
            if taille < pos:          # fichier raccourci ou remplacé : on repart du début
                pos = 0
            f.seek(pos)
            donnees = f.read(4 * 2**20)
    except OSError:
        return pos
    if donnees:
        ecrire_brut(donnees)
    return pos + len(donnees)


def debut_de_fin(chemin, n):
    """La position où commencent les n dernières lignes."""
    try:
        taille = os.path.getsize(chemin)
    except OSError:
        return 0
    fin = "\n".join(lire_fin(chemin, n))
    return max(0, taille - len(fin.encode("utf-8", "replace")) - 1)


def suivre_journal():
    """Comme tail -F sur le journal du pilote en cours ; un journal campagne-*.log
    NOUVEAU (créé après le départ du suivi) fait passer à lui : une nouvelle campagne."""
    arreter_sur_signal()
    try:
        attente = float(os.environ.get("SUIVI_ATTENTE", "2"))
    except ValueError:
        attente = 2.0
    vus = set(journaux())
    courant = plus_recent(vus)
    pos = 0
    dossier = os.path.join(DEPOT, "journaux")
    if courant is None:
        print(f"── journal du pilote : {VIDE} (aucun campagne-*.log dans {dossier}) ; on attend la première campagne",
              flush=True)
    else:
        print(f"── journal du pilote : {os.path.basename(courant)} (fin ; la suite s'affiche quand elle arrive)",
              flush=True)
        pos = debut_de_fin(courant, 20)
        pos = lire_suite(courant, pos)
    while True:
        time.sleep(attente)
        nouveaux = [f for f in journaux() if f not in vus]
        if nouveaux:
            vus.update(nouveaux)
            candidat = plus_recent(nouveaux)
            if candidat and candidat != courant:
                if courant:
                    pos = lire_suite(courant, pos)   # la fin de l'ancien d'abord
                print(f"\n════ nouvelle campagne ({maintenant():%Y-%m-%d %H:%M:%S} UTC) : journal "
                      f"{os.path.basename(candidat)} ════", flush=True)
                courant = candidat
                pos = 0 if os.path.getsize(candidat) < 65536 else debut_de_fin(candidat, 40)
        if courant:
            pos = lire_suite(courant, pos)


def age_garde(dossier):
    """Pour collecte-tmux.sh etat : une ligne."""
    L = Lecture(dossier)
    if L.derniere is None:
        print(f"{VIDE} (garde.tsv absent ou vide dans {dossier})")
        return
    m = lire_minute(L.derniere["minute"])
    age = minutes_entre(m, L.t)
    print(f"dernière minute {L.derniere['minute']} ({L.derniere.get('etat', '?')}), il y a {duree(age)}"
          + (f" — GARDIEN MUET (plus de {MUET_MIN} min)" if age > MUET_MIN else ""))


USAGE = "Usage : suivi.sh [--une-fois | --boucle <secondes> | --journal] [--dossier <d>]"


def main(args):
    dossier = os.environ.get("GARDE_DOSSIER") or os.path.join(ACCUEIL, "journaux-hors-campagne", "garde")
    mode, periode = "une-fois", None
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--une-fois", "--journal", "--age-garde", "--pilotes"):
            mode = a[2:]
        elif a == "--boucle" and i + 1 < len(args):
            mode = "boucle"
            try:
                periode = float(args[i + 1])
            except ValueError:
                periode = -1
            if periode < 1:
                print(f"suivi : --boucle attend un nombre de secondes ≥ 1, pas « {args[i + 1]} »\n{USAGE}",
                      file=sys.stderr)
                return 2
            i += 1
        elif a == "--dossier" and i + 1 < len(args):
            dossier = args[i + 1]
            i += 1
        elif a in ("-h", "--help"):
            print(USAGE)
            return 0
        else:
            print(f"suivi : option inconnue « {a} »\n{USAGE}", file=sys.stderr)
            return 2
        i += 1
    dossier = os.path.expanduser(dossier)
    try:
        if mode == "une-fois":
            une_fois(dossier)
        elif mode == "boucle":
            boucle(dossier, periode)
        elif mode == "journal":
            suivre_journal()
        elif mode == "age-garde":
            age_garde(dossier)
        elif mode == "pilotes":
            try:
                trouves = pilotes(strict=True)
            except Exception as e:   # collecte-tmux.sh doit savoir que la recherche a échoué
                print(f"suivi : recherche du pilote impossible ({type(e).__name__}: {e})", file=sys.stderr)
                return 1
            for p in trouves:
                print(f"{p.get('nom') or '?'}\t{p['pid']}")
    except KeyboardInterrupt:
        return 0
    except BrokenPipeError:
        try:
            sys.stdout = open(os.devnull, "w")
        except OSError:
            pass
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
