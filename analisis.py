"""
analisis.py
===========
Suite autocontenida de análisis de sensibilidad, benchmarks y experimentos
hipotéticos (What-If) para la Entrega Final (Grupo 27).

No modifica data_loader.py, core_model.py, policies.py ni main.py.
Imprime todas las tablas en consola y guarda respaldos en Excel (out_1 a out_6).

Uso desde la raíz del repo:
  python analisis.py              -> corre los 6 bloques completos
  python analisis.py capacidad    -> solo diagnóstico de saturación y K
  python analisis.py factorial    -> solo diseño K x CV x Correlación
  python analisis.py etiquetas    -> solo postergación parcial en K=84,63,42
  python analisis.py benchmarks   -> solo Híbrido Realista (MTS+MTO) y VMS
  python analisis.py whatif       -> solo costos (C_bbl, C_sb), doble manejo y borde t=3
  python analisis.py computo      -> solo escalamiento de tiempos de cómputo
"""

import os
import sys
import io
import time
import math
import random
import itertools
import contextlib

import pandas as pd
import gurobipy as gp
from gurobipy import GRB

from src.data_loader import load_data
from src.core_model import build_base_model
from src.policies import apply_mts_policy, apply_mto_policy


# =============================================================================
# 1. UTILIDADES SOBRE DATOS Y ESTADÍSTICA INTRA-PERÍODO
# =============================================================================

def obtener_productos(data):
    return [(i, j) for i in data['vinos'] for j in data['etiquetas_por_vino'][i]]


def nodos_del_periodo(data, t):
    return [n for n in data['nodos'] if data['periodos_nodo'][n] == t]


def media_y_desviacion(data, producto, t):
    i, j = producto
    prob = data['probabilidades']
    ns = nodos_del_periodo(data, t)
    mu = sum(prob[n] * data['demandas'][(i, j, n)] for n in ns)
    var = sum(prob[n] * (data['demandas'][(i, j, n)] - mu) ** 2 for n in ns)
    return mu, math.sqrt(var)


def correlacion_intra_periodo(data, prod1, prod2, t):
    prob = data['probabilidades']
    ns = nodos_del_periodo(data, t)
    mu1, sd1 = media_y_desviacion(data, prod1, t)
    mu2, sd2 = media_y_desviacion(data, prod2, t)
    if sd1 == 0 or sd2 == 0:
        return 0.0
    cov = sum(prob[n] * (data['demandas'][(*prod1, n)] - mu1) * (data['demandas'][(*prod2, n)] - mu2) for n in ns)
    return cov / (sd1 * sd2)


def clonar_datos(data, **cambios):
    nuevo = dict(data)
    nuevo['demandas'] = dict(data['demandas'])
    nuevo.update(cambios)
    K = nuevo['capacidad_horas']
    nuevo['M_wb'] = K / nuevo['t_wb']
    nuevo['M_wbl'] = K / nuevo['t_wbl']
    nuevo['M_wl'] = K / nuevo['t_wl']
    return nuevo


def datos_con_cv(data, cv):
    nuevo = clonar_datos(data)
    for prod in obtener_productos(data):
        for t in set(data['periodos_nodo'].values()):
            mu, sigma = media_y_desviacion(data, prod, t)
            if sigma == 0:
                continue
            k = cv * mu / sigma
            for n in nodos_del_periodo(data, t):
                d = data['demandas'][(*prod, n)]
                nuevo['demandas'][(*prod, n)] = max(0.0, mu + k * (d - mu))
    return nuevo


def _estandarizar(data, valores):
    prob = data['probabilidades']
    mu = sum(prob[n] * x for n, x in valores.items())
    sd = math.sqrt(sum(prob[n] * (x - mu) ** 2 for n, x in valores.items()))
    return {n: (x - mu) / sd for n, x in valores.items()}


def datos_con_correlacion(data, tipo):
    nuevo = clonar_datos(data)
    productos = obtener_productos(data)
    prob = data['probabilidades']

    for t in set(data['periodos_nodo'].values()):
        ns = nodos_del_periodo(data, t)
        if len(ns) <= 1:
            continue
        total = {n: sum(data['demandas'][(i, j, n)] for i, j in productos) for n in ns}
        z_a = _estandarizar(data, total)
        u = {n: z_a[n] ** 2 for n in ns}
        proj = sum(prob[n] * u[n] * z_a[n] for n in ns)
        z_b = _estandarizar(data, {n: u[n] - proj * z_a[n] for n in ns})

        for i in data['vinos']:
            etiq = data['etiquetas_por_vino'][i]
            for k, j in enumerate(etiq):
                ang = 0.0 if tipo == "positiva" else 2.0 * math.pi * k / len(etiq)
                mu, sigma = media_y_desviacion(data, (i, j), t)
                for n in ns:
                    z = math.cos(ang) * z_a[n] + math.sin(ang) * z_b[n]
                    nuevo['demandas'][(i, j, n)] = max(0.0, mu + sigma * z)
    return nuevo


# =============================================================================
# 2. POLÍTICAS EXTERNAS (NO TOCAN src/policies.py NI src/core_model.py)
# =============================================================================

def politica_hibrida_mts_mto(model, vars_dict, data):
    """Caso Base Híbrido Realista: cada SKU elige MTS o MTO sin stock (sin postergación)."""
    w_b, w_l = vars_dict['w_b'], vars_dict['w_l']
    s_b, s_bl = vars_dict['s_b'], vars_dict['s_bl']
    nodos = data['nodos']
    nodos_ext = [0] + nodos
    productos = obtener_productos(data)

    for i in data['vinos']:
        for n in nodos_ext:
            model.addConstr(s_b[i, n] == 0, name=f"HYB_sb_{i}_{n}")
            model.addConstr(w_b[i, n] == 0, name=f"HYB_wb_{i}_{n}")
            for j in data['etiquetas_por_vino'][i]:
                model.addConstr(w_l[i, j, n] == 0, name=f"HYB_wl_{i}_{j}_{n}")

    y_mts = model.addVars(productos, vtype=GRB.BINARY, name="y_mts")
    max_dem = sum(data['demandas'][(i, j, n)] for (i, j) in productos for n in nodos)
    for (i, j) in productos:
        for n in nodos:
            model.addConstr(s_bl[i, j, n] <= max_dem * y_mts[i, j], name=f"HYB_cap_{i}_{j}_{n}")

    vars_dict['y_mts'] = y_mts
    model.update()
    return model


def politica_estatica_twostage(model, vars_dict, data):
    """Modelo Estático Two-Stage (plan fijo por período sin recurso adaptativo)."""
    w_b, z_b = vars_dict['w_b'], vars_dict['z_b']
    w_bl, z_bl = vars_dict['w_bl'], vars_dict['z_bl']
    w_l, z_l = vars_dict['w_l'], vars_dict['z_l']

    por_periodo = {}
    for n in data['nodos']:
        por_periodo.setdefault(data['periodos_nodo'][n], []).append(n)

    for t, ns in por_periodo.items():
        if len(ns) <= 1:
            continue
        n_ref = ns[0]
        for n_otro in ns[1:]:
            for i in data['vinos']:
                model.addConstr(w_b[i, n_otro] == w_b[i, n_ref], name=f"2S_wb_{i}_{t}_{n_otro}")
                model.addConstr(z_b[i, n_otro] == z_b[i, n_ref], name=f"2S_zb_{i}_{t}_{n_otro}")
                for j in data['etiquetas_por_vino'][i]:
                    model.addConstr(w_bl[i, j, n_otro] == w_bl[i, j, n_ref], name=f"2S_wbl_{i}_{j}_{t}_{n_otro}")
                    model.addConstr(z_bl[i, j, n_otro] == z_bl[i, j, n_ref], name=f"2S_zbl_{i}_{j}_{t}_{n_otro}")
                    model.addConstr(w_l[i, j, n_otro] == w_l[i, j, n_ref], name=f"2S_wl_{i}_{j}_{t}_{n_otro}")
                    model.addConstr(z_l[i, j, n_otro] == z_l[i, j, n_ref], name=f"2S_zl_{i}_{j}_{t}_{n_otro}")

    model.update()
    return model


def aplicar_valor_terminal_externo(model, vars_dict, data, rescate_wip=0.0, rescate_fg=0.0, multa_bo=0.0):
    """Añade externamente valor residual de inventario y/o multa de cierre en t=T."""
    ultimo_t = max(data['periodos_nodo'].values())
    nodos_term = nodos_del_periodo(data, ultimo_t)
    prob = data['probabilidades']
    productos = obtener_productos(data)

    obj_actual = model.getObjective()
    ajuste = gp.LinExpr()
    for n in nodos_term:
        p = prob[n]
        ajuste += p * (
            - rescate_wip * gp.quicksum(vars_dict['s_b'][i, n] for i in data['vinos'])
            - rescate_fg * gp.quicksum(vars_dict['s_bl'][i, j, n] for (i, j) in productos)
            + multa_bo * gp.quicksum(vars_dict['b_bl'][i, j, n] for (i, j) in productos)
        )
    model.setObjective(obj_actual + ajuste, GRB.MINIMIZE)
    model.update()
    return model


# =============================================================================
# 3. RESOLVER Y CALCULAR KPIs COMPLETOS
# =============================================================================

def resolver_y_medir(data, politica_fn=None, ajuste_obj_fn=None, time_limit=300):
    with contextlib.redirect_stdout(io.StringIO()):
        m, v = build_base_model(data)
        if politica_fn is not None:
            m = politica_fn(m, v, data)
        if ajuste_obj_fn is not None:
            m = ajuste_obj_fn(m, v, data)

    m.setParam("TimeLimit", time_limit)
    m.optimize()

    if m.SolCount == 0:
        return None, m, v

    vinos, etiq = data['vinos'], data['etiquetas_por_vino']
    productos = obtener_productos(data)
    prob = data['probabilidades']
    periodos_nodo = data['periodos_nodo']
    ultimo_t = max(periodos_nodo.values())
    K = data['capacidad_horas']

    c_setup = c_wip = c_fg = c_bo = 0.0
    vol_wip = vol_fg = vol_bo = 0.0
    dem_t23 = a_tiempo_t23 = post_t23 = 0.0
    horas_esp = 0.0
    util_max = 0.0
    nodo_pico = None
    nodos_saturados = 0
    setups_b = setups_bl = setups_l = 0.0

    dem_sku = {p: 0.0 for p in productos}
    post_sku = {p: 0.0 for p in productos}

    for n in data['nodos']:
        p = prob[n]
        t = periodos_nodo[n]

        sb_n = sum(v['z_b'][i, n].X for i in vinos)
        sbl_n = sum(v['z_bl'][i, j, n].X for i, j in productos)
        sl_n = sum(v['z_l'][i, j, n].X for i, j in productos)

        setups_b += p * sb_n
        setups_bl += p * sbl_n
        setups_l += p * sl_n

        c_setup += p * (data['C_zb'] * sb_n + data['C_zbl'] * sbl_n + data['C_zl'] * sl_n)
        c_wip += p * data['C_sb'] * sum(v['s_b'][i, n].X for i in vinos)
        c_fg += p * data['C_sbl'] * sum(v['s_bl'][i, j, n].X for i, j in productos)
        c_bo += p * data['C_bbl'] * sum(v['b_bl'][i, j, n].X for i, j in productos)

        vol_wip += p * sum(v['s_b'][i, n].X for i in vinos)
        vol_fg += p * sum(v['s_bl'][i, j, n].X for i, j in productos)
        vol_bo += p * sum(v['b_bl'][i, j, n].X for i, j in productos)

        h_n = (
            sum(data['t_wb'] * v['w_b'][i, n].X + data['t_zb'] * v['z_b'][i, n].X for i in vinos)
            + sum(
                data['t_wbl'] * v['w_bl'][i, j, n].X + data['t_zbl'] * v['z_bl'][i, j, n].X
                + data['t_wl'] * v['w_l'][i, j, n].X + data['t_zl'] * v['z_l'][i, j, n].X
                for i, j in productos
            )
        )
        horas_esp += p * h_n
        u_n = h_n / K if K > 0 else 0.0
        if u_n >= util_max:
            util_max = u_n
            nodo_pico = n
        if K - h_n <= 1e-3:
            nodos_saturados += 1

        if t >= 2:
            for (i, j) in productos:
                d = data['demandas'][(i, j, n)]
                wl = v['w_l'][i, j, n].X
                bo = v['b_bl'][i, j, n].X
                dem_t23 += p * d
                a_tiempo_t23 += p * (d - min(d, bo))
                post_t23 += p * wl
                dem_sku[(i, j)] += p * d
                post_sku[(i, j)] += p * wl

    atraso_terminal = sum(
        prob[n] * v['b_bl'][i, j, n].X
        for n in nodos_del_periodo(data, ultimo_t)
        for (i, j) in productos
    )

    kpis = {
        'Costo Total ($)': m.ObjVal,
        'Costo Set-ups ($)': c_setup,
        'Costo WIP ($)': c_wip,
        'Costo FG ($)': c_fg,
        'Costo Atrasos ($)': c_bo,
        'Inv. WIP Esp. (bot-per)': vol_wip,
        'Inv. FG Esp. (bot-per)': vol_fg,
        'Backorder Acum. (bot-per)': vol_bo,
        'Atraso Terminal (bot)': atraso_terminal,
        'Servicio FIFO (%)': 100.0 * a_tiempo_t23 / dem_t23 if dem_t23 > 0 else 100.0,
        'Tasa Postergación Global (%)': 100.0 * post_t23 / dem_t23 if dem_t23 > 0 else 0.0,
        'Horas Esperadas (h)': horas_esp,
        'Utilización Promedio (%)': 100.0 * horas_esp / (ultimo_t * K),
        'Utilización Máxima (%)': 100.0 * util_max,
        'Nodo Pico': nodo_pico,
        'Nodos Saturados (#/11)': nodos_saturados,
        'Set-ups Total (#)': setups_b + setups_bl + setups_l,
        'Set-ups Emb. (#)': setups_b,
        'Set-ups Acop. (#)': setups_bl,
        'Set-ups Etiq. (#)': setups_l,
        'Runtime (s)': m.Runtime,
    }
    for (i, j) in productos:
        kpis[f'Posterg. ({i},{j}) (%)'] = 100.0 * post_sku[(i, j)] / dem_sku[(i, j)] if dem_sku[(i, j)] > 0 else 0.0

    return kpis, m, v


def imprimir_tabla(titulo, df):
    print("\n" + "=" * 100)
    print(f" {titulo}")
    print("=" * 100)
    with pd.option_context('display.max_columns', None, 'display.width', 1000, 'display.float_format', '{:,.2f}'.format):
        print(df.to_string(index=False))


# =============================================================================
# BLOQUE 1: DIAGNÓSTICO DE CAPACIDAD Y SATURACIÓN REAL POR NODO
# =============================================================================

def exp_diagnostico_capacidad(data):
    print("\n[1/6] Diagnóstico de Capacidad y Saturación Real...")
    filas_anexo = []
    for K in [21, 42, 63, 84]:
        dk = clonar_datos(data, capacidad_horas=K)
        k_post, _, _ = resolver_y_medir(dk, None)
        k_mts, _, _ = resolver_y_medir(dk, apply_mts_policy)
        k_mto, _, _ = resolver_y_medir(dk, apply_mto_policy)

        filas_anexo.append({
            'K (h)': K,
            'Costo Post ($)': k_post['Costo Total ($)'],
            'Costo MTS ($)': k_mts['Costo Total ($)'],
            'Costo MTO ($)': k_mto['Costo Total ($)'],
            'Ahorro MTS (%)': 100.0 * (k_mts['Costo Total ($)'] - k_post['Costo Total ($)']) / k_mts['Costo Total ($)'],
            'Serv Post (%)': k_post['Servicio FIFO (%)'],
            'Serv MTS (%)': k_mts['Servicio FIFO (%)'],
            'Atraso Term Post': k_post['Atraso Terminal (bot)'],
            'Atraso Term MTS': k_mts['Atraso Terminal (bot)'],
            'Util Prom Post (%)': k_post['Utilización Promedio (%)'],
            'Util Máx Post (%)': k_post['Utilización Máxima (%)'],
            'Nodo Pico': k_post['Nodo Pico'],
            'Nodos Sat Post': k_post['Nodos Saturados (#/11)'],
            'Nodos Sat MTS': k_mts['Nodos Saturados (#/11)'],
        })

    filas_fino = []
    for K in range(20, 88, 4):
        dk = clonar_datos(data, capacidad_horas=K)
        k_post, _, _ = resolver_y_medir(dk, None)
        k_mts, _, _ = resolver_y_medir(dk, apply_mts_policy)
        filas_fino.append({
            'K (h)': K,
            'Costo_Post': k_post['Costo Total ($)'],
            'Costo_MTS': k_mts['Costo Total ($)'],
            'Ahorro_MTS_pct': 100.0 * (k_mts['Costo Total ($)'] - k_post['Costo Total ($)']) / k_mts['Costo Total ($)'],
            'Backlog_Post': k_post['Backorder Acum. (bot-per)'],
            'Backlog_MTS': k_mts['Backorder Acum. (bot-per)'],
            'Util_Prom_Post_pct': k_post['Utilización Promedio (%)'],
            'Util_Max_Post_pct': k_post['Utilización Máxima (%)'],
            'Nodos_Sat_Post': k_post['Nodos Saturados (#/11)'],
            'Tasa_Post_pct': k_post['Tasa Postergación Global (%)'],
        })

    df_anexo = pd.DataFrame(filas_anexo)
    df_fino = pd.DataFrame(filas_fino)
    imprimir_tabla("1A. DIAGNÓSTICO DE CAPACIDAD Y SATURACIÓN POR NODO (NIVELES ANEXO A)", df_anexo)
    imprimir_tabla("1B. BARRIDO FINO DE CAPACIDAD (CADA 4 HORAS)", df_fino)

    with pd.ExcelWriter("out_1_capacidad_y_saturacion.xlsx") as xl:
        df_anexo.to_excel(xl, sheet_name="Niveles_Anexo_A", index=False)
        df_fino.to_excel(xl, sheet_name="Barrido_Fino_4h", index=False)


# =============================================================================
# BLOQUE 2: FACTORIAL COMPLETO (CAPACIDAD x CV x CORRELACIÓN INTRA-PERÍODO)
# =============================================================================

def exp_factorial_completo(data):
    print("\n[2/6] Factorial Completo 3x3x3 (Capacidad x CV x Correlación intra-período)...")
    corr_rows = []
    pares = [((1, 1), (1, 2)), ((1, 1), (1, 3)), ((1, 2), (1, 3)), ((2, 1), (2, 2))]
    for tipo_corr, d_base in [
        ("Original", data),
        ("Positiva", datos_con_correlacion(data, "positiva")),
        ("Negativa", datos_con_correlacion(data, "negativa")),
    ]:
        for t in [2, 3]:
            for p1, p2 in pares:
                corr_rows.append({
                    'Estructura': tipo_corr,
                    'Período': t,
                    'Par': f"{p1} vs {p2}",
                    'Corr_Intra_Periodo': correlacion_intra_periodo(d_base, p1, p2, t),
                })

    filas = []
    for K in [42, 63, 84]:
        for tipo_corr in ["Original", "Positiva", "Negativa"]:
            d_corr = data if tipo_corr == "Original" else datos_con_correlacion(data, tipo_corr.lower())
            for cv in [0.10, 0.30, 0.50]:
                d_scen = clonar_datos(datos_con_cv(d_corr, cv), capacidad_horas=K)
                k_post, _, _ = resolver_y_medir(d_scen, None)
                k_mts, _, _ = resolver_y_medir(d_scen, apply_mts_policy)

                filas.append({
                    'K (h)': K,
                    'Correlación': tipo_corr,
                    'CV (%)': int(cv * 100),
                    'Costo Post ($)': k_post['Costo Total ($)'],
                    'Costo MTS ($)': k_mts['Costo Total ($)'],
                    'Ahorro MTS (%)': 100.0 * (k_mts['Costo Total ($)'] - k_post['Costo Total ($)']) / k_mts['Costo Total ($)'],
                    'WIP Post': k_post['Inv. WIP Esp. (bot-per)'],
                    'FG Post': k_post['Inv. FG Esp. (bot-per)'],
                    'FG MTS': k_mts['Inv. FG Esp. (bot-per)'],
                    'BO Post': k_post['Backorder Acum. (bot-per)'],
                    'BO MTS': k_mts['Backorder Acum. (bot-per)'],
                    'Util Máx (%)': k_post['Utilización Máxima (%)'],
                    'Tasa Post (%)': k_post['Tasa Postergación Global (%)'],
                })

    df_fact = pd.DataFrame(filas)
    df_corr = pd.DataFrame(corr_rows)
    imprimir_tabla("2A. VERIFICACIÓN DE CORRELACIONES INTRA-PERÍODO", df_corr)
    imprimir_tabla("2B. FACTORIAL COMPLETO (CAPACIDAD x CORRELACIÓN x CV)", df_fact)

    with pd.ExcelWriter("out_2_factorial_K_CV_Corr.xlsx") as xl:
        df_fact.to_excel(xl, sheet_name="Factorial_27_Escenarios", index=False)
        df_corr.to_excel(xl, sheet_name="Verificacion_Correlaciones", index=False)


# =============================================================================
# BLOQUE 3: POSTERGACIÓN PARCIAL EN K=84h, 63h y 42h + TASA POR ETIQUETA
# =============================================================================

def exp_etiquetas_por_capacidad(data):
    print("\n[3/6] Postergación Parcial (PL=0,2,3,4,5) en K=84h, 63h y 42h + Tasa por SKU...")
    opciones_por_vino = []
    for i in data['vinos']:
        prods = [(i, j) for j in data['etiquetas_por_vino'][i]]
        ops = [()] + [c for r in range(2, len(prods) + 1) for c in itertools.combinations(prods, r)]
        opciones_por_vino.append(ops)
    combos = [sum(c, ()) for c in itertools.product(*opciones_por_vino)]
    productos = obtener_productos(data)

    filas = []
    for K in [84, 63, 42]:
        dk = clonar_datos(data, capacidad_horas=K)
        k_mts, _, _ = resolver_y_medir(dk, apply_mts_policy)
        costo_mts = k_mts['Costo Total ($)']

        for perm in combos:
            def restr_perm(m, v, d):
                for (i, j) in productos:
                    if (i, j) not in perm:
                        for n in d['nodos']:
                            m.addConstr(v['w_l'][i, j, n] == 0)
                m.update()
                return m

            kp, _, _ = resolver_y_medir(dk, restr_perm)
            fila = {
                'K (h)': K,
                'PL': len(perm),
                'Combinación': ", ".join(f"({i},{j})" for i, j in perm) or "Ninguna (MTS)",
                'Costo ($)': kp['Costo Total ($)'],
                'Ahorro MTS (%)': 100.0 * (costo_mts - kp['Costo Total ($)']) / costo_mts,
                'Util Máx (%)': kp['Utilización Máxima (%)'],
                'BO Acum': kp['Backorder Acum. (bot-per)'],
            }
            for (i, j) in productos:
                fila[f'Post ({i},{j}) %'] = kp[f'Posterg. ({i},{j}) (%)']
            filas.append(fila)

    df = pd.DataFrame(filas).sort_values(['K (h)', 'PL', 'Costo ($)'])
    mejores = df.groupby(['K (h)', 'PL'], as_index=False).first()
    imprimir_tabla("3. MEJOR SELECCIÓN DE ETIQUETAS POR CAPACIDAD Y TASA DE POSTERGACIÓN POR SKU", mejores)

    with pd.ExcelWriter("out_3_etiquetas_y_tasa_sku.xlsx") as xl:
        mejores.to_excel(xl, sheet_name="Mejores_por_K_y_PL", index=False)
        df.to_excel(xl, sheet_name="Todas_Combinaciones", index=False)


# =============================================================================
# BLOQUE 4: BENCHMARKS AVANZADOS (HÍBRIDO REALISTA MTS+MTO Y VMS TWO-STAGE)
# =============================================================================

def exp_benchmarks_avanzados(data):
    print("\n[4/6] Benchmarks Avanzados (Caso Base Híbrido MTS+MTO y Valor Multietapa VMS)...")
    filas = []
    for K in [42, 63, 84]:
        dk = clonar_datos(data, capacidad_horas=K)
        k_post, _, _ = resolver_y_medir(dk, None)
        k_mts, _, _ = resolver_y_medir(dk, apply_mts_policy)
        k_mto, _, _ = resolver_y_medir(dk, apply_mto_policy)
        k_hyb, m_hyb, v_hyb = resolver_y_medir(dk, politica_hibrida_mts_mto)
        k_2s, m_2s, _ = resolver_y_medir(dk, politica_estatica_twostage)

        skus_mts = (
            [f"({i},{j})" for (i, j), var in v_hyb['y_mts'].items() if var.X > 0.5]
            if k_hyb is not None else ["Infactible"]
        )

        for nombre, kp in [
            ("Postergación Multietapa", k_post),
            ("Híbrido Realista (MTS+MTO)", k_hyb),
            ("MTS Puro", k_mts),
            ("MTO Sin Stock", k_mto),
            ("Postergación Estática (Two-Stage)", k_2s),
        ]:
            if kp is None:
                filas.append({
                    'K (h)': K,
                    'Política': nombre,
                    'Costo Total ($)': None,
                    'Ahorro Post vs Pol (%)': None,
                    'Serv FIFO (%)': None,
                    'Atraso Term (bot)': None,
                    'Util Máx (%)': None,
                    'Detalle': "INFACTIBLE (capacidad insuficiente sin recurso/stock)",
                })
            else:
                filas.append({
                    'K (h)': K,
                    'Política': nombre,
                    'Costo Total ($)': kp['Costo Total ($)'],
                    'Ahorro Post vs Pol (%)': 100.0 * (kp['Costo Total ($)'] - k_post['Costo Total ($)']) / kp['Costo Total ($)'],
                    'Serv FIFO (%)': kp['Servicio FIFO (%)'],
                    'Atraso Term (bot)': kp['Atraso Terminal (bot)'],
                    'Util Máx (%)': kp['Utilización Máxima (%)'],
                    'Detalle': f"MTS: {', '.join(skus_mts) or 'Ninguno'}" if "Híbrido" in nombre else "-",
                })

    df_bench = pd.DataFrame(filas)
    imprimir_tabla("4. BENCHMARKS AVANZADOS: HÍBRIDO REALISTA (MTS+MTO) Y VALOR MULTIETAPA (VMS)", df_bench)
    df_bench.to_excel("out_4_benchmarks_hibrido_vms.xlsx", index=False)


# =============================================================================
# BLOQUE 5: ANÁLISIS HIPOTÉTICOS (COSTOS, DOBLE MANEJO Y VALOR TERMINAL t=3)
# =============================================================================

def exp_whatif_costos_y_borde(data):
    print("\n[5/6] Análisis Hipotéticos (C_bbl, C_sb=15, Doble Manejo y Valor Terminal)...")
    filas = []

    def registrar(grupo, escenario, d_mod, ajuste_obj_fn=None):
        kp, _, _ = resolver_y_medir(d_mod, None, ajuste_obj_fn=ajuste_obj_fn)
        km, _, _ = resolver_y_medir(d_mod, apply_mts_policy, ajuste_obj_fn=ajuste_obj_fn)
        filas.append({
            'Dimensión': grupo,
            'Escenario': escenario,
            'Costo Post ($)': kp['Costo Total ($)'],
            'Costo MTS ($)': km['Costo Total ($)'],
            'Ahorro MTS (%)': 100.0 * (km['Costo Total ($)'] - kp['Costo Total ($)']) / km['Costo Total ($)'],
            'Serv Post (%)': kp['Servicio FIFO (%)'],
            'Serv MTS (%)': km['Servicio FIFO (%)'],
            'WIP Post': kp['Inv. WIP Esp. (bot-per)'],
            'FG Post': kp['Inv. FG Esp. (bot-per)'],
            'FG MTS': km['Inv. FG Esp. (bot-per)'],
            'Tasa Post (%)': kp['Tasa Postergación Global (%)'],
            'Util Máx (%)': kp['Utilización Máxima (%)'],
        })

    # 5A. Penalización por Backorder (C_bbl)
    for cbbl in [150, 750, 1500, 3000, 15000]:
        registrar("1. Multa Backorder", f"C_bbl = ${cbbl:,} ({cbbl//15}x FG)", clonar_datos(data, C_bbl=float(cbbl)))

    # 5B. Diferencial de Bodega (C_sb = 15 aísla 100% el efecto Risk Pooling puro)
    for csb in [5.0, 10.0, 12.5, 15.0]:
        registrar("2. Bodega WIP (C_sb)", f"C_sb = ${csb:.1f} (Dif ${15-csb:.1f})", clonar_datos(data, C_sb=csb))

    # 5C. Fricción Doble Manipulación (Set-up de etiquetado t_zl y C_zl)
    for mult in [1, 2, 4, 6]:
        registrar(
            "3. Doble Manejo",
            f"{mult}x Etiq (t_zl={0.5*mult:.1f}h, C_zl=${500*mult:,})",
            clonar_datos(data, t_zl=0.5 * mult, C_zl=500.0 * mult),
        )

    # 5D. Efecto de Borde / Valor Residual Terminal en t=3 (externo al modelo base)
    registrar("4. Efecto Borde t=3", "Sin valor terminal (Base)", data, ajuste_obj_fn=None)
    registrar(
        "4. Efecto Borde t=3",
        "Rescate stock 50% (WIP=$5, FG=$7.5)",
        data,
        ajuste_obj_fn=lambda m, v, d: aplicar_valor_terminal_externo(m, v, d, rescate_wip=5.0, rescate_fg=7.5, multa_bo=0.0),
    )
    registrar(
        "4. Efecto Borde t=3",
        "Rescate stock + Multa cierre BO ($30k)",
        data,
        ajuste_obj_fn=lambda m, v, d: aplicar_valor_terminal_externo(m, v, d, rescate_wip=5.0, rescate_fg=7.5, multa_bo=30000.0),
    )

    df_wi = pd.DataFrame(filas)
    imprimir_tabla("5. ANÁLISIS HIPOTÉTICOS (COSTOS, DOBLE MANEJO Y VALOR TERMINAL)", df_wi)
    df_wi.to_excel("out_5_whatif_costos_y_borde.xlsx", index=False)


# =============================================================================
# BLOQUE 6: SIMULACIÓN DE ESCALAMIENTO COMPUTACIONAL (PARA PILOTO)
# =============================================================================

def generar_instancia_sintetica(data_base, T_periodos, n_vinos, etiq_por_vino, seed=42):
    rng = random.Random(seed)
    vinos = list(range(1, n_vinos + 1))
    etiquetas = {i: list(range(1, etiq_por_vino + 1)) for i in vinos}
    productos = [(i, j) for i in vinos for j in etiquetas[i]]

    nodos, antecesores, probabilidades, periodos_nodo = [], {}, {}, {}
    nodo_id = 1
    nivel_anterior = [(0, 1.0)]
    for t in range(1, T_periodos + 1):
        nivel_actual = []
        ramas = [1.0] if t == 1 else [0.3, 0.4, 0.3]
        for ant_id, p_ant in nivel_anterior:
            for p_rama in ramas:
                nodos.append(nodo_id)
                antecesores[nodo_id] = ant_id
                probabilidades[nodo_id] = p_ant * p_rama
                periodos_nodo[nodo_id] = t
                nivel_actual.append((nodo_id, p_ant * p_rama))
                nodo_id += 1
        nivel_anterior = nivel_actual

    factor_escala = len(productos) / 5.0
    demandas = {}
    for (i, j) in productos:
        base_mu = 20000.0 + rng.uniform(-2500, 2500)
        for n in nodos:
            t = periodos_nodo[n]
            mult = 1.0 if t == 1 else rng.choice([0.65, 1.0, 1.40])
            demandas[(i, j, n)] = base_mu * mult

    return clonar_datos(
        data_base,
        vinos=vinos,
        etiquetas_por_vino=etiquetas,
        nodos=nodos,
        antecesores=antecesores,
        probabilidades=probabilidades,
        periodos_nodo=periodos_nodo,
        demandas=demandas,
        capacidad_horas=data_base['capacidad_horas'] * factor_escala,
    )


def exp_escalamiento_computacional(data):
    print("\n[6/6] Simulación de Escalamiento Computacional (T períodos x |P| productos)...")
    configs = [
        (3, 2, 3),   # T=3 (13 nodos), 6 productos
        (3, 3, 3),   # T=3 (13 nodos), 9 productos
        (3, 4, 3),   # T=3 (13 nodos), 12 productos
        (3, 4, 4),   # T=3 (13 nodos), 16 productos
        (4, 2, 3),   # T=4 (40 nodos), 6 productos
        (4, 3, 3),   # T=4 (40 nodos), 9 productos
        (4, 4, 3),   # T=4 (40 nodos), 12 productos
        (5, 2, 3),   # T=5 (121 nodos), 6 productos
        (5, 3, 3),   # T=5 (121 nodos), 9 productos
    ]
    filas = []
    for T, nv, ne in configs:
        d_sint = generar_instancia_sintetica(data, T, nv, ne)
        t0 = time.perf_counter()
        with contextlib.redirect_stdout(io.StringIO()):
            m, _ = build_base_model(d_sint)
        t_build = time.perf_counter() - t0

        m.setParam("TimeLimit", 120.0)
        m.optimize()

        filas.append({
            'T': T,
            'Vinos': nv,
            'Etiq/Vino': ne,
            '|P|': nv * ne,
            'Nodos': len(d_sint['nodos']),
            'Vars Totales': m.NumVars,
            'Vars Binarias': m.NumBinVars,
            'Restricciones': m.NumConstrs,
            'Build (s)': t_build,
            'Solver Gurobi (s)': m.Runtime,
            'MIPGap (%)': 100.0 * m.MIPGap if m.SolCount > 0 else None,
            'Estado': "Óptimo" if m.Status == GRB.OPTIMAL else f"Límite/Otro ({m.Status})",
        })

    df_comp = pd.DataFrame(filas)
    imprimir_tabla("6. ESCALAMIENTO COMPUTACIONAL (PARA JUSTIFICACIÓN DE PILOTO)", df_comp)
    df_comp.to_excel("out_6_escalamiento_computacional.xlsx", index=False)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    with contextlib.redirect_stdout(io.StringIO()):
        data = load_data(os.path.join(base_dir, "data", "P12 Anexo A Datos.xlsx"))

    modo = sys.argv[1] if len(sys.argv) > 1 else "todos"
    if modo in ("capacidad", "todos"):
        exp_diagnostico_capacidad(data)
    if modo in ("factorial", "todos"):
        exp_factorial_completo(data)
    if modo in ("etiquetas", "todos"):
        exp_etiquetas_por_capacidad(data)
    if modo in ("benchmarks", "todos"):
        exp_benchmarks_avanzados(data)
    if modo in ("whatif", "todos"):
        exp_whatif_costos_y_borde(data)
    if modo in ("computo", "todos"):
        exp_escalamiento_computacional(data)