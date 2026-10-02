# Journal de la remise en état du cluster, 1er octobre 2026

Toutes les heures sont celles de Paris. Ce journal est à recopier dans `notes/JOURNAL.md` du dépôt au moment de la prochaine mise à jour du code (étape F).

## La panne du matin

- **6 h 41 :** `unattended-upgrade` met à jour openssl et redémarre `systemd-networkd` sur vms0. Les autres machines suivent, chacune à son heure, de 6 h 55 à 7 h 38.
- **De 6 h 41 à 9 h 37 :** le serveur DHCP de SLICES (10.10.208.2) ne répond pas. Les machines perdent leur adresse.
- **Vers 7 h 24 :** workers1 et workers4 ne reviennent pas. tsdb-mysql-0, le leader de la base, était sur workers4. Il reste bloqué, et une vingtaine de services plantent en boucle.

## Étape A : réparer (fini vers 16 h 20)

- **15 h 45 :** workers1 et workers4 sont redémarrés par l'utilisateur, depuis SLICES. Ils reviennent avec les mêmes adresses, et les 8 nœuds sont Ready.
- **15 h 50 :** tsdb-mysql revient à 3/3, avec **tsdb-mysql-0 toujours leader**. nacosdb-mysql revient à 3/3.
- **15 h 53 :** Nacos est à 3/3. Les services refusent d'abord de s'inscrire (« Nacos cluster is running with 1.X mode »), puis repartent seuls avant 16 h 05.
- **16 h 07 :** l'utilisateur lance `loadgen.sh scale 0`, puis `donnees.sh purger --redemarrer`. Commandes, sièges et recherche sont maintenant **tous sur workers1**.
- **16 h 15 :** l'utilisateur lance `loadgen.sh scale 25`. On lit 6,2 à 7,9 req/s, sans échec. La file reçoit 3,49 msg/s, a 3 consommateurs et un tas à 0.
- **Problème nouveau, jamais vu :** ts-consign-price-service plantait au démarrage (`NonUniqueResultException`). La table `ts.consign_price` avait deux lignes identiques (idx 0). L'utilisateur a supprimé `dc581102-0444-40a2-b659-ea31e62009a3`, et le service est reparti.
- **Problème confirmé (C4 du plan de stabilité) :** le retard de 140 ms ne couvrait plus que r5pwb. Les répliques 44v2p (workers5) et mmndx (workers3), recréées pendant la panne, n'en avaient pas. Chaos Mesh ne choisit ses cibles qu'au moment où la règle est posée : le commentaire de `consommateur.sh` qui dit « les nouveaux pods sont couverts » est faux. À **16 h 19**, l'utilisateur lance `consommateur.sh dimensionner --retard 140` : les 3 répliques portent leurs 140 ms (vérifié pod par pod).
- **Contrôles faits sans problème :**
  - ts-order-service : limites inchangées (2 CPU, 2000Mi) ;
  - prefetch à 1 ;
  - chaos-daemon sur les 8 machines ;
  - NTP synchronisé ;
  - aucune panne Chaos Mesh restée en place.
- **Les agents OTel de workers1 et workers4** ont redémarré 152 et 162 fois, mais seulement pendant la panne. Ils sont stables depuis.

## Étape B : protéger (finie vers 16 h 40)

- **B1, mises à jour automatiques :** les minuteries `apt-daily.timer` et `apt-daily-upgrade.timer` sont coupées (`disable --now`) sur les 9 machines (vérifié). Pour les rallumer : `enable --now`.
- **B2, nouveau noyau en attente :** décision de l'utilisateur, un redémarrage contrôlé, machine par machine, **à l'étape F**.
- **B3, garder son adresse :** le fichier `/etc/netplan/60-garder-adresse.yaml` (`critical: true` sur enp6s18, droits 600) est posé sur les 9 machines, et `netplan get` répond `true` partout. Il prend effet au redémarrage de B2. Il faudra vérifier alors `KeepConfiguration` dans `/run/systemd/network/10-netplan-enp6s18.network`.
- **B4, disque de vms0 :** S3 garde toutes les données brutes (15 463 objets, environ 9 Go compressés, du 09/09 au 30/09, vérifié par une simple liste). Les 144 Go de `graphe_en/runs/*/raw` ne sont que des copies. Décision de l'utilisateur : **les effacer à l'étape F**.
- **B5, Locust :** remis à 0 pendant l'écriture du code, sinon la base se remplit et le service des commandes s'étouffe.

## À reporter

- **Le garde-fou de Claude Code** refuse à l'agent toute écriture sur le cluster, même avec la règle `Bash(ssh vms0:*)`. L'utilisateur tape donc les gestes, et l'agent lit et vérifie.
- **Le placement a changé après la purge avec redémarrage** : commandes, sièges et recherche sont sur workers1. Il faut le fixer avant la collecte.
- **Jaeger ne sert pas au graphe** : aucun fichier de `graphe_en/` ne s'en sert. C'est seulement une visionneuse, qui garde les traces 6 h.

## Étape C : décisions de l'utilisateur (vers 16 h 50)

- **Oui pour les 14 décisions :**
  - C1 : délai d'abandon de Locust à 60 s ;
  - C2 : tas Java de ts-order-service à 1 Go, avec une purge simple entre les blocs ;
  - C3 : niveau 1 du gardien (retirer une panne restée en place, `kill -INT` du pilote) ;
  - C4 : niveau 2 du gardien, seulement entre deux campagnes (Locust, purge), avec une seule tentative par cycle ;
  - C5 : redémarrage de security et preserve si « réserver » reste bloqué, une fois par cycle ;
  - C6 : placement imposé ;
  - C7 : charges du plan du dataset ;
  - C8 : graphes construits sur vms0 seulement ;
  - C9 : Jaeger retiré de la passerelle pendant la collecte ;
  - C10 : limites mémoire de Nacos et RabbitMQ ;
  - C11 : journal binaire de MySQL laissé ;
  - C12 : seuils du plan, revus après T1 ;
  - C13 : alertes dans un fichier sur vms0 ;
  - C14 : le master vérifie que le gardien est vivant.
- **Exigence nouvelle :** pouvoir suivre la collecte à tout moment. Ce sera une session tmux `collecte` sur vms0, à rejoindre en lecture seule (`tmux attach -r -t collecte`), plus une commande `suivi.sh` qui résume l'état en un écran.
- **Constat :** les plans de stabilité et du dataset touchent aux mêmes scripts. Ils sont fusionnés en un plan de travail unique avant tout code.

## Plan de travail unique, et étape E2 (vers 17 h 15)

- **Plan unique :** `Plan_de_travail_unique_2026-10-01.md`, qui fusionne la stabilité et le dataset, en étapes E0 à E26.
- **Constats revérifiés :**
  - Locust contient `--users 25 --autostart` ;
  - Prometheus est à 7,50 Go pour un plafond de 8 Go, avec des mesures depuis le 25/09 à 18:00Z ;
  - `Linger=no` sur vms0 ;
  - le master ne joint pas vms0 par ssh.
- **E2 fait (lecture seule) :** `enregistrements/prometheus_incidents_2026-10-01.jsonl` contient 28 séries sur 3 fenêtres :
  - le gel du 28/09 : le CPU de ts-order-service passe de 0,564 à 0,003 et le dépôt de 3,37 à 0,38 msg/s, entre 06:10 et 06:30Z ;
  - la dérive du 29 au 30/09, **sans les séries de la file**, parce que C2, D2 et C3 sont scellées ;
  - la panne du 1/10.

## Plan court et code K1 (1er octobre, soir)

- **Plan court adopté** (`Plan_court_2026-10-01.md`) : dataset de 7 jours. Graphes construits sur gpu (remplace C8). Le code est modifié par des agents dans `~/zero/chantier`, une copie complète du dépôt.
- **K1.1 à K1.5 faits et testés à blanc** : `collecte.sh`, `consommateur.sh` (verifier, reposer), `donnees.sh` (etat --brut, redemarrer-reservation), `campagne.sh` (plafonds ssh, nettoyage sur signal, `journaux/fins.tsv`, 140 ms et machines contrôlés au départ), `locustfile.py` (délai de 10 s / 60 s).
- **Validé par l'utilisateur** (soir du 1/10) :
  - les 6 points hors spécification de K1.3, K1.4 et K1.5 ;
  - **le niveau 2 passe à `serie.sh`**, pour qu'un seul programme agisse sur l'application ; le gardien mesure, étiquette, alerte et fait seulement le niveau 1 ;
  - le gardien envoie `kill -TERM`, pas `-INT` : un pilote lancé en arrière-plan sans `set -m` ignore SIGINT.
- **Constaté dans l'original de `campagne.sh`** : Ctrl-C tuait aussi `tee`, et le nettoyage mourait (aucun retrait, aucun compte rendu). C'est corrigé dans K1.4.
- **À vérifier sur vms0** : deux fichiers `:USERPROFILE.sshid_rsa(.pub)` à la racine du dépôt. Il faut s'assurer qu'ils ne sont pas suivis par git.
- **9 vieilles sessions tmux inactives** sur vms0 : à fermer à la remise à neuf.
- **Écart de l'agent** : `git log -1` et `git status --short` lancés sur le dépôt de vms0, sans accord.

## 2 octobre : K1.6a, K2.0a, et les réponses sur le gardien

- **K1.6a (le gardien qui mesure) et K2.0a (noms anglais dans la collecte) sont faits.** Tests relancés à la main, un par un, tous verts : collecte, consommateur 32, donnees 23, panne 27, campagne 149, gardien 201.
- **Réponses de l'utilisateur (« ok go ») aux 6 questions du gardien :**
  - dépôt bas : 0,124 msg/s par voyageur sur 3 min, à étalonner sur la référence de K5 ;
  - PROMETHEUS_SHORT_HISTORY (moins de 2 jours gardés) = DOUTEUX ; la métrique existe (6,2 jours le 2/10) ;
  - effondrement = moins de min(5 req/s ; 0,2 × voyageurs), compté sur le palier d'avant la panne ;
  - recherche lente = moyenne de la minute ≥ 15 s ;
  - pas de ControlMaster ssh pour l'instant ;
  - test Locust (a) à stabiliser.
- **À faire avant toute analyse d'une campagne nouvelle (K2.0b) :** l'expression de `graphe_en/ligne_de_base.py:130` s'arrête au trait d'union. Elle lirait « consumer » au lieu de « consumer-slowdown ».
- **Remise à neuf (K4) :** envoyer `panne.sh` et `consommateur.sh` ensemble, sans panne en cours. L'espace vide `voisin` est à effacer (il est remplacé par `fault-neighbors`).
