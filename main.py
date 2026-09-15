import os
import pandas as pd
from src.data_loader import load_data
from src.core_model import build_base_model
from src.policies import apply_mto_policy, apply_mts_policy
from src.kpi_calculator import extract_results

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
    model_mto = apply_mto_policy(model_mto, vars_mto, data)
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

if __name__ == "__main__":
    main()