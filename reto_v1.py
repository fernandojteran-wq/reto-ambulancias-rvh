#!/usr/bin/env python3
"""Reto ambulancias Cuenca (SUMO + TraCI) — Fase 2: hospitales, flota y ambulancia de prueba.

Uso (dentro del contenedor, tras `source ~/results/reto/env_reto.sh`):
    python3 reto_ambulancias.py                 # sumo sin interfaz, 3,5 h
    python3 reto_ambulancias.py --gui --end 1800   # depurar con sumo-gui
    python3 reto_ambulancias.py --gui --end 1800 --delay 50 --pausa 115   # más rápido, parar en t=115
"""
import argparse
import random
from collections import deque

import traci

# ---------------------------------------------------------------------------
# Parámetros
# ---------------------------------------------------------------------------
SEMILLA = 42          # misma semilla para SUMO (--seed) y para random.Random
P_SIN = 0.25          # probabilidad de que un hospital con stock niegue la unidad
T_PRUEBA = 120        # instante del despacho de la ambulancia de prueba (s)
DIST_MAX_HOSP = 200   # distancia máxima admisible hospital -> arista (m)

# Tabla 4.5: id -> (tipo, nombre, lon, lat)
HOSPITALES = {
    "VCM":         ("publico", "Hospital Vicente Corral Moscoso",  -78.992923, -2.911098),
    "IESS_JCA":    ("publico", "Hospital José Carrasco Arteaga",   -78.970118, -2.898698),
    "MILITAR":     ("publico", "Hospital Militar HB-III Tarqui",   -79.003968, -2.903146),
    "MUNI_PAT":    ("publico", "Hospital Municipal (Patamarca)",   -78.982263, -2.866103),
    "MUNI_VALLE":  ("publico", "Hospital Municipal de El Valle",   -78.961959, -2.919522),
    "MONTE_SINAI": ("privado", "Hospital Monte Sinaí",             -79.007373, -2.908606),
    "DEL_RIO":     ("privado", "Hospital Universitario del Río",   -78.960796, -2.892939),
}


# ---------------------------------------------------------------------------
# Tarea 2.1 — Ubicar los hospitales
# ---------------------------------------------------------------------------
def ubicar_hospitales():
    """Convierte cada (lon, lat) en (arista, pos, carril) y dibuja un POI."""
    hosp = {}
    print(f"\n{'Hospital':12s} {'Tipo':8s} {'Arista':18s} {'Pos (m)':>8s} "
          f"{'Carril':>6s} {'Dist (m)':>8s}  Calle")
    for hid, (tipo, nombre, lon, lat) in HOSPITALES.items():
        edge, pos, lane = traci.simulation.convertRoad(lon, lat, isGeo=True,
                                                       vClass="emergency")
        # punto del hospital y punto de la red en coordenadas x, y
        x, y = traci.simulation.convertGeo(lon, lat, fromGeo=True)
        xr, yr = traci.simulation.convert2D(edge, pos, lane)
        dist = traci.simulation.getDistance2D(x, y, xr, yr)
        calle = traci.edge.getStreetName(edge) or "(sin nombre)"
        aviso = "" if dist < DIST_MAX_HOSP else "  <-- ¡más de 200 m!"
        print(f"{hid:12s} {tipo:8s} {edge:18s} {pos:8.1f} {lane:6d} {dist:8.1f}  "
              f"{calle}{aviso}")

        color = (0, 200, 0, 255) if tipo == "publico" else (0, 120, 255, 255)
        traci.poi.add(f"H_{hid}", x, y, color, poiType="hospital",
                      layer=10, width=25, height=25)
        hosp[hid] = {"tipo": tipo, "nombre": nombre, "edge": edge,
                     "pos": pos, "lane": lane, "x": x, "y": y}
    return hosp


# ---------------------------------------------------------------------------
# Tarea 2.2 — Cola de disponibilidad
# ---------------------------------------------------------------------------
def crear_flota(hosp, rng):
    """Una deque de unidades por hospital, con stock inicial aleatorio."""
    n = 0
    print("\nStock inicial de ambulancias:")
    for hid, h in hosp.items():
        stock = rng.randint(1, 3) if h["tipo"] == "publico" else rng.randint(0, 1)
        h["cola"] = deque()
        for _ in range(stock):
            n += 1
            h["cola"].append(f"U{n:02d}")
        h["stock_ini"] = stock
        print(f"  {hid:12s} ({h['tipo']}): {stock} -> {list(h['cola'])}")


def pedir_unidad(h, rng):
    """Intenta sacar una unidad del hospital. None si no hay o si la niega (p_sin)."""
    if not h["cola"]:
        return None, "sin stock"
    if rng.random() < P_SIN:
        return None, "rechazo (p_sin)"
    return h["cola"].popleft(), "ok"


# ---------------------------------------------------------------------------
# Tarea 2.3 — Ambulancia de prueba VCM -> IESS_JCA
# ---------------------------------------------------------------------------
def despachar_prueba(hosp, origen, destino):
    """Despacho manual (sin sorteo p_sin): saca una unidad de `origen` y la envía."""
    ho, hd = hosp[origen], hosp[destino]
    ruta = traci.simulation.findRoute(ho["edge"], hd["edge"], vType="ambulance")
    if not ruta.edges:
        print(f"[{traci.simulation.getTime():.0f}] No hay ruta {origen} -> {destino}")
        return None
    unidad = ho["cola"].popleft() if ho["cola"] else "UPRUEBA"
    vid = f"amb_{unidad}_prueba"
    traci.route.add(f"r_{vid}", ruta.edges)
    traci.vehicle.add(vid, f"r_{vid}", typeID="ambulance", depart="now",
                      departLane=str(ho["lane"]), departPos=str(ho["pos"]),
                      arrivalPos=str(hd["pos"]))
    print(f"[{traci.simulation.getTime():.0f}] Despacho de prueba {unidad}: "
          f"{origen} -> {destino}, {len(ruta.edges)} aristas, "
          f"{ruta.length:.0f} m, travelTime estimado {ruta.travelTime:.1f} s")
    return {"vid": vid, "unidad": unidad, "destino": destino,
            "eta": ruta.travelTime, "t_pedido": traci.simulation.getTime(),
            "t_salida": None}


# ---------------------------------------------------------------------------
# Programa principal
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gui", action="store_true", help="usar sumo-gui")
    ap.add_argument("--end", type=float, default=None, help="fin de simulación (s)")
    ap.add_argument("--delay", type=int, default=100,
                    help="[gui] ms de espera por paso (0 = máxima velocidad)")
    ap.add_argument("--pausa", type=float, nargs="+", default=[],
                    help="[gui] instantes (s) en que sumo-gui se detiene, p. ej. --pausa 115 340")
    ap.add_argument("--cerrar", action="store_true",
                    help="[gui] cerrar la ventana al terminar")
    args = ap.parse_args()

    cmd = ["sumo-gui" if args.gui else "sumo", "-c", "reto.sumocfg",
           "--seed", str(SEMILLA)]
    if args.gui:
        cmd += ["--start", "--delay", str(args.delay)]
        if args.pausa:
            cmd += ["--breakpoints", ",".join(str(t) for t in args.pausa)]
        if args.cerrar:
            cmd += ["--quit-on-end"]
    if args.end:
        cmd += ["--end", str(args.end)]
    traci.start(cmd)
    rng = random.Random(SEMILLA)

    hosp = ubicar_hospitales()
    crear_flota(hosp, rng)

    prueba = None
    teleports = 0
    t_fin = traci.simulation.getEndTime()
    while traci.simulation.getTime() < t_fin:
        traci.simulationStep()
        t = traci.simulation.getTime()
        teleports += traci.simulation.getStartingTeleportNumber()  # solo los de este paso

        if t == T_PRUEBA:
            prueba = despachar_prueba(hosp, "VCM", "IESS_JCA")

        if prueba:
            if prueba["t_salida"] is None and prueba["vid"] in traci.simulation.getDepartedIDList():
                prueba["t_salida"] = t
            if prueba["vid"] in traci.simulation.getArrivedIDList():
                real = t - prueba["t_salida"]
                print(f"[{t:.0f}] {prueba['unidad']} llegó a {prueba['destino']}: "
                      f"tiempo real {real:.0f} s vs travelTime {prueba['eta']:.1f} s "
                      f"(diferencia {real - prueba['eta']:+.0f} s, "
                      f"retraso de inserción {prueba['t_salida'] - prueba['t_pedido']:.0f} s)")
                hosp[prueba["destino"]]["cola"].append(prueba["unidad"])
                prueba = None

    print(f"\nTeleports totales: {teleports}")
    print("Stock final:", {hid: list(h["cola"]) for hid, h in hosp.items()})
    traci.close()


if __name__ == "__main__":
    main()
