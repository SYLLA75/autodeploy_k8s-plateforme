"""Chaque composante du papier est-elle calculable avec ce qu'on collecte ?"""
import sys, collections
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lecture import lire_notes, lire_releves

D = Path(__file__).resolve().parent.parent / "donnees/2026-09-09_1505-1514"

notes = []
for f in sorted(D.glob("*traces_*.json")):
    notes += lire_notes(f)
noms_compteurs = set()
for f in sorted(D.glob("*metrics_*.json"))[:3]:
    for r in lire_releves(f):
        noms_compteurs.add(r.nom)

attrs = collections.Counter()
for n in notes:
    attrs.update(n.attributs.keys())

print("1) LES GENRES DE NOTES (kind OTLP)")
GENRES = {0: "non précisé", 1: "interne", 2: "SERVEUR (reçoit)",
          3: "CLIENT (émet)", 4: "PRODUCTEUR (dépose)", 5: "CONSOMMATEUR (retire)"}
for g, k in sorted(collections.Counter(n.genre for n in notes).items()):
    ex = next((x.nom for x in notes if x.genre == g), "")
    print(f"   {g} {GENRES.get(g,'?'):<20} {k:6d}   ex. « {ex[:40]} »")

print("\n2) ATTRIBUTS DE NOTE dont le papier a besoin")
for a in ("http.request.method", "http.response.status_code", "error.type",
          "url.path", "http.route", "rpc.system", "db.system",
          "messaging.operation.type", "messaging.destination.name",
          "messaging.rabbitmq.message.delivery_tag"):
    k = attrs.get(a, 0)
    print(f"   {'OUI' if k else 'NON':<4} {a:<45} {k}")

print("\n3) COMPTEURS dont le papier a besoin")
BESOINS = [
 ("instance  9",  "container_cpu_cfs_throttled_periods_total"),
 ("instance  9",  "container_cpu_cfs_periods_total"),
 ("instance 10",  "container_cpu_usage_seconds_total"),
 ("instance 11-12","container_memory_working_set_bytes"),
 ("instance 13",  "container_spec_memory_limit_bytes"),
 ("instance 14",  "container_spec_cpu_quota"),
 ("instance 15",  "kube_pod_container_status_restarts_total"),
 ("instance 16",  "container_network_receive_packets_dropped_total"),
 ("instance 17",  "container_network_transmit_packets_dropped_total"),
 ("instance 18",  "container_network_receive_errors_total"),
 ("instance 19",  "container_network_receive_bytes_total"),
 ("file  1-2",    "rabbitmq_queue_messages_ready"),
 ("file  3",      "rabbitmq_queue_messages_published_total"),
 ("file  6",      "rabbitmq_queue_consumers"),
 ("machine 1",    "node_pressure_cpu_waiting_seconds_total"),
 ("machine 2",    "node_pressure_memory_waiting_seconds_total"),
 ("machine 3",    "node_pressure_io_waiting_seconds_total"),
 ("machine 4",    "node_memory_MemAvailable_bytes"),
 ("machine 5",    "node_cpu_seconds_total"),
]
for comp, nom in BESOINS:
    print(f"   {'OUI' if nom in noms_compteurs else 'NON !':<6} {comp:<14} {nom}")

print("\n4) node_cpu_seconds_total porte-t-il l'étiquette « mode » ?  (composante machine 5)")
modes = set()
for f in sorted(D.glob("*metrics_*.json"))[:2]:
    for r in lire_releves(f):
        if r.nom == "node_cpu_seconds_total":
            modes.add(r.etiquettes.get("mode"))
print(f"   modes vus : {sorted(m for m in modes if m)}")
