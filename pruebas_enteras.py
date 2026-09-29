"""
prueba_enteras.py
 
Prueba que salió en la reunión con el profe: en estricto rigor las botellas son
enteras, pero dejarlas enteras puede hacer el modelo más lento. La idea es medir
cuánto cambia el costo y el tiempo si las cantidades (w, s, b) son ENTERAS en vez
de CONTINUAS, para justificar si podemos dejarlas continuas (y redondear después).
 
Para cada política (postergación, contra pedido y contra stock) resolvemos:
  1) el modelo como lo tenemos (cantidades continuas, set-ups binarios)
  2) el mismo modelo pero con w_b, w_bl, w_l, s_b, s_bl, b_bl enteras
y comparamos costo, tiempo de resolución y gap.
 
Se corre desde la raíz del repo:  python prueba_enteras.py
"""
import os
import io
import contextlib
 
import pandas as pd
from gurobipy import GRB
 
from src.data_loader import load_data
from src.core_model import build_base_model
from src.policies import apply_mto_policy, apply_mts_policy
 
# Variables de cantidad (botellas). Las z ya son binarias en core_model, no se tocan.
VARIABLES_CANTIDAD = ['w_b', 'w_bl', 'w_l', 's_b', 's_bl', 'b_bl']
 
# Por si la versión entera se demora mucho, cortamos a los 10 minutos
LIMITE_TIEMPO = 600
 
 
def construir(data, politica):
    """Arma el modelo base y le aplica las restricciones de la política."""
    # build_base_model y las políticas imprimen cosas, las escondemos
    with contextlib.redirect_stdout(io.StringIO()):
        m, v = build_base_model(data)
        if politica == "Contra Pedido (MTO)":
            m = apply_mto_policy(m, v, data)
        elif politica == "Contra Stock (MTS)":
            m = apply_mts_policy(m, v, data)
        # "Postergación" es el modelo base, no se le agrega nada
    return m, v
 
 
def volver_enteras(m, v):
    """Cambia las variables de cantidad de continuas a enteras."""
    for nombre in VARIABLES_CANTIDAD:
        for var in v[nombre].values():
            var.VType = GRB.INTEGER
    m.update()
 
 
def resolver(m):
    """Resuelve y devuelve (costo, tiempo en segundos, gap)."""
    m.setParam('OutputFlag', 0)          # sin el log de Gurobi para que la tabla se lea bien
    m.setParam('TimeLimit', LIMITE_TIEMPO)
    m.optimize()
    if m.SolCount == 0:
        return None, m.Runtime, None
    return m.ObjVal, m.Runtime, m.MIPGap
 
 
def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    with contextlib.redirect_stdout(io.StringIO()):
        data = load_data(os.path.join(base_dir, "data", "P12 Anexo A Datos.xlsx"))
 
    filas = []
    for politica in ["Postergación", "Contra Pedido (MTO)", "Contra Stock (MTS)"]:
        print(f"Resolviendo {politica}...")
 
        # 1) Continuas (como está el modelo ahora)
        m_c, v_c = construir(data, politica)
        costo_c, t_c, _ = resolver(m_c)
 
        # 2) Enteras
        m_e, v_e = construir(data, politica)
        volver_enteras(m_e, v_e)
        costo_e, t_e, gap_e = resolver(m_e)
 
        # Diferencia relativa de costo: cuánto nos equivocamos al dejarlas continuas
        dif = (costo_e - costo_c) / costo_c if (costo_c and costo_e) else None
        filas.append({
            "Política": politica,
            "Costo continuo ($)": costo_c,
            "Costo entero ($)": costo_e,
            "Diferencia (%)": dif * 100 if dif is not None else None,
            "Tiempo continuo (s)": t_c,
            "Tiempo entero (s)": t_e,
            "Gap entero (%)": gap_e * 100 if gap_e is not None else None,
            "Llegó al óptimo (entero)": m_e.Status == GRB.OPTIMAL,
        })
 
    df = pd.DataFrame(filas)
    print("\n" + "=" * 70)
    print(" CONTINUAS vs ENTERAS")
    print("=" * 70)
    with pd.option_context('display.float_format', '{:,.4f}'.format, 'display.width', 200):
        print(df.to_string(index=False))
 
    df.to_csv("resultados_enteras.csv", index=False)
    print("\n(Resultados guardados en 'resultados_enteras.csv')")
    print("Si la diferencia es muy chica y el tiempo sube, conviene dejarlas continuas y redondear.")
 
 
if __name__ == "__main__":
    main()