"""
analisis.py
===========
Análisis de sensibilidad del proyecto (Capstone G27).

Cada análisis copia los datos, cambia UNA sola cosa y resuelve las tres
políticas (Postergación, MTS y MTO sin stock) con esos datos:

    1. Variabilidad: desviación estándar = 10%, 30%, 50% de la media (CV)
    2. Capacidad:    21, 42, 63 y 84 horas por período
    3. Etiquetas:    cuántas y cuáles etiquetas se permite postergar (0, 2, 3, 4, 5)
    4. Correlación:  demandas de las etiquetas de un mismo vino positiva / negativa

Cómo correrlo (desde la carpeta del proyecto):
    python analisis.py                 -> todos los análisis
    python analisis.py variabilidad    -> solo variabilidad
    python analisis.py capacidad       -> solo capacidad
    python analisis.py etiquetas       -> solo etiquetas
    python analisis.py correlacion     -> solo correlación

Cada análisis genera un Excel con dos hojas:
    Resumen -> una fila por nivel: costo de cada política y ahorro de postergar
    Detalle -> una fila por nivel y política: desglose del costo y KPI operacionales
"""

import itertools
import math
import sys

import pandas as pd
from gurobipy import GRB

from src.data_loader import load_data
from src.core_model import build_base_model
from src.policies import apply_mts_policy, apply_mto_policy


# Políticas a comparar. "None" = modelo base (postergación), sin restricciones extra.
POLITICAS = {
    "Postergación": None,
    "MTS": apply_mts_policy,
    "MTO sin stock": apply_mto_policy,
}


# =============================================================================
# 1. Cambiar los datos
# =============================================================================

def nodos_del_periodo(data, t):
    """Lista de nodos que pertenecen al período t."""
    return [n for n in data['nodos'] if data['periodos_nodo'][n] == t]


def media_y_desviacion(data, producto, t):
    """Media y desviación estándar de la demanda de un producto en el período t,
    ponderadas por la probabilidad de cada nodo (en cada período suman 1)."""
    i, j = producto
    prob = data['probabilidades']
    nodos_t = nodos_del_periodo(data, t)

    media = sum(prob[n] * data['demandas'][(i, j, n)] for n in nodos_t)
    varianza = sum(prob[n] * (data['demandas'][(i, j, n)] - media) ** 2 for n in nodos_t)
    return media, math.sqrt(varianza)


def datos_con_cv(data, cv):
    """Copia de 'data' en que cada producto, en cada período, tiene desviación
    estándar = cv * media. Se escala la distancia de cada nodo a la media:

        d_nueva = mu + k * (d - mu),   con  k = cv * mu / sigma

    Así la media y la correlación entre productos no cambian; solo la dispersión."""
    nuevas = dict(data['demandas'])                     # copia de la demanda

    for producto in data['productos']:
        for t in set(data['periodos_nodo'].values()):
            mu, sigma = media_y_desviacion(data, producto, t)
            if sigma == 0:
                continue                                # período 1: demanda conocida
            k = cv * mu / sigma
            for n in nodos_del_periodo(data, t):
                d = data['demandas'][(*producto, n)]
                nuevas[(*producto, n)] = max(0.0, mu + k * (d - mu))

    data_cv = dict(data)
    data_cv['demandas'] = nuevas
    return data_cv


def datos_con_capacidad(data, horas):
    """Copia de 'data' con otra capacidad por período. Las Big-M se recalculan
    porque dependen de la capacidad: M = K / t (botellas máximas por período)."""
    data_k = dict(data)
    data_k['capacidad_horas'] = horas
    data_k['M_wb'] = horas / data['t_wb']
    data_k['M_wbl'] = horas / data['t_wbl']
    data_k['M_wl'] = horas / data['t_wl']
    return data_k


# =============================================================================
# 2. Resolver y medir
# =============================================================================

def resolver(data, aplicar_politica):
    """Arma el modelo base, le agrega la política (si corresponde) y lo resuelve."""
    modelo, v = build_base_model(data)
    if aplicar_politica is not None:
        modelo = aplicar_politica(modelo, v, data)
    modelo.optimize()
    return modelo, v


def horas_usadas(v, data, n):
    """Horas de línea usadas en el nodo n (lado izquierdo de la restricción 4.2)."""
    vinos, etiq = data['vinos'], data['etiquetas_por_vino']
    return sum(data['t_wb'] * v['w_b'][i, n].X + data['t_zb'] * v['z_b'][i, n].X
               for i in vinos) + \
           sum(data['t_wbl'] * v['w_bl'][i, j, n].X + data['t_zbl'] * v['z_bl'][i, j, n].X +
               data['t_wl'] * v['w_l'][i, j, n].X + data['t_zl'] * v['z_l'][i, j, n].X
               for i in vinos for j in etiq[i])


def calcular_kpis(modelo, v, data):
    """KPI esperados de la solución (ponderados por la probabilidad de cada nodo)."""
    vinos, etiq = data['vinos'], data['etiquetas_por_vino']
    prob = data['probabilidades']
    ultimo = max(data['periodos_nodo'].values())
    productos = [(i, j) for i in vinos for j in etiq[i]]

    setup = wip = terminado = atraso = 0.0
    demanda = a_tiempo = postergada = 0.0
    util_max = horas_ultimo = 0.0

    for n in data['nodos']:
        p = prob[n]

        # Costos: los mismos cuatro términos de la función objetivo (4.1)
        setup += p * (sum(data['C_zb'] * v['z_b'][i, n].X for i in vinos) +
                      sum(data['C_zbl'] * v['z_bl'][i, j, n].X + data['C_zl'] * v['z_l'][i, j, n].X
                          for i, j in productos))
        wip += p * data['C_sb'] * sum(v['s_b'][i, n].X for i in vinos)
        terminado += p * data['C_sbl'] * sum(v['s_bl'][i, j, n].X for i, j in productos)
        atraso += p * data['C_bbl'] * sum(v['b_bl'][i, j, n].X for i, j in productos)

        # Capacidad: nodo más cargado y horas usadas en el último período
        h = horas_usadas(v, data, n)
        util_max = max(util_max, h / data['capacidad_horas'])
        if data['periodos_nodo'][n] == ultimo:
            horas_ultimo += p * h

        # Servicio (desde el período 2; el período 1 está predefinido). Atendiendo
        # primero lo más antiguo (FIFO), lo atrasado al cierre del nodo es demanda
        # reciente: la demanda del nodo no atendida a tiempo es min(d, b).
        if data['periodos_nodo'][n] >= 2:
            for i, j in productos:
                d = data['demandas'][(i, j, n)]
                demanda += p * d
                a_tiempo += p * (d - min(d, v['b_bl'][i, j, n].X))
                postergada += p * v['w_l'][i, j, n].X     # etiquetado desde el WIP

    atraso_final = sum(prob[n] * v['b_bl'][i, j, n].X
                       for n in nodos_del_periodo(data, ultimo) for i, j in productos)

    return {
        'Costo total ($)': modelo.ObjVal,
        'Set-ups ($)': setup,
        'Inventario WIP ($)': wip,
        'Inventario terminado ($)': terminado,
        'Atrasos ($)': atraso,
        'Servicio a tiempo (%)': 100 * a_tiempo / demanda,
        'Atraso final (bot)': atraso_final,
        'Demanda postergada (%)': 100 * postergada / demanda,
        'Utilización máxima (%)': 100 * util_max,
        'Horas período 3 (h)': horas_ultimo,
    }


def comparar_politicas(data, nivel):
    """Resuelve las tres políticas con los mismos datos y compara sus costos.
    Devuelve la fila del resumen y las filas del detalle (una por política)."""
    detalle = []
    costo = {}
    for nombre, aplicar in POLITICAS.items():
        modelo, v = resolver(data, aplicar)
        if modelo.status != GRB.OPTIMAL:
            raise RuntimeError(f"{nombre} ({nivel}) no llegó al óptimo")
        kpis = calcular_kpis(modelo, v, data)
        costo[nombre] = kpis['Costo total ($)']
        detalle.append({'Nivel': nivel, 'Política': nombre, **kpis})

    post, mts, mto = costo["Postergación"], costo["MTS"], costo["MTO sin stock"]
    resumen = {
        'Nivel': nivel,
        'Postergación ($)': post,
        'MTS ($)': mts,
        'MTO sin stock ($)': mto,
        'Valor de postergar vs MTS ($)': mts - post,
        'Ahorro vs MTS (%)': 100 * (mts - post) / mts,      # ecuación 4.17
        'Ahorro vs MTO (%)': 100 * (mto - post) / mto,
    }
    return resumen, detalle


# =============================================================================
# 3. Correr un análisis completo
# =============================================================================

def correr_analisis(titulo, escenarios, archivo):
    """'escenarios' es una lista de (nombre del nivel, datos de ese nivel)."""
    filas_resumen, filas_detalle = [], []
    for nivel, datos in escenarios:
        print(f"   Resolviendo {titulo}: {nivel} ...")
        resumen, detalle = comparar_politicas(datos, nivel)
        filas_resumen.append(resumen)
        filas_detalle.extend(detalle)

    resumen = pd.DataFrame(filas_resumen)
    print("\n" + "=" * 90)
    print(f" {titulo.upper()}")
    print("=" * 90)
    print(resumen.to_string(index=False, float_format='{:,.2f}'.format))

    with pd.ExcelWriter(archivo) as excel:
        resumen.to_excel(excel, sheet_name='Resumen', index=False)
        pd.DataFrame(filas_detalle).to_excel(excel, sheet_name='Detalle', index=False)
    print(f"\nResultados guardados en '{archivo}'\n")


def analisis_variabilidad(data):
    escenarios = [("Original", data)]
    for cv in (0.10, 0.30, 0.50):
        escenarios.append((f"CV {cv:.0%}", datos_con_cv(data, cv)))
    correr_analisis("Variabilidad de la demanda", escenarios, "resultados_variabilidad.xlsx")


def analisis_capacidad(data):
    escenarios = [(f"{h} h", datos_con_capacidad(data, h)) for h in (21, 42, 63, 84)]
    correr_analisis("Capacidad de la línea", escenarios, "resultados_capacidad.xlsx")


# =============================================================================
# ANÁLISIS 3. Etiquetas cuya postergación se permite: 0, 2, 3, 4 y 5
# =============================================================================
# A diferencia de los otros, aquí no se cambian los datos: se agrega la
# restricción (4.16) w_l[i,j,n] = 0 para los productos que NO se pueden postergar.
# Regla del enunciado: una botella sin etiqueta debe poder convertirse en al
# menos dos productos, así que de cada vino se habilitan 0 o al menos 2 etiquetas.
# =============================================================================

def combinaciones_validas(data):
    """Todas las combinaciones de productos postergables que cumplen la regla."""
    opciones_por_vino = []
    for i in data['vinos']:
        prods = [(i, j) for j in data['etiquetas_por_vino'][i]]
        opciones = [()]                                   # ninguna etiqueta del vino
        for r in range(2, len(prods) + 1):                # o al menos 2
            opciones += list(itertools.combinations(prods, r))
        opciones_por_vino.append(opciones)
    # Combinar una opción de cada vino: 5 opciones (vino 1) x 2 (vino 2) = 10
    return [sum(combo, ()) for combo in itertools.product(*opciones_por_vino)]


def solo_postergar(permitidos):
    """Devuelve una 'política' que prohíbe etiquetar desde el WIP (w_l = 0)
    a los productos que no están en 'permitidos' (restricción 4.16)."""
    def aplicar(modelo, v, data):
        for (i, j) in data['productos']:
            if (i, j) not in permitidos:
                for n in data['nodos']:
                    modelo.addConstr(v['w_l'][i, j, n] == 0, name=f"no_post_{i}_{j}_{n}")
        modelo.update()
        return modelo
    return aplicar


def analisis_etiquetas(data, archivo="resultados_etiquetas.xlsx"):
    # MTS no depende de qué etiquetas se posterguen: se resuelve una sola vez
    modelo, v = resolver(data, apply_mts_policy)
    costo_mts = modelo.ObjVal

    filas = []
    for permitidos in combinaciones_validas(data):
        modelo, v = resolver(data, solo_postergar(permitidos))
        if modelo.status != GRB.OPTIMAL:
            raise RuntimeError(f"Combinación {permitidos} no llegó al óptimo")
        kpis = calcular_kpis(modelo, v, data)
        filas.append({
            'N° etiquetas': len(permitidos),
            'Etiquetas postergables': ", ".join(f"({i},{j})" for i, j in permitidos) or "Ninguna",
            'Ahorro vs MTS (%)': 100 * (costo_mts - kpis['Costo total ($)']) / costo_mts,
            **kpis,
        })

    todas = pd.DataFrame(filas).sort_values(['N° etiquetas', 'Costo total ($)'])
    # Parte del ahorro máximo (todas las etiquetas) que logra cada combinación
    ahorro_max = todas['Ahorro vs MTS (%)'].max()
    todas.insert(3, '% del ahorro máximo', 100 * todas['Ahorro vs MTS (%)'] / ahorro_max)

    # Resumen: la mejor combinación para cada número de etiquetas
    mejores = todas.groupby('N° etiquetas', as_index=False).first()
    resumen = mejores[['N° etiquetas', 'Etiquetas postergables', 'Costo total ($)',
                       'Ahorro vs MTS (%)', '% del ahorro máximo']]

    print("\n" + "=" * 90)
    print(" ETIQUETAS POSTERGABLES (mejor combinación para cada número de etiquetas)")
    print("=" * 90)
    print(resumen.to_string(index=False, float_format='{:,.2f}'.format))

    with pd.ExcelWriter(archivo) as excel:
        resumen.to_excel(excel, sheet_name='Resumen', index=False)
        todas.to_excel(excel, sheet_name='Todas las combinaciones', index=False)
    print(f"\nResultados guardados en '{archivo}'\n")


# =============================================================================
# ANÁLISIS 4. Correlación entre las demandas de las etiquetas de un mismo vino
# =============================================================================
# Se mantiene la media y la desviación estándar de cada producto en cada período
# (las originales) y se cambia SOLO cómo se mueven las etiquetas entre sí.
#
# Cada producto se arma como  d = mu + sigma * z,  donde z es un "patrón" sobre
# los nodos del período con media 0 y desviación 1. Se usan dos patrones
# perpendiculares (correlación 0 entre ellos):
#     z_a: el estado de la demanda (alta / media / baja), sacado de la demanda total
#     z_b: un segundo patrón perpendicular a z_a
# y cada etiqueta k del vino toma la mezcla  z = cos(ang_k)*z_a + sin(ang_k)*z_b.
# La correlación entre dos etiquetas es el coseno del ángulo entre ellas:
#     Positiva: todas con ángulo 0              -> correlación +1
#     Negativa: ángulos repartidos en el círculo -> vino 2 (2 etiquetas, 180°): -1
#                                                  vino 1 (3 etiquetas, 120°): -0,5
# (-0,5 es lo más negativo posible para tres productos a la vez.)
# =============================================================================

def estandarizar(data, valores):
    """Deja un patrón {nodo: valor} con media 0 y desviación 1 (ponderadas)."""
    prob = data['probabilidades']
    media = sum(prob[n] * x for n, x in valores.items())
    sd = math.sqrt(sum(prob[n] * (x - media) ** 2 for n, x in valores.items()))
    return {n: (x - media) / sd for n, x in valores.items()}


def patrones_base(data, t):
    """Los dos patrones perpendiculares z_a y z_b de los nodos del período t."""
    prob = data['probabilidades']
    nodos_t = nodos_del_periodo(data, t)

    # z_a: estado de la demanda = demanda total de todos los productos en cada nodo
    total = {n: sum(data['demandas'][(i, j, n)] for i, j in data['productos']) for n in nodos_t}
    z_a = estandarizar(data, total)

    # z_b: se parte de z_a^2 (qué tan extremo es el nodo) y se le quita la parte
    # que se parece a z_a (Gram-Schmidt), para que quede perpendicular a z_a
    u = {n: z_a[n] ** 2 for n in nodos_t}
    parecido = sum(prob[n] * u[n] * z_a[n] for n in nodos_t)
    z_b = estandarizar(data, {n: u[n] - parecido * z_a[n] for n in nodos_t})
    return z_a, z_b


def datos_con_correlacion(data, tipo):
    """Copia de 'data' con correlación 'positiva' o 'negativa' entre las etiquetas
    de cada vino, manteniendo la media y la desviación de cada producto."""
    nuevas = dict(data['demandas'])

    for t in set(data['periodos_nodo'].values()):
        if len(nodos_del_periodo(data, t)) == 1:
            continue                                    # período 1: demanda conocida
        z_a, z_b = patrones_base(data, t)

        for i in data['vinos']:
            etiquetas = data['etiquetas_por_vino'][i]
            for k, j in enumerate(etiquetas):
                angulo = 0 if tipo == "positiva" else 2 * math.pi * k / len(etiquetas)
                mu, sigma = media_y_desviacion(data, (i, j), t)
                for n in z_a:
                    z = math.cos(angulo) * z_a[n] + math.sin(angulo) * z_b[n]
                    nuevas[(i, j, n)] = max(0.0, mu + sigma * z)   # con estos datos nunca < 0

    data_c = dict(data)
    data_c['demandas'] = nuevas
    return data_c


def analisis_correlacion(data):
    escenarios = [("Original", data),
                  ("Positiva", datos_con_correlacion(data, "positiva")),
                  ("Negativa", datos_con_correlacion(data, "negativa"))]
    correr_analisis("Correlación de la demanda", escenarios, "resultados_correlacion.xlsx")


if __name__ == "__main__":
    pedido = sys.argv[1] if len(sys.argv) > 1 else "todos"
    data = load_data()

    if pedido in ("variabilidad", "todos"):
        analisis_variabilidad(data)
    if pedido in ("capacidad", "todos"):
        analisis_capacidad(data)
    if pedido in ("etiquetas", "todos"):
        analisis_etiquetas(data)
    if pedido in ("correlacion", "todos"):
        analisis_correlacion(data)
