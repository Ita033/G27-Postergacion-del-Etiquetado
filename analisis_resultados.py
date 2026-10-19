"""
analisis_resultados.py

Análisis de resultados del modelo. Ver la sección "Análisis de resultados" del README.

Resuelve el modelo base (core_model.py) y las políticas, y guarda tablas CSV con el detalle
de los resultados que se usan en la presentación de la entrega 2. No cambia la formulación
ni los datos originales: cada experimento trabaja sobre una copia de `data`.

El análisis está dividido en bloques que se pueden correr por separado:
  base       -> compara las políticas, costo por camino, estadísticas de la demanda (CV y
                correlaciones) y detalle por nodo y período
  capacidad  -> las políticas con 21, 42, 63 y 84 horas por período

La versión completa (selección de etiquetas, costos de inventario, límite de bodega y diseño
factorial de variabilidad x correlación) quedó respaldada en la rama `respaldo-analisis-completo`.

Se corre desde la raíz del repo:
  python analisis_resultados.py                                   (los dos bloques, unos segundos)
  python analisis_resultados.py --bloques base capacidad
  python analisis_resultados.py --salida otra/carpeta --limite-segundos 120
"""
import os
import io
import json
import copy
import argparse
import contextlib
from itertools import combinations

import numpy as np
import pandas as pd
import gurobipy as gp
from gurobipy import GRB

from src.core_model import build_base_model
from src.data_loader import load_data
from src.policies import apply_mto_policy, apply_mts_policy

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Mismos nombres que en main.py. Postergación va primero porque es contra la que se compara.
POLITICAS = {
    "Postergación": None,
    "Contra Stock (MTS)": apply_mts_policy,
    "Contra Pedido (MTO)": apply_mto_policy,
}

# Variable -> parámetro de costo (por unidad) y variable -> parámetro de tiempo (horas por unidad)
COSTOS = {"z_b": "C_zb", "z_bl": "C_zbl", "z_l": "C_zl",
          "s_b": "C_sb", "s_bl": "C_sbl", "b_bl": "C_bbl"}
TIEMPOS = {"w_b": "t_wb", "w_bl": "t_wbl", "w_l": "t_wl",
           "z_b": "t_zb", "z_bl": "t_zbl", "z_l": "t_zl"}

# Parámetros de Gurobi fijos para que cada corrida dé siempre lo mismo
MIP_GAP = 1e-8
SEMILLA = 27
HILOS = 1


# -----------------------------------------------------------------------------
# Árbol y datos
# -----------------------------------------------------------------------------
def productos(data):
    """Los pares (vino, etiqueta): (1,1), (1,2), (1,3), (2,1), (2,2)."""
    return [(i, j) for i in data['vinos'] for j in data['etiquetas_por_vino'][i]]


def nodos_por_periodo(data):
    """{período: [nodos de ese período]}"""
    return {t: [n for n in data['nodos'] if data['periodos_nodo'][n] == t]
            for t in sorted(set(data['periodos_nodo'].values()))}


def hojas(data):
    """Nodos del último período (los que no son padre de nadie)."""
    return [n for n in data['nodos'] if n not in data['antecesores'].values()]


def validar_datos(data):
    """Revisa que el árbol y las demandas tengan sentido antes de resolver."""
    # Las probabilidades de cada período suman 1
    for t, ns in nodos_por_periodo(data).items():
        if not np.isclose(sum(data['probabilidades'][n] for n in ns), 1):
            raise ValueError(f"Probabilidades incondicionales no suman 1 en período {t}")

    for n in data['nodos']:
        if data['probabilidades'][n] <= 0:
            raise ValueError("Probabilidades deben ser positivas")
        # Los hijos de un nodo suman la probabilidad del padre
        h = [k for k in data['nodos'] if data['antecesores'][k] == n]
        if h and not np.isclose(sum(data['probabilidades'][k] for k in h), data['probabilidades'][n]):
            raise ValueError(f"Probabilidades inconsistentes en hijos de {n}")
        # Cada arco avanza exactamente un período
        padre = data['antecesores'][n]
        if padre and data['periodos_nodo'][padre] + 1 != data['periodos_nodo'][n]:
            raise ValueError("El árbol debe avanzar un período por arco")

    # Hay una demanda finita y no negativa para cada producto y nodo
    esperadas = {(*p, n) for p in productos(data) for n in data['nodos']}
    if set(data['demandas']) != esperadas or any(
            not np.isfinite(x) or x < 0 for x in data['demandas'].values()):
        raise ValueError("Demandas incompletas, negativas o no finitas")


# -----------------------------------------------------------------------------
# Demanda
# -----------------------------------------------------------------------------
def momentos(valores, pesos):
    """Media, desviación estándar y coeficiente de variación, ponderados por `pesos`."""
    p = np.asarray(pesos, dtype=float)
    p /= p.sum()
    x = np.asarray(valores, dtype=float)
    media = float(p @ x)
    sd = float(np.sqrt(p @ (x - media)**2))
    return media, sd, sd / media if media > 0 else np.nan


def estadisticas_demanda(data):
    """
    Por período y vino: media, sd y CV de cada etiqueta (y del total del vino), y la
    correlación entre cada par de etiquetas del mismo vino. Se pondera por la
    probabilidad de los nodos de ese período.
    """
    filas, correlaciones = [], []
    for t, ns in nodos_por_periodo(data).items():
        p = np.array([data['probabilidades'][n] for n in ns])
        for i in data['vinos']:
            etiquetas = data['etiquetas_por_vino'][i]
            xs = {j: np.array([data['demandas'][i, j, n] for n in ns]) for j in etiquetas}
            total = sum(xs.values())
            for j, x in list(xs.items()) + [("TOTAL", total)]:
                media, sd, cv = momentos(x, p)
                filas.append(dict(periodo=t, vino=i, etiqueta=j, media=media, sd=sd, cv=cv))
            for a, b in combinations(etiquetas, 2):
                ma, sa, _ = momentos(xs[a], p)
                mb, sb, _ = momentos(xs[b], p)
                cov = float(p @ ((xs[a] - ma) * (xs[b] - mb)))
                correlaciones.append(dict(periodo=t, vino=i, etiqueta_a=a, etiqueta_b=b, covarianza=cov,
                                          correlacion=cov / (sa * sb) if sa * sb > 1e-12 else np.nan))
    return filas, correlaciones


# -----------------------------------------------------------------------------
# Modelo
# -----------------------------------------------------------------------------
def resolver(data, politica="Postergación", limite_tiempo=60):
    """
    Arma el modelo base, le aplica la política, lo resuelve y devuelve un diccionario con
    el estado, el costo, los KPIs y los valores de las variables.
    """
    validar_datos(data)
    d = copy.deepcopy(data)
    # Big-M según la capacidad del experimento, para que las de 84 h no limiten si se sube la capacidad
    for op in ("wb", "wbl", "wl"):
        d['M_' + op] = d['capacidad_horas'] / d['t_' + op]

    # build_base_model y las políticas imprimen cosas, las escondemos
    with contextlib.redirect_stdout(io.StringIO()):
        model, v = build_base_model(d)
        if POLITICAS[politica]:
            POLITICAS[politica](model, v, d)

    try:
        # Lo embotellado en las hojas llegaría después del horizonte, así que no se permite
        for n in hojas(d):
            for i in d['vinos']:
                v['w_b'][i, n].UB = v['z_b'][i, n].UB = 0
            for i, j in productos(d):
                v['w_bl'][i, j, n].UB = v['z_bl'][i, j, n].UB = 0

        model.Params.TimeLimit = limite_tiempo
        model.Params.MIPGap = MIP_GAP
        model.Params.Seed = SEMILLA
        model.Params.Threads = HILOS
        model.optimize()

        resultado = dict(politica=politica, estado=int(model.Status), solucion=bool(model.SolCount),
                         optimo=model.Status == GRB.OPTIMAL, tiempo_s=model.Runtime,
                         costo=np.nan, cota=np.nan, gap=np.nan)
        if model.SolCount:
            resultado.update(costo=model.ObjVal, cota=model.ObjBound, gap=model.MIPGap)
            valores = {nombre: {k: float(var.X) for k, var in grupo.items()} for nombre, grupo in v.items()}
            resultado['valores'] = valores
            resultado.update(resumir(valores, d))

            # Chequeos: el desglose de costos tiene que dar el objetivo y no se puede pasar de la capacidad
            if not np.isclose(resultado['costo'], sum(resultado['costo_' + k] for k in COSTOS), rtol=1e-8, atol=.01):
                raise AssertionError("El desglose no reconstruye el objetivo")
            if resultado['holgura_min_h'] < -1e-5:
                raise AssertionError("Capacidad de línea excedida")
        return resultado
    finally:
        model.dispose()


# -----------------------------------------------------------------------------
# KPIs
# -----------------------------------------------------------------------------
def metricas_nodo(v, d, n):
    """Totales del nodo n (sumando vinos y etiquetas): cantidades, costos, horas, holguras y servicio."""
    def total(nombre):
        return sum(x for k, x in v[nombre].items() if k[-1] == n)

    fila = dict(nodo=n, periodo=d['periodos_nodo'][n], probabilidad=d['probabilidades'][n],
                demanda=sum(d['demandas'][i, j, n] for i, j in productos(d)))
    fila.update({nombre: total(nombre) for nombre in v})
    fila.update({"costo_" + nombre: total(nombre) * d[param] for nombre, param in COSTOS.items()})
    fila['costo'] = sum(fila['costo_' + nombre] for nombre in COSTOS)

    # Horas usadas en la línea: producción (w) y set-ups (z)
    fila['horas_proceso'] = sum(total(nombre) * d[param] for nombre, param in TIEMPOS.items() if nombre.startswith("w"))
    fila['horas_setup'] = sum(total(nombre) * d[param] for nombre, param in TIEMPOS.items() if nombre.startswith("z"))
    fila['horas'] = fila['horas_proceso'] + fila['horas_setup']
    fila['holgura_h'] = d['capacidad_horas'] - fila['horas']
    fila['utilizacion_pct'] = 100 * fila['horas'] / d['capacidad_horas']
    fila['holgura_estanques_bot'] = d['q_tanque_botellas'] * d['estanques_disp'] - fila['w_b'] - fila['w_bl']

    # Botellas físicamente en bodega al cierre (incluye lo embotellado que se usa en el período siguiente)
    fila['wip_fisico_cierre'] = fila['s_b'] + fila['w_b']
    fila['fg_fisico_cierre'] = fila['s_bl'] + fila['w_bl']

    # Demanda cubierta a tiempo, suponiendo que primero se entregan los atrasos antiguos (FIFO).
    # Los balances del modelo no dicen a qué pedido va cada botella, así que es un supuesto.
    ant = d['antecesores'][n]
    fila['atendido_tiempo_fifo'] = sum(max(0., d['demandas'][i, j, n] - v['b_bl'][i, j, n])
                                       for i, j in productos(d))
    fila['despachos'] = sum(d['demandas'][i, j, n] + v['b_bl'][i, j, ant] - v['b_bl'][i, j, n]
                            for i, j in productos(d))
    return fila


def resumir(v, d):
    """KPIs esperados de una solución (cada nodo ponderado por su probabilidad)."""
    filas = [metricas_nodo(v, d, n) for n in d['nodos']]

    def esperado(clave):
        return sum(r['probabilidad'] * r[clave] for r in filas)

    kpis = {"costo_" + k: esperado("costo_" + k) for k in COSTOS}
    n_periodos = len(nodos_por_periodo(d))
    kpis.update(
        backorder_bot_periodo=esperado('b_bl'), wip_bot_periodo=esperado('s_b'), fg_bot_periodo=esperado('s_bl'),
        wip_promedio_bot=esperado('s_b') / n_periodos, fg_promedio_bot=esperado('s_bl') / n_periodos,
        bo_terminal_bot=sum(r['probabilidad'] * r['b_bl'] for r in filas if r['nodo'] in hojas(d)),
        horas_esperadas=esperado('horas'), utilizacion_promedio_pct=esperado('utilizacion_pct') / n_periodos,
        holgura_min_h=min(r['holgura_h'] for r in filas),
        wip_max_bot=max(r['s_b'] for r in filas), fg_max_bot=max(r['s_bl'] for r in filas),
        servicio_fifo_pct=100 * esperado('atendido_tiempo_fifo') / esperado('demanda'),
    )
    # % de lo etiquetado que se etiquetó desde el WIP (o sea, postergado)
    wl, wbl = esperado('w_l'), esperado('w_bl')
    kpis['postergado_produccion_pct'] = 100 * wl / (wl + wbl) if wl + wbl else np.nan
    for k in ("z_b", "z_bl", "z_l"):
        kpis['setups_' + k] = esperado(k)
    return kpis


def sin_valores(resultado):
    """El resultado sin los valores de las variables (para guardarlo como fila de una tabla)."""
    return {k: x for k, x in resultado.items() if k != 'valores'}


# -----------------------------------------------------------------------------
# Bloques del análisis
# -----------------------------------------------------------------------------
class Analisis:
    """
    Corre los bloques y guarda las tablas en la carpeta `salida`.
    Guarda cada modelo resuelto en `self.cache`, así si dos bloques piden exactamente el
    mismo modelo se resuelve una sola vez.
    """

    def __init__(self, salida, limite_tiempo):
        self.salida = salida
        os.makedirs(salida, exist_ok=True)
        self.limite_tiempo = limite_tiempo
        self.cache = {}
        self.tablas = {}

    def guardar(self, nombre, filas):
        """Guarda la tabla como CSV con ';' y coma decimal, para abrirla directo en Excel."""
        df = pd.DataFrame(filas)
        df.to_csv(os.path.join(self.salida, nombre + ".csv"), index=False, sep=";", decimal=",", encoding="utf-8-sig")
        self.tablas[nombre] = df
        return df

    def correr(self, d, politica="Postergación", **kwargs):
        clave = repr((d, politica, kwargs))
        if clave not in self.cache:
            self.cache[clave] = resolver(d, politica, limite_tiempo=self.limite_tiempo, **kwargs)
        return self.cache[clave]

    def comparar_politicas(self, d, columnas_extra):
        """Resuelve las 3 políticas con los mismos datos y calcula cuánto ahorra postergar frente a cada una."""
        resultados = [dict(columnas_extra, **sin_valores(self.correr(d, p))) for p in POLITICAS]
        post = resultados[0]
        for r in resultados:
            r['ahorro_post_vs_politica'] = r['costo'] - post['costo']
            r['ahorro_post_pct'] = 100 * (r['costo'] - post['costo']) / r['costo'] if r['costo'] else np.nan
            r['comparacion_optima'] = r['optimo'] and post['optimo']
            # Las otras políticas son el modelo base con más restricciones, no pueden ser más baratas
            if r['comparacion_optima'] and r['costo'] + .1 < post['costo']:
                raise AssertionError("Postergación no puede superar al óptimo de una política restringida")
        return resultados

    def bloque_base(self, d):
        self.guardar("01_politicas", self.comparar_politicas(d, {"horas": d['capacidad_horas']}))
        estadisticas, correlaciones = estadisticas_demanda(d)
        self.guardar("03_demanda_por_periodo", estadisticas)
        self.guardar("03_correlaciones", correlaciones)

        nodos, variables, caminos, caminos_detalle, por_producto = [], [], [], [], []
        for politica in POLITICAS:
            resultado = self.correr(d, politica)
            if not resultado['solucion']:
                continue
            v = resultado['valores']
            for n in d['nodos']:
                nodos.append(dict(politica=politica, **metricas_nodo(v, d, n)))
            for nombre, valores in v.items():
                for k, x in valores.items():
                    variables.append(dict(politica=politica, variable=nombre, vino=k[0],
                                          etiqueta=k[1] if len(k) == 3 else "", nodo=k[-1], valor=x))

            # Costo de cada camino con las MISMAS decisiones del modelo completo (no se re-optimiza;
            # eso lo hace replanificacion.py). Los caminos N1-N2-N5 y N1-N4-N11 se detallan nodo a nodo.
            for hoja in hojas(d):
                ns, n = [], hoja
                while n:
                    ns.append(n)
                    n = d['antecesores'][n]
                ns.reverse()
                filas = [metricas_nodo(v, d, n) for n in ns]
                camino = "-".join(map(str, ns))
                caminos.append(dict(politica=politica, camino=camino, probabilidad=d['probabilidades'][hoja],
                                    destacado=hoja in (5, 11), costo_camino=sum(r['costo'] for r in filas),
                                    demanda_camino=sum(r['demanda'] for r in filas),
                                    bo_bot_periodo=sum(r['b_bl'] for r in filas), bo_final=filas[-1]['b_bl'],
                                    holgura_min_h=min(r['holgura_h'] for r in filas)))
                if hoja in (5, 11):
                    caminos_detalle.extend(dict(politica=politica, camino=camino, **r) for r in filas)

            # Chequeo: los caminos ponderados por probabilidad tienen que dar el costo esperado
            reconstruido = sum(r['probabilidad'] * r['costo_camino'] for r in caminos if r['politica'] == politica)
            if not np.isclose(reconstruido, resultado['costo'], rtol=1e-8, atol=.01):
                raise AssertionError("Los caminos no reconstruyen la esperanza")

        # Cuánto se posterga de cada producto (postergación, para cada nivel de capacidad)
        for horas in d['niveles_capacidad']:
            dd = copy.deepcopy(d)
            dd['capacidad_horas'] = horas
            r = self.correr(dd)
            if not r['solucion']:
                continue
            v = r['valores']
            for i in d['vinos']:
                for j in d['etiquetas_por_vino'][i] + ["TOTAL"]:
                    etiquetas = d['etiquetas_por_vino'][i] if j == "TOTAL" else [j]

                    def cantidad(nombre):
                        return sum(d['probabilidades'][n] * v[nombre][i, jj, n] for jj in etiquetas for n in d['nodos'])

                    wl, wbl = cantidad('w_l'), cantidad('w_bl')
                    # Demanda esperada de los períodos 2 y 3 (la del período 1 viene cubierta)
                    dem = sum(d['probabilidades'][n] * d['demandas'][i, jj, n]
                              for jj in etiquetas for n in d['nodos'] if d['periodos_nodo'][n] > 1)
                    por_producto.append(dict(horas=horas, vino=i, etiqueta=j, etiquetado_wip_bot=wl,
                                             produccion_acoplada_bot=wbl,
                                             postergado_produccion_pct=100 * wl / (wl + wbl) if wl + wbl else np.nan,
                                             wl_sobre_demanda_t2_t3_pct=100 * wl / dem, optimo=r['optimo']))

        self.guardar("02_caminos", caminos)
        self.guardar("02_caminos_destacados_nodos", caminos_detalle)
        self.guardar("03_postergacion_por_producto", por_producto)
        self.guardar("04_nodos", nodos)
        self.guardar("04_variables", variables)

        # Por período se promedian los nodos ponderando por probabilidad (no se suman, porque
        # son escenarios que no pueden ocurrir a la vez)
        tabla = pd.DataFrame(nodos)
        if not tabla.empty:
            columnas = [k for k in nodos[0] if k not in ("politica", "nodo", "periodo", "probabilidad")]
            por_periodo = []
            for (politica, t), grupo in tabla.groupby(["politica", "periodo"]):
                por_periodo.append(dict(politica=politica, periodo=t,
                                        **{k: float((grupo[k] * grupo.probabilidad).sum()) for k in columnas}))
            self.guardar("04_periodos", por_periodo)

    def bloque_capacidad(self, d):
        filas = []
        for horas in d['niveles_capacidad']:
            dd = copy.deepcopy(d)
            dd['capacidad_horas'] = horas
            filas.extend(self.comparar_politicas(dd, dict(horas=horas)))
        self.guardar("06_capacidad", filas)

    def graficos(self):
        """Gráficos de capacidad y de postergación por producto (solo si esos bloques se corrieron)."""
        try:
            import matplotlib
            matplotlib.use("Agg")  # sin ventana, solo guarda los PNG
            import matplotlib.pyplot as plt
        except ImportError:
            print("Sin matplotlib: las tablas sí están disponibles.")
            return

        if "06_capacidad" in self.tablas:
            df = self.tablas["06_capacidad"]
            fig, ejes = plt.subplots(1, 2, figsize=(11, 4))
            for politica, grupo in df.groupby("politica"):
                ejes[0].plot(grupo.horas, grupo.costo, "o-", label=politica)
                ejes[1].plot(grupo.horas, grupo.backorder_bot_periodo, "o-", label=politica)
            ejes[0].set_yscale("log")
            ejes[0].set_ylabel("Costo esperado (u.m., escala log)")
            ejes[1].set_ylabel("Atraso acumulado (botellas·período)")
            for eje in ejes:
                eje.set_xlabel("Capacidad por período (horas)")
                eje.set_xticks([21, 42, 63, 84])
                eje.grid(alpha=.2)
            ejes[0].legend(fontsize=8)
            fig.tight_layout()
            fig.savefig(os.path.join(self.salida, "06_capacidad.png"), dpi=180)
            plt.close(fig)

        if "03_postergacion_por_producto" in self.tablas:
            df = self.tablas["03_postergacion_por_producto"].copy()
            df = df[df.etiqueta != "TOTAL"]
            df['producto'] = df.apply(lambda r: f"({r.vino},{r.etiqueta})", axis=1)
            matriz = df.pivot(index="producto", columns="horas", values="postergado_produccion_pct")
            fig, eje = plt.subplots(figsize=(7, 4))
            im = eje.imshow(matriz.values, vmin=0, vmax=100, cmap="YlGnBu", aspect="auto")
            eje.set_xticks(range(len(matriz.columns)), [f"{h:g} h" for h in matriz.columns])
            eje.set_yticks(range(len(matriz.index)), matriz.index)
            for y in range(len(matriz.index)):
                for x in range(len(matriz.columns)):
                    val = matriz.iloc[y, x]
                    eje.text(x, y, f"{val:.1f}%", ha="center", va="center", color="white" if val > 65 else "black")
            eje.set_title("Postergación por producto y capacidad\n% de producción con etiqueta: etapas 2 y 3")
            fig.colorbar(im, ax=eje, label="%")
            fig.tight_layout()
            fig.savefig(os.path.join(self.salida, "03_postergacion.png"), dpi=180)
            plt.close(fig)


def main(argv=None):
    bloques = ["base", "capacidad"]
    parser = argparse.ArgumentParser(description="Análisis de resultados del modelo de postergación.")
    parser.add_argument("--bloques", nargs="+", choices=bloques, default=bloques)
    parser.add_argument("--salida", default=os.path.join(BASE_DIR, "results", "analisis_validado"))
    parser.add_argument("--limite-segundos", type=float, default=60)
    args = parser.parse_args(argv)
    if args.limite_segundos <= 0:
        parser.error("El límite de tiempo debe ser positivo")

    d = load_data()
    analisis = Analisis(args.salida, args.limite_segundos)
    funciones = {"base": analisis.bloque_base, "capacidad": analisis.bloque_capacidad}
    for bloque in args.bloques:
        print(f"Ejecutando {bloque}...", flush=True)
        funciones[bloque](d)
    analisis.graficos()

    # Cuántos modelos terminaron en cada estado de Gurobi (2 = óptimo, 3 = infactible, 9 = límite de tiempo)
    estados = {}
    for r in analisis.cache.values():
        estados[str(r['estado'])] = estados.get(str(r['estado']), 0) + 1

    # Resumen de la corrida, para saber con qué configuración salieron las tablas
    resumen = dict(bloques=args.bloques, estados=estados, modelos_resueltos=len(analisis.cache),
                   gurobi=gp.gurobi.version(), limite_segundos=args.limite_segundos,
                   mip_gap=MIP_GAP, seed=SEMILLA, threads=HILOS)
    with open(os.path.join(args.salida, "ejecucion.json"), "w", encoding="utf-8") as f:
        json.dump(resumen, f, indent=2)
    print(f"Resultados en {args.salida}; estados Gurobi: {estados}")


if __name__ == "__main__":
    main()
