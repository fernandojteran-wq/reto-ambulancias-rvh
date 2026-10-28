#!/usr/bin/env python3
"""Extensión §4.7.9 — Política de retorno: compara la corrida base (retorno al hospital más
cercano al accidente, salida/) con la de retorno al hospital de origen (salida_origen/).

Uso (tras correr ambas políticas y analisis.py en cada carpeta):
    python3 comparar.py
Guarda salida/RA_fig_e_extension.png.
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

import analisis as A          # misma paleta y estilo (ejecuta el análisis de salida/)

POLITICAS = {"Más cercano al accidente": "salida", "Hospital de origen": "salida_origen"}
COLORES = [A.AZUL, A.NARANJA]

filas, stock_fin = [], {}
for nombre, d in POLITICAS.items():
    acc = pd.read_csv(os.path.join(d, "accidentes.csv"))
    hosp = pd.read_csv(os.path.join(d, "hospitales.csv")).set_index("hospital")
    agenda = acc[acc["t_agenda"].notna()]          # solo los accidentes provocados
    for subconj, df in (("todos", acc), ("agenda", agenda)):
        r, m = df["respuesta"], df["mision"]
        filas.append({"política": nombre, "accidentes": subconj, "n": len(df),
                      "resp_mediana": r.median(), "resp_media": r.mean(),
                      "resp_p90": r.quantile(0.9), "resp_max": r.max(),
                      "mision_mediana": m.median(),
                      "retornos_distintos": (df["mismo"].astype(str) == "False").sum()})
    pub = hosp[hosp["tipo"] == "publico"]
    filas[-1]["util_max"] = f"{pub['utilizacion'].idxmax()} {pub['utilizacion'].max():.1%}"
    stock_fin[nombre] = hosp["stock_fin"]

print("\n=== Extensión: política de retorno ===")
print(pd.DataFrame(filas).round(1).to_string(index=False))
stock_fin = pd.DataFrame(stock_fin)
print("\nStock final por hospital:")
print(stock_fin.to_string())

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4), gridspec_kw={"width_ratios": [1, 1.6]})
for i, ((nombre, d), color) in enumerate(zip(POLITICAS.items(), COLORES)):
    r = pd.read_csv(os.path.join(d, "accidentes.csv"))["respuesta"].dropna()
    ax1.scatter([i] * len(r), r, s=36, color=color, alpha=0.75, edgecolors=A.FONDO,
                linewidths=1, zorder=3)
    for valor, texto, estilo in ((r.median(), "mediana", "-"), (r.quantile(0.9), "p90", ":")):
        ax1.hlines(valor, i - 0.25, i + 0.25, color=A.TINTA, linewidth=1.5, linestyle=estilo)
        ax1.annotate(f"{texto} {valor:.0f}", (i + 0.27, valor), va="center", fontsize=8,
                     color=A.TINTA)
ax1.set_xticks(range(len(POLITICAS)))
ax1.set_xticklabels([n.replace(" al ", "\nal ").replace(" de ", "\nde ") for n in POLITICAS])
ax1.set_xlim(-0.5, len(POLITICAS) - 0.1)
ax1.set_ylabel("Tiempo de respuesta (s)")
ax1.set_title("Respuesta por accidente", loc="left")
ax1.grid(axis="x", visible=False)

ancho = 0.38
xs = range(len(stock_fin))
for i, (nombre, color) in enumerate(zip(POLITICAS, COLORES)):
    ax2.bar([x + (i - 0.5) * (ancho + 0.02) for x in xs], stock_fin[nombre], width=ancho,
            color=color, label=nombre)
ax2.set_xticks(list(xs))
ax2.set_xticklabels(stock_fin.index, rotation=20, ha="right")
ax2.set_ylabel("Unidades al final")
ax2.yaxis.get_major_locator().set_params(integer=True)
ax2.set_title("Distribución final de la flota", loc="left")
ax2.legend(loc="upper right")
ax2.grid(axis="x", visible=False)
fig.tight_layout()
A.guardar(fig, "RA_fig_e_extension.png")
