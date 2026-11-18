import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
from matplotlib.colors import LinearSegmentedColormap

# ==============================================================================
# CONFIGURACIÓN DE RUTAS Y ESTILO VISUAL (Paleta Burdeo / Dorado de la PPT)
# ==============================================================================
RUTA_EXCEL = "."
CARPETA_SALIDA = "graficos_pedro_nico"
os.makedirs(CARPETA_SALIDA, exist_ok=True)

BURDEO = "#5C1622"
BURDEO_CLARO = "#8E283B"
DORADO = "#B89B6A"
GRIS_OSCURO = "#2B2B2B"

plt.rcParams.update({
    "font.sans-serif": "DejaVu Sans",
    "axes.edgecolor": "#CCCCCC",
    "axes.linewidth": 0.8,
    "figure.dpi": 300
})

# ==============================================================================
# 1. CARGAR DATOS DESDE LOS EXCEL YA GENERADOS
# ==============================================================================
f_out1 = os.path.join(RUTA_EXCEL, "out_1_capacidad_y_saturacion.xlsx")
f_out2 = os.path.join(RUTA_EXCEL, "out_2_factorial_K_CV_Corr.xlsx")

xl1 = pd.ExcelFile(f_out1)
hoja_barrido = next(s for s in xl1.sheet_names if "barrido" in s.lower() or "fino" in s.lower())
hoja_diag = next((s for s in xl1.sheet_names if s != hoja_barrido), hoja_barrido)

df_barrido = pd.read_excel(xl1, sheet_name=hoja_barrido)
df_diag = pd.read_excel(xl1, sheet_name=hoja_diag)

xl2 = pd.ExcelFile(f_out2)
hoja_fact = next((s for s in xl2.sheet_names if "fact" in s.lower() or "27" in s), xl2.sheet_names[0])
df_fact = pd.read_excel(xl2, sheet_name=hoja_fact)


def col_match(df, candidatos):
    cols_lower = {c.lower().strip(): c for c in df.columns}
    for cand in candidatos:
        for k, orig in cols_lower.items():
            if cand.lower() in k:
                return orig
    raise KeyError(f"No se encontró ninguna columna similar a {candidatos} en {list(df.columns)}")


# ==============================================================================
# GRÁFICO 1: CURVA EN CAMPANA DEL AHORRO Y ATRASOS (BARRIDO FINO K = 20..84 h)
# ==============================================================================
df_barrido = df_barrido.sort_values(by="K (h)")
K_vals = df_barrido["K (h)"].values
ahorro_vals = df_barrido["Ahorro_MTS_pct"].values
if np.nanmax(ahorro_vals) <= 1.5:
    ahorro_vals = ahorro_vals * 100.0

fig, ax1 = plt.subplots(figsize=(9.5, 4.8))
ax2 = ax1.twinx()

ancho = 1.4
b1 = ax2.bar(K_vals - ancho / 2, df_barrido["Backlog_MTS"] / 1000.0, width=ancho,
             color=DORADO, alpha=0.45, label="Atraso terminal MTS (miles bot.)")
b2 = ax2.bar(K_vals + ancho / 2, df_barrido["Backlog_Post"] / 1000.0, width=ancho,
             color=GRIS_OSCURO, alpha=0.45, label="Atraso terminal Postergación (miles bot.)")

l1 = ax1.plot(K_vals, ahorro_vals, color=BURDEO, marker="o", linewidth=2.8,
              markersize=6.5, label="Ahorro frente a MTS (%)", zorder=5)

for k_target in [20, 44, 64, 84]:
    idx = (np.abs(K_vals - k_target)).argmin()
    ax1.annotate(f"{ahorro_vals[idx]:.1f}%",
                 xy=(K_vals[idx], ahorro_vals[idx]),
                 xytext=(0, 10), textcoords="offset points",
                 ha="center", fontsize=9.5, fontweight="bold", color=BURDEO)

ax1.set_title("El ahorro alcanza su máximo (99,9%) en capacidad estrecha antes de saturar la línea",
              fontsize=12.5, fontweight="bold", color=BURDEO, pad=32)
ax1.set_xlabel("Capacidad disponible por período (horas)", fontsize=10.5, fontweight="bold", color=GRIS_OSCURO)
ax1.set_ylabel("Ahorro de costo esperado vs. MTS (%)", fontsize=10.5, fontweight="bold", color=BURDEO)
ax2.set_ylabel("Atraso terminal en t=3 (miles de botellas)", fontsize=10, color="#665533")

ax1.set_ylim(0, 112)
ax1.set_xticks(K_vals)
ax1.yaxis.set_major_formatter(mtick.PercentFormatter())
ax1.grid(axis="y", linestyle="--", alpha=0.4)
ax1.spines["top"].set_visible(False)
ax2.spines["top"].set_visible(False)

# Leyenda compacta horizontal justo debajo del título (cero superposición con la curva)
handles = l1 + [b1, b2]
labels = [h.get_label() for h in handles]
ax1.legend(handles, labels, loc="lower center", bbox_to_anchor=(0.5, 1.01),
           ncol=3, frameon=True, facecolor="white", framealpha=0.95, fontsize=8.2)

plt.tight_layout()
plt.savefig(os.path.join(CARPETA_SALIDA, "fig1_campana_capacidad.png"))
plt.close()


# ==============================================================================
# GRÁFICO 2: MECANISMO FÍSICO (TASA DE POSTERGACIÓN VS. NODOS SATURADOS)
# ==============================================================================
df_diag = df_diag.sort_values(by="K (h)", ascending=False).copy()  # 84 -> 63 -> 42 -> 21
etiquetas_k = [f"{int(k)} h" for k in df_diag["K (h)"]]

# Obtener tasa de postergación desde df_barrido (buscando el K más cercano en el barrido)
tasa_vals = []
for k_val in df_diag["K (h)"]:
    idx_cercano = (df_barrido["K (h)"] - k_val).abs().idxmin()
    val = df_barrido.loc[idx_cercano, "Tasa_Post_pct"]
    tasa_vals.append(val * 100.0 if val <= 1.5 else val)
tasa_vals = np.array(tasa_vals)

fig, (ax_top, ax_bot) = plt.subplots(1, 2, figsize=(9.5, 4.0))

# Subgráfico A: Tasa de postergación activa
bars = ax_top.bar(etiquetas_k, tasa_vals, color=[BURDEO, BURDEO_CLARO, DORADO, "#C9B79C"], width=0.55)
for bar, val in zip(bars, tasa_vals):
    ax_top.text(bar.get_x() + bar.get_width() / 2, val + 2.5, f"{val:.1f}%",
                ha="center", fontsize=10, fontweight="bold", color=GRIS_OSCURO)
ax_top.set_title("Tasa de postergación activa (%)", fontsize=11, fontweight="bold", color=BURDEO)
ax_top.set_ylim(0, 115)
ax_top.yaxis.set_major_formatter(mtick.PercentFormatter())
ax_top.grid(axis="y", linestyle="--", alpha=0.4)
ax_top.spines["top"].set_visible(False)
ax_top.spines["right"].set_visible(False)

# Subgráfico B: Nodos saturados al 100% (MTS vs Postergación)
x = np.arange(len(etiquetas_k))
w = 0.35
b_mts = ax_bot.bar(x - w / 2, df_diag["Nodos Sat MTS"], width=w, color=DORADO, label="MTS puro")
b_pos = ax_bot.bar(x + w / 2, df_diag["Nodos Sat Post"], width=w, color=BURDEO, label="Postergación")
for bar in b_mts:
    h = bar.get_height()
    ax_bot.text(bar.get_x() + bar.get_width() / 2, h + 0.25, f"{int(h)}", ha="center", fontsize=9.5, color="#554422", fontweight="bold")
for bar in b_pos:
    h = bar.get_height()
    ax_bot.text(bar.get_x() + bar.get_width() / 2, h + 0.25, f"{int(h)}", ha="center", fontsize=9.5, color=BURDEO, fontweight="bold")

ax_bot.set_title("Nodos saturados al 100% (de 11 nodos)", fontsize=11, fontweight="bold", color=BURDEO)
ax_bot.set_xticks(x)
ax_bot.set_xticklabels(etiquetas_k)
ax_bot.set_ylim(0, 11)
ax_bot.grid(axis="y", linestyle="--", alpha=0.4)
ax_bot.spines["top"].set_visible(False)
ax_bot.spines["right"].set_visible(False)
ax_bot.legend(frameon=True, facecolor="white", fontsize=9)

plt.tight_layout()
plt.savefig(os.path.join(CARPETA_SALIDA, "fig2_saturacion_y_postergacion.png"))
plt.close()

# ==============================================================================
# GRÁFICO 3: HEATMAP FACTORIAL 3x3x3 (CAPACIDAD x CORRELACIÓN x CV)
# ==============================================================================
c_kf = col_match(df_fact, ["k (h)", "capacidad", "k"])
c_corr = col_match(df_fact, ["corr"])
c_cv = col_match(df_fact, ["cv"])
c_ah_f = col_match(df_fact, ["ahorro"])

df_fact = df_fact.copy()
if df_fact[c_ah_f].max() <= 1.5:
    df_fact[c_ah_f] = df_fact[c_ah_f] * 100.0
if df_fact[c_cv].max() <= 1.5:
    df_fact[c_cv] = (df_fact[c_cv] * 100).round().astype(int)

capacidades_f = sorted(df_fact[c_kf].unique())
orden_corr = ["Negativa", "Original", "Positiva"]
corrs_presentes = [c for c in orden_corr if c in df_fact[c_corr].unique()]
if not corrs_presentes:
    corrs_presentes = sorted(df_fact[c_corr].unique())
cvs_presentes = sorted(df_fact[c_cv].unique())

fig, axes = plt.subplots(1, len(capacidades_f), figsize=(11.5, 4.2), sharey=True)
if len(capacidades_f) == 1:
    axes = [axes]

cmap_burdeo = LinearSegmentedColormap.from_list("burdeo_ppt", ["#F7F3EE", "#D9B38C", "#8E283B", "#5C1622"])

for ax, k_val in zip(axes, capacidades_f):
    sub = df_fact[df_fact[c_kf] == k_val]
    piv = sub.pivot(index=c_corr, columns=c_cv, values=c_ah_f).reindex(index=corrs_presentes, columns=cvs_presentes)
    im = ax.imshow(piv.values, cmap=cmap_burdeo, vmin=50, vmax=100, aspect="auto")

    ax.set_title(f"Capacidad K = {int(k_val)} h", fontsize=11.5, fontweight="bold", color=BURDEO, pad=10)
    ax.set_xticks(np.arange(len(cvs_presentes)))
    ax.set_xticklabels([f"CV {int(v)}%" for v in cvs_presentes], fontsize=9.5, fontweight="bold")
    ax.set_yticks(np.arange(len(corrs_presentes)))
    ax.set_yticklabels(corrs_presentes, fontsize=9.5, fontweight="bold")

    for i in range(len(corrs_presentes)):
        for j in range(len(cvs_presentes)):
            val = piv.values[i, j]
            color_txt = "white" if val >= 82 else GRIS_OSCURO
            ax.text(j, i, f"{val:.1f}%", ha="center", va="center",
                    color=color_txt, fontsize=10, fontweight="bold")

axes[0].set_ylabel("Correlación intra-período", fontsize=10.5, fontweight="bold", color=GRIS_OSCURO)
fig.suptitle("Ahorro frente a MTS (%) según Capacidad, Correlación y Variabilidad (CV)",
             fontsize=13, fontweight="bold", color=BURDEO, y=1.02)

cbar = fig.colorbar(im, ax=axes, orientation="vertical", fraction=0.025, pad=0.03)
cbar.set_label("Ahorro vs. MTS (%)", fontsize=9.5, fontweight="bold", color=GRIS_OSCURO)
cbar.ax.yaxis.set_major_formatter(mtick.PercentFormatter())

plt.savefig(os.path.join(CARPETA_SALIDA, "fig3_heatmap_factorial.png"), bbox_inches="tight")
plt.close()

print(f"Gráficos generados exitosamente en la carpeta: '{CARPETA_SALIDA}/'")