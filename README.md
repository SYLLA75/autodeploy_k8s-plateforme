# autodeploy_k8s — plateforme de mesure

Chaîne complète pour étudier les **fautes de coordination** dans une application
microservices événementielle : réserver des machines, installer Kubernetes,
déployer l'application instrumentée, collecter traces et métriques, et en
fabriquer un **graphe hétérogène temporel** exploitable par un modèle.

Tout est piloté depuis une machine **Ubuntu**, qui ne fait que piloter : elle
n'exécute ni Kubernetes, ni conteneur.

---

## Où le code s'exécute

C'est le principe d'organisation du dépôt : les fichiers sont rangés par
**machine**, pas par sujet.

```
   ┌─ TON NŒUD DE CONTRÔLE ────────────────────────────────┐
   │   deploy.sh      réserve les VMs et installe le cluster│
   │   destroy.sh     détruit tout, poste local compris     │
   │   lib/           les briques que ces deux-là partagent │
   │   graphe_en/     lit le magasin d'objets → figures     │
   │                  et export PyTorch Geometric           │
   └────────────────────────────────────────────────────────┘
                            │  deploy.sh copie apps/ sur le master
                            ▼
   ┌─ LE MASTER DU CLUSTER ─────────────────────────────────┐
   │   apps/*.sh      installent et pilotent l'application  │
   │                  train-ticket · observability ·        │
   │                  instrument · loadgen · collecte ·     │
   │                  chaos · panne                         │
   └────────────────────────────────────────────────────────┘
```

Un `git pull` sur le nœud de contrôle **ne met pas à jour la copie du master**.
Après un changement dans `apps/` :

```bash
git pull && ./deploy.sh --push-scripts
```

`journaux/` apparaît des deux côtés : chaque machine journalise ce qu'elle
exécute.

---

## Par où commencer

| tu veux… | lis |
|---|---|
| partir d'une machine neuve | **[INSTALL.md](INSTALL.md)** — comptes, clés, dépendances |
| lancer une campagne de mesure | **[PROCEDURE.md](PROCEDURE.md)** — de zéro aux figures |
| comprendre les chiffres du graphe | [notes/OBSERVABILITE.md](notes/OBSERVABILITE.md) |
| savoir pourquoi c'est fait ainsi | [notes/CHOIX.md](notes/CHOIX.md) |
| combien de machines, quel gabarit | [notes/DIMENSIONNEMENT.md](notes/DIMENSIONNEMENT.md) |
| l'état des questions ouvertes | [notes/RECOMMANDATIONS.md](notes/RECOMMANDATIONS.md) |
| ce qui a été décidé, quand, et pourquoi | [notes/JOURNAL.md](notes/JOURNAL.md) |

En bref, une fois installé :

```bash
./deploy.sh --app train-ticket        # ~45 à 60 min
```

puis les étapes de `PROCEDURE.md`, et enfin :

```bash
cd graphe_en
python3 -m venv .venv                 # la première fois seulement
./.venv/bin/python run.py             # des données brutes aux figures
```

---

## Structure du dépôt

```
   deploy.sh              point d'entrée : réserve, installe, déploie
   destroy.sh             tout supprimer, y compris les traces locales
   campagne.sh            piloter et enregistrer une campagne de mesure
   .env.example           tous les réglages, commentés — à copier en .env

   lib/                   briques partagées par deploy.sh et destroy.sh
     common.sh              journal, SSH, diagnostic de panne
     slices.sh              la CLI SLICES : authentification, réservation
     cluster.sh             inventaire Kubespray, copie des scripts, capacité

   apps/                  s'exécutent SUR LE MASTER
     train-ticket.sh        l'application étudiée
     observability.sh       collecteurs, Prometheus, Jaeger, magasin d'objets
     instrument.sh          l'agent OpenTelemetry sur chaque service
     loadgen.sh             le générateur de trafic
     consommateur.sh        tailler le consommateur pour sa charge
     donnees.sh             remettre les tables de commandes à zéro
     mysql.sh               parler à la base, partagé par les deux précédents
     collecte.sh            allumer et éteindre l'enregistrement
     chaos.sh               l'injecteur de pannes (Chaos Mesh)
     panne.sh               les quatre pannes : injecter, retirer, consigner
     journal.sh             journal d'exécution, partagé par les précédents

   graphe_en/             s'exécute SUR LE NŒUD DE CONTRÔLE
     run.py                 les 8 étapes, du magasin aux figures
     config.example.yaml    tous les réglages de l'analyse
     README.md              ce que contient le graphe

   notes/                 notes de recherche, pas des modes d'emploi
   figures/               illustrations pour l'article
```

---

## Reproductibilité

Trois versions à figer dans `.env` pour qu'une expérience reste rejouable à
l'identique : `KUBESPRAY_REF`, `OTEL_CHART_VERSION`, `TT_REF`.

`deploy.sh` est ré-entrant : relancé après un échec, il réutilise les VMs
existantes, le clone Kubespray, et ne réinstalle pas une application déjà en
place — sauf `--force-reinstall`.

---

## Références

- SLICES-RI — <https://slices-ri.eu/> · documentation et CLI : <https://doc.slices-ri.eu/>
- Kubespray — <https://github.com/kubernetes-sigs/kubespray>
- Train Ticket — <https://github.com/FudanSELab/train-ticket> ·
  wiki : <https://github.com/FudanSELab/train-ticket/wiki>
- OpenTelemetry Demo — <https://opentelemetry.io/docs/demo/>
- local-path-provisioner — <https://github.com/rancher/local-path-provisioner>
- Helm — <https://helm.sh/docs/>
