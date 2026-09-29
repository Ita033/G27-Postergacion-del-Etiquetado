import os
import pandas as pd
from gurobipy import GRB
from src.data_loader import load_data
from src.core_model import build_base_model
from src.policies import apply_mto_policy, apply_mts_policy
import copy 
import numpy as np
from itertools import combinations

os.makedirs("results", exist_ok=True)
pd.options.display.float_format = "{:,.2f}".format


def guardar(df, nombre):
    df.round(2).to_csv(f"results/{nombre}.csv", index=False,
                       sep=";", decimal=",", encoding="utf-8-sig")
    print(f"\n(Guardado en results/{nombre}.csv)")


def titulo(texto):
    print("\n" + "=" * 70)
    print(" " + texto)
    print("=" * 70)


def resolver(data, politica=None):
    model, vars_ = build_base_model(data)
    if politica:
        model = politica(model, vars_, data)
    model.Params.OutputFlag = 0
    model.optimize()
    if model.Status != GRB.OPTIMAL:
        print("  -> Sin solución óptima (status", model.Status, ")")
        return None, None
    return model, vars_


# =====================================================================
# PARTE 1: Costo esperado de las 3 políticas
# =====================================================================
def parte1(data):
    titulo("PARTE 1: COMPARACIÓN DE POLÍTICAS")
    politicas = {"Postergación": None, "MTO": apply_mto_policy, "MTS": apply_mts_policy}
    filas = []
    for nombre, pol in politicas.items():
        model, _ = resolver(data, pol)
        if model:
            filas.append({"Política": nombre, "Costo esperado": model.ObjVal,
                          "Tiempo (s)": model.Runtime})
    df = pd.DataFrame(filas)
    c_post = df.loc[df["Política"] == "Postergación", "Costo esperado"].iloc[0]
    df["Ahorro vs esta política ($)"] = df["Costo esperado"] - c_post
    df["Ahorro (%)"] = 100 * (df["Costo esperado"] - c_post) / df["Costo esperado"]
    print(df.to_string(index=False))
    guardar(df, "parte1_politicas")


# =====================================================================
# PARTE 2: Caminos del árbol 
# =====================================================================
#Camino A: 1 → 2 → 5 (media → alta → alta), probabilidad 0,21
#Camino B: 1 → 4 → 11 (media → baja → baja), probabilidad 0,1

NOMBRES_VINO = {"w_b": "Embotellado sin etiquetar", "s_b": "Inv. sin etiquetar"}
NOMBRES_PROD = {"w_bl": "Acoplado", "w_l": "Etiquetado desde WIP",
                "s_bl": "Inv. terminado", "b_bl": "Backorder"}


def tabla_detalle(vars_):
    """Todas las variables en una tabla larga: nodo, producto, variable, valor."""
    filas = []
    for nombre, v in vars_.items():
        if nombre not in NOMBRES_VINO and nombre not in NOMBRES_PROD:
            continue
        for idx, var in v.items():
            *prod, nodo = idx
            filas.append({
                "Nodo": nodo,
                "Producto": f"Vino {prod[0]}" if len(prod) == 1 else str(tuple(prod)),
                "Variable": NOMBRES_VINO.get(nombre) or NOMBRES_PROD[nombre],
                "Nivel": "vino" if nombre in NOMBRES_VINO else "producto",
                "Valor": round(var.X),
            })
    return pd.DataFrame(filas)


def mostrar_camino(df, nodos, nombre):
    titulo(f"CAMINO {nombre}: nodos {' -> '.join(map(str, nodos))}")
    sub = df[df["Nodo"].isin(nodos)]
    for nivel in ["vino", "producto"]:
        t = sub[sub["Nivel"] == nivel].pivot_table(
            index=["Nodo", "Producto"], columns="Variable",
            values="Valor", aggfunc="sum", fill_value=0)
        t = t[(t != 0).any(axis=1)]          # ocultar filas en cero
        print(f"\n--- A nivel de {nivel} ---")
        print(t.to_string() if not t.empty else "(todo en cero)")
    return sub


def parte2(data):
    titulo("PARTE 2: CAMINOS DEL ÁRBOL (POSTERGACIÓN)")
    model, vars_ = resolver(data)
    df = tabla_detalle(vars_)
    guardar(df, "detalle_postergacion")

    a = mostrar_camino(df, [0, 1, 2, 5], "A (media -> alta -> alta)")
    b = mostrar_camino(df, [0, 1, 4, 11], "B (media -> baja -> baja)")
    guardar(a, "parte2_camino_A")
    guardar(b, "parte2_camino_B")


# =====================================================================
# PARTE 3: Qué productos se postergan y relación con la demanda
# =====================================================================
DEMANDA = {  # Anexo A, nodos 1 a 11
    (1, 1): [23525, 53218, 34328, 18118, 81856, 45302, 50426, 31482, 12538, 30856, 10426],
    (1, 2): [24328, 15184, 28525, 45832, 24546, 31371, 23569, 40767, 57965, 20546, 45569],
    (1, 3): [20368, 38150, 21080, 6762, 4920, 25765, 35043, 25646, 16248, 10920, 11043],
    (2, 1): [21080, 39387, 30368, 12646, 34115, 22773, 37045, 27831, 18616, 24115, 17045],
    (2, 2): [22991, 38048, 27991, 14949, 33440, 22824, 35085, 25147, 15209, 23440, 15085],
}
PROB = {1: 1, 2: .3, 3: .4, 4: .3, 5: .21, 6: .09,
        7: .4/3, 8: .4/3, 9: .4/3, 10: .18, 11: .12}
PERIODOS = {2: [2, 3, 4], 3: [5, 6, 7, 8, 9, 10, 11]}


def cv_ponderado(valores_por_nodo, nodos):
    x = np.array([valores_por_nodo[n - 1] for n in nodos])
    p = np.array([PROB[n] for n in nodos])
    m = np.average(x, weights=p)
    s = np.sqrt(np.average((x - m) ** 2, weights=p))
    return s / m


def estadisticas_demanda():
    filas = []
    for prod, d in DEMANDA.items():
        cv = np.mean([cv_ponderado(d, nodos) for nodos in PERIODOS.values()])
        filas.append({"Producto": str(prod), "CV demanda": cv})
    df = pd.DataFrame(filas)

    print("\n--- Variabilidad del total por vino (lo que 've' la botella sin etiquetar) ---")
    for vino in [1, 2]:
        prods = [p for p in DEMANDA if p[0] == vino]
        total = [sum(DEMANDA[p][k] for p in prods) for k in range(11)]
        cv_total = np.mean([cv_ponderado(total, nodos) for nodos in PERIODOS.values()])
        cv_prom = df[df["Producto"].isin([str(p) for p in prods])]["CV demanda"].mean()
        print(f"Vino {vino}: CV promedio por etiqueta = {cv_prom:.2f} | "
              f"CV del total del vino = {cv_total:.2f}")
    return df


def pct_postergado(vars_):
    filas = []
    for prod in DEMANDA:
        # Etiquetado desde WIP en los nodos 2 a 11 (el nodo 1 viene predefinido)
        wl = sum(PROB[n] * vars_["w_l"][(*prod, n)].X for n in range(2, 12))
        # Producción acoplada decidida en los nodos 1 a 11
        wbl = sum(PROB[n] * vars_["w_bl"][(*prod, n)].X for n in range(1, 12))
        pct = 100 * wl / (wl + wbl) if wl + wbl > 0 else 0
        filas.append({"Producto": str(prod), "% postergado": pct})
    return pd.DataFrame(filas)


def parte3(data):
    titulo("PARTE 3: PRODUCTOS POSTERGADOS VS VARIABILIDAD DE LA DEMANDA")

    # Buscar automáticamente qué clave de 'data' es la capacidad (vale 84)
    clave_cap = next(k for k, v in data.items()
                     if isinstance(v, (int, float)) and not isinstance(v, bool) and v == 84)
    print(f"(Clave de capacidad en data: '{clave_cap}')")

    tabla = estadisticas_demanda()
    for horas in [84, 63, 42, 21]:
        d = copy.deepcopy(data)
        d[clave_cap] = horas
        model, vars_ = resolver(d)
        if model:
            res = pct_postergado(vars_)
            tabla[f"% post. {horas}h"] = res["% postergado"].values
            print(f"  {horas} h resuelto: costo esperado = {model.ObjVal:,.0f}")

    print("\n--- % de cada producto atendido etiquetando desde WIP ---")
    print(tabla.to_string(index=False))
    guardar(tabla, "parte3_postergacion_por_producto")

# =====================================================================
# PARTE 4: Desglose de costos, backorders y holguras
# =====================================================================
COSTOS = {  # variable: (nombre, costo unitario)
    "z_b": ("Set-up embotellado", 1500),
    "z_bl": ("Set-up acoplado", 1500),
    "z_l": ("Set-up etiquetado", 500),
    "s_b": ("Inv. sin etiquetar", 10),
    "s_bl": ("Inv. terminado", 15),
    "b_bl": ("Backorders", 15000),
}
TIEMPOS = {"w_b": 0.00014, "w_bl": 0.00028, "w_l": 0.00028,
           "z_b": 1.5, "z_bl": 1.5, "z_l": 0.5}


def suma_esperada(vars_, nombre, factor=1):
    """Suma P_n * factor * valor sobre los nodos reales (1 a 11)."""
    return sum(PROB[k[-1]] * factor * v.X
               for k, v in vars_[nombre].items() if k[-1] in PROB)


def horas_por_nodo(vars_):
    horas = {n: 0.0 for n in PROB}
    for nombre, t in TIEMPOS.items():
        for k, v in vars_[nombre].items():
            if k[-1] in horas:
                horas[k[-1]] += t * v.X
    return horas


def parte4(data):
    titulo("PARTE 4: DESGLOSE DE COSTOS, BACKORDERS Y HOLGURAS")
    politicas = {"Postergación": None, "MTO": apply_mto_policy, "MTS": apply_mts_policy}
    cap = data["capacidad_horas"]

    costos, backorders, holguras = {}, {}, {}
    for nombre, pol in politicas.items():
        model, vars_ = resolver(data, pol)
        if not model:
            continue
        # 1. Costos
        c = {COSTOS[v][0]: suma_esperada(vars_, v, COSTOS[v][1]) for v in COSTOS}
        c["TOTAL (suma)"] = sum(c.values())
        c["Control: ObjVal Gurobi"] = model.ObjVal
        costos[nombre] = c
        # 2. Backorders esperados por producto
        backorders[nombre] = {
            str(p): sum(PROB[n] * vars_["b_bl"][(*p, n)].X for n in PROB)
            for p in DEMANDA}
        # 3. Holgura por nodo
        horas = horas_por_nodo(vars_)
        holguras[nombre] = {n: cap - h for n, h in horas.items()}

    df_c = pd.DataFrame(costos)
    df_pct = 100 * df_c.drop(["TOTAL (suma)", "Control: ObjVal Gurobi"]) / df_c.loc["TOTAL (suma)"]
    print("\n--- Costo esperado por componente ($) ---")
    print(df_c.to_string())
    print("\n--- Participación de cada componente en el costo (%) ---")
    print(df_pct.to_string())

    df_b = pd.DataFrame(backorders)
    print("\n--- Backorders esperados por producto (botellas) ---")
    print(df_b.to_string())

    df_h = pd.DataFrame(holguras)
    df_h.index.name = "Nodo"
    print(f"\n--- Holgura de la línea por nodo (horas libres de {cap:.0f}) ---")
    print(df_h.to_string())

    guardar(df_c.reset_index(names="Componente"), "parte4_costos")
    guardar(df_b.reset_index(names="Producto"), "parte4_backorders")
    guardar(df_h.reset_index(), "parte4_holguras")


# =====================================================================
# PARTE 5: Postergación limitada a algunos productos
# =====================================================================
VINO1 = [(1, 1), (1, 2), (1, 3)]
VINO2 = [(2, 1), (2, 2)]
OPCIONES_V1 = [[]] + [list(c) for c in combinations(VINO1, 2)] + [VINO1]
OPCIONES_V2 = [[], VINO2]
SUBCONJUNTOS = [a + b for a in OPCIONES_V1 for b in OPCIONES_V2]


def limitar_postergacion(model, vars_, permitidos):
    """Prohíbe etiquetar desde WIP los productos que no están en 'permitidos'."""
    for (i, j, n), var in vars_["w_l"].items():
        if (i, j) not in permitidos and n >= 1:
            var.UB = 0
    model.update()
    return model


def parte5(data):
    titulo("PARTE 5: POSTERGACIÓN LIMITADA A ALGUNOS PRODUCTOS")
    capacidades = [84, 42]
    filas = []
    for perms in SUBCONJUNTOS:
        fila = {"Productos postergados": ", ".join(map(str, perms)) or "Ninguno",
                "N°": len(perms)}
        for horas in capacidades:
            d = copy.deepcopy(data)
            d["capacidad_horas"] = horas
            model, _ = resolver(d, lambda m, v, dd, p=perms: limitar_postergacion(m, v, p))
            fila[f"Costo {horas}h"] = model.ObjVal if model else None
        filas.append(fila)

    df = pd.DataFrame(filas)
    for horas in capacidades:
        sin_post = df.loc[df["N°"] == 0, f"Costo {horas}h"].iloc[0]
        todos = df.loc[df["N°"] == 5, f"Costo {horas}h"].iloc[0]
        # % del ahorro máximo (postergar los 5) que logra cada combinación
        df[f"% del ahorro máx. {horas}h"] = (100 * (sin_post - df[f"Costo {horas}h"])
                                            / (sin_post - todos))
    df = df.sort_values(["N°", "Costo 84h"])

    pd.options.display.float_format = "{:,.0f}".format
    print("\n--- Todas las combinaciones ---")
    print(df.to_string(index=False))

    for horas in capacidades:
        mejores = df.loc[df.groupby("N°")[f"Costo {horas}h"].idxmin(),
                         ["N°", "Productos postergados", f"Costo {horas}h",
                          f"% del ahorro máx. {horas}h"]]
        print(f"\n--- Mejor combinación por cantidad de productos ({horas} h) ---")
        print(mejores.to_string(index=False))

    pd.options.display.float_format = "{:,.2f}".format
    guardar(df, "parte5_postergacion_limitada")
    
# =====================================================================
# ELEGIR QUÉ PARTES CORRER
# =====================================================================
if __name__ == "__main__":
    data = load_data()
    PARTES = [parte5]          # para correr todo: [parte1, parte2, ...]
    for parte in PARTES:
        parte(data)
