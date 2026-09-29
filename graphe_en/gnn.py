"""
Le GNN : reconstruire le normal de chaque nœud par ses voisins, puis nommer la cause.

    ./.venv/bin/python gnn.py --verifier [--version v12|v1|v2|v3|u|u1|u2]
    ./.venv/bin/python gnn.py --validation [--graines n] [--epoques e] [--sans-temoins]
                              [--variantes a,b|toutes] [--repetition] [--version v12|v1|v2|v3|u|u1|u2]
    ./.venv/bin/python gnn.py --repetition [mêmes options]
    ./.venv/bin/python gnn.py --test [mêmes options]       refusé sans les étiquettes gnn-fige
                                                          et gnn-fige-2, pour toute version

Phase E. Écrit d'après notes/GNN_SPEC.md (§1 à §6, §8 et les amendements du §10),
jugé par juge.py avec les règles de fautifs.py, comme les témoins. Le banc de
pannes fabriquées (§7) est dans gnn_banc.py, qui importe ce fichier.

LES DONNÉES
  Les fenêtres des deux séries seules (fautifs.SERIES), lues par le juge. Le GNN
  reçoit toutes les fenêtres et ne garde que jeu == « apprentissage » hors des
  écartées : l'étape 1 n'apprend QUE sur les normales, l'étape 2 sur les pannes.
  La conversion est celle du graphe figé (export_pyg.convert, absents en masque,
  sans flèches inverses), avec scaler.json contrôlé par son sha256 contre
  graphe_fige.json de l'étiquette ; jamais recalé. Puis asinh (en entrée comme en
  cible) : en panne, certaines colonnes dépassent de 10² à 10³ fois l'écart-type de
  saine-09 ; asinh est monotone et sans plafond, donc ne crée pas d'égalités.
  memory_limit et cpu_quota sont du CONTEXTE : toujours en entrée, jamais masqués,
  jamais reconstruits, jamais notés. Ils distinguent les pods MySQL : c'est une
  quasi-identité, à dire au rapport. AUCUN nom (names, keys, hosts) n'entre dans
  le modèle : les noms ne servent qu'à écrire les clés de la réponse.

L'ÉTAPE 1 : le Reconstructeur, un R-GCN hétérogène (H = 32, 2 couches, ReLU,
  LayerNorm, moyenne des messages), un encodeur par sorte de nœud, les 5 relations
  du gel et leurs inverses ajoutées DANS le modèle, un canal d'arête φ_r sur chaque
  relation chiffrée (calls, queries, publishes, consumes ; partagé entre r et
  rev_r ; executes_on n'a pas de colonnes). La tâche : masquer un nœud ET toutes
  ses flèches entrantes, puis les reconstruire (Huber δ = 1 sur les valeurs, plus
  0,5 × BCE sur la présence de chaque colonne d'état). Adam 3e-3, wd 1e-4, 150
  époques, lots de 16 graphes, p = 0,15. Déterministe : graine × 1009 + rang (0 le
  modèle final, 1 à n les plis dans l'ordre trié des campagnes), un fil, algorithmes
  déterministes. Chaque campagne mise de côté à son tour (un pli) : ses normales
  sont notées par le modèle appris sans elle.

LA NOTE D'UNE FENÊTRE : un passage par nœud, en lot (N copies de la fenêtre, la
  copie i masque le nœud i et ses flèches entrantes). Résidus signés, puis écarts
  z = (résidu − médiane) / échelle robuste, médiane et échelle par (sorte,
  colonne) et par (relation, colonne), calculées sur les résidus tenus hors pli.
  Erreur d'un nœud : max |z| (absents compris) ; d'une flèche : max |z|.

LE POST-TRAITEMENT, écrit à la main (principe P du journal), en fonctions pures :
  B (le bout des flèches anormales, ε > κ_r) : B1 cible-max, B2 source-max,
    B3 deux-max, B4 cible-somme, B5 part ; t_v = max(r_v, e_v) ; ŝ_v = t_v / τ_k ;
  H (la remontée pods → machine, par le champ hosts) : H0 aucune, H1 somme à
    seuil (au moins deux pods anormaux), H2 concentrée ;
  V (l'explication par les dépendances) : V0 aucune, V1 héritage.
  CHOIX (CHOIX_VERSIONS, un par version) est fixé par le banc (gnn_banc.py), règle
  équilibrée de l'écart E-3 (§13 de la spécification).

LES TROIS VERSIONS DE L'ÉTAPE 1 (écart E-1, §11 de la spécification, fixées avant
  tout calcul ; VERSION, v1 par défaut) :
    v1 : ce qui précède (masque, asinh, calage par sorte) ;
    v2 : masque, SANS asinh, calage des résidus PAR IDENTITÉ (temoin_noeud.identite,
         médiane et échelle de temoin_noeud.echelles par (identité, colonne) sur les
         résidus tenus hors pli, plancher par sorte ; flèches : (relation, identité
         source, identité cible), plancher par relation) ; une identité sans normal
         retombe sur le calage par sorte ;
    v3 : v2, mais un auto-encodeur SANS masque : goulot de dimension 8 après la
         dernière couche, les décodeurs ne lisent que ce plongement ; une passe par
         fenêtre, perte sur tous les nœuds et toutes les flèches.
  En aucune version l'identité n'entre dans le modèle : elle ne cale que la sortie.
  La version entre dans la clé du cache et le nom des sorties, et s'imprime à côté
  de l'empreinte (qui reste le sha256 du §8, sans la version).

LE GNN COMBINÉ v12 (écart E-5, §15, écrit avant tout calcul ; VERSION par défaut) :
  deux exemplaires du même modèle, appris à part sur les mêmes normales et les
  mêmes graines (chacun a son cache, ses plis, son calage, son empreinte) :
    alarme      l'exemplaire v2 : son score de fenêtre sous SON choix (B2/H0/V1),
                son seuil propre et ses budgets (§4) ; la cause (prototypes du §5)
                sur ses profils d'écart ;
    classement  l'exemplaire v1 sous le CHOIX B5/H2/V0 (celui que §13 donne à v1).
  methodes() rend les quatre noms de decision_c (« GNN, sans exemples », « GNN, sans
  exemples, budget de la règle », « GNN, avec exemples », « GNN, avec exemples,
  budget de la règle » ; les deux derniers par gnn_exemples.py sur la même version),
  puis les variantes (sans exemples) ; empreintes() rend l'empreinte de chaque modèle
  (modèles finaux, plis, et les modèles « sans c ni c' » de l'avec exemples).

LA VARIANTE « GNN UNIQUE » u (§17, écrite avant tout calcul et avant tout regard sur
  la première ouverture) : UN exemplaire, celui de v2 (masque, sans asinh, mêmes
  normales, mêmes graines : c'est le modèle même de l'alarme de v12, mêmes caches,
  mêmes empreintes) ; ses résidus sont calés deux fois :
    alarme      par identité, exactement comme v12 (même exemplaire, même choix
                B2/H0/V1, mêmes seuils et budgets) ;
    classement  PAR SORTE (Calage(..., par_identite=False) : médiane et échelle par
                (sorte, colonne) et (relation, colonne), comme la version 1, sur les
                MÊMES résidus tenus hors pli), sous le CHOIX B5/H2/V0 (celui de
                l'exemplaire v1 de v12). L'exemplaire ainsi calé s'appelle « v2:sorte »
                (Etape1.par_sorte, classe ParSorte) : rien n'y est appris.
  Les noms rendus par methodes() sont ceux de v12 avec « GNN unique » au lieu de
  « GNN » en tête (prefixe, noms_decision) : « GNN unique, sans exemples », « GNN
  unique, sans exemples, budget de la règle », « GNN unique, avec exemples », « GNN
  unique, avec exemples, budget de la règle », puis « GNN unique sans aucune
  arête »… ; decision_c --variante u les attend (decision_c.noms_gnn). Les versions
  v1, v2, v3, v12 gardent « GNN ».

LA SECONDE VARIANTE « GNN UNIQUE » u1 (§18, symétrique de u, écrite avant tout calcul
  de u1 et avant tout regard sur la première ouverture) : UN exemplaire, celui de v1
  (masque, asinh, mêmes normales, mêmes graines : c'est le modèle même du classement de
  v12, mêmes caches, mêmes empreintes) ; ses résidus sont calés deux fois :
    alarme      PAR IDENTITÉ (Calage(..., par_identite=True) : exactement la méthode de
                v2, temoin_noeud.identite et temoin_noeud.echelles, plancher par sorte,
                repli par sorte pour une identité sans normal, sur les MÊMES résidus
                tenus hors pli), sous le choix de l'alarme de v12 (B2/H0/V1), seuils et
                budgets calculés comme ceux de v12. L'exemplaire ainsi calé s'appelle
                « v1:identite » (Etape1.recale, classe ParIdentite) : rien n'y est appris ;
    classement  par sorte, sous B5/H2/V0 : l'exemplaire v1 de v12 lui-même, le classement
                même de v12.
  Noms : « GNN unique u1, sans exemples »… (decision_c --variante u1).

LA DERNIÈRE VARIANTE « GNN UNIQUE » u2 (§19, double entrée, écrite avant tout calcul de u2, avant
  tout chiffre de u1 et avant tout regard sur la première ouverture) : UN réseau, UN entraînement,
  le modèle « double » (VERSIONS ; il ne se choisit pas seul par --version) :
    entrée      chaque colonne chiffrée (état, contexte, flèche) DEUX fois, telle quelle (comme v2)
                puis en asinh (comme v1), bout à bout (convertir(..., DEUX_ECHELLES)) ; les bits de
                présence et le drapeau de masque une seule fois ;
    sortie      deux têtes de reconstruction, les mêmes décodeurs dupliqués (dec, dec_e : la tête
                brute ; dec_asinh, dec_e_asinh : la tête asinh), sur le même plongement ;
    perte       ½ (L_v2 + L_v1) : chacune la perte complète de sa version (Huber, 0,5 × BCE de
                présence, flèches ; moyennes par sorte et par relation) sur SA tête et SA cible ;
    le reste    même architecture, même masque, mêmes normales, mêmes graines, mêmes
                hyperparamètres, même déterminisme, même empreinte (§8).
  Ses deux têtes sont deux exemplaires (VueTete : les poids du réseau, la sortie et la cible
  d'une tête ; classes TeteBrute et TeteAsinh : rien n'y est appris) :
    alarme      « double:brute » : les résidus de la tête brute, calés PAR IDENTITÉ (la méthode de
                v2), sous le choix de l'alarme de v12 (B2/H0/V1), seuils et budgets comme v12 ;
    classement  « double:asinh » : les résidus de la tête asinh, calés PAR SORTE (la méthode de
                v1), sous B5/H2/V0 (le classement de v12).
  B/H/V sont fixés (aucun réglage nouveau) ; le banc rapporte la grille sans choisir.
  Noms : « GNN unique u2, sans exemples »… (decision_c --variante u2).

LES PROCESSUS : GNN_PROCESSUS (variable d'environnement, défaut 4) fixe le nombre
  d'entraînements en parallèle (PROCESSUS), pour gnn.py, gnn_exemples.py, gnn_banc.py
  et decision_c.py. Sans effet sur les résultats : chaque tâche a son germe (graine ×
  1009 + rang), un fil, et les états reviennent dans l'ordre des tâches (T18).

L'ALARME : le plus haut score de nœud de la fenêtre, celui qui sert au classement.
  Seuil propre : 95e centile des scores des normales tenues hors pli ; face à une
  autre méthode, son budget (BUDGETS, sur 249 minutes, mis à l'échelle si N ≠ 249).

L'ÉTAPE 2 : les profils d'écart signés du modèle final (sans identité), les
  prototypes du témoin 2 (temoin_noeud.Prototypes, importés sans modification),
  le rejet calé en mettant chaque injection de côté (95e centile des distances des
  fenêtres bien classées). « avec exemples » : la cause du prototype le plus proche
  quand l'alarme sonne, « inconnue » au-delà du rejet ; « sans exemples » :
  « inconnue » si l'alarme sonne. Le classement et l'alarme viennent toujours de
  l'étape 1 : les deux réglages ne diffèrent que par la cause.

LE SCELLÉ : juge.lire n'est appelé qu'avec fautifs.SERIES ; --validation et
  --repetition ne lisent que juge.validation (jamais « hors ») ; --test est refusé
  tant que l'étiquette gnn-fige n'existe pas, puis, pour TOUTE version, tant que
  l'étiquette gnn-fige-2 n'est pas bien posée : après gnn-fige, portant les empreintes
  d'UNE variante unique (graphe_en/gnn-empreintes-<u|u1|u2>.txt ; pour u, u1 et u2,
  celles de cette variante), avec le scellé de decision_c (scelle_2_mal_pose) et le
  même contrôle ici (entre gnn-fige et gnn-fige-2, graphe_en/ ne change que dans
  PERMIS_SCELLE_2 et les empreintes des variantes uniques), graphe_en/ inchangé
  depuis gnn-fige-2 et aucun .py non suivi. Pourquoi toute version : l'alarme de v12
  est celle de u, son classement celui de u1, et v1, v2 sont leurs modèles mêmes ; le
  vrai test de v12 (la première ouverture) n'est regardé qu'après gnn-fige-2 (§17,
  §18, §19.3). Si v12 est retenue (§19.2), elle a déjà été lue avec le code de gnn-fige :
  ce code-ci ne la relit pas.

Options :
  --verifier             les contrôles T1 à T4, T6, T7 de la spécification, T12
                         (le calage de la sortie), T13 (l'empreinte), T15 (les
                         empreintes de tous les modèles), T16 (les noms de
                         decision_c), T18 (le nombre de processus ne change rien)
                         et, pour v12, T14 (alarme = v2, classement = v1 B5/H2/V0),
                         pour u, T17 (alarme = celle de v12, classement = résidus v2
                         calés par sorte, noms, un seul exemplaire, déterminisme),
                         pour u1, T19 (classement = celui de v12, alarme = résidus v1
                         calés par identité sous B2/H0/V1, noms, un seul exemplaire,
                         déterminisme), pour u2, T20 (formes de l'entrée et des têtes,
                         perte = ½ (L_v2 + L_v1) recalculée à la main, déterminisme en
                         1 et 3 processus, chaque tête lit son échelle, alarme = tête
                         brute par identité, classement = tête asinh par sorte, un seul
                         réseau, noms), sur 20 fenêtres de validation et 2 époques
  --validation           le tableau de bord sur juge.validation ; écrit
                         <campagnes>/gnn-validation.txt
  --repetition           la répétition « panne jamais vue », dans la validation
  --test                 le vrai test : refusé sans les étiquettes gnn-fige et
                         gnn-fige-2 (LE SCELLÉ)
  --graines <n>          graines 0 à n−1 (défaut 5)
  --epoques <e>          époques d'apprentissage (défaut 150)
  --sans-temoins         ne recalcule pas les témoins (seulement « a priori »)
  --variantes <liste>    variantes en plus du complet, séparées par des virgules,
                         ou « toutes »
  --version <v>          v12 (défaut, le GNN combiné), v1, v2, v3, u (le GNN
                         unique, §17), u1 (§18) ou u2 (§19) ; les sorties d'une version
                         autre que v1 portent son nom (gnn-validation-v12.txt, -u.txt,
                         -u1.txt, -u2.txt)
  --campaigns <dossier>  le dossier des dossiers de campagne (défaut ../campagnes)
  --runs <dossier>       où sont les runs (défaut runs)
  --help                 ce texte

Code de sortie 0 ; 1 si une campagne est refusée, un contrôle échoue ou le scellé
est fermé ; 2 sur un mauvais argument.
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import math
import multiprocessing
import os
import random
import statistics
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from torch import nn

import export_pyg
import fautifs as fautifs_module
import gel
import juge
import temoin_noeud as tn

HERE = Path(__file__).resolve().parent
ETIQUETTE_SCELLE = "gnn-fige"
ETIQUETTE_SCELLE_2 = "gnn-fige-2"      # le gel de la variante unique (u, u1 ou u2, §17 à §19), après gnn-fige
# Ce qui peut changer dans graphe_en/ entre gnn-fige et gnn-fige-2, en plus des gnn-empreintes-<u|u1|u2>.txt :
# le même tuple que decision_c.PERMIS_SCELLE_2 (raisons_scelle_2 fait les contrôles de code de decision_c).
PERMIS_SCELLE_2 = ("gnn.py", "gnn_exemples.py", "gnn_banc.py", "decision_c.py")
SORTES = ("instance", "queue", "host")
# (source, cible) de chaque relation du gel, dans l'ordre d'edges.RELATIONS.
RELATIONS = {r: (s, d) for r, (s, d, _) in export_pyg.RELATIONS.items()}
CHIFFREES = tuple(r for r, (_, _, c) in export_pyg.RELATIONS.items() if c)
APPELS = ("calls", "queries")
CONTEXTE = {"instance": ("memory_limit", "cpu_quota"), "queue": (), "host": ()}
ABSENTS = tn.ABSENTS

# L'étape 1 (spécification §2.1-2.2), valeurs figées, sans recherche.
H = 32
COUCHES = 2
P_MASQUE = 0.15
HUBER = 1.0
POIDS_PRESENCE = 0.5
LR = 3e-3
WD = 1e-4
EPOQUES = 150
LOT = 16


def _processus_de_l_environnement(defaut: int = 4) -> int:
    """GNN_PROCESSUS, le nombre d'entraînements en parallèle ; `defaut` sans la variable.
    Sans effet sur les résultats (T18) : seul le temps change."""
    brut = os.environ.get("GNN_PROCESSUS", "").strip()
    if not brut:
        return defaut
    if not brut.isdigit() or int(brut) < 1:
        raise ValueError(f"GNN_PROCESSUS={brut!r} : un entier au moins égal à 1 est attendu")
    return int(brut)


PROCESSUS = _processus_de_l_environnement()   # défaut 4 : au plus 4 entraînements en parallèle sur vms0 : 6 processus avec le principal et le suivi des ressources de multiprocessing (spawn)
CENTILE = 95

# Les budgets de fausses alertes des témoins, sur 249 minutes normales mises de
# côté (journal 1165-1169) ; les versions « machine » gardent celui de la règle.
BUDGETS = {"tableau": 13, "score par nœud, sans": 13, "score par nœud, avec": 25, "règle": 21}
MINUTES_BUDGET = 249

# La grille du post-traitement (§3.5), dans l'ordre de simplicité.
BOUTS = ("B1", "B2", "B3", "B4", "B5")
REMONTEES = ("H0", "H1", "H2")
EXPLICATIONS = ("V0", "V1")
# Le résultat du banc de gnn_banc.py, codé en dur : chaque version a le sien, fixé
# par SON banc (§11), validation seule, graines 0 à 4, 150 époques, selon la règle
# ÉQUILIBRÉE de l'écart E-3 (§13 : le plus grand min(F_C, F_D, F_R), qui remplace le
# critère 3 du §3.5 ; l'ancien choix était v1 B5/H1/V1, v2 et v3 B2/H0/V1).
# Aucune version n'atteint min(F_C, F_D, F_R) ≥ 0,5 (v1 0,054 ; v2 0,000 ; v3 0,020) :
# selon le §13, aucune n'est figée ; ces CHOIX ne servent qu'à la mesure.
# CHOIX est celui de la version 1. CHOIX_SOURCES dit d'où vient chacun.
CHOIX = {"bout": "B5", "remontee": "H2", "explication": "V0"}
CHOIX_VERSIONS = {"v1": CHOIX,
                  "v2": {"bout": "B2", "remontee": "H0", "explication": "V1"},
                  "v3": {"bout": "B2", "remontee": "H0", "explication": "V1"}}
MIN_FAMILLES = {"v1": 0.054, "v2": 0.000, "v3": 0.020}     # min(F_C, F_D, F_R) du CHOIX, lu au banc
CHOIX_SOURCES = {v: f"fixé par campagnes/{'gnn-banc-validation.txt' if v == 'v1' else f'gnn-banc-validation-{v}.txt'}"
                    f", 5 graines, 150 époques, règle de l'écart E-3 (§13) ; min(F_C, F_D, F_R) "
                    f"{MIN_FAMILLES[v]:.3f} < 0,5 : NON FIGÉ" for v in ("v1", "v2", "v3")}

# Les trois versions de l'étape 1 (écart E-1, §11 de la spécification, fixées avant
# tout calcul) : masque (reconstruire un nœud masqué par ses voisins) ou
# auto-encodeur sans masque à goulot ; asinh sur les nombres ou non ; calage des
# résidus par sorte ou par identité (temoin_noeud.identite). L'identité ne sert
# qu'à caler la SORTIE, jamais en entrée du modèle, en aucune version.
# Le modèle de la variante u2 (§19), « double » : le masque, chaque colonne chiffrée DEUX fois en
# entrée (brute puis asinh : convertir(..., DEUX_ECHELLES)), deux têtes de reconstruction (TETES,
# dans l'ordre des échelles) ; il n'a pas de calage à lui : chacune de ses têtes a le sien (TeteBrute
# par identité, TeteAsinh par sorte). Il ne se choisit pas seul (TOUTES_VERSIONS) : c'est le modèle de u2.
DOUBLE = "double"
DEUX_ECHELLES = "brute+asinh"          # la valeur « asinh » du modèle double : les deux échelles, bout à bout
TETES = ("brute", "asinh")             # ses têtes, dans l'ordre des échelles de l'entrée
VERSIONS = {"v1": {"masque": True, "asinh": True, "identite": False},
            "v2": {"masque": True, "asinh": False, "identite": True},
            "v3": {"masque": False, "asinh": False, "identite": True},
            DOUBLE: {"masque": True, "asinh": DEUX_ECHELLES, "identite": None, "tetes": TETES}}
GOULOT = 8               # v3 : la dimension du plongement final, lu seul par les décodeurs
# Le GNN combiné (écart E-5, §15 de la spécification, écrit avant tout calcul) : deux
# exemplaires du même modèle, appris à part sur les mêmes normales et les mêmes graines,
# chacun dans sa version ; l'ALARME est celle de l'exemplaire v2 (son score de fenêtre
# sous SON choix B/H/V, son seuil propre et ses budgets, §4), le CLASSEMENT celui de
# l'exemplaire v1 sous le CHOIX B5/H2/V0 que §13 donne à v1. Aucune identité n'entre
# dans aucun des deux modèles. C'est la version par défaut.
COMBINEES = {"v12": {"alarme": "v2", "classement": "v1"}}
# La variante « GNN unique » (§17, écrite avant tout calcul et avant tout regard sur la
# première ouverture) : UN exemplaire, celui de v2 ; ses résidus calés par identité font
# l'alarme (exactement celle de v12), les mêmes résidus calés PAR SORTE font le classement
# sous B5/H2/V0 (le choix de l'exemplaire v1 de v12). L'exemplaire calé par sorte porte le
# nom « v2:sorte » (PAR_SORTE) : le même modèle, un autre calage de la sortie.
# La seconde variante « GNN unique » u1 (§18, symétrique de u) : UN exemplaire, celui de v1 ;
# ses résidus calés PAR IDENTITÉ (la méthode de v2, plancher et repli par sorte compris)
# font l'alarme, sous le choix de l'alarme de v12 (B2/H0/V1) ; les mêmes résidus calés par
# sorte font le classement sous B5/H2/V0 : exactement le classement de v12. L'exemplaire
# calé par identité porte le nom « v1:identite » (PAR_IDENTITE).
# La dernière variante « GNN unique » u2 (§19, double entrée) : UN réseau, le modèle « double » ; sa
# tête brute, ses résidus calés PAR IDENTITÉ (la méthode de v2), fait l'alarme sous le choix de
# l'alarme de v12 (B2/H0/V1) : l'exemplaire « double:brute » (TETE_BRUTE) ; sa tête asinh, ses résidus
# calés PAR SORTE (la méthode de v1), fait le classement sous B5/H2/V0 : « double:asinh » (TETE_ASINH).
# Le banc rapporte la grille sans choisir (banc_sans_choix).
PAR_SORTE = ":sorte"
PAR_IDENTITE = ":identite"
TETE_BRUTE = ":" + TETES[0]
TETE_ASINH = ":" + TETES[1]
RECALAGES = {PAR_SORTE: False, PAR_IDENTITE: True,     # suffixe d'un exemplaire recalé -> calage par identité
             TETE_BRUTE: True, TETE_ASINH: False}      # u2 : une tête du réseau double -> son calage
UNIQUES = {"u": {"modele": "v2", "alarme": "v2", "classement": "v2" + PAR_SORTE, "section": "§17"},
           "u1": {"modele": "v1", "alarme": "v1" + PAR_IDENTITE, "classement": "v1", "section": "§18"},
           "u2": {"modele": DOUBLE, "alarme": DOUBLE + TETE_BRUTE, "classement": DOUBLE + TETE_ASINH, "section": "§19",
                  "role": "tête brute par identité pour l'alarme, tête asinh par sorte pour le classement",
                  "banc_sans_choix": True}}
TOUTES_VERSIONS = tuple(v for v in VERSIONS if not VERSIONS[v].get("tetes")) + tuple(COMBINEES) + tuple(UNIQUES)
VERSION = "v12"
# Ce qui travaille sur UN modèle (Reconstructeur, entrainer, charger, Calage, Etape1,
# etape1) prend une version de VERSIONS, jamais une combinée ; v1 par défaut, comme avant v12.
MODELE_DEFAUT = "v1"
CHOIX_VERSIONS["v12"] = CHOIX_VERSIONS[COMBINEES["v12"]["classement"]]
CHOIX_SOURCES["v12"] = ("celui de l'exemplaire v1 (§15 : B5/H2/V0, fixé par campagnes/gnn-banc-validation.txt, "
                        "5 graines, 150 époques) ; l'alarme vient de l'exemplaire v2 sous son propre choix "
                        f"{'/'.join(CHOIX_VERSIONS['v2'].values())}")
CHOIX_VERSIONS["u"] = CHOIX_VERSIONS[COMBINEES["v12"]["classement"]]
CHOIX_SOURCES["u"] = ("celui de l'exemplaire v1 de v12 (§17 : B5/H2/V0, fixé par campagnes/gnn-banc-validation.txt), "
                      "appliqué aux résidus de l'exemplaire v2 calés PAR SORTE ; l'alarme vient du même exemplaire "
                      f"calé par identité, sous son propre choix {'/'.join(CHOIX_VERSIONS['v2'].values())}")
CHOIX_VERSIONS["u1"] = CHOIX_VERSIONS[COMBINEES["v12"]["classement"]]
CHOIX_SOURCES["u1"] = ("celui de l'exemplaire v1 de v12 (§18 : B5/H2/V0, fixé par campagnes/gnn-banc-validation.txt) : "
                       "le même exemplaire, le classement même de v12 ; l'alarme vient de ce modèle calé PAR IDENTITÉ, "
                       f"sous le choix de l'alarme de v12 {'/'.join(CHOIX_VERSIONS['v2'].values())}")
CHOIX_VERSIONS["u2"] = CHOIX_VERSIONS[COMBINEES["v12"]["classement"]]
CHOIX_SOURCES["u2"] = ("celui du classement de v12 (§19 : B5/H2/V0, fixé par campagnes/gnn-banc-validation.txt), "
                       "appliqué aux résidus de la tête asinh du réseau double calés PAR SORTE ; l'alarme vient de sa "
                       f"tête brute calée PAR IDENTITÉ, sous le choix de l'alarme de v12 "
                       f"{'/'.join(CHOIX_VERSIONS['v2'].values())} ; B/H/V fixés, le banc ne choisit pas")
# Le début des noms que rend methodes() (decision_c) : « GNN » sauf pour une variante (§17, §18, §19).
PREFIXES = {"u": "GNN unique", "u1": "GNN unique u1", "u2": "GNN unique u2"}


def exemplaires(version: str) -> tuple[str, str]:
    """(exemplaire de l'ALARME, exemplaire du CLASSEMENT) : les deux sont la même version
    pour v1, v2, v3 ; v12 : (v2, v1) ; u (§17) : (v2, v2:sorte), le même modèle calé
    deux fois ; u1 (§18) : (v1:identite, v1), de même ; u2 (§19) : (double:brute,
    double:asinh), les deux têtes du même réseau."""
    if version in COMBINEES:
        return COMBINEES[version]["alarme"], COMBINEES[version]["classement"]
    if version in UNIQUES:
        return UNIQUES[version]["alarme"], UNIQUES[version]["classement"]
    if version in VERSIONS:
        return version, version
    raise ValueError(f"version inconnue : {version}")


def modele_de(exemplaire: str) -> str:
    """La version du modèle appris d'un exemplaire (« v2:sorte » → « v2 », « v1:identite » → « v1 »,
    « double:brute » → « double »)."""
    for suffixe in RECALAGES:
        if exemplaire.endswith(suffixe):
            return exemplaire[:-len(suffixe)]
    return exemplaire


def par_identite(exemplaire: str) -> bool:
    """Les résidus de cet exemplaire sont-ils calés par identité ? Ceux de sa version (v2, v3),
    ou ceux de son recalage (« :identite » oui, « :sorte » non), ou ceux de sa tête (u2 :
    « :brute » oui, « :asinh » non)."""
    for suffixe, oui in RECALAGES.items():
        if exemplaire.endswith(suffixe):
            return oui
    if VERSIONS[exemplaire]["identite"] is None:     # le réseau double (u2, §19) : seules ses têtes ont un calage
        raise ValueError(f"{exemplaire} : le réseau à deux têtes (u2, §19) n'a pas de calage à lui ; nommer sa tête "
                         f"({exemplaire}{TETE_BRUTE} par identité, {exemplaire}{TETE_ASINH} par sorte)")
    return VERSIONS[exemplaire]["identite"]


def choix_exemplaire(exemplaire: str) -> dict:
    """Le CHOIX B/H/V sous lequel un exemplaire note par défaut : celui de sa version ; un
    exemplaire recalé par sorte (u, §17) : B5/H2/V0, celui de l'exemplaire v1 de v12 ; recalé
    par identité (u1, §18) : B2/H0/V1, celui de l'alarme de v12 (l'exemplaire v2) ; la tête
    brute de u2 (§19) : B2/H0/V1 ; sa tête asinh : B5/H2/V0."""
    if exemplaire in CHOIX_VERSIONS:
        return CHOIX_VERSIONS[exemplaire]
    if exemplaire.endswith(PAR_SORTE):
        return CHOIX_VERSIONS[COMBINEES["v12"]["classement"]]
    if exemplaire.endswith(PAR_IDENTITE):
        return CHOIX_VERSIONS[COMBINEES["v12"]["alarme"]]
    if exemplaire.endswith(TETE_BRUTE):          # u2 (§19) : la tête brute fait l'alarme, comme l'alarme de v12
        return CHOIX_VERSIONS[COMBINEES["v12"]["alarme"]]
    if exemplaire.endswith(TETE_ASINH):          # u2 (§19) : la tête asinh fait le classement, comme celui de v12
        return CHOIX_VERSIONS[COMBINEES["v12"]["classement"]]
    raise ValueError(f"exemplaire inconnu : {exemplaire}")


def modeles_de(version: str) -> tuple[str, ...]:
    """Les versions de modèle à apprendre pour une version (une ; deux pour v12 ; une pour u, u1 et u2)."""
    return tuple(dict.fromkeys(modele_de(e) for e in exemplaires(version)))


def prefixe(version: str) -> str:
    """Le début des noms de methodes() : « GNN », ou « GNN unique » pour u (§17), « GNN
    unique u1 » pour u1 (§18), « GNN unique u2 » pour u2 (§19)."""
    return PREFIXES.get(version, "GNN")


def decrire(version: str) -> str:
    """Une ligne qui dit ce qu'est la version."""
    def un(v: str) -> str:
        cfg = VERSIONS[v]
        if cfg.get("tetes"):
            return ("masque, chaque colonne chiffrée deux fois en entrée (brute et asinh), deux têtes de "
                    "reconstruction, perte ½ (L_v2 + L_v1)")
        return (f"{'masque' if cfg['masque'] else f'auto-encodeur sans masque, goulot {GOULOT}'}, "
                f"{'asinh' if cfg['asinh'] else 'sans asinh'}, calage {'par identité' if cfg['identite'] else 'par sorte'}")
    if version in COMBINEES:
        va, vc = exemplaires(version)
        return (f"GNN combiné (écart E-5, §15) : alarme = exemplaire {va} ({un(va)}, choix "
                f"{'/'.join(CHOIX_VERSIONS[va].values())}) ; classement = exemplaire {vc} ({un(vc)}, choix "
                f"{'/'.join(CHOIX_VERSIONS[version].values())}) ; mêmes normales, mêmes graines")
    if version in UNIQUES and VERSIONS[UNIQUES[version]["modele"]].get("tetes"):
        va, vc = exemplaires(version)
        return (f"GNN unique u2 ({UNIQUES[version]['section']}) : UN réseau {UNIQUES[version]['modele']} "
                f"({un(UNIQUES[version]['modele'])}) ; alarme = sa tête brute ({va}), résidus calés PAR IDENTITÉ, "
                f"choix {'/'.join(choix_exemplaire(va).values())} (celui de l'alarme de v12) ; classement = sa tête "
                f"asinh ({vc}), résidus calés PAR SORTE, choix {'/'.join(CHOIX_VERSIONS[version].values())} (celui du "
                f"classement de v12) ; un seul entraînement")
    if version in UNIQUES and exemplaires(version)[1].endswith(PAR_SORTE):
        va, vc = exemplaires(version)
        return (f"GNN unique (§17) : UN exemplaire {va} ({un(va)}) ; alarme = ses résidus calés par identité, choix "
                f"{'/'.join(CHOIX_VERSIONS[va].values())} (celle de v12) ; classement = les mêmes résidus calés PAR "
                f"SORTE ({vc}), choix {'/'.join(CHOIX_VERSIONS[version].values())} ; aucun modèle de plus")
    if version in UNIQUES:
        va, vc = exemplaires(version)
        return (f"GNN unique u1 ({UNIQUES[version]['section']}) : UN exemplaire {vc} ({un(vc)}) ; alarme = ses "
                f"résidus calés PAR IDENTITÉ ({va}, la méthode de v2), choix {'/'.join(choix_exemplaire(va).values())} "
                f"(celui de l'alarme de v12) ; classement = les mêmes résidus calés par sorte, choix "
                f"{'/'.join(CHOIX_VERSIONS[version].values())} (le classement de v12) ; aucun modèle de plus")
    return un(version)

# Les variantes du retrait des flèches (§6) : relations du passage de messages,
# canal d'arête, un seul W lié, flèches notées, relations lues par V (H2 lit toujours
# calls et queries de la fenêtre, comme le complet).
TOUTES = frozenset(RELATIONS)


def _variante(relations, canal=True, lie=False, notees=None, deps=None) -> dict:
    relations = frozenset(relations)
    return {"relations": relations, "canal": canal, "lie": lie,
            "notees": frozenset(CHIFFREES) & relations if notees is None else frozenset(notees),
            "deps": relations if deps is None else frozenset(deps)}


VARIANTES = {
    "complet": _variante(TOUTES),
    "sans aucune arête": _variante((), canal=False, notees=(), deps=()),
    "sans queries": _variante(TOUTES - {"queries"}),
    "sans calls": _variante(TOUTES - {"calls"}),
    "sans publishes": _variante(TOUTES - {"publishes"}),
    "sans consumes": _variante(TOUTES - {"consumes"}),
    "sans executes_on": _variante(TOUTES - {"executes_on"}, deps=TOUTES),
    "sans canal d'arête": _variante(TOUTES, canal=False, notees=()),
    "un seul type sans canal": _variante(TOUTES, canal=False, lie=True, notees=()),
}


# ------------------------------------------------------------------------------
# L'échelle figée et la conversion
# ------------------------------------------------------------------------------
_ECHELLE: dict | None = None
_GRAPHES: dict[tuple, tuple[dict, "Graphe"]] = {}


def charger_echelle(fige: dict) -> dict:
    """scaler.json, refusé si son sha256 n'est pas celui du graphe figé. Jamais recalé."""
    global _ECHELLE
    brut = (HERE / "scaler.json").read_bytes()
    empreinte = hashlib.sha256(brut).hexdigest()
    if empreinte != fige["echelle"]["sha256"]:
        raise juge.Refus(f"scaler.json : sha256 {empreinte[:12]}…, le gel attend "
                         f"{fige['echelle']['sha256'][:12]}… : ce n'est pas l'échelle figée")
    _ECHELLE = json.loads(brut)["scaler"]
    return _ECHELLE


def _echelle() -> dict:
    if _ECHELLE is None:
        fige, ecarts, _ = gel.reference()
        if ecarts:
            raise juge.Refus(ecarts[0])
        charger_echelle(fige)
    return _ECHELLE


@dataclass
class Graphe:
    """Une fenêtre en tenseurs, SANS aucun nom : ce que voit le modèle."""
    x: dict          # sorte -> [n, d_état] asinh, un absent vaut 0
    p: dict          # sorte -> [n, d_état] présence (0 ou 1)
    ctx: dict        # sorte -> [n, d_ctx] asinh (memory_limit, cpu_quota)
    ei: dict         # relation -> [2, E] indices dans les lignes de chaque sorte
    ea: dict         # relation -> [E, d_r] asinh
    n: dict          # sorte -> nombre de nœuds


def convertir(donnees: dict, asinh: bool | str = True) -> Graphe:
    """La conversion du graphe figé (export_pyg), puis asinh (version 1 ; pas en
    versions 2 et 3), contexte à part. Gardée en mémoire par objet : `donnees` est
    partagé par les copies de juge.validation. `asinh` = DEUX_ECHELLES (u2, §19) : les
    deux échelles bout à bout (convertir_double)."""
    if asinh == DEUX_ECHELLES:
        return convertir_double(donnees)
    cle = (id(donnees), asinh)
    if cle in _GRAPHES and _GRAPHES[cle][0] is donnees:
        return _GRAPHES[cle][1]
    h = export_pyg.convert([donnees], _echelle(), "mask", False, "cpu")[0]
    f = torch.asinh if asinh else torch.clone
    x, p, ctx, n = {}, {}, {}, {}
    for k in SORTES:
        cols = list(h[k].columns)
        etat = [i for i, c in enumerate(cols) if c not in CONTEXTE[k]]
        contexte = [i for i, c in enumerate(cols) if c in CONTEXTE[k]]
        x[k] = f(h[k].x[:, etat]).contiguous()
        p[k] = h[k].present[:, etat].float().contiguous()
        ctx[k] = f(h[k].x[:, contexte]).contiguous()
        n[k] = int(h[k].num_nodes)
    ei, ea = {}, {}
    for r, (s, d) in RELATIONS.items():
        ei[r] = h[s, r, d].edge_index.contiguous()
        ea[r] = f(h[s, r, d].edge_attr).contiguous()
    g = Graphe(x, p, ctx, ei, ea, n)
    _GRAPHES[cle] = (donnees, g)
    return g


def convertir_double(donnees: dict) -> Graphe:
    """u2 (§19) : l'entrée du réseau à deux échelles. Chaque colonne chiffrée deux fois, bout à
    bout : telle quelle (convertir sans asinh, comme v2), puis en asinh (convertir avec, comme v1),
    pour l'état (x), le contexte (ctx) et les flèches (ea) ; la présence (p), les flèches (ei) et
    les nombres de nœuds une seule fois. Gardée en mémoire comme convertir."""
    cle = (id(donnees), DEUX_ECHELLES)
    if cle in _GRAPHES and _GRAPHES[cle][0] is donnees:
        return _GRAPHES[cle][1]
    b, a = convertir(donnees, False), convertir(donnees, True)
    g = Graphe({k: torch.cat([b.x[k], a.x[k]], 1) for k in SORTES}, b.p,
               {k: torch.cat([b.ctx[k], a.ctx[k]], 1) for k in SORTES}, b.ei,
               {r: torch.cat([b.ea[r], a.ea[r]], 1) for r in RELATIONS}, dict(b.n))
    _GRAPHES[cle] = (donnees, g)
    return g


def cible(g: Graphe, tete: str, dims: dict) -> Graphe:
    """u2 (§19) : ce que reconstruit la tête `tete` (TETES), pris dans l'entrée à deux échelles :
    les colonnes d'état, de contexte et des flèches de SON échelle ; la présence et les flèches
    telles quelles. Rien n'est copié (des vues des tenseurs)."""
    i = TETES.index(tete)
    de, dc, dr = dims["etat"], dims["ctx"], dims["rel"]
    return Graphe({k: g.x[k][:, i * de[k]:(i + 1) * de[k]] for k in SORTES}, g.p,
                  {k: g.ctx[k][:, i * dc[k]:(i + 1) * dc[k]] for k in SORTES}, g.ei,
                  {r: g.ea[r][:, i * dr[r]:(i + 1) * dr[r]] for r in RELATIONS}, g.n)


def dimensions(fige: dict) -> dict:
    """Les largeurs d'entrée, lues dans le graphe figé."""
    return {"etat": {k: sum(1 for c in fige["noeuds"][k] if c not in CONTEXTE[k]) for k in SORTES},
            "ctx": {k: sum(1 for c in fige["noeuds"][k] if c in CONTEXTE[k]) for k in SORTES},
            "rel": {r: len(fige["relations"][r]["colonnes"]) for r in RELATIONS}}


def assembler(graphes: list[Graphe]) -> Graphe:
    """Un lot : les fenêtres mises bout à bout, indices des flèches décalés."""
    decal = dict.fromkeys(SORTES, 0)
    ei = {r: [] for r in RELATIONS}
    for g in graphes:
        for r, (s, d) in RELATIONS.items():
            ei[r].append(g.ei[r] + torch.tensor([[decal[s]], [decal[d]]]))
        for k in SORTES:
            decal[k] += g.n[k]
    return Graphe({k: torch.cat([g.x[k] for g in graphes]) for k in SORTES},
                  {k: torch.cat([g.p[k] for g in graphes]) for k in SORTES},
                  {k: torch.cat([g.ctx[k] for g in graphes]) for k in SORTES},
                  {r: torch.cat(ei[r], 1) for r in RELATIONS},
                  {r: torch.cat([g.ea[r] for g in graphes]) for r in RELATIONS},
                  decal)


def _copies(g: Graphe, n: int) -> Graphe:
    """N copies de la même fenêtre, en un lot."""
    ei = {}
    for r, (s, d) in RELATIONS.items():
        e = g.ei[r].shape[1]
        o = torch.arange(n).repeat_interleave(e)
        ei[r] = g.ei[r].repeat(1, n) + torch.stack([o * g.n[s], o * g.n[d]])
    return Graphe({k: g.x[k].repeat(n, 1) for k in SORTES}, {k: g.p[k].repeat(n, 1) for k in SORTES},
                  {k: g.ctx[k].repeat(n, 1) for k in SORTES}, ei,
                  {r: g.ea[r].repeat(n, 1) for r in RELATIONS}, {k: g.n[k] * n for k in SORTES})


# ------------------------------------------------------------------------------
# Le modèle
# ------------------------------------------------------------------------------
def _moyenne(msg: torch.Tensor, idx: torch.Tensor, n: int) -> torch.Tensor:
    """La moyenne des messages reçus par chaque nœud (0 sans message) ; index_add, déterministe."""
    somme = msg.new_zeros(n, msg.shape[1]).index_add_(0, idx, msg)
    compte = msg.new_zeros(n).index_add_(0, idx, torch.ones(idx.shape[0], dtype=msg.dtype))
    return somme / compte.clamp(min=1.0).unsqueeze(1)


class Reconstructeur(nn.Module):
    """
    R-GCN hétérogène : un encodeur par sorte, des poids par relation (directe ou
    inverse), partagés par tous les nœuds d'une sorte et toutes les flèches d'une
    relation ; un canal d'arête φ_r par relation chiffrée, partagé entre r et rev_r.
    Entrée d'un nœud : [asinh(état)·(1−m), présence·(1−m), asinh(contexte), m].
    Entrée d'une flèche : [asinh(e)·(1−m_e), m_e], m_e = sa cible est masquée.
    Version 2 : les mêmes, sans asinh. Version 3 (auto-encodeur, §11) : pas de
    masque ni de drapeau m ([état, présence, contexte] ; [e]), et un goulot de
    dimension GOULOT par sorte après la dernière couche : les décodeurs ne lisent
    que ce plongement final.
    Modèle « double » (u2, §19) : l'entrée [brut·(1−m), asinh·(1−m), présence·(1−m),
    contexte brut, contexte asinh, m] (convertir_double) ; flèche [e brut·(1−m_e),
    asinh(e)·(1−m_e), m_e] ; deux têtes : les mêmes décodeurs dupliqués (dec, dec_e :
    la tête brute ; dec_asinh, dec_e_asinh : la tête asinh, créés après tout le reste),
    sur le même plongement ; forward rend alors {tête : (valeurs, logits, flèches)}.
    """

    def __init__(self, dims: dict, variante: str = "complet", version: str = MODELE_DEFAUT):
        super().__init__()
        cfg = VARIANTES[variante]
        self.dims, self.lie = dims, cfg["lie"]
        self.version, self.masque = version, VERSIONS[version]["masque"]
        self.tetes = VERSIONS[version].get("tetes")          # u2 (§19) : deux têtes ; None sinon
        ne = len(self.tetes) if self.tetes else 1            # chaque colonne chiffrée, une fois par échelle
        drapeau = 1 if self.masque else 0
        self.canal = [r for r in CHIFFREES if cfg["canal"] and r in cfg["relations"] and dims["rel"][r]]
        self.notees = [r for r in CHIFFREES if r in cfg["notees"] and dims["rel"][r]]
        self.passages = []
        for r, (s, d) in RELATIONS.items():
            if r in cfg["relations"]:
                self.passages += [(r, r, s, d, True), (f"rev_{r}", r, d, s, False)]
        de, dc = dims["etat"], dims["ctx"]
        self.enc = nn.ModuleDict({k: nn.Linear(ne * de[k] + de[k] + ne * dc[k] + drapeau, H) for k in SORTES})
        self.phi = nn.ModuleDict({r: nn.Sequential(nn.Linear(ne * dims["rel"][r] + drapeau, H), nn.ReLU(),
                                                   nn.Linear(H, H))
                                  for r in self.canal})
        self.soi = nn.ModuleList([nn.ModuleDict({k: nn.Linear(H, H) for k in SORTES}) for _ in range(COUCHES)])
        if self.lie:
            self.W = nn.ModuleList([nn.Linear(H, H) for _ in range(COUCHES)])
        else:
            self.W = nn.ModuleList([nn.ModuleDict({nom: nn.Linear(2 * H if r in self.canal else H, H)
                                                   for nom, r, _, _, _ in self.passages}) for _ in range(COUCHES)])
        self.norme = nn.ModuleList([nn.ModuleDict({k: nn.LayerNorm(H) for k in SORTES}) for _ in range(COUCHES)])
        # v3 : le goulot, créé après les couches (v1 et v2 gardent l'ordre de création, donc leurs poids initiaux).
        self.goulot = None if self.masque else nn.ModuleDict({k: nn.Linear(H, GOULOT) for k in SORTES})
        lu = H if self.masque else GOULOT                  # ce que lisent les décodeurs
        self.dec = nn.ModuleDict({k: nn.Sequential(nn.Linear(lu, H), nn.ReLU(), nn.Linear(H, 2 * de[k]))
                                  for k in SORTES})
        self.dec_e = nn.ModuleDict({r: nn.Sequential(nn.Linear(2 * lu, H), nn.ReLU(), nn.Linear(H, dims["rel"][r]))
                                    for r in self.notees})
        if self.tetes:   # u2 (§19) : la tête asinh, les mêmes décodeurs dupliqués, créés après tout le reste
            self.dec_asinh = nn.ModuleDict({k: nn.Sequential(nn.Linear(lu, H), nn.ReLU(), nn.Linear(H, 2 * de[k]))
                                            for k in SORTES})
            self.dec_e_asinh = nn.ModuleDict({r: nn.Sequential(nn.Linear(2 * lu, H), nn.ReLU(),
                                                               nn.Linear(H, dims["rel"][r])) for r in self.notees})

    def decodeurs(self, tete: str | None = None) -> tuple[nn.ModuleDict, nn.ModuleDict]:
        """(décodeurs des nœuds, des flèches) : ceux du modèle ; u2, ceux de la tête `tete`."""
        return (self.dec_asinh, self.dec_e_asinh) if self.tetes and tete == TETES[1] else (self.dec, self.dec_e)

    def forward(self, g: Graphe, m: dict | None):
        """m : sorte -> masque des nœuds (versions à masque) ; ignoré en version 3."""
        h = {}
        if self.masque:
            for k in SORTES:
                mk = m[k].float().unsqueeze(1)
                h[k] = self.enc[k](torch.cat([g.x[k] * (1 - mk), g.p[k] * (1 - mk), g.ctx[k], mk], 1))
            me = {r: m[RELATIONS[r][1]][g.ei[r][1]].float().unsqueeze(1) for r in RELATIONS}
            phi = {r: self.phi[r](torch.cat([g.ea[r] * (1 - me[r]), me[r]], 1)) for r in self.canal}
        else:
            h = {k: self.enc[k](torch.cat([g.x[k], g.p[k], g.ctx[k]], 1)) for k in SORTES}
            phi = {r: self.phi[r](g.ea[r]) for r in self.canal}
        for couche in range(COUCHES):
            a = {k: self.soi[couche][k](h[k]) for k in SORTES}
            for nom, r, s, d, directe in self.passages:
                i_s, i_d = (g.ei[r][0], g.ei[r][1]) if directe else (g.ei[r][1], g.ei[r][0])
                entree = h[s][i_s]
                if r in self.canal:
                    entree = torch.cat([entree, phi[r]], 1)
                w = self.W[couche] if self.lie else self.W[couche][nom]
                a[d] = a[d] + _moyenne(w(entree), i_d, g.n[d])
            h = {k: self.norme[couche][k](h[k] + F.relu(a[k])) for k in SORTES}
        if self.goulot is not None:
            h = {k: self.goulot[k](h[k]) for k in SORTES}
        if self.tetes:   # u2 (§19) : une sortie par tête, sur le même plongement
            return {t: self._decoder(h, g, *self.decodeurs(t)) for t in self.tetes}
        return self._decoder(h, g, self.dec, self.dec_e)

    def _decoder(self, h: dict, g: Graphe, dec: nn.ModuleDict, dec_e: nn.ModuleDict):
        """(valeurs, logits de présence, flèches) lus par ces décodeurs sur le plongement h."""
        valeurs, logits = {}, {}
        for k in SORTES:
            v, lo = dec[k](h[k]).split(self.dims["etat"][k], 1)
            valeurs[k], logits[k] = v, lo
        fleches = {}
        for r in self.notees:
            s, d = RELATIONS[r]
            fleches[r] = dec_e[r](torch.cat([h[s][g.ei[r][0]], h[d][g.ei[r][1]]], 1))
        return valeurs, logits, fleches


def perte_masquee(modele: Reconstructeur, g: Graphe, m: dict):
    """Huber sur les valeurs présentes et 0,5 × BCE sur la présence des nœuds masqués ;
    Huber sur les flèches masquées ; moyenne par sorte, moyenne par relation. En
    version 3 (sans masque), m vaut 1 partout : la perte porte sur tous les nœuds et
    toutes les flèches, et le modèle ne voit pas m. Modèle double (u2, §19) :
    ½ (L_v2 + L_v1), chacune la perte complète de sa version (cette même perte) sur SA
    tête et SA cible (cible) ; la présence, la même dans les deux, compte donc une fois."""
    sorties = modele(g, m)
    if modele.tetes:
        pertes = [_perte(sorties[t], cible(g, t, modele.dims), m, modele.notees) for t in modele.tetes]
        if pertes[0] is None:          # mêmes masques, mêmes lignes : les deux pertes existent ou aucune
            return None
        return 0.5 * (pertes[0] + pertes[1])   # ½ (L_v2 + L_v1) : TETES = (brute, asinh)
    return _perte(sorties, g, m, modele.notees)


def _perte(sortie: tuple, g: Graphe, m: dict, notees: list[str]):
    """La perte d'une version sur ses sorties (valeurs, logits, flèches) et sa cible g (perte_masquee)."""
    valeurs, logits, fleches = sortie
    noeuds = []
    for k in SORTES:
        lignes = m[k]
        if not bool(lignes.any()) or valeurs[k].shape[1] == 0:
            continue
        pr, x = g.p[k][lignes], g.x[k][lignes]
        v, lo = valeurs[k][lignes], logits[k][lignes]
        la = pr > 0.5
        hub = F.huber_loss(v[la], x[la], delta=HUBER) if bool(la.any()) else v.sum() * 0.0
        noeuds.append(hub + POIDS_PRESENCE * F.binary_cross_entropy_with_logits(lo, pr))
    aretes = []
    for r in notees:
        me = m[RELATIONS[r][1]][g.ei[r][1]]
        if bool(me.any()):
            aretes.append(F.huber_loss(fleches[r][me], g.ea[r][me], delta=HUBER))
    if not noeuds and not aretes:
        return None
    perte = torch.stack(noeuds).mean() if noeuds else 0.0
    return perte + (torch.stack(aretes).mean() if aretes else 0.0)


def _un_fil() -> None:
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)


def entrainer(graphes: list[Graphe], dims: dict, variante: str, graine: int, rang_pli: int,
              epoques: int = EPOQUES, version: str = MODELE_DEFAUT) -> tuple[dict, dict]:
    """(state_dict, informations). Déterministe : graine × 1009 + rang_pli, un fil.
    Les graphes sont convertis pour la version (asinh ou non)."""
    _un_fil()
    debut = time.perf_counter()
    germe = graine * 1009 + rang_pli
    torch.manual_seed(germe)
    gen = torch.Generator().manual_seed(germe)
    modele = Reconstructeur(dims, variante, version)
    opt = torch.optim.Adam(modele.parameters(), lr=LR, weight_decay=WD)
    pertes = []
    for _ in range(epoques):
        ordre = torch.randperm(len(graphes), generator=gen).tolist()
        total, pas = 0.0, 0
        for i in range(0, len(ordre), LOT):
            g = assembler([graphes[j] for j in ordre[i:i + LOT]])
            if modele.masque:
                m = {k: torch.rand(g.n[k], generator=gen) < P_MASQUE for k in SORTES}
            else:
                m = {k: torch.ones(g.n[k], dtype=torch.bool) for k in SORTES}
            perte = perte_masquee(modele, g, m)
            if perte is None:
                continue
            opt.zero_grad()
            perte.backward()
            opt.step()
            total, pas = total + float(perte), pas + 1
        pertes.append(total / max(pas, 1))
    etat = {k: v.detach().clone() for k, v in modele.state_dict().items()}
    return etat, {"duree": time.perf_counter() - debut, "pertes": pertes, "fenetres": len(graphes),
                  "parametres": sum(p.numel() for p in modele.parameters())}


# Les entraînements en parallèle : les fenêtres converties sont envoyées une fois
# à chaque processus (initializer), chaque tâche ne porte que des identifiants.
_TRAVAIL: dict = {}


def _en_octets(obj) -> bytes:
    """Les tenseurs passent entre processus en octets : le partage de descripteurs de
    torch.multiprocessing casse sur de nombreux tenseurs (« received 0 items of ancdata »)."""
    tampon = io.BytesIO()
    torch.save(obj, tampon)
    return tampon.getvalue()


def _des_octets(brut: bytes):
    return torch.load(io.BytesIO(brut), weights_only=False)


def _init_processus(graphes: bytes) -> None:
    global _TRAVAIL
    _un_fil()
    _TRAVAIL = _des_octets(graphes)


def _tache(t: tuple) -> bytes:
    ids, dims, variante, graine, rang_pli, epoques, version = t
    return _en_octets(entrainer([_TRAVAIL[i] for i in ids], dims, variante, graine, rang_pli, epoques, version))


def entrainer_tous(taches: list[tuple], graphes: dict) -> list[tuple[dict, dict]]:
    """Chaque tâche (ids, dims, variante, graine, rang, époques, version), sur au plus PROCESSUS
    processus (contexte spawn, un fil chacun), dans l'ordre des tâches."""
    if not taches:
        return []
    with ProcessPoolExecutor(max_workers=min(PROCESSUS, len(taches)),
                             mp_context=multiprocessing.get_context("spawn"),
                             initializer=_init_processus, initargs=(_en_octets(graphes),)) as ex:
        return [_des_octets(b) for b in ex.map(_tache, taches)]


def charger(etat: dict, dims: dict, variante: str, version: str = MODELE_DEFAUT) -> Reconstructeur:
    modele = Reconstructeur(dims, variante, version)
    modele.load_state_dict(etat)
    return modele.eval()


class VueTete(nn.Module):
    """
    u2 (§19) : une tête du réseau à deux échelles, vue comme un modèle simple. La même entrée
    (convertir_double), les sorties de SA tête (valeurs, logits de présence, flèches) et SA cible
    (cible) ; les poids sont ceux du réseau, le même objet : rien n'est copié ni appris. Son
    plongement (norme) est celui du réseau, commun aux deux têtes.
    """

    def __init__(self, reseau: Reconstructeur, tete: str):
        super().__init__()
        if not reseau.tetes or tete not in reseau.tetes:
            raise ValueError(f"tête {tete} : le modèle {reseau.version} n'a pas cette tête")
        self.reseau, self.tete = reseau, tete
        self.version, self.masque, self.notees, self.dims = reseau.version, reseau.masque, reseau.notees, reseau.dims
        self.tetes = None

    @property
    def norme(self):
        """La dernière couche du réseau (gnn_exemples.plongements) : le plongement commun."""
        return self.reseau.norme

    def forward(self, g: Graphe, m: dict | None):
        return self.reseau(g, m)[self.tete]

    def cible(self, g: Graphe) -> Graphe:
        return cible(g, self.tete, self.dims)


def reseau_de(modele: nn.Module) -> Reconstructeur:
    """Le réseau appris d'un modèle : lui-même, ou celui d'une tête (VueTete, u2)."""
    reseau = getattr(modele, "reseau", None)
    return modele if reseau is None else reseau


def tete_de(modele: nn.Module) -> str | None:
    """La tête d'un modèle (u2 : « brute » ou « asinh ») ; None pour un modèle simple."""
    return getattr(modele, "tete", None)


def vue_tete(modele: Reconstructeur, tete: str | None) -> nn.Module:
    """Le modèle tel quel (tete None), ou sa tête `tete` (VueTete, u2)."""
    return modele if tete is None else VueTete(modele, tete)


# ------------------------------------------------------------------------------
# La note d'une fenêtre : résidus, écarts, post-traitement
# ------------------------------------------------------------------------------
@dataclass
class Sortie:
    """Les résidus d'une fenêtre, un passage par nœud masqué. Les noms et hosts ne
    servent qu'au post-traitement (H, V) et aux clés de la réponse."""
    res_n: dict                    # sorte -> [n, d_état + 1] : résidus signés, NaN si absent ; absents
    res_e: dict                    # relation notée -> [E, d_r]
    edges: dict                    # relation -> [2, E] (indices locaux)
    n: dict                        # sorte -> nombre
    names: dict                    # sorte -> noms
    hosts: list                    # machine (nom) de chaque instance, ou None
    decal: dict = field(default_factory=dict)

    def __post_init__(self):
        o = 0
        for k in SORTES:
            self.decal[k] = o
            o += self.n[k]
        self.total = o

    def cles(self) -> list[str]:
        return [juge._cle(k, nom) for k in SORTES for nom in self.names[k]]

    def machine(self) -> np.ndarray:
        """L'indice global de la machine de chaque instance (−1 sans machine connue)."""
        place = {nom: self.decal["host"] + i for i, nom in enumerate(self.names["host"])}
        return np.array([place.get(h, -1) for h in self.hosts], dtype=int)

    def globaux(self, r: str) -> tuple[np.ndarray, np.ndarray]:
        s, d = RELATIONS[r]
        e = self.edges[r]
        return e[0] + self.decal[s], e[1] + self.decal[d]

    def identites(self) -> tuple[dict, dict]:
        """({sorte : identité de chaque nœud}, {relation : (relation, identité source,
        identité cible) de chaque flèche}), temoin_noeud.identite : pour le SEUL
        calage de la sortie (versions 2 et 3), jamais pour le modèle."""
        if getattr(self, "_identites", None) is None:
            noeuds = {k: [tn.identite(k, nom) for nom in self.names[k]] for k in SORTES}
            fleches = {r: [(r, noeuds[s][a], noeuds[d][b]) for a, b in zip(*self.edges[r].tolist())]
                       for r, (s, d) in RELATIONS.items()}
            self._identites = (noeuds, fleches)
        return self._identites


def residus(modele: Reconstructeur, donnees: dict) -> Sortie:
    """Versions à masque : un passage par nœud, en lot (la copie i masque le nœud i et
    ses flèches entrantes). Version 3 : une seule passe, sans masque, les résidus de
    tous les nœuds et de toutes les flèches d'un coup. Une tête du réseau double (VueTete,
    u2, §19) : l'entrée aux deux échelles, les résidus de SA tête contre SA cible."""
    if getattr(modele, "tetes", None):
        raise ValueError("u2 : le réseau à deux têtes se lit par une tête (VueTete)")
    g = convertir(donnees, VERSIONS[modele.version]["asinh"])
    # Ce que le modèle reconstruit : g, ou la cible de sa tête (VueTete, reconnue à sa méthode `cible` et non
    # par isinstance : gnn.py lancé en script et importé par gnn_exemples a deux classes VueTete).
    cible_de = getattr(modele, "cible", None)
    t = cible_de(g) if cible_de is not None else g
    n = {k: g.n[k] for k in SORTES}
    total = sum(n.values())
    decal, o = {}, 0
    for k in SORTES:
        decal[k], o = o, o + n[k]
    if modele.masque:
        lot = _copies(g, total)
        m = {}
        for k in SORTES:
            mk = torch.zeros(total * n[k], dtype=torch.bool)
            i = torch.arange(n[k])
            mk[(decal[k] + i) * n[k] + i] = True
            m[k] = mk
        with torch.no_grad():
            valeurs, logits, fleches = modele(lot, m)
    else:
        with torch.no_grad():
            valeurs, logits, fleches = modele(g, None)
    res_n = {}
    for k in SORTES:
        i = torch.arange(n[k])
        lignes = (decal[k] + i) * n[k] + i if modele.masque else i
        r = (t.x[k] - valeurs[k][lignes]).numpy().astype(float)
        r[t.p[k].numpy() < 0.5] = np.nan
        absents = (t.p[k] - torch.sigmoid(logits[k][lignes])).sum(1).numpy().astype(float)
        res_n[k] = np.concatenate([r, absents[:, None]], 1)
    res_e = {}
    for r in modele.notees:
        s, d = RELATIONS[r]
        e = g.ei[r].shape[1]
        lignes = (decal[d] + g.ei[r][1]) * e + torch.arange(e) if modele.masque else torch.arange(e)
        res_e[r] = (t.ea[r] - fleches[r][lignes]).numpy().astype(float) if e else np.zeros((0, t.ea[r].shape[1]))
    inst = donnees["nodes"]["instance"]
    return Sortie(res_n, res_e, {r: g.ei[r].numpy() for r in RELATIONS}, n,
                  {k: list(donnees["nodes"][k]["names"]) for k in SORTES}, list(inst.get("hosts") or [None] * n["instance"]))


def _echelle_robuste(vals: np.ndarray) -> float:
    """tn.echelle (quantiles linéaires), plancher de tn.echelles : 0,1 × pstdev, ou 0,1."""
    if len(vals) == 0:
        return 1.0
    q01, q25, q75, q99 = np.quantile(vals, [0.01, 0.25, 0.75, 0.99])
    s = max((q75 - q25) / 1.349, (q99 - q01) / 4.653)
    if s <= 1e-12:
        sd = float(np.std(vals))
        s = tn.PLANCHER * (sd if sd > 1e-12 else 1.0)
    return float(s)


def _q95(vals) -> float:
    return tn._q(list(map(float, vals)), CENTILE / 100)


def ecarts(sortie: Sortie, calage: "Calage") -> tuple[dict, np.ndarray, dict, dict]:
    """(z des nœuds par sorte, erreur r_v de chaque nœud en indices globaux, z des
    flèches par relation notée, erreur ε de chaque flèche). Médiane et échelle par
    sorte (version 1) ou par identité (versions 2 et 3) : Calage.lignes."""
    med_n, ech_n, med_e, ech_e = calage.lignes(sortie)
    z_n, r = {}, np.zeros(sortie.total)
    for k in SORTES:
        z = (sortie.res_n[k] - med_n[k]) / ech_n[k]
        z_n[k] = z
        if len(z):
            o = sortie.decal[k]
            r[o:o + sortie.n[k]] = np.nanmax(np.abs(z), axis=1)   # la colonne absents n'est jamais NaN
    z_e, eps = {}, {}
    for rel in calage.notees:
        z = (sortie.res_e[rel] - med_e[rel]) / ech_e[rel]
        z_e[rel] = z
        eps[rel] = np.abs(z).max(axis=1) if len(z) else np.zeros(0)
    return z_n, r, z_e, eps


def bout(b: str, sortie: Sortie, eps: dict, kappa: dict) -> np.ndarray:
    """e_v, ce que chaque nœud reçoit des flèches ANORMALES (ε > κ_r), selon B."""
    e = np.zeros(sortie.total)
    for rel, ep in eps.items():
        if not len(ep):
            continue
        src, dst = sortie.globaux(rel)
        an = ep > kappa[rel]
        if not an.any():
            continue
        if b in ("B1", "B3"):
            np.maximum.at(e, dst[an], ep[an])
        if b in ("B2", "B3"):
            np.maximum.at(e, src[an], ep[an])
        if b == "B4":
            np.add.at(e, dst[an], ep[an])
        if b == "B5":
            entrant, entrant_an = np.zeros(sortie.total), np.zeros(sortie.total)
            sortant, sortant_an = np.zeros(sortie.total), np.zeros(sortie.total)
            np.add.at(entrant, dst, 1.0)
            np.add.at(entrant_an, dst[an], 1.0)
            np.add.at(sortant, src, 1.0)
            np.add.at(sortant_an, src[an], 1.0)
            fin = entrant_an[dst[an]] / entrant[dst[an]]
            fout = sortant_an[src[an]] / sortant[src[an]]
            np.add.at(e, dst[an], ep[an] * fin / (fin + fout))
            np.add.at(e, src[an], ep[an] * fout / (fin + fout))
    return e


def normaliser(sortie: Sortie, r: np.ndarray, e: np.ndarray, tau: dict) -> np.ndarray:
    """ŝ_v = max(r_v, e_v) / τ_k : « 1 = l'extrême normal de sa sorte »."""
    t = np.maximum(r, e)
    s = np.empty_like(t)
    for k in SORTES:
        o = sortie.decal[k]
        s[o:o + sortie.n[k]] = t[o:o + sortie.n[k]] / tau[k]
    return s


def _actifs(sortie: Sortie, machine: np.ndarray, rels) -> set[int]:
    """Les pods source d'une flèche calls ou queries vers un pod d'une autre machine."""
    out = set()
    for rel in APPELS:
        if rel not in rels:
            continue
        src, dst = sortie.globaux(rel)
        for a, b in zip(src.tolist(), dst.tolist()):
            if machine[a] >= 0 and machine[b] >= 0 and machine[a] != machine[b]:
                out.add(a)
    return out


def _amont(sortie: Sortie, rels, cibles: set[int]) -> set[int]:
    """Les pods qui atteignent l'un des pods cibles par les flèches calls et queries de
    la fenêtre (sans nom), hors les cibles elles-mêmes."""
    appelants: dict[int, set[int]] = {}
    for rel in APPELS:
        if rel in rels:
            src, dst = sortie.globaux(rel)
            for a, b in zip(src.tolist(), dst.tolist()):
                appelants.setdefault(b, set()).add(a)
    vus, bord = set(), set(cibles)
    while bord:
        bord = {a for b in bord for a in appelants.get(b, ())} - vus - cibles
        vus |= bord
    return vus


def remontee(hh: str, s: np.ndarray, sortie: Sortie, rels) -> np.ndarray:
    """H : l'erreur des pods remonte à leur machine (par le champ hosts)."""
    out = s.copy()
    if hh == "H0":
        return out
    machine = sortie.machine()
    inst = np.arange(sortie.decal["instance"], sortie.decal["instance"] + sortie.n["instance"])
    actifs = _actifs(sortie, machine, rels) if hh == "H2" else set()
    for hote in range(sortie.decal["host"], sortie.decal["host"] + sortie.n["host"]):
        pods = [int(p) for p in inst if machine[p] == hote]
        anormaux = [p for p in pods if s[p] > 1]
        if len(anormaux) < 2:
            continue
        if hh == "H2":
            ici = [p for p in pods if p in actifs]
            if not 2 * sum(1 for p in ici if s[p] > 1) > len(ici):
                continue
            amont = _amont(sortie, rels, set(pods))
            ailleurs = [p for p in actifs if machine[p] != hote and p not in amont]
            if 2 * sum(1 for p in ailleurs if s[p] > 1) > len(ailleurs):
                continue
        out[hote] = max(out[hote], float(sum(s[p] for p in anormaux)))
    return out


def dependances(sortie: Sortie, rels) -> list[set[int]]:
    """D(v) lu dans la fenêtre : une file dépend de ses consommateurs et producteurs ;
    une instance des cibles de ses calls et queries, et de sa machine ; une machine de rien."""
    dep = [set() for _ in range(sortie.total)]
    if "consumes" in rels:
        src, dst = sortie.globaux("consumes")
        for q, i in zip(src.tolist(), dst.tolist()):
            dep[q].add(i)
    if "publishes" in rels:
        src, dst = sortie.globaux("publishes")
        for i, q in zip(src.tolist(), dst.tolist()):
            dep[q].add(i)
    for rel in APPELS:
        if rel in rels:
            src, dst = sortie.globaux(rel)
            for a, b in zip(src.tolist(), dst.tolist()):
                if a != b:
                    dep[a].add(b)
    for p, h in zip(range(sortie.decal["instance"], sortie.decal["instance"] + sortie.n["instance"]),
                    sortie.machine().tolist()):
        if h >= 0:
            dep[p].add(h)
    return dep


def explication(v: str, s: np.ndarray, sortie: Sortie, rels) -> tuple[np.ndarray, dict, dict]:
    """V : une anomalie qui s'explique par une dépendance anormale passe à cette
    dépendance, jusqu'au dernier composant anormal. (ŝ', pointeurs, racines)."""
    if v == "V0":
        return s.copy(), {}, {}
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import connected_components
    anorm = s > 1
    dep = dependances(sortie, rels)
    lignes, colonnes = [], []
    for a in np.flatnonzero(anorm).tolist():
        for u in dep[a]:
            if anorm[u]:
                lignes.append(a)
                colonnes.append(u)
    graphe = csr_matrix((np.ones(len(lignes)), (lignes, colonnes)), shape=(sortie.total, sortie.total))
    _, scc = connected_components(graphe, directed=True, connection="strong")
    pointeur = {}
    for a in np.flatnonzero(anorm).tolist():
        cand = [u for u in dep[a] if anorm[u] and scc[u] != scc[a]]
        if cand:
            # égalité : le plus haut ŝ, puis le plus petit indice ; jamais le nom
            pointeur[a] = max(cand, key=lambda u: (s[u], -u))
    racine = {}
    for a in pointeur:
        r = a
        while r in pointeur:
            r = pointeur[r]
        racine[a] = r
    out = s.copy()
    for a in pointeur:
        out[a] = 1.0 - math.exp(-s[a])
    for a, r in racine.items():
        out[r] = max(out[r], s[r], s[a])
    return out, pointeur, racine


def noter_noeuds(sortie: Sortie, calage: "Calage", choix: dict | None = None,
                 variante: str | None = None) -> tuple[dict, float, dict]:
    """(score ŝ' de chaque clé du juge, score de la fenêtre S = max ŝ', diagnostic). La
    variante est celle du calage (celle de l'étape 1 qui l'a produit) ; le choix par
    défaut, celui de la version du calage, et seulement pour un calage de sa version : un
    calage recalé (« v2:sorte » de u, « v1:identite » de u1) n'a pas de défaut (son choix
    n'est pas celui de sa version), le choix doit être passé."""
    if not choix and calage.par_identite != VERSIONS[calage.version]["identite"]:
        raise ValueError(f"calage recalé ({calage.version}, par identité : {calage.par_identite}) sans choix : "
                         f"le choix B/H/V doit être passé (choix_exemplaire)")
    choix = choix or CHOIX_VERSIONS[calage.version]
    if variante is not None and variante != calage.variante:
        raise ValueError(f"variante {variante} contre un calage de la variante {calage.variante}")
    cfg = VARIANTES[calage.variante]
    _, r, _, eps = ecarts(sortie, calage)
    e = bout(choix["bout"], sortie, eps, calage.kappa)
    s = normaliser(sortie, r, e, calage.tau(choix["bout"]))
    s = remontee(choix["remontee"], s, sortie, APPELS)   # H lit les flèches de la fenêtre dans toutes les variantes (§6, J 1597-1599)
    sp, pointeur, racine = explication(choix["explication"], s, sortie, cfg["deps"])
    cles = sortie.cles()
    scores = {c: float(x) for c, x in zip(cles, sp)}
    haut = int(np.argmax(sp)) if len(sp) else None
    return scores, float(sp.max()) if len(sp) else 0.0, {
        "premier": cles[haut] if haut is not None else None,
        "pointeurs": {cles[a]: cles[b] for a, b in pointeur.items()},
        "racines": sorted({cles[b] for b in racine.values()})}


def rang_attendu(scores: dict, attendue: str | list[str], tous: list[str]) -> int:
    """Le rang de la réponse attendue (une clé ou plusieurs), égalités contre le GNN (juge.rang)."""
    return juge.rang([attendue] if isinstance(attendue, str) else list(attendue), scores, tous)


def base_en_tete(scores: dict, base: list[str], tous: list[str]) -> bool:
    """La base est-elle première, ex aequo compris ? Pour la garde G_val, une égalité
    compte contre le GNN (la base est alors désignée) ; juge.rang la compte déjà contre
    lui pour le top-1. Sous B3, la base partage son ε avec la source de sa flèche
    queries anormale : dc.premier (rang == 1) verrait « pas première »."""
    m = max(juge._val(scores.get(c)) for c in base)
    return m > -math.inf and not any(juge._val(scores.get(k)) > m for k in tous if k not in base)


def grille() -> list[dict]:
    """Les 30 combinaisons B/H/V, dans l'ordre de simplicité (V, puis H, puis B)."""
    return [{"bout": b, "remontee": h, "explication": v}
            for v in EXPLICATIONS for h in REMONTEES for b in BOUTS]


def simplicite(choix: dict) -> tuple[int, int, int]:
    """La clé de l'ordre de simplicité (§3.5) : V0 < V1, puis H0 < H1 < H2, puis B1 < … < B5."""
    return (EXPLICATIONS.index(choix["explication"]), REMONTEES.index(choix["remontee"]),
            BOUTS.index(choix["bout"]))


def nom_choix(choix: dict) -> str:
    return f"{choix['bout']}/{choix['remontee']}/{choix['explication']}"


# ------------------------------------------------------------------------------
# Les échelles hors pli, κ, τ
# ------------------------------------------------------------------------------
class Calage:
    """Médianes et échelles des résidus, κ_r et τ_k(B), sur des résidus TENUS hors pli.

    Version 1 : par (sorte, colonne) et (relation, colonne). Versions 2 et 3 (§11) :
    par (identité, colonne), l'identité du témoin 2 (temoin_noeud.identite : un pod de
    Deployment ramené à son service ; StatefulSet, file, machine par leur nom) et,
    pour une flèche, (relation, identité source, identité cible) comme le témoin
    des flèches ; médiane et échelle robustes de temoin_noeud.echelles, avec son
    plancher par (sorte, colonne) ou (relation, colonne) et son minimum de MIN_OBS
    résidus. Une identité (ou une de ses colonnes) sans normal retombe sur le calage
    par sorte ou par relation. L'identité ne cale que la sortie : le modèle ne la
    voit jamais.

    `par_identite` (None : celui de la version) : la variante u (§17) cale les résidus
    de l'exemplaire v2 PAR SORTE (par_identite=False) pour son classement ; la variante u1
    (§18) cale ceux de l'exemplaire v1 PAR IDENTITÉ (par_identite=True) pour son alarme. Le
    réseau double (u2, §19) n'a pas de calage à lui : `par_identite` est alors obligatoire
    (tête brute True, tête asinh False), sinon ValueError."""

    def __init__(self, sorties: list[Sortie], variante: str, notees: list[str], version: str = MODELE_DEFAUT,
                 par_identite: bool | None = None):
        self.variante, self.notees, self.sorties = variante, list(notees), sorties
        self.version = version
        if par_identite is None and VERSIONS[version].get("tetes"):
            raise ValueError(f"Calage du réseau {version} (u2, §19) : préciser le calage de la tête (par_identite), "
                             f"le réseau n'en a pas à lui")
        self.par_identite = VERSIONS[version]["identite"] if par_identite is None else bool(par_identite)
        self.med_n, self.ech_n, self.med_e, self.ech_e = {}, {}, {}, {}
        for k in SORTES:
            tout = np.concatenate([s.res_n[k] for s in sorties]) if sorties else np.zeros((0, 1))
            med, ech = [], []
            for c in range(tout.shape[1]):
                vals = tout[:, c][~np.isnan(tout[:, c])]
                med.append(float(np.median(vals)) if len(vals) else 0.0)
                ech.append(_echelle_robuste(vals))
            self.med_n[k], self.ech_n[k] = np.array(med), np.array(ech)
        for rel in self.notees:
            tout = np.concatenate([s.res_e[rel] for s in sorties])
            self.med_e[rel] = np.array([float(np.median(tout[:, c])) if len(tout) else 0.0
                                        for c in range(tout.shape[1])])
            self.ech_e[rel] = np.array([_echelle_robuste(tout[:, c]) for c in range(tout.shape[1])])
        self.ident_n: dict = {k: {} for k in SORTES}     # identité -> (médianes, échelles), repli compris
        self.ident_e: dict = {rel: {} for rel in self.notees}
        if self.par_identite:
            self._caler_identites(sorties)
        self._ecarts = [ecarts(s, self) for s in sorties]
        self.kappa = {}
        for rel in self.notees:
            tout = np.concatenate([ec[3][rel] for ec in self._ecarts])
            self.kappa[rel] = _q95(tout) if len(tout) else math.inf
        self._tau: dict[str, dict] = {}

    def _caler_identites(self, sorties: list[Sortie]) -> None:
        for k in SORTES:
            valeurs: dict = {}
            for s in sorties:
                ids = s.identites()[0][k]
                for ident, ligne in zip(ids, s.res_n[k].tolist()):
                    par = valeurs.setdefault(ident, {})
                    for c, v in enumerate(ligne):
                        if not math.isnan(v):
                            par.setdefault(c, []).append(v)
            stats = tn.echelles(valeurs, lambda ident: ident.split(":", 1)[0])
            for ident, par in stats.items():
                if not par:
                    continue                             # aucune colonne assez observée : le repli
                med, ech = self.med_n[k].copy(), self.ech_n[k].copy()
                for c, (m, e) in par.items():
                    med[c], ech[c] = m, e
                self.ident_n[k][ident] = (med, ech)
        for rel in self.notees:
            valeurs = {}
            for s in sorties:
                for ident, ligne in zip(s.identites()[1][rel], s.res_e[rel].tolist()):
                    par = valeurs.setdefault(ident, {})
                    for c, v in enumerate(ligne):
                        par.setdefault(c, []).append(v)
            stats = tn.echelles(valeurs, lambda cle: cle[0])
            for ident, par in stats.items():
                if not par:
                    continue
                med, ech = self.med_e[rel].copy(), self.ech_e[rel].copy()
                for c, (m, e) in par.items():
                    med[c], ech[c] = m, e
                self.ident_e[rel][ident] = (med, ech)

    def lignes(self, sortie: Sortie) -> tuple[dict, dict, dict, dict]:
        """(médianes, échelles) des nœuds par sorte, puis des flèches par relation notée :
        un vecteur par sorte (version 1, diffusé sur les lignes), ou une ligne par nœud et
        par flèche selon son identité, le repli par sorte pour une identité inconnue."""
        if not self.par_identite:
            return self.med_n, self.ech_n, self.med_e, self.ech_e
        noeuds, fleches = sortie.identites()
        med_n, ech_n, med_e, ech_e = {}, {}, {}, {}
        for k in SORTES:
            defaut = (self.med_n[k], self.ech_n[k])
            paires = [self.ident_n[k].get(i, defaut) for i in noeuds[k]]
            med_n[k] = np.array([m for m, _ in paires]).reshape(len(paires), len(defaut[0]))
            ech_n[k] = np.array([e for _, e in paires]).reshape(len(paires), len(defaut[0]))
        for rel in self.notees:
            defaut = (self.med_e[rel], self.ech_e[rel])
            paires = [self.ident_e[rel].get(i, defaut) for i in fleches[rel]]
            med_e[rel] = np.array([m for m, _ in paires]).reshape(len(paires), len(defaut[0]))
            ech_e[rel] = np.array([e for _, e in paires]).reshape(len(paires), len(defaut[0]))
        return med_n, ech_n, med_e, ech_e

    def connues(self, sortie: Sortie) -> tuple[int, int, int, int]:
        """(nœuds calés par leur identité, nœuds, flèches calées par leur identité, flèches notées)."""
        noeuds, fleches = sortie.identites()
        n = sum(1 for k in SORTES for i in noeuds[k] if i in self.ident_n[k])
        e = sum(1 for rel in self.notees for i in fleches[rel] if i in self.ident_e[rel])
        return n, sortie.total, e, sum(len(fleches[rel]) for rel in self.notees)

    def tau(self, b: str) -> dict:
        """τ_k : 95e centile des t = max(r, e) hors pli de la sorte k, pour le bout B."""
        if b not in self._tau:
            par = {k: [] for k in SORTES}
            for s, (_, r, _, eps) in zip(self.sorties, self._ecarts):
                t = np.maximum(r, bout(b, s, eps, self.kappa))
                for k in SORTES:
                    par[k] += t[s.decal[k]:s.decal[k] + s.n[k]].tolist()
            tau = {}
            for k in SORTES:
                v = _q95(par[k]) if par[k] else 1.0
                tau[k] = v if v > 1e-12 else 1.0
            self._tau[b] = tau
        return self._tau[b]


# ------------------------------------------------------------------------------
# L'étape 1 : le modèle final, les plis, les résidus tenus
# ------------------------------------------------------------------------------
def _taches(normales: list[dict], dims: dict, variante: str, graine: int, epoques: int,
            version: str = MODELE_DEFAUT) -> list[tuple]:
    """Le modèle final (rang 0), puis un pli par campagne dans l'ordre trié (rang 1 à n)."""
    campagnes = sorted({f["campagne"] for f in normales})
    ids = lambda garde: tuple(id(f["donnees"]) for f in garde)
    out = [(ids(normales), dims, variante, graine, 0, epoques, version)]
    for rang, c in enumerate(campagnes, 1):
        out.append((ids([f for f in normales if f["campagne"] != c]), dims, variante, graine, rang, epoques, version))
    return out


def empreinte(etat: dict) -> str:
    """§8 : sha256 de torch.save en mémoire, sans rien d'autre, dans toutes les versions
    (--ouvrir la refait sur le state_dict). La version s'imprime à côté, dans l'en-tête."""
    return hashlib.sha256(_en_octets(etat)).hexdigest()


class Etape1:
    """
    Le modèle final, appris sur toutes les normales d'apprentissage, et un modèle par
    pli (une campagne mise de côté). Les résidus tenus : les normales de chaque
    campagne notées par le modèle appris sans elle. Le calage du modèle final vient
    de tous les résidus tenus ; celui qui note la campagne c, des résidus tenus des
    autres campagnes (§3.1). Le réseau double (u2, §19) n'a ni résidus ni calage à lui : il
    garde ses normales, et chacune de ses têtes (TeteBrute, TeteAsinh : recale) a les siens.
    """

    def __init__(self, normales: list[dict], fige: dict, variante: str = "complet", graine: int = 0,
                 epoques: int = EPOQUES, etats: list[tuple[dict, dict]] | None = None, version: str = MODELE_DEFAUT):
        if variante not in VARIANTES:
            raise ValueError(f"variante inconnue : {variante}")
        if version not in VERSIONS:
            raise ValueError(f"version inconnue : {version}")
        self.campagnes = sorted({f["campagne"] for f in normales})
        if len(self.campagnes) < 2:
            raise ValueError("il faut des fenêtres normales d'apprentissage dans au moins deux campagnes "
                             "(le seuil d'alarme se cale en en mettant une de côté)")
        self.variante, self.graine, self.epoques, self.version = variante, graine, epoques, version
        self.exemplaire = version    # son nom dans les sorties (ParSorte : « v2:sorte » ; ParIdentite : « v1:identite »)
        _un_fil()                    # notes reproductibles : un fil, algorithmes déterministes
        self.dims = dimensions(fige)
        if etats is None:
            asinh = VERSIONS[version]["asinh"]
            graphes = {id(f["donnees"]): convertir(f["donnees"], asinh) for f in normales}
            etats = entrainer_tous(_taches(normales, self.dims, variante, graine, epoques, version), graphes)
        self.infos = [i for _, i in etats]
        self.modele = charger(etats[0][0], self.dims, variante, version)
        self.plis = {c: charger(etats[r][0], self.dims, variante, version) for r, c in enumerate(self.campagnes, 1)}
        self.empreinte = empreinte(etats[0][0])   # §8 : sha256 de torch.save en mémoire
        # Toutes les empreintes (modèle final et plis : les plis calent le seuil), pour empreintes().
        self.empreintes = {"modèle final": self.empreinte,
                           **{f"pli sans {c}": empreinte(etats[r][0]) for r, c in enumerate(self.campagnes, 1)}}
        if VERSIONS[version].get("tetes"):
            # u2 (§19) : le réseau à deux têtes ; chaque tête calcule SES résidus tenus sur ces normales.
            self.normales = list(normales)
            self.tenues = self.calage = self.calages_sans = None
            self._sorties, self._tenus, self._recales = {}, {}, {}
            return
        self.tenues = {c: [(f["id"], residus(self.plis[c], f["donnees"])) for f in normales if f["campagne"] == c]
                       for c in self.campagnes}
        notees = self.modele.notees
        self.calage = Calage([s for c in self.campagnes for _, s in self.tenues[c]], variante, notees, version)
        self.calages_sans = {c: Calage([s for c2 in self.campagnes if c2 != c for _, s in self.tenues[c2]],
                                       variante, notees, version) for c in self.campagnes}
        self._sorties: dict[int, tuple[dict, Sortie]] = {}
        self._tenus: dict[tuple, list] = {}
        self._recales: dict[str, "Recale"] = {}

    def recale(self, suffixe: str) -> "Recale":
        """Le même exemplaire, ses résidus calés autrement : PAR SORTE (« :sorte », variante u,
        §17) ou PAR IDENTITÉ (« :identite », variante u1, §18) ; ou, pour le réseau double (u2,
        §19), une de ses têtes avec son calage (« :brute » par identité, « :asinh » par sorte) ;
        gardé."""
        if suffixe not in self._recales:
            self._recales[suffixe] = {PAR_SORTE: ParSorte, PAR_IDENTITE: ParIdentite,
                                      TETE_BRUTE: TeteBrute, TETE_ASINH: TeteAsinh}[suffixe](self)
        return self._recales[suffixe]

    def par_sorte(self) -> "ParSorte":
        """Le même exemplaire, ses résidus calés PAR SORTE (variante u, §17) ; gardé."""
        return self.recale(PAR_SORTE)

    def sortie(self, donnees: dict) -> Sortie:
        """Les résidus du modèle final (gardés par objet ; une copie profonde est recalculée)."""
        cle = id(donnees)
        if cle not in self._sorties or self._sorties[cle][0] is not donnees:
            self._sorties[cle] = (donnees, residus(self.modele, donnees))
        return self._sorties[cle][1]

    def tenus(self, choix: dict | None = None) -> list[tuple[str, str, float]]:
        """(campagne, id, S) de chaque normale d'apprentissage, notée hors pli (J 1298-1299)."""
        choix = choix or CHOIX_VERSIONS[self.version]
        cle = tuple(sorted(choix.items()))
        if cle not in self._tenus:
            self._tenus[cle] = [(c, i, noter_noeuds(s, self.calages_sans[c], choix)[1])
                                for c in self.campagnes for i, s in self.tenues[c]]
        return self._tenus[cle]


class Recale(Etape1):
    """
    Un exemplaire déjà appris, ses résidus calés autrement (SUFFIXE, RECALAGES). Rien
    n'est appris ni recalculé côté modèle : le modèle final, les plis, les résidus tenus
    hors pli, les empreintes et les résidus de chaque fenêtre sont ceux de l'exemplaire
    (les mêmes objets). Seuls les calages sont refaits, sur les MÊMES résidus tenus et dans
    le même ordre (Calage(..., par_identite=RECALAGES[SUFFIXE])) : celui du modèle final et
    celui de chaque pli (les scores tenus). Le nom de l'exemplaire est « <version><SUFFIXE> ».
    """
    SUFFIXE = ""

    def __init__(self, origine: Etape1):     # sans Etape1.__init__ : rien n'est appris
        self.origine = origine
        for a in ("campagnes", "variante", "graine", "epoques", "version", "dims", "infos", "modele", "plis",
                  "empreinte", "empreintes", "tenues"):
            setattr(self, a, getattr(origine, a))
        self.exemplaire = origine.exemplaire + self.SUFFIXE
        notees = self.modele.notees
        identite = RECALAGES[self.SUFFIXE]

        def calage(campagnes: list[str]) -> Calage:
            return Calage([s for c in campagnes for _, s in self.tenues[c]], self.variante, notees, self.version,
                          par_identite=identite)
        self.calage = calage(self.campagnes)
        self.calages_sans = {c: calage([c2 for c2 in self.campagnes if c2 != c]) for c in self.campagnes}
        self._tenus: dict[tuple, list] = {}
        self._recales = {self.SUFFIXE: self}

    def recale(self, suffixe: str) -> "Recale":
        return self if suffixe == self.SUFFIXE else self.origine.recale(suffixe)

    def sortie(self, donnees: dict) -> Sortie:
        """Les résidus du modèle final de l'exemplaire (le même cache)."""
        return self.origine.sortie(donnees)

    def tenus(self, choix: dict | None = None) -> list[tuple[str, str, float]]:
        """Comme Etape1.tenus, sous le choix de l'exemplaire recalé par défaut (choix_exemplaire)."""
        return super().tenus(choix or choix_exemplaire(self.exemplaire))


class ParSorte(Recale):
    """
    L'exemplaire, ses résidus calés PAR SORTE : le classement de la variante u (§17), sur
    l'exemplaire v2 ; médiane et échelle par (sorte, colonne) et (relation, colonne), κ et
    τ, comme en version 1 (Calage(..., par_identite=False)). Choix par défaut B5/H2/V0.
    """
    SUFFIXE = PAR_SORTE


class ParIdentite(Recale):
    """
    L'exemplaire, ses résidus calés PAR IDENTITÉ : l'alarme de la variante u1 (§18), sur
    l'exemplaire v1 ; exactement la méthode de v2 (Calage(..., par_identite=True) :
    temoin_noeud.identite et temoin_noeud.echelles, plancher par sorte, repli par sorte pour
    une identité sans normal). Choix par défaut B2/H0/V1, celui de l'alarme de v12.
    """
    SUFFIXE = PAR_IDENTITE


class Tete(Recale):
    """
    u2 (§19) : une tête du réseau à deux échelles, avec SES résidus et SON calage. Le modèle final
    et les plis sont ceux du réseau, vus par cette tête (VueTete : les mêmes poids, rien n'est
    appris ni copié) ; les empreintes sont celles du réseau. Les résidus tenus hors pli sont ceux de
    SA tête (les normales de chaque campagne notées par le pli appris sans elle, §3.1), calés
    PAR IDENTITÉ (tête brute, la méthode de v2) ou PAR SORTE (tête asinh, la méthode de v1) :
    Calage(..., par_identite=RECALAGES[SUFFIXE]), le calage final et celui de chaque pli. Le nom de
    l'exemplaire est « double:brute » ou « double:asinh ».
    """
    SUFFIXE = ""
    TETE = ""

    def __init__(self, origine: Etape1):     # sans Etape1.__init__ ni Recale.__init__ : rien n'est appris
        if not VERSIONS[origine.version].get("tetes"):
            raise ValueError(f"{self.SUFFIXE} : l'exemplaire {origine.exemplaire} n'a pas de têtes (u2, §19)")
        self.origine = origine
        for a in ("campagnes", "variante", "graine", "epoques", "version", "dims", "infos", "empreinte", "empreintes"):
            setattr(self, a, getattr(origine, a))
        self.exemplaire = origine.exemplaire + self.SUFFIXE
        self.modele = self.envelopper(origine.modele)
        self.plis = {c: self.envelopper(p) for c, p in origine.plis.items()}
        self.tenues = {c: [(f["id"], residus(self.plis[c], f["donnees"])) for f in origine.normales if f["campagne"] == c]
                       for c in self.campagnes}
        notees = self.modele.notees
        identite = RECALAGES[self.SUFFIXE]

        def calage(campagnes: list[str]) -> Calage:
            return Calage([s for c in campagnes for _, s in self.tenues[c]], self.variante, notees, self.version,
                          par_identite=identite)
        self.calage = calage(self.campagnes)
        self.calages_sans = {c: calage([c2 for c2 in self.campagnes if c2 != c]) for c in self.campagnes}
        self._sorties: dict[int, tuple[dict, Sortie]] = {}
        self._tenus: dict[tuple, list] = {}
        self._recales = {self.SUFFIXE: self}

    def envelopper(self, modele: Reconstructeur) -> VueTete:
        """Un réseau double (le final, un pli, un modèle « sans c ni c' » de gnn_exemples) vu par cette tête."""
        return VueTete(modele, self.TETE)

    def sortie(self, donnees: dict) -> Sortie:
        """Les résidus de SA tête sur le modèle final (gardés par objet, comme Etape1.sortie)."""
        return Etape1.sortie(self, donnees)


class TeteBrute(Tete):
    """u2 (§19) : la tête brute (comme v2), calée PAR IDENTITÉ : l'alarme, sous B2/H0/V1."""
    SUFFIXE = TETE_BRUTE
    TETE = TETES[0]


class TeteAsinh(Tete):
    """u2 (§19) : la tête asinh (comme v1), calée PAR SORTE : le classement, sous B5/H2/V0."""
    SUFFIXE = TETE_ASINH
    TETE = TETES[1]


_CACHE: dict[tuple, Etape1] = {}


def _cle_cache(normales: list[dict], variante: str, graine: int, epoques: int, version: str = MODELE_DEFAUT) -> tuple:
    return (version, variante, graine, epoques, frozenset(f["id"] for f in normales))


def _normales(fen: list[dict]) -> list[dict]:
    return [f for f in fen if f["jeu"] == "apprentissage" and f["etiquette"] == "normale"]


def etape1(fen: list[dict], fige: dict, variante: str = "complet", graine: int = 0,
           epoques: int = EPOQUES, version: str = MODELE_DEFAUT) -> Etape1:
    """L'étape 1 apprise sur les normales d'apprentissage de `fen`, gardée en mémoire. Un
    exemplaire « v2:sorte » (variante u, §17) : l'étape 1 v2, calée par sorte (ParSorte) ;
    « v1:identite » (variante u1, §18) : l'étape 1 v1, calée par identité (ParIdentite) ;
    « double:brute », « double:asinh » (u2, §19) : une tête du réseau double (TeteBrute,
    TeteAsinh)."""
    for suffixe in RECALAGES:
        if version.endswith(suffixe):
            return etape1(fen, fige, variante, graine, epoques, modele_de(version)).recale(suffixe)
    normales = _normales(fen)
    cle = _cle_cache(normales, variante, graine, epoques, version)
    if cle not in _CACHE:
        _CACHE[cle] = Etape1(normales, fige, variante, graine, epoques, version=version)
    return _CACHE[cle]


def preparer(fen: list[dict], fige: dict, graines: int = 5, variantes=tuple(VARIANTES),
             epoques: int = EPOQUES, version: str = VERSION) -> float:
    """Tous les entraînements manquants en une fois, en parallèle. Rend la durée (s).
    Une version combinée (v12) apprend ses deux exemplaires (v2 et v1), l'un après l'autre."""
    debut = time.perf_counter()
    normales = _normales(fen)
    dims = dimensions(fige)
    for mv in modeles_de(version):
        a_faire, taches = [], []
        for v in variantes:
            for g in range(graines):
                cle = _cle_cache(normales, v, g, epoques, mv)
                if cle in _CACHE:
                    continue
                t = _taches(normales, dims, v, g, epoques, mv)
                a_faire.append((cle, v, g, len(taches), len(t)))
                taches += t
        if not taches:
            continue
        graphes = {id(f["donnees"]): convertir(f["donnees"], VERSIONS[mv]["asinh"]) for f in normales}
        etats = entrainer_tous(taches, graphes)
        for cle, v, g, debut_t, n in a_faire:
            _CACHE[cle] = Etape1(normales, fige, v, g, epoques, etats=etats[debut_t:debut_t + n], version=mv)
    return time.perf_counter() - debut


def empreintes(fen: list[dict], fige: dict, graines: int = 5, epoques: int = EPOQUES, version: str = VERSION,
               variantes=tuple(VARIANTES), avec_exemples: bool = True) -> dict[str, str]:
    """
    {clé : sha256 de torch.save en mémoire (§8)} de tous les modèles qui entrent dans les
    décisions (decision_c.empreintes_du_gnn) : pour chaque variante de methodes(), chaque
    graine et chaque exemplaire (v12 : l'alarme v2 et le classement v1 ; u : le seul
    exemplaire v2, calé deux fois ; u1 : le seul exemplaire v1, calé deux fois ; u2 : le seul
    réseau double, ses deux têtes calées chacune à sa façon), le modèle
    final ET chaque pli (ils calent le seuil) ; et, pour « GNN, avec exemples » (complet),
    les modèles « sans c ni c' » du modèle de l'alarme, qui calent le seuil de sa forêt
    (gnn_exemples). Ce qui manque est appris (mêmes caches que les réponses). La forêt et
    les régressions (scikit-learn) n'ont pas d'empreinte : elles se refont, déterministes
    par graine, sur ces modèles.
    """
    preparer(fen, fige, graines, variantes, epoques, version)
    va, vc = exemplaires(version)
    if version in UNIQUES:           # un seul modèle : ses empreintes une fois
        roles = [(UNIQUES[version]["modele"], UNIQUES[version].get("role", "alarme par identité et classement par sorte"))]
    else:
        roles = [(va, "alarme et classement")] if va == vc else [(va, "alarme"), (vc, "classement")]
    out = {}
    for v in variantes:
        for g in range(graines):
            for mv, role in roles:
                e1 = etape1(fen, fige, v, g, epoques, mv)
                for nom, sha in e1.empreintes.items():
                    out[f"{version} {v} exemplaire {mv} ({role}) graine {g} {nom}"] = sha
    if avec_exemples:
        import gnn_exemples           # import paresseux : gnn_exemples importe gnn
        gnn_exemples.preparer_paires(fen, fige, graines, ("complet",), epoques, version)
        normales = _normales(fen)
        for g in range(graines):
            e1 = etape1(fen, fige, "complet", g, epoques, va)
            for (a, b), etat in gnn_exemples._ETATS_PAIRES[gnn_exemples._cle_e1(e1, normales)].items():
                out[f"{version} complet exemplaire {modele_de(va)} (alarme, avec exemples) graine {g} modèle sans {a} "
                    f"ni {b}"] = empreinte(etat)
    return out


# ------------------------------------------------------------------------------
# L'étape 2 et la réponse
# ------------------------------------------------------------------------------
def profil(sortie: Sortie, calage: Calage) -> list[float]:
    """Le profil d'une fenêtre, sans identité : pour chaque sorte et chaque colonne
    d'état (absents compris), puis chaque relation notée et chaque colonne, le plus
    grand et le plus petit z signé, compressés (tn._c)."""
    z_n, _, z_e, _ = ecarts(sortie, calage)
    out = []
    for k in SORTES:
        z = z_n[k]
        for c in range(len(calage.med_n[k])):
            vals = z[:, c][~np.isnan(z[:, c])] if len(z) else np.zeros(0)
            out += [tn._c(float(vals.max())), tn._c(float(vals.min()))] if len(vals) else [0.0, 0.0]
    for rel in calage.notees:
        z = z_e[rel]
        for c in range(len(calage.med_e[rel])):
            out += [tn._c(float(z[:, c].max())), tn._c(float(z[:, c].min()))] if len(z) else [0.0, 0.0]
    return out


def budget_mis_a_l_echelle(budget, n: int) -> int:
    """b sur n minutes pour un budget écrit sur 249 (un nom de BUDGETS, ou un nombre)."""
    b249 = BUDGETS[budget] if isinstance(budget, str) else int(budget)
    return int(math.floor(b249 * n / MINUTES_BUDGET + 0.5))


def seuil_budget(scores: list[float], b: int) -> float:
    """Le seuil qui fait sonner exactement b scores tenus s'il n'y a pas d'égalité."""
    s = sorted(scores, reverse=True)
    return s[b] if b < len(s) else -math.inf


class GNN:
    """
    La méthode, comme un témoin : fabriquée sur toutes les fenêtres (elle filtre
    elle-même l'apprentissage), elle répond fenêtre par fenêtre sur les seuls
    nombres, flèches et noms de la fenêtre.

    Deux étapes 1 : `etape1_alarme` (son score de fenêtre sous `choix_alarme` fait
    l'alarme, ses profils d'écart la cause) et `etape1` (ses scores sous `choix` font
    le classement). Pour v1, v2, v3, c'est la même, sous le même choix ; pour v12
    (écart E-5, §15), l'exemplaire v2 sous son choix, et l'exemplaire v1 sous B5/H2/V0 ;
    pour u (§17), l'exemplaire v2 sous son choix, et le même calé par sorte (ParSorte)
    sous B5/H2/V0 ; pour u1 (§18), l'exemplaire v1 calé par identité (ParIdentite) sous
    B2/H0/V1, et le même exemplaire v1 sous B5/H2/V0 (celui de v12) ; pour u2 (§19), la tête
    brute du réseau double calée par identité (TeteBrute) sous B2/H0/V1, et sa tête asinh
    calée par sorte (TeteAsinh) sous B5/H2/V0.
    """

    def __init__(self, fen: list[dict], fige: dict, graine: int = 0, variante: str = "complet",
                 budget=None, reglage: str = "avec exemples", epoques: int = EPOQUES, choix: dict | None = None,
                 version: str = VERSION):
        if reglage not in tn.REGLAGES:
            raise ValueError(f"réglage inconnu : {reglage}")
        charger_echelle(fige)
        self.reglage, self.variante, self.budget, self.version = reglage, variante, budget, version
        va, vc = exemplaires(version)
        self.choix = dict(choix or CHOIX_VERSIONS[version])
        self.choix_alarme = dict(self.choix) if va == vc else dict(choix_exemplaire(va))
        garde = [f for f in fen if f["jeu"] == "apprentissage" and f["etiquette"] not in juge.ECARTEES]
        pannes = [f for f in garde if f["etiquette"] == "panne"]
        self.etape1 = etape1(fen, fige, variante, graine, epoques, vc)
        self.etape1_alarme = self.etape1 if va == vc else etape1(fen, fige, variante, graine, epoques, va)
        self.combinee = va != vc

        # L'alarme : les scores tenus hors pli (gardés pour recaler à tout budget).
        self.tenus = self.etape1_alarme.tenus(self.choix_alarme)
        s = [x for _, _, x in self.tenus]
        self.seuil_propre = _q95(s)
        self.calage_propre = (sum(1 for x in s if x > self.seuil_propre), len(s))
        if budget is None:
            self.seuil = self.seuil_propre
            self.calage_alarme = self.calage_propre
        else:
            b = budget_mis_a_l_echelle(budget, len(s))
            self.seuil = seuil_budget(s, b)
            self.calage_alarme = (sum(1 for x in s if x > self.seuil), len(s))
            self.budget_b = b
            self.calage_budget = self.calage_alarme

        # L'étape 2 : prototypes sur les profils d'écart du modèle final (de l'alarme), rejet par injection.
        self.prototypes, self.seuil_rejet, self.calage_rejet = None, math.inf, (0, 0)
        if reglage == "avec exemples" and pannes:
            e1a = self.etape1_alarme
            cal = e1a.calage
            profils = {f["id"]: profil(e1a.sortie(f["donnees"]), cal) for f in pannes}
            self.prototypes = tn.Prototypes([profils[f["id"]] for f in pannes], [f["cause"] for f in pannes])
            bien = []
            injections = sorted({(f["campagne"], f["injection"]) for f in pannes})
            for g in injections:
                reste = [f for f in pannes if (f["campagne"], f["injection"]) != g]
                if not reste:
                    continue
                protos = tn.Prototypes([profils[f["id"]] for f in reste], [f["cause"] for f in reste])
                for f in (f for f in pannes if (f["campagne"], f["injection"]) == g):
                    cause, d = protos.plus_proche(profils[f["id"]])
                    if cause == f["cause"]:
                        bien.append(d)
            self.seuil_rejet = _q95(bien) if bien else math.inf
            self.calage_rejet = (len(injections), len(bien))

    def classement(self, donnees: dict) -> tuple[dict, float, dict]:
        """(scores du classement, score de fenêtre de l'exemplaire du classement, diagnostic)."""
        return noter_noeuds(self.etape1.sortie(donnees), self.etape1.calage, self.choix)

    def score_alarme(self, donnees: dict) -> float:
        """Le score de fenêtre de l'exemplaire de l'alarme, sous son choix."""
        return noter_noeuds(self.etape1_alarme.sortie(donnees), self.etape1_alarme.calage, self.choix_alarme)[1]

    def repondre(self, donnees: dict) -> dict:
        scores, s_c, diag = self.classement(donnees)
        s = self.score_alarme(donnees) if self.combinee else s_c
        alarme = bool(s > self.seuil)
        brute = None
        if not alarme:
            cause = "normale"
        elif self.reglage == "sans exemples" or self.prototypes is None:
            cause = "inconnue"
        else:
            e1a = self.etape1_alarme
            brute, d = self.prototypes.plus_proche(profil(e1a.sortie(donnees), e1a.calage))
            cause = brute if d <= self.seuil_rejet else "inconnue"
        return {"alarme": alarme, "cause": cause, "scores": scores, "_S": s, "_S_classement": s_c,
                "_premier": diag["premier"], "_racine": diag["racines"], "_pointeurs": diag["pointeurs"],
                "_sans_rejet": brute}


NOMS_DECISION = ("GNN, sans exemples", "GNN, sans exemples, budget de la règle",
                 "GNN, avec exemples", "GNN, avec exemples, budget de la règle")


def noms_decision(version: str = VERSION) -> tuple[str, ...]:
    """Les quatre noms qu'attend decision_c pour cette version : NOMS_DECISION, « GNN » en
    tête remplacé par prefixe(version) (u : « GNN unique, sans exemples »…)."""
    return tuple(prefixe(version) + n[len("GNN"):] for n in NOMS_DECISION)


def methodes(fige: dict, epoques: int = EPOQUES, version: str = VERSION,
             variantes=tuple(v for v in VARIANTES if v != "complet")) -> list[tuple[str, object, bool]]:
    """(nom, fabrique(fen, graine), tire au hasard) : noms commençant par « GNN »
    (decision_c.methodes), les quatre qu'attend decision_c (NOMS_DECISION, écart E-2) :
      « GNN, sans exemples »                   l'étape 1 seule (v12 : alarme v2, classement v1), seuil propre ;
      « GNN, sans exemples, budget de la règle »  la même, θ_21 ;
      « GNN, avec exemples »                   gnn_exemples sur la même version (écart E-2, rejet E-4) ;
      « GNN, avec exemples, budget de la règle »  la même, ses deux alarmes calées ensemble à 21/249 ;
    puis les variantes (« GNN sans aucune arête »… : sans exemples, seuil propre), pour la
    décision 1 et la ligne 0 de l'axe (d). Pour u (§17), les mêmes noms, « GNN unique » en
    tête au lieu de « GNN » (noms_decision, prefixe) ; pour u1 (§18), « GNN unique u1 »."""
    import gnn_exemples           # import paresseux : gnn_exemples importe gnn
    noms_d, p = noms_decision(version), prefixe(version)
    out = [(noms_d[0], lambda fen, g: GNN(fen, fige, graine=g, reglage="sans exemples", epoques=epoques,
                                          version=version), True),
           (noms_d[1], lambda fen, g: GNN(fen, fige, graine=g, reglage="sans exemples", budget="règle",
                                          epoques=epoques, version=version), True)]
    for nom, fab, hasard in gnn_exemples.methodes(fige, epoques, version, budgets=True):
        if not nom.startswith("GNN"):
            raise ValueError(f"gnn_exemples.methodes : « {nom} » ne commence pas par « GNN »")
        out.append((p + nom[len("GNN"):], fab, hasard))
    for v in variantes:
        if v != "complet":
            out.append((f"{p} {v}", lambda fen, g, v=v: GNN(fen, fige, graine=g, variante=v, reglage="sans exemples",
                                                            epoques=epoques, version=version), True))
    noms = [n for n, _, _ in out]
    if noms[:4] != list(noms_d):
        raise ValueError(f"gnn.methodes : {noms[:4]} au lieu de {list(noms_d)}")
    return out


# ------------------------------------------------------------------------------
# Le scellé
# ------------------------------------------------------------------------------
def _git_lecture(*args: str) -> subprocess.CompletedProcess:
    """git en lecture seule, depuis la racine du dépôt (comme decision_c._git)."""
    return subprocess.run(["git", "-C", str(HERE.parent), *args], capture_output=True, text=True)


def fichier_empreintes_unique(version: str) -> str:
    """graphe_en/gnn-empreintes-<version>.txt, les empreintes d'une variante unique (decision_c
    --empreintes --variante), commitées avec gnn-fige-2."""
    return f"gnn-empreintes-{version}.txt"


def scelle_ouvert(version: str | None = None) -> bool:
    """Sans version : l'étiquette gnn-fige existe-t-elle ? (lecture seule, comme decision_c._git)
    Avec une version (le vrai test de cette version) : il faut EN PLUS l'étiquette gnn-fige-2
    bien posée (raisons_scelle_2), pour TOUTE version (u, u1, u2 compris) : l'alarme de v12 est
    celle de u, son classement celui de u1, v1 et v2 sont leurs modèles mêmes (§17, §18) ; le
    vrai test de v12 (la première ouverture) n'est regardé qu'après gnn-fige-2 (§19.3)."""
    r = subprocess.run(["git", "-C", str(HERE.parent), "rev-parse", "-q", "--verify",
                        f"refs/tags/{ETIQUETTE_SCELLE}"], capture_output=True, text=True)
    ouvert = r.returncode == 0 and bool(r.stdout.strip())
    if not ouvert or version is None:
        return ouvert
    return not raisons_scelle_2(version)


def raisons_scelle_2(version: str) -> list[str]:
    """Ce qui ferme encore le vrai test d'une version, gnn-fige existant (§17–§19) ; rien s'il
    est ouvert :
      - gnn-fige-2 existe, posée APRÈS gnn-fige (gnn-fige ancêtre, sur un autre commit) ;
      - elle porte les empreintes d'UNE seule variante unique (graphe_en/gnn-empreintes-<w>.txt,
        §18 : une seule seconde lecture) : pour u, u1 et u2, celles de cette variante ; pour v12,
        v1, v2, v3, celles de la variante figée, quelle qu'elle soit ;
      - le scellé de la seconde lecture (decision_c.scelle_2_mal_pose), et le même contrôle ici :
        entre gnn-fige et gnn-fige-2, graphe_en/ ne change que dans PERMIS_SCELLE_2 (le code du
        GNN et de la lecture) et les empreintes des variantes uniques ;
      - graphe_en/ inchangé depuis gnn-fige-2 (copie de travail comprise) et aucun .py non suivi
        dans graphe_en/ : le vrai test se lit avec le code figé, comme la seconde lecture
        (decision_c.controle_du_code)."""
    c1 = _git_lecture("rev-parse", "-q", "--verify", f"refs/tags/{ETIQUETTE_SCELLE}^{{commit}}").stdout.strip()
    c2 = _git_lecture("rev-parse", "-q", "--verify", f"refs/tags/{ETIQUETTE_SCELLE_2}^{{commit}}").stdout.strip()
    pourquoi = "" if version in UNIQUES else (f" (le vrai test de {version} montre l'alarme de u et le classement "
                                               f"de u1 : il ne se lit qu'après {ETIQUETTE_SCELLE_2}, §17, §18, §19.3)")
    if not c2:
        return [f"l'étiquette « {ETIQUETTE_SCELLE_2} » n'existe pas{pourquoi}"]
    if not c1 or c1 == c2 or _git_lecture("merge-base", "--is-ancestor", c1, c2).returncode != 0:
        return [f"l'étiquette « {ETIQUETTE_SCELLE_2} » n'est pas posée après « {ETIQUETTE_SCELLE} »{pourquoi}"]
    fichiers = {f"graphe_en/{fichier_empreintes_unique(w)}": w for w in UNIQUES}
    arbre = _git_lecture("ls-tree", "-z", "--name-only", c2, "graphe_en/")
    portees = sorted(n for n in arbre.stdout.split("\0")
                     if n.startswith("graphe_en/" + fichier_empreintes_unique("")[:-len(".txt")]) and n.endswith(".txt"))
    if version in UNIQUES:
        attendu = f"graphe_en/{fichier_empreintes_unique(version)}"
        bien = portees == [attendu]
    else:
        attendu = "les empreintes d'UNE variante unique (" + ", ".join(sorted(fichiers)) + ")"
        bien = len(portees) == 1 and portees[0] in fichiers
    if arbre.returncode != 0 or not bien:
        return [f"« {ETIQUETTE_SCELLE_2} » doit porter {attendu} et aucune autre empreinte de variante unique "
                f"(§18 : une seule variante figée) ; elle porte : {', '.join(portees) or 'aucune'}{pourquoi}"]
    import decision_c as dc      # le même scellé que la seconde lecture (import paresseux, comme T16)
    soucis = list(dc.scelle_2_mal_pose(fichiers[portees[0]]))
    # Le même contrôle ici, par PERMIS_SCELLE_2 : entre gnn-fige et gnn-fige-2, graphe_en/ ne change que
    # dans le code du GNN et les empreintes des variantes uniques.
    permis = {f"graphe_en/{x}" for x in PERMIS_SCELLE_2} | set(fichiers)
    r = _git_lecture("diff", "-z", "--name-only", "--no-renames", c1, c2, "--", "graphe_en/")
    hors_permis = sorted(n for n in r.stdout.split("\0") if n and n not in permis)
    if r.returncode != 0 or hors_permis:
        soucis.append(f"graphe_en/ a changé entre « {ETIQUETTE_SCELLE} » et « {ETIQUETTE_SCELLE_2} » hors de "
                      f"{', '.join(sorted(permis))} : "
                      f"{', '.join(hors_permis) if r.returncode == 0 else 'git diff illisible'}")
    if _git_lecture("diff", "--quiet", c2, "--", "graphe_en/").returncode != 0:
        soucis.append(f"graphe_en/ a changé depuis l'étiquette {ETIQUETTE_SCELLE_2} : le vrai test se lit avec le "
                      f"code figé")
    # git diff ne voit pas un fichier non suivi : aucun .py non suivi dans graphe_en/ (comme decision_c).
    hors = _git_lecture("ls-files", "--others", "--exclude-standard", "--", "graphe_en/*.py").stdout.split()
    if hors:
        soucis.append(f"fichiers Python non suivis dans graphe_en/ : {', '.join(hors)}")
    return soucis


def exiger_scelle(version: str | None = None) -> None:
    """Refus (juge.Refus) si le vrai test de cette version est fermé (scelle_ouvert)."""
    if not scelle_ouvert():
        raise juge.Refus(f"SCELLÉ FERMÉ : l'étiquette « {ETIQUETTE_SCELLE} » n'existe pas ; le vrai test "
                         f"ne se lit qu'une fois le GNN figé (réglages sur juge.validation seulement).")
    if version is not None:
        raisons = raisons_scelle_2(version)
        if raisons:
            raise juge.Refus(f"SCELLÉ FERMÉ pour la version {version} : {'; '.join(raisons)} ; le vrai test ne se lit "
                             f"qu'une fois la variante unique figée à « {ETIQUETTE_SCELLE_2} » (réglages sur "
                             f"juge.validation seulement).")


# ------------------------------------------------------------------------------
# --verifier : T1 à T4, T6, T7 (§8), T12, T13
# ------------------------------------------------------------------------------
def _propre(rep: dict) -> dict:
    return {k: v for k, v in rep.items() if not k.startswith("_")}


def _sans_fleches(donnees: dict) -> dict:
    d = copy.deepcopy(donnees)
    for e in d["edges"].values():
        e["source"], e["target"], e["X"] = [], [], []
    return d


def _nom_de_deploiement(nom: str, rnd: random.Random, pris: set) -> str | None:
    """Un autre nom de pod pour le même Deployment (même service, autre ReplicaSet et
    autre suffixe : même identité pour temoin_noeud.identite) ; None hors Deployment."""
    ident = tn.identite("instance", nom)
    if ident == f"instance:{nom}":
        return None
    while True:
        neuf = (ident.split(":", 1)[1] + "-" + "".join(rnd.choice("bcdf456789") for _ in range(10))
                + "-" + "".join(rnd.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(5)))
        if neuf not in pris and tn.identite("instance", neuf) == ident:
            pris.add(neuf)
            return neuf


def _permuter(donnees: dict, graine: int, tout: bool = True) -> tuple[dict, dict]:
    """Les lignes de chaque sorte et les flèches permutées, les indices réécrits ; `tout` :
    tous les pods et toutes les machines renommés ; sinon (calage par identité, versions
    2 et 3) seuls les pods de Deployment, dans leur service (hachage et suffixe neufs) :
    renommer un StatefulSet ou une machine change son identité, donc son calage.
    (copie, {ancienne clé : nouvelle clé})."""
    rnd = random.Random(graine)
    d = copy.deepcopy(donnees)
    renomme = {}
    hotes = {h: (f"machine-{i:02d}-{rnd.randrange(10**6):06d}" if tout else h)
             for i, h in enumerate(d["nodes"]["host"]["names"])}
    nouvelle_place = {}
    for k in SORTES:
        b = d["nodes"][k]
        n = len(b["names"])
        perm = list(range(n))
        rnd.shuffle(perm)                                   # la place p reçoit l'ancienne ligne perm[p]
        nouvelle_place[k] = {ancien: p for p, ancien in enumerate(perm)}
        for champ in ("keys", "names", "hosts", "X"):
            if isinstance(b.get(champ), list) and len(b[champ]) == n:
                b[champ] = [b[champ][i] for i in perm]
        if k == "instance":
            if tout:
                nouveaux = [f"pod-{rnd.randrange(10**8):08d}-{i}" for i in range(n)]
            else:
                pris = set(b["names"])
                nouveaux = [_nom_de_deploiement(nom, rnd, pris) or nom for nom in b["names"]]
            for vieux, neuf in zip(b["names"], nouveaux):
                renomme[juge._cle(k, vieux)] = juge._cle(k, neuf)
            b["names"] = nouveaux
            b["keys"] = [f"uid-{i}" for i in range(n)]
        if k == "host":
            for vieux in b["names"]:
                renomme[juge._cle(k, vieux)] = juge._cle(k, hotes[vieux])
            b["names"] = [hotes[h] for h in b["names"]]
            b["keys"] = [f"host:{h}" for h in b["names"]]
        if k == "queue":
            for nom in b["names"]:
                renomme[juge._cle(k, nom)] = juge._cle(k, nom)
        if isinstance(b.get("hosts"), list):
            b["hosts"] = [hotes.get(h, h) if h is not None else None for h in b["hosts"]]
    for e in d["edges"].values():
        m = len(e["source"])
        perm = list(range(m))
        rnd.shuffle(perm)
        e["source"] = [nouvelle_place[e["source_kind"]][e["source"][i]] for i in perm]
        e["target"] = [nouvelle_place[e["target_kind"]][e["target"][i]] for i in perm]
        e["X"] = [e["X"][i] for i in perm]
    return d, renomme


def _petit_jeu(fen: list[dict]) -> list[dict]:
    """20 fenêtres de validation : 12 normales d'apprentissage (3 campagnes × 4), 4 pannes
    d'apprentissage (2 injections × 2, deux causes), 2 normales et 2 pannes du test."""
    app = [f for f in fen if f["jeu"] == "apprentissage" and f["etiquette"] == "normale"]
    par = {}
    for f in app:
        par.setdefault(f["campagne"], []).append(f)
    trois = sorted(par, key=lambda c: -len(par[c]))[:3]
    choisies = [x for c in trois for x in par[c][::max(1, len(par[c]) // 4)][:4]]
    pannes = [f for f in fen if f["jeu"] == "apprentissage" and f["etiquette"] == "panne"]
    injections, causes = [], set()
    for f in pannes:
        k = (f["campagne"], f["injection"])
        if f["cause"] not in causes and k not in injections:
            injections.append(k)
            causes.add(f["cause"])
        if len(injections) == 2:
            break
    for k in injections:
        choisies += [f for f in pannes if (f["campagne"], f["injection"]) == k][:2]
    test = [f for f in fen if f["jeu"] == "test" and f["etiquette"] not in juge.ECARTEES]
    choisies += [f for f in test if f["etiquette"] == "normale"][:2] + [f for f in test if f["etiquette"] == "panne"][:2]
    return choisies


def verifier(campagnes: Path, runs: Path, version: str = VERSION) -> int:
    """Les contrôles, pour la version donnée. Une version combinée (v12) passe les
    contrôles d'un modèle (T3, T2 sur la grille et les résidus bruts, T12, T13) pour
    CHACUN de ses exemplaires, les contrôles de la réponse (T1, T2 sur la réponse, T4,
    T6) sur la méthode combinée, et en plus T14 (l'alarme est celle de l'exemplaire v2,
    le classement celui de l'exemplaire v1 sous B5/H2/V0, la cause celle de v2), T15 (les
    empreintes de tous les modèles) et T16 (les noms qu'attend decision_c). La variante u
    (§17) passe les contrôles d'un modèle pour son seul exemplaire v2, T2 et T12 aussi pour
    ce même exemplaire calé par sorte (« v2:sorte »), et T17 au lieu de T14 ; la variante u1
    (§18) de même pour son seul exemplaire v1 et « v1:identite », et T19 ; la variante u2 (§19)
    pour son seul réseau double (T3, T13, T18) et ses deux têtes (T2, T12 : « double:brute »,
    « double:asinh »), et T20. Pour toute version, T6 éprouve le refus du vrai test sans
    gnn-fige, puis sans gnn-fige-2 bien posée (§17–§19). T18 (le nombre de processus) pour
    toute version."""
    _un_fil()
    fige, ecarts_ref, _ = gel.reference()
    if ecarts_ref:
        print(f"REFUS  {ecarts_ref[0]}")
        return 1
    resultats = {}
    mvs = modeles_de(version)
    va, vc = exemplaires(version)

    # T7 : l'empreinte de l'échelle est contrôlée.
    faux = copy.deepcopy(fige)
    faux["echelle"]["sha256"] = "0" * 64
    try:
        charger_echelle(faux)
        t7 = False
    except juge.Refus:
        t7 = True
    charger_echelle(fige)
    resultats["T7 sha256 de l'échelle contrôlé"] = (t7, "une fausse empreinte est refusée, la vraie acceptée")

    fen = juge.validation(juge.lire(fautifs_module.SERIES, campagnes, runs))
    petit = _petit_jeu(fen)
    print(f"# version {version} : {decrire(version)}")
    print(f"# petit jeu : {len(petit)} fenêtres de validation "
          f"({sum(1 for f in petit if f['jeu'] == 'apprentissage' and f['etiquette'] == 'normale')} normales "
          f"d'apprentissage sur {len({f['campagne'] for f in _normales(petit)})} campagnes), 2 époques")

    # T3 : deux entraînements à la même graine, identiques (dans ce processus et dans un autre) ;
    # pour chaque exemplaire.
    dims = dimensions(fige)
    egal = lambda x, y: x.keys() == y.keys() and all(torch.equal(x[k], y[k]) for k in x)
    finals, t3, det3 = {}, True, []
    for mv in mvs:
        asinh = VERSIONS[mv]["asinh"]
        graphes = [convertir(f["donnees"], asinh) for f in _normales(petit)]
        a, info = entrainer(graphes, dims, "complet", 0, 0, 2, mv)
        b, _ = entrainer(graphes, dims, "complet", 0, 0, 2, mv)
        c, _ = entrainer(graphes, dims, "complet", 1, 0, 2, mv)
        [(d_, _)] = entrainer_tous([(tuple(id(f["donnees"]) for f in _normales(petit)), dims, "complet", 0, 0, 2,
                                     mv)],
                                   {id(f["donnees"]): convertir(f["donnees"], asinh) for f in _normales(petit)})
        finals[mv] = a
        ok = egal(a, b) and egal(a, d_) and not egal(a, c)
        t3 = t3 and ok
        det3.append(f"{mv} : même graine identique ici {egal(a, b)}, dans un processus spawn {egal(a, d_)} ; "
                    f"autre graine différente {not egal(a, c)} ; {info['parametres']} paramètres")
    resultats["T3 entraînement déterministe"] = (t3, " ; ".join(det3))

    # T1 : forme de la réponse, pour chaque variante et chaque fenêtre ; flèches vides.
    soucis = []
    preparer(petit, fige, graines=1, variantes=tuple(VARIANTES), epoques=2, version=version)
    modeles = {v: GNN(petit, fige, graine=0, variante=v, epoques=2, version=version) for v in VARIANTES}
    for v, m in modeles.items():
        for f in petit:
            rep = m.repondre(f["donnees"])
            try:
                juge.verifier(f, _propre(rep))
            except ValueError as e:
                soucis.append(f"{v} : {e}")
                continue
            if list(rep["scores"]) != juge.noeuds(f["donnees"]):
                soucis.append(f"{v} : {f['id']} : les clés ne sont pas tous les nœuds")
            if any(not math.isfinite(x) for x in rep["scores"].values()):
                soucis.append(f"{v} : {f['id']} : un score n'est pas fini")
            if not isinstance(rep["alarme"], bool):
                soucis.append(f"{v} : {f['id']} : alarme {type(rep['alarme']).__name__}")
        vide = {"id": "vide", "donnees": _sans_fleches(petit[0]["donnees"])}
        try:
            juge.verifier(vide, _propre(m.repondre(vide["donnees"])))
        except Exception as e:                                   # noqa: BLE001 — tout échec compte
            soucis.append(f"{v} : fenêtre sans flèche : {type(e).__name__} {e}")
    resultats["T1 forme de la réponse"] = (not soucis, f"{len(VARIANTES)} variantes × {len(petit)} fenêtres, "
                                                       f"plus une fenêtre sans aucune flèche"
                                           + (f" ; {len(soucis)} soucis, dont {soucis[0]}" if soucis else ""))

    # T2 : renommer, permuter, réindexer ne change rien (toutes les combinaisons B/H/V), pour
    # chaque exemplaire. Calage par identité (v2, v3) : seuls les pods de Deployment sont
    # renommés (dans leur service), et les résidus bruts du modèle doivent en plus être
    # invariants quand TOUT est renommé (pods, StatefulSet, machines) : aucun nom n'entre
    # dans le modèle. Et la réponse de la méthode (v12 : alarme, S, scores), sous le
    # renommage que permettent tous ses exemplaires.
    pire, pire_res, pire_rep, cas, det2 = 0.0, 0.0, 0.0, 0, []
    tout_rep = not any(par_identite(e) for e in (va, vc))
    for v in ("complet", "sans aucune arête"):
        m = modeles[v]
        for e1 in dict.fromkeys((m.etape1, m.etape1_alarme)):
            tout = not e1.calage.par_identite
            for f in petit[-6:]:
                d2, renomme = _permuter(f["donnees"], 7, tout)
                s1, s2 = e1.sortie(f["donnees"]), e1.sortie(d2)
                for ch in grille():
                    sc1, S1, _ = noter_noeuds(s1, e1.calage, ch)
                    sc2, S2, _ = noter_noeuds(s2, e1.calage, ch)
                    pire = max(pire, abs(S1 - S2), *(abs(sc1[k] - sc2[renomme[k]]) for k in sc1))
                    cas += 1
                d3, renomme3 = _permuter(f["donnees"], 11, True)
                s3 = e1.sortie(d3)
                place1 = {c: i for i, c in enumerate(s1.cles())}
                place3 = {c: i for i, c in enumerate(s3.cles())}
                for k in SORTES:
                    o1, o3 = s1.decal[k], s3.decal[k]
                    for c, i in place1.items():
                        if c.startswith(k + ":"):
                            a1, a3 = s1.res_n[k][i - o1], s3.res_n[k][place3[renomme3[c]] - o3]
                            if not np.array_equal(np.isnan(a1), np.isnan(a3)):
                                pire_res = math.inf
                            else:
                                pire_res = max(pire_res, float(np.nanmax(np.abs(a1 - a3), initial=0.0)))
            det2.append(f"{v} {e1.exemplaire} : " + ("tout renommé" if tout else "pods de Deployment renommés"))
        for f in petit[-6:]:
            d2, renomme = _permuter(f["donnees"], 13, tout_rep)
            r1, r2 = m.repondre(f["donnees"]), m.repondre(d2)
            if r1["alarme"] != r2["alarme"] or r1["cause"] != r2["cause"]:
                pire_rep = math.inf
            pire_rep = max(pire_rep, abs(r1["_S"] - r2["_S"]),
                           *(abs(r1["scores"][k] - r2["scores"][renomme[k]]) for k in r1["scores"]))
    resultats["T2 aucun nom, invariance par permutation"] = (
        pire <= 1e-5 and pire_res <= 1e-5 and pire_rep <= 1e-5,
        f"{cas} cas (2 variantes × {cas // (2 * 6 * 30)} exemplaire(s) × 6 fenêtres × 30 combinaisons ; "
        f"{', '.join(det2)}) ; "
        f"plus grand écart {pire:.2e} ; résidus bruts du modèle, tout renommé : plus grand écart {pire_res:.2e} ; "
        f"réponse de la méthode ({'tout renommé' if tout_rep else 'pods de Deployment renommés'}) : {pire_rep:.2e}")

    # T12 : le calage de la sortie, pour chaque exemplaire. v1 : par sorte, le nom ne compte
    # pas. v2, v3 : par identité (médiane et échelle recalculées ici à part), et repli par
    # sorte pour une identité inconnue (tsdb-mysql-0 et une machine renommées).
    soucis12, n12, det12 = [], 0, []
    for e1 in dict.fromkeys((modeles["complet"].etape1, modeles["complet"].etape1_alarme)):
        cal = e1.calage
        for f in petit[-6:]:
            s1 = e1.sortie(f["donnees"])
            z1 = ecarts(s1, cal)[0]
            d4 = copy.deepcopy(f["donnees"])
            inst, hotes = d4["nodes"]["instance"], d4["nodes"]["host"]
            change = {}
            for i, nom in enumerate(inst["names"]):
                if tn.identite("instance", nom) == f"instance:{nom}":        # un StatefulSet
                    inst["names"][i] = f"inconnu-{i}"
                    change[("instance", i)] = True
            vieux = hotes["names"][0]
            hotes["names"][0] = "machine-inconnue"
            inst["hosts"] = ["machine-inconnue" if h == vieux else h for h in inst["hosts"]]
            change[("host", 0)] = True
            z4 = ecarts(e1.sortie(d4), cal)[0]
            noeuds = s1.identites()[0]
            for k in SORTES:
                for i in range(s1.n[k]):
                    n12 += 1
                    ident = noeuds[k][i]
                    if not cal.par_identite or change.get((k, i)) or ident not in cal.ident_n[k]:
                        attendu = (s1.res_n[k][i] - cal.med_n[k]) / cal.ech_n[k]
                    else:
                        vals = [s.res_n[k][j] for s in cal.sorties for j, x in enumerate(s.identites()[0][k])
                                if x == ident]
                        vals = np.array(vals)
                        attendu = s1.res_n[k][i].copy()
                        for c in range(vals.shape[1]):
                            col = vals[:, c][~np.isnan(vals[:, c])]
                            if len(col) >= tn.MIN_OBS:
                                med = float(np.median(col))
                                ech = cal.ident_n[k][ident][1][c]
                                if ech < tn.echelle(col.tolist()) - 1e-12:
                                    soucis12.append(f"{ident} col {c} : échelle sous tn.echelle")
                                attendu[c] = (attendu[c] - med) / ech
                            else:
                                attendu[c] = (attendu[c] - cal.med_n[k][c]) / cal.ech_n[k][c]
                    zi = z4[k][i] if change.get((k, i)) else z1[k][i]
                    if not np.allclose(zi, attendu, equal_nan=True, atol=1e-9):
                        soucis12.append(f"{e1.exemplaire} {f['id']} {k} {i} ({ident})")
        connus = cal.connues(e1.sortie(petit[-1]["donnees"]))
        det12.append(f"{e1.exemplaire} {'par identité' if cal.par_identite else 'par sorte'}, identités calées dans une "
                     f"fenêtre : {connus[0]}/{connus[1]} nœuds, {connus[2]}/{connus[3]} flèches")
    resultats["T12 calage de la sortie"] = (
        not soucis12, f"{n12} nœuds ({' ; '.join(det12)} ; StatefulSet et machine renommés : repli par sorte)"
        + (f" ; {len(soucis12)} soucis, dont {soucis12[0]}" if soucis12 else ""))

    # T13 : l'empreinte du modèle final est celle du §8 dans toutes les versions : le sha256
    # de torch.save en mémoire du state_dict, sans rien d'autre ; recalculée ici sur
    # l'entraînement de T3 (même jeu, graine 0, rang 0, 2 époques : le modèle final de T1),
    # pour chaque exemplaire.
    ok13, det13 = True, []
    for mv in mvs:
        tampon = io.BytesIO()
        torch.save(finals[mv], tampon)
        refaite = hashlib.sha256(tampon.getvalue()).hexdigest()
        imprimee = etape1(petit, fige, "complet", 0, 2, mv).empreinte
        ok13 = ok13 and imprimee == refaite
        det13.append(f"{mv} : imprimée {imprimee[:16]}, refaite sur torch.save du state_dict {refaite[:16]}")
    resultats["T13 empreinte du §8"] = (ok13, " ; ".join(det13))

    # T4 : θ_b fait sonner exactement b scores tenus (ceux de l'alarme).
    m = modeles["complet"]
    s = [x for _, _, x in m.tenus]
    # Exactement b au-dessus quand il n'y a pas d'égalité à la limite ; jamais plus de b sinon.
    tries = sorted(s, reverse=True)
    libre = lambda b: b == 0 or b == len(s) or tries[b - 1] > tries[b]
    ecarts_b = [b for b in range(len(s) + 1)
                if (n_b := sum(1 for x in s if x > seuil_budget(s, b))) > b or (libre(b) and n_b != b)]
    budgets = {nom: budget_mis_a_l_echelle(nom, len(s)) for nom in BUDGETS}
    egalites = len(s) - len(set(s))
    ok4 = not ecarts_b
    resultats["T4 seuil au budget"] = (ok4, f"b = 0 à {len(s)} sur {len(s)} scores tenus ({egalites} égalités ; exact là où la "
                                            f"limite n'est pas une égalité, jamais plus de b ailleurs), "
                                            f"exacts sauf {ecarts_b or 'aucun'} ; budgets mis à l'échelle {budgets}")

    # T6 : le mode test est refusé sans gnn-fige, puis, pour TOUTE version (§17–§19 : le vrai test de
    # v12 montre l'alarme de u et le classement de u1), sans gnn-fige-2 bien posée (raisons_scelle_2).
    nom6 = "T6 test refusé sans gnn-fige" if not scelle_ouvert() else "T6 test refusé sans gnn-fige-2"
    if scelle_ouvert(version):
        resultats[nom6] = (True, f"gnn-fige et gnn-fige-2 (bien posée pour {version}) existent ici : refus non éprouvé")
    else:
        try:
            exiger_scelle(version)
            t6 = False
        except juge.Refus:
            t6 = True
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = main(["gnn.py", "--test", "--graines", "1", "--epoques", "1", "--sans-temoins", "--version", version])
        raison = f"« {ETIQUETTE_SCELLE} » absente" if not scelle_ouvert() else "; ".join(raisons_scelle_2(version))
        resultats[nom6] = (t6 and code == 1, f"{raison} : exiger_scelle refuse : {t6} ; --test --version {version} "
                                             f"rend le code {code}")

    if version in COMBINEES:
        # T14 : l'alarme de v12 est celle de l'exemplaire v2 (score, seuils propre et au budget,
        # cause), le classement celui de l'exemplaire v1 sous B5/H2/V0 ; sur chaque fenêtre,
        # chaque variante, chaque réglage, seuil propre et budget de la règle.
        soucis14, n14 = [], 0
        if CHOIX_VERSIONS[version] != CHOIX_VERSIONS[vc] or CHOIX_VERSIONS[vc] != {"bout": "B5", "remontee": "H2",
                                                                                     "explication": "V0"}:
            soucis14.append(f"choix du classement {CHOIX_VERSIONS[version]}")
        for v in VARIANTES:
            for reglage in tn.REGLAGES:
                for budget in (None, "règle"):
                    m12 = GNN(petit, fige, graine=0, variante=v, epoques=2, version=version, reglage=reglage,
                              budget=budget)
                    ma = GNN(petit, fige, graine=0, variante=v, epoques=2, version=va, reglage=reglage, budget=budget)
                    mc = GNN(petit, fige, graine=0, variante=v, epoques=2, version=vc, reglage=reglage, budget=budget)
                    if (m12.seuil, m12.seuil_propre, m12.tenus) != (ma.seuil, ma.seuil_propre, ma.tenus):
                        soucis14.append(f"{v} {reglage} {budget} : seuils ou scores tenus de l'alarme")
                    if m12.etape1 is not mc.etape1 or m12.etape1_alarme is not ma.etape1:
                        soucis14.append(f"{v} : les exemplaires ne sont pas ceux de {va} et {vc}")
                    for f in petit:
                        r12, ra, rc = (x.repondre(f["donnees"]) for x in (m12, ma, mc))
                        n14 += 1
                        if (r12["alarme"], r12["cause"], r12["_S"]) != (ra["alarme"], ra["cause"], ra["_S"]):
                            soucis14.append(f"{v} {reglage} {budget} {f['id']} : alarme, cause ou S ≠ {va}")
                        if r12["scores"] != rc["scores"] or r12["_S_classement"] != rc["_S"]:
                            soucis14.append(f"{v} {reglage} {budget} {f['id']} : classement ≠ {vc}")
        resultats["T14 v12 = alarme v2 + classement v1"] = (
            not soucis14, f"{n14} réponses ({len(VARIANTES)} variantes × 2 réglages × 2 seuils × {len(petit)} "
                          f"fenêtres) : alarme, S, cause, seuils identiques à {va} ; scores identiques à {vc} "
                          f"({nom_choix(CHOIX_VERSIONS[version])})"
            + (f" ; {len(soucis14)} soucis, dont {soucis14[0]}" if soucis14 else ""))

    # T15 : les empreintes de tous les modèles (decision_c --empreintes, --ouvrir) : chaque
    # exemplaire, modèle final et plis, et les modèles « sans c ni c' » de l'avec exemples.
    emp = empreintes(petit, fige, 1, 2, version, ("complet",), avec_exemples=True)
    soucis15 = []
    n_plis = len({f["campagne"] for f in _normales(petit)})
    attendues = len(mvs) * (1 + n_plis) + n_plis * (n_plis - 1) // 2
    if len(emp) != attendues:
        soucis15.append(f"{len(emp)} clés au lieu de {attendues}")
    for mv in mvs:
        e1 = etape1(petit, fige, "complet", 0, 2, mv)
        for nom, sha in e1.empreintes.items():
            if sha not in emp.values():
                soucis15.append(f"{mv} {nom} absente")
        tampon = io.BytesIO()
        torch.save(finals[mv], tampon)
        if hashlib.sha256(tampon.getvalue()).hexdigest() != e1.empreintes["modèle final"]:
            soucis15.append(f"{mv} : le modèle final n'est pas celui de T3")
    if len(set(emp.values())) != len(emp):
        soucis15.append("deux modèles ont la même empreinte")
    if any(len(v) != 64 or " " in v for v in emp.values()):
        soucis15.append("une empreinte n'est pas un sha256")
    resultats["T15 empreintes de tous les modèles"] = (
        not soucis15, f"{len(emp)} empreintes (graine 0 : {len(mvs)} exemplaire(s) × (modèle final + {n_plis} plis) "
                      f"+ {n_plis * (n_plis - 1) // 2} modèles « sans c ni c' »), toutes distinctes ; par exemple "
                      f"« {sorted(emp)[0]} »" + (f" ; {len(soucis15)} soucis, dont {soucis15[0]}" if soucis15 else ""))

    # T16 : les noms qu'attend decision_c (les quatre du GNN, puis les variantes), tous « GNN… » ;
    # pour u, ceux de decision_c --variante u (« GNN unique… »).
    noms = [n for n, _, _ in methodes(fige, 2, version)]
    import decision_c as dc
    nd = dc.noms_gnn(version if version in UNIQUES else None)
    attendus = [n for r in dc.REGLAGES for n in (nd["propre"][r], nd["regle"][r])]
    ok16 = set(attendus) <= set(noms) and all(n.startswith("GNN") for n in noms) and len(set(noms)) == len(noms) \
        and nd["sans_arete"] in noms
    resultats["T16 noms de decision_c"] = (ok16, f"{len(noms)} noms : {', '.join(noms[:4])}, puis "
                                                 f"{len(noms) - 4} variantes ; attendus par decision_c présents "
                                                 f"{set(attendus) <= set(noms)}")

    if version in UNIQUES and vc.endswith(PAR_SORTE):
        # T17 : la variante u (§17). (a) L'alarme est celle de v12 à graine égale : le même
        # exemplaire v2 (le même objet), les mêmes seuils, scores tenus, S, alarme et cause, pour
        # chaque variante, chaque réglage, seuil propre et budget de la règle. (b) Le classement
        # est celui des résidus de CE modèle calés PAR SORTE sous B5/H2/V0 : calage refait ici à
        # part sur ses résidus tenus (Calage, par_identite=False), scores et S identiques ; et il
        # diffère du calage par identité sur au moins une fenêtre (le calage compte). (c) Un seul
        # exemplaire : les empreintes de u sont celles de l'exemplaire v2 de v12, et elles seules.
        # (d) Les noms : ceux de v12, « GNN unique » en tête. (e) Déterminisme : tout réappris à
        # neuf (caches vidés), mêmes empreintes et mêmes réponses.
        soucis17, n17, differe, garder = [], 0, 0, []
        choix_u = CHOIX_VERSIONS[version]
        if choix_u != {"bout": "B5", "remontee": "H2", "explication": "V0"} or va != UNIQUES[version]["modele"] \
                or vc != va + PAR_SORTE:
            soucis17.append(f"choix {nom_choix(choix_u)}, exemplaires {va} et {vc}")
        preparer(petit, fige, graines=1, variantes=tuple(VARIANTES), epoques=2, version="v12")
        for v in VARIANTES:
            e2 = etape1(petit, fige, v, 0, 2, va)
            cal = Calage([s_ for c in e2.campagnes for _, s_ in e2.tenues[c]], v, e2.modele.notees, e2.version,
                         par_identite=False)
            if cal.par_identite or any(cal.ident_n.values()) or any(cal.ident_e.values()):
                soucis17.append(f"{v} : le calage par sorte lit une identité")
            for reglage in tn.REGLAGES:
                for budget in (None, "règle"):
                    mu = GNN(petit, fige, graine=0, variante=v, epoques=2, version=version, reglage=reglage,
                             budget=budget)
                    m12 = GNN(petit, fige, graine=0, variante=v, epoques=2, version="v12", reglage=reglage,
                              budget=budget)
                    if mu.etape1_alarme is not e2 or m12.etape1_alarme is not e2:
                        soucis17.append(f"{v} : l'exemplaire de l'alarme n'est pas celui de v12")
                    if mu.etape1.modele is not e2.modele or mu.etape1.plis is not e2.plis \
                            or mu.etape1.empreintes != e2.empreintes or mu.etape1.calage.par_identite:
                        soucis17.append(f"{v} : le classement n'est pas l'exemplaire {va} calé par sorte")
                    if (mu.seuil, mu.seuil_propre, mu.tenus, mu.seuil_rejet) != \
                            (m12.seuil, m12.seuil_propre, m12.tenus, m12.seuil_rejet):
                        soucis17.append(f"{v} {reglage} {budget} : seuils ou scores tenus ≠ v12")
                    for f in petit:
                        ru, r12 = mu.repondre(f["donnees"]), m12.repondre(f["donnees"])
                        n17 += 1
                        if (ru["alarme"], ru["cause"], ru["_S"], ru["_sans_rejet"]) != \
                                (r12["alarme"], r12["cause"], r12["_S"], r12["_sans_rejet"]):
                            soucis17.append(f"{v} {reglage} {budget} {f['id']} : alarme, cause ou S ≠ v12")
                        sortie = e2.sortie(f["donnees"])
                        attendu, s_att, _ = noter_noeuds(sortie, cal, choix_u)
                        if ru["scores"] != attendu or ru["_S_classement"] != s_att:
                            soucis17.append(f"{v} {reglage} {budget} {f['id']} : classement ≠ résidus {va} par sorte")
                        if reglage == "sans exemples" and budget is None \
                                and noter_noeuds(sortie, e2.calage, choix_u)[0] != attendu:
                            differe += 1
        if not differe:
            soucis17.append("le calage par identité donne partout le même classement que le calage par sorte")
        emp_u = empreintes(petit, fige, 1, 2, version, ("complet",), avec_exemples=True)
        emp_12 = empreintes(petit, fige, 1, 2, "v12", ("complet",), avec_exemples=True)
        du_v2 = {sha for k, sha in emp_12.items() if f" exemplaire {va} (" in k}
        if set(emp_u.values()) != du_v2 or len(emp_u) != len(du_v2) \
                or not all(f" exemplaire {va} (" in k and k.startswith(f"{version} ") for k in emp_u):
            soucis17.append(f"empreintes : {len(emp_u)} pour u, {len(du_v2)} de l'exemplaire {va} de v12")
        nu = [n for n, _, _ in methodes(fige, 2, version)]
        n12 = [n for n, _, _ in methodes(fige, 2, "v12")]
        if nu != [PREFIXES[version] + n[len("GNN"):] for n in n12] or tuple(nu[:4]) != noms_decision(version) \
                or dc.VARIANTES_GNN.get(version) != PREFIXES[version]:
            soucis17.append(f"noms : {nu[:4]}")
        # (e) tout réappris à neuf, puis les caches remis (les objets neufs restent vivants : leur id
        # ne doit pas être réemployé par un autre, gnn_exemples.lecteur garde par id).
        e2_avant = etape1(petit, fige, "complet", 0, 2, va)
        net = lambda r: {k: r[k] for k in ("alarme", "cause", "scores", "_S", "_S_classement")}
        m_avant = GNN(petit, fige, graine=0, epoques=2, version=version, reglage="sans exemples")
        rep_avant = {f["id"]: net(m_avant.repondre(f["donnees"])) for f in petit}
        sauve = dict(_CACHE)
        try:
            _CACHE.clear()
            preparer(petit, fige, graines=1, variantes=("complet",), epoques=2, version=version)
            e2_neuf = etape1(petit, fige, "complet", 0, 2, va)
            m_neuf = GNN(petit, fige, graine=0, epoques=2, version=version, reglage="sans exemples")
            garder += [e2_neuf, m_neuf]
            neuf = e2_neuf is not e2_avant and e2_neuf.empreintes == e2_avant.empreintes \
                and all(net(m_neuf.repondre(f["donnees"])) == rep_avant[f["id"]] for f in petit)
        finally:
            _CACHE.clear()
            _CACHE.update(sauve)
        if not neuf:
            soucis17.append("réappris à neuf : autres empreintes ou autres réponses")
        resultats["T17 u : alarme de v12, classement v2 par sorte"] = (
            not soucis17, f"{n17} réponses ({len(VARIANTES)} variantes × 2 réglages × 2 seuils × {len(petit)} "
                          f"fenêtres) : alarme, S, cause, seuils identiques à v12 (même exemplaire {va}) ; scores = "
                          f"résidus {va} calés par sorte ({nom_choix(choix_u)}), recalculés à part ; le calage par "
                          f"identité donnerait d'autres scores sur {differe}/{len(VARIANTES) * len(petit)} fenêtres ; "
                          f"{len(emp_u)} empreintes, celles de l'exemplaire {va} de v12 ; noms « {nu[0]} »… ; "
                          f"réappris à neuf : mêmes empreintes et réponses {neuf}"
            + (f" ; {len(soucis17)} soucis, dont {soucis17[0]}" if soucis17 else ""))

    if version in UNIQUES and va.endswith(PAR_IDENTITE):
        # T19 : la variante u1 (§18). (a) Le classement est celui de v12 à graine égale : le même
        # exemplaire v1 (le même objet), le même choix B5/H2/V0 ; scores, S du classement, premier,
        # racines et pointeurs identiques, pour chaque variante, chaque réglage, seuil propre et
        # budget de la règle. (b) L'alarme est celle de CE modèle v1, ses résidus calés PAR IDENTITÉ
        # (Calage, par_identite=True, la méthode de v2, recalculé ici à part : le calage final et
        # celui de chaque pli) sous B2/H0/V1, le choix de l'alarme de v12 : scores tenus, seuil
        # propre et au budget, S, alarme, et (avec exemples) la cause du prototype le plus proche,
        # tous recalculés à part ; et le calage par identité compte (S autre que par sorte sur au
        # moins une fenêtre). (c) Un seul modèle : les empreintes de u1 sont celles de la version
        # v1 (modèle final, plis, modèles « sans c ni c' »), et celles de ses modèles finals et plis
        # sont celles de l'exemplaire v1 de v12. (d) Les noms : ceux de v12, « GNN unique u1 » en
        # tête. (e) Déterminisme : tout réappris à neuf, mêmes empreintes et mêmes réponses.
        soucis19, n19, differe, garder19 = [], 0, 0, []
        choix_a, choix_c = choix_exemplaire(va), CHOIX_VERSIONS[version]
        m_u1 = UNIQUES[version]["modele"]
        if choix_c != {"bout": "B5", "remontee": "H2", "explication": "V0"} \
                or choix_a != CHOIX_VERSIONS[COMBINEES["v12"]["alarme"]] or vc != m_u1 or va != m_u1 + PAR_IDENTITE \
                or choix_c != CHOIX_VERSIONS["v12"] or vc != COMBINEES["v12"]["classement"]:
            soucis19.append(f"choix {nom_choix(choix_a)} et {nom_choix(choix_c)}, exemplaires {va} et {vc}")
        preparer(petit, fige, graines=1, variantes=tuple(VARIANTES), epoques=2, version="v12")
        garde19 = [f for f in petit if f["jeu"] == "apprentissage" and f["etiquette"] not in juge.ECARTEES]
        pannes19 = [f for f in garde19 if f["etiquette"] == "panne"]
        for v in VARIANTES:
            e1 = etape1(petit, fige, v, 0, 2, vc)
            recal = lambda camps, e1=e1, v=v: Calage([s_ for c in camps for _, s_ in e1.tenues[c]], v,
                                                     e1.modele.notees, e1.version, par_identite=True)
            cal = recal(e1.campagnes)
            if not cal.par_identite or not any(cal.ident_n.values()):
                soucis19.append(f"{v} : le calage par identité ne cale aucune identité")
            tenus_att = [(c, i, noter_noeuds(s_, recal([c2 for c2 in e1.campagnes if c2 != c]), choix_a)[1])
                         for c in e1.campagnes for i, s_ in e1.tenues[c]]
            s_t = [x for _, _, x in tenus_att]
            protos = tn.Prototypes([profil(e1.sortie(f["donnees"]), cal) for f in pannes19],
                                   [f["cause"] for f in pannes19]) if pannes19 else None
            for reglage in tn.REGLAGES:
                for budget in (None, "règle"):
                    mu = GNN(petit, fige, graine=0, variante=v, epoques=2, version=version, reglage=reglage,
                             budget=budget)
                    m12 = GNN(petit, fige, graine=0, variante=v, epoques=2, version="v12", reglage=reglage,
                              budget=budget)
                    ea = mu.etape1_alarme
                    if mu.etape1 is not e1 or m12.etape1 is not e1 or mu.choix != m12.choix:
                        soucis19.append(f"{v} : le classement n'est pas l'exemplaire {vc} de v12")
                    if ea is e1 or ea.modele is not e1.modele or ea.plis is not e1.plis or ea.tenues is not e1.tenues \
                            or ea.empreintes != e1.empreintes or not ea.calage.par_identite \
                            or mu.choix_alarme != m12.choix_alarme or mu.choix_alarme != choix_a:
                        soucis19.append(f"{v} : l'alarme n'est pas l'exemplaire {vc} calé par identité sous "
                                        f"{nom_choix(choix_a)}")
                    seuil_att = _q95(s_t) if budget is None else seuil_budget(s_t, budget_mis_a_l_echelle(budget,
                                                                                                        len(s_t)))
                    if mu.tenus != tenus_att or mu.seuil != seuil_att or mu.seuil_propre != _q95(s_t):
                        soucis19.append(f"{v} {reglage} {budget} : scores tenus ou seuils ≠ recalcul par identité")
                    for f in petit:
                        ru, r12 = mu.repondre(f["donnees"]), m12.repondre(f["donnees"])
                        n19 += 1
                        cles19 = ("scores", "_S_classement", "_premier", "_racine", "_pointeurs")
                        if any(ru[k] != r12[k] for k in cles19):
                            soucis19.append(f"{v} {reglage} {budget} {f['id']} : classement ≠ v12")
                        sortie = e1.sortie(f["donnees"])
                        s_att = noter_noeuds(sortie, cal, choix_a)[1]
                        if ru["_S"] != s_att or ru["alarme"] != bool(s_att > seuil_att):
                            soucis19.append(f"{v} {reglage} {budget} {f['id']} : S ou alarme ≠ recalcul par identité")
                        if reglage == "avec exemples" and ru["alarme"] and protos is not None \
                                and ru["_sans_rejet"] != protos.plus_proche(profil(sortie, cal))[0]:
                            soucis19.append(f"{v} {reglage} {budget} {f['id']} : prototype ≠ recalcul par identité")
                        if reglage == "sans exemples" and budget is None \
                                and noter_noeuds(sortie, e1.calage, choix_a)[1] != s_att:
                            differe += 1
        if not differe:
            soucis19.append("le calage par sorte donne partout le même S que le calage par identité")
        emp_u1 = empreintes(petit, fige, 1, 2, version, ("complet",), avec_exemples=True)
        emp_v1 = empreintes(petit, fige, 1, 2, vc, ("complet",), avec_exemples=True)
        emp_12 = empreintes(petit, fige, 1, 2, "v12", ("complet",), avec_exemples=True)
        du_v1 = {sha for k, sha in emp_12.items() if f" exemplaire {vc} (" in k}
        sans_paires = {sha for k, sha in emp_u1.items() if "(alarme, avec exemples)" not in k}
        if sorted(emp_u1.values()) != sorted(emp_v1.values()) or sans_paires != du_v1 \
                or not all(f" exemplaire {vc} (" in k and k.startswith(f"{version} ") for k in emp_u1):
            soucis19.append(f"empreintes : {len(emp_u1)} pour u1, {len(emp_v1)} de la version {vc}, {len(du_v1)} de "
                            f"l'exemplaire {vc} de v12")
        nu = [n for n, _, _ in methodes(fige, 2, version)]
        n12 = [n for n, _, _ in methodes(fige, 2, "v12")]
        if nu != [PREFIXES[version] + n[len("GNN"):] for n in n12] or tuple(nu[:4]) != noms_decision(version) \
                or dc.VARIANTES_GNN.get(version) != PREFIXES[version] \
                or set(nu) & {n for n, _, _ in methodes(fige, 2, "u")}:
            soucis19.append(f"noms : {nu[:4]}")
        # (e) tout réappris à neuf, puis les caches remis (comme T17).
        e1_avant = etape1(petit, fige, "complet", 0, 2, vc)
        net = lambda r: {k: r[k] for k in ("alarme", "cause", "scores", "_S", "_S_classement")}
        m_avant = GNN(petit, fige, graine=0, epoques=2, version=version, reglage="sans exemples")
        rep_avant = {f["id"]: net(m_avant.repondre(f["donnees"])) for f in petit}
        sauve = dict(_CACHE)
        try:
            _CACHE.clear()
            preparer(petit, fige, graines=1, variantes=("complet",), epoques=2, version=version)
            e1_neuf = etape1(petit, fige, "complet", 0, 2, vc)
            m_neuf = GNN(petit, fige, graine=0, epoques=2, version=version, reglage="sans exemples")
            garder19 += [e1_neuf, m_neuf]
            neuf19 = e1_neuf is not e1_avant and e1_neuf.empreintes == e1_avant.empreintes \
                and m_neuf.etape1_alarme.origine is e1_neuf \
                and all(net(m_neuf.repondre(f["donnees"])) == rep_avant[f["id"]] for f in petit)
        finally:
            _CACHE.clear()
            _CACHE.update(sauve)
        if not neuf19:
            soucis19.append("réappris à neuf : autres empreintes ou autres réponses")
        resultats["T19 u1 : classement de v12, alarme v1 par identité"] = (
            not soucis19, f"{n19} réponses ({len(VARIANTES)} variantes × 2 réglages × 2 seuils × {len(petit)} "
                          f"fenêtres) : scores, S du classement, premier, racines identiques à v12 (même exemplaire "
                          f"{vc}, {nom_choix(choix_c)}) ; scores tenus, seuils, S, alarme et prototype = résidus {vc} "
                          f"calés par identité ({nom_choix(choix_a)}), recalculés à part ; le calage par sorte "
                          f"donnerait un autre S sur {differe}/{len(VARIANTES) * len(petit)} fenêtres ; "
                          f"{len(emp_u1)} empreintes, celles de la version {vc} (dont {len(du_v1)} de l'exemplaire "
                          f"{vc} de v12) ; noms « {nu[0]} »… ; réappris à neuf : mêmes empreintes et réponses {neuf19}"
            + (f" ; {len(soucis19)} soucis, dont {soucis19[0]}" if soucis19 else ""))

    if version in UNIQUES and VERSIONS[UNIQUES[version]["modele"]].get("tetes"):
        # T20 : la variante u2 (§19). (a) Les formes : l'entrée aux deux échelles (la brute = convertir sans
        # asinh, puis l'asinh = convertir avec, bout à bout ; présence et flèches une fois), l'encodeur, le
        # canal d'arête, les deux têtes (les mêmes décodeurs dupliqués, distincts), les sorties de chaque tête ;
        # le nombre de paramètres. (b) La perte = ½ (L_v2 + L_v1), recalculée à la main sur un petit lot
        # (Huber δ = 1, 0,5 × BCE de présence, flèches, moyennes par sorte et par relation, écrites ici sans
        # F.huber_loss ni F.binary_cross_entropy_with_logits) ; son gradient atteint les deux têtes. (c) Le
        # déterminisme : les mêmes entraînements en 1 et en 3 processus, mêmes empreintes, celles de l'étape 1
        # déjà apprise ; tout réappris à neuf (caches vidés), mêmes empreintes et mêmes réponses. (d) Chaque tête
        # lit SON échelle : le résidu d'un nœud et de ses flèches entrantes, recalculé à la main par une passe du
        # réseau où ce nœud seul est masqué, contre la cible brute (tête brute) et la cible asinh (tête asinh).
        # (e) L'alarme de u2 est la tête brute calée PAR IDENTITÉ sous B2/H0/V1 (résidus des plis, calages,
        # scores tenus, seuils propre et au budget, S, alarme et prototype recalculés à part), le classement la
        # tête asinh calée PAR SORTE sous B5/H2/V0 (scores recalculés à part), pour chaque variante, réglage et
        # seuil ; les deux têtes comptent (l'autre tête donnerait un autre S, d'autres scores). (f) Un seul
        # réseau : les empreintes de u2 sont celles du réseau double (modèle final, plis, modèles « sans c ni
        # c' »), aucune de v1 ni de v2 ; les modèles « sans c ni c' » sont des réseaux doubles vus par la tête
        # brute, leur monde calé par identité. (g) Les noms : ceux de v12, « GNN unique u2 » en tête, distincts
        # de ceux de u et de u1.
        import gnn_exemples as gx      # import paresseux : gnn_exemples importe gnn
        soucis20, garder20 = [], []
        m_u2 = UNIQUES[version]["modele"]
        ed = etape1(petit, fige, "complet", 0, 2, m_u2)
        res = ed.modele
        de, dcx, dr = dims["etat"], dims["ctx"], dims["rel"]
        # (a) les formes
        for f in petit[:3] + [{"donnees": _sans_fleches(petit[0]["donnees"])}]:
            gb, ga, gd = (convertir(f["donnees"], False), convertir(f["donnees"], True),
                          convertir(f["donnees"], DEUX_ECHELLES))
            for k in SORTES:
                if not (torch.equal(gd.x[k], torch.cat([gb.x[k], ga.x[k]], 1)) and torch.equal(gd.p[k], gb.p[k])
                        and torch.equal(gd.ctx[k], torch.cat([gb.ctx[k], ga.ctx[k]], 1))
                        and torch.equal(ga.x[k], torch.asinh(gb.x[k])) and torch.equal(ga.ctx[k], torch.asinh(gb.ctx[k]))
                        and gd.x[k].shape[1] == 2 * de[k] and gd.p[k].shape[1] == de[k]
                        and gd.ctx[k].shape[1] == 2 * dcx[k] and gd.n[k] == gb.n[k]):
                    soucis20.append(f"entrée {k}")
            for r in RELATIONS:
                if not (torch.equal(gd.ea[r], torch.cat([gb.ea[r], ga.ea[r]], 1)) and torch.equal(gd.ei[r], gb.ei[r])
                        and torch.equal(ga.ea[r], torch.asinh(gb.ea[r])) and gd.ea[r].shape[1] == 2 * dr[r]):
                    soucis20.append(f"entrée {r}")
        for k in SORTES:
            if res.enc[k].in_features != 3 * de[k] + 2 * dcx[k] + 1:
                soucis20.append(f"encodeur {k} : {res.enc[k].in_features} entrées")
            for t in TETES:
                dk = res.decodeurs(t)[0][k]
                if dk[0].in_features != H or dk[-1].out_features != 2 * de[k]:
                    soucis20.append(f"décodeur {t} {k}")
        for r in res.canal:
            if res.phi[r][0].in_features != 2 * dr[r] + 1:
                soucis20.append(f"canal {r} : {res.phi[r][0].in_features} entrées")
        for r in res.notees:
            for t in TETES:
                d_r = res.decodeurs(t)[1][r]
                if d_r[0].in_features != 2 * H or d_r[-1].out_features != dr[r]:
                    soucis20.append(f"décodeur {t} {r}")
        forme = lambda mod: [tuple(p.shape) for p in mod.parameters()]
        if forme(res.dec) != forme(res.dec_asinh) or forme(res.dec_e) != forme(res.dec_e_asinh) \
                or {id(p) for p in res.dec.parameters()} & {id(p) for p in res.dec_asinh.parameters()} \
                or {id(p) for p in res.dec_e.parameters()} & {id(p) for p in res.dec_e_asinh.parameters()}:
            soucis20.append("les deux têtes n'ont pas des décodeurs dupliqués et distincts")
        g0 = convertir(petit[-1]["donnees"], DEUX_ECHELLES)
        m0 = {k: torch.zeros(g0.n[k], dtype=torch.bool) for k in SORTES}
        m0["instance"][0] = True
        with torch.no_grad():
            o0 = res(g0, m0)
        if list(o0) != list(TETES):
            soucis20.append(f"sorties {list(o0)}")
        for t in TETES:
            v_, lo_, fl_ = o0[t]
            if any(tuple(v_[k].shape) != (g0.n[k], de[k]) or tuple(lo_[k].shape) != (g0.n[k], de[k]) for k in SORTES) \
                    or any(tuple(fl_[r].shape) != (g0.ei[r].shape[1], dr[r]) for r in res.notees):
                soucis20.append(f"sorties de la tête {t}")
        n_par = sum(p.numel() for p in res.parameters())
        with torch.random.fork_rng():
            n_v = {v: sum(p.numel() for p in Reconstructeur(dims, "complet", v).parameters()) for v in ("v1", "v2")}
        if ed.infos[0]["parametres"] != n_par:
            soucis20.append(f"paramètres : {ed.infos[0]['parametres']} à l'entraînement, {n_par} ici")

        # (b) la perte, à la main, sur un petit lot (6 fenêtres, 30 % des nœuds masqués)
        normales_p20 = _normales(petit)
        lot = assembler([convertir(f["donnees"], DEUX_ECHELLES) for f in normales_p20[:6]])
        gen20 = torch.Generator().manual_seed(20)
        m20 = {k: torch.rand(lot.n[k], generator=gen20) < 0.3 for k in SORTES}
        with torch.no_grad():
            perte20 = float(perte_masquee(res, lot, m20))
            o20 = res(lot, m20)

        def huber(a: torch.Tensor, b: torch.Tensor) -> torch.Tensor:
            d_ = (a - b).abs()
            return torch.where(d_ < 1.0, 0.5 * d_ * d_, d_ - 0.5).mean()

        def a_la_main(sortie: tuple, i: int) -> float:
            """La perte complète d'une version sur une tête, contre l'échelle i de l'entrée."""
            valeurs, logits, fleches = sortie
            noeuds, aretes = [], []
            for k in SORTES:
                lig = m20[k]
                if not bool(lig.any()) or de[k] == 0:
                    continue
                x_ = lot.x[k][lig][:, i * de[k]:(i + 1) * de[k]]
                pr, v_, lo_ = lot.p[k][lig], valeurs[k][lig], logits[k][lig]
                la = pr > 0.5
                hub = huber(v_[la], x_[la]) if bool(la.any()) else torch.tensor(0.0)
                bce = (lo_.clamp(min=0) - lo_ * pr + torch.log1p(torch.exp(-lo_.abs()))).mean()
                noeuds.append(float(hub) + 0.5 * float(bce))
            for r in res.notees:
                me = m20[RELATIONS[r][1]][lot.ei[r][1]]
                if bool(me.any()):
                    aretes.append(float(huber(fleches[r][me], lot.ea[r][me][:, i * dr[r]:(i + 1) * dr[r]])))
            return sum(noeuds) / len(noeuds) + (sum(aretes) / len(aretes) if aretes else 0.0)
        l_v2, l_v1 = a_la_main(o20[TETES[0]], 0), a_la_main(o20[TETES[1]], 1)
        ecart_b = abs(perte20 - 0.5 * (l_v2 + l_v1))
        if ecart_b > 1e-5 * max(1.0, abs(perte20)) or not (l_v1 > 0 and l_v2 > 0 and abs(l_v1 - l_v2) > 1e-6):
            soucis20.append(f"perte {perte20} au lieu de ½ ({l_v2} + {l_v1})")
        with torch.random.fork_rng():
            copie20 = Reconstructeur(dims, "complet", m_u2)
        copie20.load_state_dict(res.state_dict())
        perte_masquee(copie20, lot, m20).backward()
        grad = {t: sum(float(p.grad.abs().sum()) for mod in copie20.decodeurs(t) for p in mod.parameters()
                       if p.grad is not None) for t in TETES}
        if not all(x > 0 for x in grad.values()):
            soucis20.append(f"gradient des têtes {grad}")

        # (c) le déterminisme : 1 contre 3 processus (modèle final et plis, graine 0)
        taches20 = _taches(normales_p20, dims, "complet", 0, 2, m_u2)
        graphes20 = {id(f["donnees"]): convertir(f["donnees"], DEUX_ECHELLES) for f in normales_p20}
        avant20, emp20 = PROCESSUS, {}
        try:
            for n in (1, 3):
                globals()["PROCESSUS"] = n
                emp20[n] = [empreinte(e) for e, _ in entrainer_tous(taches20, graphes20)]
        finally:
            globals()["PROCESSUS"] = avant20
        ok_c = emp20[1] == emp20[3] == list(ed.empreintes.values()) and len(set(emp20[1])) == len(taches20)
        if not ok_c:
            soucis20.append("1 et 3 processus : autres empreintes")

        # (d) chaque tête lit son échelle : un nœud masqué seul, à la main
        f1 = petit[-1]["donnees"]
        eb, ea20 = etape1(petit, fige, "complet", 0, 2, va), etape1(petit, fige, "complet", 0, 2, vc)
        sorties_t = {TETES[0]: eb.sortie(f1), TETES[1]: ea20.sortie(f1)}
        gd1 = convertir(f1, DEUX_ECHELLES)
        cibles = {TETES[0]: convertir(f1, False), TETES[1]: convertir(f1, True)}
        pire_d, n_d = 0.0, 0
        for k in SORTES:
            for i in (sorted({0, gd1.n[k] - 1}) if gd1.n[k] else []):
                mi = {kk: torch.zeros(gd1.n[kk], dtype=torch.bool) for kk in SORTES}
                mi[k][i] = True
                with torch.no_grad():
                    oi = res(gd1, mi)
                for t in TETES:
                    c_, s_t = cibles[t], sorties_t[t]
                    v_, lo_, fl_ = oi[t]
                    att = (c_.x[k][i] - v_[k][i]).numpy().astype(float)
                    att[c_.p[k][i].numpy() < 0.5] = np.nan
                    ab = float((c_.p[k][i] - torch.sigmoid(lo_[k][i])).sum())
                    obs = s_t.res_n[k][i]
                    if not np.array_equal(np.isnan(att), np.isnan(obs[:-1])):
                        soucis20.append(f"tête {t} {k} {i} : absents")
                    rel = lambda a, b: np.nan_to_num(np.abs(a - b) / np.maximum(1.0, np.abs(a)), nan=0.0)
                    pire_d = max(pire_d, float(rel(att, obs[:-1]).max(initial=0.0)), float(rel(np.array(ab), obs[-1])))
                    for r in res.notees:
                        if RELATIONS[r][1] != k:
                            continue
                        for e in (gd1.ei[r][1] == i).nonzero().flatten().tolist():
                            pire_d = max(pire_d, float(rel((c_.ea[r][e] - fl_[r][e]).numpy().astype(float),
                                                           s_t.res_e[r][e]).max(initial=0.0)))
                    n_d += 1
        if pire_d > 1e-4 or not n_d:
            soucis20.append(f"résidus des têtes recalculés à la main : écart {pire_d:.1e}")
        if np.allclose(sorties_t[TETES[0]].res_n["instance"], sorties_t[TETES[1]].res_n["instance"], equal_nan=True):
            soucis20.append("les deux têtes ont les mêmes résidus")

        # (e) l'alarme = la tête brute par identité, le classement = la tête asinh par sorte, recalculés à part
        choix_a, choix_c = choix_exemplaire(va), CHOIX_VERSIONS[version]
        if choix_a != CHOIX_VERSIONS[COMBINEES["v12"]["alarme"]] or choix_c != CHOIX_VERSIONS[COMBINEES["v12"]["classement"]] \
                or va != m_u2 + TETE_BRUTE or vc != m_u2 + TETE_ASINH or not par_identite(va) or par_identite(vc):
            soucis20.append(f"choix {nom_choix(choix_a)} et {nom_choix(choix_c)}, exemplaires {va} et {vc}")
        garde20 = [f for f in petit if f["jeu"] == "apprentissage" and f["etiquette"] not in juge.ECARTEES]
        pannes20 = [f for f in garde20 if f["etiquette"] == "panne"]
        n20, differe_s, differe_c = 0, 0, 0
        for v in VARIANTES:
            base = etape1(petit, fige, v, 0, 2, m_u2)

            def tenues_de(t: str) -> dict:
                return {c: [(f["id"], residus(VueTete(base.plis[c], t), f["donnees"])) for f in base.normales
                            if f["campagne"] == c] for c in base.campagnes}

            def calage_de(tenues: dict, camps: list, ident: bool) -> Calage:
                return Calage([s_ for c in camps for _, s_ in tenues[c]], v, base.modele.notees, base.version,
                              par_identite=ident)
            tb, ta = tenues_de(TETES[0]), tenues_de(TETES[1])
            cal_b, cal_a = calage_de(tb, base.campagnes, True), calage_de(ta, base.campagnes, False)
            if not cal_b.par_identite or not any(cal_b.ident_n.values()) or cal_a.par_identite \
                    or any(cal_a.ident_n.values()) or any(cal_a.ident_e.values()):
                soucis20.append(f"{v} : calages des têtes")
            tenus_att = [(c, i, noter_noeuds(s_, calage_de(tb, [c2 for c2 in base.campagnes if c2 != c], True),
                                             choix_a)[1]) for c in base.campagnes for i, s_ in tb[c]]
            s_t20 = [x for _, _, x in tenus_att]
            sb_f = {f["id"]: residus(VueTete(base.modele, TETES[0]), f["donnees"]) for f in petit}
            sa_f = {f["id"]: residus(VueTete(base.modele, TETES[1]), f["donnees"]) for f in petit}
            protos = tn.Prototypes([profil(sb_f[f["id"]], cal_b) for f in pannes20],
                                   [f["cause"] for f in pannes20]) if pannes20 else None
            for reglage in tn.REGLAGES:
                for budget in (None, "règle"):
                    mu = GNN(petit, fige, graine=0, variante=v, epoques=2, version=version, reglage=reglage,
                             budget=budget)
                    ea2, ec2 = mu.etape1_alarme, mu.etape1
                    if not (isinstance(ea2, TeteBrute) and isinstance(ec2, TeteAsinh) and ea2.origine is base
                            and ec2.origine is base and ea2.modele.reseau is base.modele
                            and ec2.modele.reseau is base.modele and ea2.calage.par_identite
                            and not ec2.calage.par_identite and mu.choix_alarme == choix_a and mu.choix == choix_c
                            and mu.combinee and ea2.empreintes == ec2.empreintes == base.empreintes):
                        soucis20.append(f"{v} {reglage} {budget} : les exemplaires ne sont pas les deux têtes du réseau")
                    seuil_att = _q95(s_t20) if budget is None else \
                        seuil_budget(s_t20, budget_mis_a_l_echelle(budget, len(s_t20)))
                    if mu.tenus != tenus_att or mu.seuil != seuil_att or mu.seuil_propre != _q95(s_t20):
                        soucis20.append(f"{v} {reglage} {budget} : scores tenus ou seuils ≠ tête brute par identité")
                    for f in petit:
                        ru = mu.repondre(f["donnees"])
                        n20 += 1
                        s_att = noter_noeuds(sb_f[f["id"]], cal_b, choix_a)[1]
                        sc_att, sc_s, _ = noter_noeuds(sa_f[f["id"]], cal_a, choix_c)
                        if ru["_S"] != s_att or ru["alarme"] != bool(s_att > seuil_att):
                            soucis20.append(f"{v} {reglage} {budget} {f['id']} : S ou alarme ≠ tête brute par identité")
                        if ru["scores"] != sc_att or ru["_S_classement"] != sc_s:
                            soucis20.append(f"{v} {reglage} {budget} {f['id']} : classement ≠ tête asinh par sorte")
                        if reglage == "avec exemples" and ru["alarme"] and protos is not None \
                                and ru["_sans_rejet"] != protos.plus_proche(profil(sb_f[f["id"]], cal_b))[0]:
                            soucis20.append(f"{v} {reglage} {budget} {f['id']} : prototype ≠ tête brute par identité")
                        if reglage == "sans exemples" and budget is None:
                            differe_s += noter_noeuds(sa_f[f["id"]], cal_a, choix_a)[1] != s_att
                            differe_c += noter_noeuds(sb_f[f["id"]], cal_b, choix_c)[0] != sc_att
        if not differe_s or not differe_c:
            soucis20.append("l'autre tête donnerait partout le même S ou les mêmes scores")

        # (f) un seul réseau : ses empreintes, ses modèles « sans c ni c' » (lus par gnn_exemples, sur SON module
        # gnn : lancé en script, ce fichier est __main__, et gnn_exemples en a sa propre copie, gx.gnn)
        emp_u2 = empreintes(petit, fige, 1, 2, version, ("complet",), avec_exemples=True)
        emp_12 = empreintes(petit, fige, 1, 2, "v12", ("complet",), avec_exemples=True)
        n_plis20 = len(ed.campagnes)
        ebx = gx.gnn.etape1(petit, fige, "complet", 0, 2, va)
        pp = gx.paires(ebx, normales_p20)
        if {sha for k, sha in emp_u2.items() if "(alarme, avec exemples)" not in k} != set(ed.empreintes.values()) \
                or len(emp_u2) != 1 + n_plis20 + n_plis20 * (n_plis20 - 1) // 2 \
                or set(emp_u2.values()) & set(emp_12.values()) \
                or not all(f" exemplaire {m_u2} (" in k and k.startswith(f"{version} ") for k in emp_u2):
            soucis20.append(f"empreintes : {len(emp_u2)} pour u2")
        if not (pp.modeles and all(isinstance(mm, gx.gnn.VueTete) and mm.tete == TETES[0] and mm.reseau.version == m_u2
                                   and mm.reseau.tetes for mm in pp.modeles.values())
                and all(t_[6] == m_u2 for t_ in gx._taches_paires(ebx, normales_p20))
                and all(pp.monde(c)[0].par_identite for c in ebx.campagnes)
                and ebx.empreintes == ed.empreintes):
            soucis20.append("les modèles « sans c ni c' » ne sont pas des réseaux doubles vus par la tête brute")

        # (g) les noms
        nu = [n for n, _, _ in methodes(fige, 2, version)]
        n12 = [n for n, _, _ in methodes(fige, 2, "v12")]
        autres = {n for w in UNIQUES if w != version for n, _, _ in methodes(fige, 2, w)}
        if nu != [PREFIXES[version] + n[len("GNN"):] for n in n12] or tuple(nu[:4]) != noms_decision(version) \
                or dc.VARIANTES_GNN.get(version) != PREFIXES[version] or set(nu) & autres \
                or any(n.startswith(PREFIXES[w] + ",") or n.startswith(PREFIXES[w] + " sans")
                       for w in UNIQUES if w != version for n in nu):
            soucis20.append(f"noms : {nu[:4]}")

        # (c, suite) tout réappris à neuf, puis les caches remis (comme T17)
        net20 = lambda r: {k: r[k] for k in ("alarme", "cause", "scores", "_S", "_S_classement")}
        m_avant = GNN(petit, fige, graine=0, epoques=2, version=version, reglage="sans exemples")
        rep_avant = {f["id"]: net20(m_avant.repondre(f["donnees"])) for f in petit}
        sauve = dict(_CACHE)
        try:
            _CACHE.clear()
            preparer(petit, fige, graines=1, variantes=("complet",), epoques=2, version=version)
            ed_neuf = etape1(petit, fige, "complet", 0, 2, m_u2)
            m_neuf = GNN(petit, fige, graine=0, epoques=2, version=version, reglage="sans exemples")
            garder20 += [ed_neuf, m_neuf]
            neuf20 = ed_neuf is not ed and ed_neuf.empreintes == ed.empreintes \
                and m_neuf.etape1.origine is ed_neuf and m_neuf.etape1_alarme.origine is ed_neuf \
                and all(net20(m_neuf.repondre(f["donnees"])) == rep_avant[f["id"]] for f in petit)
        finally:
            _CACHE.clear()
            _CACHE.update(sauve)
        if not neuf20:
            soucis20.append("réappris à neuf : autres empreintes ou autres réponses")
        resultats["T20 u2 : réseau double, alarme tête brute, classement tête asinh"] = (
            not soucis20,
            f"(a) entrée brute + asinh bout à bout, encodeur instance {res.enc['instance'].in_features} entrées, "
            f"2 têtes aux décodeurs dupliqués ; {n_par} paramètres (v1 {n_v['v1']}, v2 {n_v['v2']}) ; (b) perte "
            f"{perte20:.6f} = ½ (L_v2 {l_v2:.6f} + L_v1 {l_v1:.6f}), écart {ecart_b:.1e}, gradient sur les deux têtes ; "
            f"(c) 1 et 3 processus : mêmes empreintes {emp20[1] == emp20[3]} ({len(taches20)} entraînements), réappris "
            f"à neuf : mêmes empreintes et réponses {neuf20} ; (d) {n_d} nœuds masqués seuls : résidus des deux têtes "
            f"contre leur échelle à {pire_d:.1e} près ; (e) {n20} réponses ({len(VARIANTES)} variantes × 2 réglages × 2 "
            f"seuils × {len(petit)} fenêtres) : S, alarme, seuils, prototype = tête brute par identité "
            f"({nom_choix(choix_a)}), scores = tête asinh par sorte ({nom_choix(choix_c)}), recalculés à part ; l'autre "
            f"tête : autre S sur {differe_s}, autres scores sur {differe_c}/{len(VARIANTES) * len(petit)} fenêtres ; "
            f"(f) {len(emp_u2)} empreintes, celles du réseau double, aucune de v12 ; (g) noms « {nu[0]} »…"
            + (f" ; {len(soucis20)} soucis, dont {soucis20[0]}" if soucis20 else ""))

    # T18 : GNN_PROCESSUS ne change aucun modèle : les mêmes tâches (modèle final et plis du petit
    # jeu, graines 0 et 1) en 1 processus puis en max(2, PROCESSUS), mêmes empreintes, et celles de
    # l'étape 1 déjà apprise (graine 0).
    mv0 = mvs[0]
    normales_p = _normales(petit)
    taches18 = _taches(normales_p, dims, "complet", 0, 2, mv0) + _taches(normales_p, dims, "complet", 1, 2, mv0)
    graphes18 = {id(f["donnees"]): convertir(f["donnees"], VERSIONS[mv0]["asinh"]) for f in normales_p}
    avant18, n18, emp18 = PROCESSUS, max(2, PROCESSUS), {}
    try:
        for n in (1, n18):
            globals()["PROCESSUS"] = n
            emp18[n] = [empreinte(e) for e, _ in entrainer_tous(taches18, graphes18)]
    finally:
        globals()["PROCESSUS"] = avant18
    deja18 = list(etape1(petit, fige, "complet", 0, 2, mv0).empreintes.values())
    ok18 = emp18[1] == emp18[n18] and emp18[1][:len(deja18)] == deja18 and len(set(emp18[1])) == len(taches18)
    resultats["T18 le nombre de processus ne change rien"] = (
        ok18, f"{len(taches18)} entraînements ({mv0}, graines 0 et 1) en 1 et en {n18} processus : mêmes empreintes "
              f"{emp18[1] == emp18[n18]} ; celles de l'étape 1 apprise avec PROCESSUS = {avant18} "
              f"{emp18[1][:len(deja18)] == deja18}")

    echecs = 0
    for nom, (ok, detail) in sorted(resultats.items(), key=lambda x: int(x[0].split()[0][1:])):
        print(f"{nom:<44} {'réussi' if ok else 'ÉCHEC'}  ({detail})")
        echecs += not ok
    print("TOUT PASSE" if not echecs else f"{echecs} ÉCHEC(S)")
    return 0 if not echecs else 1


# ------------------------------------------------------------------------------
# --validation, --repetition, --test
# ------------------------------------------------------------------------------
def _reponses(t, fen: list[dict]) -> dict:
    test = [f for f in fen if f["jeu"] == "test" and f["etiquette"] not in juge.ECARTEES]
    return {f["id"]: t.repondre(f["donnees"]) for f in test}


PROTOTYPES_SEULS = "GNN, étape 1 + prototypes (avant E-2)"


def _entrees(fige: dict, variantes, epoques: int, version: str = VERSION) -> list[tuple[str, object]]:
    """Les entrées du tableau : les deux « sans exemples » de decision_c (NOMS_DECISION),
    l'étape 1 avec les prototypes du §5 (le réglage « avec exemples » d'avant l'écart E-2,
    pour comparaison ; le vrai « avec exemples » est dans gnn_exemples.py), les variantes."""
    ve = {"epoques": epoques, "version": version}
    out = [(NOMS_DECISION[0], lambda fen, g: GNN(fen, fige, graine=g, reglage="sans exemples", **ve)),
           (NOMS_DECISION[1], lambda fen, g: GNN(fen, fige, graine=g, reglage="sans exemples", budget="règle", **ve)),
           (PROTOTYPES_SEULS, lambda fen, g: GNN(fen, fige, graine=g, **ve))]
    for v in variantes:
        out.append((f"GNN {v}", lambda fen, g, v=v: GNN(fen, fige, graine=g, variante=v, reglage="sans exemples",
                                                        **ve)))
    return out


def _notes(fen: list[dict], fige: dict, graines: int, variantes, epoques: int, sans_temoins: bool,
           detail: dict | None = None, version: str = VERSION) -> dict:
    if sans_temoins:
        rep = juge.factices(fen)["a priori"]
        n = {"a priori (ne lit rien)": [(juge.noter(fen, rep)[1], rep)]}
    else:
        import temoins as temoins_module
        n = temoins_module.notes(fen, fige, graines)
    for nom, fabrique in _entrees(fige, variantes, epoques, version):
        n[nom] = []
        for g in range(graines):
            t = fabrique(fen, g)
            brutes = _reponses(t, fen)
            rep = {i: _propre(r) for i, r in brutes.items()}
            n[nom].append((juge.noter(fen, rep)[1], rep))
            if detail is not None and g == 0:
                detail[nom] = (t, brutes)
    return n


def _source_choix(choix: dict, version: str) -> str:
    """D'où vient le CHOIX écrit dans l'en-tête : le banc de la version, ou PROVISOIRE."""
    if CHOIX_SOURCES.get(version) and choix == CHOIX_VERSIONS[version]:
        return CHOIX_SOURCES[version]
    if choix == {"bout": "B1", "remontee": "H0", "explication": "V0"}:
        return "PROVISOIRE tant que le banc n'a pas tranché"
    return "choix passé à la main"


def _en_tete(t: GNN, variantes_infos: list) -> list[str]:
    out = []
    roles = [(t.etape1, t.choix, "alarme et classement")] if not t.combinee else \
        [(t.etape1_alarme, t.choix_alarme, "alarme"), (t.etape1, t.choix, "classement")]
    for e1, choix, role in roles:
        cal = e1.calage
        tau = cal.tau(choix["bout"])
        duree = [i["duree"] for i in e1.infos]
        if isinstance(e1, Tete) and choix != t.choix:        # u2 (§19) : la tête brute, sous le choix de l'alarme de v12
            source = f"le choix de l'alarme de v12 (§19), {_source_choix(choix, COMBINEES['v12']['alarme'])}"
        else:
            source = _source_choix(choix, t.version) if choix == t.choix else \
                f"le choix de {e1.exemplaire}, {_source_choix(choix, e1.version)}" if not isinstance(e1, ParIdentite) \
                else f"le choix de l'alarme de v12 (§18), {_source_choix(choix, COMBINEES['v12']['alarme'])}"
        out += [f"# étape 1 ({role}) version {e1.exemplaire} ({e1.variante}, graine {e1.graine}) : "
                f"{e1.infos[0]['parametres']} paramètres, {e1.epoques} époques, {e1.infos[0]['fenetres']} normales "
                f"d'apprentissage, {len(e1.campagnes)} plis ; empreinte du modèle final {e1.empreinte[:16]}",
                f"#   durée d'un entraînement : modèle final {duree[0]:.1f} s, plis {min(duree[1:]):.1f}–"
                f"{max(duree[1:]):.1f} s (un fil chacun) ; perte du modèle final {e1.infos[0]['pertes'][0]:.3f} → "
                f"{e1.infos[0]['pertes'][-1]:.3f}",
                f"#   post-traitement {nom_choix(choix)} ({source}) ; "
                f"κ : " + ", ".join(f"{r} {cal.kappa[r]:.2f}" for r in cal.notees)
                + " ; τ : " + ", ".join(f"{k} {tau[k]:.2f}" for k in SORTES)]
        if cal.par_identite:
            idn = sum(len(v) for v in cal.ident_n.values())
            ide = sum(len(v) for v in cal.ident_e.values())
            out.append(f"#   calage par identité (temoin_noeud.identite, temoin_noeud.echelles) : {idn} identités de "
                       f"nœud et {ide} de flèche ont leur normal ; les autres retombent sur le calage par sorte")
        elif isinstance(e1, ParSorte):
            out.append(f"#   calage PAR SORTE des résidus de l'exemplaire {e1.version} (§17) : le même modèle et les "
                       f"mêmes résidus tenus que l'alarme, médiane et échelle par (sorte, colonne) et (relation, colonne)")
        elif isinstance(e1, Tete):
            out.append(f"#   calage PAR SORTE des résidus de la tête {e1.TETE} du réseau {e1.version} (§19) : ses résidus "
                       f"tenus hors pli, médiane et échelle par (sorte, colonne) et (relation, colonne), comme en version 1")
        if isinstance(e1, Tete):
            out.append(f"#   (§19 : la tête {e1.TETE} du réseau {e1.version}, le même entraînement que l'autre tête ; ses "
                       f"résidus contre SA cible, l'échelle {'brute (comme v2)' if e1.TETE == TETES[0] else 'asinh (comme v1)'})")
        if isinstance(e1, ParIdentite):
            out.append(f"#   (§18 : le modèle {e1.version} du classement, ses mêmes résidus tenus, calés par identité "
                       f"comme en version 2)")
    out.append(f"# alarme ({t.etape1_alarme.exemplaire}) au-dessus de {t.seuil_propre:.3f} (95e centile de "
               f"{t.calage_propre[1]} scores tenus hors pli ; {t.calage_propre[0]} au-dessus)")
    n = len(t.tenus)
    s = [x for _, _, x in t.tenus]
    out.append("#   budgets mis à l'échelle (N = " + f"{n} au lieu de {MINUTES_BUDGET}) : "
               + ", ".join(f"{nom} {BUDGETS[nom]}/{MINUTES_BUDGET} → {budget_mis_a_l_echelle(nom, n)}/{n} "
                           f"(θ {seuil_budget(s, budget_mis_a_l_echelle(nom, n)):.3f})" for nom in BUDGETS))
    if t.prototypes is not None:
        out.append(f"#   étape 2 : {len(t.prototypes.moyennes)} prototypes ({', '.join(sorted(t.prototypes.moyennes))}) "
                   f"sur {len(t.prototypes.ecart)} dimensions ; rejet au-dessus de {t.seuil_rejet:.2f} "
                   f"({t.calage_rejet[0]} injections mises de côté, {t.calage_rejet[1]} fenêtres bien classées)")
    par = {}
    for c, _, x in t.tenus:
        par.setdefault(c, []).append(x > t.seuil_propre)
    out.append("#   scores tenus au-dessus du seuil, par campagne : "
               + ", ".join(f"{c} {sum(v)}/{len(v)}" for c, v in par.items()))
    out += variantes_infos
    return out


def repetition(noms: list[str], campagnes: Path, runs: Path, fige: dict, graines: int, variantes,
               epoques: int, sans_temoins: bool, validation: bool = True, version: str = VERSION) -> list[str]:
    """La boucle de temoins.repetition (l.181-200), recopiée, avec le GNN : chaque cause
    connue retirée de l'apprentissage (l'étape 1 est reprise : ses normales ne bougent pas)."""
    import temoins as temoins_module
    out = []
    for cause in temoins_module.REPETEES:
        fen = juge.lire(noms, campagnes, runs, jamais_vues=juge.JAMAIS_VUES | {cause})
        if validation:
            fen = juge.validation(fen)
        groupe = [f for f in fen if f["jeu"] == "test" and f["etiquette"] == "panne" and f["cause"] == cause]
        injections = len({(f["campagne"], f["injection"]) for f in groupe})
        out.append(f"\n{cause} retirée de l'apprentissage : {len(groupe)} fenêtres de test, {injections} injections")
        n = _notes(fen, fige, graines, variantes, epoques, sans_temoins, version=version)
        for nom, liste in n.items():
            cases = []
            for titre, cle in (("détection", f"detection jamais vue : {cause}"),
                               ("« inconnue »", f"cause jamais vue : {cause}"),
                               ("top-1", f"top-1 jamais vue : {cause}"),
                               ("top-3", f"top-3 jamais vue : {cause}")):
                v = [c[cle][0] for c, _ in liste if cle in c]
                if v:
                    cases.append(f"{titre} {temoins_module._case(v, liste[0][0][cle][1])}")
            if nom.startswith("règle"):
                cases = [x for x in cases if not x.startswith("« inconnue »")] + ["« inconnue » sans objet"]
            out.append(f"  {nom:<40}" + " ; ".join(cases))
    return out


def rapport(campagnes: Path, runs: Path, graines: int, epoques: int, sans_temoins: bool, variantes,
            validation: bool, avec_repetition: bool, tableau: bool = True, version: str = VERSION) -> int:
    import temoins as temoins_module
    _un_fil()
    fige, ecarts_ref, _ = gel.reference()
    if ecarts_ref:
        print(f"REFUS  {ecarts_ref[0]}")
        return 1
    try:
        if not validation:
            exiger_scelle(version)
        charger_echelle(fige)
        noms = fautifs_module.SERIES
        fen = juge.lire(noms, campagnes, runs)
    except juge.Refus as e:
        print(f"REFUS  {e}")
        return 1
    if validation:
        fen = juge.validation(fen)
        print("# VALIDATION : coupure répétée dans l'apprentissage (juge.validation), vrai test jamais lu")
    print("# Le GNN — écrit par graphe_en/gnn.py, ne pas éditer à la main.")
    print(f"# version {version} de l'étape 1 (écarts E-1, §11, et E-5, §15) : {decrire(version)}")
    print(f"# graines 0 à {graines - 1} ; {epoques} époques ; variantes en plus du complet : "
          f"{', '.join(variantes) or 'aucune'} ; témoins {'NON recalculés' if sans_temoins else 'recalculés'}")
    duree = preparer(fen, fige, graines, ("complet",) + tuple(variantes), epoques, version)
    n_entr = len(modeles_de(version)) * graines * (1 + len(variantes)) * (1 + len(_etape_campagnes(fen)))
    print(f"# {n_entr} entraînements en {duree:.0f} s de temps réel ({PROCESSUS} processus au plus, un fil chacun)")
    if tableau:
        detail: dict = {}
        n = _notes(fen, fige, graines, variantes, epoques, sans_temoins, detail, version)
        t0 = detail[PROTOTYPES_SEULS][0]
        tb = detail[NOMS_DECISION[1]][0]
        infos = [f"#   {NOMS_DECISION[1]} : {tb.budget_b}/{len(tb.tenus)} → alarme au-dessus de {tb.seuil:.3f} "
                 f"({tb.calage_alarme[0]} scores tenus au-dessus)"]
        for v in variantes:
            tv = detail[f"GNN {v}"][0]
            sv = [x for _, _, x in tv.tenus]
            b21 = budget_mis_a_l_echelle("règle", len(sv))
            infos.append(f"#   {v} : alarme au-dessus de {tv.seuil_propre:.3f} (θ au budget de la règle, en "
                         f"diagnostic : {seuil_budget(sv, b21):.3f}) ; durée d'un entraînement "
                         f"{statistics.median(i['duree'] for i in tv.etape1.infos):.1f} s (médiane)")
        print("\n".join(_en_tete(t0, infos)))
        normales = [f for f in fen if f["jeu"] == "test" and f["etiquette"] == "normale"]
        print(f"\n== 1. tableau de bord ({'validation' if validation else 'test'} ; fausses alertes sur "
              f"{sum(1 for f in normales if not f['vue'])} minutes normales non vues, puis sur "
              f"{sum(1 for f in normales if f['vue'])} de saine-09)")
        print("\n".join(temoins_module.tableau_de_bord(n)))
        print("\n== 2. fausses alertes au fil du temps (fenêtres normales du test ; médiane sur les graines)")
        print("\n".join(temoins_module.fil_du_temps(fen, n)))
        nom0 = NOMS_DECISION[0]
        print(f"\n== note détaillée du {nom0}, graine 0")
        rep0 = {i: _propre(r) for i, r in detail[nom0][1].items()}
        print("\n".join(juge.noter(fen, rep0, f"{nom0}, graine 0")[0]))
        print("désigné en premier, par cause (fenêtres de panne du test)")
        print("\n".join(tn.premiers(fen, rep0)))
        if graines > 1:
            import temoin_tableau
            print(f"\n# {nom0}, sur {graines} graines : chaque nombre de la note")
            print("\n".join(temoin_tableau._resume_graines([c for c, _ in n[nom0]])))
    if avec_repetition:
        print("\n== 3. répétition « panne jamais vue » (une cause connue retirée de l'apprentissage)")
        print("\n".join(repetition(fautifs_module.SERIES, campagnes, runs, fige, graines, variantes, epoques,
                                   sans_temoins, validation, version)))
    return 0


def nom_sortie(nom: str, version: str) -> str:
    """La version entre dans le nom des sorties : gnn-validation.txt (v1, inchangé),
    gnn-validation-v2.txt, gnn-banc-validation-v3.txt…"""
    return nom if version == "v1" else nom[:-len(".txt")] + f"-{version}.txt"


def _etape_campagnes(fen: list[dict]) -> set[str]:
    return {f["campagne"] for f in _normales(fen)}


def main(argv: list[str]) -> int:
    campagnes, runs = HERE.parent / "campagnes", HERE / "runs"
    graines, epoques, sans_temoins, variantes = 5, EPOQUES, False, []
    mode, avec_repetition, version = None, False, VERSION
    args = argv[1:]
    try:
        while args:
            a = args.pop(0)
            if a == "--help":
                print(__doc__.strip())
                return 0
            elif a == "--verifier":
                mode = "verifier"
            elif a == "--validation":
                mode = "validation" if mode != "test" else mode
            elif a == "--test":
                mode = "test"
            elif a == "--repetition":
                avec_repetition = True
            elif a == "--graines":
                graines = int(args.pop(0))
                if graines < 1:
                    raise ValueError
            elif a == "--epoques":
                epoques = int(args.pop(0))
                if epoques < 1:
                    raise ValueError
            elif a == "--sans-temoins":
                sans_temoins = True
            elif a == "--version":
                version = args.pop(0)
                if version not in TOUTES_VERSIONS:
                    raise ValueError
            elif a == "--variantes":
                v = args.pop(0)
                variantes = [x for x in VARIANTES if x != "complet"] if v == "toutes" else \
                    [x.strip() for x in v.split(",") if x.strip()]
                if any(x not in VARIANTES or x == "complet" for x in variantes):
                    raise ValueError
            elif a == "--campaigns":
                campagnes = Path(args.pop(0))
            elif a == "--runs":
                runs = Path(args.pop(0))
            else:
                print(f"option inconnue : {a}", file=sys.stderr)
                return 2
    except (IndexError, ValueError):
        print("option sans valeur ou valeur illisible (variantes : "
              + ", ".join(v for v in VARIANTES if v != "complet") + " ; versions : " + ", ".join(TOUTES_VERSIONS) + ")",
              file=sys.stderr)
        return 2
    campagnes, runs = campagnes.resolve(), runs.resolve()
    if mode == "verifier":
        return verifier(campagnes, runs, version)
    if mode is None and avec_repetition:
        mode = "repetition"
    if mode is None:
        print(__doc__.strip())
        return 0
    validation = mode != "test"
    if mode == "test" and not scelle_ouvert():
        print(f"REFUS  SCELLÉ FERMÉ : l'étiquette « {ETIQUETTE_SCELLE} » n'existe pas ; --test est refusé.")
        return 1
    if mode == "test" and not scelle_ouvert(version):     # toute version, u2 compris (§17–§19) : gnn-fige-2 aussi
        print(f"REFUS  SCELLÉ FERMÉ pour la version {version} : {'; '.join(raisons_scelle_2(version))} ; "
              f"--test est refusé.")
        return 1
    sortie = io.StringIO()
    with contextlib.redirect_stdout(sortie):
        print(f"# campagnes lues : {', '.join(fautifs_module.SERIES)}")
        code = rapport(campagnes, runs, graines, epoques, sans_temoins, variantes, validation,
                       avec_repetition, tableau=mode != "repetition", version=version)
    texte = sortie.getvalue()
    print(texte, end="")
    if code == 0:
        base = "gnn" if mode != "repetition" else "gnn-repetition"
        cible = campagnes / nom_sortie(juge.sortie(base, fautifs_module.SERIES, validation), version)
        cible.write_text(texte)
        print(f"-> {cible}")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
