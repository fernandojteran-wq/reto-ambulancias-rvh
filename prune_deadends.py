#!/usr/bin/env python3
"""Poda iterativa de calles 'rotas' (dead-ends) en los bordes de una red SUMO.
Uso: python3 prune_deadends.py zona.net.xml prune.txt
Usa el sumolib incluido en la instalacion de SUMO ($SUMO_HOME/tools):
no requiere pip install sumolib."""
import os, sys

if 'SUMO_HOME' in os.environ:
    sys.path.append(os.path.join(os.environ['SUMO_HOME'], 'tools'))
try:
    import sumolib
except ImportError:
    sys.exit("ERROR: no se encontro sumolib. Defina SUMO_HOME "
             "(export SUMO_HOME=/usr/share/sumo) o instale: pip install sumolib")

if len(sys.argv) != 3 or not sys.argv[1].endswith('.net.xml'):
    sys.exit("Uso: python3 prune_deadends.py <red.net.xml> <salida.txt>\n"
             "  <red.net.xml>  red SUMO a podar (NO el .rou.xml)\n"
             "  <salida.txt>   archivo donde escribir los IDs a eliminar")

net = sumolib.net.readNet(sys.argv[1])
removed = set()
changed = True
while changed:
    changed = False
    for node in net.getNodes():
        out_e = [e for e in node.getOutgoing() if e.getID() not in removed]
        in_e  = [e for e in node.getIncoming() if e.getID() not in removed]
        # nodo hoja: solo lo toca una calle (ida y/o vuelta) -> es un muñón
        street_ids = {e.getID().lstrip('-') for e in out_e + in_e}
        if len(street_ids) == 1 and street_ids:
            for e in out_e + in_e:
                removed.add(e.getID())
            changed = True
with open(sys.argv[2], 'w') as f:
    f.write(' '.join(sorted(removed)))
print(f"Aristas a podar: {len(removed)}")
