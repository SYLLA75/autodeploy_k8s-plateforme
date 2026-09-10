"""
Choisir la largeur de fenêtre et le pas.

Ce qu'on mesure dans une fenêtre est d'autant plus fort que la fenêtre est
occupée par la panne. Une fenêtre à moitié dans la panne montre une amplitude
deux fois trop faible. La bonne question est donc :

    « quelle est la fenêtre la PLUS remplie par la panne,
      dans le pire placement possible de celle-ci ? »

C'est cette valeur qui décide si le seuil d'alerte se déclenche.
"""
L = 60.0
PAS = [60, 30, 20, 10]
DUREES = [5, 10, 30, 55, 60, 65, 90, 120, 300]
FIN = 0.05

def pire_cas(D, L, P):
    pire = 1.0
    for i in range(int(P / FIN)):          # une période du pas suffit
        t = i * FIN
        meilleur = 0.0
        k0 = int((t - L) // P) - 1
        for k in range(k0, k0 + int((L + D) / P) + 4):
            a, b = k * P, k * P + L
            meilleur = max(meilleur, max(0.0, min(t + D, b) - max(t, a)) / L)
        pire = min(pire, meilleur)
    return pire

print(f"fenêtre de {L:g} s — dans le pire placement de la panne, quelle part de la")
print("meilleure fenêtre est occupée par la panne ? (100 % = signal à pleine force)\n")
print(f"  {'durée panne':>12} │" + "".join(f"  pas {p:>3g} s " for p in PAS) + " │ plafond")
print("  " + "─"*13 + "┼" + "─"*(12*len(PAS)) + "─┼" + "─"*9)
for D in DUREES:
    plafond = min(D, L) / L
    ligne = f"  {D:>10g} s │"
    for P in PAS:
        v = pire_cas(D, L, P)
        marque = " " if v >= plafond - 1e-6 else "!"
        ligne += f"  {100*v:5.1f} %{marque} "
    print(ligne + f" │ {100*plafond:5.1f} %")

print("""
  « plafond » = le mieux qu'on puisse espérer avec cette largeur de fenêtre.
  « ! »       = ce réglage n'atteint pas le plafond : la panne peut tomber mal.

  RÈGLE :  pas <= | durée de la panne − largeur de la fenêtre |

  Une panne qui dure exactement la largeur d'une fenêtre est le pire cas :
  aucun pas ne garantit de la voir en entier. À éviter en choisissant une
  largeur nettement différente de la durée de panne visée.""")
