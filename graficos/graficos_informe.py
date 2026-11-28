r"""
graficos_informe.py
Versión de los gráficos 1 y 3 para el informe en LaTeX:
sin título (va en \caption), tipografía serif, colores sobrios aptos para
impresión en escala de grises y salida en PDF vectorial.
Requiere haber corrido: python analisis.py barrido  y  python analisis.py factorial
"""
import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick

CARPETA_CODIGO = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(CARPETA_CODIGO)
CARPETA = os.path.join(CARPETA_CODIGO, "informe")
os.makedirs(CARPETA, exist_ok=True)

AZUL = "#425CDD"          # curva de ahorro
GRIS_MTS = "#B8B8B8"      # barras MTS
GRIS_POST = "#5E5E5E"     # barras Postergación
TEXTO = "#222222"

plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["CMU Serif", "Computer Modern Roman", "Times New Roman", "DejaVu Serif"],
    "mathtext.fontset": "cm",
    "font.size": 9,
    "axes.edgecolor": "#444444",
    "axes.linewidth": 0.6,
    "savefig.bbox": "tight",
    "savefig.dpi": 300,
})
ANCHO = 6.3   # pulgadas, ~ \textwidth de un artículo A4/carta


def coma(x, dec=1):
    return f"{x:.{dec}f}".replace(".", ",")


# =============================================================================
# FIGURA 1: AHORRO FRENTE A MTS SEGÚN CAPACIDAD (barrido cada 3 h)
# =============================================================================
df = pd.read_excel(
    os.path.join(BASE, "out_1b_barrido_capacidad.xlsx"), sheet_name="Barrido_3h"
).sort_values("K (h)")
if df["K (h)"].tolist() != list(range(21, 85, 3)):
    raise ValueError("Se requiere el barrido de 21 a 84 h cada 3 h: ejecuta python analisis.py barrido.")
K = df["K (h)"].values
ahorro = df["Ahorro_MTS_pct"].values
bo_post = df["Backlog_Post"].values / 1000
bo_mts = df["Backlog_MTS"].values / 1000
paso = K[1] - K[0]

lim1 = K[np.argmax(df["Backlog_Post"].values < 1)] - paso / 2
lim2 = K[np.argmax(df["Backlog_MTS"].values < 1)] - paso / 2
x0, x1 = K[0] - paso / 2, K[-1] + paso / 2

fig, ax1 = plt.subplots(figsize=(ANCHO, 3.3))
ax2 = ax1.twinx()

for a, b, gris, etiqueta in [(x0, lim1, "#F2F2F2", "Ambas se atrasan"),
                             (lim1, lim2, "#E3E3E3", "Solo MTS se atrasa"),
                             (lim2, x1, "#FFFFFF", "Ninguna se atrasa")]:
    ax2.axvspan(a, b, color=gris, zorder=0, lw=0)
    ax1.text((a + b) / 2, 113, etiqueta, ha="center", fontsize=8, style="italic", color=TEXTO)
for lim in (lim1, lim2):
    ax1.axvline(lim, color="#888888", lw=0.6, ls=":")

ancho = paso * 0.36
b1 = ax2.bar(K - ancho / 2, bo_mts, width=ancho, color=GRIS_MTS, edgecolor="white", lw=0.3,
             label="Atraso acumulado MTS")
b2 = ax2.bar(K + ancho / 2, bo_post, width=ancho, color=GRIS_POST, edgecolor="white", lw=0.3,
             label="Atraso acumulado Postergación")
l1 = ax1.plot(K, ahorro, color=AZUL, marker="o", ms=3.5, lw=1.6, label="Ahorro vs. MTS", zorder=5)

for k_obj in (21, 42, 63, 84):
    i = int(np.abs(K - k_obj).argmin())
    ha, dx = ("left", -3) if k_obj == K[0] else ("right", 3) if k_obj == K[-1] else ("center", 0)
    ax1.annotate(f"{coma(ahorro[i])}%", xy=(K[i], ahorro[i]), xytext=(dx, 7),
                 textcoords="offset points", ha=ha, fontsize=8.5, color=AZUL, fontweight="bold",
                 bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.85), zorder=6)

ax1.set_xlabel("Capacidad de la línea por período, $K$ (h)")
ax1.set_ylabel("Ahorro frente a MTS (%)", color=AZUL)
ax2.set_ylabel("Atraso acumulado esperado\n(miles de botellas$\\cdot$período)")
ax1.set_xlim(x0, x1)
ax1.set_ylim(0, 120)
ax1.set_yticks(range(0, 101, 20))
ax1.yaxis.set_major_formatter(mtick.PercentFormatter(decimals=0))
ax1.set_xticks(K)
ax1.tick_params(axis="x", labelsize=7.5)
ax1.grid(axis="y", ls="--", lw=0.4, alpha=0.5)
ax1.set_zorder(ax2.get_zorder() + 1)
ax1.patch.set_visible(False)
for ax in (ax1, ax2):
    ax.spines["top"].set_visible(False)

ax1.legend(l1 + [b1, b2], [h.get_label() for h in l1 + [b1, b2]], loc="upper center",
           bbox_to_anchor=(0.5, -0.17), ncol=3, frameon=False, fontsize=8)
fig.savefig(os.path.join(CARPETA, "fig_capacidad.pdf"))
fig.savefig(os.path.join(CARPETA, "fig_capacidad.png"))
plt.close(fig)


# =============================================================================
# FIGURA 2: AHORRO SEGÚN CAPACIDAD, CORRELACIÓN Y CV (factorial 3x3x3)
# =============================================================================
xl = pd.ExcelFile(os.path.join(BASE, "out_2_factorial_K_CV_Corr.xlsx"))
hoja = next((s for s in xl.sheet_names if "fact" in s.lower() or "27" in s), xl.sheet_names[0])
dff = pd.read_excel(xl, sheet_name=hoja)


def col(df, claves):
    for c in df.columns:
        if any(k in c.lower() for k in claves):
            return c
    raise KeyError(claves)


cK, cCorr, cCV, cAh = col(dff, ["k (h)", "capacidad"]), col(dff, ["corr"]), col(dff, ["cv"]), col(dff, ["ahorro"])
if dff[cAh].max() <= 1.5:
    dff[cAh] *= 100
if dff[cCV].max() <= 1.5:
    dff[cCV] = (dff[cCV] * 100).round().astype(int)

caps = sorted(dff[cK].unique())
corrs = [c for c in ["Negativa", "Original", "Positiva"] if c in dff[cCorr].unique()]
cvs = sorted(dff[cCV].unique())

fig, axes = plt.subplots(1, len(caps), figsize=(ANCHO, 2.6), sharey=True)
for ax, k in zip(axes, caps):
    piv = dff[dff[cK] == k].pivot(index=cCorr, columns=cCV, values=cAh).reindex(index=corrs, columns=cvs)
    im = ax.imshow(piv.values, cmap="Blues", vmin=30, vmax=100, aspect="auto")
    ax.set_title(f"$K$ = {int(k)} h", fontsize=9.5)
    ax.set_xlabel("CV de la demanda", fontsize=8)
    ax.set_xticks(range(len(cvs)))
    ax.set_xticklabels([f"{int(v)}%" for v in cvs], fontsize=8)
    ax.set_yticks(range(len(corrs)))
    ax.set_yticklabels(corrs, fontsize=8.5)
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    for i in range(len(corrs)):
        for j in range(len(cvs)):
            v = piv.values[i, j]
            ax.text(j, i, coma(v), ha="center", va="center", fontsize=8.5,
                    color="white" if v >= 75 else TEXTO)
axes[0].set_ylabel("Correlación entre etiquetas")
cb = fig.colorbar(im, ax=axes, fraction=0.025, pad=0.02)
cb.set_label("Ahorro frente a MTS (%)", fontsize=8.5)
cb.ax.tick_params(labelsize=7.5)
cb.outline.set_visible(False)
fig.savefig(os.path.join(CARPETA, "fig_factorial.pdf"))
fig.savefig(os.path.join(CARPETA, "fig_factorial.png"))
plt.close(fig)

print(f"Figuras para el informe guardadas en '{CARPETA}/'")
