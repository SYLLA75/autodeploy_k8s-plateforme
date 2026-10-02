"""
Lecture de garde.tsv pour test_garde.sh.

  lire.py <garde.tsv> <HH:MM> <colonne>     la valeur d'une colonne à cette minute
                                             (« ABSENTE » si la minute manque)
  lire.py <garde.tsv> --lignes               nombre de lignes de données
  lire.py <garde.tsv> --compte <col>=<val>   nombre de lignes où col vaut val
  lire.py <garde.tsv> --entete               les colonnes, séparées par des virgules
"""
import sys

chemin, quoi = sys.argv[1], sys.argv[2]
with open(chemin, encoding="utf-8") as f:
    lignes = [l.rstrip("\n").split("\t") for l in f if l.strip()]
entete, donnees = lignes[0], lignes[1:]
if quoi == "--lignes":
    print(len(donnees))
elif quoi == "--entete":
    print(",".join(entete))
elif quoi == "--compte":
    col, _, val = sys.argv[3].partition("=")
    i = entete.index(col)
    print(sum(1 for l in donnees if l[i] == val))
else:
    i = entete.index(sys.argv[3])
    trouve = [l for l in donnees if l[0].endswith(f"T{quoi}Z")]
    print(trouve[-1][i] if trouve else "ABSENTE")
