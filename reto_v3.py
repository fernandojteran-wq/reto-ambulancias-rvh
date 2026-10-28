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

# Fase 4
T_REINTENTO_DESP = 30   # sin ambulancia disponible: reintentar el despacho tras (s)
DIST_LLEGADA = 50       # llegada: distancia de conducción al accidente (m)
DIST_A_PIE = 300        # ... o detenida en la cola a menos de esta distancia (m)
T_A_PIE = 30            # ... durante al menos este tiempo (s): "siguen a pie"
T_REROUTE = 60          # cada cuánto se recalcula la ruta de la ambulancia en camino (s)
T_ATENCION = 120        # duración de la atención en el sitio (s)
T_STOCK = 60            # cada cuánto se guarda el stock de los hospitales (s)

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
        h.update(despachos=0, retornos=0, rechazos=0, sin_stock=0, ocupado=0.0)
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
# Tareas 4.1 y 4.2 — Hospital más cercano con unidad y despacho
# ---------------------------------------------------------------------------
def rutas_hospitales(hosp, edge, desde_hospital=True):
    """Lista (travelTime, hid, ruta) ordenada, solo hospitales con ruta válida.
    desde_hospital=True: hospital -> edge (ida); False: edge -> hospital (retorno)."""
    rutas = []
    for hid, h in hosp.items():
        a, b = (h["edge"], edge) if desde_hospital else (edge, h["edge"])
        r = traci.simulation.findRoute(a, b, vType="ambulance")
        if r.edges:
            rutas.append((r.travelTime, hid, r))
    rutas.sort(key=lambda x: x[0])
    return rutas


def elegir_hospital(acc, hosp, rng):
    """Pide unidad a los hospitales de menor a mayor travelTime: el primero que la da es el
    de menor travelTime entre los que tienen stock y no la niegan (sorteo p_sin)."""
    negativas = []
    for tt, hid, ruta in rutas_hospitales(hosp, acc["edge"]):
        unidad, motivo = pedir_unidad(hosp[hid], rng)
        if unidad:
            return hid, unidad, ruta, negativas
        hosp[hid]["rechazos" if motivo.startswith("rechazo") else "sin_stock"] += 1
        negativas.append(f"{hid} {motivo} ({tt:.0f} s)")
    return None, None, None, negativas


def despachar(acc, hosp, rng, t):
    hid, unidad, ruta, negativas = elegir_hospital(acc, hosp, rng)
    if hid is None:
        acc["reintentos"] += 1
        acc["t_prox"] = t + T_REINTENTO_DESP
        log(f"{acc['id']}: SIN AMBULANCIA [{'; '.join(negativas)}] -> reintento "
            f"{acc['reintentos']} en t={acc['t_prox']:.0f}")
        return
    h = hosp[hid]
    amb = f"amb_{unidad}_{acc['id']}"
    traci.route.add(f"r_{amb}", ruta.edges)
    traci.vehicle.add(amb, f"r_{amb}", typeID="ambulance", depart="now",
                      departLane=str(h["lane"]), departPos=str(h["pos"]))
    h["despachos"] += 1
    acc.update(estado="en_camino", t_desp=t, espera=t - acc["t_acc"], origen=hid,
               unidad=unidad, amb=amb, eta=ruta.travelTime, t_reroute=t,
               negativas="; ".join(negativas))
    log(f"{acc['id']}: DESPACHO {unidad} desde {hid}, ETA {ruta.travelTime:.0f} s, "
        f"espera {acc['espera']:.0f} s"
        + (f" | antes no pudieron: {'; '.join(negativas)}" if negativas else ""))


# ---------------------------------------------------------------------------
# Tarea 4.3 — Llegada
# ---------------------------------------------------------------------------
def revisar_llegada(acc, ids, llegados, t):
    """Devuelve el motivo de llegada (str) o None si la ambulancia sigue en camino."""
    amb = acc["amb"]
    if amb in llegados:
        return "fin de ruta"          # salió de la red al final de su ruta (ver Fase 4, ayudas)
    if amb not in ids:
        return None                   # todavía no insertada
    edge = traci.vehicle.getRoadID(amb)
    if edge.startswith(":"):
        return None                   # dentro de un cruce: se mide en el paso siguiente
    try:
        d = traci.simulation.getDistanceRoad(edge, traci.vehicle.getLanePosition(amb),
                                             acc["edge"], acc["pos"], isDriving=True)
    except traci.TraCIException:
        d = -1
    if 0 <= d <= DIST_LLEGADA:
        return f"a {d:.0f} m"
    if edge == acc["edge"] and traci.vehicle.getSpeed(amb) < 0.1:
        return "detenida en la arista del accidente"
    if 0 <= d <= DIST_A_PIE and traci.vehicle.getWaitingTime(amb) >= T_A_PIE:
        return f"a pie desde {d:.0f} m"
    if t - acc["t_reroute"] >= T_REROUTE:
        traci.vehicle.rerouteTraveltime(amb)
        acc["t_reroute"] = t
    return None


# ---------------------------------------------------------------------------
# Tareas 4.4 y 4.5 — Atención, retorno al hospital más cercano y cierre
# ---------------------------------------------------------------------------
def iniciar_retorno(acc, hosp, ids, t):
    """Retira a los accidentados y manda la ambulancia al hospital más cercano al accidente."""
    for v in (acc["bus"], acc["moto"]):
        if v in ids:
            traci.vehicle.remove(v, tc.REMOVE_VAPORIZED)
    traci.poi.remove(acc["id"])

    rutas = rutas_hospitales(hosp, acc["edge"], desde_hospital=False)
    tt, hid, ruta = rutas[0] if rutas else (None, acc["origen"], None)
    amb = acc["amb"]
    reinsertar = amb not in ids
    if not reinsertar:
        devolver_control(amb)                 # speedMode 31, laneChangeMode 1621, setSpeed -1
        try:
            traci.vehicle.changeTarget(amb, hosp[hid]["edge"])
        except traci.TraCIException:
            traci.vehicle.remove(amb)         # sin ruta desde donde está: se reinserta
            reinsertar = True
    if reinsertar and ruta is not None:
        amb = f"{acc['amb']}_ret"
        traci.route.add(f"r_{amb}", ruta.edges)
        traci.vehicle.add(amb, f"r_{amb}", typeID="ambulance", depart="now",
                          departLane="best", departPos=str(acc["pos"]))
        acc["amb"] = amb
    acc.update(estado="retorno", t_fin=t, retorno=hid, mismo=hid == acc["origen"])
    log(f"{acc['id']}: fin de atención, {acc['unidad']} vuelve a {hid}"
        f"{'' if tt is None else f' (travelTime {tt:.0f} s)'}"
        f" — {'mismo hospital' if acc['mismo'] else 'DISTINTO del de origen ' + acc['origen']}"
        f"{' [reinsertada]' if reinsertar else ''}")


def cerrar_mision(acc, hosp, t):
    h = hosp[acc["retorno"]]
    h["cola"].append(acc["unidad"])
    h["retornos"] += 1
    acc.update(estado="cerrado", t_ret=t, mision=t - acc["t_desp"])
    hosp[acc["origen"]]["ocupado"] += acc["mision"]
    log(f"{acc['id']}: {acc['unidad']} llegó a {acc['retorno']}, misión {acc['mision']:.0f} s; "
        f"cola de {acc['retorno']}: {list(h['cola'])}")


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

    stock_log = []          # (t, hospital, unidades disponibles) cada T_STOCK s
    prueba = None
    teleports = 0
    t_fin = traci.simulation.getEndTime()
    while traci.simulation.getTime() < t_fin:
        traci.simulationStep()
        t = traci.simulation.getTime()
        teleports += traci.simulation.getStartingTeleportNumber()  # solo los de este paso
        ids = set(traci.vehicle.getIDList())
        llegados = set(traci.simulation.getArrivedIDList())

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
                       "calle": traci.edge.getStreetName(edge), "estado": "espera",
                       "t_prox": t, "reintentos": 0, "t_agenda": None,
                       "t_desp": None, "espera": None, "origen": None, "unidad": None,
                       "amb": None, "eta": None, "negativas": "", "t_lleg": None,
                       "respuesta": None, "llegada": None, "t_fin": None, "retorno": None,
                       "mismo": None, "t_ret": None, "mision": None}
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
            if prueba["vid"] in llegados:
                real = t - prueba["t_salida"]
                print(f"[{t:.0f}] {prueba['unidad']} llegó a {prueba['destino']}: "
                      f"tiempo real {real:.0f} s vs travelTime {prueba['eta']:.1f} s "
                      f"(diferencia {real - prueba['eta']:+.0f} s, "
                      f"retraso de inserción {prueba['t_salida'] - prueba['t_pedido']:.0f} s)")
                hosp[prueba["destino"]]["cola"].append(prueba["unidad"])
                prueba = None

        # Fase 4 — máquina de estados de cada accidente (tabla 4.4)
        for acc in accidentes:
            if acc["estado"] == "espera" and t >= acc["t_prox"]:
                despachar(acc, hosp, rng, t)
            elif acc["estado"] == "en_camino":
                motivo = revisar_llegada(acc, ids, llegados, t)
                if motivo:
                    acc.update(estado="atendiendo", t_lleg=t,
                               respuesta=t - acc["t_desp"], llegada=motivo)
                    if acc["amb"] in ids:     # parar en el sitio
                        traci.vehicle.setSpeed(acc["amb"], 0)
                        traci.vehicle.setLaneChangeMode(acc["amb"], 0)
                    log(f"{acc['id']}: LLEGADA de {acc['unidad']} ({motivo}), respuesta "
                        f"{acc['respuesta']:.0f} s (ETA {acc['eta']:.0f} s), total desde el "
                        f"accidente {t - acc['t_acc']:.0f} s")
            elif acc["estado"] == "atendiendo" and t - acc["t_lleg"] >= T_ATENCION:
                iniciar_retorno(acc, hosp, ids, t)
                en_accidente.difference_update((acc["bus"], acc["moto"]))
                ocupados.difference_update((acc["bus"], acc["moto"]))
            elif acc["estado"] == "retorno" and acc["amb"] in llegados:
                cerrar_mision(acc, hosp, t)

        # 4.5 — stock de todos los hospitales cada T_STOCK s
        if t % T_STOCK == 0:
            stock_log += [(t, hid, len(h["cola"])) for hid, h in hosp.items()]

    por_hora = [sum(h * 3600 <= a["t_acc"] < (h + 1) * 3600 for a in accidentes)
                for h in range(HORAS)]
    print(f"\nAccidentes bus-moto: {len(accidentes)} (por hora: {por_hora}), "
          f"en {len({a['edge'] for a in accidentes})} aristas distintas")
    print(f"Intentos abortados y reprogramados: {n_abortados}; "
          f"vehículos retirados por colisiones de fondo: {n_fondo}")
    fmt = lambda v: "-" if v is None else f"{v:.0f}"
    print(f"\n{'Acc':6s} {'t_acc':>6s} {'estado':10s} {'origen':12s} {'espera':>6s} "
          f"{'resp':>5s} {'ETA':>5s} {'retorno':12s} {'misión':>6s}  llegada")
    for a in accidentes:
        print(f"{a['id']:6s} {a['t_acc']:6.0f} {a['estado']:10s} {a['origen'] or '-':12s} "
              f"{fmt(a['espera']):>6s} {fmt(a['respuesta']):>5s} {fmt(a['eta']):>5s} "
              f"{a['retorno'] or '-':12s} {fmt(a['mision']):>6s}  {a['llegada'] or '-'}")
        if a["estado"] == "en_camino" and a["amb"] in traci.vehicle.getIDList():
            amb = a["amb"]
            print(f"       ¡no llegó! {amb} en {traci.vehicle.getRoadID(amb)}, espera "
                  f"{traci.vehicle.getWaitingTime(amb):.0f} s, líder {traci.vehicle.getLeader(amb, 100)}")
    distintos = [a for a in accidentes if a["mismo"] is False]
    print(f"\nRetornos a un hospital distinto del de origen: {len(distintos)} de "
          f"{sum(a['mismo'] is not None for a in accidentes)}")
    print(f"\n{'Hospital':12s} {'tipo':8s} {'ini':>3s} {'fin':>3s} {'desp':>4s} {'ret':>3s} "
          f"{'rech':>4s} {'sin':>3s} {'ocupado(s)':>10s} {'util':>6s}")
    for hid, h in hosp.items():
        util = (f"{h['ocupado'] / (HORAS * 3600 * h['stock_ini']):6.1%}"
                if h["stock_ini"] else "   n/a")
        print(f"{hid:12s} {h['tipo']:8s} {h['stock_ini']:3d} {len(h['cola']):3d} "
              f"{h['despachos']:4d} {h['retornos']:3d} {h['rechazos']:4d} {h['sin_stock']:3d} "
              f"{h['ocupado']:10.0f} {util}")
    print(f"\nTeleports totales: {teleports}")
    print("Stock final:", {hid: list(h["cola"]) for hid, h in hosp.items()})
    traci.close()


if __name__ == "__main__":
    main()
