import os
import pandas as pd
from src.data_loader import load_data
from src.core_model import build_base_model
from src.policies import apply_mto_policy_varas, apply_mts_policy
from src.kpi_calculator import extract_results
from combinaciones_32 import analizar_combinaciones
from src.replanificacion import correr_todos_los_caminos, mostrar_por_camino, comparar_con_modelo_completo

def main():
    # 1. Cargar Datos
    base_dir = os.path.dirname(os.path.abspath(__file__))
    filepath = os.path.join(base_dir, "data", "P12 Anexo A Datos.xlsx")
    
    print("Iniciando ejecución del proyecto Capstone...")
    try:
        data = load_data(filepath)
    except Exception as e:
        print(f"Error crítico al cargar datos: {e}")
        return

    resultados_comparativos = []

    # =========================================================================
    # ESCENARIO 1: POSTERGACIÓN PURA (MODELO BASE)
    # =========================================================================
    print("\n" + "="*70)
    print(" RESOLVIENDO ESCENARIO 1: POSTERGACIÓN (MODELO BASE)")
    print("="*70)
    model_post, vars_post = build_base_model(data)
    model_post.optimize()
    res_post = extract_results(model_post, vars_post, data, "Postergación")
    if res_post: resultados_comparativos.append(res_post)

    # =========================================================================
    # ESCENARIO 2: PRODUCIR CONTRA PEDIDO (MTO)
    # =========================================================================
    print("\n" + "="*70)
    print(" RESOLVIENDO ESCENARIO 2: PRODUCIR CONTRA PEDIDO (MTO)")
    print("="*70)
    model_mto, vars_mto = build_base_model(data)
    model_mto = apply_mto_policy_varas(model_mto, vars_mto, data)
    model_mto.optimize()
    res_mto = extract_results(model_mto, vars_mto, data, "Contra Pedido (MTO)")
    if res_mto: resultados_comparativos.append(res_mto)

    # =========================================================================
    # ESCENARIO 3: PRODUCIR A STOCK (MTS)
    # =========================================================================
    print("\n" + "="*70)
    print(" RESOLVIENDO ESCENARIO 3: PRODUCIR A STOCK (MTS)")
    print("="*70)
    model_mts, vars_mts = build_base_model(data)
    model_mts = apply_mts_policy(model_mts, vars_mts, data)
    model_mts.optimize()
    res_mts = extract_results(model_mts, vars_mts, data, "Contra Stock (MTS)")
    if res_mts: resultados_comparativos.append(res_mts)

    # =========================================================================
    # TABLA RESUMEN DE COMPARACIÓN
    # =========================================================================
    print("\n" + "="*70)
    print(" TABLA RESUMEN COMPARATIVA")
    print("="*70)
    if resultados_comparativos:
        df_res = pd.DataFrame(resultados_comparativos)
        
        # Ajustamos el formato para que sea más legible en consola
        pd.options.display.float_format = '{:,.0f}'.format
        print(df_res.to_string(index=False))
        
        # Opcional: Guardar el resultado a un CSV para usarlo en el informe LaTeX
        df_res.to_csv("resultados_comparativos.csv", index=False)
        print("\n(Resultados guardados exitosamente en 'resultados_comparativos.csv')")

    # =========================================================================
    # ANÁLISIS: ¿QUÉ ETIQUETAS CONVIENE POSTERGAR? (32 COMBINACIONES)
    # =========================================================================
    # Cada producto (vino, etiqueta) se puede postergar o no -> 2^5 = 32 corridas.
    # La lógica está en combinaciones_32.py, acá solo la llamamos.
    print("\n" + "="*70)
    print(" ANÁLISIS: LAS 32 COMBINACIONES DE POSTERGACIÓN")
    print("="*70)
    analizar_combinaciones(data)

    # =========================================================================
    # RE-PLANIFICACIÓN PERÍODO A PERÍODO (HORIZONTE DECRECIENTE)
    # =========================================================================
    # En cada período se vuelve a resolver desde el nodo que ocurrió, partiendo con el
    # inventario (y lo embotellado en camino) que dejó el período anterior.
    # No es un horizonte rodante: el árbol no cambia y el horizonte se achica (3, 2, 1 períodos).
    # Sirve para mostrar qué se sabe y qué se decide en cada período (no anticipatividad).
    # La lógica está en src/replanificacion.py.
    print("\n" + "="*70)
    print(" RE-PLANIFICACIÓN PERÍODO A PERÍODO (HORIZONTE DECRECIENTE)")
    print("="*70)
    print("En cada período se vuelve a resolver el modelo desde el nodo que ocurrió,")
    print("partiendo con lo que dejó el período anterior, y se aplica solo lo de ese período.")

    politicas_replanif = {
        "Postergación": None,
        "Contra Stock": apply_mts_policy,
        "Contra Pedido": apply_mto_policy_varas,
    }
    resultados_replanif = correr_todos_los_caminos(data, politicas_replanif)

    # 1) Cada uno de los 7 caminos del árbol, período a período, comparando las políticas
    mostrar_por_camino(data, resultados_replanif,
                       abreviaturas={"Postergación": "Posterg.", "Contra Stock": "C.Stock", "Contra Pedido": "C.Pedido"})

    # 2) Costo de los 7 caminos y comparación con el modelo completo
    comparar_con_modelo_completo(data, politicas_replanif, resultados_replanif)

if __name__ == "__main__":
    main()
