from gurobipy import GRB

def extract_results(model, vars_dict, data, policy_name=""):
    """
    Extrae los resultados óptimos de Gurobi, calcula los KPIs esperados,
    muestra el plan de producción desagregado por período y registra el tiempo de ejecución.
    """
    if model.status != GRB.OPTIMAL:
        print(f"Advertencia: El modelo {policy_name} no encontró solución óptima. Estado: {model.status}")
        return None
        
    obj_val = model.ObjVal
    exec_time = model.Runtime  # Tiempo exacto de resolución de Gurobi en segundos
    
    # Desempaquetar variables
    w_b = vars_dict['w_b']
    w_bl = vars_dict['w_bl']
    w_l = vars_dict['w_l']
    s_b = vars_dict['s_b']
    s_bl = vars_dict['s_bl']
    b_bl = vars_dict['b_bl']
    z_b = vars_dict['z_b']
    z_bl = vars_dict['z_bl']
    z_l = vars_dict['z_l']
    
    prob = data['probabilidades']
    nodos = data['nodos']
    nodos_ext = [0] + nodos
    periodos_nodo = data['periodos_nodo']
    vinos = data['vinos']
    etiquetas = data['etiquetas_por_vino']
    
    # Cálculo de valores esperados globales (multiplicando por la probabilidad del nodo)
    exp_wip = sum(prob[n] * s_b[i, n].X for i in vinos for n in nodos)
    exp_fg = sum(prob[n] * s_bl[i, j, n].X for i in vinos for j in etiquetas[i] for n in nodos)
    exp_backorder = sum(prob[n] * b_bl[i, j, n].X for i in vinos for j in etiquetas[i] for n in nodos)
    
    exp_setups = sum(
        prob[n] * (z_b[i, n].X + sum(z_bl[i, j, n].X + z_l[i, j, n].X for j in etiquetas[i]))
        for i in vinos for n in nodos
    )
    
    results = {
        'Política': policy_name,
        'Costo Total ($)': obj_val,
        'WIP Esperado (bot)': exp_wip,
        'Prod. Terminado Esperado (bot)': exp_fg,
        'Backorders Esperados (bot)': exp_backorder,
        'Set-ups Esperados (#)': exp_setups,
        'Tiempo Ejecución (s)': exec_time
    }
    
    print(f"\n--- KPIs: {policy_name} ---")
    for k, v in results.items():
        if isinstance(v, float) or isinstance(v, int):
            if k == 'Set-ups Esperados (#)':
                print(f"{k}: {v:,.2f}")
            elif k == 'Tiempo Ejecución (s)':
                print(f"{k}: {v:,.4f} s")
            else:
                print(f"{k}: {v:,.0f}")
        else:
            print(f"{k}: {v}")

    # =========================================================================
    # Desglose de Producción por Período (Valor Esperado Ponderado)
    # =========================================================================
    print(f"\n   [Desglose de Producción Esperada por Período]")
    
    # Identificar qué nodos corresponden a cada período (excluyendo el nodo 0 auxiliar)
    períodos_map = {}
    for n in nodos:
        p = periodos_nodo[n]
        if p not in períodos_map:
            períodos_map[p] = []
        períodos_map[p].append(n)
        
    for p in sorted(períodos_map.keys()):
        ns_período = períodos_map[p]
        
        # Sumar volumen esperado producido en este período
        # Nota: W_b y W_bl en el nodo 'n' se programan en ese nodo para la etapa siguiente
        vol_wb_p = sum(prob[n] * w_b[i, n].X for n in ns_período for i in vinos)
        vol_wbl_p = sum(prob[n] * w_bl[i, j, n].X for n in ns_período for i in vinos for j in etiquetas[i])
        vol_wl_p = sum(prob[n] * w_l[i, j, n].X for n in ns_período for i in vinos for j in etiquetas[i])
        
        print(f"    • Período {p}: Embotellado WIP (wb) = {vol_wb_p:,.0f} bot | Acoplado (wbl) = {vol_wbl_p:,.0f} bot | Etiquetado (wl) = {vol_wl_p:,.0f} bot")

    return results