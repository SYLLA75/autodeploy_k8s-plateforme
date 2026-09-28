# Journal des décisions

Ce qui a changé, pourquoi, et où le retrouver. Une entrée par décision, datée.
Le détail de chaque changement est dans le message de commit correspondant
(`git log --grep=<mot>`). Ce journal dit *ce qu'il faut savoir* pour ne pas
refaire une erreur déjà faite.

---

## 2026-09-18 — Les lignes de base sont mesurées : un tableau plat nomme la cause sur chaque fenêtre de test

`graphe_en/ligne_de_base.py` (PROCEDURE.md, étape 13) sur les cinq campagnes,
saine-08, charge-03, blocage-02, lenteur-01, hote-01. Vérité tirée des
déroulés, fenêtres à cheval sur une transition et fenêtres de vidange (tas >
10 après le retrait, plus une de garde) écartées. Coupure par le temps, la
troisième injection de chaque campagne servant de test : 575 fenêtres, 406
gardées, 256 pour l'apprentissage, 150 pour le test, 19 par cause.

| ligne de base | sur les 150 fenêtres de test |
|---|---|
| seuil, `backlog_slope` > 20 | alarme sur 56 des 57 fenêtres de charge, blocage, lenteur ; jamais sur hote ; aucune fausse alerte ; jamais une cause |
| file seule, 6 nombres | 129 bien nommées (arbre) ; hote jamais, la file ne bouge pas |
| tableau plat, 16 nombres, aucune flèche | 150 bien nommées, arbre de décision et forêt aléatoire pareil |
| règles à la main, limites prises sur saine-08 | 150 bien nommées |

Les quatre questions de l'arbre : `rate_imbalance` > 0,21 (la file se
remplit), `hote_cpu_busy_max` > 0,51 (hote), `process_time_p50_max` > 894 ms
(lenteur, à mi-chemin entre 706 et 1 081), `publish_rate` > 4,10 msg/s
(charge, sinon blocage).

**Conséquence.** Sur quatre causes injectées une à la fois, un modèle qui lit
les flèches ne peut pas nommer la cause mieux qu'un tableau qui les ignore,
au plus aussi bien — la leçon de Fang et al. (2025), reproduite ici. Le
graphe reste la représentation (les 16 nombres en viennent) et la
contribution (la file comme nœud) ; l'argument pour un modèle sur graphe doit
se faire là où le tableau est aveugle : nommer la réplique ou l'hôte en
faute, le même motif sous des pods renommés, une panne qui se propage (la
base ralentit les répliques qui remplissent la file), plusieurs files, deux
pannes à la fois. À concevoir dans les prochaines campagnes. Rappel : `hote`
n'atteint pas la file (la demande CPU garantit sa part à la réplique, son
temps est de l'attente réseau) — anomalie d'hôte sans faute de coordination,
témoin négatif, pas le cas à plusieurs sauts qu'un modèle sur graphe
exigerait. Une cause d'hôte qui atteindrait la file passerait par le réseau
de l'hôte de la réplique, ou par l'hôte de la base.

## 2026-09-13 — Les quatre campagnes sont faites : le jeu de données existe

Après saine-08 et charge-03 (entrée précédente) :

| campagne | plage UTC | tas au retrait (×3) | fondu avant la suivante |
|---|---|---|---|
| blocage-02 | 06:15 → 08:25 | 744 / 711 / 745 | oui (minutes 46, 86, 133) |
| lenteur-01 | 08:31 → 10:41 | 824 / 877 / 883 | oui (4 et 7 avant les injections 2 et 3) |
| hote-01 | 10:48 → 12:58 | 0 – 9 | rien à fondre |

Chaque cause laisse la trace attendue et seulement elle : blocage →
`consumers` 3 → 2 et une réplique à cpu 0 sans temps de traitement ;
lenteur → 706 → 1 081 ms par message sur les trois répliques (5 × 75,
exact) ; hote → `cpu_busy` 0,04 → 0,83 et `cpu_pressure` 0,01 → 0,66 sur un
seul hôte, et la file ne bouge pas (réplique +0,5 %). Entrée stable à
3,4–3,7 msg/s dans les trois. Le service des commandes n'a plus gelé :
~7 300 commandes par campagne, sous le seuil.

**blocage-01** a été abandonnée par le pilote à la minute 2 : le service des
commandes, à court de mémoire à la fin de charge-03, répondait 500 à toute
recherche — la purge ne le redémarre pas, par choix. Le pilote relit
maintenant le bilan des parcours **avant** de partir, avec le remède
(`donnees.sh redemarrer`, puis deux minutes).

**État du jeu de données** : 1 référence (55 fenêtres) + 4 campagnes (130
fenêtres chacune) = 575 fenêtres, dont 180 sous injection (60 par cause
pour charge, blocage, lenteur, et 60 « hôte saturé, file saine »).
`scaler.json` calé sur saine-08. Les dossiers `campagnes/*` sont la
provenance ; les runs sont à reconstruire depuis le magasin d'objets avec
la plage de chaque `campagne.yaml`.

**Ce qui reste** : l'étiquetage par fenêtre depuis les déroulés (avec une
période de garde autour des transitions), le découpage par injection
(jamais au hasard), le modèle et ses deux comparaisons imposées, puis
l'étude à 50 % et 95 % d'occupation avec sa propre référence chacune.

## 2026-09-13 — saine-08 et charge-03 : la référence refaite, la première campagne propre

**saine-08** (10/25/20 voyageurs, 60 min, service des commandes à 2 cœurs,
dates sur l'année) : identique à saine-07 en tout point mesuré — entrée
1,4 / 3,4 / 2,7 msg/s, tas 0 à 5, 3 consommateurs, 706 ms par message
(846 à 10 voyageurs). `scaler.json` recalculé dessus.

**charge-03** (`campagnes/charge-03/lecture.txt`) : les trois injections
sont exactement le calcul.

```
   injection   entrée    tas au retrait   fondu à 0 à la minute
   1 (min 5)   4,8–5,1     692            40
   2 (min 50)  4,8–5,0     792            88
   3 (min 95)  4,8–5,2     764           128
```

Sortie plafonnée à 4,25/s, répliques à 706 ms, 3 consommateurs, hôtes
calmes. Le service des commandes est monté jusqu'à 532 m de CPU — au-dessus
de son ancienne limite : la correction était nécessaire.

**Réserve, à écrire** : fenêtres 05:41–05:45 (minutes 126–130, après la
dernière fonte) — `ts-order-service` à court de tas Java
(`java -Xmx200m`, `OutOfMemoryError: Java heap space` dans ses journaux,
~8 500 commandes en table) : recherche et réservation gelées 3 min, entrée
de la file à 0, puis reprise seule. Les injections ne sont pas touchées ;
ces fenêtres sont à écarter, ou à étiqueter « anomalie non injectée ».

**Décision : le tas Java n'est pas relevé pour ces campagnes** (la commande
existe depuis pour les suivantes : `donnees.sh dimensionner --tas 1g`,
testée puis retirée, à poser avant une nouvelle référence). `memory_used` est un attribut
du graphe ; un tas plus grand changerait le niveau de ce nœud dans toutes
les fenêtres, et la référence serait à refaire une seconde fois. Les
trois campagnes restantes tournent à 25 voyageurs d'un bout à l'autre :
~7 300 commandes en 135 min, sous les ~8 500 où le tas a manqué (charge-03
en a produit 9 000 avec ses trois paliers à 35). Si le gel réapparaît, il
se rapporte. Limite connue de la plateforme : **une campagne ne doit pas
dépasser ~8 000 commandes** avec le tas de 200 Mo du service des commandes.

## 2026-09-13 — charge-01 et charge-02 : l'application s'étouffe au bout d'une heure, deux couches

Deux campagnes de 135 min (25 voyageurs, 35 pendant les injections à 5, 50
et 95 min). Dans les deux, les injections 1 et 2 sont exactement le calcul
(entrée 3,5 → 4,9/s, tas ~700–800, fondu en 19 min, file à 0–10 avant la
suivante). Dans les deux, la troisième ne produit rien : l'entrée de la
file s'effondre à 0,6–2/s **avant** elle, dès la 75ᵉ–80ᵉ minute
(`campagnes/charge-01/lecture.txt`, `charge-02/lecture.txt`).

**Mesuré, pas deviné** (Locust `/stats/requests`, `kubectl top`) : la
réservation passe de 0,3 s à 5, 28 puis 60 s (p95) ; les voyageurs y
restent coincés et ne commandent plus de repas — ce sont les repas qui
déposent dans la file. Derrière, `ts-order-service` à 500 m de CPU, sa
limite.

**Première couche** (charge-01) : 6 400 commandes empilées sur 30 dates
(~240 par date, un seul train sur la liaison) ; le service recharge et
journalise la pile à chaque recherche. Correction : dates étalées sur
365 jours (`LG_JOURS_ETALEMENT`, passé au conteneur Locust).

**Deuxième couche** (charge-02, dates étalées, 16 commandes par date) : le
CPU croît quand même, avec le **total** — 97 m à 1 900 commandes, 212 m à
4 700, 444 m à 5 900, 500 m à 7 000. Le service fait un travail
proportionnel à toutes les commandes du train, pas de la date.
Correction : `donnees.sh dimensionner`, limite CPU 500 m → 2 000 m, une
fois. Testé avec 7 600 commandes en table, 25 voyageurs, 6 min : 308 m,
réservation médiane 430 ms, repas à 3,3/s — personne de coincé.

**Résidu accepté, à écrire** : même sans saturation, la réservation passe
de 110 ms (table vide) à ~430 ms (8 000 commandes) — le `request_time`
des trois services de la chaîne dérive lentement pendant toute campagne,
de la même façon dans toutes, et n'atteint pas la file. C'est
l'application ; on ne la corrige pas.

**Pourquoi la référence est refaite** (saine-08) : la limite CPU est un
attribut du graphe (`cpu_quota` du service des commandes). Une référence
doit partager toutes les conditions des campagnes qu'on lui compare.
saine-07 reste dans le dépôt ; le `scaler.json` est recalculé sur saine-08.

**Deux pièges au passage** : `kubectl set resources` sans `-c` touche aussi
le conteneur d'initialisation de l'agent, qui n'a pas de demande —
Kubernetes lui donne alors une demande égale à la limite et le pod ne
trouve plus de nœud (« Insufficient cpu ») ; corrigé. Et une campagne qui
traverse minuit (charge-02, 23:46 → 01:56) : `fetch.py` parcourt
maintenant les deux jours, `run.py` borne la plage sur le lendemain quand
la fin n'est pas après le début.

## 2026-09-12 — essai-hote-02 : la quatrième cause se voit sur l'hôte, pas sur la file

Voisin à 100 % des 4 cœurs de `workers0` de la minute 3 à 8, plage 21:01 →
21:08 (`campagnes/essai-hote-02/lecture.txt`) :

```
   fenêtre   workers0 cpu_busy  cpu_pressure   réplique r5pwb p50   backlog
   21:01          0,24             0,08              706 ms             0
   21:02          0,84             0,62              711 ms             4
   21:05          0,84             0,63              709 ms             0
   21:07          0,05             0,01              706 ms             0
```

L'hôte est saturé, et seulement lui. La réplique qui y vit ralentit de
0,5 % ; la file ne bouge pas. Explication : sa demande CPU (100 m) lui
garantit sa part quand tout le monde veut du processeur, et 4 m lui
suffisent — son temps est fait d'attente réseau, pas de calcul. **Résultat
retenu tel quel** (règle : une cause sans trace se rapporte, ne se retire
pas) : un voisin bruyant sur l'hôte d'une réplique n'est pas une panne de
coordination sur cette plateforme. Pour le modèle, c'est une anomalie
d'hôte *sans* symptôme sur la file — utile pour apprendre à ne pas
attribuer un tas à un hôte chargé. Si un jour il faut qu'un hôte pèse sur
la file, viser l'hôte de la base (les trois répliques y passent cinq fois
par message) serait la voie ; c'est une autre cause, à décider, pas à
glisser.

**Décision pour les grandes campagnes** (`PROCEDURE.md`, étape 11, point
3) : profil `25:135`, injections à 5, 50 et 95 min, 20 min chacune, 25 min
de retour — le temps que le tas du gel (0,7/s, sans réglage possible)
fonde à 0,6/s. `charge` à 35 voyageurs et `lenteur` à +75 ms pour que les
trois causes fassent monter le tas au même rythme (~0,7/s) : le modèle ne
peut alors pas les distinguer à la taille du symptôme. `hote` à sa
valeur par défaut. Ordre : charge, blocage, lenteur, hote.

## 2026-09-12 — essai-lenteur : troisième cause validée, et un trou comblé

+300 ms par échange de la minute 3 à la minute 8, plage 20:31 → 20:38
(`campagnes/essai-lenteur/lecture.txt`) :

```
   fenêtre   backlog  slope  publish  consume  p50 réplique
   20:31         0      -     3,43     3,27      706 ms     avant
   20:32       127    127     3,53     1,35     2206 ms     injection à 20:31:55
   20:35       507    122     3,47     1,35     2206 ms
   20:36       417     19     3,43     5,22        3 ms     retrait à 20:36:55
   20:37       379    -64     3,65     4,23      706 ms
```

706 + 5 × 300 = 2 206 ms : le modèle « cinq échanges avec la base par
message » est exact. La sortie tombe à 1,35/s (3 ÷ 2,206), le tas monte de
127 par minute, CPU et hôtes ne bougent pas. Ligne « lenteur » du tableau.

**Le trou** : à 20:36, p50 de 3 ms et sortie à 5,2/s. Entre la suppression de
l'objet Chaos Mesh de la panne et la pose de celui du réglage, quelques
secondes sans aucun retard : les répliques ont avalé 150 messages à 3 ms.
Mesuré que deux retards sur les mêmes pods s'additionnent (140 + 1 → 143
ms) ; `panne.sh` pose donc la panne avant de retirer le réglage, et repose
le réglage avant de lever la panne. Le recouvrement dure quelques
secondes, un peu plus lent, jamais sans retard. Et un minuteur repose le
réglage de base à l'expiration si le pilote est mort entre-temps.

## 2026-09-12 — essai-hote (1) : refusé par le kubelet, refait

Le voisin bruyant demandait 2 cœurs (la moitié de l'hôte) ; l'hôte n'en a
que 3,4 allouables, dont 1,65 déjà demandés. `nodeName` contourne
l'ordonnanceur : c'est le kubelet qui a refusé le pod (`OutOfcpu`).
Injection non confirmée, essai sans mesure (`campagnes/essai-hote/`).
La demande ne fixe que le poids du voisin face aux autres pods ; le stress
occupe de toute façon tous les cœurs. Elle est maintenant plafonnée à ce
qui reste sur l'hôte moins 100 m (ici 1 600 m). Essai refait : `essai-hote-02`.

## 2026-09-12 — essai-charge : deuxième cause validée, et une règle d'intensité

50 voyageurs (2 × la base) de la minute 3 à la minute 8, plage 20:02 → 20:10
(`campagnes/essai-charge/lecture.txt`) :

```
   fenêtre   backlog  slope  publish  consume  imbalance
   20:02         1      -     3,65     3,65      0,00     avant
   20:04       308    153     7,47     4,25      3,22     injection à 20:03:29
   20:07       800    171     7,13     4,23      2,90
   20:08       813     93     4,05     4,20     -0,15     retrait à 20:08:26
   20:09       784     -8     3,72     4,25     -0,53
```

L'entrée double, la sortie plafonne à 4,25/s (trois répliques à 706 ms),
le tas monte de 170 par minute ; répliques, hôtes, temps par message :
inchangés. C'est la ligne « charge » du tableau des causes.

**Ce que l'essai apprend en plus** : le tas ne fond qu'à ~0,5–0,75/s sous
la charge de base. Vingt minutes à 50 voyageurs feraient 3 300 messages,
plus d'une heure de fonte : dans une campagne à trois injections, la
deuxième partirait sur le tas de la première, et les fenêtres « saines »
entre deux ne le seraient pas. **Règle retenue pour les grandes
campagnes** : l'intensité est choisie pour que le tas construit pendant
l'injection soit fondu avant l'injection suivante, calculée sur les débits
mesurés dans l'essai. Les valeurs sont fixées après les essais lenteur et
hôte (entrée suivante).

**Nettoyé au passage** : deux boucles `while true; do panne.sh temoin;
sleep 20; done`, restées orphelines sur le master après la fermeture de
leurs sessions SSH, avaient écrit 780 fichiers dans `journaux/` ; tuées.
Une simple lecture (`etat`, `temoin`, `bilan`, `fenetre`) n'écrit plus de
journal. Et le pilote attend maintenant une file vide avant de partir, et
relève le bilan des parcours toutes les dix minutes sans arrêter.

## 2026-09-12 — essai-blocage-02 : la première cause validée sur la plateforme

25 voyageurs, réplique gelée de la minute 3 à la minute 8, lu au témoin
toutes les 20 s :

```
   pendant   2 consommateurs (le courtier a lâché la gelée), 2 non acquittés,
             tas + ~50 par minute (129 → 182 en 63 s ; prévu + 40)
   minute 8  3 consommateurs, pic à 188
   après     fonte à ~45 par minute, 0 au bout de cinq minutes, puis 0–3
```

L'entrée n'a pas bougé (3,5/s) ; la sortie est passée de 4,2 à 2,8/s. La
trace est nette, datée, réversible.

**Le graphe la porte** (run sur la plage 19:12 → 19:19, `scaler: apply`,
gardé dans `campagnes/essai-blocage-02/lecture.txt`) :

```
   fenêtre   backlog  slope  publish  consume  imbalance  consumers
   19:12         0      -     3,55     3,55      0,00        3      avant
   19:13        25     25     3,35     2,80      0,55        3      gel à 19:12:59
   19:15        95     35     3,43     2,83      0,60        2      le courtier lâche la gelée
   19:17       192     48     3,75     2,93      0,82        2
   19:18       156      9     3,48     4,22     -0,73        3      levée à 19:17:56
```

Et sur les répliques : la gelée (`…-bmgvs`) n'a plus de `process_time` et
`cpu_rate` 0,000 de 19:13 à 19:17, mémoire inchangée ; les deux autres
gardent 706 ms. Exactement la ligne « blocage » du tableau des causes.

**Corrigé au passage** : le pilote d'alors lisait le début de la plage dans
la date du pod de collecte (resté de la campagne d'avant : « 19:00 »). Il
la calcule maintenant depuis ses propres instants (`collecte_demarree` +
marge). Et le dossier d'une campagne recevait *tout* `journaux/` du master,
600 fichiers dont 500 d'avant elle : il ne reçoit plus que les registres
(.tsv) et les journaux écrits depuis le départ du pilote.

## 2026-09-12 — Le gel d'une réplique doit partir de la machine

**Mesuré** (essai-blocage, première tentative) : `kill -STOP` envoyé depuis
l'intérieur du conteneur à Java, processus 1 → état `S`, rien ne se passe.
Le noyau fait ignorer au processus 1 d'un conteneur les signaux envoyés
depuis son propre conteneur, STOP compris. Sur simulateur, ça passait.

**Décision** : le signal part de la machine, par le démon Chaos Mesh du nœud
(processus de la machine en vue) : le processus Java est retrouvé par
l'identifiant du conteneur dans son cgroup, gelé, et la levée est programmée
dans le démon. `verifier blocage` exige un démon sur le nœud de chaque
réplique. L'essai est à refaire.

## 2026-09-12 — Référence saine-07 : la plateforme réglée se comporte comme calculé

Campagne complète (10 / 25 / 20 voyageurs), `scaler.json` écrit dessus.
Mesuré (`queues.py`, `instances.py`) :

| palier | dépôts/s | tas | temps par message (p50) |
|---|---|---|---|
| 10 voyageurs | 1,2 – 1,5 | 0 | 846 ms |
| 25 voyageurs | 3,3 – 3,75 | 0 – 4, redescend toujours | 706 ms |
| 20 voyageurs | 2,6 – 3,1 | 0 – 3 | 706 ms |

Le débit suit les voyageurs (0,12/s par voyageur, comme prévu), l'écart
dépôt/retrait reste sous ±0,1, 3 consommateurs sans interruption, aucun
point chaud sur les hôtes (pression CPU max 0,026 — les commandes réparties
sur trente dates ne chargent plus le service des commandes).

Le temps par message vaut 5 échanges × 140 ms à 25 voyageurs — le facteur 5
estimé est exact — et 6 échanges à 10 voyageurs : une connexion restée
inactive plus d'une demi-seconde est vérifiée avant réutilisation (Hikari,
`aliveBypassWindow`), un aller-retour de plus. Le temps par message *baisse*
donc quand la charge monte ; c'est une propriété de l'application, à
connaître avant d'interpréter une figure. Occupation à 25 voyageurs :
3,5 × 0,706 ÷ 3 = 82 %.

Corrigé au passage : les fenêtres hors de la plage demandée entraient dans
l'analyse (le rapatriement prend un fichier de plus de chaque côté) ; cinq
fenêtres d'avant la campagne, sans compteurs du courtier, avaient été
comptées dans la normale. Écartées désormais (« outside requested range »).

## 2026-09-12 — Redémarrer le service des commandes seul casse la recherche deux minutes

**Mesuré** au départ de saine-04 : le pilote purgeait et redémarrait
`ts-order-service` ; dans la minute, « chercher un train » à 100 % de `500`
(30 s), puis retour à la normale de lui-même après ~2 minutes (57 ms). Les
services qui appellent les commandes gardent des connexions ouvertes vers le
pod disparu et y attendent. La campagne a été arrêtée et relancée : ses deux
premières minutes étaient fausses.

**Décisions** : la purge ne redémarre plus rien (`--redemarrer` redémarre la
chaîne complète — commandes, sièges, recherche — quand c'est nécessaire) ;
`bilan` rend un code de retour ; le pilote contrôle les parcours à la minute
2 et s'arrête proprement si l'un échoue ou ne tourne pas.

## 2026-09-12 — Le sommeil dans la base sérialise les répliques : retard réseau à la place

**Mesuré**, après la purge et à 25 voyageurs, avec le déclencheur SQL à
0,7 s : 570 messages en attente en cinq minutes ; 3,4 reçus/s, 1,3 traités/s
pour 3 répliques ; et côté base, **un seul** `User sleep` actif en
permanence (10 échantillons sur 10). MySQL n'exécute qu'un sommeil de
déclencheur à la fois : les trois répliques attendaient l'une après l'autre.
La capacité valait 1 ÷ S quel que soit le nombre de répliques — une réplique
gelée n'aurait rien changé, les causes `blocage` et `hote` étaient mortes.

**Décision** : le temps de service est un **retard réseau propre à chaque
réplique** (Chaos Mesh NetworkChaos sans durée, `consommateur.sh
dimensionner --retard 140`), entre les pods du consommateur et `tsdb-mysql`.
Traiter un message coûte ~5 échanges avec la base : ≈ 0,7 s. Le facteur 5
est une estimation, à vérifier sur la référence (`process_time_p50`) et sur
le témoin (tas à 0 à 25 voyageurs).

Piège trouvé à la première pose : les répliques parlent à la base par une
adresse de *service* (`tsdb-mysql-leader`), traduite en adresse de pod après
la sortie du pod ; un retard posé sur les seules adresses des pods de la base
ne voit jamais passer ce trafic (mesuré : connexion en 2 ms, Chaos Mesh
disant « appliqué »). Les adresses des services devant la base sont ajoutées
en `externalTargets` — pour le réglage comme pour la cause `lenteur`.

Conséquence sur la cause `lenteur` : un seul objet à la fois sur ce chemin.
La panne remplace le réglage par « base + panne » (défaut +300 ms) et
`retirer` repose le réglage. Le déclencheur SQL est retiré par
`dimensionner` s'il en reste un.

## 2026-09-12 — L'application s'étouffe sur ses propres données (`apps/donnees.sh`)

**Symptôme** : après l'étalonnage, « chercher un train » répond `500` à 100 %,
`p50` = 30 000 ms, même à 1 voyageur, même après redémarrage de
`ts-travel-service`, puis de `ts-seat-service`.

**Diagnostic, de haut en bas** (connexions ouvertes lues dans `/proc/net/tcp`
de chaque pod, requêtes vues côté MySQL, journaux) :

1. `ts-travel-service` : ses 10 connexions à la base dorment (`Sleep 232 s`),
   tenues par des requêtes qui attendent `ts-seat-service` (4 connexions sans
   réponse). Spring garde la connexion pendant toute la requête
   (`open-in-view`) : au-delà de 10 recherches en attente, les suivantes
   attendent 30 s et rendent `500`.
2. `ts-seat-service` : aucune erreur ; il attend `ts-order-service`
   (4 connexions sans réponse).
3. `ts-order-service` : 41 connexions à la base pour une réserve de 10,
   dormant depuis 20 min à 2 h ; journal : *« Thread starvation or clock leap
   detected (55 s) »* — la JVM (tas de 200 Mo) se fige.
4. La base : 9 643 commandes, dont **5 229 sur le train D1345 le 12 et 4 408
   le 13** — toutes les réservations visaient le même train à la même date
   (« demain »). Pour compter les places vendues, le service des sièges fait
   charger toutes ces commandes en mémoire à chaque recherche.

**Conséquence** : le comportement de train-ticket dépend du volume de ses
tables ; deux campagnes ne se comparent que si elles partent des mêmes
données. C'est aussi ce qui faisait baisser le débit au fil de l'heure dans
saine-03.

**Décisions** :
- `apps/donnees.sh purger` vide `orders`, `orders_other`, `food_order`,
  `delivery` (le déclencheur reste) et redémarre `ts-order-service`. Le pilote
  l'appelle au départ de chaque campagne, avant la collecte ; le compte rendu
  note l'état des tables (`donnees_au_depart`).
- Le générateur étale les dates de départ sur trente jours
  (`TT_JOURS_ETALEMENT`) : trente fois moins de commandes par train et par
  date.
- Remède documenté si la signature revient : redémarrer commandes, sièges,
  recherche, dans cet ordre.
- `apps/mysql.sh`, sourcé par `consommateur.sh` et `donnees.sh`.

## 2026-09-12 — Le débit de la file ne suit pas les voyageurs : nouveau parcours

**Mesuré** (saine-03, `queues.py` sur l'heure entière) :

| voyageurs | messages/s dans food_delivery |
|---|---|
| 10 | 0,40 – 0,60 |
| 30 | 0,37 – 0,60 |
| 10 | 0,22 – 0,53 |
| 55 | 0,13 – 0,35 |

Le débit **baisse** quand les voyageurs montent. Un message naît d'une
réservation, qui passe par la recherche de train — l'appel lourd. Dès 10
voyageurs la recherche ralentit ; à 55, chaque voyageur réserve moins qu'à 10.

**Conséquences** : la cause `charge` (« plus de voyageurs ») était impossible
par construction ; et un débit de 0,13 à 0,67 ne permet aucun dimensionnement
stable (30 % ou 120 % selon la minute).

**Décision** : un quatrième parcours dans le générateur, « commander un
repas » — un appel direct à `ts-food-service` (`POST /foodservice/orders`,
l'API existe, elle exige seulement un numéro de commande inédit), qui dépose
le même message dans `food_delivery` sans la recherche devant. Poids : repas
6, réserver 2, chercher 1, courriel 1. Le débit devient 0,12 message/s par
voyageur — 3/s à 25, 6/s à 50 — et la recherche reste à un niveau que
l'application tient à 50 voyageurs (moins de demande qu'avant à 25).

## 2026-09-12 — Le consommateur dimensionné pour sa charge (`apps/consommateur.sh`)

Deux réglages de plateforme, posés une fois avant la référence, jamais
changés ensuite, recopiés dans chaque compte rendu (`reglage_consommateur`) :

- **temps de service ≈ 0,7 s par message** : d'abord un déclencheur SQL
  (`SLEEP`) — abandonné le jour même, voir l'entrée suivante — puis un retard
  réseau de 140 ms par échange avec la base. Capacité des 3 répliques :
  ~4,3 messages/s ; à 25 voyageurs, **3,4 messages/s mesurés** (3,0 du
  parcours direct + 0,4 des réservations avec repas), occupation 80 %.
- **prefetch 1** (`SPRING_RABBITMQ_LISTENER_SIMPLE_PREFETCH=1`) : par défaut
  le courtier confie 250 messages d'avance à chaque réplique ; le tas visible
  (`messages_ready`) n'aurait bougé qu'après 750 messages en souffrance, et une
  réplique gelée en aurait emporté 250. Entraîne un redémarrage roulant, donc
  de nouveaux pods : d'où « avant la référence ».

Le déclencheur SQL avait été préféré au retard réseau pour ne pas mélanger
deux retards sur le même chemin (cause `lenteur`). La mesure a tranché
autrement (entrée suivante) ; `lenteur` remplace désormais le réglage le
temps de la panne.

Attendu avec ce réglage (à mesurer par les essais courts) : charge 25 → 50 :
160 % ; blocage : 120 % ; lenteur +1 s réseau : ~380 % ; hote : faible, le
temps par message étant de l'attente et non du CPU.

La charge de base est 25 voyageurs ; la référence saine ne dépasse jamais 25
(au-delà, le tas grossirait dans la référence elle-même). La cause `charge`
vise 50 (`--intensite 50`, défaut 2 × la charge).

## 2026-09-12 — Le consommateur a mille fois trop de marge (mesuré, résolu ci-dessus)

**Mesuré** (étalonnage, profil 80/160/320) : la file reçoit 0,5 message/s à
25–55 voyageurs ; trois répliques de `ts-delivery-service` en absorbent ~500/s
(6 ms par message). Marge × 1000.

**Conséquence** : aucune cause ne fait grossir le tas — une réplique gelée ou
un hôte saturé, les deux autres absorbent tout ; seule une lenteur énorme
(≥ 10 s par message) se verrait sur la file. Le modèle ne verrait jamais le
symptôme central de la thèse.

**Décision** : donner au consommateur un coût par message réaliste, comme
*réglage de plateforme* posé avant la référence saine — pas comme panne. La
valeur se choisit par étalonnage pour que la charge de base occupe ~70 % de
la capacité. La référence saine (saine-03) est donc à refaire une fois ce
réglage posé. La cause `hote` restera la plus faible des quatre (une réplique
ralentie par le CPU quand son coût est surtout de l'attente) — à mesurer.

**Aussi mesuré** : l'application plafonne entre 55 et 80 voyageurs, et ce
n'est pas le CPU : `ts-travel-service` a 10 connexions à sa base (défaut
Spring) et en garde une pendant toute une recherche ; au-delà de 10 recherches
simultanées, les autres attendent 30 s et rendent `500`. Quand ça arrive, les
réservations s'arrêtent et la file **se vide**. La charge de base doit rester
nettement sous ce plafond (40 voyageurs), et la cause `charge` ne peut pas
dépasser ~60.

## 2026-09-12 — Les quatre injections existent (`apps/panne.sh`)

| cause | mécanisme | outil |
|---|---|---|
| charge | plus de voyageurs, retour programmé | `loadgen.sh scale` |
| lenteur | retard réseau entre les répliques et `tsdb-mysql` | Chaos Mesh NetworkChaos |
| hote | pod « voisin bruyant » hors du graphe, sur l'hôte d'une réplique, tous les cœurs | Chaos Mesh StressChaos |
| blocage | `SIGSTOP` sur le Java d'une réplique | `kubectl exec` |

Chaque injection expire d'elle-même. `panne.sh etat` rend 3 si quelque chose
est en place, et le pilote refuse alors de partir — saine comprise.
Correction de doc : `SIGSTOP` ne fait PAS redémarrer le pod, train-ticket n'a
pas de sonde de vivacité (vérifié dans ses manifestes).

Pilote (`campagne.sh`) : `--panne --a --duree --intensite --cible` ; instants
calculés depuis un point de départ unique ; témoins avant / pendant / après ;
`Ctrl-C` retire, clôt, écrit le compte rendu ; lu en entier avant d'exécuter
(un `git pull` pendant une campagne le tuait) ; compteurs Locust remis à zéro
au départ ; charge ramenée au premier palier à la fin.

`bilan` : deux lectures (totaux depuis le reset, et maintenant/s), le p50, et
le motif des échecs. Les totaux seuls ne disaient pas *quand*.

`queues.py` : une ligne par fenêtre pour une file — la lecture d'un étalonnage.

## 2026-09-11 — Référence saine-03 : signature confirmée

Campagne complète, `scaler.json` écrit. Sur toute l'heure : tas 0, écart 0,
3 consommateurs, 0,35–0,67 message/s selon le palier. Un service chaud par
déploiement (ici `station-food` à 0,4 cœur, avant `ts-order-service`) : un
hôte affiche une pression CPU 30–70 × les autres. Normal, pas une panne.
Les 3 répliques de `delivery` sont sur trois hôtes différents.

Reproductibilité vérifiée : création des VMs → campagne, en suivant
`INSTALL.md` puis `PROCEDURE.md`, sans intervention hors doc.

## 2026-09-10 — Deux campagnes perdues, deux causes

- saine-01 : jeton de connexion expiré (~1 h) → tous les parcours en `500`,
  pods `Running`, collecte active, rien ne le montrait. Correction :
  reconnexion proactive toutes les 20 min, en-tête vidé avant. Et `bilan`
  avant chaque campagne, obligatoire.
- saine-02 : VMs expirées en pleine campagne (`DURATION=10h`). Réglage : `3d`.
- Le soir, « aujourd'hui » ne rend aucun train : recherche pour le lendemain
  (`TT_JOURS_AVANCE=1`).

## 2026-09-10 — Chaos Mesh avant la référence

Installé **avant** la référence saine : son démon tourne sur chaque nœud, son
coût doit être des deux côtés. Une liste de tolérances remplace celle du
chart : `operator: Exists` pour que le démon monte aussi sur le master.
`CHAOS_VERSION` à figer dans `.env`.

## 2026-09-10 — Deux copies des scripts

`git pull` sur le nœud de contrôle ne met pas à jour le master :
`./deploy.sh --push-scripts` après chaque changement dans `apps/`. Le
locustfile vit dans un ConfigMap : `loadgen.sh uninstall && install` pour le
recharger.

## 2026-09-10 — Le dépôt rangé par machine

`deploy.sh`, `destroy.sh`, `lib/`, `campagne.sh`, `graphe_en/` tournent sur
le nœud de contrôle ; `apps/*.sh` sur le master. `graphe/` (ancienne version)
et `test.sh` supprimés. Les campagnes vivent dans `campagnes/<nom>/`
(compte rendu + journaux du master), à committer : c'est la provenance.

## 2026-09-09 — Corrections de la chaîne de graphe (`graphe_en/`)

- `process_rate` (nœud) valait 2 × `consume_rate` (arête) : il comptait les
  spans, pas les messages. Supprimé.
- Un message consommé = deux spans (livraison par le courtier, 0,09 ms ;
  traitement par l'application, 6 ms). Le p50 mélangeait les deux, 22 × trop
  petit. On garde le span de traitement (absence de `network.peer.address`).
- Les positions de pente étaient des indices figés : par nom maintenant.
- Un `scaler.json` d'une autre largeur de colonnes s'appliquait en silence :
  refusé.
- Deux définitions de « échec » : une seule, `otlp.failed()`.
- Plage à cheval sur minuit : refusée avec explication.

## 2026-09-09 — Le modèle (rapport de recherche externe)

R-GCN + MLP d'arêtes sur `calls`, entraînement en deux temps, classifieur
prototypique à peu d'exemples, rejet hors ensemble par distance aux
prototypes. Le point aveugle asynchrone de la littérature RCA est confirmé.
Rien ne change au graphe.

## Avant le dépôt — la construction de la plateforme (jusqu'au 9 septembre)

Résumé chronologique ; le détail, les mesures et les erreurs sont dans
`notes/OBSERVABILITE.md` (§3 découvertes, §4 briques, §8 journal, puis une
section par module du graphe), `notes/CHOIX.md` et `notes/RECOMMANDATIONS.md`.

1. **La grappe** (`deploy.sh`, Kubespray sur SLICES-RI). Deux Helm sur le
   master (v4 pour otel-demo, v3 pour les charts de train-ticket) ; une
   `StorageClass` par défaut, sans laquelle MySQL et Nacos restent en
   `Pending` ; une attente active des VMs à la place d'un `sleep` ; les
   scripts d'application copiés et exécutés sur le master. (CHOIX.md)
2. **L'application étudiée** : train-ticket (46 services, deux files RabbitMQ :
   `food_delivery` et `email`). otel-demo retiré : collisions et machines.
3. **La chaîne de mesure à nous** (`observability.sh`) : collecteur
   OpenTelemetry, Prometheus, Jaeger, relevés des machines et de Kubernetes,
   port de mesure du courtier. Découverte qui décide de tout le graphe : le
   courtier ne donne PAS de débit par file — les débits déposé / retiré
   viennent des traces, pas des compteurs. (OBSERVABILITE.md §3.2)
4. **Faire parler les 46 services** (`instrument.sh`) : agent Java 2.31.1
   attaché sans toucher au code, version figée ; téléchargé depuis Maven parce
   que le registre d'images de GitHub est bloqué sur SLICES-RI. Un message
   consommé donne deux notes (livraison par le courtier, traitement par
   l'application) — c'est la seconde qui compte. (§8)
5. **Le trafic** (`loadgen.sh`) : Locust dans la grappe, hors de l'espace
   applicatif, non instrumenté ; trois parcours d'abord, choisis pour toucher
   les files. La file `email` est morte dans cette version (l'envoi est
   commenté par les auteurs) : un point d'entrée de test l'alimente. Trois
   écarts constatés avec la documentation officielle (noms de champs, gares en
   minuscules, date passée refusée). (§« Le générateur »)
6. **Isoler la mesure** : un nœud réservé (`OBS_DEDICATED_NODE`), taché, où
   vivent collecteur, Prometheus, Jaeger et Locust — leur coût ne se mêle pas
   à celui des services mesurés.
7. **Sortir les données** : magasin d'objets MinIO (survit à la destruction
   des VMs), compression, traitement de la saturation du disque, compteurs
   exportés eux aussi, liste des compteurs gardés (`metrics-keep.txt`).
8. **Le graphe** (`graphe_en/`, ex-`graphe/`) : à quelle fenêtre appartient
   une note (décision mesurée), largeur et pas, marge aux bords retirée sur
   preuve, `null` jamais 0, aucun one-hot, format neutre puis PyTorch
   Geometric, manifeste qui décrit le jeu de données. Trois écarts au papier,
   tous mesurés. (sections « Le découpage », « Les valeurs », « Les flèches »)
9. **Six correctifs au déploiement (2026-09-10)** : MySQL inaccessible en
   IPv6, boucle arrêtée à la première base, `--apps-only` sans bastion,
   `isolate` qui expulsait l'inexpulsable, épinglage avant étiquetage, profil
   de dimensionnement périmé. (RECOMMANDATIONS.md, dernière section)
10. **Revue de la formalisation (2026-09-09)** : neuf défauts dans le papier,
    dont deux corrigés dans le code — voir l'entrée du 9 septembre ci-dessus.
    (RECOMMANDATIONS.md §1)

## Règles qui ne bougent plus

- `export.scaler: write` une seule fois, sur la référence saine ; `apply`
  partout ailleurs.
- `windows.width_s` / `step_s` ne changent pas entre deux campagnes.
- Identifiants du magasin dans `.env.secrets` et `graphe_en/config.yaml`,
  jamais dans git.
- `DURATION=3d` pour les VMs. Horloges NTP des deux côtés.
- Pas de code adapté à un incident : la règle dans le code, le récit dans le
  commit.

## 2026-09-24 — Phase A.1 : le pod leader de la base

Le leader est lu dans les mesures archivées sur S3, puis vérifié sur le cluster
(expérience `deployk8s_slices_final`, accès par le contrôleur `vms0`, jamais
directement depuis le poste).

Méthode : débit reçu (`container_network_receive_bytes_total`) des trois pods
`tsdb-mysql`, sur une minute au début et une vers la fin de chaque campagne. Le leader
reçoit toutes les écritures, il reçoit donc bien plus que les deux autres.

| campagne | minutes | tsdb-mysql-0 | tsdb-mysql-1 | tsdb-mysql-2 |
|---|---|---|---|---|
| saine-08 | 02:58, 03:25 | 50 / 37 ko/s | 6 / 5 | 7 / 6 |
| charge-03 | 04:14, 05:45 | 49 / 8 | 7 / 3 | 7 / 3 |
| blocage-02 | 06:52, 08:20 | 44 / 44 | 7 / 7 | 7 / 7 |
| lenteur-01 | 09:07, 10:35 | 47 / 51 | 7 / 7 | 7 / 7 |
| hote-01 | 11:24, 12:55 | 50 / 52 | 6 / 6 | 6 / 6 |

Résultat : `tsdb-mysql-0` est le leader dans les cinq campagnes, avec le même uid
(35b0f5fb…), jamais redémarré. Les appelants écrivent l'adresse `tsdb-mysql-leader`
(service Kubernetes) : cette adresse se relie donc au pod `tsdb-mysql-0`. La
correspondance se fait par le nom du pod, stable dans un StatefulSet, plutôt que par
l'uid, qui changerait si le pod était recréé.

Vérifié sur le cluster le 24 septembre : `tsdb-mysql-leader` pointe vers
`tsdb-mysql-0`, uid 35b0f5fb-f49f-4241-a901-7f58fd832737, démarré le 11 septembre à
21:02 UTC. C'est le même pod que pendant les cinq campagnes.

## 2026-09-24 — Phase A.2 : la relation queries (appelant → base)

Code : `graphe_en/edges.py` (relation `queries`, fonction `_queries`), `settings.py`
(`graph.databases`, vide par défaut), `run.py` (colonne et alerte), `config.example.yaml`.
Exécuté sur vms0, blocage-02, 06:23 à 06:28, configuration hors du dépôt
(`~/configs-hors-git/config-a2.yaml`, elle contient les identifiants).

Résultat, fenêtre 06:25 : 15 arêtes `queries`, toutes vers `tsdb-mysql-0`, aucune
adresse inconnue, résolution des appels inchangée (100 %).

- r5pwb et tvmfl : 2,8 appels/s, p50 141 ms (le retard réglé de 140 ms).
- bmgvs, gelée : aucune arête `queries`, comme pour consumes.
- les douze autres appelants : p50 de 0,2 à 0,8 ms.

Une base lente ferait donc monter d'un coup les quinze arêtes ; la cause 2 ne fait
monter que celles des répliques. Les figures ne dessinent pas encore la relation
(étape A.7).

## 2026-09-24 — Phase A.4 : quatre attributs réseau pour l'hôte

Code : `apps/metrics-keep.txt` (six compteurs node-exporter), `graphe_en/features.py`
(`net_rx_rate`, `net_tx_rate`, `net_drop_rate`, `tcp_retrans_ratio`, interface
physique seulement), `export_pyg.py` (échelle log), `LEXIQUE.md`. Le vecteur hôte
passe de 5 à 9 nombres. Les campagnes du 13 septembre n'ont pas ces compteurs :
absents, jamais 0. La mise à l'échelle calée sur saine-08 ne correspond plus
(`_check_scaler` refuse) : une nouvelle référence normale est nécessaire.

Déploiement : `git pull && ./deploy.sh --push-scripts` sur vms0, puis sur le master
`observability.sh tune`. PIÈGE vécu : `tune` lancé sans l'environnement de l'étape 3
a réinstallé Prometheus et la passerelle sans le nœud réservé ni l'envoi S3 (pods
Pending, puis passerelle en boucle, dix minutes, hors campagne). La seule forme
correcte, sur le master :

    set -a; . ~/autodeploy/.env.secrets; set +a
    export OBS_DEDICATED_NODE=workers6
    bash ~/autodeploy/apps/observability.sh tune

`tune` rallume aussi la passerelle, donc la collecte : la refermer ensuite avec
`collecte.sh arreter` si aucune expérience ne suit.

Vérifié : les six compteurs arrivent dans S3 dès 16:52 UTC pour les huit machines,
interface physique `enp6s18`. Graphe de 16:51 à 16:57 sur vms0, fenêtre 16:53 :
réception 13 à 134 ko/s (workers6, la mesure, en tête), envoi 17 à 113 ko/s,
2 paquets jetés par minute partout, aucune retransmission TCP. Collecte refermée.

## 2026-09-25 — Référence normale saine-09 (seconde série)

Pilote : `./campagne.sh saine-09 --profil "10:30,25:30,20:30,15:30"` sur vms0, tmux
`normale`, le 24 septembre de 17:34 à 19:34 UTC. Données remises à zéro au départ
(10 lignes), quatre paliers confirmés, douze veilles « parcours ok », file au plus à 3
au palier de 25 voyageurs puis revenue à 0. Aucun redémarrage de conteneur, mesure
restée sur workers6. Plage exploitable 17:37 à 19:32.

Graphe sur vms0 (`~/configs-hors-git/config-saine-09.yaml`, `databases` et
`scaler: write`), run `20260925-113438` : 1 547 116 spans, 115 fenêtres, 58/2/8 nœuds,
cinq relations dont 15 ou 16 arêtes `queries` par fenêtre, résolution 100 %,
0 avertissement. `scaler.json` recalé sur saine-09 (18 / 6 / 9 colonnes) ; l'ancien,
calé sur saine-08, est gardé en `scaler-v1-saine-08.json`.

Valeurs absentes 29,7 % contre 30,4 % pour saine-08, mêmes colonnes (temps de traitement
et de requête des pods qui n'en ont pas) : structurel. Colonnes réseau de l'hôte
remplies partout. Les trois répliques du consommateur interrogent la base en 143 ms,
les autres appelants en quelques millisecondes.

Observé grâce aux nouveaux compteurs : la réception de workers1 et l'envoi de workers4
montent au fil de la campagne (50 ko/s à 1,2 Mo/s). C'est ts-order-service qui reçoit
de plus en plus d'octets de tsdb-mysql-0 : la table des commandes grossit après la
remise à zéro et chaque lecture la renvoie. saine-08 montrait déjà la même montée
(15 à 896 ko/s). Comportement de l'application, identique dans toutes les campagnes
tant que chacune part de la même purge et dure autant ; les hôtes visés par les pannes
(workers0, 2, 5) ne sont pas concernés.

## 2026-09-25 — Cibles tournantes : `--cible` en liste, essai à blanc réussi

Code (commit 58c9691) : `campagne.sh --cible x,y,z` donne une cible par injection, dans
l'ordre des `--a` (chaque cible suit sa minute au tri) ; une seule cible vaut pour
toutes ; refusée pour charge et lenteur ; chaîne entière limitée aux caractères d'un nom
Kubernetes. `panne.sh verifier <cause> --cible …` contrôle chaque cible avant le départ :
réplique en marche (blocage) ; nœud qui porte une réplique, démon Chaos Mesh, place libre
(hote). Le déroulé note la cible après le résultat, `ligne_de_base.py` lit les lignes
comme avant (vérifié sur les essais et sur blocage-02). Relecture par quatre relecteurs
indépendants : deux défauts réels corrigés avant le commit (liste collée avec des retours
à la ligne réduite à son premier nom ; hôte sans réplique accepté comme cible).

Ordre retenu pour la seconde série : blocage bmgvs (workers2) → r5pwb (workers0) →
tvmfl (workers5) ; hôte workers5 → workers2 → workers0. Au même rang d'injection, les deux
causes ne frappent jamais la même machine. Les huit machines ont 4 cœurs : l'intensité
par défaut de l'hôte vaut 2 partout. La demande du voisin reste plafonnée par la place
libre de chaque machine (1 400 à 1 700m, comme les 1 600m de hote-01) ; le stress, lui,
occupe les 4 cœurs à 100 % partout.

Avant l'essai, le pilote a refusé de partir : « chercher un train » à 43 % d'échecs,
15 057 commandes après 15 h de Locust à 10 voyageurs depuis la fin de saine-09. Remède
`donnees.sh purger --redemarrer`, recherche revenue à 0,9/s sans échec.

Essai sur vms0, collecte éteinte (`--sans-collecte`, rien dans S3), 12 min par cause,
injections de 2 min aux minutes 3, 6 et 9 : six injections confirmées, chacune sur sa
cible (pannes.tsv et déroulé concordent), réplique gelée à 0m de CPU, hôte visé à 4000m,
rien de résiduel. Dossiers d'essai rangés hors du dépôt.

## 2026-09-25 — Seconde série : blocage-03, hote-02, charge-04, lenteur-02

Enchaînées sur vms0 (tmux `serie`, script hors dépôt), 11:10 → 20:13 UTC, chacune
25 voyageurs pendant 135 min, injections de 20 min aux minutes 5, 50 et 95, mêmes
intensités qu'en septembre (charge 35, lenteur +75 ms, hôte 2 cœurs). Cibles tournantes :
bmgvs → r5pwb → tvmfl ; workers5 → workers2 → workers0. 12 injections sur 12 confirmées
sur leur cible, 13 veilles « parcours ok » par campagne, aucun redémarrage de conteneur,
retard de base reposé, S3 complet (aucune minute sans traces ni mesures).

| campagne | plage | file 1 min après retrait | septembre |
|---|---|---|---|
| blocage-03 | 11:13–13:23 | 794 / 791 / 798 | 768 / 695 / 698 |
| hote-02 | 13:29–15:39 | 0 / 0 / 7 | 0 à 9 |
| charge-04 | 15:45–17:56 | 704 / 731 / 721 | 696 / 754 / 490 |
| lenteur-02 | 18:01–20:11 | 814 / 813 / 896 | 847 / 853 / 883 |

Graphes sur vms0 avec la mise à l'échelle de saine-09 appliquée (`scaler: apply`),
130 ou 131 fenêtres, 0 avertissement, 29,5 à 29,8 % de valeurs absentes (saine-09 :
29,7 %). Marques relevées dans le graphe, 5 fenêtres avant contre fenêtres pendant :
- blocage : la réplique visée seule perd son temps de traitement, son CPU tombe à 0 et
  son arête `queries` disparaît ; `consumers` 3 → 2 ; retrait 3,5 → 2,83 msg/s.
- lenteur : les trois répliques 706 → 1 081 ms par message, leurs arêtes `queries`
  141 → 216 ms (+75 exactement) ; les douze autres appelants de la base restent à 0,45 ms.
- charge : dépôt 3,5 → 4,9 msg/s, répliques inchangées.
- hote : l'hôte visé seul à `cpu_busy` 0,83 et `cpu_pressure` 0,64 à 0,72.

**Constaté : la 3e injection d'hôte (workers0) remonte en amont.** Le dépôt dans la file
tombe de 3,6 à 0,94 msg/s, ce que ni workers5 ni workers2 ne font, ni workers0 en
septembre (hote-01, dépôt 3,4 à 3,9 pendant les trois injections). Cause :
`donnees.sh purger --redemarrer`, lancé le 25 sept. vers 10:30 pour débloquer
l'application avant l'essai à blanc, a recréé ts-order-service, ts-seat-service et
ts-travel-service, et l'ordonnanceur les a replacés : ts-order-service workers1 →
workers0, ts-seat-service workers3 → workers2, ts-travel-service workers4 → workers1.
Sur workers0 saturé, ts-order-service passe de 3 à 640 ms par requête, la réservation
(ts-preserve-service) de 0,2 à 84 s, donc moins de repas commandés et moins de messages
déposés. L'étiquette reste juste (l'hôte workers0 est fautif), mais cette injection, qui
est l'injection de test, se propage par le producteur alors que les deux premières
restent sur l'hôte. Le placement des pods n'est pas figé par la plateforme ; il fait
partie des conditions à noter dans chaque compte rendu.

## 2026-09-26 — Phase A.6 : lignes de base, septembre refait et seconde série à l'aveugle

**Septembre refait.** Les cinq campagnes du 13 septembre reconstruites sur vms0 avec le code
du graphe actuel (relation `queries`, hôte à 9 nombres ; sans mise à l'échelle, que les lignes
de base n'utilisent pas) : runs 20260926-020314 (saine-08), -020626 (charge-03), -021439
(blocage-02), -022230 (lenteur-01), -023015 (hote-01), 0 erreur, deux avertissements attendus
(compteurs réseau jamais relevés en septembre ; pas de mise à l'échelle). Les `lecture.txt`
régénérés ne diffèrent des originaux que par le numéro de run, et `ligne_de_base.py` redonne
exactement `campagnes/lignes_de_base.txt` : 150/150 inchangé. Les originaux sont gardés,
ce sont eux que cite le rapport.

**Seconde série, premier test à l'aveugle.** `ligne_de_base.py` tel que commité le 18 sept.,
aucune colonne ni aucun facteur changé, sur saine-09, blocage-03, hote-02, charge-04,
lenteur-02 : 636 fenêtres lues, 460 gardées, 162 de test (19 à 20 par cause, 85 normales).
Seuil : 57/57 pannes de file trouvées, 0 fausse alerte, hôte jamais. File seule : 142/162
(arbre), hôte jamais. Tableau plat : 162/162 (arbre et forêt). Règles à la main : 162/162.
L'arbre retrouve les mêmes quatre questions qu'en septembre (rate_imbalance > 0,20 ;
hote_cpu_busy_max > 0,32 ; process_time_p50_max > 894 ms ; publish_rate > 4,14). L'injection
de test d'hôte qui s'est propagée (workers0) est bien nommée : la file reste calme et l'hôte
chargé. À noter : la règle de lenteur coupe à 883 ms (1,25 × 706) et le normal à faible
trafic est à 846 ms ; la marge n'est que de 37 ms. Résultat : `campagnes/lignes_de_base_serie2.txt`.

Conclusion : sur les quatre causes, un tableau sans flèches nomme la cause à l'aveugle comme
en septembre. Le résultat du rapport tient ; l'intérêt des flèches et du modèle se jouera sur
la base lente (fautif muet) et les jumeaux.

## 2026-09-26 — Phase A.7 : les figures dessinent la relation `queries`

`render.py` (commit a87bb6a) : les arêtes `queries` sont tracées en tirets gris foncé,
courbées dans l'autre sens que `calls`, épaisseur selon le débit ; la vue de la file ajoute
les bases que ses instances interrogent, avec leur hôte (5 instances, 1 file, 4 hôtes pour
food_delivery), sans quoi la flèche réplique → base ne pourrait jamais y figurer ; chaque
hôte affiche aussi son réseau reçu et envoyé. Les instantanés construits avant la relation
se dessinent comme avant (pas de clé `queries`). README du graphe : cinq relations, hôte à
9 nombres. Vérifié sur vms0, sur une copie des fenêtres de lenteur-02 (18:02 et 18:13) :
les trois répliques et ts-food-service reliées à tsdb-mysql-0 dans la vue de la file, les
quinze arêtes convergent vers la base dans la vue complète. Images :
`~/verifications-phases/A7/` sur le poste.

## 2026-09-26 — Phase A.8 : le graphe est figé (étiquette `graphe-fige`)

À partir d'ici, plus aucune colonne, relation, réglage de fenêtre ni mise à l'échelle ne
change. Raison : les témoins (phase B) puis le GNN (phase E) doivent tous lire le même
graphe, et il est figé avant toute donnée de la base lente (phase C) ; un graphe retouché
après l'avoir vue serait taillé pour la réponse.

- `graphe_en/graphe_fige.json` : ce qui est figé (colonnes de chaque sorte de nœud, cinq
  relations et leurs colonnes, colonnes passées au log, réglages, adresse de la base et son
  pod, écriture des tenseurs, empreinte de la mise à l'échelle, fichiers qui calculent le
  graphe).
- `graphe_en/gel.py` : la vérification. Référence lue dans l'étiquette, pas sur le disque ;
  étiquette absente = écart. `gel.py runs/<a> …` contrôle en plus le code qui a construit
  chaque run (empreintes du manifest contre l'étiquette), ses réglages, sa mise à l'échelle,
  ses colonnes et ses arêtes `queries`.

Deux relectures indépendantes avant l'étiquette (chaque constat revérifié à part) ont
ajouté au gel :
- **Les flèches sont mises à l'échelle comme les nœuds**, sur saine-09 (log des débits et
  durées). Sans cela, la décision serait revenue au GNN, en phase E, donc après la base
  lente, qui ne se voit que par les flèches `queries`. Les statistiques des nœuds sont
  identiques à l'ancienne mise à l'échelle ; nouvelle empreinte 53b6728f…, l'ancienne
  gardée sur vms0 (`scaler-v2-saine-09-noeuds.json`).
- **Chaque run dit quel code l'a construit** (commit, sha256 de chaque module), avec quelle
  mise à l'échelle et quelle base visée ; chaque fenêtre compte ses appels à une base
  inconnue. Un graphe sans aucune arête `queries` est refusé.
- Corrigés au passage : l'écart 4 du manifest, périmé depuis 2a0ccc4 (le débit de
  traitement n'est plus en double) ; un refus de `run.py` affiche enfin sa raison ; le
  lexique (valeurs réseau saines de saine-09, pertes constantes par machine, 0,033 ou 0,05 ;
  la panne hôte fait monter `tcp_retrans_ratio` sur l'hôte visé et sur le master).

Les 10 graphes des deux séries ont été reconstruits sur vms0 avec le code figé (saine-09 en
`write`, les 9 autres en `apply`) : `gel.py` les dit tous CONFORMES ; le graphe de saine-08
d'avant le gel (runs/20260913-053054) est refusé (pas de `queries`, hôte à 5 nombres, code
inconnu). Les 10 `lecture.txt` ne changent que par le numéro du run : aucun nombre n'a
bougé. Seul avertissement, attendu : la première série n'a pas les compteurs réseau.

| campagne | run figé | | campagne | run figé |
|---|---|---|---|---|
| saine-09 | 20260926-033245 | | saine-08 | 20260926-041410 |
| blocage-03 | 20260926-034025 | | charge-03 | 20260926-041723 |
| hote-02 | 20260926-034850 | | blocage-02 | 20260926-042549 |
| charge-04 | 20260926-035654 | | lenteur-01 | 20260926-043347 |
| lenteur-02 | 20260926-040544 | | hote-01 | 20260926-044150 |

Pour la suite : les témoins de la phase B liront les fenêtres de ces runs (vérifiées par
`gel.py`), pas `lecture.txt` (arrondi, produit par des fichiers hors du gel).

## 2026-09-26 — Phase B.1 : le fautif de chaque injection, et comment on juge

Écrit avant tout calcul des témoins et avant toute donnée de la base lente :
`graphe_en/fautifs.py` (commits e338da4, 3c5aa84), qui produit `campagnes/fautifs.txt`.

Le fautif, par cause : blocage = la réplique gelée ; hôte = la machine (même quand la
panne remonte en amont, hote-02 injection 3) ; lenteur = les trois répliques ; **charge =
aucun fautif** (décidé avec l'utilisateur : rien n'est cassé, il y a plus de voyageurs ;
jugée sur la cause seulement) ; base lente (C) = le pod de la base ; jumeaux (D) = la
machine au réseau dégradé, jamais le leurre. Les 24 injections des deux séries ont leur
réponse, tirée du registre des pannes de chaque campagne ; les 18 qui ont un fautif le
retrouvent comme nœud du graphe figé dans chaque minute de l'injection.

Une relecture indépendante (2 relecteurs, chaque constat revérifié) a montré que les
règles de jugement étaient incomplètes ; complétées avant tout calcul :
- chaque témoin rend une alarme, une cause et un classement de tous les nœuds ; seuil
  d'alarme réglé sur les minutes normales d'apprentissage ; réglé sans puis avec exemples ;
- fausses alertes mesurées au fil du temps ; saine-09 à part (vue par la mise à l'échelle) ;
- top-k principal sans tenir compte de l'alarme, donné aussi « avec alarme » ;
- égalités départagées contre le témoin, jamais par l'ordre alphabétique des fichiers
  (il mettrait bmgvs et workers0 en tête, les fautifs fixes de la première série) ;
- mesures par minute et par injection ; une cause jamais vue est jugée sur toutes ses
  injections, la bonne cause y étant « panne inconnue ».
Et la lecture des campagnes à venir échoue bruyamment au lieu de se taire : campagne
interrompue, nom de cause inconnu, retrait raté, injection jamais retirée, compte
d'injections différent de l'en-tête, nombre de répliques de la lenteur.

## 2026-09-26 — Phase B.2 : le juge commun

`graphe_en/juge.py` (commits de B.2 jusqu'à 519c686) : tous les témoins, puis le GNN, passent
par lui. Il lit les 10 graphes figés (refusés s'ils ne sont pas conformes au gel), étiquette
chaque minute, coupe apprentissage et test, et note les réponses avec les règles de B.1.
`campagnes/etiquettes.txt` en garde la trace (identique sur le poste et sur vms0).

Étiquettes et coupure identiques à celles des lignes de base (`ligne_de_base.py`), minute
par minute, sur les 1 211 minutes : 408 normales, 458 de panne, 303 de vidange, 42 à cheval.
Test sans les écartées : 312 minutes, dont 153 de panne (8 injections, 6 avec un fautif) et
159 normales (39 de saine-09, marquées « vues » par la mise à l'échelle).

Une relecture indépendante (3 relecteurs, chaque constat revérifié) a trouvé de vrais
défauts, corrigés avant qu'un seul témoin soit calculé :
- le fautif n'était classé que parmi les nœuds notés par le témoin : un témoin qui ne
  notait RIEN obtenait 100 %. Il est maintenant classé parmi tous les nœuds de la fenêtre ;
- un NaN float32 (numpy, tenseur) sur le fautif le mettait premier ; classé dernier ;
- une alarme « False » (texte) ou 0,03 (probabilité) comptait comme alarme ; refusée,
  comme toute réponse mal formée ou un nœud nommé par son uid ;
- la bonne cause dépendait de la liste passée à la notation ; fixée une fois à la lecture.
Chaque correction a son essai dans le script (témoins factices de note connue, refus).

**Constat honnête, à écrire dans le rapport.** Un témoin « a priori », qui ne lit AUCUNE
donnée et classe les nœuds par le nombre de fois qu'ils ont été fautifs à l'apprentissage,
obtient déjà 100 % en top-1 sur la lenteur et 100 % en top-3 sur le blocage : les fautifs
sont toujours les trois mêmes répliques. Il fait 0 sur l'hôte. Sur les quatre causes
actuelles, les mesures qui départagent vraiment sont donc le top-1 du blocage et de l'hôte ;
et la base lente (C), dont le fautif n'a jamais été fautif, où ce plancher fait 0.

## 2026-09-26 — Phase B.3 : témoin 1, le tableau équitable

`graphe_en/temoin_tableau.py` (commits de B.3 jusqu'à 96d2622), résultat dans
`campagnes/temoin_tableau.txt` (identique sur le poste et sur vms0, 5 graines).

Ce qu'il voit : tous les nombres des nœuds (1128 par fenêtre, la base comprise, chaque pod
à une case fixe « service#rang »), plus des résumés sans identité : par sorte de nœud (max,
min, médiane, absents) et par relation (nombre de flèches, max et médiane de chaque
colonne). Il sait qu'un appel a ralenti quelque part, jamais qui appelle qui ni qui tourne
où. Deux forêts : la cause (rejet « inconnue » des deux côtés, seuils calés en mettant de
côté chaque injection ou campagne d'apprentissage) ; le fautif (une forêt pour tous les
nœuds, comme le GNN partage ses poids). Réglé avec exemples seulement : sans exemple, c'est
le score par nœud (témoin 2).

**Deux versions écartées, dites honnêtement.** (1) Rejet calé « hors sac » : trop sévère
(fenêtres voisines de la même injection dans les arbres), cause 33 % → recalé par injection
mise de côté. (2) Relecture indépendante : le fautif appris case par case ne pouvait désigner
que les 6 cases déjà fautives, plaçait la base dernière d'avance, et manquait le seul fautif
nouveau (tvmfl) ; les graines changeaient les chiffres ; il ne recevait aucun nombre des
flèches ; il ne pouvait pas dire « inconnue » d'une panne prise pour normale. Les quatre
points corrigés, chaque fois dans le sens qui RENFORCE le témoin (un adversaire faible
rendrait la victoire du GNN sans valeur).

Résultat (test, 5 graines, min–max) : détection 153/153 ; cause 149–153/153 (8/8
injections) ; fautif top-1 114–115/115, fautif nouveau 19/19 (6/6 injections) ; fausses
alertes 8–10/120 minutes normales non vues, 0/39 sur saine-09. Plancher « a priori » :
fautif top-1 57/115.

**Répétition d'une panne jamais vue** (une cause connue retirée de l'apprentissage, graine 0) :
- blocage retiré : détection 114/114, « inconnue » 114/114, fautif top-1 0/114 ;
- lenteur retirée : détection 114/114, « inconnue » 114/114, fautif top-1 0/114 ;
- hôte retiré : détection 3/117, fautif 0/117 (sans exemple, la panne CPU ressemble au normal).
Le tableau sait qu'une panne est NOUVELLE, pas OÙ elle est : son fautif n'a appris que les
motifs des causes vues. C'est le terrain de la première étape du GNN (l'écart au normal,
nœud par nœud) et du témoin 2.

## 2026-09-26 — Phase B.4 : témoin 2, le score par nœud

`graphe_en/temoin_noeud.py` (commit 4ca7001, puis 98ec3f9 et ea31952 après relectures ;
sortie de 4ca7001 gardée en 483e814), résultat dans `campagnes/temoin_noeud.txt` et `-validation.txt`.

Chaque nœud comparé à SON normal (appris sur les fenêtres normales d'apprentissage) :
écart robuste z par nombre, plus le nombre de valeurs absentes ; aucune flèche lue.
Deux réglages : **sans exemples** (score = plus grand |z| ; alarme au 95e centile du
normal mis de côté campagne par campagne ; cause « inconnue » dès qu'il sonne) et **avec
exemples** (détecteur forêt sur le profil d'écart, fautif par régression logistique
partagée, cause par prototypes avec rejet ; devant une panne « inconnue », le classement
retombe sur l'écart seul, comme le GNN désignera toujours par son étape 1).

**Quatre versions vues sur le test, dites** (`campagnes/versions-vues-sur-test/`) :
1. échelle par l'écart interquartile seul : seuil d'alarme 138 (pics rares de
   cpu_throttle_ratio, memory_slope) ; défaut vu sur le calage, mais la version avait
   aussi été notée sur le test (détection 48/153) ; corrigé ;
2. détecteur en régression logistique : seuil 0,043, 33/120 fausses alertes au test ;
   remplacé par une forêt APRÈS ce test ;
3. commit 4ca7001 (noté sur le test) : lenteur top-1 0/38 sans exemples ;
4. version finale, après deux relectures indépendantes. Leurs constats, vérifiés sur la
   **validation** (nouvelle, voir B.5), jamais sur le test :
   - le plancher d'échelle mesurait les différences de niveau entre nœuds : 0,28 en
     log pour le temps de traitement, 7 fois l'échelle propre des répliques, la lenteur
     n'y faisait que z = 1,5 ; maintenant, les écarts de chaque nœud à SA médiane ;
   - le détecteur apprenait sur des écarts au normal qui contient la fenêtre même : il
     apprend maintenant sur des écarts « croisés » (normal appris sans la campagne) ;
   - le fautif appris ne connaît que les pannes apprises : repli sur l'écart seul ;
   - distances aux prototypes mises à l'échelle.

**Résultat (test)** : sans exemples, détection 42/153, fausses alertes 5/120, fautif
top-1 100/115 (hôte 39/39, blocage 36/38, lenteur 25/38), 6/6 injections sans l'alarme.
Avec exemples (5 graines, médiane [min–max]) : détection 153/153, fausses alertes
28/120 [19–30], cause 130/153, fautif top-1 113/115.

**Ce qu'il apprend à la thèse.** Sans exemples, il désigne souvent la victime : la file,
dont le tas s'écarte bien plus que la réplique gelée ou lente. Ce résultat varie avec la
coupure : sur la validation, blocage top-1 1/38 et lenteur 0/38 (la file désignée),
contre 36/38 et 25/38 au test ; seul l'hôte est solide (39/39 partout). Avec exemples,
ses fausses alertes viennent de la dérive de fin de campagne : le CPU de
ts-order-service monte avec la table des commandes (relecture B.7 ; ce n'est pas un
reste de la panne d'hôte, selon la relecture ; à montrer sur ces fenêtres). Elles se
groupent juste après une injection de hote-01 : au test 13 sur 16 après la dernière, sur
la validation 11 sur 14 après la deuxième, en milieu de campagne. Il connaît chaque nœud
par son nom, ce que le GNN ne fait pas.

## 2026-09-26 — Phase B.5 : témoin 3, la règle qui suit les flèches

`graphe_en/temoin_fleches.py` (commits 98ec3f9, 483e814, ea31952), résultat dans
`campagnes/temoin_fleches.txt` et `-validation.txt`. Bibliothèque standard seulement.

La définition du 24 sept. : la file → ses répliques → leur machine, puis ce qu'elles
appellent → le dernier composant anormal. Écrite comme par un ingénieur qui connaît la
plateforme, le graphe figé et les quatre causes (sa structure reprend le tableau « quelle
panne fait bouger quoi » du LEXIQUE) ; limites d'alarme calées sur le normal seul.
**Deux versions, notées côte à côte** :
- **littérale** : la cible appelée est accusée si ses propres nombres sont anormaux ;
- **cause commune** : la cible est accusée si la plupart des AUTRES services qui
  l'appellent la voient aussi plus lente. Principe général (« lent pour tout le monde,
  ou pour moi seulement ? »), rien de propre à une base ; mais choisi par celui qui
  prépare la base lente, entre deux règles que la validation ne distingue pas (la cause
  commune ne se déclenche sur aucune panne connue ; au test, la littérale sans exemples
  accuse la base dans 25 fenêtres de lenteur) : d'où les deux versions.

**Versions vues sur le test, dites.** La première version a été notée sur le test
(détection 107/153, cause 52/153, lenteur top-1 0/38), puis changée : deux limites
d'alarme au lieu d'une ; charge par élimination ; et surtout le plancher fautif du
témoin 2, qui la rendait aveugle à la lenteur. Les chiffres de la règle sur les causes
connues sont donc « après une révision informée par le test ». La base lente ne l'est
pas, si la règle est figée avant C. Après deux relectures, vérifié sur la validation
seule : la saturation d'une machine = sa pression, pas son occupation (cpu_busy suit la
dérive de ts-order-service : fausses alertes 21 → 2 sur 102) ; réplique gelée = plus de
temps de traitement ; autres appelants comptés par service ; désignés à égalité.

**Outil nouveau : `juge.validation()`**, la coupure répétée une injection plus tôt, le
vrai test mis de côté (option `--validation` des scripts). **Depuis, tout choix de réglage
(témoins, puis GNN) se fait sur la validation, jamais sur le test.** Les pannes de la
base lente y sont toujours mises de côté (relecture B.7).

**Résultat (test)** : cause commune, sans exemples : détection 153/153, fausses alertes
10/120, cause 150/153, fautif top-1 115/115 ; avec exemples : cause 153/153, top-1
115/115. Littérale, sans exemples : cause 125/153, top-1 90/115, lenteur 13/38 (elle
accuse la base dans des fenêtres de lenteur : son épreuve compare au seuil de la file le
plus grand |z| des douze nombres de la base, que le bruit dépasse souvent) ; avec
exemples : 153/153, 115/115. Sur la validation, les deux versions font pareil : fausses
alertes 2/102 et top-1 114/115 pour les quatre, cause 150/153 sans exemples, 152/153 avec.

**Ce qu'elle sait de plus que le GNN** (à dire au rapport) : le normal de chaque nœud par
son nom, celui de chaque flèche par (relation, service source, service cible), les
consommateurs attendus de chaque file, les signatures des quatre causes écrites à la
main. C'est la référence experte sur les pannes connues ; ses presque 100 % y sont un
plafond par construction.

## 2026-09-26 — Phase B.6 : les témoins côte à côte

`graphe_en/temoins.py`, résultat dans `campagnes/temoins.txt` (test) et
`temoins-validation.txt`. Rien n'y est réglé : chaque témoin est appris par son fichier.

**Tableau de bord (test ; médiane sur 5 graines pour ce qui tire au hasard)**

| témoin | détection | fausses alertes /120 | cause | fautif top-1 /115 | nouveau /19 |
|---|---|---|---|---|---|
| tableau équitable | 153 | 9 [8–10] | 150 | 115 | 19 |
| score par nœud, sans exemples | 42 | 5 | 0 (par construction) | 100 | 17 |
| score par nœud, avec exemples | 153 | 28 [19–30] | 130 | 113 | 18 |
| règle littérale, sans / avec | 153 | 10 | 125 / 153 | 90 / 115 | 19 |
| règle cause commune, sans / avec | 153 | 10 | 150 / 153 | 115 | 19 |
| a priori (ne lit rien) | 0 | 0 | 0 | 57 | 0 |

**Fausses alertes au fil du temps.** Au test, aucune sur saine-08 ni saine-09 (fin de
campagne), aucune sur hote-02 (sur la validation : toujours aucune sur saine-08, mais le
score par nœud en fait 2 sur 26 sur saine-09 et 1 à 3 sur hote-02). Elles tombent après la dernière injection de charge-03 (4 à 6 sur 8
pour tous) et de hote-01 (le score par nœud avec exemples : 13 sur 16 ; les autres : 0 à
3). La relecture B.7 les attribue à la dérive de ts-order-service ; elles suivent de près
une injection : à montrer fenêtre par fenêtre avant de l'écrire au rapport.

**Répétition « panne jamais vue »** (une cause connue retirée de l'apprentissage ; toutes
ses injections au test) — le fautif top-1 :

| cause retirée | tableau | score par nœud (sans / avec) | règle (4 variantes) |
|---|---|---|---|
| blocage | 0/114 | 101/114 | 114/114 |
| hote | 0/117 | 117/117 | 117/117 |
| lenteur | 0/114 | 89/114 | 84 à 114/114 |

- Le tableau sait qu'une panne est nouvelle (« inconnue » 114/114 pour blocage et
  lenteur), jamais **où** elle est. Il ne voit presque pas un hôte jamais vu (3/117).
- Le score par nœud désigne un fautif qu'il n'a jamais vu fauter : c'est l'écart au normal
  nœud par nœud, l'idée de l'étape 1 du GNN. Mais sur la validation, il n'y arrive que
  pour l'hôte (78/78 ; blocage 1/76, lenteur 0/76 : il désigne la file, victime).
- La règle porte les noms des quatre causes et chaque branche a été écrite pour sa cause :
  sa colonne « inconnue » est sans objet, ses lignes ne se comparent pas au GNN. Seule la
  base lente l'éprouvera.
- La relecture B.7 nuance aussi B.3 : sur la validation, le tableau dit « inconnue » pour
  un blocage jamais vu dans 15/76 fenêtres seulement (il le prend pour une charge).

## 2026-09-26 — Phase B.7 : relecture finale des trois témoins, et gel

Deux relectures finales indépendantes (les trois témoins ensemble ; l'équité au niveau
de la thèse). Aucune fuite, aucun défaut de calcul dans le tableau. Corrigé (commit
ea31952) : les pannes de la base lente ne peuvent pas entrer dans la validation ; les
totaux par injection et le tableau de bord montrent une cause jamais vue à part ; les
résultats des deux séries ne sont jamais écrasés par une lecture qui ajoute C (fichiers
`<témoin>-<campagne>.txt`) ; chaque sortie dit les campagnes lues ; le tableau affiche son
budget de fausses alertes ; les versions vues sur le test sont dites dans chaque en-tête et
dans `campagnes/versions-vues-sur-test/LISEZMOI.md` (regards sur le test, version finale
comprise : tableau 3, score par nœud 4, règle 2). Chaque changement visait à renforcer le
témoin ; au test, c'est vrai pour le tableau (cause 144 → 150/153, top-1 94 → 115/115), la
règle (cause 52 → 150/153) et le score par nœud sans exemples (lenteur 0 → 25/38), mais le
score par nœud avec exemples y perd un peu (cause 136 → 130/153, top-1 114 → 113/115), et le
tableau fait 9/120 fausses alertes au lieu de 0 depuis son rejet des deux côtés.

**Budgets de fausses alertes** (fenêtres normales mises de côté, campagne par campagne) :
tableau et score par nœud sans exemples 13/249 = 5,2 % chacun (le même centile sur les
mêmes fenêtres ; les plus serrés) ; score par nœud avec exemples 25/249 = 10 % (deux
alarmes) ; règle 21/249 = 8,4 % (file et machines). Les fausses
alertes se comparent donc à budget égal, et par campagne (quelques fenêtres = du bruit).

**Ce que les témoins savent de plus que le GNN** : les noms (normal par nœud, cases du
tableau), le normal de chaque flèche par paire de services et les consommateurs attendus
(règle), les signatures des causes (règle), la cause commune écrite en sachant que C est
une base lente. Une victoire du GNN est donc prudente ; une défaite peut venir en partie
de là.

La table de décision, le calage de l'étape 1 du GNN et les conditions de C ont été
proposés ici le 26 sept., puis fixés le 27 : voir la section du 27 sept. (le texte du 26
reste dans l'historique git, commit 0c7daf2).

## 2026-09-27 — Avant C : les règles fixées, et ce que le cluster montre

Proposées le 26 sept., fixées le 27 : l'utilisateur a délégué le choix (« de la meilleure
façon que ferait un chercheur ») et tranché quatre points. Changements par rapport au 26 :
le scellé ; une injection ne compte que si la file déborde ; les minutes normales de C et D
hors de tout apprentissage ; « plus tôt » et « file pas encore pleine » réunis en un axe ;
D renforcée au lieu d'abandonnée ; aucun nouveau témoin.

**Décisions de l'utilisateur (27 sept.)**
- Tout scénario reste une faute de coordination : la file doit déborder. Une panne où la
  file ne bouge pas est hors sujet.
- Les minutes normales de C et D ne servent à l'apprentissage de personne : témoins et GNN
  apprennent sur les deux séries seules.
- Pas de comparaison à un autre GNN publié (DOMINANT, promis par le rapport) : la question
  « un GNN plus simple suffirait-il ? » est traitée par une variante de notre GNN dans le
  retrait des flèches (plus bas). La phrase du rapport sera retirée quand on le modifiera.
- Le simulateur tourne à 1 voyageur entre deux campagnes (fait le 27 sept. à 17:24 UTC).
- Seuls les résultats finaux iront sur un git public.

**Pourquoi écrire avant.** Choisir après avoir vu C ne change pas le GNN, seulement ce qu'on
en dit ; ce qui abîmerait sa qualité réelle, c'est de le régler en regardant C (il serait bon
sur C et on ne saurait plus ce qu'il vaut ailleurs). D'où les deux règles : ces critères, et
le scellé.

### Le scellé
C, puis D, sont enregistrées ; on ne lit alors que ces vérifications : la panne posée et
confirmée, le leader, le placement et les redémarrages, les veilles Locust, le tas, gel.py
CONFORME, le fautif présent dans chaque fenêtre (`fautifs.py base-01`, qui écrit
`fautifs-base-01.txt` et ne touche plus la sortie des séries). Aucun témoin ni le GNN ne lit
C ou D avant l'étiquette `gnn-fige` ; ensuite chacun passe une seule fois. `decision_c.py
--ouvrir` refuse sans cette étiquette, ou si le code des témoins, du juge et du GNN n'est plus
celui de leurs étiquettes. La table de décision de D est commitée avant l'enregistrement de
D, et en tout cas avant l'ouverture du scellé de C.

### Ce qui décidera sur C
**Mise en place.** Témoins à l'étiquette `temoins-figes`, code inchangé. Ils apprennent sur
les fenêtres d'apprentissage des deux séries seules (les mêmes que dans les sorties figées),
puis répondent sur toutes les minutes de C. Seul `decision_c.py` lit C, à part : C et D ne
passent jamais par `juge.lire` avec les deux séries, ni par `temoins.py`, ni par
`--validation` (le juge, lui, ne l'empêcherait pas : il mettrait leurs minutes normales en
apprentissage). La garde G est calculée tout de suite sur les deux séries et commitée.

**Une injection compte** si elle est confirmée, si la file est vide avant (tas ≤ 10 la minute
d'avant), si la file déborde (tas > 10 dans STRICTEMENT plus de la moitié de ses minutes de
panne ; égalité : ne déborde pas ; le même sens partout, essai compris) et s'il n'y a pas
d'effondrement (plus bas). Une injection qui ne compte pas est montrée à part, avec sa raison.
Moins de 2 injections confirmées : C est refaite à l'identique. Confirmées mais moins de 2 qui
comptent : C ne décide rien, on le dit et on en parle avec l'utilisateur.

**Mesure principale, par injection** : F = tsdb-mysql-0 est premier dans plus de la moitié
des fenêtres de panne de l'injection, sans tenir compte de l'alarme. A = la même avec
l'alarme, donnée à côté.

**TROUVE** (pour une méthode et un réglage) : F sur une majorité stricte des injections qui
comptent, ET garde de spécificité G : sur aucune des 8 injections de test des causes connues
tsdb-mysql-0 n'est premier dans plus de la moitié des fenêtres (une méthode qui accuse la base
partout ne « trouve » rien). Méthodes au hasard (graines 0 à 4) : TROUVE si, sur une majorité
stricte des graines, F et G tiennent avec la même graine ; les nombres d'injections se
comparent par leur médiane, donnée avec le minimum et le maximum.

**Décisions, dans cet ordre**
1. Le tableau ou le score par nœud (l'un ou l'autre réglage) TROUVE : sans la structure des
   flèches, les nombres suffisent sur C ; aucune conclusion sur le GNN n'est tirée de C (D et
   l'axe (a) restent).
2. Sinon, une ou plusieurs versions de la règle TROUVENT : H1 soutenue. Le GNN complet figé
   est comparé à CHACUNE (G comprise). Il gagne sur C s'il TROUVE avec au moins autant
   d'injections que chacune ET gagne nettement sur au moins un axe sans perdre sur aucun,
   contre chacune. Perdre est l'image de gagner, avec la même marge. Le GNN sonne au budget de
   fausses alertes de la méthode comparée (sa part de fausses alertes sur les minutes normales
   mises de côté : 21/249 pour la règle). Gagner demande TOUTES les graines ; perdre, une
   majorité stricte des graines. Calculé par `decision_c.comparer` :
   - (a) fausses alertes sur les 120 minutes normales NON VUES du test des deux séries
     (saine-09 à part : la mise à l'échelle y a été calée) : au moins 3 et 25 % de moins ;
   - (b) plus tôt : la première minute de panne où la méthode sonne ET met tsdb-mysql-0
     premier arrive au moins une minute avant, sur une majorité stricte des injections qui
     comptent (« jamais » est plus tard que toute minute ; jamais contre jamais : égalité) ;
   - (c) plus d'injections trouvées (F, médiane des graines) ;
   - (d) les jumeaux (phase D), table commitée avant D.
   « Inconnue » n'est pas un axe contre la règle (elle le dit par construction).
3. Personne ne trouve : le GNN gagne sur C s'il TROUVE.

Seul le GNN complet figé entre dans la décision ; les variantes du retrait des flèches sont
données à part. Si la variante « sans aucune arête » TROUVE, on conclut comme en 1.

**Prédictions écrites avant C.** Ce sont des prédictions, pas des résultats : chacune sera
vraie ou fausse. Base ralentie de 75 ms par échange, comme la lenteur.
- Nombres de tsdb-mysql-0 : cpu stable ou en baisse, mémoire stable, débits réseau stables ou
  en baisse, aucun paquet jeté ; aucun temps de traitement ni de requête (pas de span côté
  base, pas d'exportateur MySQL : c'est l'instrumentation qui la rend muette, à dire).
- Flèches queries de ses appelants : latence d'environ +75 ms. Répliques : 140 + 75 = 215 ms
  par échange, comme lenteur-02, donc un temps de traitement proche de lenteur-02.
- Dépôt : chaque voyageur de Locust enchaîne ses parcours au rythme d'un toutes les 5 s
  (constant_pacing, par voyageur et pour tous ses parcours). Si la réservation ou la recherche
  (qui touchent la base plusieurs fois) dépassent 5 s, le repas suivant part plus tard : le
  dépôt baisse et la file peut moins déborder (précédent : hote-02, 3e injection).
- La file : à 75 ms elle déborde probablement dès la première minute de panne (lenteur-02, même
  capacité : tas de 58 à sa première minute). L'axe (b) ne départagera donc probablement pas :
  si une version de la règle TROUVE, un verdict pour le GNN sur C ne peut venir que de (a), de
  (c) ou de D. Écrit ici pour ne pas le découvrir après.
- Règle, cause commune, sans exemples : trouve (inconnue, tsdb-mysql-0), si la file déborde et
  que la flèche des répliques vers la base dépasse s.
- Règle, avec exemples (cause commune ET littérale, même limite s = 5) : répond « lenteur, les
  répliques » (la flèche des répliques reste sous le seuil ; au-delà d'environ +140 ms elle
  trouverait aussi).
- Règle littérale sans exemples : écartée d'avance par G (essai à une graine : elle accuse la
  base dans lenteur-01 ; à confirmer avec 5 graines sur vms0).
- Tableau : ne sait pas désigner le fautif d'une cause jamais vue (0 % dans la répétition),
  alors qu'il trouve un fautif nouveau d'une cause connue (19/19) ; nommera probablement la
  cause « lenteur ».
- Score par nœud : la base ne bouge presque pas elle-même ; il désignera une victime.
- Retrait des flèches (GNN) : sans aucune arête, sans queries, sans canal d'arête, et un seul
  type de lien sans canal : ne trouvent pas (la base ne se voit que par les nombres portés par
  ses flèches queries) ; sans calls, publishes, consumes ou executes_on, une à la fois : même
  réponse que le GNN complet. Toutes figées avec le GNN.

### Le calage du GNN, écrit avant
1. Fenêtres d'apprentissage des deux séries seules ; l'étape 1 n'apprend que sur les normales.
2. Chaque campagne mise de côté à son tour : l'étape 1 réapprise sans elle (mêmes réglages,
   même graine), score de ses fenêtres normales ; tous mis ensemble.
3. Score d'une fenêtre = le plus haut score de nœud, le même qui sert au classement ; l'erreur
   d'un nœud divisée par l'échelle robuste de sa sorte dans le pli. Deux choix restent à fixer
   avant le gel du GNN, par un principe général écrit : à quel bout va l'erreur d'une flèche
   (la cible, la source, les deux) et comment se réunissent les erreurs de plusieurs flèches
   sur un nœud (somme, moyenne, maximum, part des voisins) ; et comment l'erreur des pods
   remonte à leur machine. Aucune panne connue n'a un fautif muet : régler ces choix sur la
   seule validation pousserait vers « la source » (le fautif de la lenteur est la source de
   ses flèches lentes), qui donnerait dans C l'erreur aux appelants, des victimes. Ils sont
   donc aussi éprouvés, avant le gel, sur des pannes FABRIQUÉES à la main dans les minutes des
   deux séries (un retard ajouté à toutes les flèches entrant dans un nœud, ou sortant d'un
   nœud, ou aux pods d'une machine), jamais sur C ni D ; leur effet sur la lenteur (garde G)
   est écrit.
4. L'alarme : seuil au 95e centile des scores des minutes normales mises de côté ; contre
   chaque méthode, le GNN sonne à son budget (part de fausses alertes de cette méthode sur les
   mêmes minutes). Plusieurs signaux d'alarme : leur union, calée de même.
5. Modèle final sur toutes les normales d'apprentissage ; graines 0 à 4, chacune avec son
   calage.
6. Rejet de l'étape 2 : chaque injection mise de côté, 95e centile des distances des fenêtres
   bien classées (comme le tableau et le score par nœud).
7. Jamais les fenêtres de test, jamais C ni D avant le gel du GNN ; C et D ne passent jamais par
   `juge.lire` avec les séries ni par `--validation` (voir la mise en place).
8. Tout choix du GNN (architecture, réglages) se fait sur la validation (`juge.validation`),
   sur la répétition « panne jamais vue » DANS la validation (`temoins.py --validation`, jamais
   celle du test), ou sur les pannes fabriquées du point 3 ; jamais sur le test, C ou D. Chaque
   regard sur le test est compté, comme pour les témoins.
9. Le GNN et ses variantes sont figés (étiquette `gnn-fige`) avant d'ouvrir C et D.

### Les conditions de C (jamais réglées sur un témoin)
**Vérifié sur le cluster le 27 sept.** (lecture seule, vms0 puis master) :
- tsdb-mysql-0 est le leader (role=leader ; tsdb-mysql-leader pointe sur son adresse), sur
  workers4 ; ses deux suiveuses sur workers5 et workers3 ; son chaos-daemon tourne, avec `tc`
  et `nsenter`.
- Aucun retard n'est posé côté base (podnetworkchaos de tsdb-mysql-0 vide). Le retard
  permanent de 140 ms est sur la SORTIE des trois répliques, vers les adresses de la base
  (pods et services) : un retard sur la sortie de tsdb-mysql-0 s'y ajoute sans le doubler.
- La base voit ses clients par leurs adresses de pod (27 adresses dans processlist, toutes des
  pods de train-ticket, dont les deux suiveuses) : une cible par pods les atteint.
- Réplication semi-synchrone active (attente d'une suiveuse, AFTER_SYNC) : retarder ce que la
  base envoie à ses suiveuses ralentirait chaque validation et les battements de xenon. Les
  suiveuses sont donc HORS de la cible.
- Horloges de vms0 et du master synchronisées.
- ts-order-service est bloqué (0/1 prêt depuis 2 jours : sa table a trop grossi) ; la purge
  avec redémarrage d'avant C le remet en route.

**Mécanisme exact.** Un NetworkChaos `panne-base` NEUF (le gabarit du réglage permanent,
yaml_retard, ciblerait la base elle-même : la mauvaise panne) : sélection = le pod
tsdb-mysql-0 par son nom (pas role=leader, pour ne pas suivre un nouveau leader) ; direction
« to » ; cible = les pods de train-ticket en marche sauf app=tsdb-mysql ; retard 75 ms, gigue
0, corrélation 0, sans perte ; durée 20 min ; refus si tsdb-mysql-0 n'est pas le leader. Après
la pose, `panne.sh` exige que chaque client en marche soit dans la liste des adresses
retardées, aucune suiveuse, et le bon retard ; sinon l'objet est retiré et l'injection notée
NON_CONFIRMEE (de même si Chaos Mesh ne confirme pas en 60 s). Le retrait ne touche jamais le
réglage permanent des répliques ; `verifier base` exige ce réglage à 140 ms et posé sur chaque
réplique.

**Relevés.** Pendant chaque injection, une veille toutes les 5 minutes (campagne.sh, 27
sept.) : bilan Locust (les 10 dernières secondes ; EN_DEFAUT = un parcours au-delà de 5 %
d'échecs ou qui ne tourne pas), tas, leader. Aux témoins (avant, pendant, après) : en plus, le
nombre de lignes de `orders` (un `SELECT COUNT(*)` sur la base, trois fois par injection :
écart d'instrumentation minime par rapport aux séries, dit ici), le cpu de ts-order-service,
le réglage posé sur chaque réplique, le retard et les adresses de panne-base, et les paquets
jetés à la sortie de la base (`tc -s qdisc` dans son espace réseau, par le démon Chaos Mesh ;
accepté : 0). Le placement note les redémarrages.

**Effondrement** = deux veilles de suite EN_DEFAUT pendant l'injection, OU le leader perdu à
une veille ou un témoin, OU un redémarrage de pod de train-ticket pendant l'injection (colonne
restarts du graphe). Une injection effondrée est notée, montrée à part, et ne compte pas.

**Intensité et repli**, lus seulement sur les relevés ci-dessus et la file, jamais sur un
témoin ni le GNN :
- essai à 75 ms, une injection de 20 min comme celles de C : `./campagne.sh essai-base
  --profil "25:30" --panne base --a 5 --duree 20 --intensite 75` (jamais noté ni pris dans le
  normal) ; y lire aussi les temps des parcours Locust (chercher, réserver, repas) et le dépôt ;
- l'essai tient et la file déborde : 75 ms est retenu ;
- il s'effondre : un seul autre essai, à 40 ms ;
- il tient, la file ne déborde pas, ET le dépôt reste proche de celui d'avant l'injection et
  au-dessus du retrait : un seul autre essai, à 150 ms ;
- tout autre cas, et tout second essai qui ne donne pas « tient et déborde » : arrêt et
  décision avec l'utilisateur ;
- l'intensité retenue sert aux 3 injections.

**Déroulé.** Comme la seconde série : `donnees.sh purger --redemarrer` (la seconde série l'a
fait une fois, le 25 sept., avant son premier essai), puis au moins 30 min à 25 voyageurs, puis
`./campagne.sh base-01 --profil "25:135" --panne base --a 5,50,95 --duree 20 --intensite
<retenue>` (sa propre purge, sans redémarrage ; 135 min, 3 injections de 20 min, mêmes écarts,
même réglage du consommateur à 140 ms). Noter l'heure, le cpu de ts-order-service et la taille
de la table des commandes à chaque injection (la dérive).

**Placement.** Codé le 27 sept. (campagne.sh) : pod → machine, phase, redémarrages, au départ
(juste avant la collecte) et à la fin ; accepté tel quel, jamais tiré au sort. Le 27 sept. : la
réplique r5pwb partage workers0 avec ts-order-service et ts-food-service (le producteur) ;
aucune réplique sur workers4 (la base). À relire après la purge, qui replace commandes, sièges
et recherche, et à dire avant de noter.

**Leader** vérifié avant, au départ réel (après la purge : départ refusé s'il a changé), à
chaque veille et témoin, et après. **Instrumentation** sinon inchangée : pas d'exportateur
MySQL, gel.py CONFORME, cause nommée « base » dans panne.sh et campagne.yaml.

**Relecture du 27 sept.** (deux agents sur ce texte, trois sur le code) : termes rendus
précis (meilleure règle, perte, graines, « jamais », alarme du GNN, « déborde »), la garde du
scellé sur le code, la prédiction du dépôt corrigée, le repli qui lit aussi le dépôt, l'essai
sur 20 min avec des veilles pendant la panne, les redémarrages relevés, la purge dans l'ordre de
la seconde série, et le point 3 du calage (le risque d'un réglage poussé vers « la source »).

## 2026-09-27 — Phase C, étapes 3 et 4 sur 7

Les étapes de C : C.1 règles fixées et relues ; C.2 code de la panne et du pilote ; C.3 garde
G ; C.4 préparer le cluster ; C.5 essai court ; C.6 campagne base-01 ; C.7 vérifications,
graphe figé, scellé. C.1 et C.2 : commit 591bd59 (relectures appliquées), poussé sur vms0 et
le master ; à blanc sur le master : leader, `verifier base` (réglage à 140 ms sur les trois
répliques), `etat` propre, relevé lisible.

**C.3** (vms0, 5 graines, `campagnes/decision-garde.txt`, commit 8104a8c) : aucune méthode ne met
tsdb-mysql-0 premier dans une panne connue, sauf la règle littérale sans exemples
(lenteur-01, comme prédit) : elle est écartée d'avance. Même résultat qu'à une graine.

**C.4** : `donnees.sh purger --redemarrer` à 20:5x UTC (commandes, sièges, recherche
redémarrés ; ts-order-service, bloqué depuis deux jours à 11 769 commandes, revenu à 3
lignes) ; simulateur remis à 25 voyageurs à 20:52:42 UTC (il était à 1 depuis 17:24) ; 30 min
d'attente avant l'essai.

**C.5 (essai, jamais noté ni pris dans le normal)**. Premier départ à 21:08 UTC arrêté par le pilote à
la minute 2, AVANT toute injection : aucun parcours ne tournait. Cause : après la purge avec
redémarrage (20:5x), ts-preserve-service restait bloqué à « checkSecurity » et ts-security-service
ne répondait plus (probablement des connexions gardées vers l'ancien pod de ts-order-service) ;
chaque voyageur de Locust se coinçait sur « 30 réserver un billet ». Remède, autorisé une fois par
l'utilisateur : redémarrage de ts-security-service et ts-preserve-service à 21:20 UTC ; les
parcours sont repartis. Leçon : après un `--redemarrer`, vérifier « réserver » avant de lancer.
Compte rendu du départ arrêté gardé hors du dépôt (vms0, `~/journaux-hors-campagne/`).

Second départ à 21:23 UTC, `essai-base --profil 25:30 --panne base --a 5 --duree 20 --intensite
75`, injection de 21:28:03 à 21:48:03 UTC (`campagnes/essai-base/`, tas relevé chaque minute dans
`file-chaque-minute.txt`). Lu seulement ce que la règle écrite d'avance demande :
- panne posée comme prévu : 75 ms vers 55 adresses, les 55 pods clients, aucune suiveuse ; aucun
  paquet jeté à la sortie de la base ; réglage des répliques resté à 140 ms sur les trois ;
- le site tient : trois veilles pendant l'injection, toutes « parcours ok » ; leader inchangé ;
  aucun redémarrage ; aucun échec Locust sur l'essai (p50 sur les 30 min : chercher 2,2 s,
  réserver 5,3 s, repas 0,54 s) ;
- la file déborde : tas > 10 dans 19 des 20 minutes de panne (10 à la première minute, 30 à la
  deuxième, 271 à la fin), vidée après le retrait.
Décision selon la règle : **75 ms retenu**. À noter sans en tirer de conclusion : la file a monté
moins vite que pour lenteur-02 (58 à sa première minute) ; « réserver » dépasse 5 s, ce qui freine
le dépôt comme le journal le prédisait. En attente du signal de l'utilisateur pour C.6.

## 2026-09-28 — D.1/7 : ce qui décidera sur D, écrit avant

Écrit pendant la campagne base-01 (C.6), sans rien lire de C, relu par deux agents, commité avant
toute lecture du placement de D, avant l'enregistrement de D et avant l'ouverture du scellé de C.
Les étapes de D : D.1 écrit avant ; D.2 lectures et une mesure sur le cluster (le mécanisme possible,
la carte réseau, le temps de validation avec une suiveuse retardée, le placement) ; D.3 code de la
panne « reseau » et du leurre ; D.4 relecture et déploiement ; D.5 essais ; D.6 campagne jumeaux-01 ;
D.7 vérifications, graphe figé, scellé.

### La panne et son sens
Le réseau de la machine X qui porte UNE réplique du consommateur est ralenti : retard pur sur tout
ce qui SORT de sa carte réseau physique, sans perte ni gigue. La réplique de X ralentit, la file
déborde : une faute de coordination grise (rien ne tombe, aucune erreur). En même temps, une machine
leurre Y reçoit le voisin bruyant de la cause hote (même mécanisme, demande de 2 cœurs, stress sur
tous les cœurs) : elle « crie » par sa pression sans rien causer. Le fautif est X (fautifs.py,
`reseau`), jamais Y.

**La signature attendue, d'après la façon dont le graphe mesure** (edges.py : `queries` est mesurée
chez l'appelant, `calls` chez l'appelé, par la durée du span serveur ; `publishes` et `consumes` ne
portent qu'un débit) :
- plus lents : les flèches queries des pods de X (+d par échange) ; le temps de traitement des pods
  de X qui échangent hors de X ; le temps de traitement de leurs appelants hors de X, cumulé vers
  l'amont ; les flèches calls qui ENTRENT dans X (elles suivent le temps de traitement des pods de X) ;
- inchangées : les flèches calls qui SORTENT de X (mesurées chez l'appelé, réseau exclu), le trafic
  entre pods de X (il ne quitte pas la carte) ;
- la réplique de X : moins de débit consumes, temps de traitement plus long.

**Les jumeaux.** Vue de la réplique seule, cette panne ressemble à une lenteur qui ne toucherait
qu'elle. Ce qui la distingue est la structure : d'autres pods de X ralentissent aussi, pas ceux des
autres machines (hors de l'amont). D'où la condition d'identifiabilité : X porte, en plus de la
réplique, au moins un autre service ACTIF ; on en exige deux, par marge (ce nombre est un choix, pas
une nécessité). Un service est actif s'il est, dans les fenêtres normales d'apprentissage des deux
séries, SOURCE de flèches queries ou calls vers un service placé hors de X au départ de D (identité
d'un pod = son service, comme dans temoin_noeud.py).

### Le choix de X et de Y (écrit avant, jamais tiré au sort, jamais choisi en regardant un témoin)
Lu sur le placement au départ de D, après la purge avec redémarrage, l'attente et la vérification
du parcours « réserver ».
- X : une machine de travail qui porte une réplique ET au moins deux autres services actifs, et qui
  ne porte ni le leader de la base (retarder sa sortie ralentirait toute la base : ce serait C), ni
  rabbitmq, ni le producteur ts-food-service, ni ts-order-service (un voisin ou un retard sur sa
  machine a fait remonter la panne en amont : hote-02, 3e injection), ni la passerelle ; jamais
  workers6 (la mesure, Locust, le contrôleur Chaos Mesh) ni le master. Une suiveuse de la base
  n'exclut pas X SI la mesure de D.2 montre qu'une suiveuse retardée ne change pas le temps de
  validation (la réplication n'attend qu'une suiveuse) ; sinon elle l'exclut.
- Y : une autre machine de travail, jamais workers6 ni le master, qui ne porte ni un pod de la base
  (leader ou suiveuse), ni rabbitmq, ni le producteur, ni ts-order-service, ni la passerelle, avec au
  moins 2 100 m de CPU allouable libre (la demande de 2 cœurs du voisin de la seconde série).
- Les répliques ne bougent pas à la purge (elle ne redémarre que commandes, sièges et recherche) :
  elles sont sur workers0, workers2 et workers5. Y ne portera donc pas de réplique. Le leurre est ainsi
  un motif NOUVEAU (une machine bruyante sans réplique), pas la signature de la cause hote ; et quand
  la file déborde, la règle ne regarde que les machines des répliques lentes : le leurre ne piège que
  les méthodes qui regardent toutes les machines (tableau, score par nœud, GNN).
- Ordre fixe : X trié par nom, Y trié par nom, couples (X, Y) avec X ≠ Y dans l'ordre lexicographique ;
  l'injection k prend le couple (k − 1) mod n ; les essais se font sur le couple de la première
  injection. Aucun couple : D ne part pas, on en parle avec l'utilisateur (aucun choix libre).
- campagne.sh refusera le départ si le placement relu au départ ne donne plus les mêmes couples que
  les cibles fournies (D.3).
- Au placement du 27 sept. (fin de essai-base) : X ne pourrait être que workers2 (workers0 porte le
  producteur, workers5 une suiveuse, sous réserve de D.2), Y que workers1. workers2 a été fautif de la
  cause hote à l'apprentissage (hote-02, 2e injection) : toutes les fenêtres de D y tombent dans
  « fautif déjà vu ailleurs ».

### Le mécanisme exigé (le moyen exact est fixé en D.2 et D.3)
Retard pur sur la sortie de la carte réseau physique de X ; sans perte (décidé une fois pour toutes :
une perte ferait bondir les retransmissions de X, le score par nœud le trouverait seul, ce serait une
autre expérience) ; la file du netem assez grande pour ne rien jeter, et vérifiée : paquets jetés sur
X = 0 à chaque témoin, retransmissions de X relevées ; durée portée par l'injection, levée garantie
sans pilote, retrait vérifié (plus aucune règle de retard sur la carte de X). Le leurre est posé
dans la même injection : une seule ligne de registre `cause=reseau`, cible `X@leurre:Y`, les deux
confirmés à moins de 60 s d'écart, sinon l'injection est NON_CONFIRMEE.

### Intensité : l'échelle, lue seulement sur les relevés, la file et le dépôt
Calcul (pas mesure) : la réplique de X passe de 0,706 s par message à 0,706 + (5 ou 6) × d ; les
deux autres gardent environ 1,42 message/s chacune ; pour un dépôt de 3,4 à 3,5 messages/s, le
seuil de débordement est entre 100 et 176 ms, 150 ms est sur le seuil, 200 ms déborde d'environ 8
messages par minute, 300 ms d'environ 16. Mais les services actifs de X (au 27 sept. : preserve et
station, sur « réserver » et « chercher ») ralentissent aussi les parcours et donc le dépôt.
- Les essais se font AVEC le leurre, comme la campagne (`--profil 25:30 --a 5 --duree 20`).
- Échelle : 75 → 150 → 200 → 300 ms. Un cran est retenu s'il tient et déborde avec marge : tas > 10
  dès la 5e minute de panne, et toujours en hausse au retrait.
- Monter d'un cran seulement si le cran tient, ne déborde pas avec marge, ET le dépôt reste proche de
  celui d'avant l'injection et au-dessus du retrait (la condition de C) ; sinon arrêt et décision
  avec l'utilisateur. Un cran qui s'effondre, ou 300 ms sans débordement : arrêt et décision avec
  l'utilisateur.
- À chaque essai : temps des parcours Locust, dépôt, paquets jetés et retransmissions de X.
- « Déborde » et « effondrement » comme pour C ; s'y ajoutent pour l'effondrement une machine
  NotReady, et une seule fenêtre de panne sans le nœud host X ou sans la réplique de X.
- Les essais de D sont sous le même scellé que D : jamais lus par un témoin ni par le GNN, jamais
  utilisés pour le banc de pannes fabriquées. La seule vérification : un script qui ne sort que le
  temps de traitement des trois répliques pendant l'essai ; s'il ne montre pas la réplique de X
  nettement plus lente que les deux autres, arrêt et décision avec l'utilisateur.

### Ce qui décidera sur D (même forme que C)
- Mise en place : témoins à `temoins-figes`, appris sur les deux séries seules ; les minutes
  normales de D n'entrent dans l'apprentissage de personne. `decision_c.py` est étendu à D, relu et
  commité AVANT l'étiquette `gnn-fige` ; C et D sont ouvertes dans la même lecture.
- Moins de 2 injections confirmées : D refaite à l'identique ; confirmées mais moins de 2 qui
  comptent : D ne décide rien.
- Une injection compte : confirmée (retard ET leurre), file vide avant, file qui déborde, pas
  d'effondrement.
- F_D : la machine X (nœud host) est première dans plus de la moitié des fenêtres de panne de
  l'injection, sans tenir compte de l'alarme ; A_D la même avec l'alarme.
- Garde G_D, calculée sur les deux séries pour CHAQUE X employé, dès que les couples sont connus et
  avant d'ouvrir quoi que ce soit : sur aucune des 8 injections de test des causes connues, X n'est
  premier dans plus de la moitié des fenêtres, sauf une injection hote dont X serait le fautif.
  TROUVE exige G_D pour tous les X employés.
- Plancher : « a priori » restreint aux machines (nœuds host, classés par leurs fenêtres fautives à
  l'apprentissage). S'il TROUVE, D ne décide rien.
- TROUVE, graines : comme pour C, avec X à la place de tsdb-mysql-0.
- **Ce que D peut dire, écrit avant** : quand la file déborde, la règle des flèches ne met jamais en
  tête une machine sans pression (temoin_fleches.py : une machine n'est désignée que par sa
  pression ; désignés à 1e9, chemin à 1e8) ; aucun témoin figé n'a de principe au niveau de la
  machine. La décision 2 (le GNN comparé à une règle qui TROUVE) est donc très probablement
  inatteignable sur D, et D se ramène en pratique à « le GNN désigne-t-il X ». Une victoire sur D veut
  dire « le GNN désigne une machine muette que des méthodes sans principe au niveau de la machine ne
  peuvent pas désigner », pas « le GNN bat la règle à armes égales ». Le rapport le dira ainsi.
- **L'axe (d) de C**, table fixée : le GNN TROUVE sur D en décision 3 → gagné ; décision 1, plancher,
  moins de 2 injections qui comptent, ou personne ne trouve (GNN compris) → égal ; une version de la
  règle TROUVE et pas le GNN → perdu. L'axe (a) n'est pas repris par D (mêmes minutes normales que
  C). Le rapport ne présentera pas une victoire sur C obtenue par l'axe (d) comme indépendante de D.

### Prédictions écrites avant D (ce sont des prédictions, pas des résultats)
- Nombres de X : pressions stables ; débits réseau un peu plus bas ; paquets jetés 0 ;
  retransmissions proches de 0 jusqu'à 200 ms, possibles à 300 ms (l'aller-retour dépasse le délai
  minimal de retransmission de Linux, 200 ms) : X presque muet sur ses propres nombres. Y :
  pressions très hautes.
- Règle des flèches : file pleine, une réplique ralentie ; selon la chute de son débit, « blocage,
  la réplique de X » (le débit consumes est testé avant le temps de traitement) ou, sa machine étant
  sans pression, « lenteur, la réplique de X » ; « inconnue, tsdb-mysql-0 » seulement si la majorité
  des appelants de la base sont sur X ET que la flèche de la réplique vers la base dépasse s. X n'est
  pas premier.
- Score par nœud sans exemples : la file, Y (la pression la plus haute) ou la réplique en premier.
  Avec exemples : une cause apprise ou « inconnue », avec la file ou la réplique en premier (les
  pannes hote avaient une file vide et workers1 n'a jamais été cible) ; X pas premier.
- Tableau : ne désigne pas le fautif d'une cause jamais vue ; cause incertaine.
- Le GNN : ne désignera X que si sa règle « l'erreur des pods remonte à leur machine » donne à une
  machine l'erreur commune de plusieurs de ses pods. Cette règle est fixée avant le gel du GNN et
  éprouvée sur le banc ci-dessous, jamais sur D ni ses essais.

### Le banc de pannes fabriquées, fixé maintenant (avant de connaître X)
Sur les fenêtres de la VALIDATION (juge.validation) des deux séries, jamais le test, jamais C ni D :
- chaque machine de travail qui porte une réplique (workers0, workers2, workers5), tour à tour, et
  chaque retard d ∈ {75, 150, 300} ms, avec la signature écrite plus haut ;
- cas M, la machine : signature appliquée à tous ses pods → réponse attendue : la machine ;
- cas R, le jumeau : la même signature sur la seule réplique → réponse attendue : la réplique ;
- cas M+Y : le cas M et, dans les mêmes fenêtres, les pressions d'une autre machine portées aux
  valeurs des pannes hote de l'apprentissage → réponse attendue : la machine aux pods ralentis devant
  la machine bruyante ;
- cas Y, la machine bruyante seule : réponse attendue celle de fautifs.py pour hote, la machine ;
- critère : la règle de remontée (le bout de la flèche, la façon de réunir les erreurs, la remontée
  pods → machine) qui met la réponse attendue première dans le plus de cas du banc, à condition de
  garder la garde G de C et la validation au moins aussi bonnes ; égalités : la plus simple ;
- la variante « sans aucune arête » du retrait des flèches garde la même remontée pods → machine
  (elle lit la machine de chaque pod dans le champ hosts de ses nœuds, sans flèche) ; si elle
  TROUVE X, c'est la remontée écrite à la main et pas le GNN qui trouve : on le dit.

### D.1, suite : l'option B, décidée par l'utilisateur (28 sept.)
« Cette règle est évidente, on ne peut pas l'enlever » : la règle reçoit, avant D, l'idée qui sépare
les jumeaux, comme la cause commune l'avait été pour C. Témoin 3 bis, `graphe_en/temoin_machine.py`
(hérite de temoin_fleches.py sans le modifier), figé sous l'étiquette `temoin-machine-fige` avant D.
Deux relectures par deux agents chacune.

**L'idée, telle que figée.** Quand la règle « cause commune » accuse des répliques (« blocage » ou
« lenteur »), elle regarde la machine h qui porte une majorité stricte des répliques accusées (une
panne de machine n'explique pas des répliques lentes sur plusieurs machines ; sinon rien ne change).
S'il existe au moins deux autres pods actifs sur h et qu'une majorité stricte d'entre eux sont lents,
et qu'il existe au moins deux pods actifs ailleurs hors de l'amont de h avec au plus la moitié d'entre
eux lents, elle accuse la machine (cause « inconnue »), les répliques passant sur le chemin.
- actif : un pod qui, dans la fenêtre lue, est source d'une flèche calls ou queries vers un pod d'une
  autre machine ;
- amont de h : les services qui appellent un service de h, directement ou de proche en proche, dans
  les fenêtres normales d'apprentissage (D.1 : ils ralentissent avec X, « hors de l'amont ») ;
- lent : le plus haut écart du pod (temps de traitement ou de requête, flèches queries sortantes,
  flèches calls entrantes) dépasse s_l, sa propre limite, calée comme s_f (95e centile sur les pods
  actifs des fenêtres normales d'apprentissage, chaque campagne mise de côté), toujours sans exemples ;
- alarme, s_f, s_m : ceux de la règle (même budget de fausses alertes). Avec exemples, s est choisie
  par la grille de la règle, notée sur les réponses AVEC l'idée.

**Une version vue sur le test, à dire.** Une première version (jamais commitée) comptait l'amont dans
« ailleurs », jouait avec des répliques accusées sur trois machines, reprenait s comme limite de
« lent », lisait « actif » sur le normal seul et gardait la grille sans l'idée. Son `--comparer`
lisait aussi des fenêtres du test : lenteur-01/0063 et 0101, lenteur-02/0109 et 0111, dans les
injections de lenteur du test, celles-là mêmes qui serviront à G_D pour les versions machine. Deux
relecteurs ont mesuré ses défauts en partie sur les fenêtres normales du test. Les corrections sont
choisies par principe (le texte de D.1 pour l'amont, une machine et non trois, s_l calée comme s_f) ;
leur effet sur D est inconnu. Sur les données permises (la validation, et l'apprentissage des deux
séries sans aucune fenêtre du test), seule la correction « majorité » change une réponse : une
fenêtre de lenteur de la validation, où le défaut se voit donc sans le test. s_l rend « lent » plus
strict sans exemples (5,0 % des pods actifs du normal mis de côté au-dessus de s_l, contre 7,9 %
au-dessus de s_f) et moins strict avec exemples (0,4 % au-dessus de s = 5) ; ces pourcentages sont
ceux de l'apprentissage complet des deux séries (sur la validation : 5,0 %, 6,8 % et 1,0 %). La majorité a un coût
pour D, mesuré sur un banc de la validation : l'idée se tait dans 5 à 7 fenêtres sur 128 du cas M
sans exemples (une autre réplique dépasse s par le bruit), 1 sur 128 avec. Compté dans
`campagnes/versions-vues-sur-test/LISEZMOI.md`. `--comparer` ne lit plus que la validation.

**Chiffres de la version figée** (poste) :
- validation : 1 fenêtre changée sur 554 pour les deux réglages, blocage-02/0057 (panne connue, la
  réplique de workers2 accusée → workers2) ; s_f = 3,79, s_l = 4,40 (1 962 pods actifs, 10 campagnes) ;
  s = 3,79 sans exemples, 5 avec, comme la règle ;
- apprentissage des deux séries, les limites qui serviront à D (vérifié par un relecteur, sans
  fenêtre du test) : s_f = 2,39, s_l = 3,44 (4 053 pods actifs) ; avec exemples, la grille avec l'idée
  choisit le même s que la règle, 5 (535 points contre 533 : l'idée ne coûte que blocage-02/0057) ;
- banc grossier de la validation (signature de D.1 posée en écarts, file pleine) : cas M, X premier
  dans 121 à 127 fenêtres sur 128 pour workers2 et workers5 dès un écart de +5 ou +6 ; cas R (la
  réplique seule), X premier à tort 0 fois sur 128, pour chaque X, chaque retard, les deux réglages,
  même avec le leurre ; à +3, presque rien (0 à 3 fenêtres sur 128 : la règle répond « charge »). Sans l'idée, X n'est jamais premier.

**Où elle sert.** Seulement à D (`decision_c.methodes(machine=True)`, une seule liste passée à la
garde et à la lecture). C garde la liste de méthodes écrite avant C : l'idée ne joue qu'après
« blocage » ou « lenteur », où des répliques sont déjà à 1e9, donc la base reste à 1e7 au plus et
l'alarme ne bouge pas ; avec exemples, s est la même (5). F, A, G, les minutes et les fausses alertes
de C n'en changeraient pas.

**Le contrôle avant l'ouverture, réparé.** La relecture a trouvé que `controle_du_code` (C.0) lançait
git depuis graphe_en/ avec des chemins « graphe_en/… » : tous les contrôles « a changé » étaient
aveugles. Réparé (git lancé depuis la racine) avec un auto-contrôle : git doit voir que
decision_c.py est né après `temoins-figes`, sinon rien ne s'ouvre. `--ouvrir` refuse aussi si
l'étiquette `temoin-machine-fige` manque, si le fichier n'y est pas, n'est pas suivi ou a changé, si
l'étiquette n'est pas un ancêtre de `gnn-fige` (le même commit est accepté : la règle ne peut plus
changer ensuite), ou s'il y a un .py non suivi dans graphe_en/. À faire en D.3 : refuser si le commit
de `temoin-machine-fige` n'est pas antérieur au premier instant de campagne.yaml de D ; son hachage
sera noté dans A_REPORTER.md dès l'étiquette posée.

**L'axe (c) de `comparer`, réparé avant toute ouverture.** Le code ne pouvait jamais rendre
« perdu » sur l'axe (c), contre « perdre est l'image de gagner ». Désormais, comme les autres axes :
gagné si TOUTES les graines trouvent plus d'injections que la règle, perdu si une majorité stricte
des graines en trouve moins (lecture plus stricte pour le GNN que « la médiane », donnée à côté).
Vaut pour C et pour D.

**Le choix de X (D.1), précisé** : un service compte comme actif pour la marge de X s'il l'est dans
plus de la moitié des fenêtres normales d'apprentissage des deux séries (dans les séries, chaque
service de workers0, workers2 et workers5 est actif dans 0 % ou 100 % des fenêtres normales).

**Prédiction pour les versions machine, écrite avant D** : X premier quand la règle accuse la
réplique de X seule (blocage ou lenteur), qu'une majorité stricte des autres pods actifs de X (au
moins deux) dépassent s_l, et au plus la moitié des pods actifs ailleurs hors de l'amont ; sinon,
la même réponse que la règle. Si D ressemble au banc, les deux versions machine TROUVERONT X ; le GNN
devra alors gagner par l'axe (b) ou (c). La phrase « X n'est pas premier » des prédictions de D.1 ne
vaut que pour la règle sans l'idée.

**Ce que D pourra dire désormais** (remplace « Ce que D peut dire, écrit avant ») : la décision 2
devient atteignable (la règle a le principe « machine ») ; un écart du GNN sur D ne pourra venir que
de ce qu'il fait mieux que cette règle (plus tôt, plus d'injections trouvées, les cas limites où
l'idée ne joue pas), pas de l'absence du principe.

**La décision 2 de C, précisée avant toute ouverture** (relecture du 28 sept.) : quand plusieurs
versions de la règle TROUVENT, « perdre est l'image de gagner » se lit ainsi : le GNN perd sur C si,
contre AU MOINS UNE version, c'est l'image (elle TROUVE avec au moins autant d'injections, gagne
nettement sur un axe et ne perd sur aucun) ; il gagne seulement contre chacune ; sinon égal. C'est la
lecture la plus dure pour le GNN : il doit battre le meilleur adversaire, et perd s'il est battu par
un seul.

**L'axe (d) de C, table complétée** (remplace la table de D.1). « Version de la règle » comprend
désormais les deux versions machine. On lit les lignes DANS CET ORDRE ; la première qui s'applique
donne l'axe :
0. moins de 2 injections qui comptent sur D, le plancher TROUVE, la décision 1 sur D (tableau ou
   score par nœud TROUVE), ou la variante « sans aucune arête » TROUVE X → égal ;
1. aucune version de la règle ne TROUVE et le GNN TROUVE (majorité stricte des graines, comme la
   décision 3 de C) → gagné ;
2. une ou plusieurs versions de la règle TROUVENT et le GNN aussi → le GNN est comparé à CHACUNE sur D
   comme en décision 2 de C, avec les axes (b) et (c) lus sur D (l'axe (a) n'est pas repris : mêmes
   minutes normales que C) ; gagné s'il TROUVE avec au moins autant d'injections que chacune ET gagne
   nettement sur au moins un de ces axes sans perdre sur aucun, contre chacune ; perdu si, contre AU
   MOINS UNE version, c'est l'image (elle TROUVE avec au moins autant d'injections que le GNN, gagne
   nettement sur un axe et ne perd sur aucun) ; sinon égal. Sur chaque axe, gagner demande toutes les
   graines, perdre une majorité stricte ;
3. une version de la règle TROUVE et pas le GNN → perdu ;
4. personne ne trouve → égal.
Le rapport ne présentera pas une victoire sur C obtenue par l'axe (d) comme indépendante de D.

## 2026-09-28 — D.2/7 : lectures et mesure sur le cluster

Accord de l'utilisateur pour cette nuit seulement (28 sept., vers 00:20 UTC ; il dort, veut D finie
au réveil) : la mesure ci-dessous, la purge avec redémarrage des 3 services habituels, les essais de
D.5, le lancement de jumeaux-01, et le redémarrage d'un service bloqué seulement s'il empêche
« réserver ». Chaque geste est noté ici. Toute règle écrite « décision avec l'utilisateur » arrête
tout jusqu'à son réveil.

**Lectures (00:15–00:25 UTC, rien modifié).**
- Toutes les machines de travail : carte `enp6s18`, file racine fq_codel (défaut du noyau), Calico
  en vxlan (le trafic entre machines sort par enp6s18), kube-proxy en IPVS.
- Chaos Mesh 2.8.4 : NetworkChaos a un champ `device` ; aucun filtre d'espace de noms.
- Débit de sortie de workers2 en fin de campagne : environ 170 paquets/s ; à 300 ms, environ 50
  paquets dans la file du netem, loin de sa limite par défaut (1 000) : rien ne devrait être jeté.
- Base : MySQL 5.7.34, semi-synchrone AFTER_SYNC, attente d'UNE suiveuse (wait_for_slave_count = 1),
  2 suiveuses branchées, attente moyenne par validation 0,54 ms depuis le départ ; délai d'abandon
  infini.
- Placement (après base-01) : répliques sur workers0, workers2, workers5 ; leader tsdb-mysql-0 sur
  workers4 ; suiveuses tsdb-mysql-1 sur workers5, tsdb-mysql-2 sur workers3 ; rabbitmq, passerelle,
  ts-order-service sur workers3 ; producteur ts-food-service sur workers0. workers2 porte aussi
  nacos-0, un coredns et dns-autoscaler (le cache DNS local de chaque machine les amortit).

**La mesure de la suiveuse, règle écrite avant de mesurer.** Trois relevés de 3 min des compteurs
Rpl_semi_sync_master_tx_wait_time et tx_waits du leader : avant, pendant un retard de 300 ms (le
plus haut cran de l'échelle) sur TOUT ce que sort tsdb-mysql-1 (NetworkChaos sur ce pod, 4 min), et
après. Attente moyenne par validation = Δtemps / Δvalidations. La suiveuse retardée « ne change pas
le temps de validation » si l'attente pendant reste sous 2 × celle d'avant + 1 ms, ET si le leader
reste tsdb-mysql-0. Alors workers5 n'est pas exclue par sa suiveuse ; sinon elle l'est. Le mécanisme
de D est aussi essayé, à blanc : un NetworkChaos de 1 ms, 60 s, sur la carte enp6s18 de workers1
(sans réplique) par le pod node-exporter de cette machine (réseau de l'hôte), relu dans l'espace
réseau de l'hôte, puis retiré (la file racine doit revenir à fq_codel).

## 2026-09-28 — C.6/7 et C.7/7 : base-01 enregistrée, puis scellée

**C.6** : `./campagne.sh base-01 --profil 25:135 --panne base --a 5,50,95 --duree 20 --intensite 75`,
22:00–00:15 UTC (tmux sur vms0). **C.7, seulement les vérifications permises par le scellé** :
- 3 injections confirmées sur 3, aucune non confirmée ; chacune « 75 ms vers 55 adresses, les 55 pods
  clients, aucune suiveuse » ;
- leader tsdb-mysql-0 au départ, avant la collecte et à la fin (même adresse) ; placement identique
  au départ et à la fin ; aucun redémarrage de pod ;
- veilles toutes « parcours ok » (pendant les pannes aussi) ;
- tas relevé chaque minute (`campagnes/base-01/file-chaque-minute.txt`) : au-dessus de 10 dans 19/20,
  19/19 et 18/19 minutes de panne ; la file revenue à 0–2 avant chaque injection ;
- graphe figé : run.py (mise à l'échelle apply), `runs/20260928-021822` sur vms0, 130 fenêtres ;
  gel.py CONFORME ; `fautifs.py base-01` : tsdb-mysql-0 vu dans 19 fenêtres sur 19 pour chaque
  injection, « TOUS LES FAUTIFS SONT ÉTABLIS » ;
- lecture.txt écrit par lecture.py sans être affiché (le juge en a besoin pour trouver le run).
**C est sous scellé** : aucun témoin, aucun decision_c `--ouvrir` avant `gnn-fige`.

## 2026-09-28 — D.2/7 (résultats) et D.3/7 : le moyen de la panne change, écrit avant tout essai

**À valider par l'utilisateur à son réveil** : deux écarts à D.1, pris cette nuit parce que D ne pouvait
pas partir autrement, écrits ici avant tout essai et toute donnée de D. S'il les refuse, D est refaite.

**La suiveuse (mesure de D.2, 00:20–00:30 UTC).** Attente moyenne par validation : avant 535 µs
(751 085 µs sur 1 404 validations), pendant le retard de 300 ms sur tsdb-mysql-1 596 µs (806 901 sur
1 353), après 534 µs (723 366 sur 1 354) ; seuil de la règle 2 × 535 + 1 000 = 2 070 µs. Leader
tsdb-mysql-0 tout du long (même adresse), 2 suiveuses branchées, semi-synchrone resté ON, aucune
validation sans attente. → une suiveuse retardée ne change pas le temps de validation : elle n'exclut
pas X (`couples_d.SUIVEUSE_EXCLUT = False`). Le NetworkChaos de la mesure a été retiré et vérifié.

**La carte réseau : impossible.** L'essai à blanc a échoué : Chaos Mesh 2.8.4 refuse de poser un
NetworkChaos sur un pod au réseau de l'hôte (le pod node-exporter de workers1). L'objet est resté
accroché ; nettoyé (finaliseurs retirés, l'objet PodNetworkChaos de ce pod supprimé), la carte de
workers1 est restée en fq_codel, rien n'a été retardé. Poser le retard directement sur la carte par
`tc`, depuis le démon Chaos Mesh dans l'espace réseau de l'hôte, a été refusé par la protection
automatique de Claude Code ; ce refus n'a pas été contourné.

**Le moyen retenu (écart 1).** Un NetworkChaos `panne-reseau` sur TOUS les pods en marche de l'espace
train-ticket placés sur X (sélecteur `namespaces: [train-ticket]`, `nodes: [X]`, `podPhaseSelectors:
[Running]`), `direction: to` sans cible, retard d ms, gigue 0, corrélation 0, aucune perte, durée
portée par l'objet. Ce que ça change par rapport à la carte :
- pareil : tout ce qu'un pod de X envoie hors de X est retardé une fois de d (ses requêtes et ses
  réponses aux appelants des autres machines) ; aucune perte ; la levée ne dépend pas du pilote ;
- différent : le trafic ENTRE deux pods de X est retardé aussi (d à l'aller, d au retour), alors que
  la carte l'épargnait. Dans la signature de D.1, « inchangé : le trafic entre pods de X » devient
  « plus lent chez l'appelant de X » (les flèches calls entre pods de X, mesurées chez l'appelé,
  restent inchangées). Le banc de pannes fabriquées de E prendra cette signature-là ;
- différent : les pods des autres espaces sur X (coredns, dns-autoscaler, node-exporter, Calico,
  kube-proxy) ne sont pas retardés. nacos-0 (espace train-ticket, sur workers2) l'est, comme avec la
  carte ;
- les paquets jetés et les retransmissions de X sont lus pod par pod (file du netem de chaque pod,
  compteurs TCP de l'espace réseau de chaque pod, sommés sur les pods de X), à chaque témoin complet.
  Une file par pod, avec bien moins de trafic que la machine entière : rien ne devrait être jeté.

Confirmation exigée : AllInjected sur les deux objets dans les mêmes 60 s ; chaque pod en marche de X
porte le retard de panne-reseau à d ms (lu dans les objets PodNetworkChaos), aucun pod d'une autre
machine ne le porte ; sinon tout est retiré et l'injection est NON_CONFIRMEE. Au retrait : plus aucun
pod ne porte ce retard (30 s au plus).

**La règle de Y, corrigée (écart 2).** D.1 demandait 2 100 m de CPU libre sur Y, « la demande de 2
cœurs du voisin de la seconde série ». La prémisse était fausse : dans la seconde série, panne.sh
plafonne la demande du voisin à « libre − 100 m, arrondi à 100 m », et les voisins ont réclamé 1 400 à
1 700 m. Avec 2 100 m, aucune machine n'était Y (la plus libre hors workers6 et hors base, workers1,
a 1 725 m) : D ne serait pas partie. La règle suit maintenant son intention écrite : Y où le voisin
réclamerait au moins 1 400 m par la même règle que la cause hote (la plus petite demande des voisins
de la seconde série). Corrigée en voyant le CPU libre, mais sans rien lire de C, de D ni d'un témoin ;
elle ne change pas X.

**Les couples** (`graphe_en/couples_d.py`, placement de la fin de base-01, CPU libre relevé le 28
sept.) : 249 fenêtres normales d'apprentissage ; workers0 pas X (le producteur) ; workers5 pas X (un
seul service actif) ; workers2 X possible (ts-config, ts-order-other, ts-preserve, ts-station actifs
dans 249/249) ; workers1 seul Y possible (1 725 m libres, le voisin réclamerait 1 600 m). Couple unique
workers2:workers1, pour les trois injections. campagne.sh refait ce calcul au départ et refuse si les
cibles diffèrent.

**La vérification des essais, fixée avant le premier** (`graphe_en/essai_d.py`). Le graphe de l'essai
est construit par run.py (code figé, mise à l'échelle apply) ; lecture.py n'est pas lancé ; le seul
script lu dessus ne sort que, pour chaque réplique, sa machine et la médiane de process_time_p50 avant
et pendant l'injection. « Nettement plus lente » (D.1) : la médiane de la réplique de X pendant la
panne vaut au moins 1,5 fois la plus grande des deux autres (calcul : 0,706 s + 5 à 6 × d, soit 1,5 fois
dès 75 ms environ). Sinon : arrêt, décision avec l'utilisateur. Le reste de chaque essai est lu comme
en D.1 : tas relevé chaque minute, dépôt, temps des parcours Locust, paquets jetés et retransmissions
de X, veilles.

**D.4/7, la préparation du cluster (accord de la nuit).** Avant la purge (00:41 UTC) : Locust à 25
voyageurs, tous les parcours passent, aucune panne en cours ni reste. `donnees.sh purger
--redemarrer` de 00:41:31 à 00:45:45 UTC : 70 945 lignes purgées, ts-order-service, ts-seat-service
et ts-travel-service redémarrés. Relecture du code de D par trois agents en parallèle (constats
contre-vérifiés un par un, voir plus bas).
Contrôle à 00:47 UTC (`loadgen.sh bilan`) : tous les parcours passent, « réserver » à 0,7/s (3 échecs
500 pendant les redémarrages, 56 sur « chercher ») ; rien n'est bloqué, aucun redémarrage de plus.
Placement après la purge : ts-order-service passé de workers3 à workers5, ts-seat-service sur
workers1, ts-travel-service sur workers3 ; répliques inchangées (workers0, workers2, workers5) ;
workers1 : 1 625 m libres (le leurre réclamerait 1 500 m). Attente de 30 min à 25 voyageurs.

**D.4/7, la relecture** (trois agents, un par partie, chaque constat contre-vérifié par un quatrième
qui cherchait à le réfuter) : 15 constats, 10 confirmés, tous corrigés avant tout essai :
- le retrait de « reseau » s'arrêtait au premier objet qui résistait (le leurre pouvait rester) : il
  tente désormais les trois, le leurre d'abord, et dit s'il a échoué ;
- les paquets jetés se lisent dans la file du netem de chaque pod, que Chaos Mesh refait au retrait :
  le témoin « après » voyait donc toujours 0. Le compte de X est relevé juste AVANT le retrait et gardé
  avec les témoins (« relevé avant le retrait ») ; c'est là que se lit « jetés = 0 » ;
- essai_d.py compte aussi les fenêtres de panne sans le nœud host X ou sans la réplique de X (des
  comptes, aucune valeur) : une seule → effondrement, arrêt (D.1) ; une lecture impossible rend 2 ;
- l'instant de l'injection est pris à la pose des deux objets de Chaos Mesh (et non avant l'attente
  du pod leurre, jusqu'à 90 s) : la ligne du registre reste à moins de 120 s du déroulé, comme
  fautifs.py l'exige ;
- un objet refusé par Kubernetes laisse maintenant une ligne NON_CONFIRMEE au registre ;
- couples_d.py ne compte que les pods en marche (ni en attente, ni en arrêt) ;
- `--intensite` d'au moins 1 ms exigée dès le départ de campagne.sh ;
- le relevé réseau des pods ne lance plus qu'une recherche par pod (il retardait le témoin « avant »,
  donc la pose) ;
- `verifier reseau` exige aussi le réglage de base des répliques (140 ms, posé sur chacune), comme
  `verifier base` (constat jugé non bloquant, ajouté quand même : le calcul de D.1 en dépend).
Écartés à la contre-vérification : Y « sans réplique » (écrit en D.1), les restes d'objets au départ
(déjà refusés par l'état et le nettoyage), une lecture ratée comptée 0 (le nombre de pods lus est
affiché), le retrait lu dans les objets de Chaos Mesh (même lecture que pour la base).
Seconde relecture, des seules corrections (un agent) : 2 défauts et 3 petits, corrigés :
- essai_d.py : les pires effondrements (réplique de X absente de toute la panne, X absent, réplique
  recréée sous un autre nom) sortaient en « REFUS » ; la réplique de X est désormais désignée par les
  fenêtres d'AVANT la panne et l'effondrement est testé avant la forme ;
- l'ordre du retrait : le pod leurre met 30 s à partir (son sh ignore SIGTERM) ; le retard de X
  restait donc 30 s après la fin du stress. Ordre : stress de Y, retard de X, puis le pod ;
- une file illisible ne compte plus comme « 0 jeté, pod lu » ; le relevé avant le retrait dit aussi
  combien de pods sont encore retardés (0 : Chaos Mesh a déjà levé la panne, le relevé ne compte pas) ;
  son heure est prise avant le retrait.

**D.5/7, essai 1 : 75 ms** — lancé à 01:17:04 UTC (horloge de vms0), 31 min après la fin de la purge :
`./campagne.sh essai-reseau-75 --profil 25:30 --panne reseau --a 5 --duree 20 --intensite 75 --cible
workers2:workers1` (tmux sur vms0, `~/journaux-hors-campagne/d5-lancer.sh`), tas relevé chaque minute.
Au départ : leader tsdb-mysql-0 ; `verifier reseau` prêt (réglage de base 140 ms sur les trois
répliques) ; couples recalculés sur le placement du départ : workers2:workers1, identiques aux cibles.
À la 5e minute de panne (01:28 UTC), tas = 2 : 75 ms ne déborde pas avec marge ; l'essai va à son
terme pour lire la règle de montée. **Le dépôt, fixé avant de le lire** : Prometheus ne garde aucun
débit de RabbitMQ (seulement le tas et les consommateurs) ; le dépôt et le retrait ne se lisent que
dans le graphe de l'essai (publish_rate et consume_rate de la file, reconstruits des spans), lecture
que D.1 permet (« lue seulement sur les relevés, la file et le dépôt »). essai_d.py les écrit aussi
(médianes avant / pendant), avec la règle de montée rendue chiffrée avant le premier verdict :
« dépôt proche de celui d'avant » = médiane pendant ≥ 0,9 × médiane avant (à 25 voyageurs, le dépôt
va de 3,3 à 3,75 : ±6 %) ; « au-dessus du retrait » = médiane de (dépôt − retrait) pendant
≥ −0,1 message/s (l'écart d'équilibre mesuré à l'étalonnage : ±0,1). Rien d'autre du graphe n'est lu.
Résultat de l'essai 1 (75 ms), lu seulement comme D.1 le permet : injection confirmée 01:22:41 →
retrait 01:42:32 (10 pods de workers2 retardés, leurre à 1 500 m sur workers1) ; 3 veilles pendant
la panne « parcours ok », leader inchangé, aucun redémarrage ; Locust sans échec (p50 sur l'essai :
chercher 0,58 s, réserver 2,3 s, repas 10 ms) ; paquets jetés sur workers2 : 0 (relevé avant le
retrait, les 10 pods encore retardés), retransmissions +4 pendant la panne ; tas entre 0 et 7 pendant
la panne, 2 à la 5e minute, 10 au retrait, puis 0. essai_d.py (graphe `runs/20260928-034749` sur vms0,
25 fenêtres) : réplique de workers2 706 → 1 081 ms, les deux autres 706 ms (1,53 fois, « nettement
plus lente » ; le calcul de D.1, 0,706 + 5 × 0,075 = 1,081 s) ; aucune fenêtre sans X ni sans sa
réplique ; dépôt 3,34 → 3,35/s, dépôt − retrait +0,00. **Décision selon la règle** : le cran tient, ne
déborde pas avec marge, le dépôt reste proche et au-dessus du retrait → essai 2 à 150 ms.

**D.5/7, essai 2 : 150 ms** — lancé 01:50:13 UTC ; injection confirmée 01:57:02 → retrait 02:16:4x
(10 pods de workers2, leurre 1 500 m sur workers1) ; couples au départ identiques. 3 veilles pendant la
panne « parcours ok », leader inchangé, aucun redémarrage ; Locust sans échec (p50 sur l'essai :
chercher 1,1 s, réserver 4,5 s, repas 10 ms) ; paquets jetés sur workers2 : 0 (avant le retrait, 10
pods encore retardés) ; tas entre 0 et 9 pendant la panne, 8 à la 5e minute. essai_d.py (`runs/20260928-042201`) :
réplique de workers2 706 → 1 456 ms (0,706 + 5 × 0,150 = 1,456 s), les autres 706 ms, 2,06 fois ;
aucune fenêtre sans X ni sans sa réplique ; dépôt 3,37 → 3,17/s (94 %), dépôt − retrait +0,00.
**Décision selon la règle** : tient, ne déborde pas avec marge, dépôt proche et au-dessus du retrait
→ essai 3 à 200 ms. À noter : « réserver » approche les 5 s du rythme de Locust ; au-delà, le dépôt
baissera (prédit en D.1).

**D.5/7, essai 3 : 200 ms** — lancé 02:23:59 UTC ; injection confirmée 02:29:37 → retrait 02:50:09 ;
3 veilles « parcours ok », leader inchangé, aucun redémarrage ; Locust sans échec (p50 : chercher
1,5 s, réserver 6,1 s, repas 10 ms) ; jetés sur workers2 : 0 (10 pods encore retardés) ; tas entre 0
et 7 pendant la panne. essai_d.py (`runs/20260928-045441`) : réplique de workers2 706 → 1 706 ms
(0,706 + 5 × 0,2), 2,42 fois ; aucune fenêtre sans X ni sans sa réplique ; dépôt 3,31 → 3,04/s (92 %),
dépôt − retrait +0,00. **Décision selon la règle** : tient, ne déborde pas, dépôt proche et
au-dessus du retrait → essai 4 à 300 ms, le dernier cran.
**Prédiction écrite avant l'essai 4** : le dépôt baisse à chaque cran (réserver passe les 5 s du
rythme de Locust : preserve et station sont sur workers2). Les deux autres répliques absorbent
2 × 1,416 = 2,83 messages/s ; à 300 ms la réplique de X en traite 1/2,206 = 0,45, soit 3,29 en tout.
Si le dépôt tombe sous environ 3,2/s, la file ne débordera pas : ce sera « 300 ms sans débordement »,
donc arrêt et décision avec l'utilisateur.

**D.5/7, essai 4 : 300 ms** — lancé 02:57:06 UTC ; injection confirmée 03:02:44 → retrait 03:23:12 ;
3 veilles « parcours ok » (file 0 aux trois), leader inchangé, aucun redémarrage ; Locust sans échec
(p50 : chercher 2,5 s, réserver 9,8 s, repas 10 ms) ; jetés sur workers2 : 0 (10 pods encore
retardés), retransmissions +43 pendant la panne ; tas entre 0 et 4 pendant la panne. essai_d.py
(`runs/20260928-052746`) : réplique de workers2 706 → 2 206 ms (0,706 + 5 × 0,3), 3,12 fois ; aucune
fenêtre sans X ni sans sa réplique ; dépôt 3,50 → 2,48/s (71 %), dépôt − retrait +0,00.

**Décision selon la règle : « 300 ms sans débordement » → arrêt, décision avec l'utilisateur.**
jumeaux-01 n'est PAS lancée. Cluster laissé propre (aucune panne, aucun reste ; seul le réglage de
base des répliques), Locust à 25 voyageurs. Les quatre essais : `campagnes/essai-reseau-{75,150,200,300}/`
(sous le scellé de D : jamais lus par un témoin ni par le GNN).

**Ce que montrent les essais (lu seulement comme D.1 le permet).**
- Le moyen fait exactement ce qui était calculé : la réplique de X prend 5 × d de plus par message
  (706 → 1 081, 1 456, 1 706, 2 206 ms), les deux autres ne bougent pas, rien n'est jeté, aucune
  erreur, pose et retrait sans accroc.
- La file ne déborde jamais, parce que le dépôt baisse avec d (3,34 → 3,35 ; 3,37 → 3,17 ; 3,31 →
  3,04 ; 3,50 → 2,48/s) : « réserver » passe de 0,23 s au repos à 2,3 ; 4,5 ; 6,1 ; 9,8 s, au-delà des
  5 s du rythme de Locust. Les deux autres répliques absorbent seules 2 × 1,416 = 2,83 messages/s ;
  il faudrait un dépôt au-dessus de 2,83 + 1/(0,706 + 5d), qui recule quand d monte.
- Deux causes possibles de la chute du dépôt, non séparables sans lire davantage : les services de X
  sur les parcours (preserve et station, sur workers2), et le leurre lui-même (workers1 porte
  ts-security-service et ts-seat-service, sur « réserver » ; son stress occupe les 4 cœurs). Si le
  leurre ralentit « réserver », il ne « crie » plus « sans rien causer ».
- Prédit avant l'essai 4 (« si le dépôt tombe sous environ 3,2/s, la file ne débordera pas ») : vérifié.

**Pour la décision (à prendre avec l'utilisateur, rien n'est lancé).**
1. Un essai de diagnostic, puis un moyen corrigé : retarder seulement ce que X envoie vers la base
   (workers4) et la file (workers3), pas vers les autres services. La réplique ralentit pareil (ses 5
   échanges vont à la base et à la file), les autres pods de X qui interrogent la base aussi (la
   signature « machine » reste), mais les appels des parcours entre services ne sont plus retardés :
   le dépôt devrait tenir. À 300 ms le débordement serait juste (3,28 absorbés contre environ 3,35
   déposés) : l'échelle devrait aller au-delà (400, 500 ms), et un essai « leurre seul » dirait ce que
   le leurre coûte au dépôt. Tout cela serait écrit et relu avant, comme D.1.
2. Abandonner D : le GNN n'est alors jugé que sur C (l'axe (d) vaut « égal »), et le rapport dit
   pourquoi D n'a pas pu déborder.

## 2026-09-28 — D.5/7, suite : écart 3, le moyen corrigé (écrit avant tout nouvel essai)

**Décidé avec l'utilisateur** (28 sept., matin : « VAS Y » sur la recommandation ci-dessous, avec 4
injections ; juger le GNN sur C seul est exclu). Les essais de M0 restent sous scellé ; ils n'ont servi
que par leurs lectures permises (dépôt, parcours Locust, réplique).

**Pourquoi.** Sous M0 (retard de tout ce qu'envoient les 10 pods de X), la chaîne « réserver » prenait
28 à 40 d de plus, la réplique 5 d : les parcours ralentissaient environ 7 fois plus que la réplique,
et le dépôt baissait avant que la file déborde. ts-preserve-service, sur X, fait environ 7,5 appels
sortants par réservation, chacun retardé.

**L'étude** (workflow, 3 agents indépendants, une synthèse, un contradicteur ; calculs dans le
scratchpad hors dépôt). Données lues : fenêtres normales d'apprentissage des deux séries, code, code
source de Chaos Mesh v2.8.4. À dire : un agent a aussi lu les fenêtres de PANNE hote-01 et hote-02 de
l'apprentissage (ni le test, ni C, ni D) pour le leurre ; inutile, car M0 à 75 ms montre déjà que le
leurre ne touche pas le dépôt (3,34 → 3,35).

**Le moyen corrigé (M4).** Leurre inchangé. Deux objets réseau sur X :
- `panne-reseau-replique` : la seule réplique de X (sélecteur nodes + app), tout ce qu'elle envoie,
  sans cible. Sans cible, ce retard s'ajoute à son réglage de 140 ms (règle à la racine, puis le
  prio et la bande filtrée du réglage : la composition de M0, mesurée à 706 + 5d aux 4 crans) ;
- `panne-reseau` : les autres pods de train-ticket sur X (app ≠ la réplique, ≠ la base), vers la base
  seulement (même cible que le réglage : pods de la base + adresses de service devant elle).
- Pourquoi pas une seule règle « X vers la base » sur tous les pods : sur la réplique, deux règles à
  cible sur les mêmes adresses ne s'additionnent pas (chaque règle à cible a sa bande ; le paquet ne
  prend qu'une bande, tc_server.go) : elle aurait 140 ms OU d.
- Confirmation : les trois objets AllInjected dans les mêmes 60 s ; la réplique de X porte
  panne-reseau-replique à d ms (et lui seul), chaque autre pod de X porte panne-reseau à d ms (et lui
  seul), aucun pod hors de X n'en porte ; sinon tout est retiré, NON_CONFIRMEE.

**Ce que ça change à la signature de D.1.** Plus lents : la réplique de X (+5d par message, et
l'accusé de réception à rabbitmq retardé : capacité probablement 1/(0,706 + 6d)) ; les flèches
queries de station, config et order-other (+d par requête : les 3 services de X qui interrogent la
base, actifs dans 249/249 fenêtres normales) ; preserve par ricochet. Inchangés : les flèches calls
qui sortent de X, le trafic entre pods de X (sauf depuis la réplique), les nombres de la machine X,
et les appelants de la base hors de X (ce qui sépare D de C, où tous les appelants ralentissent). Le
banc de pannes fabriquées de E prendra cette signature. Le rapport dira : « le chemin de X vers les
données est lent » (la réplique : tout ce qu'elle envoie), pas « toute la carte de X ».

**Prédiction** (estimée, modèle du dépôt en boucle fermée calé sur M0) : à 300 ms, la chaîne
« réserver » resterait sous les 5 s du rythme ; marge dépôt − capacité de +0,07 à +0,19 message/s,
tas de 20 à 55 à la 5e minute ; une injection compte avec une probabilité d'environ 0,75 (0,56 si
la capacité ne perd que 5d). Mince : c'est pourquoi 4 injections.

**Échelle et arrêt.** 300 ms ; retenu s'il déborde selon D.1 (tas > 10 dès la 5e minute de panne,
en hausse au retrait) et passe essai_d.py. S'il tient sans déborder : un seul autre essai, 400 ms.
400 ms sans débordement, un effondrement, ou un échec d'essai_d.py : arrêt, décision avec
l'utilisateur (repli étudié : sortir ts-station-service de X, un choix de placement qui lui
revient). 500 ms exclu d'avance (Hikari vérifie une connexion inactive depuis plus de 0,5 s : un
échange de plus ; sondes du kubelet non éprouvées au-delà de 300 ms). essai_d.py vérifie en plus,
avant le verdict : la réplique de X pendant la panne vaut sa médiane d'avant + 5 × d à 10 % près
(sinon « MOYEN NON CONFORME » : un retard perdu ou doublé sur la réplique ; à 300 ms, les pièges
seraient 706, 1 506 ou 3 006 ms au lieu de 2 206).

**Campagne.** `jumeaux-01 --profil 25:180 --panne reseau --a 5,50,95,140 --duree 20 --intensite
<retenue> --cible workers2:workers1 ×4`. Les règles de décision de D sont inchangées (au moins 2
injections qui comptent). Essais nommés `essai-reseau-b-<d>`.
Relecture de l'écart 3 (deux agents, constats contre-vérifiés) : aucun défaut bloquant ; corrigés :
commentaires restés sur M0, deux refus de l'injection repris dans `verifier` (une seule réplique sur X,
adresses devant la base lisibles), un pod de la base sur X n'attend aucun retard (il est exclu du
sélecteur), essai_d.py refuse s'il ne peut pas faire le contrôle « avant + 5d ».
