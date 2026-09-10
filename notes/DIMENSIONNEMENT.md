# Dimensionnement et ressources


Besoins **mesurés sur les manifestes amont** (somme des `requests`, hors système) :

| Application | Pods | RAM demandée | CPU demandé |
|---|:--:|---:|---:|
| OpenTelemetry Demo | ~20 | ≈ 9 Gio | ≈ 3 vCPU |
| Train Ticket (*quick start*) | 46 + bases | ≈ 17 Gio | ≈ 4,6 vCPU |
| **Les deux** | ~70 | **≈ 26 Gio** | **≈ 8 vCPU** |

À cela s'ajoutent, **sur chaque nœud**, les pods système — Calico, kube-proxy,
CoreDNS, provisionneur de stockage, metrics-server : environ **800 m de CPU et
1 Gio de RAM par nœud**.

> ⚠️ **C'est le CPU qui bloque en premier, pas la mémoire.** Constaté sur le
> banc d'essai local : avec 3 vCPU par worker, train-ticket laisse 32 pods en
> `Pending` avec `0/3 nodes are available: 2 Insufficient cpu`, alors que la
> mémoire n'est qu'à 55 %. Prévois **au moins 6 vCPU par worker** pour
> train-ticket.

Le contrôle de capacité intégré mesure la place **réellement libre** — allouable
moins ce que les pods déjà présents réservent — et non la capacité totale, qui
surestimerait largement le disponible.

Le script applique automatiquement un **profil** (`WORKER_COUNT="auto"`) puis
**mesure la capacité réelle** du cluster après installation et t'avertit si elle
est insuffisante — cas dans lequel des pods resteraient en `Pending`.

### Gabarits disponibles sur `be-gent1-bi-vm1`

Relevé avec `slices bi --site-id be-gent1-bi-vm1 flavor list` :

| Gabarit | vCPU | RAM | Disque racine |
|---|:--:|:--:|:--:|
| `tiny` | 1 | 1 Gio | 10 GB |
| `m1.small` | 1 | 2 Gio | 10 GB |
| `small` | 2 | 4 Gio | 20 GB |
| **`medium`** | **4** | **8 Gio** | **50 GB** |
| `bdt-vm` | 4 | 8 Gio | 75 GB |
| `large` | 4 | 16 Gio | 100 GB |
| `xlarge` | 8 | 32 Gio | 200 GB |

### Vérification des profils par défaut

Avec `medium` (4 vCPU / 8 Gio), en comptant ~1 Gio et ~0,5 vCPU de surcoût
système par nœud :

| Sélection | Profil | Capacité ordonnançable | Besoin | Marge |
|---|:--:|---|---|---|
| `otel-demo` | 3 workers | ~12 vCPU / ~21 Gio | 3 vCPU / 9 Gio | confortable |
| `train-ticket` | 4 workers | ~14 vCPU / ~28 Gio | 4,6 vCPU / 17 Gio | confortable |
| `both` | 6 workers | ~21 vCPU / ~42 Gio | 8 vCPU / 26 Gio | confortable |

Les profils par défaut sont donc corrects sur ce site. Sur un site où `medium`
serait plus petit, ajuste `PROFILE_*_WORKERS` ou passe `WORKER_FLAVOR` à `large`
(4 vCPU / 16 Gio) : moins de nœuds pour la même mémoire, donc moins de surcoût
système et une installation Kubespray plus rapide.

Pistes pour réduire l'empreinte :

- déployer **une seule** application à la fois ;
- pour train-ticket, rester sur le *quick start* (`TT_DEPLOY_ARGS=""`) plutôt que
  `--independent-db` ou `--all` ;
- passer `WORKER_FLAVOR` à un gabarit supérieur plutôt que multiplier les nœuds
  (moins de surcoût système par nœud).

---

