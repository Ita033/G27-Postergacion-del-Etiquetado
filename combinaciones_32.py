"""
combinaciones_32.py

Análisis de qué etiquetas conviene postergar (lo que pidió el profe en la entrega 1).

La idea: cada uno de los 5 productos (vino, etiqueta) se puede postergar o no,
así que hay 2^5 = 32 combinaciones posibles. Para cada una resolvemos el mismo
modelo base, pero prohibiendo postergar los productos que no están en la
combinación. Después ordenamos todo por costo esperado.

Ojo: el paper (Varas et al., 2018) hace algo parecido con las restricciones
(26)-(27), pero ahí solo se fija CUÁNTAS etiquetas se pueden postergar y el
modelo elige cuáles. Acá fijamos explícitamente CUÁLES, así tenemos el ranking
completo y también el caso de postergar una sola etiqueta.

Se corre solo desde la raíz del repo:  python combinaciones_32.py
También se llama al final de main.py (función analizar_combinaciones).
"""
import os
import io
import contextlib
import itertools

from gurobipy import GRB
from src.data_loader import load_data
from src.core_model import build_base_model


def resolver_combinacion(data, postergables):
    """Resuelve el modelo base permitiendo postergar solo los productos en `postergables`."""
    vinos = data['vinos']
    etiquetas = data['etiquetas_por_vino']
    nodos_ext = [0] + data['nodos']  # incluimos el nodo 0 artificial igual que en core_model

    # build_base_model imprime cosas, las escondemos para no llenar la consola 32 veces
    with contextlib.redirect_stdout(io.StringIO()):
        m, v = build_base_model(data)

    # 1) Los productos que NO se pueden postergar no pueden etiquetarse desde el WIP,
    #    o sea solo se pueden producir acoplados (w_bl), como en contra stock.
    for i in vinos:
        for j in etiquetas[i]:
            if (i, j) not in postergables:
                for n in nodos_ext:
                    m.addConstr(v['w_l'][i, j, n] == 0, name=f"no_post_{i}_{j}_{n}")

    # 2) Si ninguna etiqueta de un vino se puede postergar, no tiene sentido embotellar
    #    ese vino sin etiqueta. Esto no cambia el óptimo (igual no convendría), pero
    #    deja el modelo más limpio.
    for i in vinos:
        if not any((i, j) in postergables for j in etiquetas[i]):
            for n in nodos_ext:
                m.addConstr(v['w_b'][i, n] == 0, name=f"no_wb_{i}_{n}")
                m.addConstr(v['s_b'][i, n] == 0, name=f"no_sb_{i}_{n}")

    m.optimize()
    if m.status != GRB.OPTIMAL:
        raise RuntimeError(f"La combinación {postergables} no llegó al óptimo (status {m.status})")
    return m.ObjVal


def analizar_combinaciones(data, guardar_csv=True):
    """Resuelve las 32 combinaciones, imprime el ranking y lo devuelve como lista de (costo, combinación).
    La usamos desde main.py y también si se corre este archivo solo."""
    # Los 5 productos: (1,1), (1,2), (1,3), (2,1), (2,2)
    productos = [(i, j) for i in data['vinos'] for j in data['etiquetas_por_vino'][i]]

    resultados = []
    # k = cuántos productos se postergan (0 a 5); combinations nos da todos los grupos de tamaño k
    for k in range(len(productos) + 1):
        for comb in itertools.combinations(productos, k):
            costo = resolver_combinacion(data, set(comb))
            resultados.append((costo, comb))

    resultados.sort()  # de más barato a más caro
    costo_sin_postergar = max(c for c, comb in resultados if len(comb) == 0)  # caso base (contra stock)
    costo_todo = min(c for c, comb in resultados if len(comb) == len(productos))
    ahorro_total = costo_sin_postergar - costo_todo

    print(f"Se resolvieron {len(resultados)} combinaciones\n")
    print(f"{'#':>2} {'Costo esperado':>15} {'Ahorro vs base':>15} {'% del ahorro total':>19}  Productos postergados")
    for costo, comb in resultados:
        ahorro = costo_sin_postergar - costo
        print(f"{len(comb):>2} {costo:>15,.0f} {ahorro / costo_sin_postergar:>15.1%} {ahorro / ahorro_total:>19.1%}  {comb if comb else 'ninguno'}")

    # Resumen: la mejor combinación para cada cantidad de productos postergados
    print("\nMejor combinación según cuántos productos se postergan:")
    for k in range(len(productos) + 1):
        costo, comb = min((c, s) for c, s in resultados if len(s) == k)
        print(f"  {k}: {costo:>12,.0f}  ({1 - costo / costo_sin_postergar:.0%} de ahorro)  {comb if comb else 'ninguno'}")

    # Guardamos la tabla para usarla en el informe, igual que main.py con las políticas
    if guardar_csv:
        with open("resultados_combinaciones.csv", "w", encoding="utf-8") as f:
            f.write("n_postergados,productos_postergados,costo_esperado,ahorro_vs_base,pct_ahorro_total\n")
            for costo, comb in resultados:
                ahorro = costo_sin_postergar - costo
                prods = " ".join(f"({i},{j})" for i, j in comb) if comb else "ninguno"
                f.write(f"{len(comb)},{prods},{costo:.0f},{ahorro / costo_sin_postergar:.4f},{ahorro / ahorro_total:.4f}\n")
        print("\n(Resultados guardados en 'resultados_combinaciones.csv')")

    return resultados


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    with contextlib.redirect_stdout(io.StringIO()):
        data = load_data(os.path.join(base_dir, "data", "P12 Anexo A Datos.xlsx"))
    analizar_combinaciones(data)


if __name__ == "__main__":
    main()
