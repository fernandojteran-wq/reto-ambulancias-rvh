#!/usr/bin/env python3
"""Reto ambulancias Cuenca — Fase 5: indicadores (5.2) y gráficos (5.3).

Lee salida/accidentes.csv, salida/hospitales.csv, salida/stock.csv y salida/stats.xml
(escritos por reto_ambulancias.py) y guarda salida/RA_fig_{a,b,c,d}_*.png.

Uso (dentro del contenedor, tras `source ~/results/reto/env_reto.sh`):
    python3 analisis.py                    # lee y escribe en salida/
    python3 analisis.py salida_origen      # extensión: otra carpeta
"""
import os
import sys
import xml.etree.ElementTree as ET

import matplotlib
matplotlib.use("Agg")                     # sin pantalla: solo guardar PNG
import matplotlib.pyplot as plt
import pandas as pd
import sumolib
from matplotlib.collections import LineCollection
from sumolib.geomhelper import polyLength, positionAtShapeOffset

DIR = sys.argv[1] if len(sys.argv) > 1 else "salida"
RED = "cuenca_ciudad.net.xml"
HORAS = 3

# Paleta (fondo claro): tinta para texto, tres colores de serie y gris para la red
FONDO = "#fcfcfb"
TINTA = "#0b0b0b"
TINTA_2 = "#52514e"
REJILLA = "#e4e3df"
AZUL, NARANJA, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
GRIS_RED = "#c9c8c3"

plt.rcParams.update({
    "figure.facecolor": FONDO, "axes.facecolor": FONDO, "savefig.facecolor": FONDO,
    "axes.edgecolor": REJILLA, "axes.labelcolor": TINTA_2, "axes.titlecolor": TINTA,
    "axes.titlesize": 11, "axes.titleweight": "bold", "axes.labelsize": 9,
    "xtick.color": TINTA_2, "ytick.color": TINTA_2, "xtick.labelsize": 8,
    "ytick.labelsize": 8, "axes.grid": True, "grid.color": REJILLA, "grid.linewidth": 0.6,
    "axes.axisbelow": True, "axes.spines.top": False, "axes.spines.right": False,
    "legend.frameon": False, "legend.fontsize": 8, "font.size": 9,
})


def resumen(s):
    """Mediana, media, p90, mínimo y máximo de una serie (s)."""
    return {"mediana": s.median(), "media": s.mean(), "p90": s.quantile(0.9),
            "min": s.min(), "max": s.max(), "n": s.count()}


def guardar(fig, nombre):
    ruta = os.path.join(DIR, nombre)
    fig.savefig(ruta, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  {ruta}")


# ---------------------------------------------------------------------------
# Datos
# ---------------------------------------------------------------------------
acc = pd.read_csv(os.path.join(DIR, "accidentes.csv"))
hosp = pd.read_csv(os.path.join(DIR, "hospitales.csv"))
stock = pd.read_csv(os.path.join(DIR, "stock.csv"))
stats = ET.parse(os.path.join(DIR, "stats.xml")).getroot()

# ---------------------------------------------------------------------------
# Tarea 5.2 — Indicadores
# ---------------------------------------------------------------------------
print("=== Totales de SUMO (statistic-output) ===")
veh, tel, seg = stats.find("vehicles"), stats.find("teleports"), stats.find("safety")
viajes = stats.find("vehicleTripStatistics")
print(f"Insertados {veh.get('inserted')}, en marcha al final {veh.get('running')}, "
      f"esperando {veh.get('waiting')}")
print(f"Teleports {tel.get('total')}, colisiones {seg.get('collisions')}, "
      f"emergency stops {seg.get('emergencyStops')}")
print(f"Duración media {float(viajes.get('duration')):.1f} s, timeLoss medio "
      f"{float(viajes.get('timeLoss')):.1f} s, waitingTime medio "
      f"{float(viajes.get('waitingTime')):.1f} s (sobre {viajes.get('count')} viajes)")

print("\n=== Accidentes ===")
acc["hora"] = (acc["t_acc"] // 3600).astype(int) + 1
por_hora = acc.groupby("hora").size().reindex(range(1, HORAS + 1), fill_value=0)
print(f"Accidentes: {len(acc)}; por hora: {por_hora.to_dict()}")
print(f"Estados: {acc['estado'].value_counts().to_dict()}")

ind = pd.DataFrame({
    "respuesta (despacho -> llegada)": resumen(acc["respuesta"]),
    "total (accidente -> llegada)": resumen(acc["total"]),
    "misión (despacho -> retorno)": resumen(acc["mision"]),
}).T
print("\nTiempos (s):")
print(ind.round(1).to_string())

esperaron = acc[acc["espera"] > 0]
print(f"\nAccidentes que esperaron por falta de ambulancia: {len(esperaron)} de {len(acc)}"
      f"; espera máxima {acc['espera'].max():.0f} s")
con_retorno = acc["mismo"].notna()
distinto = (acc.loc[con_retorno, "mismo"].astype(str) == "False").sum()
print(f"Retornos a un hospital distinto del de origen: {distinto} de {con_retorno.sum()} "
      f"({distinto / con_retorno.sum():.0%})")

print("\n=== Hospitales públicos ===")
pub = hosp[hosp["tipo"] == "publico"].set_index("hospital")
tabla = pub[["stock_ini", "stock_fin", "despachos", "retornos", "rechazos", "sin_stock",
             "ocupado_s", "utilizacion"]].copy()
tabla["utilizacion"] = (tabla["utilizacion"] * 100).round(1).astype(str) + " %"
print(tabla.to_string())
mas_usado = pub["utilizacion"].idxmax()
print(f"Hospital público más usado: {mas_usado} "
      f"(utilización {pub.loc[mas_usado, 'utilizacion']:.1%})")

# ---------------------------------------------------------------------------
# Tarea 5.3 — Gráficos
# ---------------------------------------------------------------------------
print("\nGráficos:")

# (a) Tiempo de respuesta por accidente, con mediana y p90
r = acc.dropna(subset=["respuesta"])
med, p90 = r["respuesta"].median(), r["respuesta"].quantile(0.9)
fig, ax = plt.subplots(figsize=(8, 4))
ax.bar(r["id"].str.replace("ACC_", ""), r["respuesta"], width=0.6, color=AZUL)
for valor, texto, estilo in ((med, "mediana", "--"), (p90, "p90", ":")):
    ax.axhline(valor, color=TINTA, linewidth=1, linestyle=estilo)
    ax.annotate(f"{texto} {valor:.0f} s", (1, valor), xycoords=("axes fraction", "data"),
                xytext=(4, 0), textcoords="offset points", va="center", fontsize=8,
                color=TINTA)
ax.set_title("Tiempo de respuesta por accidente (despacho → llegada)", loc="left")
ax.set_xlabel("Accidente (ACC_nn)")
ax.set_ylabel("Tiempo de respuesta (s)")
ax.grid(axis="x", visible=False)
guardar(fig, "RA_fig_a_respuesta.png")

# (b) Stock inicial, despachos y retornos por hospital
fig, ax = plt.subplots(figsize=(9, 4))
series = (("stock_ini", "Stock inicial", AZUL), ("despachos", "Despachos", NARANJA),
          ("retornos", "Retornos", AQUA))
ancho = 0.26
xs = range(len(hosp))
for i, (col, etiqueta, color) in enumerate(series):
    ax.bar([x + (i - 1) * (ancho + 0.02) for x in xs], hosp[col], width=ancho,
           color=color, label=etiqueta)
ax.set_xticks(list(xs))
ax.set_xticklabels([f"{h}\n({t})" for h, t in zip(hosp["hospital"], hosp["tipo"])])
ax.set_ylabel("Unidades")
ax.yaxis.get_major_locator().set_params(integer=True)
ax.set_title("Stock inicial, despachos y retornos por hospital", loc="left")
ax.legend(loc="upper right", ncols=3)
ax.grid(axis="x", visible=False)
guardar(fig, "RA_fig_b_hospitales.png")

# (c) Stock disponible en el tiempo, un panel por hospital
nombres = list(stock.columns[1:])
fig, axs = plt.subplots(len(nombres), 1, figsize=(8, 1.3 * len(nombres)), sharex=True,
                        sharey=True)
t_h = stock["t"] / 3600
tope = stock[nombres].to_numpy().max()
for ax, h in zip(axs, nombres):
    ax.step(t_h, stock[h], where="post", color=AZUL, linewidth=2)
    ax.set_ylim(-0.3, tope + 0.5)
    ax.yaxis.get_major_locator().set_params(integer=True)
    ax.set_ylabel(h, rotation=0, ha="right", va="center", color=TINTA)
    ax.grid(axis="x", visible=False)
for _, a in acc.iterrows():                       # instantes de los accidentes
    for ax in axs:
        ax.axvline(a["t_acc"] / 3600, color=REJILLA, linewidth=0.8, zorder=0)
axs[0].set_title("Ambulancias disponibles en cada hospital (líneas grises: accidentes)",
                 loc="left")
axs[-1].set_xlabel("Tiempo de simulación (h)")
fig.tight_layout()
guardar(fig, "RA_fig_c_stock.png")

# (d) Mapa: red, hospitales, accidentes y viajes de ida y retorno
net = sumolib.net.readNet(RED)
lonlat = lambda pts: [net.convertXY2LonLat(x, y) for x, y in pts]
def recortar(shape, desde, hasta):
    """Trozo de la polilínea entre las distancias desde..hasta (m) sobre ella."""
    puntos, acum = [positionAtShapeOffset(shape, desde)], 0.0
    for a, b in zip(shape, shape[1:]):
        acum += ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
        if desde < acum < hasta:
            puntos.append(b)
    puntos.append(positionAtShapeOffset(shape, hasta))
    return puntos


def tramos_viaje(aristas, pos_ini, pos_fin):
    """Formas (lon, lat) de las aristas de un viaje: la primera desde pos_ini y la
    última hasta pos_fin (las aristas extremas no se recorren completas)."""
    tramos = []
    for i, e in enumerate(aristas):
        shape = net.getEdge(e).getShape()
        desde = pos_ini if i == 0 else 0.0
        hasta = pos_fin if i == len(aristas) - 1 else polyLength(shape)
        tramos.append(lonlat(recortar(shape, desde, max(desde, hasta))))
    return tramos


pos_h = dict(zip(hosp["hospital"], hosp["pos"]))

fig, ax = plt.subplots(figsize=(9, 9))
ax.add_collection(LineCollection([lonlat(e.getShape()) for e in net.getEdges()],
                                 colors=GRIS_RED, linewidths=0.5, zorder=1))
viajes = {"ruta_ida": [], "ruta_ret": []}
for _, a in acc.iterrows():
    if isinstance(a["ruta_ida"], str):
        viajes["ruta_ida"] += tramos_viaje(a["ruta_ida"].split(), pos_h[a["origen"]], a["pos"])
    if isinstance(a["ruta_ret"], str):
        viajes["ruta_ret"] += tramos_viaje(a["ruta_ret"].split(), a["pos"], pos_h[a["retorno"]])
for col, color, estilo, etiqueta in (("ruta_ida", AZUL, "-", "Ida (hospital → accidente)"),
                                     ("ruta_ret", NARANJA, "--",
                                      "Retorno (accidente → hospital)")):
    tramos = viajes[col]
    ax.add_collection(LineCollection(tramos, colors=color, linewidths=2, linestyles=estilo,
                                     alpha=0.8, zorder=2, label=etiqueta))
for tipo, relleno in (("publico", TINTA), ("privado", FONDO)):
    h = hosp[hosp["tipo"] == tipo]
    ll = lonlat(zip(h["x"], h["y"]))
    ax.scatter([p[0] for p in ll], [p[1] for p in ll], s=90, marker="s", c=relleno,
               edgecolors=TINTA, linewidths=1.5, zorder=4, label=f"Hospital {tipo}")
    for nombre, (lon, lat) in zip(h["hospital"], ll):
        ax.annotate(nombre, (lon, lat), xytext=(6, 6), textcoords="offset points",
                    fontsize=8, fontweight="bold", color=TINTA, zorder=5)
ax.scatter(acc["lon"], acc["lat"], s=70, marker="X", c=AQUA, edgecolors=FONDO,
           linewidths=1, zorder=4, label="Accidente")
for _, a in acc.iterrows():
    ax.annotate(a["id"].replace("ACC_", ""), (a["lon"], a["lat"]), xytext=(5, -10),
                textcoords="offset points", fontsize=7, color=TINTA_2, zorder=5)
ax.set_xlim(-79.030, -78.950)
ax.set_ylim(-2.930, -2.860)
ax.set_aspect(1.0)
ax.set_xlabel("Longitud")
ax.set_ylabel("Latitud")
ax.grid(False)
ax.set_title("Hospitales, accidentes y viajes de las ambulancias (Cuenca)", loc="left")
ax.legend(loc="upper left", fontsize=8, facecolor=FONDO, frameon=True, edgecolor=REJILLA)
guardar(fig, "RA_fig_d_mapa.png")
