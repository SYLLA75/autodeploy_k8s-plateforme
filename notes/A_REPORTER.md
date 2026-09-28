# À reporter : dans les trois projets, et dans le rapport CSI

Tenu à jour à chaque étape du plan (phases A à F). Deux listes :
ce qu'il faudra **porter dans le code** des trois projets refondus, et ce qu'il
faudra **réécrire dans le rapport CSI**. Le détail de chaque étape (mesures,
chiffres, vérifications) est dans `notes/JOURNAL.md` ; ici, seulement quoi
changer et où.

Point de départ de tout le travail : commit `95ad49b` (lignes de base du
18 sept.). Tout ce qui a changé depuis, en une commande :

```bash
git diff 95ad49b..plan-phases -- apps/ campagne.sh PROCEDURE.md graphe_en/
```

---

## 1. Code à porter dans les trois projets

Projets : `~/coordination-fault-bench`, `~/banc-fautes-coordination`,
`~/coordination-fault-bench-web`. Ce ne sont pas des dépôts git et leurs
fichiers sont renommés (`campaign.sh`, `graphe/`…) : porter **par le sens**,
pas en appliquant le diff tel quel. Décidé le 26 sept. : en une seule fois,
à la fin, « une fois qu'on aura quelque chose de propre ».

| étape | quoi | fichiers | commits |
|---|---|---|---|
| A.2 | relation `queries` : appelant → pod de la base (spans CLIENT `db.system`), 5 nombres mesurés chez l'appelant ; adresse → pod par `graph.databases` | `graphe_en/edges.py`, `settings.py`, `config.example.yaml` | 89881ed, 0907f77 |
| A.4 | 4 nombres réseau pour l'hôte (`net_rx_rate`, `net_tx_rate`, `net_drop_rate`, `tcp_retrans_ratio`), carte physique seulement ; hôte 5 → 9 nombres ; métriques gardées par la collecte | `graphe_en/features.py`, `apps/metrics-keep.txt` | 0426a09, 5e3f0bd |
| série 2 | cibles tournantes : `--cible x,y,z`, une cible par injection, vérifiées avant le départ (`panne.sh verifier`) | `campagne.sh`, `apps/panne.sh`, `PROCEDURE.md` | 58c9691 |
| A.7 | les figures dessinent `queries` et le réseau des hôtes | `graphe_en/render.py`, `README.md` | a87bb6a |
| A.8 | **flèches mises à l'échelle** comme les nœuds (même référence saine) ; le manifest dit quel code a construit le run, quelle base, quelle mise à l'échelle ; `run.py` affiche la raison d'un refus ; écart 4 du manifest corrigé | `graphe_en/export_pyg.py`, `snapshot.py`, `run.py` | 440e8af |
| A.8 | le gel : ce qui est figé et sa vérification | `graphe_en/graphe_fige.json`, `gel.py` (nouveaux), `LEXIQUE.md`, `README.md` | 440e8af, 100945c, étiquette `graphe-fige` |
| B.1 | le fautif de chaque injection et les règles de jugement, écrits avant tout calcul | `graphe_en/fautifs.py` (nouveau) | e338da4, 3c5aa84 |

| B.2 | le juge commun : lecture des graphes figés, étiquette des minutes, coupure, notation, essais du juge | `graphe_en/juge.py` (nouveau), `fautifs.py` | 5 commits jusqu'à 519c686 |

| B.3 | témoin 1, le tableau équitable : cases + résumés sans identité, 2 forêts, rejet des deux côtés, 5 graines ; juge : cause jamais vue à part | `graphe_en/temoin_tableau.py` (nouveau), `juge.py`, `fautifs.py` | jusqu'à 96d2622 |
| B.4 | témoin 2, le score par nœud : normal propre de chaque nœud (plancher = écarts de chaque nœud à sa médiane), sans / avec exemples (détecteur sur écarts croisés, prototypes, repli sur l'écart devant l'inconnu) | `graphe_en/temoin_noeud.py` (nouveau) | 4ca7001 → ea31952 |
| B.5 | témoin 3, la règle qui suit les flèches, deux versions (littérale, cause commune) ; `juge.validation` (coupure répétée, `--validation`) | `graphe_en/temoin_fleches.py` (nouveau), `juge.py`, les trois témoins | 98ec3f9 → ea31952 |
| B.6 | les témoins côte à côte : tableau de bord, fausses alertes au fil du temps, répétition « panne jamais vue » | `graphe_en/temoins.py` (nouveau) | 98ec3f9 → ea31952 |
| B.7 | relecture finale : base lente jamais dans la validation, cause jamais vue à part, sorties des deux séries jamais écrasées (`juge.sortie`), budgets affichés | `juge.py`, les trois témoins, `temoins.py` | ea31952, étiquette `temoins-figes` |

| C.0 (27 sept.) | la panne « base » (objet Chaos Mesh neuf `panne-base`, retard sur la sortie de tsdb-mysql-0 vers ses clients sauf ses suiveuses, refus si ce n'est pas le leader) ; `panne.sh leader` ; le relevé note le leader, le cpu de ts-order-service et la taille de `orders` ; un cas par défaut dans `retirer` ; `campagne.sh` refuse de partir si tsdb-mysql-0 n'est pas le leader et écrit `leader_base`, `placement_au_depart`, `placement_a_la_fin` ; `decision_c.py` (garde G tout de suite, lecture de C seulement après l'étiquette `gnn-fige`) | `apps/panne.sh`, `campagne.sh`, `graphe_en/decision_c.py` (nouveau), `PROCEDURE.md` | à committer |

**Encore à coder, pas encore fait :**
- phase D : la panne « réseau » d'une machine entière et le leurre dans la même
  injection (`panne.sh`, `campagne.sh --leurre`) ; `fautifs.py` ne doit plus
  écraser `campagnes/fautifs.txt` quand il lit une autre campagne que les séries.

**À ne jamais porter :** `graphe_en/config.yaml` (identifiants),
`scaler.json` (propre à une référence saine), `runs/` (données).

---

## 2. Rapport CSI à réécrire

Fichier : `~/CSI_REPORT_2026/rapport/rapport.tex`. Les numéros de ligne datent
du 24 sept. : chercher la phrase. À appliquer seulement quand tu le décides,
en respectant tes règles de prose. Vérifier aussi les diapositives qui
reprennent la perspective (19 et 20 de la version allégée, 16 de la plénière).

### Faux ou contradictoire
1. l. 836, section 7, « conçues pour que ce tableau échoue » : contredit 3.3.
   Dire : pannes réelles dont la marque tombe loin de la file.
2. l. 841-842, « les quatre mêmes causes » avec la base lente : la base lente
   appelle une autre équipe, c'est une **5e cause** (décidé le 24 sept.).
3. l. 843, « toujours du côté du consommateur » : faux pour la cause 1.
4. l. 820-824, raisons R-GCN contre HGT : HGT a aussi des poids par relation ;
   retirer une relation marche avec tout modèle ; garder le petit nombre de
   paramètres (« très peu d'injections »).
5. l. 634-636, 5.3, « la réplique gelée se noierait » : faux (706 contre
   1 081 ms, 3 → 2 lecteurs). Dire : on saurait qu'une réplique décroche,
   sans savoir laquelle.

### Affirmé sans preuve, à adoucir
6. l. 829 « signale et localise », l. 838 « fournit directement » : les
   victimes d'une panne qui se propage s'écartent aussi.
7. l. 809 « découle d'un état de l'art » : l'état de l'art justifie le graphe,
   pas le GNN ; dire qu'il sera comparé à une règle qui suit les flèches.
8. l. 348, 4.1, `executes on` sert la cause 3 : les nombres de l'hôte ont
   suffi ; la flèche ne sert que si plusieurs hôtes sont chargés.
9. l. 853, 5e relation « vers la base » : fait (A.2), vers le pod leader
   `tsdb-mysql-0`, depuis l'adresse donnée par l'appelant.
10. l. 404, 4.2, « aucune source ne l'expose » : « aucune des sources
    collectées sur la plateforme ».

### Précisions
11. l. 152, H1 : « une méthode qui lit cette représentation, flèches
    comprises » ; scinder H1 (file comme nœud, relations).
12. l. 710 et 779, « sans aucune relation » : « sans les flèches, mais
    construit en les suivant à la main ».
13. l. 791 : ce sont les relations qui doivent faire leurs preuves, face à une
    règle qui les suit et à un modèle appris.
14. l. 862-866, lignes de base : ajouter le tableau équitable et la règle qui
    suit les flèches, écrits avant la base lente (phase B).
15. l. 861 : l'hôte n'avait aucun compteur réseau (tableau 3) ; il en a quatre
    depuis A.4.

### Le graphe (A.2, A.4, A.7, A.8)
16. Relation `queries` : équation (1) de 4.1 (une méta-relation de plus),
    « cinq sortes d'arêtes », figure 1, tableau 3, comptes d'arêtes en 5.3,
    diapos et schémas du graphe. Le 150/150 ne change pas.
17. Hôte à 9 nombres : tableau 3 ; ils n'existent pas dans la première série
    (absents, jamais 0).
18. **Le graphe est figé avant la base lente** (étiquette `graphe-fige`) :
    colonnes, relations, fenêtres, mise à l'échelle. Pourquoi : un graphe
    retouché après avoir vu la panne serait taillé pour la réponse.
    `gel.py` le prouve pour chaque graphe utilisé.
19. **Les flèches sont mises à l'échelle** comme les nœuds, sur la même
    référence saine, décidé au gel : c'est par elles que la base lente se
    verra. Moyennes communes à toutes les flèches d'une relation.

### Les campagnes (seconde série)
20. Décrire la seconde série et chaque raison : refaire les 5 campagnes
    (compteurs réseau absents de la première, ne pas mélanger) ; normale de
    120 min à paliers 10/25/20/15 ; cibles tournantes pour qu'aucun modèle
    n'apprenne un nom ; mêmes intensités et même plan ; pas d'exportateur
    MySQL ; `purger --redemarrer` avant chaque campagne.
21. Cause 2 « dégradation du consommateur » (tableau 2, 3.3) : le retard est
    posé sur le chemin répliques → base, mais seul ce chemin ralentit, la base
    répond vite aux douze autres appelants. C'est bien le consommateur ; la
    base lente (cause 5) ralentit tous les appelants.
22. Section 6, lignes de base : écrites **après** avoir vu la première série
    (« avant toute modélisation » est vrai, « avant d'avoir vu les données »
    serait faux). Ajouter le test à l'aveugle de la seconde série : 162/162
    pour le tableau plat et les règles, 142/162 pour la file seule.
23. Section 6, « la saturation d'hôte n'atteint pas la file » : dépend de ce
    que l'hôte porte. hote-02, 3e injection : workers0 portait aussi
    ts-order-service (replacé par un redémarrage), le dépôt tombe de 3,6 à
    0,94 msg/s. Le placement des pods est une condition d'expérience.
24. Temps de traitement des répliques selon le trafic : 706 ms à ≥ 0,95 msg/s
    par réplique, 846 ms à ≤ 0,70 (saine-09). La limite de 883–894 ms des
    lignes de base est proche de 846.
25. Flux commandes → base : grossit avec l'âge de la purge (quelques dizaines
    de ko/s à plusieurs Mo/s), vu grâce aux compteurs réseau. Même dérive
    d'une campagne à l'autre.

### Évaluation (phase B)
26. **Le fautif de chaque cause, écrit avant tout calcul** (B.1) : blocage =
    la réplique gelée ; hôte = la machine ; lenteur = les 3 répliques ;
    **charge = aucun fautif**, jugée sur la cause seulement (rien n'est cassé,
    il y a plus de voyageurs) ; base lente = le pod de la base ; jumeaux = la
    machine au réseau dégradé, jamais le leurre. Juste au rang k si un fautif
    est parmi les k premiers.
    Règles de jugement, écrites aussi avant : chaque méthode rend une alarme,
    une cause et un classement ; fausses alertes au fil du temps ; top-k sans
    et avec l'alarme ; égalités départagées contre la méthode ; mesures par
    minute ET par injection ; une panne jamais vue a pour bonne cause
    « panne inconnue » (c'est là que sert le rejet du classifieur à
    prototypes).

27b. **Le plancher « a priori »** (B.2) : une méthode qui ne lit aucune donnée,
    et classe les nœuds par le nombre de fois qu'ils ont été fautifs à
    l'apprentissage, a déjà 100 % en top-1 sur la lenteur et 100 % en top-3
    sur le blocage (toujours les trois mêmes répliques), 0 sur l'hôte. Donner
    ce plancher à côté de chaque méthode ; les mesures qui départagent sont le
    top-1 du blocage et de l'hôte, et la base lente (fautif jamais vu).

27c. **Le tableau équitable** (B.3) : tous les nombres, aucune structure de
    flèche ; 8/8 causes, 6/6 fautifs, 8–10 fausses alertes sur 120 (5 graines).
    Dire les deux versions écartées et pourquoi (chaque fois pour le
    renforcer). Répétition « panne jamais vue » : il détecte la nouveauté
    (blocage, lenteur : 100 % « inconnue ») mais ne désigne jamais le fautif
    (0 %), et ne voit pas l'hôte (3 %). Argument central pour l'écart au
    normal nœud par nœud (témoin 2, première étape du GNN).

27d. **Le score par nœud** (B.4, témoin 2) : chaque nœud comparé à son propre normal,
    sans flèches. Sans exemples, il désigne l'hôte (39/39) et souvent la réplique
    gelée, mais aussi la victime (la file) : blocage 36/38 et lenteur 25/38 au test,
    1/38 et 0/38 sur la validation. Avec exemples : 113/115, mais 28/120 fausses
    alertes (dérive de fin de campagne). Il connaît chaque nœud par son nom.

27e. **La règle qui suit les flèches** (B.5, témoin 3), deux versions : littérale (la
    définition du 24 sept.) et cause commune (la plus forte, choisie en sachant que C
    serait une base lente). Référence experte : ~100 % sur les causes connues pour la
    cause commune et pour la littérale avec exemples ; la littérale sans exemples fait
    cause 125/153 et top-1 90/115 au test (elle accuse la base par le bruit), 150/153 et
    114/115 sur la validation. Par construction, et après une révision informée par le
    test (v1 : cause 52/153). Elle
    sait plus que le GNN (normal par nœud et par paire de services, consommateurs
    attendus, signatures des causes).

27f. **Les témoins côte à côte et la répétition « panne jamais vue »** (B.6) : les
    tableau, appris sur exemples, ne désigne jamais le fautif d'une cause jamais vue
    (0 %) ; l'écart au normal nœud par nœud, oui, avec ou sans exemples (devant
    l'inconnu, le fautif appris retombe sur l'écart) : hôte 117/117 au test et 78/78 sur
    la validation ; blocage 101/114 et lenteur 89/114 au test, mais 1/76 et 0/76 sur la
    validation (il désigne la file). C'est l'argument de l'étape 1 du
    GNN ; la règle ne se compare pas ici (elle connaît les causes). Corriger 27c : le
    « 100 % inconnue » du tableau ne tient pas sur la validation (blocage 15/76).

27g. **Méthode** : toute version notée sur le test puis changée est dite (sortie
    gardée dans `campagnes/versions-vues-sur-test/` pour 974ba15, 4ca7001 et la règle
    v1 ; chiffres seuls dans le journal pour les autres). Regards sur le test, version
    finale comprise : tableau 3, score par nœud 4, règle 2. Chaque changement visait à
    renforcer le témoin ; le score par nœud avec exemples y a pourtant un peu perdu
    (cause 136 → 130/153). Depuis B.5, tout réglage se fait sur la
    validation (la coupure répétée une injection plus tôt), jamais sur le test ; la
    base lente n'y entre jamais. Budgets de fausses alertes différents (tableau et
    score par nœud sans exemples 5,2 %, score par nœud avec exemples 10 %, règle
    8,4 %) : comparer à budget égal.

27h. **Écrit avant C, fixé le 27 sept.** (journal, section du 27 sept.) : la table de
    décision (mesure principale, garde de spécificité G, décisions dans l'ordre, axes
    où le GNN doit battre la règle), les prédictions, le calage du GNN, les conditions
    de C. Choix de méthode à dire : (1) le SCELLÉ, C et D enregistrées mais lues par
    personne avant que le GNN soit figé (le code le fait respecter : `decision_c.py`
    refuse sans l'étiquette `gnn-fige` ou si le code a changé depuis les étiquettes) ;
    (2) une injection ne compte que si la file était vide avant, déborde (tas > 10 dans
    strictement plus de la moitié de ses minutes) et sans effondrement : le sujet est la
    faute de COORDINATION ; (3) les minutes normales de C et D n'entrent dans l'apprentissage de
    personne (témoins et GNN sur les deux séries seules) ; (4) aucun témoin ajouté après
    le gel ; (5) le GNN comparé à chaque version de la règle qui trouve, à son budget de
    fausses alertes, perte = image de la victoire. Pourquoi écrire avant : choisir après ne
    change pas le GNN, seulement ce qu'on en dit ; le régler en regardant C abîmerait sa
    valeur réelle. Limite dite d'avance : à 75 ms la file déborde dès la première minute,
    donc « plus tôt » ne départagera probablement pas ; si la règle trouve la base, l'écart
    du GNN sur C ne peut venir que des fausses alertes ou du nombre d'injections, sinon de D.
27i. **La garde G calculée avant C** (`decision_c.py --garde` ; essai à une graine sur le
    poste, à confirmer avec 5 graines sur vms0) : aucune méthode ne met la base première
    dans une panne connue, sauf la règle littérale sans exemples (lenteur-01) : elle est
    écartée d'avance, comme le journal le prédisait.
27j. **DOMINANT** (l. 867, promis comme témoin) : jamais codé ; décidé le 27 sept. de ne
    pas comparer à un autre GNN publié. À la place, dans le retrait des flèches : notre
    GNN avec un seul type de lien et sans canal d'arête (« un GNN plus simple
    suffirait-il ? »). Retirer DOMINANT de la phrase.
27k. **Numéro de la base lente** : le tableau 2 du rapport a déjà une cause 5
    (déséquilibre entre partitions) et une cause 6 (courtier) ; la base lente n'est donc
    pas « la cause 5 » (points 2 et 21) : 7e cause ou nouvelle numérotation, à décider
    en réécrivant.

27l. **D écrit avant** (journal, 28 sept., D.1/7, relu par deux agents) : la panne (retard pur sur la
    sortie de la machine X d'une réplique, leurre bruyant Y sans réplique), la signature attendue
    d'après la façon dont le graphe mesure, le choix de X et Y par règle fixe, l'échelle d'intensité
    avec le dépôt, la table de D et de l'axe (d), le banc de pannes fabriquées du GNN fixé avant de
    connaître X. À dire : sur D, aucun témoin figé n'a de principe au niveau de la machine ; une
    victoire du GNN sur D veut dire « il désigne une machine muette que ces méthodes ne peuvent pas
    désigner », pas « il bat la règle à armes égales ».

27m. **Option B : la règle reçoit l'idée « machine » avant D** (journal, 28 sept., « D.1, suite ») :
    témoin 3 bis, `graphe_en/temoin_machine.py`, figé sous `temoin-machine-fige`, utilisé seulement
    pour D. À dire au rapport : une première version a été vue en partie sur le test et corrigée
    par principe (effet sur D inconnu ; compté dans versions-vues-sur-test/LISEZMOI.md). La phrase de 27l
    (« aucun témoin figé n'a de principe au niveau de la machine ») est remplacée : sur D, le GNN
    est comparé à une règle qui a ce principe. Code à porter : temoin_machine.py,
    decision_c.methodes(machine=True) et le contrôle git renforcé. Étiquette `temoin-machine-fige` posée sur
    le commit 818d11f (28 sept., avant D.2 et pendant C.6, sans rien lire de C).
27n. **Deux défauts de decision_c.py (C.0) trouvés et réparés avant toute ouverture** : le contrôle
    git était aveugle (lancé depuis graphe_en/ avec des chemins « graphe_en/… »), et l'axe (c) ne
    pouvait jamais valoir « perdu ». À dire : réparés le 28 sept., avant l'étiquette gnn-fige, sans
    rien avoir lu de C ; l'axe (c) est désormais plus strict pour le GNN (toutes les graines).
27o. **D : le moyen de la panne a changé avant tout essai** (journal, 28 sept., « D.2 (résultats) et
    D.3 ») : retard sur tous les pods train-ticket de X (Chaos Mesh, sélecteur nodes) au lieu de la
    carte réseau (Chaos Mesh refuse les pods au réseau de l'hôte ; tc direct refusé par la protection
    automatique de l'assistant). À dire : le trafic entre pods de X est retardé aussi ; la règle de Y
    corrigée (1 400 m réclamés au moins, et non 2 100 m libres : prémisse fausse). Code à porter :
    panne.sh (cause reseau, sous-commande libres), campagne.sh (--panne reseau, contrôle des couples),
    couples_d.py, essai_d.py. La mesure de la suiveuse (535 → 596 µs) va au rapport.
27p. **D.5 : quatre essais, aucun débordement** (journal, 28 sept.) : la réplique de X ralentit
    exactement de 5 × d par message, mais le dépôt baisse avec d (« réserver » dépasse le rythme de
    Locust) et deux répliques absorbent seules 2,83 messages/s. Arrêt selon la règle écrite ; la
    suite de D est à décider. À dire au rapport quelle que soit la suite : une panne réseau d'une
    seule machine, à cette charge, est absorbée par la file (fait mesuré, pas un échec du GNN).
27q. **D, écart 3 : le moyen corrigé** (journal, 28 sept.) : la réplique de X retardée sur tout ce
    qu'elle envoie, les autres pods de X seulement vers la base ; pourquoi (M0 freinait les parcours
    7 fois plus que la réplique) ; le piège de Chaos Mesh (deux règles à cible ne s'additionnent pas)
    ; 4 injections. À dire : « le chemin de X vers les données », pas « toute la carte ». Code à
    porter : panne.sh (panne-reseau-replique + panne-reseau), essai_d.py (contrôle avant + 5d).

### Limites à écrire honnêtement
27. **Dérive** : toute méthode qui apprend le « normal » se trompe si le normal
    bouge (nouvelles versions, trafic, données). Réponse : recaler la
    référence saine avec la même recette ; l'étape 1 du GNN n'a besoin que de
    données normales, sans étiquettes. Mesuré en phase B : fausses alertes sur
    les minutes normales au fil du temps.
28. **Peu d'injections** : 3 par cause et par campagne, une seule application,
    une seule file. Les résultats en minutes (162/162) sont à donner aussi par
    injection.
29. **Dérive de fin de campagne** (B.4–B.7) : le CPU de ts-order-service monte avec la
    table des commandes ; c'est la source des fausses alertes de fin de campagne (pas
    un reste des pannes). Les résultats changent aussi avec la coupure (test contre
    validation) : les donner tous les deux.
30. **La base est muette par l'instrumentation** : pas d'exportateur MySQL. Le dire :
    si le score par nœud échoue sur C, ce sera d'abord parce que la base ne bouge
    presque pas dans ce qu'on mesure, pas forcément par nature ; le tableau, lui, ne
    désigne jamais le fautif d'une cause jamais vue, quelle que soit l'instrumentation.
31. **Autre environnement** (question du 28 sept.) : ce qui se transporte = collecte, graphe,
    modèle (règles par type de nœud et de flèche, pas par nom). Ce qui change = le normal
    (réapprendre l'étape 1 sur une période sans panne, sans étiquettes) ; les prototypes de
    l'étape 2 servent encore si les mesures sont des écarts au normal de chaque nœud, sinon
    « inconnue » puis un prototype ajouté avec quelques exemples. Campagne : inutile pour
    déployer, nécessaire (petite) pour CHIFFRER le résultat là-bas. **Contrainte pour E** :
    jamais l'identité d'un pod ou d'une machine en entrée du GNN (comme le tableau équitable
    de B.3), mesures exprimées en écart au normal du nœud ; un composant d'une sorte absente
    ici (Kafka, cache) demande un type de plus et un réapprentissage de cette partie.
32. **Forme de la file pendant une panne** (question du 28 sept.) : charge constante (rythme fixe de Locust,
    choisi pour qu'une variation vienne de la panne et non du hasard) + panne constante → la file monte en ligne
    droite pendant l'injection (D : ≈ +13/min), puis se vide au retrait (dent de scie sur la campagne). Bonne
    validité interne ; limite de réalisme à écrire : en production, charge variable et pannes intermittentes
    font monter et descendre la file. Suites possibles : panne intermittente, charge variable pendant la panne,
    marge nulle (la file hésite). La difficulté de D n'est pas l'alarme mais la machine (X contre leurre) et
    « inconnue » ; une file qui monte existe aussi sans panne (cause « charge »).
33. **Figures des résultats (demande du 28 sept., étape F)**, tracées APRÈS gnn-fige, à partir des mêmes réponses,
    sans rien régler dessus : (1) courbe ROC de l'alarme + AUC (et précision-rappel), par méthode ; (2) courbe top-k
    du fautif (AC@k, k = 1…10) ; (3) frise d'une campagne : file, bandes d'injection, instant d'alarme et fautif
    désigné par méthode (partir de graphe_en/figure_campagnes.py) ; (4) barres du retrait des flèches (GNN complet,
    sans aucune arête, sans executes_on, sans queries…) sur C et D ; (5) fausses alertes au fil du temps (dérive).
    Tableaux : taux « x sur n » par cause, par minute et par injection, médiane [min–max] des graines ; F1 et
    précision de l'alarme ajoutés à titre d'information.
