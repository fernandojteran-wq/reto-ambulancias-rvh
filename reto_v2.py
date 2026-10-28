#!/usr/bin/env python3
"""Reto ambulancias Cuenca (SUMO + TraCI).
Fase 2: hospitales, flota y ambulancia de prueba.
Fase 3: agenda de accidentes bus-moto, choque provocado, detección e inmovilización.

Uso (dentro del contenedor, tras `source ~/results/reto/env_reto.sh`):
    python3 reto_ambulancias.py                 # sumo sin interfaz, 3,5 h
    python3 reto_ambulancias.py --gui --end 1800   # depurar con sumo-gui
    python3 reto_ambulancias.py --gui --end 1800 --delay 50 --pausa 115   # más rápido, parar en t=115
"""
import argparse
import heapq
import random
from collections import deque

import traci
import traci.constants as tc

# ---------------------------------------------------------------------------
# Parámetros
# ---------------------------------------------------------------------------
SEMILLA = 42          # misma semilla para SUMO (--seed) y para random.Random
P_SIN = 0.25          # probabilidad de que un hospital con stock niegue la unidad
T_PRUEBA = 120        # instante del despacho de la ambulancia de prueba (s)
DIST_MAX_HOSP = 200   # distancia máxima admisible hospital -> arista (m)

# Fase 3
HORAS = 3             # duración de la demanda (h)
ACC_POR_HORA = 5      # accidentes bus-moto por hora
T_MIN_ACC = 300       # ningún accidente antes de este instante (s)
V_MOTO = 22           # velocidad impuesta a la moto imprudente (m/s)
DIST_MOTO = 45        # distancia a la que se inserta la moto detrás del bus (m)
T_MAX_ALCANCE = 90    # si la moto no alcanza al bus en este tiempo, se aborta (s)
T_REPROGRAMAR = 60    # un intento abortado se repite tras este tiempo (s)
T_MAX_INSERCION = 10  # tiempo máximo esperando a que la moto nueva entre en la red (s)
T_REINTENTO_BUS = 5   # sin bus adecuado: volver a buscar tras este tiempo (s)
LC_MODE_DEFECTO = 1621  # laneChangeMode por defecto de SUMO

NARANJA = (255, 140, 0, 255)
ROJO = (255, 0, 0, 255)
AMARILLO = (255, 255, 0, 255)

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
# Utilidades
# ---------------------------------------------------------------------------
def log(msg):
    print(f"[{traci.simulation.getTime():6.0f}] {msg}", flush=True)


def carril_permite(lane_id, vclass):
    """True si el carril admite la clase (lista allowed vacía = todas menos disallowed)."""
    allowed = traci.lane.getAllowed(lane_id)
    if allowed:
        return vclass in allowed
    return vclass not in traci.lane.getDisallowed(lane_id)


def devolver_control(vid):
    """Devuelve el vehículo al modelo de SUMO (Krauss + LC2013)."""
    traci.vehicle.setSpeedMode(vid, 31)
    traci.vehicle.setLaneChangeMode(vid, LC_MODE_DEFECTO)
    traci.vehicle.setSpeed(vid, -1)


# ---------------------------------------------------------------------------
# Tarea 3.1 — Agenda de accidentes
# ---------------------------------------------------------------------------
def generar_agenda(rng):
    """ACC_POR_HORA instantes uniformes dentro de cada hora, nunca antes de T_MIN_ACC."""
    agenda = []
    for h in range(HORAS):
        ini, fin = max(h * 3600, T_MIN_ACC), (h + 1) * 3600
        agenda += [int(rng.uniform(ini, fin)) for _ in range(ACC_POR_HORA)]
    agenda.sort()
    print("\nAgenda de accidentes (s):", agenda)
    return agenda


# ---------------------------------------------------------------------------
# Tarea 3.2 — Provocar el choque
# ---------------------------------------------------------------------------
def elegir_bus(rng, ocupados, aristas_usadas):
    """Bus en marcha (>4 m/s), fuera de cruces, a más de 60 m del inicio de su arista
    y en una arista donde aún no hubo accidente (lugares distintos)."""
    candidatos = []
    for v in traci.vehicle.getIDList():
        if v in ocupados or traci.vehicle.getTypeID(v) != "bus":
            continue
        edge = traci.vehicle.getRoadID(v)
        if (traci.vehicle.getSpeed(v) > 4
                and not edge.startswith(":")
                and edge not in aristas_usadas
                and traci.vehicle.getLanePosition(v) > 60):
            candidatos.append(v)
    return rng.choice(sorted(candidatos)) if candidatos else None


def preparar_moto(bus, n_intento, ocupados):
    """Devuelve (moto, nueva): la moto que sigue al bus o una insertada 45 m detrás."""
    seg = traci.vehicle.getFollower(bus, 80)
    if seg and seg[0] and seg[0] not in ocupados and traci.vehicle.getTypeID(seg[0]) == "moto":
        return seg[0], False

    lane = traci.vehicle.getLaneID(bus)
    if not carril_permite(lane, "motorcycle"):
        return None, False
    moto = f"moto_acc{n_intento:02d}"
    resto = traci.vehicle.getRoute(bus)[traci.vehicle.getRouteIndex(bus):]
    traci.route.add(f"r_{moto}", resto)
    traci.vehicle.add(moto, f"r_{moto}", typeID="moto", depart="now",
                      departLane=str(traci.vehicle.getLaneIndex(bus)),
                      departPos=str(traci.vehicle.getLanePosition(bus) - DIST_MOTO),
                      departSpeed=str(traci.vehicle.getSpeed(bus)))
    return moto, True


def soltar_moto(moto):
    """Saca a la moto del modelo longitudinal y lateral (§4.3.1)."""
    traci.vehicle.setSpeedMode(moto, 0)
    traci.vehicle.setLaneChangeMode(moto, 0)
    traci.vehicle.setSpeed(moto, V_MOTO)
    traci.vehicle.setColor(moto, NARANJA)


# ---------------------------------------------------------------------------
# Tareas 3.3 y 3.4 — Detectar, registrar e inmovilizar
# ---------------------------------------------------------------------------
def lugar_accidente(bus):
    """Arista/pos destino para la ambulancia, x/y y lon/lat del lugar (desde el bus)."""
    x, y = traci.vehicle.getPosition(bus)
    lon, lat = traci.simulation.convertGeo(x, y)
    edge = traci.vehicle.getRoadID(bus)
    pos = traci.vehicle.getLanePosition(bus)
    if edge.startswith(":"):                      # choque dentro de un cruce
        ruta, idx = traci.vehicle.getRoute(bus), traci.vehicle.getRouteIndex(bus)
        edge = ruta[min(idx + 1, len(ruta) - 1)]  # siguiente arista de la ruta del bus
        pos = 0.0
    pos = max(0.0, min(pos, traci.lane.getLength(f"{edge}_0")))
    return edge, pos, x, y, lon, lat


def inmovilizar(vids):
    """Paso 1: speedMode 0 + velocidad 0 (frena en seco). El paso 2 (speedMode 31) va en el bucle."""
    for v in vids:
        traci.vehicle.setSpeedMode(v, 0)
        traci.vehicle.setSpeed(v, 0)
        traci.vehicle.setLaneChangeMode(v, 0)
        traci.vehicle.setColor(v, ROJO)


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

    # Fase 3: estado
    programados = [(t_acc, t_acc) for t_acc in generar_agenda(rng)]  # (t_intento, t_agenda)
    heapq.heapify(programados)
    intentos = []           # choques provocados en curso
    accidentes = []         # registro de accidentes bus-moto (la Fase 4 añade los estados)
    pares_vistos = set()    # pares de vehículos ya registrados en una colisión
    ocupados = set()        # buses/motos en un intento o en un accidente
    en_accidente = set()    # vehículos accidentados: no se retiran hasta la Fase 4
    pendientes_31 = []      # vehículos a los que devolver speedMode 31 en el paso siguiente
    n_intento = n_abortados = n_fondo = 0

    def abortar(it, motivo, t):
        nonlocal n_abortados
        n_abortados += 1
        intentos.remove(it)
        ocupados.difference_update((it["bus"], it["moto"]))
        heapq.heappush(programados, (t + T_REPROGRAMAR, it["t_agenda"]))
        log(f"Intento {it['moto']} -> {it['bus']} abortado ({motivo}); "
            f"se reprograma en t={t + T_REPROGRAMAR:.0f}")

    prueba = None
    teleports = 0
    t_fin = traci.simulation.getEndTime()
    while traci.simulation.getTime() < t_fin:
        traci.simulationStep()
        t = traci.simulation.getTime()
        teleports += traci.simulation.getStartingTeleportNumber()  # solo los de este paso
        ids = set(traci.vehicle.getIDList())

        # 3.4 (segundo paso): speedMode 31 con velocidad 0 -> se quedan quietos sin Emergency Stops
        for v in pendientes_31:
            if v in ids:
                traci.vehicle.setSpeedMode(v, 31)
        pendientes_31 = []

        # 3.3 — Detectar y registrar colisiones
        for c in traci.simulation.getCollisions():
            par = frozenset((c.collider, c.victim))
            if par in pares_vistos:
                continue
            pares_vistos.add(par)
            if {c.colliderType, c.victimType} == {"bus", "moto"}:
                bus, moto = ((c.collider, c.victim) if c.colliderType == "bus"
                             else (c.victim, c.collider))
                if bus in en_accidente or moto in en_accidente:
                    continue
                edge, pos, x, y, lon, lat = lugar_accidente(bus)
                acc = {"id": f"ACC_{len(accidentes) + 1:02d}", "t_acc": t, "tipo": c.type,
                       "lane": c.lane, "edge": edge, "pos": pos, "x": x, "y": y,
                       "lon": lon, "lat": lat, "bus": bus, "moto": moto,
                       "calle": traci.edge.getStreetName(edge), "estado": "espera"}
                traci.poi.add(acc["id"], x, y, AMARILLO, poiType="accidente",
                              layer=20, width=15, height=15)
                inmovilizar((bus, moto))          # 3.4 (primer paso)
                pendientes_31 += [bus, moto]
                en_accidente.update((bus, moto))
                ocupados.update((bus, moto))
                for it in [it for it in intentos if it["moto"] == moto]:
                    intentos.remove(it)
                    if it["bus"] != bus:          # chocó con otro bus: el objetivo queda libre
                        ocupados.discard(it["bus"])
                    acc["t_agenda"] = it["t_agenda"]
                accidentes.append(acc)
                log(f"ACCIDENTE {acc['id']} ({c.type}): {moto} -> {bus} en {c.lane} "
                    f"({acc['calle'] or 'sin nombre'}), lon/lat {lon:.6f}, {lat:.6f}")
            else:
                # Colisión de fondo: retirar a los implicados para que no bloqueen la vía
                for v, vt in ((c.collider, c.colliderType), (c.victim, c.victimType)):
                    if v in ids and v not in en_accidente and vt != "ambulance":
                        traci.vehicle.remove(v, tc.REMOVE_VAPORIZED)
                        ids.discard(v)
                        n_fondo += 1
                log(f"Colisión de fondo {c.collider} ({c.colliderType}) -> {c.victim} "
                    f"({c.victimType}) en {c.lane}: retirados")

        # 3.2 — Seguir los intentos en curso
        for it in list(intentos):
            bus, moto = it["bus"], it["moto"]
            if it["t_activa"] is None:            # moto nueva esperando a entrar en la red
                if moto in ids:
                    soltar_moto(moto)
                    it["t_activa"] = t
                elif t - it["t0"] > T_MAX_INSERCION:
                    try:
                        traci.vehicle.remove(moto)
                    except traci.TraCIException:
                        pass
                    abortar(it, "la moto no pudo insertarse", t)
            elif moto not in ids or bus not in ids or bus in en_accidente:
                if moto in ids:
                    devolver_control(moto)
                abortar(it, "la moto o el bus ya no están disponibles", t)
            elif t - it["t_activa"] > T_MAX_ALCANCE:
                devolver_control(moto)
                traci.vehicle.setColor(moto, (255, 0, 255, 255))
                abortar(it, f"no lo alcanzó en {T_MAX_ALCANCE} s", t)

        # 3.1/3.2 — Lanzar los intentos que tocan según la agenda
        while programados and programados[0][0] <= t:
            _, t_agenda = heapq.heappop(programados)
            aristas_usadas = {a["edge"] for a in accidentes} | {a["lane"].rsplit("_", 1)[0]
                                                                for a in accidentes}
            bus = elegir_bus(rng, ocupados, aristas_usadas)
            moto, nueva = (None, False)
            if bus:
                n_intento += 1
                moto, nueva = preparar_moto(bus, n_intento, ocupados)
            if not moto:
                heapq.heappush(programados, (t + T_REINTENTO_BUS, t_agenda))
                continue
            it = {"bus": bus, "moto": moto, "t0": t, "t_activa": None, "t_agenda": t_agenda}
            if not nueva:
                soltar_moto(moto)
                it["t_activa"] = t
            intentos.append(it)
            ocupados.update((bus, moto))
            log(f"Intento de choque (agenda t={t_agenda}): "
                f"{'moto nueva' if nueva else 'moto existente'} {moto} -> {bus} "
                f"en {traci.vehicle.getRoadID(bus)}")

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

    por_hora = [sum(h * 3600 <= a["t_acc"] < (h + 1) * 3600 for a in accidentes)
                for h in range(HORAS)]
    print(f"\nAccidentes bus-moto: {len(accidentes)} (por hora: {por_hora}), "
          f"en {len({a['edge'] for a in accidentes})} aristas distintas")
    print(f"Intentos abortados y reprogramados: {n_abortados}; "
          f"vehículos retirados por colisiones de fondo: {n_fondo}")
    for a in accidentes:
        print(f"  {a['id']} t={a['t_acc']:.0f} {a['tipo']:9s} {a['edge']:18s} "
              f"pos={a['pos']:6.1f} ({a['lon']:.6f}, {a['lat']:.6f}) {a['moto']} -> {a['bus']}")
    print(f"\nTeleports totales: {teleports}")
    print("Stock final:", {hid: list(h["cola"]) for hid, h in hosp.items()})
    traci.close()


if __name__ == "__main__":
    main()
