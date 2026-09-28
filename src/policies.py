# -----------------------------------------------------------------------------
# OJO: esta era la versión anterior de apply_mto_policy. No es contra pedido:
# obliga a producir acoplado la DEMANDA ESPERADA del período siguiente, o sea
# produce por adelantado según un pronóstico (es un "contra stock ingenuo", lo
# que en la presentación llamamos contra pronóstico). La dejamos comentada como
# referencia; la versión correcta de contra pedido está justo abajo.
# -----------------------------------------------------------------------------
# def apply_mto_policy(model, vars_dict, data):
#     """
#     Política MTO Realista (Make-to-Forecast):
#     Sin postergación (WIP = 0, y sin usar wb ni wl). 
#     La producción acoplada (w_bl) responde a la demanda estimada (Valor Esperado).
#     """
#     print("Aplicando política MTO Realista estricta (Solo producción acoplada w_bl)...")
#
#     w_b = vars_dict['w_b']
#     w_l = vars_dict['w_l']
#     w_bl = vars_dict['w_bl']
#     s_b = vars_dict['s_b']
#
#     nodos = data['nodos']
#     nodos_ext = [0] + nodos
#     antecesores = data['antecesores']
#     prob = data['probabilidades']
#     demandas = data['demandas']
#     vinos = data['vinos']
#     etiquetas = data['etiquetas_por_vino']
#
#     # 1. Prohibir totalmente el WIP y las operaciones desacumuladas (wb y wl)
#     for i in vinos:
#         for n in nodos_ext:
#             model.addConstr(s_b[i, n] == 0, name=f"MTO_sb_zero_{i}_{n}")
#             model.addConstr(w_b[i, n] == 0, name=f"MTO_wb_zero_{i}_{n}")
#             for j in etiquetas[i]:
#                 model.addConstr(w_l[i, j, n] == 0, name=f"MTO_wl_zero_{i}_{j}_{n}")
#
#     # 2. Forzar la producción acoplada al Valor Esperado de la demanda futura
#     for n in nodos_ext:
#         hijos = [h for h in nodos if antecesores[h] == n]
#
#         for i in vinos:
#             for j in etiquetas[i]:
#                 if not hijos:
#                     model.addConstr(w_bl[i, j, n] == 0, name=f"MTO_wbl_term_{i}_{j}_{n}")
#                 else:
#                     demanda_esperada = 0
#                     for h in hijos:
#                         prob_condicional = prob[h] / prob.get(n, 1.0)
#                         demanda_esperada += prob_condicional * demandas[(i, j, h)]
#
#                     model.addConstr(w_bl[i, j, n] == demanda_esperada, name=f"MTO_wbl_est_{i}_{j}_{n}")
#
#     model.update()
#     return model


def apply_mto_policy(model, vars_dict, data):
    """
    Política Contra Pedido (MTO), según Varas et al. (2018), restricciones (17)-(18):
        z_l  = 0  -> no hay set-up de solo etiquetar, o sea no se posterga
        s_bl = 0  -> no se guarda producto terminado
    Todo se produce acoplado (w_bl), pero como no puede sobrar nada, el modelo solo
    produce lo que es seguro que se va a pedir y el resto queda como atraso (b_bl)
    que se cubre en la etapa siguiente, cuando el pedido ya se conoce.
    """
    print("Aplicando política Contra Pedido (MTO) según Varas et al. (2018)...")

    z_l = vars_dict['z_l']
    s_bl = vars_dict['s_bl']

    vinos = data['vinos']
    etiquetas = data['etiquetas_por_vino']
    nodos = data['nodos']  # z_l solo existe en los nodos reales (1 a 11)

    for i in vinos:
        for j in etiquetas[i]:
            for n in nodos:
                # (17) sin etiquetado separado. Con esto la Big-M de core_model ya obliga w_l = 0
                model.addConstr(z_l[i, j, n] == 0, name=f"MTO_zl_zero_{i}_{j}_{n}")
                # (18) sin stock de producto terminado
                model.addConstr(s_bl[i, j, n] == 0, name=f"MTO_sbl_zero_{i}_{j}_{n}")

    # No hace falta prohibir w_b ni s_b: si nunca se puede etiquetar desde el WIP,
    # embotellar sin etiqueta solo agrega costo, así que el óptimo los deja en 0.

    model.update()
    return model


apply_mto_policy_varas = apply_mto_policy


def apply_mts_policy(model, vars_dict, data):
    """
    Política Make-to-Stock (MTS):
    Sin inventario WIP (s_b = 0) y sin operaciones de solo embotellar (wb) 
    ni solo etiquetar (wl). Todo se produce acoplado (w_bl).
    """
    print("Aplicando restricciones de política MTS estricta (Cero WIP, sin postergación)...")
    
    w_b = vars_dict['w_b']
    w_l = vars_dict['w_l']
    s_b = vars_dict['s_b']
    
    vinos = data['vinos']
    etiquetas = data['etiquetas_por_vino']
    nodos_ext = [0] + data['nodos']
    
    for i in vinos:
        for n in nodos_ext:
            model.addConstr(s_b[i, n] == 0, name=f"MTS_sb_zero_{i}_{n}")
            model.addConstr(w_b[i, n] == 0, name=f"MTS_wb_zero_{i}_{n}")
            for j in etiquetas[i]:
                model.addConstr(w_l[i, j, n] == 0, name=f"MTS_wl_zero_{i}_{j}_{n}")
            
    model.update()
    return model
