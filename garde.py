#!/usr/bin/env python3
# ==============================================================================
#  garde.py — le gardien : mesurer la plateforme chaque minute et étiqueter
#  chaque minute OK, MALADE ou DOUTEUX ; avec --agir, les gestes du niveau 1
# ==============================================================================
#
#  CE QUE FAIT CE SCRIPT
#
#  Il tourne sur vms0, dans tmux, à côté du pilote (campagne.sh). Chaque minute
#  UTC :
#    1. il lance UNE commande ssh vers le master, qui exécute apps/garde_sonde.py
#       (une photo de la plateforme en JSON : Prometheus, Locust, nœuds, pods,
#       Chaos Mesh, pannes, leader, passerelle, réglage des 140 ms) ;
#    2. il regarde, ici sur vms0, si le pilote vit, l'âge de son journal, les
#       lignes FIN_CAMPAGNE, la place libre sur le disque ;
#    3. toutes les 5 minutes, il regarde si S3 reçoit encore des objets ;
#    4. il compare tout aux seuils du plan (Stabilite_cluster §5.b), décide
#       l'état de la minute et ses causes (§5.e), et l'écrit ;
#    5. il pose ou efface le drapeau de pause, et, avec --agir seulement, fait
#       les gestes du niveau 1 (plus bas).
#
#  POURQUOI
#
#  Deux pannes déjà vécues sont restées invisibles des heures : un service figé
#  mais « Ready » (3 h 30 le 28/09, D16) et un Locust à un quart de sa charge
#  (L9). Une minute « normale » prise pendant un tel incident fausse le jeu de
#  données sans que personne le sache. La garde le voit, l'écrit minute par
#  minute, et les minutes MALADE sont ensuite exclues des fenêtres normales.
#
#  LES GESTES (K1.6b), ET CE QU'IL NE FAIT JAMAIS
#
#  Sans --agir, la garde ne fait AUCUN geste sur le cluster ni sur le pilote :
#  elle écrit seulement ses propositions (colonnes action_niveau1_proposee et
#  pause_proposee). C'est le mode des essais à la main (K3), où l'on pose des
#  pannes sans pilote : elles ne doivent pas être retirées dans le dos.
#  Avec --agir, elle fait les gestes du niveau 1 accordés (C3, Stabilite_cluster
#  §5.c), et eux seuls :
#    - retirer une panne restée : « bash <GARDE_DISTANT>/apps/panne.sh retirer »
#      sur le master, par ssh (mêmes options que la sonde, plafond LOCAL de
#      2400 s, aucun plafond posé sur le master). Il tourne en arrière-plan (un
#      sous-processus suivi, résultat dans gestes/) : la mesure de chaque minute
#      continue. Un seul à la fois. Limite connue : si le ssh local meurt (plafond
#      de 2400 s atteint, ou lien perdu plus de 60 s : ServerAliveInterval 15 ×
#      ServerAliveCountMax 4), le master ferme les tubes et panne.sh peut mourir
#      à sa ligne suivante (SIGPIPE) : un retrait peut donc être coupé en route
#      de cette façon indirecte, comme pour campagne.sh ; il est alors compté
#      ECHEC (seconde tentative, puis décision humaine).
#      Déclencheurs : FAULT_OVERDUE 2 min mesurées de suite ; CHAOS_UNDECLARED
#      5 min mesurées de suite, sans pilote vivant. FAULT_ORPHANED seul n'en
#      déclenche pas : tant que la durée déclarée n'est pas passée, le minuteur
#      de panne.sh s'en charge ; ensuite il devient FAULT_OVERDUE.
#      Jamais :
#        . sur l'objet de base (consommateur-temps-de-service) ;
#        . si un pilote vivant est dans sa fenêtre déclarée, quel que soit le
#          motif : de DEBUT jusqu'à DEBUT + DUREE + 2 min (panne.etat). Car
#          « panne.sh retirer » ne vise pas un objet : il lève la panne décrite
#          dans panne.etat. Un objet RESTÉ d'une injection d'avant (FAULT_OVERDUE)
#          pendant la fenêtre de la panne suivante ferait lever la panne neuve.
#          Le cas que vise l'exception « sauf FAULT_OVERDUE » (panne.etat
#          lui-même en retard) est, par définition, hors de cette fenêtre ;
#        . pendant qu'un « panne.sh » agit déjà sur le master, ou si la sonde n'a
#          pas pu dire ce qui y agit (gestes_en_cours absent ou en erreur : on
#          attend) ;
#        . pendant le nettoyage d'un pilote qui a reçu TERM.
#      Une tentative par incident ; si la panne est encore là, UNE seconde, 10
#      min au plus tôt après la fin de la première ; ensuite plus rien, et
#      l'alerte « DÉCISION HUMAINE NÉCESSAIRE » (niveau 3). Plafond global en
#      plus : au plus 4 retraits lancés en 6 h, tous incidents confondus (un
#      objet recréé sans cesse ouvrirait sinon un incident après l'autre).
#      Risque connu, non couvert : le retrait est décidé sur la photo de la
#      sonde (jusqu'à environ 50 s d'âge). Si le pilote lance son propre
#      « panne.sh » dans cet intervalle, deux panne.sh tournent ensemble sur le
#      master (panne.sh n'a pas de verrou). C'est rare, et ses gestes sont
#      presque tous sans effet la seconde fois (delete --ignore-not-found).
#    - arrêter un pilote effondré : kill -TERM (pas -INT : un pilote lancé en
#      arrière-plan sans set -m ignore SIGINT) au SEUL processus campagne.sh
#      racine (jamais tee, tmux, serie.sh ; sous « timeout », le bash qu'il
#      enveloppe), dès que la proposition term:<motif> paraît, c'est-à-dire
#      après un effondrement de 10 min (11 minutes MESURÉES de suite : la
#      première et 10 de plus ; une minute non mesurée remet la série à zéro)
#      pendant une campagne. Choix de cette version, d'après l'accord C3 et
#      §5.c (« effondrement de plus de 10 min ») : la proposition porte déjà ces
#      10 min, le geste ne les attend pas une seconde fois (ce qui ferait 20).
#      Juste avant, le pid est relu : toujours un campagne.sh, même nom de
#      campagne, même date de démarrage (/proc/<pid>/stat, champ starttime),
#      sinon rien ; le signal passe par un pidfd ouvert AVANT la relecture
#      (aucun pid réutilisé entre la relecture et le signal). Une seule fois
#      par pilote. campagne.sh retire alors sa panne, revient au premier
#      palier, écrit son compte rendu et sa ligne FIN. S'il vit encore 45 min
#      après : « DÉCISION HUMAINE NÉCESSAIRE ». JAMAIS de kill -9.
#  Avec ou sans --agir (niveau 0, rien ne touche le cluster) : le drapeau de
#  pause (fichier « pause », plus bas), posé quand pause_proposee=1, effacé
#  quand la condition a disparu 2 minutes de suite (mesurées).
#  Jamais : le niveau 2 (Locust, purge, security/preserve : c'est serie.sh qui
#  le fait), ni rien du niveau 3. La cause d'une panne est lue comme un texte
#  opaque : aucune règle ne dépend de son nom.
#
#  LES FICHIERS (dans GARDE_DOSSIER, hors du dépôt)
#
#    garde.tsv         une ligne par minute UTC, colonnes fixes (plus bas).
#                      Une minute sans mesure (sonde trop lente, garde arrêtée)
#                      est écrite au retour : MALADE, cause MEASURE_GAP.
#    alertes.txt       une ligne lisible quand une cause APPARAÎT (DEBUT) et
#                      quand elle DISPARAÎT (FIN), avec l'heure UTC et le niveau
#                      (MALADE, DOUTEUX, NOTE) ; aussi les propositions (qui
#                      disent si la garde agit : [AGIR] ou [PROPOSE], et en
#                      mode AGIR pourquoi aucun geste ne suit, le cas échéant),
#                      les gestes et le drapeau (lignes ACTION DEBUT, ACTION FIN,
#                      ACTION REFUS, ACTION MAJ), les alertes « NIVEAU 3 —
#                      DÉCISION HUMAINE NÉCESSAIRE », et chaque nouvelle ligne
#                      FIN_CAMPAGNE (INFO). Une cause qu'on n'a pas pu mesurer
#                      cette minute (ssh, sonde ou sa requête en échec) reste
#                      ouverte : pas de FIN pour un problème simplement non vu
#                      (sauf quand la mémoire est remise à neuf : FIN « fermée
#                      sans mesure », voir memoire.json).
#    dernier.json      la dernière mesure brute et l'état (pour suivi.sh),
#                      écrit d'un coup (fichier temporaire puis renommage).
#    memoire.json      ce dont la minute suivante a besoin (contamination,
#                      compteurs précédents…), pour survivre à un redémarrage ;
#                      aussi le mode (clé « mode » : agir ou propose), écrit à
#                      chaque départ (suivi.py le lit quand dernier.json manque).
#                      S'il fait échouer 3 minutes de suite, il est mis de côté
#                      (memoire.json.<date>.casse) et la garde repart à neuf,
#                      en gardant le mode. En repartant d'une mémoire neuve
#                      (celle-là, ou un memoire.json absent ou illisible au
#                      départ), chaque alerte encore ouverte (dans la mémoire
#                      perdue ou dans alertes.txt) reçoit sa ligne FIN (« fermée
#                      sans mesure ») : sinon elle resterait ouverte pour
#                      toujours. Elle repart d'un DEBUT si elle est encore vraie.
#    reference.json    le leader MySQL et les adresses des nœuds notés à la
#                      première mesure ; un changement est une cause. Effacer
#                      ce fichier pour noter une nouvelle référence.
#    garde.verrou      une seule garde à la fois (flock), pris AVANT toute écriture.
#    actions.tsv       une ligne par geste et par changement du drapeau de pause :
#                      instant  geste  motif  cible  resultat  duree_s
#                      Les résultats, geste par geste :
#                        retirer  lance              retrait parti (= « retirer:en_cours »
#                                                    dans garde.tsv)
#                                 ok                 panne.sh a rendu 0
#                                 ECHEC:<détail>     autre code, ssh en échec, plafond local
#                                 refuse:<raison>    pas lancé (objet de base, pilote dans
#                                                    sa fenêtre, panne.sh qui agit…)
#                                 decision_humaine   plus aucun retrait pour cet incident
#                        term     envoye             SIGTERM envoyé au pilote
#                                 refuse:<raison>    pas envoyé (pid réutilisé, retrait en cours…)
#                                 pilote_arrete      le pilote s'est arrêté après TERM
#                                 toujours_vivant:decision_humaine   45 min après TERM
#                        pause    posee | motifs (les motifs ont changé) | effacee
#                      duree_s n'est rempli qu'à la fin d'un geste (ok, ECHEC,
#                      pilote_arrete, toujours_vivant).
#    gestes/           pour chaque retrait : retirer-<AAAAMMJJTHHMMSSZ>-<tentative>.log
#                      (la sortie de panne.sh) et retirer-<AAAAMMJJTHHMMSSZ>-<tentative>.json
#                      (le résultat, écrit à la fin par le sous-processus).
#    pause             LE DRAPEAU DE PAUSE, lu par serie.sh (K2.5) avant de lancer
#                      une campagne : présent = ne rien lancer. Écrit d'un coup
#                      (temporaire puis renommage), lignes CLE=valeur :
#                          POSE_PAR=garde
#                          DEPUIS=<instant UTC où il a été posé>
#                          INSTANT=<instant UTC de la dernière mise à jour (chaque minute)>
#                          MOTIFS=<codes séparés par des virgules, ex. ORDERS_HIGH>
#                          VALEURS=<dernières valeurs, ex. commandes=7123>
#                      Effacé quand la condition a disparu 2 minutes mesurées de
#                      suite. Un fichier sans POSE_PAR=garde (posé à la main)
#                      n'est jamais effacé par la garde.
#                      Pour serie.sh : fichier présent = pause, quel que soit son
#                      contenu (posé à la main compris). Si la garde est arrêtée,
#                      le drapeau reste (INSTANT ne bouge plus) : seul un humain
#                      l'efface.
#
#  LES COLONNES DE garde.tsv (dans cet ordre ; vide = inconnu ou sans objet)
#
#    minute                  minute UTC mesurée (AAAA-MM-JJTHH:MMZ)
#    etat                    OK, MALADE ou DOUTEUX
#    causes                  codes qui font l'état, séparés par des virgules ; vide si OK
#    notes                   codes notés SANS changer l'état : baisses pendant une panne,
#                            codes pas encore confirmés, alertes (6 000 commandes)…
#    en_panne                1 si une panne est déclarée : panne.etat présent sur le master,
#                            ou un objet Chaos Mesh autre que le réglage de base ; sinon 0
#    panne_declaree          la cause écrite dans panne.etat (texte opaque), sinon les objets
#    pilote                  campagne.sh vivant sur vms0 : <nom>(<pid>) ; vide sinon
#    voyageurs_demandes      dernier palier de journaux/paliers.tsv (une panne de charge,
#                            plus de voyageurs, y écrit aussi sa demande : origine « panne »)
#    voyageurs_reels         voyageurs que Locust fait tourner (0 si Locust est à 0 réplique)
#    req_s                   débit de Locust sur la minute (variation du total « Aggregated »
#                            entre deux minutes) ; à défaut (première minute, Locust remis
#                            à zéro), sa propre moyenne sur 10 s
#    req_s_min               le seuil : 0,8 × 0,30 × voyageurs demandés
#    echecs_pct              part d'échecs du pire parcours (hors code et connexion)
#    recherche_ms            temps moyen de « 10 chercher un train » sur la minute
#                            (à défaut, sa médiane depuis le départ de Locust)
#    reservations_min        réservations réussies (« 30 réserver un billet ») par minute
#    depot                   msg/s déposés dans food_delivery (sur 2 min)
#    retrait                 msg/s retirés (déduits : dépôt − variation du tas)
#    tas                     messages dans la file : prêts + non acquittés
#    consommateurs           consommateurs de food_delivery
#    cpu_commandes           cœurs de ts-order-service (sur 2 min)
#    reseau_commandes_ko_s   ko/s reçus par ts-order-service
#    commandes               lignes de la table orders (lue toutes les 10 min)
#    commandes_age_min       âge de cette lecture
#    reglage_140ms           ok, manque:<n>/<répliques>, panne (remplacé par la panne), ?
#    leader                  la copie MySQL leader (role=leader et derrière le service)
#    noeuds_prets            nœuds Ready / nœuds connus
#    jaeger_mi               mémoire de Jaeger (Mi)
#    prometheus_jours        jours d'historique gardés par Prometheus (plus vieille mesure)
#    s3_age_s                âge du dernier objet S3 à la dernière vérification
#    vms0_libre_go           place libre sur le disque de vms0 (Go)
#    action_niveau1_proposee vide, « retirer:<motif>[:<objet>] » ou « term:<motif> »
#    action_niveau1_faite    ce que la garde a fait cette minute (--agir) : vide,
#                            « retirer:en_cours », « retirer:ok », « retirer:ECHEC »,
#                            « term:envoye » (plusieurs : séparés par des virgules)
#    pause_proposee          0 ou 1 (le drapeau « pause » est alors posé)
#    pause_motif             pourquoi
#    duree_sonde_s           durée de la mesure sur le master
#
#  LES CODES DE CAUSES (état → sens → seuil → source dans Stabilite_cluster)
#
#  La référence est le dictionnaire CODES plus bas : ce tableau doit suivre ses
#  changements (le test vérifie que chaque code y est décrit).
#  N = voyageurs demandés. Deux marques :
#    (d) un code de DÉBIT : pendant une panne déclarée, ou juste après un
#        changement de palier (3 min, ou Locust en train d'ajouter ou de retirer
#        des voyageurs), il passe dans « notes » au lieu de rendre la minute MALADE ;
#    (t) un code de TAS : pendant une panne, et encore 25 min après sa fin, noté.
#  Un redémarrage, un gel, un leader, un nœud… pendant une panne restent MALADE
#  (l'injection est invalide). Sous 5 voyageurs, les seuils de débit ne
#  s'appliquent pas (le bruit domine). « k min de suite » : avant la k-ième
#  minute, le code est seulement noté (une seule mesure peut être un hasard).
#
#  MALADE (la minute est exclue des fenêtres normales)
#    MEASURE_FAILED:<quoi>  une mesure impossible (ssh, sonde, prom_<requête>,
#                           locust, noeuds, pods, chaos, leader, s3, commandes,
#                           verifier, garde…) → toute erreur ou réponse vide → §5.b, §5.e, N2
#    MEASURE_GAP            minute sans mesure dans garde.tsv → toute → §5.e
#    RECOVERING             contamination après une minute MALADE → jusqu'à 5 min de
#                           suite en régime (file sans message prêt, req/s ≥ 80 %) → §5.e
#    LOCUST_USERS           voyageurs réels ≠ palier demandé, 2 min de suite → L16, L18
#    LOCUST_RATE_LOW   (d)  débit de Locust sur la minute → < 0,8 × 0,30 × N req/s → L9
#    LOCUST_ERRORS     (d)  échecs d'un parcours → > 5 % → JOURNAL 1367-1370
#    SEARCH_SLOW            « chercher un train » trop lent → moyenne sur la minute
#                           ≥ 15 000 ms (au moins la moitié des recherches à 30 s), ou
#                           médiane ≥ 30 000 ms sans minute précédente → D1, D11
#    BOOKING_STUCK     (d)  aucune réservation réussie sur la minute → 0 à ≥ 10 voyageurs
#                           → D8 (ajout de cette version)
#    PUBLISH_LOW       (d)  dépôt trop bas → < 0,124 × N msg/s (3,1 à 25), 3 min de suite
#                           → L7, L12
#    PUBLISH_FROZEN    (d)  gel probable → < 0,04 × N msg/s (1 à 25) → D16
#    DRAIN_LAG         (t)  le retrait ne suit pas → dépôt − retrait > 0,1 msg/s
#                           pendant 10 min de suite → R2
#    QUEUE_BACKLOG     (t)  tas de la file → > 10 → rapport.md:298-305
#    CONSUMERS              consommateurs de food_delivery → ≠ 3 → R3
#    BASE_DELAY_MISSING     une réplique en marche sans les 140 ms → C3, C4
#    ORDERS_MAX             commandes en table → ≥ 8 000 → D5
#    ORDER_CPU_HIGH         CPU de ts-order-service → > 1,2 cœur (+ pause) → D3, L12, L13
#    ORDER_FROZEN           ts-order-service gelé → CPU < 0,02 cœur ou réseau < 1 ko/s
#                           alors que Locust tourne (≥ 5 voyageurs) → D16
#    POD_RESTART            un redémarrage de plus (train-ticket, loadgen, passerelle) → JOURNAL 1376
#    KEY_POD_NOT_READY      order, travel, seat, preserve ou security sans pod prêt → D8, D10
#    LEADER_CHANGED         leader ≠ celui de reference.json → M4, M5
#    LEADER_LOST            aucun leader cohérent → M5
#    MYSQL_MEMORY_HIGH      tsdb-mysql-0 → > 950 Mi → M9
#    NODE_NOT_READY         un nœud ≠ Ready (ou disparu) → N3, N7
#    NODE_MEMORY_LOW        MemAvailable d'un nœud → < 500 Mi → N4
#    NODE_IP_CHANGED        adresse d'un nœud ≠ reference.json → N2
#    NODE_DISK_FULL         disque / d'un nœud → > 80 % → V18
#    VMS0_DISK_LOW          disque de vms0 → < 20 Go libres → V18
#    GATEWAY_DOWN           passerelle ≠ prête pendant une campagne → O7
#    S3_STALE               aucun objet S3 neuf, passerelle prête depuis 2 min au moins
#                           → > 2 min → O6
#    FAULT_OVERDUE          objet Chaos Mesh présent plus que sa durée + 2 min, ou panne.etat
#                           plus vieux que DEBUT + DUREE + 2 min → P5, P9, P10. Pour
#                           panne.etat seul, pendant qu'un « panne.sh » agit sur le
#                           master (le retrait du pilote, qui peut durer 10 min), le
#                           code est seulement noté (choix de cette version)
#    FAULT_ORPHANED         panne.etat présent sans pilote vivant → P9
#    CHAOS_UNDECLARED       objet Chaos Mesh sans panne.etat (hors fenêtre déclarée) → §5.b
#    CHAOS_RESIDUE          retard posé par un objet qui n'existe plus, 2 min de suite → P10
#    PILOT_SILENT           pilote vivant, journal muet → > 15 min → V11, V12
#  DOUTEUX (la minute est gardée, mais marquée)
#    JAEGER_MEMORY          mémoire de Jaeger → > 1,8 Gi → O3
#    JAEGER_RESTART         Jaeger a redémarré (OOM probable) → O3
#    PROMETHEUS_SHORT_HISTORY  Prometheus garde moins de 2 jours d'historique : les
#                           mesures de la minute risquent d'être effacées avant d'être
#                           relevées → O10 (au plafond de 8 GiB par construction, c'est
#                           la durée gardée qui compte ; choix de cette version)
#    VERIFIER_UNAVAILABLE   consommateur.sh verifier ne répond ni 0, ni 1, ni 3 (ancienne
#                           version : « Usage », code 2) ; la garde lit alors elle-même
#                           le retard posé (podnetworkchaos) → C4
#  NOTES (écrites dans « notes », sans effet sur l'état ; seules ORDERS_WARN et
#  ORDERS_HIGH ont aussi une ligne dans alertes.txt)
#    ORDERS_WARN ≥ 6 000 commandes (D5) ; ORDERS_HIGH ≥ 7 000 (+ pause, §5.d) ;
#    ORDER_CPU_WARN > 0,45 cœur (D3) ; LOCUST_RAMPING (Locust ajoute ou retire des
#    voyageurs) ; PALIER_SETTLING (palier récent : débit seulement noté) ;
#    GATEWAY_NOT_READY (hors campagne) ; OBS_RESTART (autre pod d'observability) ;
#    BASE_DELAY_REPLACED (verifier rend 3 : la panne en cours remplace le réglage) ;
#    PROMETHEUS_HISTORY_UNREAD (l'historique de Prometheus n'a pas pu être lu).
#    Un code MALADE pas encore confirmé (LOCUST_USERS, PUBLISH_LOW, CHAOS_RESIDUE)
#    est aussi écrit ici, avec « 1/2 », « 2/3 »… dans dernier.json.
#
#  LES PROPOSITIONS (écrites avec ou sans --agir ; les gestes, plus haut)
#    retirer:<code>[:<objet>]  FAULT_OVERDUE, FAULT_ORPHANED ou CHAOS_UNDECLARED, et aucun
#                              « panne.sh » en train d'agir sur le master ; <objet> est
#                              celui qui a déclenché le code (Type/nom, ou panne.etat)
#    term:<motif>              pendant une campagne, effondrement depuis 10 min ou plus
#                              (11 minutes mesurées de suite) :
#                              LOCUST_COLLAPSE (Locust < min(5 req/s ; 0,2 × N)), ORDER_FROZEN,
#                              ou NODE_NOT_READY. N = voyageurs demandés du palier d'AVANT
#                              le début de la panne déclarée (DEBUT de panne.etat, lu dans
#                              paliers.tsv : une panne de charge y écrit sa propre demande),
#                              sinon le palier courant
#    pause_proposee=1          commandes ≥ 7 000, ou CPU de ts-order-service > 1,2 cœur
#
#  Usage (sur vms0, dans tmux ; la session viendra en K1.6c) :
#      python3 garde.py                 la boucle, une mesure par minute UTC, sans geste
#      python3 garde.py --agir          la boucle, AVEC les gestes du niveau 1 : à utiliser
#                                       pendant les campagnes de collecte, jamais pendant
#                                       les essais à la main (K3)
#      python3 garde.py --une-fois      une seule minute (essai, débogage) ; se combine
#                                       avec --agir
#      options : --dossier <d>   (défaut : GARDE_DOSSIER)
#                --sans-s3       ne lit pas S3
#                --tours <n>     s'arrête après n minutes (essais)
#      interne : --geste-retirer <json>  le sous-processus d'un retrait (visible dans
#                ps pendant un retrait) ; ne pas lancer à la main
#  Le mode (AGIR ou PROPOSE) est dit au départ, et dans alertes.txt quand il
#  change. Pour l'arrêter : Ctrl-C dans sa fenêtre tmux, ou « kill -TERM <pid> ».
#  La minute en cours est finie et écrite ; un retrait en cours n'est PAS coupé
#  (il tourne dans sa propre session) et sera suivi au prochain départ ; les
#  minutes manquées pendant l'arrêt seront écrites MEASURE_GAP.
#
#  Variables reconnues :
#      GARDE_SSH        (défaut: master)                   l'hôte de la sonde
#      GARDE_DISTANT    (défaut: /home/ubuntu/autodeploy)  le dépôt déployé sur le master
#      GARDE_DOSSIER    (défaut: ~/journaux-hors-campagne/garde)
#      GARDE_DEPOT      (défaut: ~/autodeploy_k8s-plateforme)   le dépôt sur vms0
#      GARDE_PYTHON_S3  (défaut: <dépôt>/graphe_en/.venv/bin/python)  python avec boto3
#      GARDE_S3_CONFIG  (défaut: <dépôt>/graphe_en/config.yaml)  le secret n'est jamais
#                       lu par ce script : seul le petit sous-processus S3 l'ouvre
#      GARDE_PLAFOND_SSH (défaut: 50)  secondes au plus pour la sonde, ssh compris
#      GARDE_VMS0_LIBRE_MIN_GO (défaut: 20)  seuil de VMS0_DISK_LOW (essais)
#      GARDE_MAINTENANT  (essais seulement) l'heure de la garde, AAAA-MM-JJTHH:MM:SSZ
#      GARDE_PROC        (défaut: /proc)  où chercher le pilote (essais : un dossier
#                       qui imite /proc, avec les seuls processus du test)
#      GARDE_PLAFOND_GESTE (défaut: 2400)  secondes au plus pour un retrait, ssh compris
# ==============================================================================
import fcntl
import glob
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone

# Ne rien exécuter au chargement : suivi.py importe ce fichier (trouver_pilotes).
# Ici, seulement des constantes, des fonctions et des classes ; main() n'est
# appelé que sous « if __name__ == "__main__" ».

# ------------------------------------------------------------------------------
# Les seuils (Stabilite_cluster §5.b ; décision C12 : les valeurs du plan,
# revues après l'essai de 24 h)
# ------------------------------------------------------------------------------
REQ_S_PAR_VOYAGEUR = 0.30          # §5.b, L9 : référence 7,0-7,8 req/s à 25 voyageurs
PART_DEBIT_MIN = 0.80              # §5.b : malade sous 80 % de l'attendu
EFFONDREMENT_REQ_S = 5.0           # §5.b (ligne « pendant une panne ») et c3-chaine.sh:41
EFFONDREMENT_REQ_S_PAR_VOYAGEUR = 0.20   # sous 25 voyageurs, 5 req/s serait au-dessus de la
                                   # normale (3 req/s attendus à 10) : le seuil devient 0,2 × N
ECHECS_MAX_PCT = 5.0               # §5.b, JOURNAL.md:1367-1370
RECHERCHE_P50_MAX_MS = 30000       # §5.b : p50 ≥ 30 000 ms (D1, D11) ; pour la médiane
RECHERCHE_MOYENNE_MAX_MS = 15000   # même règle pour la MOYENNE sur la minute (Locust ne donne
                                   # pas de médiane par minute) : les réponses plafonnent à 30 s
                                   # (Hikari), donc une moyenne ≥ 15 s = au moins la moitié à 30 s
DEPOT_MIN_PAR_VOYAGEUR = 0.124     # §5.b : 3,1 msg/s à 25 voyageurs = 3,3 mesurés (0,132 par
                                   # voyageur, JOURNAL.md:461-474) − 6 %. Attention : L7 dit
                                   # « environ 0,12 », qui serait SOUS ce seuil (à revoir à 24 h)
DEPOT_BAS_MINUTES = 3              # choix de cette version : PUBLISH_LOW sur 3 min de suite
                                   # (les fenêtres de 2 min se chevauchent ; le bruit de tirage
                                   # des parcours vaut environ 0,1 msg/s)
DEPOT_GEL_PAR_VOYAGEUR = 0.04      # §5.b : < 1 msg/s à 25 = gel probable (D16)
ECART_RETRAIT_MAX = 0.1            # §5.b : msg/s
ECART_RETRAIT_MINUTES = 10         # §5.b [10]
TAS_MAX = 10                       # §5.b, rapport.md:298-305
TAS_APRES_PANNE_MIN = 25           # §5.b : le tas compte 25 min après un retrait
CONSOMMATEURS = 3                  # R3
RETARD_BASE = "140ms"              # consommateur.sh, PANNE_REGLAGE_ATTENDU
REGLAGE_SOURCE = "train-ticket/consommateur-temps-de-service"   # consommateur.sh, OBJET
REGLAGE_NOM = REGLAGE_SOURCE.split("/", 1)[1]   # l'objet de base : jamais retiré par la garde
COMMANDES_ALERTE, COMMANDES_PAUSE, COMMANDES_MALADE = 6000, 7000, 8000   # D5, §5.b, §5.d
CPU_ALERTE, CPU_MALADE = 0.45, 1.2     # D3, L12, L13 (limite 2 cœurs)
CPU_GEL = 0.02                     # D16
RESEAU_GEL_OCTETS_S = 1000         # D16 : 4,4 Mo/s tombés à ~100 o/s
JAEGER_MAX = 1.8 * 2**30           # O3 (limite 2 Gi)
MYSQL_MAX = 950 * 2**20            # M9 (limite 1 Gi)
NOEUD_MEMOIRE_MIN = 500 * 2**20    # N4
NOEUD_DISQUE_MAX_PCT = 80.0        # V18
VMS0_LIBRE_MIN_GO = float(os.environ.get("GARDE_VMS0_LIBRE_MIN_GO", "20"))   # V18 (20 Go par
                                   # graphe, apres-campagne.sh:250-253) ; variable pour les essais
S3_AGE_MAX_S = 120                 # O6
S3_TOUTES_LES_MIN = 5              # plan K1.6
S3_APRES_PASSERELLE_MIN = 2        # S3 n'est jugé que 2 min après que la passerelle est prête
                                   # (marge de collecte.sh fenetre : 2 min)
PANNE_MARGE_MIN = 2                # P5, P9, P10 : durée + 2 min
PILOTE_SILENCE_MIN = 15            # §5.b [15] : le pilote écrit une veille toutes les 10 min
EFFONDREMENT_MIN = 10              # §5.c [10]
REGIME_MINUTES = 5                 # §5.e [5]
PROMETHEUS_JOURS_MIN = 2.0         # O10 : au plafond de taille, c'est la durée gardée qui compte
                                   # (5,8 jours le 1/10) ; choix de cette version
COMMANDES_TOUTES_LES_MIN = 10      # §5.b : donnees.sh etat, toutes les 10 min
# Choix de cette version, absents du tableau §5.b (à revoir après l'essai de 24 h) :
VOYAGEURS_MIN_DEBIT = 5            # sous 5 voyageurs, pas de seuil de débit ni de gel
GRACE_PALIER_MIN = 3               # après un changement de palier, débit seulement noté
CONFIRMATION_MIN = 2               # LOCUST_USERS et CHAOS_RESIDUE : 2 min de suite
RESERVATIONS_VOYAGEURS_MIN = 10    # BOOKING_STUCK seulement à 10 voyageurs ou plus
ECHECS_REQUETES_MIN = 5            # un parcours n'est jugé que sur 5 requêtes ou plus
REDEMARRAGES_OUBLI_MIN = 60        # un compteur de redémarrages non revu depuis 60 min est oublié
CLES = ("order", "travel", "seat", "preserve", "security")   # §5.b, D8, D10
# Les gestes (K1.6b, accord C3 ; Stabilite_cluster §5.c) :
RETRAIT_CONFIRMATION_MIN = {"FAULT_OVERDUE": 2, "CHAOS_UNDECLARED": 5}   # minutes de suite
RETRAIT_CODES = ("FAULT_OVERDUE", "FAULT_ORPHANED", "CHAOS_UNDECLARED")   # l'incident « panne restée »
RETRAIT_TENTATIVES = 2             # une tentative, puis UNE seconde
RETRAIT_SECONDE_APRES_MIN = 10     # la seconde : 10 min au plus tôt après la fin de la première
RETRAIT_PLAFOND_GLOBAL = 4         # au plus 4 retraits lancés…
RETRAIT_PLAFOND_FENETRE_H = 6      # … en 6 h, tous incidents confondus (choix de cette version)
PLAFOND_GESTE = float(os.environ.get("GARDE_PLAFOND_GESTE", "2400"))   # comme PLAFOND_RETIRER
                                   # de campagne.sh : un retrait peut attendre 40 min
TERM_HUMAIN_APRES_MIN = 45         # pilote encore vivant 45 min après TERM : décision humaine
                                   # (son nettoyage peut durer 2400 s de retrait)
PAUSE_EFFACER_APRES_MIN = 2        # drapeau effacé après 2 min mesurées sans la condition
PAUSE_VALEURS = {"ORDERS_MAX": "commandes", "ORDERS_HIGH": "commandes",
                 "ORDER_CPU_HIGH": "cpu_commandes"}   # motif → colonne recopiée dans le drapeau

# ------------------------------------------------------------------------------
# Les codes : niveau, classe (d = débit, t = tas), sens (pour alertes.txt)
# ------------------------------------------------------------------------------
MALADE, DOUTEUX, NOTE = "MALADE", "DOUTEUX", "NOTE"
CODES = {
    "MEASURE_FAILED": (MALADE, "", "mesure impossible"),
    "MEASURE_GAP": (MALADE, "", "minute sans mesure"),
    "RECOVERING": (MALADE, "", "retour au régime pas encore atteint"),
    "LOCUST_USERS": (MALADE, "", "voyageurs de Locust différents du palier demandé"),
    "LOCUST_RATE_LOW": (MALADE, "d", "débit de Locust trop bas"),
    "LOCUST_ERRORS": (MALADE, "d", "trop d'échecs sur un parcours"),
    "SEARCH_SLOW": (MALADE, "", "« chercher un train » trop lent"),
    "BOOKING_STUCK": (MALADE, "d", "aucune réservation réussie"),
    "PUBLISH_LOW": (MALADE, "d", "dépôt dans la file trop bas"),
    "PUBLISH_FROZEN": (MALADE, "d", "dépôt presque nul : gel probable"),
    "DRAIN_LAG": (MALADE, "t", "le retrait ne suit pas le dépôt depuis 10 min"),
    "QUEUE_BACKLOG": (MALADE, "t", "la file s'accumule"),
    "CONSUMERS": (MALADE, "", "nombre de consommateurs de food_delivery anormal"),
    "BASE_DELAY_MISSING": (MALADE, "", "réglage de 140 ms absent sur une réplique"),
    "ORDERS_MAX": (MALADE, "", "trop de commandes en table"),
    "ORDER_CPU_HIGH": (MALADE, "", "CPU de ts-order-service trop haut"),
    "ORDER_FROZEN": (MALADE, "", "ts-order-service gelé alors que Locust tourne"),
    "POD_RESTART": (MALADE, "", "un pod a redémarré"),
    "KEY_POD_NOT_READY": (MALADE, "", "un service clé n'a aucun pod prêt"),
    "LEADER_CHANGED": (MALADE, "", "le leader MySQL a changé"),
    "LEADER_LOST": (MALADE, "", "aucun leader MySQL"),
    "MYSQL_MEMORY_HIGH": (MALADE, "", "mémoire de tsdb-mysql-0 trop haute"),
    "NODE_NOT_READY": (MALADE, "", "un nœud n'est pas Ready"),
    "NODE_MEMORY_LOW": (MALADE, "", "un nœud manque de mémoire"),
    "NODE_IP_CHANGED": (MALADE, "", "l'adresse d'un nœud a changé"),
    "NODE_DISK_FULL": (MALADE, "", "le disque d'un nœud est trop plein"),
    "VMS0_DISK_LOW": (MALADE, "", "le disque de vms0 est trop plein"),
    "GATEWAY_DOWN": (MALADE, "", "passerelle de collecte pas prête pendant une campagne"),
    "S3_STALE": (MALADE, "", "aucun objet neuf dans S3"),
    "FAULT_OVERDUE": (MALADE, "", "objet de panne resté au-delà de sa durée + 2 min"),
    "FAULT_ORPHANED": (MALADE, "", "panne.etat présent sans pilote vivant"),
    "CHAOS_UNDECLARED": (MALADE, "", "objet Chaos Mesh sans panne déclarée"),
    "CHAOS_RESIDUE": (MALADE, "", "retard posé par un objet Chaos Mesh disparu"),
    "PILOT_SILENT": (MALADE, "", "le journal du pilote ne bouge plus"),
    "JAEGER_MEMORY": (DOUTEUX, "", "mémoire de Jaeger trop haute"),
    "JAEGER_RESTART": (DOUTEUX, "", "Jaeger a redémarré"),
    "PROMETHEUS_SHORT_HISTORY": (DOUTEUX, "", "Prometheus garde trop peu d'historique"),
    "VERIFIER_UNAVAILABLE": (DOUTEUX, "", "réglage des 140 ms non vérifiable par consommateur.sh"),
    "ORDERS_WARN": (NOTE, "", "commandes en table : seuil d'alerte"),
    "ORDERS_HIGH": (NOTE, "", "commandes en table : plus de nouvelle injection"),
    "ORDER_CPU_WARN": (NOTE, "", "CPU de ts-order-service au-dessus de l'alerte"),
    "LOCUST_RAMPING": (NOTE, "", "Locust change de nombre de voyageurs"),
    "PALIER_SETTLING": (NOTE, "", "palier récent : débit seulement noté"),
    "GATEWAY_NOT_READY": (NOTE, "", "passerelle pas prête (hors campagne)"),
    "OBS_RESTART": (NOTE, "", "un pod d'observability a redémarré"),
    "BASE_DELAY_REPLACED": (NOTE, "", "la panne en cours remplace le réglage de 140 ms"),
    "PROMETHEUS_HISTORY_UNREAD": (NOTE, "", "historique de Prometheus illisible"),
}
# Les notes qui méritent une ligne dans alertes.txt (les autres restent dans garde.tsv).
NOTES_ALERTEES = {"ORDERS_WARN", "ORDERS_HIGH"}

# Les mesures dont dépend chaque code (les <quoi> de MEASURE_FAILED:<quoi>). Si
# l'une d'elles a échoué cette minute, le code n'a pas été VU, il n'est pas FINI :
# alertes.txt n'écrit pas de FIN. Un code absent de ce tableau ne dépend que de
# la sonde entière (ssh, sonde).
SOURCES = {
    "LOCUST_USERS": ("locust", "paliers"), "LOCUST_RATE_LOW": ("locust", "paliers"),
    "LOCUST_ERRORS": ("locust",), "SEARCH_SLOW": ("locust",), "BOOKING_STUCK": ("locust",),
    "PUBLISH_LOW": ("prom_depot", "paliers"), "PUBLISH_FROZEN": ("prom_depot", "paliers"),
    "DRAIN_LAG": ("prom_depot", "prom_retrait"),
    "QUEUE_BACKLOG": ("prom_tas_pret", "prom_tas_non_acquitte"),
    "CONSUMERS": ("prom_consommateurs",),
    "BASE_DELAY_MISSING": ("verifier", "podnetworkchaos", "pods"),
    "VERIFIER_UNAVAILABLE": ("verifier",), "BASE_DELAY_REPLACED": ("verifier",),
    "ORDERS_MAX": ("commandes",), "ORDERS_HIGH": ("commandes",), "ORDERS_WARN": ("commandes",),
    "ORDER_CPU_HIGH": ("prom_cpu_commandes",), "ORDER_CPU_WARN": ("prom_cpu_commandes",),
    "ORDER_FROZEN": ("prom_cpu_commandes", "prom_reseau_commandes", "locust"),
    "POD_RESTART": ("prom_redemarrages", "pods"), "JAEGER_RESTART": ("prom_redemarrages",),
    "OBS_RESTART": ("prom_redemarrages",), "KEY_POD_NOT_READY": ("pods",),
    "LEADER_CHANGED": ("leader",), "LEADER_LOST": ("leader",),
    "MYSQL_MEMORY_HIGH": ("prom_memoire_pods",), "JAEGER_MEMORY": ("prom_memoire_pods",),
    "NODE_NOT_READY": ("noeuds",), "NODE_IP_CHANGED": ("noeuds",),
    "NODE_MEMORY_LOW": ("prom_memoire_noeuds",), "NODE_DISK_FULL": ("prom_disque_utilise_pct",),
    "VMS0_DISK_LOW": ("vms0_disque",), "GATEWAY_DOWN": ("passerelle",),
    "GATEWAY_NOT_READY": ("passerelle",), "S3_STALE": ("s3", "passerelle"),
    "FAULT_OVERDUE": ("chaos",), "CHAOS_UNDECLARED": ("chaos", "panne_etat"),
    "FAULT_ORPHANED": ("panne_etat",), "CHAOS_RESIDUE": ("chaos", "podnetworkchaos"),
    "PROMETHEUS_SHORT_HISTORY": ("prom_historique_prometheus",),
}
# Les codes mesurés sur vms0 : ils restent jugés même quand le master est muet.
CODES_LOCAUX = {"VMS0_DISK_LOW", "PILOT_SILENT", "MEASURE_FAILED:vms0_disque"}
# Les échecs qui rendent TOUTE la mesure du master invisible.
AVEUGLES = {"MEASURE_FAILED:ssh", "MEASURE_FAILED:sonde", "MEASURE_FAILED:garde", "MEASURE_GAP"}

COLONNES = ["minute", "etat", "causes", "notes", "en_panne", "panne_declaree", "pilote",
            "voyageurs_demandes", "voyageurs_reels", "req_s", "req_s_min", "echecs_pct",
            "recherche_ms", "reservations_min", "depot", "retrait", "tas", "consommateurs",
            "cpu_commandes", "reseau_commandes_ko_s", "commandes", "commandes_age_min",
            "reglage_140ms", "leader", "noeuds_prets", "jaeger_mi", "prometheus_jours", "s3_age_s",
            "vms0_libre_go", "action_niveau1_proposee", "action_niveau1_faite", "pause_proposee",
            "pause_motif", "duree_sonde_s"]
COLONNES_ACTIONS = ["instant", "geste", "motif", "cible", "resultat", "duree_s"]

ACCUEIL = os.path.expanduser("~")
SSH_HOTE = os.environ.get("GARDE_SSH", "master")
DISTANT = os.environ.get("GARDE_DISTANT", "/home/ubuntu/autodeploy")
DEPOT = os.environ.get("GARDE_DEPOT", os.path.join(ACCUEIL, "autodeploy_k8s-plateforme"))
PYTHON_S3 = os.environ.get("GARDE_PYTHON_S3", os.path.join(DEPOT, "graphe_en/.venv/bin/python"))
S3_CONFIG = os.environ.get("GARDE_S3_CONFIG", os.path.join(DEPOT, "graphe_en/config.yaml"))
PLAFOND_SSH = float(os.environ.get("GARDE_PLAFOND_SSH", "50"))   # la sonde rend avant 38 s
PLAFOND_S3 = 60
SSH_OPTIONS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
               "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=4"]
PROC = os.environ.get("GARDE_PROC", "/proc")   # où chercher le pilote (essais : un faux /proc)


# ------------------------------------------------------------------------------
# L'heure, les textes et les fichiers
# ------------------------------------------------------------------------------
def maintenant():
    """L'heure UTC de la garde (GARDE_MAINTENANT la remplace, pour les essais)."""
    f = os.environ.get("GARDE_MAINTENANT")
    if f:
        return datetime.strptime(f, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def a_la_minute(t):
    return t.replace(second=0, microsecond=0)


def texte_minute(t):
    return t.strftime("%Y-%m-%dT%H:%MZ")


def lire_minute(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)


def lire_instant(s):
    """« 2026-10-01T14:19:04Z » → datetime, ou None."""
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def compact(texte):
    """Un texte sur une ligne, sans espaces multiples."""
    return " ".join(str(texte).split())


def ecrire_atomique(chemin, texte):
    """Écrit tout d'un coup : un lecteur voit l'ancien fichier ou le nouveau, jamais un morceau."""
    tmp = f"{chemin}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(texte)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, chemin)


def lire_json(chemin, defaut):
    try:
        with open(chemin, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else defaut
    except (OSError, ValueError):
        return defaut


def dernieres_lignes(chemin, n):
    try:
        with open(chemin, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 16384))
            texte = f.read().decode("utf-8", "replace")
    except OSError:
        return []
    return [l for l in texte.splitlines() if l.strip()][-n:]


def ouvertes_dans_alertes(chemin):
    """Les alertes ouvertes d'alertes.txt (une ligne DEBUT sans FIN après) :
    {code: (minute, niveau)}. La même lecture que suivi.py."""
    ouvertes = {}
    try:
        with open(chemin, encoding="utf-8", errors="replace") as f:
            for l in f:
                p = l.split()
                if len(p) >= 4 and p[1] == "DEBUT":
                    ouvertes[p[3]] = (p[0], p[2])
                elif len(p) >= 4 and p[1] == "FIN":
                    ouvertes.pop(p[3], None)
    except OSError:
        pass
    return ouvertes


def nombre(x, chiffres=2):
    if x is None:
        return ""
    if isinstance(x, float):
        return f"{x:.{chiffres}f}"
    return str(x)


def duree_secondes(texte):
    """Une durée Chaos Mesh (« 20m », « 1200s », « 1h30m ») en secondes, ou None."""
    if not texte:
        return None
    parts = re.findall(r"(\d+(?:\.\d+)?)(ms|h|m|s)", texte)
    if not parts or "".join(a + b for a, b in parts) != texte:
        return None
    unite = {"h": 3600, "m": 60, "s": 1, "ms": 0.001}
    return sum(float(a) * unite[b] for a, b in parts)


# ------------------------------------------------------------------------------
# Lancer une commande bornée (son groupe entier est tué au plafond)
# ------------------------------------------------------------------------------
def lancer(cmd, plafond, env=None):
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             stdin=subprocess.DEVNULL, text=True, errors="replace",
                             start_new_session=True, env=env)
    except OSError as e:
        return {"erreur": f"lancement impossible : {e}"}
    try:
        out, err = p.communicate(timeout=plafond)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            p.communicate(timeout=3)
        except (subprocess.TimeoutExpired, ValueError):
            pass
        return {"erreur": f"aucune réponse en {plafond:.0f} s"}
    return {"code": p.returncode, "out": out, "err": err}


# ------------------------------------------------------------------------------
# Les mesures
# ------------------------------------------------------------------------------
def mesurer_master(avec_commandes):
    """La sonde, par UNE connexion ssh. Rend (mesure, None) ou (None, (quoi, détail))."""
    distant = f"python3 {DISTANT}/apps/garde_sonde.py" + (" --commandes" if avec_commandes else "")
    r = lancer(["ssh", *SSH_OPTIONS, SSH_HOTE, distant], PLAFOND_SSH)
    if "erreur" in r:
        return None, ("ssh", r["erreur"])
    if r["code"] == 255:   # ssh lui-même : hôte injoignable, clé refusée…
        return None, ("ssh", (r["err"].strip().splitlines() or ["code 255"])[-1][:200])
    try:
        mesure = json.loads(r["out"])
        if not isinstance(mesure, dict) or "prom" not in mesure:
            raise ValueError(mesure.get("erreur", "objet incomplet") if isinstance(mesure, dict) else "pas un objet")
    except ValueError as e:
        detail = (r["err"].strip().splitlines() or [str(e)])[-1]
        return None, ("sonde", f"code {r['code']} : {detail}"[:200])
    return mesure, None


# Le petit programme S3, lancé avec le python du dépôt (boto3). Il ouvre lui-même
# la configuration : le secret ne passe jamais par la garde. Tout message
# d'erreur est nettoyé des clés avant d'être imprimé ; une erreur survenue AVANT
# que les clés soient connues (config.yaml illisible, YAML mal formé : son
# message recopie la ligne fautive) ne donne que le type de l'erreur.
PROGRAMME_S3 = r'''
import datetime, json, os, sys
secrets = None
def taire(e):
    if secrets is None:
        return f"{type(e).__name__} (configuration illisible ; message tu)"
    t = f"{type(e).__name__}: {e}"
    for s in secrets:
        if s:
            t = t.replace(s, "***")
    return t
try:
    import yaml
    with open(sys.argv[1], encoding="utf-8") as f:
        src = dict((yaml.safe_load(f) or {}).get("source") or {})
    for cle, var in (("endpoint", "OBS_S3_ENDPOINT"), ("bucket", "OBS_S3_BUCKET"),
                     ("prefix", "OBS_S3_PREFIX"), ("access_key", "OBS_S3_ACCESS_KEY"),
                     ("secret_key", "OBS_S3_SECRET_KEY")):
        if not src.get(cle):
            src[cle] = os.environ.get(var) or src.get(cle)
    secrets = [str(src.get("secret_key") or ""), str(src.get("access_key") or "")]
    import boto3
    from botocore.config import Config
    s3 = boto3.client("s3", endpoint_url=src["endpoint"], aws_access_key_id=src["access_key"],
                      aws_secret_access_key=src["secret_key"], region_name=src.get("region") or "us-east-1",
                      config=Config(signature_version="s3v4", s3={"addressing_style": "path"},
                                    connect_timeout=10, read_timeout=20, retries={"max_attempts": 2}))
    prefixe = (src.get("prefix") or "otel-data").rstrip("/")
    dernier, n = None, 0
    for jour in sys.argv[2:]:            # « AAAA-MM-JJ@HH » : ce jour, à partir de l'heure HH
        date, _, heure = jour.partition("@")
        a, mo, j = date.split("-")
        p = f"{prefixe}/year={a}/month={mo}/day={j}/"
        args = {"Bucket": src["bucket"], "Prefix": p}
        if heure:
            args["StartAfter"] = f"{p}hour={heure}/"
        while True:
            r = s3.list_objects_v2(**args)
            for o in r.get("Contents", []):
                n += 1
                if dernier is None or o["LastModified"] > dernier:
                    dernier = o["LastModified"]
            if not r.get("IsTruncated"):
                break
            args["ContinuationToken"] = r.get("NextContinuationToken")
    print(json.dumps({"objets": n, "dernier": dernier.astimezone(datetime.timezone.utc)
                      .strftime("%Y-%m-%dT%H:%M:%SZ") if dernier else None}))
except Exception as e:
    print(json.dumps({"erreur": taire(e)[:300]}))
'''


def verifier_s3(quand):
    """Le dernier objet du jour UTC (et de la veille juste après minuit). Rend un dict."""
    if not os.path.exists(PYTHON_S3):
        return {"erreur": f"python de S3 introuvable : {PYTHON_S3}"}
    jours = []
    if quand.hour == 0:
        jours.append(f"{(quand - timedelta(days=1)):%Y-%m-%d}@22")
    jours.append(f"{quand:%Y-%m-%d}" + (f"@{quand.hour - 1:02d}" if quand.hour >= 1 else ""))
    r = lancer([PYTHON_S3, "-c", PROGRAMME_S3, S3_CONFIG, *jours], PLAFOND_S3)
    if "erreur" in r:
        return {"erreur": r["erreur"]}
    try:
        res = json.loads(r["out"].strip().splitlines()[-1])
    except (ValueError, IndexError):
        # Ni la sortie ni l'erreur ne sont recopiées : elles pourraient porter la configuration.
        return {"erreur": f"réponse illisible (code {r['code']})"}
    if "erreur" not in res:
        d = lire_instant(res.get("dernier"))
        res["age_s"] = round((quand - d).total_seconds()) if d else None
    res["verifie_a"] = quand.strftime("%Y-%m-%dT%H:%M:%SZ")
    return res


ENVELOPPES = ("timeout", "nice", "nohup", "setsid", "env", "stdbuf", "ionice", "sudo")


def est_pilote(argv):
    """argv lance-t-il campagne.sh ? Rend (oui, nom de campagne).
    Accepte « bash campagne.sh nom », « bash -x ./campagne.sh nom », « timeout 7d
    bash campagne.sh nom », « nice bash … » ; refuse un éditeur, un tail, un grep."""
    if not argv:
        return False, ""
    if os.path.basename(argv[0]) == "campagne.sh":
        k = 0
    else:
        shells = [i for i, a in enumerate(argv) if os.path.basename(a) in ("bash", "sh")]
        if not shells:
            return False, ""
        i = shells[0]
        # Avant le shell : seulement des enveloppes et leurs arguments ; le premier mot en est une.
        if i > 0 and os.path.basename(argv[0]) not in ENVELOPPES:
            return False, ""
        k = i + 1
        while k < len(argv) and argv[k].startswith("-"):
            if argv[k] == "-c":
                return False, ""        # « bash -c '… campagne.sh …' » : un texte, pas le pilote
            k += 1                      # les options du shell (-x, -e…)
        if k >= len(argv) or os.path.basename(argv[k]) != "campagne.sh":
            return False, ""
    nom = argv[k + 1] if len(argv) > k + 1 and not argv[k + 1].startswith("-") else ""
    return True, nom


def lire_processus(pid, racine=None):
    """Un processus lu dans <racine>/<pid> (défaut : PROC) : argv, ppid, état, et sa
    date de démarrage (champ 22 « starttime » de stat, en tops depuis le démarrage
    de la machine : deux processus qui ont porté le même pid n'ont pas la même).
    Rend None s'il a disparu ou est illisible."""
    racine = racine or PROC
    try:
        with open(f"{racine}/{pid}/cmdline", "rb") as f:
            argv = [a.decode("utf-8", "replace") for a in f.read().split(b"\0") if a]
        with open(f"{racine}/{pid}/stat") as f:
            champs = f.read().rsplit(")", 1)[1].split()
        return {"argv": argv, "etat": champs[0], "ppid": int(champs[1]), "debut": int(champs[19])}
    except (OSError, ValueError, IndexError):
        return None


def trouver_pilotes(racine=None):
    """Les pilotes vivants (processus campagne.sh racines), triés par pid. Chacun :
    pid et debut de la racine (affichée), nom de campagne, et pid_signal /
    debut_signal : le processus à qui envoyer TERM (sous une enveloppe qui fourche,
    comme « timeout », le bash qu'elle enveloppe)."""
    racine = racine or PROC
    trouves = {}
    for pid in os.listdir(racine):
        if not pid.isdigit() or int(pid) == os.getpid():
            continue
        x = lire_processus(pid, racine)
        if x is None or x["etat"] == "Z":
            continue
        oui, nom = est_pilote(x["argv"])
        if oui:
            trouves[int(pid)] = dict(x, nom=nom)
    # Les sous-shells du pilote (et le bash sous « timeout ») portent la même ligne
    # de commande : on garde la racine.
    res = []
    for pid in sorted(p for p, x in trouves.items() if x["ppid"] not in trouves):
        cible = pid
        while os.path.basename(trouves[cible]["argv"][0]) in ENVELOPPES:
            enfants = [p for p, x in trouves.items() if x["ppid"] == cible]
            if len(enfants) != 1:
                break
            cible = enfants[0]
        res.append({"vivant": True, "pid": pid, "nom": trouves[pid]["nom"], "debut": trouves[pid]["debut"],
                    "pid_signal": cible, "debut_signal": trouves[cible]["debut"]})
    return res


def verifier_pilote(pid, nom, debut):
    """Le processus <pid> est-il TOUJOURS le même pilote : un campagne.sh vivant, avec
    ce nom de campagne et cette date de démarrage ? Rend (oui, raison)."""
    x = lire_processus(pid)
    if x is None:
        return False, f"pid {pid} disparu"
    if x["etat"] == "Z":
        return False, f"pid {pid} fini (zombie)"
    oui, nom_lu = est_pilote(x["argv"])
    if not oui:
        return False, f"pid {pid} n'est pas un campagne.sh : " + " ".join(x["argv"])[:120]
    if nom_lu != nom:
        return False, f"pid {pid} : campagne « {nom_lu} » au lieu de « {nom} »"
    if x["debut"] != debut:
        return False, f"pid {pid} réutilisé : démarré à {x['debut']} au lieu de {debut} (starttime)"
    return True, "même pilote"


def signaler_pilote(pid, nom, debut):
    """kill -TERM au pilote, après l'avoir relu JUSTE AVANT (pas de pid réutilisé,
    pas un autre processus). Jamais un autre signal. Rend (envoyé, raison).
    Le processus est d'abord tenu par un pidfd (Linux ≥ 5.3), puis relu, puis
    signalé par ce pidfd : si le pid avait changé de main entre l'ouverture et
    la relecture, la relecture le voit ; après, le pidfd désigne toujours le
    processus relu (mort entre-temps : le signal échoue, sans toucher personne).
    Sans pidfd (noyau ancien), os.kill juste après la relecture."""
    fd = None
    try:
        fd = os.pidfd_open(pid)
    except ProcessLookupError:
        return False, f"pid {pid} disparu"
    except (AttributeError, OSError):
        fd = None
    try:
        oui, raison = verifier_pilote(pid, nom, debut)
        if not oui:
            return False, raison
        try:
            if fd is not None:
                signal.pidfd_send_signal(fd, signal.SIGTERM)
            else:
                os.kill(pid, signal.SIGTERM)
        except OSError as e:
            return False, f"kill -TERM {pid} : {e}"
        return True, f"SIGTERM envoyé au pid {pid}"
    finally:
        if fd is not None:
            os.close(fd)


def mesures_locales(quand):
    """Sur vms0 : le pilote, son journal, les lignes FIN, le disque."""
    res = {"instant": quand.timestamp(), "pilote": {"vivant": False}}
    pilotes = trouver_pilotes()
    if pilotes:
        res["pilote"] = pilotes[0]
        if len(pilotes) > 1:
            res["autres_pilotes"] = [f"{x['nom']}({x['pid']})" for x in pilotes[1:]]
    journaux = glob.glob(os.path.join(DEPOT, "journaux", "campagne-*.log"))
    if journaux:
        dernier = max(journaux, key=os.path.getmtime)
        age = (quand.timestamp() - os.path.getmtime(dernier)) / 60
        res["journal"] = {"fichier": os.path.basename(dernier), "age_min": round(age, 1)}
    res["fins"] = dernieres_lignes(os.path.join(DEPOT, "journaux", "fins.tsv"), 3)
    try:
        res["vms0_libre_go"] = round(shutil.disk_usage(ACCUEIL).free / 1e9, 1)
    except OSError as e:
        res["vms0_libre_go"] = None
        res["disque_erreur"] = str(e)
    return res


# ------------------------------------------------------------------------------
# Le jugement d'une minute : ses causes et ses notes
# ------------------------------------------------------------------------------
def niveau(code):
    return CODES[code.split(":")[0]][0]


def classe(code):
    return CODES[code.split(":")[0]][1]


class Jugement:
    """Les codes trouvés pour une minute, chacun avec un détail lisible.
    causes : ce qui fait l'état (MALADE, DOUTEUX) ; notes : noté sans effet."""

    def __init__(self):
        self.causes = {}         # code → détail
        self.notes = {}          # code → détail
        self.fautifs = {}        # code → objet Chaos Mesh qui l'a déclenché (pour « retirer »)

    def ajouter(self, code, detail=""):
        """Un code de niveau NOTE va de lui-même dans les notes."""
        if niveau(code) == NOTE:
            self.noter(code, detail)
        else:
            self.causes.setdefault(code, detail)

    def noter(self, code, detail=""):
        self.notes.setdefault(code, detail)

    def echec(self, quoi, detail):
        self.ajouter(f"MEASURE_FAILED:{quoi}", compact(detail))

    def mettre_en_note(self, code):
        self.notes[code] = "noté : " + self.causes.pop(code)

    def malade(self):
        return any(niveau(c) == MALADE for c in self.causes)

    def mesures_ratees(self):
        return {c.split(":", 1)[1] for c in self.causes if c.startswith("MEASURE_FAILED:")}


class Contexte:
    """Ce que tous les juges d'une minute partagent : les mesures, la mémoire, la
    ligne à écrire, le jugement, et ce que les premiers juges ont trouvé et que
    les suivants utilisent (panne en cours, voyageurs demandés, débit…)."""

    def __init__(self, minute, mesure, local, s3, mem, ref):
        self.minute, self.mesure, self.local, self.s3 = minute, mesure, local, s3
        self.mem, self.ref = mem, ref
        self.t = maintenant()                 # l'heure du jugement, pour les âges
        self.ligne = {c: "" for c in COLONNES}
        self.ligne["minute"] = texte_minute(minute)
        self.jugement = Jugement()
        self.propositions = {"retirer": None, "term": None, "pause": []}
        self.prom = (mesure or {}).get("prom", {})
        pilote = local.get("pilote", {})
        self.pilote_vivant = pilote.get("vivant", False)
        # Remplis par les juges, dans l'ordre d'etiqueter() :
        self.en_panne = self.etat_present = self.apres_panne = False
        self.objets = []                      # objets Chaos Mesh (hors réglage de base)
        self.panne_debut = self.panne_duree_min = None   # DEBUT et DUREE (min) de panne.etat
        self.voyageurs_demandes = None
        self.historique_paliers = None        # [[instant_demande, voyageurs], …] de paliers.tsv
        self.effondrement = None              # le seuil de LOCUST_COLLAPSE et d'où vient N
        self.panne_agit = False               # un « panne.sh » agit sur le master (sonde)
        self.gestes_connus = False            # la sonde a pu dire ce qui agit sur le master
        self.palier_recent = False
        self.voyageurs = self.req_s = None
        self.locust_tourne = False
        self.pret = None                      # messages prêts dans la file

    def partie(self, cle):
        """Une partie de la mesure ; absente, elle devient une erreur."""
        return (self.mesure or {}).get(cle) or {"erreur": "absent de la sonde"}

    def debit_juge(self):
        n = self.voyageurs_demandes
        return n is not None and n >= VOYAGEURS_MIN_DEBIT

    def valeur(self, nom):
        """La valeur d'une requête « somme » de la sonde ; une erreur devient une cause."""
        r = self.prom.get(nom) or {"erreur": "absente de la sonde"}
        if "erreur" in r:
            self.jugement.echec(f"prom_{nom}", r["erreur"])
            return None
        return r.get("valeur")

    def series(self, nom):
        r = self.prom.get(nom) or {"erreur": "absente de la sonde"}
        if "erreur" in r:
            self.jugement.echec(f"prom_{nom}", r["erreur"])
            return None
        return r.get("series", [])


def confirmer(ctx, code, detail, minutes):
    """Un code qui doit durer `minutes` minutes de suite avant de compter.
    Avant, il est seulement noté, avec « k/minutes »."""
    suites = ctx.mem.setdefault("suites", {})
    prec = suites.get(code) or {}
    hier = texte_minute(ctx.minute - timedelta(minutes=1))
    k = prec.get("n", 0) + 1 if prec.get("minute") == hier else 1
    suites[code] = {"n": k, "minute": texte_minute(ctx.minute)}
    if k >= minutes:
        ctx.jugement.ajouter(code, detail)
    else:
        ctx.jugement.noter(code, f"{k}/{minutes} min : {detail}")


# ------------------------------------------------------------------------------
# L'étiquetage : une table des matières, puis un juge par sujet
# ------------------------------------------------------------------------------
def etiqueter(minute, mesure, echec_mesure, local, s3, mem, ref):
    """Juge une minute. Rend le Contexte (ligne, jugement, propositions) ; met à
    jour mem et ref. echec_mesure = (quoi, détail) quand la sonde n'a rien rendu."""
    ctx = Contexte(minute, mesure, local, s3, mem, ref)
    juger_local(ctx)
    if mesure is None:
        # Rien du master : la minute est MALADE, et tout le reste est inconnu.
        ctx.jugement.echec(*echec_mesure)
        mem["locust"] = None
        return ctx
    ctx.ligne["duree_sonde_s"] = nombre(mesure.get("duree_s"), 1)
    juger_panne_declaree(ctx)
    juger_palier(ctx)
    juger_locust(ctx)
    juger_file(ctx)
    juger_ts_order(ctx)
    juger_commandes(ctx)
    juger_memoire(ctx)
    juger_redemarrages(ctx)
    juger_pods_cles(ctx)
    juger_leader(ctx)
    juger_noeuds(ctx)
    juger_reglage(ctx)
    juger_collecte(ctx)
    juger_pannes_restees(ctx)
    juger_effondrement(ctx)
    mettre_en_notes_pendant_panne(ctx)
    # Ce que la minute suivante doit savoir pour décider du retour au régime.
    mem["regime_mesure"] = {"pret": ctx.pret, "req_s": ctx.req_s, "n_dem": ctx.voyageurs_demandes}
    return ctx


def juger_local(ctx):
    """vms0 : pilote, journal du pilote, disque."""
    loc, j = ctx.local, ctx.jugement
    pilote = loc.get("pilote", {})
    if ctx.pilote_vivant:
        ctx.ligne["pilote"] = f"{pilote.get('nom') or '?'}({pilote['pid']})"
    ctx.ligne["vms0_libre_go"] = nombre(loc.get("vms0_libre_go"), 1)
    if loc.get("vms0_libre_go") is None:
        j.echec("vms0_disque", loc.get("disque_erreur", "illisible"))
    elif loc["vms0_libre_go"] < VMS0_LIBRE_MIN_GO:
        j.ajouter("VMS0_DISK_LOW", f"{loc['vms0_libre_go']} Go libres < {VMS0_LIBRE_MIN_GO:.0f}")
    jr = loc.get("journal")
    if ctx.pilote_vivant and jr and jr["age_min"] > PILOTE_SILENCE_MIN:
        j.ajouter("PILOT_SILENT", f"{jr['fichier']} muet depuis {jr['age_min']:.0f} min")


def juger_panne_declaree(ctx):
    """Une panne est-elle en cours (panne.etat, ou objet Chaos Mesh) ? Finie depuis peu ?"""
    j, mem = ctx.jugement, ctx.mem
    panne_etat, chaos = ctx.partie("panne_etat"), ctx.partie("chaos")
    if "erreur" in panne_etat:
        j.echec("panne_etat", panne_etat["erreur"])
    if "erreur" in chaos:
        j.echec("chaos", chaos["erreur"])
    ctx.objets = chaos.get("objets", [])
    ctx.etat_present = panne_etat.get("present", False)
    ctx.en_panne = ctx.etat_present or bool(ctx.objets)
    ctx.ligne["en_panne"] = "1" if ctx.en_panne else "0"
    if ctx.etat_present:
        contenu = panne_etat.get("contenu") or {}
        ctx.ligne["panne_declaree"] = contenu.get("CAUSE", "?")
        ctx.panne_debut = lire_instant(contenu.get("DEBUT"))
        try:
            ctx.panne_duree_min = float(contenu.get("DUREE"))   # en minutes (panne.sh --duree)
        except (TypeError, ValueError):
            ctx.panne_duree_min = None
    elif ctx.objets:
        ctx.ligne["panne_declaree"] = "+".join(f"{o['type']}/{o['nom']}" for o in ctx.objets)
    if ctx.en_panne:
        mem["derniere_minute_en_panne"] = texte_minute(ctx.minute)
    # La fin de la dernière panne : ce que la garde a vu, ou le registre pannes.tsv.
    fins = []
    if mem.get("derniere_minute_en_panne"):
        fins.append(lire_minute(mem["derniere_minute_en_panne"]))
    for l in ctx.partie("pannes").get("lignes", []):
        if len(l) > 2 and l[2] == "retrait":
            d = lire_instant(l[1]) or lire_instant(l[0])
            if d:
                fins.append(d)
    ctx.apres_panne = bool(not ctx.en_panne and fins and
                           (ctx.minute - max(fins)).total_seconds() < TAS_APRES_PANNE_MIN * 60)


def juger_palier(ctx):
    """Les voyageurs demandés (dernière ligne de paliers.tsv) et l'âge du palier."""
    palier = ctx.partie("palier")
    if "erreur" in palier:
        ctx.jugement.echec("paliers", palier["erreur"])
        return
    ctx.voyageurs_demandes = palier.get("demandes")
    ctx.historique_paliers = palier.get("historique")   # absent d'une ancienne sonde
    ctx.ligne["voyageurs_demandes"] = nombre(ctx.voyageurs_demandes)
    d = lire_instant(palier.get("effectif")) or lire_instant(palier.get("demande"))
    ctx.palier_recent = d is not None and (ctx.t - d).total_seconds() < GRACE_PALIER_MIN * 60
    if ctx.debit_juge():
        ctx.ligne["req_s_min"] = nombre(PART_DEBIT_MIN * REQ_S_PAR_VOYAGEUR * ctx.voyageurs_demandes)


def juger_locust(ctx):
    """Voyageurs réels, débit sur la minute, échecs, recherche, réservations."""
    j, n_dem = ctx.jugement, ctx.voyageurs_demandes
    locust = ctx.partie("locust")
    if "erreur" in locust:
        j.echec("locust", locust["erreur"])
        ctx.mem["locust"] = None
        return
    if locust.get("absent"):
        ctx.voyageurs, ctx.req_s = 0, 0.0
        ctx.ligne["voyageurs_reels"] = "0"
        # À 0 réplique hors campagne, avec un palier demandé à 0 : normal.
        if n_dem is None or n_dem > 0:
            confirmer(ctx, "LOCUST_USERS", f"Locust à 0 réplique, {nombre(n_dem) or '?'} voyageurs demandés",
                      CONFIRMATION_MIN)
        ctx.mem["locust"] = None
        return
    ctx.voyageurs = locust.get("voyageurs") or 0
    ctx.locust_tourne = locust.get("etat") in ("running", "spawning") and ctx.voyageurs > 0
    ctx.ligne["voyageurs_reels"] = nombre(ctx.voyageurs)
    req_s_minute = juger_parcours(ctx, locust)
    ctx.req_s = req_s_minute if req_s_minute is not None else (locust.get("req_s") or 0.0)
    ctx.ligne["req_s"] = nombre(float(ctx.req_s))
    if locust.get("etat") == "spawning":
        # Locust ajoute OU retire des voyageurs (aussi à la descente) ; loadgen.sh
        # n'écrit le palier qu'une fois la cible atteinte : le débit est seulement noté.
        j.noter("LOCUST_RAMPING", f"{ctx.voyageurs} voyageurs, vers {nombre(n_dem) or '?'}")
        ctx.palier_recent = True
    elif n_dem is not None and ctx.voyageurs != n_dem:
        confirmer(ctx, "LOCUST_USERS", f"{ctx.voyageurs} voyageurs réels, {n_dem} demandés", CONFIRMATION_MIN)
    seuil = PART_DEBIT_MIN * REQ_S_PAR_VOYAGEUR * (n_dem or 0)
    if ctx.debit_juge() and ctx.req_s < seuil:
        j.ajouter("LOCUST_RATE_LOW", f"{ctx.req_s:.1f} req/s < {seuil:.1f}")


def juger_parcours(ctx, locust):
    """Échecs, temps de recherche et réservations, sur la minute écoulée ; rend
    le débit sur la minute (None sans minute précédente).
    Locust donne des totaux depuis sa remise à zéro : on fait la différence avec
    la mesure de la minute précédente. Sans elle (première minute, Locust remis à
    zéro), on se rabat sur ses moyennes de 10 s. Le débit sur la minute (≈ 450
    requêtes à 25 voyageurs) est bien moins bruité que celui sur 10 s (un parcours
    compte 1 à 4 requêtes) : c'est lui qui juge LOCUST_RATE_LOW et le régime."""
    j, mem, ligne, minute = ctx.jugement, ctx.mem, ctx.ligne, ctx.minute
    parcours = locust.get("parcours", {})
    prec = mem.get("locust")
    actuels = {nom: [p["n"], p["echecs"], (p.get("moyenne_ms") or 0) * p["n"]]
               for nom, p in parcours.items()}
    instant = ctx.local.get("instant")
    mem["locust"] = {"minute": texte_minute(minute), "instant": instant, "parcours": actuels}
    delta, secondes = None, 60.0
    if (prec and prec.get("minute") == texte_minute(minute - timedelta(minutes=1))
            and all(actuels.get(k, [0])[0] >= v[0] for k, v in prec["parcours"].items())):
        delta = {k: [a - b for a, b in zip(v, prec["parcours"].get(k, [0, 0, 0]))]
                 for k, v in actuels.items()}
        if instant and prec.get("instant") and 30 <= instant - prec["instant"] <= 90:
            secondes = instant - prec["instant"]
    req_s_minute = None
    if delta and "Aggregated" in delta:
        req_s_minute = delta["Aggregated"][0] / secondes
    # Échecs : le pire parcours, hors « code » et « connexion » (L6) et le total.
    pire, pire_nom = None, ""
    for nom, p in parcours.items():
        if nom == "Aggregated" or nom.startswith(("00 ", "01 ")):
            continue
        pct = None
        if delta and delta.get(nom, [0])[0] >= ECHECS_REQUETES_MIN:
            dn, de, _ = delta[nom]
            pct = 100.0 * de / dn
        elif (p.get("req_s") or 0) * 10 >= ECHECS_REQUETES_MIN:
            pct = 100.0 * (p.get("echecs_s") or 0) / p["req_s"]
        if pct is not None and (pire is None or pct > pire):
            pire, pire_nom = pct, nom
    ligne["echecs_pct"] = nombre(pire, 1)
    if pire is not None and pire > ECHECS_MAX_PCT:
        j.ajouter("LOCUST_ERRORS", f"« {pire_nom} » : {pire:.1f} % d'échecs > {ECHECS_MAX_PCT:.0f} %")
    # Recherche : moyenne sur la minute (seuil 15 s) ; sans minute précédente,
    # la médiane de Locust depuis son départ (seuil 30 s, celui du plan).
    recherche = parcours.get("10 chercher un train")
    if recherche:
        if delta and delta.get("10 chercher un train", [0])[0] > 0:
            dn, _, dsomme = delta["10 chercher un train"]
            ms, seuil, quoi = dsomme / dn, RECHERCHE_MOYENNE_MAX_MS, "moyenne sur la minute"
        else:
            ms, seuil, quoi = recherche.get("mediane_ms"), RECHERCHE_P50_MAX_MS, "médiane depuis le départ"
        ligne["recherche_ms"] = nombre(round(ms) if ms is not None else None)
        if ms is not None and ms >= seuil:
            j.ajouter("SEARCH_SLOW", f"{quoi} {ms:.0f} ms ≥ {seuil}")
    # Réservations réussies depuis la minute précédente.
    if delta and "30 réserver un billet" in parcours:
        dn, de, _ = delta.get("30 réserver un billet", [0, 0, 0])
        ligne["reservations_min"] = nombre(max(0, dn - de))
        n_dem = ctx.voyageurs_demandes
        if ctx.locust_tourne and n_dem is not None and n_dem >= RESERVATIONS_VOYAGEURS_MIN and dn - de <= 0:
            j.ajouter("BOOKING_STUCK", f"{dn} essais, aucune réussite depuis la minute précédente")
    return req_s_minute


def juger_file(ctx):
    """food_delivery : dépôt, retrait, tas, consommateurs."""
    j, mem, ligne, n_dem = ctx.jugement, ctx.mem, ctx.ligne, ctx.voyageurs_demandes
    depot = ctx.valeur("depot")
    ctx.pret = ctx.valeur("tas_pret")
    non_acquittes = ctx.valeur("tas_non_acquitte")
    retrait = ctx.valeur("retrait")
    consommateurs = ctx.valeur("consommateurs")
    ligne["depot"], ligne["retrait"] = nombre(depot), nombre(retrait)
    tas = ctx.pret + non_acquittes if ctx.pret is not None and non_acquittes is not None else None
    ligne["tas"] = nombre(int(tas)) if tas is not None else ""
    ligne["consommateurs"] = nombre(int(consommateurs)) if consommateurs is not None else ""
    if depot is not None and ctx.debit_juge():
        if depot < DEPOT_GEL_PAR_VOYAGEUR * n_dem:
            j.ajouter("PUBLISH_FROZEN", f"{depot:.2f} msg/s < {DEPOT_GEL_PAR_VOYAGEUR * n_dem:.2f}")
        elif depot < DEPOT_MIN_PAR_VOYAGEUR * n_dem:
            confirmer(ctx, "PUBLISH_LOW", f"{depot:.2f} msg/s < {DEPOT_MIN_PAR_VOYAGEUR * n_dem:.2f}",
                      DEPOT_BAS_MINUTES)
    if depot is not None and retrait is not None and depot - retrait > ECART_RETRAIT_MAX:
        depuis = lire_minute(mem.get("ecart_depuis") or texte_minute(ctx.minute))
        mem["ecart_depuis"] = texte_minute(depuis)
        if (ctx.minute - depuis).total_seconds() >= (ECART_RETRAIT_MINUTES - 1) * 60:
            j.ajouter("DRAIN_LAG", f"dépôt {depot:.2f} − retrait {retrait:.2f} > {ECART_RETRAIT_MAX} "
                                   f"depuis {texte_minute(depuis)}")
    else:
        mem["ecart_depuis"] = None
    if tas is not None and tas > TAS_MAX:
        j.ajouter("QUEUE_BACKLOG", f"{tas:.0f} messages > {TAS_MAX}")
    if consommateurs is not None and int(consommateurs) != CONSOMMATEURS:
        j.ajouter("CONSUMERS", f"{consommateurs:.0f} consommateurs au lieu de {CONSOMMATEURS}")


def juger_ts_order(ctx):
    """ts-order-service : CPU (trop haut, ou gelé) et réseau reçu."""
    j = ctx.jugement
    cpu = ctx.valeur("cpu_commandes")
    reseau = ctx.valeur("reseau_commandes")
    ko_s = reseau / 1000 if reseau is not None else None
    ctx.ligne["cpu_commandes"] = nombre(cpu, 3)
    ctx.ligne["reseau_commandes_ko_s"] = nombre(ko_s, 1)
    if cpu is not None:
        if cpu > CPU_MALADE:
            j.ajouter("ORDER_CPU_HIGH", f"{cpu:.2f} cœur > {CPU_MALADE}")
            ctx.propositions["pause"].append("ORDER_CPU_HIGH")
        elif cpu > CPU_ALERTE:
            j.ajouter("ORDER_CPU_WARN", f"{cpu:.2f} cœur > {CPU_ALERTE}")
    if ctx.locust_tourne and ctx.voyageurs >= VOYAGEURS_MIN_DEBIT and (
            (cpu is not None and cpu < CPU_GEL) or (reseau is not None and reseau < RESEAU_GEL_OCTETS_S)):
        j.ajouter("ORDER_FROZEN", f"CPU {nombre(cpu, 3) or '?'} cœur, réseau {nombre(ko_s, 2) or '?'} ko/s, "
                                  f"Locust à {ctx.voyageurs} voyageurs")


def juger_commandes(ctx):
    """Les commandes en table : lues une minute sur dix, gardées entre deux lectures,
    oubliées après une purge RÉUSSIE (registre donnees.tsv du master)."""
    j, mem, ligne, minute = ctx.jugement, ctx.mem, ctx.ligne, ctx.minute
    lecture = mem.get("commandes") or {}
    lu = (ctx.mesure or {}).get("commandes")
    if lu is not None:
        if "erreur" in lu:
            j.echec("commandes", lu["erreur"])
        else:
            lecture = {"valeur": lu["tables"].get("orders"), "minute": texte_minute(minute)}
    if lecture.get("minute"):
        lue_a = lire_minute(lecture["minute"]) + timedelta(seconds=59)
        for l in ctx.partie("purges").get("lignes", []):
            # instant, action, lignes_avant, resultat (donnees.sh consigner)
            d = lire_instant(l[0]) if l else None
            if (d and d > lue_a and len(l) > 3 and l[1].startswith("purger") and l[3] == "ok"):
                lecture = {}   # une purge depuis la lecture : la valeur ne vaut plus rien
                break
    mem["commandes"] = lecture
    v = lecture.get("valeur")
    if v is None:
        return
    ligne["commandes"] = nombre(v)
    ligne["commandes_age_min"] = nombre(int((minute - lire_minute(lecture["minute"])).total_seconds() // 60))
    if v >= COMMANDES_MALADE:
        j.ajouter("ORDERS_MAX", f"{v} commandes ≥ {COMMANDES_MALADE}")
        ctx.propositions["pause"].append("ORDERS_MAX")
    elif v >= COMMANDES_PAUSE:
        j.ajouter("ORDERS_HIGH", f"{v} commandes ≥ {COMMANDES_PAUSE}")
        ctx.propositions["pause"].append("ORDERS_HIGH")
    elif v >= COMMANDES_ALERTE:
        j.ajouter("ORDERS_WARN", f"{v} commandes ≥ {COMMANDES_ALERTE}")


def juger_memoire(ctx):
    """Mémoire de Jaeger et de tsdb-mysql-0 ; historique gardé par Prometheus."""
    j = ctx.jugement
    memoire = ctx.series("memoire_pods")
    if memoire is not None:
        pods_jaeger = [s["valeur"] for s in memoire if s["etiquettes"].get("pod", "").startswith("jaeger")]
        mysql = [s["valeur"] for s in memoire if s["etiquettes"].get("pod") == "tsdb-mysql-0"]
        if pods_jaeger:
            jaeger = sum(pods_jaeger)
            ctx.ligne["jaeger_mi"] = nombre(round(jaeger / 2**20))
            if jaeger > JAEGER_MAX:
                j.ajouter("JAEGER_MEMORY", f"{jaeger / 2**20:.0f} Mi > {JAEGER_MAX / 2**20:.0f}")
        if mysql and mysql[0] > MYSQL_MAX:
            j.ajouter("MYSQL_MEMORY_HIGH", f"{mysql[0] / 2**20:.0f} Mi > {MYSQL_MAX / 2**20:.0f}")
    # Prometheus est au plafond de taille par construction (O10) : ce qui compte
    # est la durée qu'il garde encore. Cette mesure ne juge pas les données de la
    # minute : la lire mal n'est qu'une note, pas une mesure impossible.
    h = ctx.prom.get("historique_prometheus") or {"erreur": "absente de la sonde"}
    if "erreur" in h:
        j.noter("PROMETHEUS_HISTORY_UNREAD", compact(h["erreur"]))
    else:
        jours = h["valeur"] / 86400
        ctx.ligne["prometheus_jours"] = nombre(jours, 1)
        if jours < PROMETHEUS_JOURS_MIN:
            j.ajouter("PROMETHEUS_SHORT_HISTORY", f"{jours:.1f} jours gardés < {PROMETHEUS_JOURS_MIN:.0f}")


def juger_redemarrages(ctx):
    """Toute hausse d'un compteur de redémarrages depuis la minute précédente.
    Deux sources : Prometheus (trois espaces) et kubectl (train-ticket). Un
    compteur absent cette minute (série disparue, réponse vide) garde sa valeur
    pendant 60 min : à son retour, il n'est pas pris pour un pod nouveau."""
    j, mem, minute = ctx.jugement, ctx.mem, ctx.minute
    pods = ctx.partie("pods")
    if "erreur" in pods:
        j.echec("pods", pods["erreur"])
    actuels = {}
    for s in ctx.series("redemarrages") or []:
        e = s["etiquettes"]
        actuels[f"{e.get('namespace')}/{e.get('pod')}"] = int(s["valeur"])
    for p in pods.get("pods", []):
        if p.get("redemarrages") is not None:
            cle = f"train-ticket/{p['nom']}"
            actuels[cle] = max(actuels.get(cle, 0), p["redemarrages"])
    prec = mem.get("redemarrages")
    if prec is not None:
        for cle, n in sorted(actuels.items()):
            avant = prec.get(cle)
            # Un pod jamais vu (ou pas depuis 60 min) qui a déjà redémarré compte
            # aussi : créé puis tombé dans la minute.
            if (avant is not None and n > avant) or (avant is None and n > 0):
                ns, pod = cle.split("/", 1)
                texte = f"{cle} : {avant if avant is not None else 'nouveau'} → {n}"
                if ns in ("train-ticket", "loadgen") or pod.startswith("otel-gateway"):
                    j.ajouter("POD_RESTART", texte)
                elif pod.startswith("jaeger"):
                    j.ajouter("JAEGER_RESTART", texte)
                else:
                    j.ajouter("OBS_RESTART", texte)
    # Les compteurs non revus cette minute restent connus 60 min.
    vus = mem.get("redemarrages_vus") or {}
    fusion = {}
    for cle, n in (prec or {}).items():
        vu = vus.get(cle)
        if cle not in actuels and vu and (minute - lire_minute(vu)).total_seconds() < REDEMARRAGES_OUBLI_MIN * 60:
            fusion[cle] = n
    fusion.update(actuels)
    mem["redemarrages"] = fusion
    mem["redemarrages_vus"] = {c: (texte_minute(minute) if c in actuels else vus[c]) for c in fusion}


def juger_pods_cles(ctx):
    """order, travel, seat, preserve, security : au moins un pod prêt chacun."""
    j, pods = ctx.jugement, ctx.partie("pods")
    if "pods" in pods:
        for s in CLES:
            prets = [p for p in pods["pods"] if p["nom"].startswith(f"ts-{s}-service-")
                     and p["phase"] == "Running" and p["pret"] and not p["en_arret"]]
            if not prets:
                j.ajouter("KEY_POD_NOT_READY", f"ts-{s}-service : aucun pod prêt")
        return
    series = (ctx.prom.get("pods_cles_prets") or {}).get("series")
    if series is None:
        return   # les deux sources manquent : déjà compté comme mesure impossible
    for s in CLES:
        if not any(x["etiquettes"].get("pod", "").startswith(f"ts-{s}-service-") and x["valeur"] >= 1
                   for x in series):
            j.ajouter("KEY_POD_NOT_READY", f"ts-{s}-service : aucun pod prêt (Prometheus)")


def juger_leader(ctx):
    """Le leader MySQL : présent, cohérent, et le même qu'à la référence."""
    j, ref, leader = ctx.jugement, ctx.ref, ctx.partie("leader")
    if "erreur" in leader:
        j.echec("leader", leader["erreur"])
        return
    ctx.ligne["leader"] = leader.get("leader") or ""
    if not leader.get("leader"):
        copies = ", ".join(f"{n}={c.get('role')}" for n, c in sorted((leader.get("copies") or {}).items()))
        vers = ", ".join(leader.get("destinations") or []) or "aucune adresse"
        j.ajouter("LEADER_LOST", f"{copies or 'aucune copie'} ; service → {vers}")
    elif not ref.get("leader"):
        ref["leader"] = leader["leader"]
        ref["leader_note_le"] = texte_minute(ctx.minute)
    elif leader["leader"] != ref["leader"]:
        j.ajouter("LEADER_CHANGED", f"{leader['leader']} au lieu de {ref['leader']}")


def juger_noeuds(ctx):
    """Nœuds Ready, adresses, mémoire disponible, disque."""
    j, ref, ligne = ctx.jugement, ctx.ref, ctx.ligne
    noeuds = ctx.partie("noeuds")
    adresses = ref.setdefault("adresses", {})
    if "erreur" in noeuds:
        j.echec("noeuds", noeuds["erreur"])
        # Prometheus sait aussi quels nœuds sont Ready.
        series = (ctx.prom.get("noeuds_prets") or {}).get("series")
        if series is not None:
            prets = {s["etiquettes"].get("node") for s in series if s["valeur"] >= 1}
            ligne["noeuds_prets"] = f"{len(prets)}/{max(len(adresses), len(series))}"
            for nom in sorted(set(adresses) - prets):
                j.ajouter("NODE_NOT_READY", f"{nom} (Prometheus)")
    else:
        liste = noeuds["noeuds"]
        connus = set(adresses) | set(liste)
        ligne["noeuds_prets"] = f"{sum(1 for x in liste.values() if x['pret'])}/{len(connus)}"
        for nom in sorted(connus):
            x = liste.get(nom)
            if x is None:
                j.ajouter("NODE_NOT_READY", f"{nom} a disparu de la liste des nœuds")
                continue
            if not x["pret"]:
                j.ajouter("NODE_NOT_READY", f"{nom} : {x['statut']}")
            if nom not in adresses:
                adresses[nom] = x["ip"]
            elif x["ip"] != adresses[nom]:
                j.ajouter("NODE_IP_CHANGED", f"{nom} : {x['ip']} au lieu de {adresses[nom]}")
    for s in ctx.series("memoire_noeuds") or []:
        if s["valeur"] < NOEUD_MEMOIRE_MIN:
            nom = s["etiquettes"].get("node") or s["etiquettes"].get("instance")
            j.ajouter("NODE_MEMORY_LOW", f"{nom} : {s['valeur'] / 2**20:.0f} Mi disponibles")
    for s in ctx.series("disque_utilise_pct") or []:
        if s["valeur"] > NOEUD_DISQUE_MAX_PCT:
            nom = s["etiquettes"].get("node") or s["etiquettes"].get("instance")
            j.ajouter("NODE_DISK_FULL", f"{nom} : {s['valeur']:.0f} % > {NOEUD_DISQUE_MAX_PCT:.0f} %")
    ctx.series("noeuds_prets")   # une requête en erreur reste une mesure impossible


def juger_reglage(ctx):
    """Le retard de 140 ms sur chaque réplique en marche du consommateur.
    consommateur.sh verifier d'abord (0 OK, 1 manque, 3 remplacé par la panne) ;
    s'il ne sait pas répondre (ancienne version : « Usage », code 2), la garde lit
    elle-même le retard posé, dans les podnetworkchaos. La nouvelle version rend
    aussi 1 quand l'API ne répond pas : ce n'est pas un manque, c'est une mesure
    impossible."""
    j, ligne = ctx.jugement, ctx.ligne
    verifier = ctx.partie("verifier")
    code = verifier.get("code")
    lignes = [compact(l) for l in verifier.get("lignes", [])]
    if code == 0:
        ligne["reglage_140ms"] = "ok"
        return
    if code == 1 and any("ne répond pas" in l for l in lignes):
        ligne["reglage_140ms"] = "?"
        j.echec("verifier", "consommateur.sh verifier : l'API Kubernetes ne répond pas")
        return
    if code == 1:
        ligne["reglage_140ms"] = "manque"
        j.ajouter("BASE_DELAY_MISSING", ("consommateur.sh verifier : " + " / ".join(lignes))[:200])
        return
    if code == 3:
        ligne["reglage_140ms"] = "panne"
        j.ajouter("BASE_DELAY_REPLACED", "consommateur.sh verifier rend 3")
        return
    if "erreur" in verifier:
        pourquoi = compact(verifier["erreur"])
    elif code == 2 and any(l.startswith("Usage") for l in lignes):
        pourquoi = "ancienne version (répond « Usage », code 2)"
    else:
        pourquoi = (f"code {code} : " + " / ".join(lignes))[:120]
    j.ajouter("VERIFIER_UNAVAILABLE", pourquoi + " ; retard lu dans podnetworkchaos")
    pnc, pods = ctx.partie("podnetworkchaos"), ctx.partie("pods")
    if "pods" not in pnc or "pods" not in pods:
        ligne["reglage_140ms"] = "?"
        return
    repliques = [p["nom"] for p in pods["pods"] if p["nom"].startswith("ts-delivery-service-")
                 and p["phase"] == "Running" and not p["en_arret"]]
    manque = []
    for r in repliques:
        retards = (pnc["pods"].get(r) or {}).get("retards", [])
        if ctx.en_panne and retards:
            continue   # pendant une panne, un autre retard peut remplacer le réglage
        if not any(x.get("source") == REGLAGE_SOURCE and x.get("latence") == RETARD_BASE for x in retards):
            manque.append(r)
    if not repliques or manque:
        ligne["reglage_140ms"] = f"manque:{len(manque)}/{len(repliques)}"
        j.ajouter("BASE_DELAY_MISSING", "sans 140 ms : " + (", ".join(manque) or "aucune réplique en marche"))
    else:
        ligne["reglage_140ms"] = "ok"


def juger_collecte(ctx):
    """La passerelle de collecte, puis S3. S3 n'est jugé qu'avec une vérification
    faite 2 min au moins après que la passerelle est devenue prête : au départ
    d'une campagne, le dernier objet date d'avant la collecte, ce n'est pas un trou."""
    j, mem, s3 = ctx.jugement, ctx.mem, ctx.s3
    passerelle = ctx.partie("passerelle")
    prete = None
    if "erreur" in passerelle:
        j.echec("passerelle", passerelle["erreur"])
    else:
        voulues, pretes = passerelle["voulues"], passerelle["pretes"]
        prete = voulues >= 1 and pretes >= voulues
        if not prete and ctx.pilote_vivant:
            j.ajouter("GATEWAY_DOWN", f"passerelle {pretes}/{voulues} pendant une campagne")
        elif voulues >= 1 and not prete:
            j.ajouter("GATEWAY_NOT_READY", f"passerelle {pretes}/{voulues}")
        if prete and mem.get("passerelle_prete") is False:
            # La collecte vient de se mettre en route : vérifier S3 dans 2 min.
            mem["passerelle_prete_depuis"] = texte_minute(ctx.minute)
            mem["s3_a_faire"] = texte_minute(ctx.minute + timedelta(minutes=S3_APRES_PASSERELLE_MIN))
        mem["passerelle_prete"] = prete
    if not s3:
        return
    ctx.ligne["s3_age_s"] = nombre(s3.get("age_s"))
    if not prete:
        return
    depuis = mem.get("passerelle_prete_depuis")
    verifie = lire_instant(s3.get("verifie_a"))
    if depuis and (verifie is None or
                   verifie < lire_minute(depuis) + timedelta(minutes=S3_APRES_PASSERELLE_MIN)):
        return   # vérification trop tôt après la mise en route : pas de jugement
    if "erreur" in s3:
        j.echec("s3", s3["erreur"])
    elif s3.get("age_s") is None:
        j.ajouter("S3_STALE", "aucun objet aujourd'hui")
    elif s3["age_s"] > S3_AGE_MAX_S:
        j.ajouter("S3_STALE", f"dernier objet il y a {s3['age_s']} s (vérifié à {s3.get('verifie_a')})")


def juger_pannes_restees(ctx):
    """Objets Chaos Mesh restés, non déclarés, ou retard posé par un objet disparu ;
    la proposition « retirer » (et le geste, avec --agir) nomme l'objet en cause."""
    j, objets = ctx.jugement, ctx.objets
    # Ce qui agit sur le master (la sonde le lit dans /proc) : liste, ou inconnu.
    gestes = (ctx.mesure or {}).get("gestes_en_cours")
    ctx.gestes_connus = isinstance(gestes, list)
    ctx.panne_agit = ctx.gestes_connus and any(g.startswith("panne.sh") for g in gestes)
    en_retard, non_declares, fautifs_retard = [], [], []
    for o in objets:
        nom = f"{o['type']}/{o['nom']}"
        d, cree = duree_secondes(o.get("duree")), lire_instant(o.get("creation"))
        if not ctx.etat_present:
            non_declares.append(nom)
        if d is not None and cree is not None and (ctx.t - cree).total_seconds() > d + PANNE_MARGE_MIN * 60:
            en_retard.append(f"{nom} (posé à {o['creation']}, durée {o['duree']})")
            fautifs_retard.append(nom)
    # panne.etat lui-même, plus vieux que sa durée déclarée + 2 min. Pendant qu'un
    # « panne.sh » agit (le retrait du pilote, ou du minuteur, peut durer 10 min :
    # rollout de consumer-slowdown), c'est seulement noté : le retrait est en route.
    etat_en_retard = None
    if ctx.etat_present and ctx.panne_debut is not None and ctx.panne_duree_min is not None:
        fin = ctx.panne_debut + timedelta(minutes=ctx.panne_duree_min + PANNE_MARGE_MIN)
        if ctx.t > fin:
            etat_en_retard = (f"panne.etat « {ctx.ligne['panne_declaree']} » (posé à "
                              f"{texte_minute(ctx.panne_debut)}, durée {ctx.panne_duree_min:g} min)")
            if ctx.panne_agit and not en_retard:
                j.noter("FAULT_OVERDUE", f"{etat_en_retard} ; un « panne.sh » agit déjà sur le master")
            else:
                en_retard.append(etat_en_retard)
                fautifs_retard.append("panne.etat")
    # L'objet nommé dans la proposition : le premier qui n'est pas l'objet de base
    # (celui-là n'est jamais retiré ; la garde refusera le geste s'il est seul).
    for code, noms in (("FAULT_OVERDUE", fautifs_retard), ("CHAOS_UNDECLARED", non_declares)):
        if noms:
            j.fautifs[code] = next((n for n in noms if not est_reglage(n)), noms[0])
    if non_declares:
        j.ajouter("CHAOS_UNDECLARED", ", ".join(non_declares) + " sans panne.etat")
    if en_retard:
        j.ajouter("FAULT_OVERDUE", ", ".join(en_retard))
    panne_etat = ctx.partie("panne_etat")
    if ctx.etat_present and not ctx.pilote_vivant:
        c = panne_etat.get("contenu") or {}
        j.ajouter("FAULT_ORPHANED", f"panne « {c.get('CAUSE', '?')} » depuis {c.get('DEBUT', '?')}, aucun pilote")
    pnc = ctx.partie("podnetworkchaos")
    if "erreur" in pnc:
        j.echec("podnetworkchaos", pnc["erreur"])
    elif "erreur" not in ctx.partie("chaos"):
        # Chaos Mesh nettoie les podnetworkchaos après coup : 2 minutes de suite.
        noms = {f"{o['espace']}/{o['nom']}" for o in objets}
        restes = sorted({s for p in pnc["pods"].values() for s in p["sources"]
                         if s != REGLAGE_SOURCE and s not in noms})
        if restes:
            confirmer(ctx, "CHAOS_RESIDUE", "retard encore posé par : " + ", ".join(restes), CONFIRMATION_MIN)
    # Proposition « retirer » : seulement si aucun panne.sh n'agit déjà. Si la sonde
    # n'a pas pu le dire, la proposition reste écrite, mais le geste attendra.
    for code in ("FAULT_OVERDUE", "FAULT_ORPHANED", "CHAOS_UNDECLARED"):
        if code in j.causes and not ctx.panne_agit:
            objet = j.fautifs.get(code)
            ctx.propositions["retirer"] = f"retirer:{code}" + (f":{objet}" if objet else "")
            break


def est_reglage(nom):
    """« Type/consommateur-temps-de-service » : l'objet du réglage de base."""
    return nom.rsplit("/", 1)[-1] == REGLAGE_NOM


def voyageurs_reference(ctx):
    """N pour le seuil d'effondrement : pendant une panne déclarée, les voyageurs
    demandés du dernier palier écrit AVANT son début (paliers.tsv : une panne de
    charge y écrit sa propre demande, plus haute) ; sinon le palier courant. Le nom
    de la panne n'est pas lu. Rend (N, d'où il vient)."""
    if ctx.etat_present and ctx.panne_debut is not None and ctx.historique_paliers:
        debut = ctx.panne_debut.strftime("%Y-%m-%dT%H:%M:%SZ")
        avant = [n for instant, n in ctx.historique_paliers if instant < debut and n is not None]
        if avant:
            return avant[-1], "palier d'avant la panne"
    return ctx.voyageurs_demandes, "palier courant"


def juger_effondrement(ctx):
    """Pendant une campagne, un effondrement qui dure 10 min → proposer « term ».
    Locust est effondré sous min(5 req/s ; 0,2 × N). Ce sont des minutes MESURÉES
    de suite (comme confirmer) : la série repart à zéro si la minute d'avant n'a
    pas été jugée effondrée (master muet, garde arrêtée, trou), ou si le pilote
    change (autre pid ou autre date de démarrage) : c'est une autre campagne."""
    j, mem = ctx.jugement, ctx.mem
    motif = None
    if ctx.pilote_vivant:
        n, source = voyageurs_reference(ctx)
        seuil = None
        if n is not None and n >= VOYAGEURS_MIN_DEBIT:
            seuil = min(EFFONDREMENT_REQ_S, EFFONDREMENT_REQ_S_PAR_VOYAGEUR * n)
        ctx.effondrement = {"n": n, "source": source, "seuil_req_s": seuil, "req_s": ctx.req_s}
        if seuil is not None and ctx.req_s is not None and ctx.req_s < seuil:
            motif = "LOCUST_COLLAPSE"
        elif "ORDER_FROZEN" in j.causes:
            motif = "ORDER_FROZEN"
        elif "NODE_NOT_READY" in j.causes:
            motif = "NODE_NOT_READY"
    if motif:
        pilote = ctx.local.get("pilote", {})
        qui = [pilote.get("pid"), pilote.get("debut")]
        hier = texte_minute(ctx.minute - timedelta(minutes=1))
        if mem.get("effondrement_pilote") != qui or mem.get("effondrement_minute") != hier:
            mem["effondrement_depuis"] = None   # pas la minute d'avant : la série repart
        mem["effondrement_pilote"] = qui
        mem["effondrement_minute"] = texte_minute(ctx.minute)
        depuis = lire_minute(mem.get("effondrement_depuis") or texte_minute(ctx.minute))
        mem["effondrement_depuis"] = texte_minute(depuis)
        # Chaque minute de depuis à maintenant a été jugée effondrée : 10 min d'écart
        # = 11 minutes mesurées de suite.
        if (ctx.minute - depuis).total_seconds() >= EFFONDREMENT_MIN * 60:
            ctx.propositions["term"] = f"term:{motif}"
    else:
        mem["effondrement_depuis"] = mem["effondrement_minute"] = None


def mettre_en_notes_pendant_panne(ctx):
    """Une baisse de débit (d) est attendue pendant une panne et juste après un
    changement de palier ; le tas (t) pendant une panne et jusqu'à 25 min après.
    Ces codes passent dans les notes au lieu de rendre la minute MALADE."""
    j = ctx.jugement
    for code in list(j.causes):
        c = classe(code)
        if (c == "d" and (ctx.en_panne or ctx.palier_recent)) or (c == "t" and (ctx.en_panne or ctx.apres_panne)):
            j.mettre_en_note(code)
    debits_notes = any(classe(c) == "d" for c in j.notes)
    if ctx.palier_recent and debits_notes and not ctx.en_panne:
        j.noter("PALIER_SETTLING", "palier changé il y a moins de 3 min, ou Locust en train de changer")


# ------------------------------------------------------------------------------
# La garde : état, fichiers, boucle
# ------------------------------------------------------------------------------
ARRET = threading.Event()   # posé par Ctrl-C ou TERM : finir la minute en cours, puis s'arrêter
LEGENDE = ("# alertes.txt de la garde (heures UTC) : DEBUT/FIN <niveau> <code> quand une cause "
           "apparaît/disparaît (MALADE, DOUTEUX, NOTE) ; PROPOSITION (avec le mode : [AGIR] ou "
           "[PROPOSE], et pourquoi aucun geste ne suit) ; ACTION DEBUT/FIN/REFUS/MAJ <geste> (retirer, "
           "term, pause) ; NIVEAU 3 — DÉCISION HUMAINE NÉCESSAIRE ; INFO. Une cause non mesurée reste "
           "ouverte (pas de FIN), sauf quand la mémoire est remise à neuf : FIN « fermée sans mesure ».")
MODES = {True: "AGIR (--agir : gestes du niveau 1 selon les règles, voir les lignes ACTION)",
         False: "PROPOSE (sans --agir : aucun geste sur le cluster ni sur le pilote)"}
MODES_COURTS = {True: "[AGIR]", False: "[PROPOSE : sans --agir, aucun geste]"}


class Garde:
    def __init__(self, dossier, sans_s3, agir=False):
        self.dossier = dossier
        self.sans_s3 = sans_s3
        self.agir = agir
        os.makedirs(dossier, exist_ok=True)
        # Le verrou d'abord : une seconde garde ne doit RIEN écrire (pas même
        # mettre de côté un garde.tsv aux colonnes changées).
        self.verrouiller()
        self.tsv = os.path.join(dossier, "garde.tsv")
        self.alertes = os.path.join(dossier, "alertes.txt")
        self.dernier = os.path.join(dossier, "dernier.json")
        self.f_memoire = os.path.join(dossier, "memoire.json")
        self.f_reference = os.path.join(dossier, "reference.json")
        self.f_actions = os.path.join(dossier, "actions.tsv")
        self.f_pause = os.path.join(dossier, "pause")
        self.d_gestes = os.path.join(dossier, "gestes")
        self.geste_proc = None                # le retrait lancé par CE processus (boucle)
        self.mem = lire_json(self.f_memoire, None)
        if self.mem is None:   # absent ou illisible : une mémoire neuve
            self.mem = {}
            self.fermer_alertes_perdues(None, "memoire.json absent ou illisible au départ")
        self.ref = lire_json(self.f_reference, {})
        self.s3_fil = None
        self.s3_resultat = None
        self.verrou_s3 = threading.Lock()
        self.preparer_tsv()

    # ------------------------------------------------------------ verrou
    def verrouiller(self):
        self.f_verrou = open(os.path.join(self.dossier, "garde.verrou"), "a+")
        try:
            fcntl.flock(self.f_verrou, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print(f"garde : une autre garde tourne déjà (verrou {self.f_verrou.name}) — rien n'est fait.",
                  file=sys.stderr)
            sys.exit(3)
        self.f_verrou.seek(0)
        self.f_verrou.truncate()
        self.f_verrou.write(f"{os.getpid()}\n")
        self.f_verrou.flush()

    # ------------------------------------------------------------ garde.tsv
    def preparer_tsv(self):
        entete = "\t".join(COLONNES)
        if os.path.exists(self.tsv) and os.path.getsize(self.tsv) > 0:
            with open(self.tsv, encoding="utf-8") as f:
                premiere = f.readline().rstrip("\n")
            if premiere == entete:
                return
            # Colonnes changées : l'ancien fichier est mis de côté, jamais mélangé.
            cote = f"{self.tsv}.{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.ancien"
            os.replace(self.tsv, cote)
            self.alerter(f"{texte_minute(maintenant())}  INFO   colonnes changées : ancien fichier → {cote}")
        with open(self.tsv, "w", encoding="utf-8") as f:
            f.write(entete + "\n")

    def derniere_minute_ecrite(self):
        for l in reversed(dernieres_lignes(self.tsv, 3)):
            c = l.split("\t", 1)[0]
            try:
                return lire_minute(c)
            except ValueError:
                continue
        return None

    def ecrire_ligne(self, ligne):
        with open(self.tsv, "a", encoding="utf-8") as f:
            f.write("\t".join(str(ligne[c]).replace("\t", " ").replace("\n", " ") for c in COLONNES) + "\n")

    def alerter(self, texte):
        nouveau = not os.path.exists(self.alertes) or os.path.getsize(self.alertes) == 0
        with open(self.alertes, "a", encoding="utf-8") as f:
            if nouveau:
                f.write(LEGENDE + "\n")
            f.write(texte + "\n")

    def sauver_memoire(self):
        ecrire_atomique(self.f_memoire, json.dumps(self.mem, ensure_ascii=False, indent=1))

    # ------------------------------------------------------------ S3, en arrière-plan
    def s3_du(self, minute):
        if self.sans_s3:
            return False
        a_faire = self.mem.get("s3_a_faire")   # posé quand la collecte se met en route
        if a_faire and minute >= lire_minute(a_faire):
            return True
        dern = (self.mem.get("s3") or {}).get("minute")
        return not dern or (minute - lire_minute(dern)).total_seconds() >= S3_TOUTES_LES_MIN * 60

    def lancer_s3(self, minute, attendre):
        def travail():
            r = verifier_s3(maintenant())
            with self.verrou_s3:
                self.s3_resultat = r
        self.mem["s3"] = {**(self.mem.get("s3") or {}), "minute": texte_minute(minute)}
        self.mem["s3_a_faire"] = None
        if attendre:
            travail()
        elif not (self.s3_fil and self.s3_fil.is_alive()):
            self.s3_fil = threading.Thread(target=travail, daemon=True)
            self.s3_fil.start()

    def prendre_s3(self):
        with self.verrou_s3:
            if self.s3_resultat is not None:
                self.mem["s3"] = {**(self.mem.get("s3") or {}), "resultat": self.s3_resultat}
                self.s3_resultat = None
        return None if self.sans_s3 else (self.mem.get("s3") or {}).get("resultat")

    # ------------------------------------------------------------ une minute
    def ligne_sans_mesure(self, minute, cause):
        ligne = {c: "" for c in COLONNES}
        ligne.update(minute=texte_minute(minute), etat=MALADE, causes=cause, pause_proposee="0")
        self.mem["contamine"], self.mem["serie_regime"] = True, 0
        self.ecrire_ligne(ligne)

    def combler_trous(self, minute):
        """Chaque minute vide depuis la dernière ligne devient une ligne MEASURE_GAP."""
        derniere = self.derniere_minute_ecrite()
        if derniere is None:
            return
        trou = derniere + timedelta(minutes=1)
        n = 0
        while trou < minute and n < 20160:   # au plus 14 jours d'un coup
            self.ligne_sans_mesure(trou, "MEASURE_GAP")
            self.suivre_alertes(trou, {"MEASURE_GAP": "garde arrêtée ou sonde trop lente"}, {},
                                self.mem.get("proposition") or "", self.mem.get("pause") or "0", "")
            trou += timedelta(minutes=1)
            n += 1

    def suivre_alertes(self, minute, causes, notes, proposition, pause, pause_motif, annonce=""):
        """DEBUT quand un code apparaît, FIN quand il disparaît : une ligne chacun,
        les FIN d'abord. Un code qui disparaît parce qu'il n'a pas été MESURÉ cette
        minute (sonde muette, ou sa requête en échec) reste ouvert, sans FIN."""
        h = texte_minute(minute)
        alertables = {**causes, **{c: d for c, d in notes.items() if c in NOTES_ALERTEES}}
        avant = self.mem.get("alertes") or {}
        aveugle = bool(AVEUGLES & set(causes))
        ratees = {c.split(":", 1)[1] for c in causes if c.startswith("MEASURE_FAILED:")}
        gardes = {}
        for code in sorted(set(avant) - set(alertables)):
            base = code.split(":")[0]
            non_vu = (base not in ("MEASURE_FAILED", "MEASURE_GAP") and
                      ((aveugle and code not in CODES_LOCAUX) or bool(ratees & set(SOURCES.get(base, ())))))
            if non_vu:
                gardes[code] = avant[code]
                continue
            duree = int((minute - lire_minute(avant[code])).total_seconds() // 60)
            self.alerter(f"{h}  FIN    {niveau(code):<7}  {code}  (apparu à {avant[code]}, {duree} min)")
        for code in sorted(set(alertables) - set(avant)):
            base = code.split(":")[0]
            detail = alertables[code]
            self.alerter(f"{h}  DEBUT  {niveau(code):<7}  {code}  {CODES[base][2]}" + (f" — {detail}" if detail else ""))
        self.mem["alertes"] = {**gardes, **{c: avant.get(c, h) for c in alertables}}
        if proposition != (self.mem.get("proposition") or ""):
            self.alerter(f"{h}  PROPOSITION niveau 1 : {proposition or 'plus rien'} — {MODES_COURTS[self.agir]}"
                         + (f" ({annonce})" if proposition and annonce else ""))
            self.mem["proposition"] = proposition
        if pause != (self.mem.get("pause") or "0"):
            if pause != "1":
                texte = "plus de pause proposée"
            elif os.path.exists(self.f_pause) and self.lire_drapeau().get("POSE_PAR") != "garde":
                texte = f"oui — {pause_motif} (drapeau posé à la main déjà présent : laissé tel quel)"
            else:
                texte = f"oui — {pause_motif} (voir la ligne ACTION pause)"
            self.alerter(f"{h}  PROPOSITION pause : {texte}")
            self.mem["pause"] = pause

    def suivre_fins(self, minute, fins):
        """Chaque nouvelle ligne FIN_CAMPAGNE de fins.tsv, une fois, dans alertes.txt."""
        vue = self.mem.get("fin_vue")
        nouvelles = fins[fins.index(vue) + 1:] if vue in fins else (fins if vue is not None else [])
        for l in nouvelles:
            self.alerter(f"{texte_minute(minute)}  INFO   " + l.replace("\t", " "))
        if fins:
            self.mem["fin_vue"] = fins[-1]

    def regime(self, jugement):
        """La minute est-elle « en régime » : aucune cause MALADE, file sans message
        prêt, débit de Locust sur la minute ≥ 80 % de l'attendu (sans objet sous 5
        voyageurs) ?"""
        if jugement.malade():
            return False
        r = self.mem.get("regime_mesure") or {}
        if r.get("pret") is None or r["pret"] > 0:
            return False
        n = r.get("n_dem")
        if n is None:
            return False
        if n < VOYAGEURS_MIN_DEBIT:
            return True
        return r.get("req_s") is not None and r["req_s"] >= PART_DEBIT_MIN * REQ_S_PAR_VOYAGEUR * n

    def faire_minute(self, minute, attendre_s3):
        debut = time.monotonic()
        local = mesures_locales(maintenant())
        if self.s3_du(minute):
            self.lancer_s3(minute, attendre=attendre_s3)
        # Les commandes en table : une minute sur dix (un kubectl exec dans MySQL).
        essai = self.mem.get("commandes_essai")
        avec_commandes = not essai or (minute - lire_minute(essai)).total_seconds() >= COMMANDES_TOUTES_LES_MIN * 60
        mesure, echec = mesurer_master(avec_commandes)
        if avec_commandes and mesure is not None:
            self.mem["commandes_essai"] = texte_minute(minute)
        s3 = self.prendre_s3()
        ctx = etiqueter(minute, mesure, echec, local, s3, self.mem, self.ref)
        self.conclure(ctx, time.monotonic() - debut)

    def conclure(self, ctx, duree):
        j, ligne, prop = ctx.jugement, ctx.ligne, ctx.propositions
        causes, notes = dict(j.causes), dict(j.notes)
        malade = j.malade()
        # Contamination : après une minute MALADE, les suivantes le restent tant
        # que 5 minutes de suite ne sont pas en régime (la 5e est la première OK).
        if malade:
            self.mem["contamine"], self.mem["serie_regime"] = True, 0
        elif self.mem.get("contamine"):
            self.mem["serie_regime"] = self.mem.get("serie_regime", 0) + 1 if self.regime(j) else 0
            if self.mem["serie_regime"] >= REGIME_MINUTES:
                self.mem["contamine"], self.mem["serie_regime"] = False, 0
            else:
                causes["RECOVERING"] = f"{self.mem['serie_regime']}/{REGIME_MINUTES} minutes en régime"
                malade = True
        ligne["etat"] = MALADE if malade else (DOUTEUX if causes else "OK")
        ligne["causes"] = ",".join(sorted(causes))
        ligne["notes"] = ",".join(sorted(notes))
        proposition = prop["term"] or prop["retirer"] or ""
        ligne["action_niveau1_proposee"] = proposition
        ligne["pause_proposee"] = "1" if prop["pause"] else "0"
        ligne["pause_motif"] = ",".join(prop["pause"])
        self.mem.pop("repartie_a", None)   # une minute jugée : la mémoire marche
        if ctx.mesure is not None:
            self.compter_suites(ctx)   # avant l'alerte : elle dit dans combien de minutes un geste suivrait
        self.suivre_alertes(ctx.minute, causes, notes, proposition, ligne["pause_proposee"], ligne["pause_motif"],
                            self.annoncer_geste(ctx) if self.agir else "")
        # Le drapeau, puis les gestes : la ligne de la minute dit ce qui a été fait.
        ligne["action_niveau1_faite"] = ",".join(self.gestes_proteges(ctx))
        self.ecrire_ligne(ligne)
        self.suivre_fins(ctx.minute, ctx.local.get("fins", []))
        self.sauver_memoire()
        ecrire_atomique(self.f_reference, json.dumps(self.ref, ensure_ascii=False, indent=1))
        ecrire_atomique(self.dernier, json.dumps(
            {"minute": ligne["minute"], "etat": ligne["etat"], "causes": causes, "notes": notes,
             "ligne": ligne, "mode": "agir" if self.agir else "propose", "effondrement": ctx.effondrement,
             "gestes": {c: self.mem.get(c) for c in ("geste", "incident_retrait", "term_envoye", "drapeau_pause")},
             "mesure": ctx.mesure, "local": ctx.local, "s3": ctx.s3, "duree_s": round(duree, 1),
             "ecrit_a": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
            ensure_ascii=False, indent=1))
        print(f"{ligne['minute']}  {ligne['etat']:<7} {ligne['causes'] or '-'}"
              + (f"   notes: {ligne['notes']}" if ligne["notes"] else "")
              + (f"   [{proposition}]" if proposition else "")
              + (f"   [fait: {ligne['action_niveau1_faite']}]" if ligne["action_niveau1_faite"] else "")
              + (f"   [pause: {ligne['pause_motif']}]" if prop["pause"] else ""), flush=True)

    # ------------------------------------------------------------ les gestes (K1.6b)
    def tracer(self, geste, motif, cible, resultat, duree_s=None):
        """Une ligne dans actions.tsv (un geste, ou un changement du drapeau)."""
        nouveau = not os.path.exists(self.f_actions) or os.path.getsize(self.f_actions) == 0
        champs = [maintenant().strftime("%Y-%m-%dT%H:%M:%SZ"), geste, motif, cible, resultat,
                  f"{duree_s:.1f}" if isinstance(duree_s, (int, float)) else ""]
        with open(self.f_actions, "a", encoding="utf-8") as f:
            if nouveau:
                f.write("\t".join(COLONNES_ACTIONS) + "\n")
            f.write("\t".join(compact(c).replace("\t", " ") for c in champs) + "\n")

    def refuser(self, h, geste, motif, cible, raison, deja, lisible=None):
        """Un geste NON fait, dit une fois (deja : les raisons déjà dites pour ce cas).
        lisible : la cible pour alertes.txt ; actions.tsv garde la cible brute."""
        if raison in deja:
            return
        deja.append(raison)
        del deja[:-20]
        self.alerter(f"{h}  ACTION REFUS  {geste:<8} {raison} (motif={motif} cible={lisible or cible})")
        self.tracer(geste, motif, cible, f"refuse:{raison}")

    def gestes_proteges(self, ctx):
        """Le drapeau, le suivi des gestes en cours et, avec --agir, les nouveaux
        gestes. Une erreur ici ne coûte jamais la ligne de la minute."""
        try:
            return self.gestes(ctx)
        except Exception as e:
            print(f"garde : erreur dans les gestes à {texte_minute(ctx.minute)} :", file=sys.stderr)
            traceback.print_exc()
            self.alerter(f"{texte_minute(ctx.minute)}  INFO   erreur dans les gestes : "
                         + compact(f"{type(e).__name__}: {e}")[:200])
            return []

    def gestes(self, ctx):
        h = texte_minute(ctx.minute)
        faites = []
        self.suivre_pause(ctx, h)                  # niveau 0 : avec ou sans --agir
        # Un geste lancé plus tôt est suivi jusqu'au bout, même si la garde a été
        # relancée depuis sans --agir.
        faites.append(self.suivre_retrait(h))
        self.suivre_term(h)
        if ctx.mesure is not None:
            self.fermer_incident(ctx, h)           # avec ou sans --agir
            if self.agir:
                faites.append(self.decider_retrait(ctx, h))
                faites.append(self.decider_term(ctx, h))
        return [f for f in faites if f]

    def annoncer_geste(self, ctx):
        """Mode AGIR : ce qui suivra la proposition, quand aucun geste ne la suit tout
        de suite (dit dans la ligne PROPOSITION, pour ne pas laisser croire la garde cassée)."""
        prop = ctx.propositions
        if prop["term"]:
            return "voir les lignes ACTION"
        if not prop["retirer"]:
            return ""
        causes, suites = ctx.jugement.causes, self.mem.get("suites_gestes") or {}
        if "FAULT_OVERDUE" in causes:
            code = "FAULT_OVERDUE"
        elif "CHAOS_UNDECLARED" in causes and not ctx.pilote_vivant:
            code = "CHAOS_UNDECLARED"
        elif "CHAOS_UNDECLARED" in causes:
            return "pas de geste : un pilote vit ; CHAOS_UNDECLARED n'est retiré que sans pilote"
        else:
            return ("pas de geste : dans sa durée déclarée, le minuteur de panne.sh retire la panne ; "
                    f"au-delà (+ {PANNE_MARGE_MIN} min) elle devient FAULT_OVERDUE")
        reste = RETRAIT_CONFIRMATION_MIN[code] - (suites.get(code) or {}).get("n", 0)
        if reste > 0:
            return f"geste dans {reste} min si confirmé"
        return "voir les lignes ACTION"

    # --------------------------------------------- le drapeau de pause (niveau 0)
    def lire_drapeau(self):
        res = {}
        try:
            with open(self.f_pause, encoding="utf-8") as f:
                for l in f:
                    cle, sep, val = l.rstrip("\n").partition("=")
                    if sep:
                        res[cle] = val
        except OSError:
            pass
        return res

    def suivre_pause(self, ctx, h):
        """Pose (ou remet à jour) le drapeau quand pause_proposee=1 ; l'efface quand
        la condition a disparu 2 minutes MESURÉES de suite. Un drapeau posé à la main
        (sans POSE_PAR=garde) n'est jamais touché."""
        motifs = ctx.propositions["pause"]
        etat = self.mem.get("drapeau_pause")
        present = os.path.exists(self.f_pause)
        if present and self.lire_drapeau().get("POSE_PAR") != "garde":
            return
        if present and not etat:   # posé par la garde, mémoire perdue depuis
            lu = self.lire_drapeau()
            etat = {"depuis": lu.get("DEPUIS", "?"), "motifs": lu.get("MOTIFS", "").split(","), "absente": 0}
        instant = maintenant().strftime("%Y-%m-%dT%H:%M:%SZ")
        if motifs:
            valeurs = []
            for m in motifs:
                col = PAUSE_VALEURS.get(m)
                v = f"{col}={ctx.ligne.get(col)}" if col and ctx.ligne.get(col) else None
                if v and v not in valeurs:
                    valeurs.append(v)
            depuis = etat["depuis"] if etat else instant
            ecrire_atomique(self.f_pause, f"POSE_PAR=garde\nDEPUIS={depuis}\nINSTANT={instant}\n"
                                          f"MOTIFS={','.join(motifs)}\nVALEURS={','.join(valeurs)}\n")
            texte = ",".join(motifs) + (f" ({', '.join(valeurs)})" if valeurs else "")
            if not etat:
                self.alerter(f"{h}  ACTION DEBUT  pause    drapeau posé ({self.f_pause}) — {texte} ; "
                             "serie.sh ne lance plus de campagne")
                self.tracer("pause", ",".join(motifs), self.f_pause, "posee")
            elif sorted(etat.get("motifs") or []) != sorted(motifs):
                self.alerter(f"{h}  ACTION MAJ    pause    motifs du drapeau changés : {texte}")
                self.tracer("pause", ",".join(motifs), self.f_pause, "motifs")
            self.mem["drapeau_pause"] = {"depuis": depuis, "motifs": list(motifs), "absente": 0}
            return
        if not etat:
            return
        # Une minute sans mesure (master muet, CPU illisible) ne prouve rien : la série repart.
        mesuree = ctx.mesure is not None and "MEASURE_FAILED:prom_cpu_commandes" not in ctx.jugement.causes
        etat["absente"] = etat.get("absente", 0) + 1 if mesuree else 0
        if etat["absente"] >= PAUSE_EFFACER_APRES_MIN:
            if present:
                os.remove(self.f_pause)
            self.alerter(f"{h}  ACTION FIN    pause    drapeau effacé : condition absente {etat['absente']} "
                         f"minutes mesurées de suite (posé à {etat['depuis']})")
            self.tracer("pause", ",".join(etat.get("motifs") or []), self.f_pause, "effacee")
            self.mem["drapeau_pause"] = None
        else:
            self.mem["drapeau_pause"] = etat

    # --------------------------------------------- retirer une panne restée (niveau 1)
    def compter_suites(self, ctx):
        """Depuis combien de minutes mesurées de suite chaque déclencheur est là."""
        suites = self.mem.setdefault("suites_gestes", {})
        hier = texte_minute(ctx.minute - timedelta(minutes=1))
        for code in RETRAIT_CONFIRMATION_MIN:
            if code in ctx.jugement.causes:
                prec = suites.get(code) or {}
                n = prec.get("n", 0) + 1 if prec.get("minute") == hier else 1
                suites[code] = {"n": n, "minute": texte_minute(ctx.minute)}
            else:
                suites.pop(code, None)

    def fermer_incident(self, ctx, h):
        """Incident clos (avec ou sans --agir) : rien de resté, vu par une mesure de
        Chaos Mesh et de panne.etat, et aucun retrait en cours."""
        incident = self.mem.get("incident_retrait")
        if (incident and not any(c in ctx.jugement.causes for c in RETRAIT_CODES) and not self.mem.get("geste")
                and not ({"chaos", "panne_etat"} & ctx.jugement.mesures_ratees())):
            self.alerter(f"{h}  INFO   panne restée : plus rien à retirer (incident ouvert à {incident['debut']}, "
                         f"{len(incident['tentatives'])} retrait(s) lancé(s))")
            self.mem["incident_retrait"] = None

    def decider_retrait(self, ctx, h):
        """Lancer « panne.sh retirer » ? Rend « retirer:en_cours » si oui."""
        mem, causes = self.mem, ctx.jugement.causes
        incident = mem.get("incident_retrait")
        if not any(c in causes for c in RETRAIT_CODES):
            return None
        suites = mem.get("suites_gestes") or {}
        def confirme(code):
            return code in causes and (suites.get(code) or {}).get("n", 0) >= RETRAIT_CONFIRMATION_MIN[code]
        if confirme("FAULT_OVERDUE"):
            motif = "FAULT_OVERDUE"
        elif confirme("CHAOS_UNDECLARED") and not ctx.pilote_vivant:
            motif = "CHAOS_UNDECLARED"
        else:
            return None   # FAULT_ORPHANED seul (le minuteur de panne.sh s'en charge), ou pas encore confirmé
        cible = ctx.jugement.fautifs.get(motif, "")
        lisible = (f"panne déclarée « {ctx.ligne['panne_declaree']} » (panne.etat)" if cible == "panne.etat"
                   else cible)
        if incident is None:
            incident = mem["incident_retrait"] = {"debut": h, "tentatives": [], "refus": [], "humain": False}
        if mem.get("geste"):
            return None   # un seul geste à la fois : celui en cours est suivi
        term = mem.get("term_envoye") or {}
        # La fenêtre du pilote : de DEBUT à DEBUT + DUREE + 2 min (panne.etat). Tant
        # qu'elle dure, c'est à lui de retirer, QUEL QUE SOIT le motif : « panne.sh
        # retirer » lève la panne de panne.etat, pas l'objet en cause.
        fenetre_inconnue = ctx.pilote_vivant and ctx.etat_present and (
            ctx.panne_debut is None or ctx.panne_duree_min is None)
        dans_fenetre = (ctx.pilote_vivant and not fenetre_inconnue and ctx.etat_present
                        and ctx.t <= ctx.panne_debut + timedelta(minutes=ctx.panne_duree_min + PANNE_MARGE_MIN))
        raison = None
        if est_reglage(cible):
            raison = "l'objet de base (140 ms) : jamais retiré par la garde"
        elif not ctx.gestes_connus:
            raison = "la sonde n'a pas pu dire ce qui agit sur le master (gestes_en_cours) : on attend"
        elif ctx.panne_agit:
            raison = "un « panne.sh » agit déjà sur le master : on attend"
        elif fenetre_inconnue:
            raison = "pilote vivant et panne.etat sans DEBUT ou DUREE lisible : fenêtre inconnue, on attend"
        elif dans_fenetre:
            raison = ("le pilote est dans sa fenêtre déclarée (jusqu'à "
                      f"{texte_minute(ctx.panne_debut + timedelta(minutes=ctx.panne_duree_min + PANNE_MARGE_MIN))}) : "
                      "c'est à lui de retirer")
        elif term and not term.get("fini"):
            raison = "le pilote a reçu TERM et fait son nettoyage (dont le retrait) : on attend"
        if raison:
            self.refuser(h, "retirer", motif, cible, raison, incident["refus"], lisible)
            return None
        tentatives = incident["tentatives"]
        # Plafond global : un objet recréé sans cesse ouvrirait un incident après l'autre.
        lances = [x for x in mem.get("retraits_lances") or []
                  if (lire_instant(x) or ctx.t) > ctx.t - timedelta(hours=RETRAIT_PLAFOND_FENETRE_H)]
        mem["retraits_lances"] = lances
        if len(lances) >= RETRAIT_PLAFOND_GLOBAL and len(tentatives) < RETRAIT_TENTATIVES:
            if not incident["humain"]:
                incident["humain"] = True
                self.alerter(f"{h}  NIVEAU 3 — DÉCISION HUMAINE NÉCESSAIRE : {len(lances)} retraits lancés en "
                             f"{RETRAIT_PLAFOND_FENETRE_H} h (plafond {RETRAIT_PLAFOND_GLOBAL}) ; la garde ne retire "
                             f"plus rien pour cet incident ({motif}, {cible}, ouvert à {incident['debut']})")
                self.tracer("retirer", motif, cible, "decision_humaine")
            return None
        if len(tentatives) >= RETRAIT_TENTATIVES:
            if not incident["humain"]:
                incident["humain"] = True
                self.alerter(f"{h}  NIVEAU 3 — DÉCISION HUMAINE NÉCESSAIRE : la panne est encore là après "
                             f"{len(tentatives)} retraits ({motif}, {cible}) ; la garde ne retire plus rien "
                             f"pour cet incident (ouvert à {incident['debut']})")
                self.tracer("retirer", motif, cible, "decision_humaine")
            return None
        if tentatives:
            fin = lire_instant(tentatives[-1].get("fin_vue"))
            if fin is None or ctx.t < fin + timedelta(minutes=RETRAIT_SECONDE_APRES_MIN):
                return None
        return self.lancer_retrait(h, motif, cible, incident, lisible)

    def lancer_retrait(self, h, motif, cible, incident, lisible=None):
        """« panne.sh retirer » sur le master, dans un sous-processus de la garde, dans
        sa propre session : ni Ctrl-C ni l'arrêt de la garde ne le coupent en route.
        Son résultat est écrit dans gestes/retirer-<instant>.json."""
        os.makedirs(self.d_gestes, exist_ok=True)
        instant = maintenant().strftime("%Y-%m-%dT%H:%M:%SZ")
        base = os.path.join(self.d_gestes, f"retirer-{instant.replace('-', '').replace(':', '')}-{len(incident['tentatives']) + 1}")
        fichier, journal = base + ".json", base + ".log"
        n = len(incident["tentatives"]) + 1
        incident["tentatives"].append({"lance_a": instant})
        self.mem.setdefault("retraits_lances", []).append(instant)
        lisible = lisible or cible
        try:
            with open(journal, "a", encoding="utf-8") as sortie:
                p = subprocess.Popen([sys.executable, os.path.abspath(__file__), "--geste-retirer", fichier],
                                     stdin=subprocess.DEVNULL, stdout=sortie, stderr=subprocess.STDOUT,
                                     start_new_session=True)
        except OSError as e:
            incident["tentatives"][-1].update(fin_vue=instant, resultat="ECHEC")
            self.alerter(f"{h}  ACTION FIN    retirer  ECHEC — lancement impossible : {e}")
            self.tracer("retirer", motif, cible, f"ECHEC:lancement impossible : {e}")
            self.sauver_memoire()
            return "retirer:ECHEC"
        x = lire_processus(p.pid, "/proc")
        self.geste_proc = p
        self.mem["geste"] = {"geste": "retirer", "pid": p.pid, "debut_proc": x["debut"] if x else None,
                             "fichier": fichier, "journal": journal, "lance_a": instant,
                             "motif": motif, "cible": cible, "lisible": lisible, "tentative": n}
        self.alerter(f"{h}  ACTION DEBUT  retirer  motif={motif} cible={lisible} tentative {n}/{RETRAIT_TENTATIVES} — "
                     f"ssh {SSH_HOTE} « bash {DISTANT}/apps/panne.sh retirer » (plafond local "
                     f"{PLAFOND_GESTE:.0f} s ; sortie : {os.path.relpath(journal, self.dossier)})")
        self.tracer("retirer", motif, cible, "lance")
        self.sauver_memoire()   # tout de suite : un geste lancé ne doit jamais être oublié
        return "retirer:en_cours"

    def suivre_retrait(self, h):
        """Le retrait lancé plus tôt : en cours, ou fini (ok, ECHEC) ?"""
        g = self.mem.get("geste")
        if not g:
            return None
        if self.geste_proc is not None:
            self.geste_proc.poll()   # le récolter s'il est fini (boucle)
        res = lire_json(g["fichier"], None)
        if res is None:
            x = lire_processus(g["pid"], "/proc")
            if x is not None and x["etat"] != "Z" and x["debut"] == g.get("debut_proc"):
                return "retirer:en_cours"
            res = lire_json(g["fichier"], None) or {
                "erreur": "le sous-processus du retrait a disparu sans écrire son résultat"}
        if self.geste_proc is not None:
            # Le résultat est écrit : le sous-processus sort aussitôt. Le récolter
            # (boucle), sans jamais bloquer la minute plus de 5 s.
            try:
                self.geste_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        ok = res.get("code") == 0 and not res.get("erreur")
        resultat = "ok" if ok else "ECHEC"
        detail = "" if ok else compact(res.get("erreur") or f"code {res.get('code')} : {res.get('resume', '')}")[:200]
        duree = res.get("duree_s")
        fin_vue = maintenant()
        suite = ""
        if not ok:
            if g["tentative"] < RETRAIT_TENTATIVES:
                suite = (" ; seconde tentative au plus tôt à "
                         f"{texte_minute(fin_vue + timedelta(minutes=RETRAIT_SECONDE_APRES_MIN))} si la panne est encore là")
            else:
                suite = " ; plus de tentative pour cet incident"
        self.alerter(f"{h}  ACTION FIN    retirer  {resultat}" + (f" — {detail}" if detail else "")
                     + f" (motif={g['motif']} cible={g.get('lisible') or g['cible']}, tentative {g['tentative']}, "
                     + (f"{duree:.0f} s)" if isinstance(duree, (int, float)) else "durée inconnue)") + suite)
        self.tracer("retirer", g["motif"], g["cible"], "ok" if ok else f"ECHEC:{detail}", duree)
        incident = self.mem.get("incident_retrait")
        if incident and incident.get("tentatives"):
            incident["tentatives"][-1].update(fin_vue=fin_vue.strftime("%Y-%m-%dT%H:%M:%SZ"), resultat=resultat)
        self.mem["geste"] = None
        self.geste_proc = None
        return f"retirer:{resultat}"

    # --------------------------------------------- arrêter un pilote effondré (niveau 1)
    def decider_term(self, ctx, h):
        """kill -TERM au pilote ? Rend « term:envoye » si oui."""
        term = ctx.propositions["term"]
        if not term or not ctx.pilote_vivant:
            return None
        p = ctx.local.get("pilote", {})
        pid, nom, debut = p.get("pid_signal"), p.get("nom"), p.get("debut_signal")
        envoye = self.mem.get("term_envoye") or {}
        if envoye.get("pid") == pid and envoye.get("debut") == debut:
            return None   # une seule fois par pilote
        cible = f"campagne.sh {nom or '?'} (pid {pid})"
        # Les refus déjà dits, pour CE pilote : un autre pilote repart de zéro.
        refus = self.mem.get("term_refus")
        if not isinstance(refus, dict) or refus.get("pilote") != [pid, debut]:
            refus = self.mem["term_refus"] = {"pilote": [pid, debut], "raisons": []}
        deja = refus["raisons"]
        if self.mem.get("geste"):
            self.refuser(h, "term", term, cible, "un retrait est en cours (un seul geste à la fois) : on attend", deja)
            return None
        oui, raison = signaler_pilote(pid, nom, debut)
        if not oui:
            self.refuser(h, "term", term, cible, raison, deja)
            return None
        self.mem["term_envoye"] = {"pid": pid, "nom": nom, "debut": debut, "motif": term,
                                   "envoye_a": maintenant().strftime("%Y-%m-%dT%H:%M:%SZ"),
                                   "fini": False, "humain": False}
        self.alerter(f"{h}  ACTION DEBUT  term     SIGTERM envoyé à {cible} — motif {term} ; le pilote retire "
                     "sa panne, revient au premier palier et écrit son compte rendu (jamais de kill -9)")
        self.tracer("term", term, cible, "envoye")
        self.sauver_memoire()
        return "term:envoye"

    def suivre_term(self, h):
        """Après TERM : le pilote s'arrête-t-il ? 45 min plus tard, décision humaine."""
        e = self.mem.get("term_envoye")
        if not e or e.get("fini"):
            return
        cible = f"campagne.sh {e.get('nom') or '?'} (pid {e['pid']})"
        vivant, _ = verifier_pilote(e["pid"], e["nom"], e["debut"])
        envoye = lire_instant(e.get("envoye_a"))
        minutes = (maintenant() - envoye).total_seconds() / 60 if envoye else 0.0
        if not vivant:
            e["fini"] = True
            self.alerter(f"{h}  ACTION FIN    term     {cible} s'est arrêté, {minutes:.0f} min après TERM")
            self.tracer("term", e["motif"], cible, "pilote_arrete", minutes * 60)
        elif minutes >= TERM_HUMAIN_APRES_MIN and not e.get("humain"):
            e["humain"] = True
            self.alerter(f"{h}  NIVEAU 3 — DÉCISION HUMAINE NÉCESSAIRE : {cible} vit encore {minutes:.0f} min "
                         "après TERM ; la garde n'envoie rien d'autre (jamais de kill -9)")
            self.tracer("term", e["motif"], cible, "toujours_vivant:decision_humaine", minutes * 60)

    def annoncer_mode(self):
        """Le mode (AGIR ou PROPOSE) est dit dans alertes.txt quand il change, et
        écrit dans memoire.json à chaque départ (suivi.py le lit sans dernier.json)."""
        mode = "agir" if self.agir else "propose"
        if (self.mem.get("mode") or "propose") != mode:
            self.alerter(f"{texte_minute(maintenant())}  INFO   la garde passe en mode {MODES[self.agir]}")
        if self.mem.get("mode") != mode:
            self.mem["mode"] = mode
            self.sauver_memoire()

    def minute_protegee(self, minute, attendre_s3):
        """Une minute, sans jamais laisser une erreur arrêter la garde."""
        try:
            self.combler_trous(minute)
            self.faire_minute(minute, attendre_s3)
        except Exception as e:
            print(f"garde : erreur imprévue à {texte_minute(minute)} :", file=sys.stderr)
            traceback.print_exc()
            try:
                if self.derniere_minute_ecrite() != minute:
                    self.ligne_sans_mesure(minute, "MEASURE_FAILED:garde")
                    self.suivre_alertes(minute, {"MEASURE_FAILED:garde": compact(f"{type(e).__name__}: {e}")[:200]},
                                        {}, self.mem.get("proposition") or "", self.mem.get("pause") or "0", "")
                    self.sauver_memoire()
            except Exception:   # la mémoire elle-même peut faire échouer suivre_alertes
                traceback.print_exc()
            try:
                self.memoire_cassee()
            except Exception:
                traceback.print_exc()

    def memoire_cassee(self):
        """3 minutes MEASURE_FAILED:garde de suite (vu dans garde.tsv, donc aussi
        après un redémarrage) : memoire.json est sans doute en cause. Il est mis de
        côté et la garde repart d'une mémoire neuve (toujours contaminée)."""
        fins = [l.split("\t") for l in dernieres_lignes(self.tsv, 3)]
        if len(fins) < 3 or any(len(l) < 3 or l[2] != "MEASURE_FAILED:garde" for l in fins):
            return
        if self.mem.get("repartie_a"):
            return   # déjà repartie d'une mémoire neuve : l'erreur vient d'ailleurs
        cote = f"{self.f_memoire}.{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.casse"
        if os.path.exists(self.f_memoire):
            os.replace(self.f_memoire, cote)
        # Les FIN seulement une fois la mémoire neuve en place : si le renommage
        # échoue, rien n'est écrit et la minute suivante réessaie.
        perdue = self.mem
        self.mem = {"contamine": True, "serie_regime": 0, "repartie_a": texte_minute(maintenant()),
                    "mode": "agir" if self.agir else "propose"}
        try:
            self.fermer_alertes_perdues(perdue, "mémoire remise à neuf")
        except Exception:
            traceback.print_exc()
        self.sauver_memoire()
        self.alerter(f"{texte_minute(maintenant())}  INFO   3 minutes en erreur de suite : "
                     f"memoire.json mis de côté ({cote}), mémoire neuve")

    def fermer_alertes_perdues(self, perdue, raison):
        """En repartant d'une mémoire neuve : une ligne FIN pour chaque alerte encore
        ouverte, dans la mémoire perdue OU dans alertes.txt (un DEBUT sans FIN, par
        exemple écrit juste avant un arrêt brutal, avant sauver_memoire). Sinon elle
        resterait ouverte pour toujours (suivi.py y cherche les DEBUT sans FIN).
        Les codes que la mémoire perdue ne connaissait pas (clé absente, illisible,
        ou pas de mémoire du tout) sont dits dans une ligne INFO."""
        m = a_la_minute(maintenant())
        h = texte_minute(m)
        connues = perdue.get("alertes") if isinstance(perdue, dict) else None
        if not isinstance(connues, dict):
            connues = {}   # pas de clé, ou pas un dictionnaire
        fichier = ouvertes_dans_alertes(self.alertes)   # {code: (minute, niveau)}
        oubliees = sorted(set(fichier) - set(connues))
        if oubliees:
            self.alerter(f"{h}  INFO   alertes ouvertes oubliées ({raison}, relues dans alertes.txt) : "
                         + ", ".join(oubliees))
        for code in sorted(set(connues) | set(fichier)):
            d = str(connues[code]) if code in connues else fichier[code][0]
            try:
                niv = niveau(code)
            except KeyError:   # code inconnu : le niveau lu dans alertes.txt
                niv = fichier[code][1] if code in fichier else "?"
            try:
                duree = f", {int((m - lire_minute(d)).total_seconds() // 60)} min"
            except ValueError:
                duree = ""
            self.alerter(f"{h}  FIN    {niv:<7}  {code}  (apparu à {d}{duree} ; fermée sans mesure : {raison})")

    def une_fois(self):
        minute = a_la_minute(maintenant())
        derniere = self.derniere_minute_ecrite()
        if derniere is not None and minute <= derniere:
            print(f"garde : la minute {texte_minute(minute)} est déjà écrite — rien à faire.")
            return
        self.minute_protegee(minute, attendre_s3=True)

    def boucle(self, tours=None):
        fait = 0
        while (tours is None or fait < tours) and not ARRET.is_set():
            minute = a_la_minute(maintenant())
            derniere = self.derniere_minute_ecrite()
            if derniere is None or minute > derniere:
                self.minute_protegee(minute, attendre_s3=False)
                fait += 1
                if tours is not None and fait >= tours:
                    break
            # Dormir jusqu'à la minute suivante (+1 s), en petits morceaux.
            cible = minute + timedelta(minutes=1, seconds=1)
            while maintenant() < cible and not ARRET.is_set():
                ARRET.wait(min(5.0, max(0.2, (cible - maintenant()).total_seconds())))


def executer_retrait(fichier):
    """Le sous-processus d'un retrait (lancé par la garde avec --geste-retirer, dans
    sa propre session). Un seul ssh vers le master, plafond LOCAL PLAFOND_GESTE,
    aucun plafond sur le master. Sa sortie va dans le journal ouvert par la garde ;
    le résultat est écrit d'un coup dans <fichier> (lu par la garde chaque minute)."""
    distant = f"bash {DISTANT}/apps/panne.sh retirer"
    print(f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}  ssh {SSH_HOTE} « {distant} » "
          f"(plafond local {PLAFOND_GESTE:.0f} s)", flush=True)
    t0 = time.monotonic()
    r = lancer(["ssh", *SSH_OPTIONS, SSH_HOTE, distant], PLAFOND_GESTE)
    duree = round(time.monotonic() - t0, 1)
    sortie = (r.get("out") or "") + (r.get("err") or "")
    if sortie:
        print(sortie.rstrip("\n"), flush=True)
    lignes = [compact(l) for l in sortie.splitlines() if l.strip()]
    res = {"code": r.get("code"), "duree_s": duree, "resume": " / ".join(lignes[-2:])[:300],
           "fin": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    if "erreur" in r:
        res["erreur"] = r["erreur"]
    elif r["code"] == 255:   # ssh lui-même : hôte injoignable, clé refusée…
        res["erreur"] = "ssh : " + ((r["err"] or "").strip().splitlines() or ["code 255"])[-1][:200]
    print(f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}  fin : code {res['code']} en {duree} s"
          + (f" — {res['erreur']}" if "erreur" in res else ""), flush=True)
    ecrire_atomique(fichier, json.dumps(res, ensure_ascii=False))
    return 0


def main():
    args = sys.argv[1:]
    if args[:1] == ["--geste-retirer"] and len(args) == 2:
        return executer_retrait(args[1])
    if "-h" in args or "--help" in args:
        with open(__file__, encoding="utf-8") as f:
            for l in f:
                if l.startswith("import"):
                    break
                print(l.rstrip("\n")[2:])
        return 0
    dossier = os.environ.get("GARDE_DOSSIER", os.path.join(ACCUEIL, "journaux-hors-campagne", "garde"))
    if "--dossier" in args:
        dossier = args[args.index("--dossier") + 1]
    tours = int(args[args.index("--tours") + 1]) if "--tours" in args else None
    garde = Garde(os.path.expanduser(dossier), "--sans-s3" in args, "--agir" in args)   # verrou d'abord
    garde.annoncer_mode()
    # Ctrl-C ou TERM : la minute en cours est finie et écrite, puis la garde s'arrête
    # (la sonde tourne dans sa propre session : Ctrl-C ne la coupe pas en route).
    def arreter(signum, _):
        print(f"garde : arrêt demandé (signal {signum}) — fin de la minute en cours.", flush=True)
        ARRET.set()
    signal.signal(signal.SIGTERM, arreter)
    signal.signal(signal.SIGINT, arreter)
    if "--une-fois" in args:
        garde.une_fois()
    else:
        print(f"garde : départ ({texte_minute(maintenant())}), dossier {garde.dossier}, "
              f"sonde {SSH_HOTE}:{DISTANT}, mode {MODES[garde.agir]}", flush=True)
        garde.boucle(tours)
        print("garde : arrêtée.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
