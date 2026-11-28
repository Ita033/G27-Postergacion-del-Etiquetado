"""
escalamiento.py

Tiempos de resolución con instancias más grandes que la del Anexo A
(Tabla 5.8 y Figura D.5 del informe). Se prueban 6, 30 y 150 etiquetas
y horizontes de 3 a 8 semanas de 84 horas.

Se corre desde la raíz del repo:  python escalamiento.py
Guarda los resultados en out_7_escalamiento_realista.xlsx después de cada
instancia. Puede tardar varias horas (límite de 2000 s por instancia).
La figura D.5 se genera después con graficos/graficos.py.
"""
import io
import time
import random
import contextlib

import pandas as pd
from gurobipy import GRB

from src.data_loader import load_data
from src.core_model import build_base_model
from analisis import clonar_datos

ARCHIVO_SALIDA = "out_7_escalamiento_realista.xlsx"
LIMITE_TIEMPO = 2000   # segundos por instancia (~33 minutos)
MIP_GAP = 0.005        # se acepta una solución a menos de 0,5% del óptimo

# Transiciones del árbol del Anexo A: desde Alta no se pasa a Baja ni viceversa.
TRANSICIONES = {
    "Raiz": [("Media", 1.0)],
    "Alta": [("Alta", 0.7), ("Media", 0.3)],
    "Media": [("Alta", 0.3), ("Media", 0.4), ("Baja", 0.3)],
    "Baja": [("Media", 0.6), ("Baja", 0.4)],
}


def generar_instancia(data_base, T_periodos, n_vinos, etiq_por_vino, seed=42):
    """Instancia sintética con el árbol del Anexo A y períodos de una semana (84 h).

    Supuestos:
      - Demanda total de ~100.000 botellas por semana (como el caso base), repartida
        entre las etiquetas, con un factor según el estado: Alta 1,35, Media 1, Baja 0,65.
      - Desde el período 2 cada nodo tiene además un ruido de +-8%.
      - Con muchas etiquetas los lotes son más chicos, así que los tiempos de set-up se
        reducen en proporción para que la línea siga siendo factible.
    Con T = 3, 4 y 8 el árbol tiene 11, 28 y 984 nodos.
    """
    rng = random.Random(seed)
    vinos = list(range(1, n_vinos + 1))
    etiquetas = {i: list(range(1, etiq_por_vino + 1)) for i in vinos}
    productos = [(i, j) for i in vinos for j in etiquetas[i]]

    nodos, antecesores, probabilidades, periodos_nodo, estados = [], {}, {}, {}, {}
    nivel = [(0, 1.0, "Raiz")]
    for t in range(1, T_periodos + 1):
        siguiente = []
        for padre, p_padre, estado_padre in nivel:
            for estado, p_rama in TRANSICIONES[estado_padre]:
                n = len(nodos) + 1
                nodos.append(n)
                antecesores[n] = padre
                probabilidades[n] = p_padre * p_rama
                periodos_nodo[n] = t
                estados[n] = estado
                siguiente.append((n, p_padre * p_rama, estado))
        nivel = siguiente

    factor_estado = {"Alta": 1.35, "Media": 1.00, "Baja": 0.65}
    demanda_media = 100000.0 / len(productos)
    demandas = {}
    for (i, j) in productos:
        base = demanda_media * rng.uniform(0.85, 1.15)
        for n in nodos:
            ruido = 1.0 if periodos_nodo[n] == 1 else rng.uniform(0.92, 1.08)
            demandas[(i, j, n)] = base * factor_estado[estados[n]] * ruido

    escala_setup = min(1.0, (5.0 / len(productos)) * 2.0)  # 6 etiquetas: 1; 30: 0,33; 150: 0,07
    return clonar_datos(
        data_base,
        vinos=vinos,
        etiquetas_por_vino=etiquetas,
        nodos=nodos,
        antecesores=antecesores,
        probabilidades=probabilidades,
        periodos_nodo=periodos_nodo,
        estados_demanda=estados,
        demandas=demandas,
        capacidad_horas=84.0,
        periodos_horizonte=T_periodos,
        estanques_disp=max(20, int(round(data_base['estanques_disp']))),
        t_zb=data_base['t_zb'] * escala_setup,
        t_zbl=data_base['t_zbl'] * escala_setup,
        t_zl=data_base['t_zl'] * escala_setup,
    )


def main():
    with contextlib.redirect_stdout(io.StringIO()):
        data = load_data()

    portafolios = [(2, 3), (5, 6), (10, 15)]  # (vinos, etiquetas por vino): 6, 30 y 150 etiquetas
    filas = []
    for nv, ne in portafolios:
        for T in range(3, 9):
            d = generar_instancia(data, T, nv, ne)
            t0 = time.perf_counter()
            with contextlib.redirect_stdout(io.StringIO()):
                m, _ = build_base_model(d)
            t_build = time.perf_counter() - t0

            m.setParam("TimeLimit", LIMITE_TIEMPO)
            m.setParam("MIPGap", MIP_GAP)
            m.optimize()

            if m.Status == GRB.OPTIMAL:
                estado = "Óptimo"
            elif m.SolCount > 0:
                estado = "Factible (TimeLimit)"
            else:
                estado = f"Sin sol ({m.Status})"
            gap = round(100.0 * m.MIPGap, 4) if m.SolCount > 0 else None
            # Mismas columnas que usa la figura D.5 en graficos/graficos.py
            filas.append({
                'Portafolio': f"{nv * ne} SKUs ({nv}V x {ne}E)",
                '|P| (SKUs)': nv * ne,
                'Vinos': nv,
                'Etiq/Vino': ne,
                'Régimen': "Semanal (1 sem = 84h)",
                'Horizonte': f"{T} sem",
                'T (períodos)': T,
                'K (h/período)': 84.0,
                'Horas Totales Horizonte': T * 84.0,
                'Nodos Árbol': len(d['nodos']),
                'Vars Totales': m.NumVars,
                'Vars Binarias': m.NumBinVars,
                'Restricciones': m.NumConstrs,
                'Build (s)': round(t_build, 4),
                'Solver Gurobi (s)': round(m.Runtime, 4),
                'Tiempo Total (s)': round(t_build + m.Runtime, 4),
                'MIPGap (%)': gap,
                'Estado': estado,
            })
            print(f"{nv * ne:>3} etiquetas, {T} semanas ({len(d['nodos'])} nodos): "
                  f"{m.Runtime:.2f} s, gap {gap}%, {estado}")
            # Se guarda después de cada instancia para no perder lo avanzado si se corta.
            pd.DataFrame(filas).to_excel(ARCHIVO_SALIDA, index=False)

    print(f"\n(Resultados guardados en '{ARCHIVO_SALIDA}')")


if __name__ == "__main__":
    main()
