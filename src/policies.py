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


# Mismo contra pedido con el nombre que usamos en la rama cambios-antonella
apply_mto_policy_varas = apply_mto_policy


def usar_produccion_del_mismo_periodo(model, vars_dict, data):
    """
    Cambia la temporalidad del balance de producto terminado, según lo que confirmó
    el profe: al empezar cada período ya se conoce su demanda y lo que se produce
    acoplado (w_bl) en ese período sirve para cubrirla en el MISMO período.

    En core_model el balance usa w_bl del nodo anterior (llega una etapa después):
        s_bl[n] - b_bl[n] = s_bl[a(n)] - b_bl[a(n)] + w_bl[a(n)] + w_l[n] - d[n]
    Acá lo reemplazamos por:
        s_bl[n] - b_bl[n] = s_bl[a(n)] - b_bl[a(n)] + w_bl[n] + w_l[n] - d[n]
    Ojo con el nodo 1: su demanda ya viene cubierta por la producción programada
    (w_bl del nodo 0 = demanda del nodo 1, ver core_model), así que ahí la seguimos sumando.
    """
    w_bl = vars_dict['w_bl']
    w_l = vars_dict['w_l']
    s_bl = vars_dict['s_bl']
    b_bl = vars_dict['b_bl']

    for n in data['nodos']:
        ant = data['antecesores'][n]
        for i in data['vinos']:
            for j in data['etiquetas_por_vino'][i]:
                # sacamos el balance original de core_model...
                model.remove(model.getConstrByName(f"bal_fg_{i}_{j}_{n}"))
                # ...y ponemos el nuevo, con la producción del mismo nodo
                # Solo al inicio del horizonte (nodo 1) llega la producción predefinida del nodo 0.
                # En el horizonte rodante lo producido en el período anterior ya cubrió su propia
                # demanda, así que no hay nada "en camino".
                inicio_horizonte = ant == 0 and data.get('condiciones_iniciales') is None
                llega_programado = w_bl[i, j, ant] if inicio_horizonte else 0
                model.addConstr(
                    s_bl[i, j, n] - b_bl[i, j, n] == s_bl[i, j, ant] - b_bl[i, j, ant]
                    + w_bl[i, j, n] + llega_programado + w_l[i, j, n] - data['demandas'][(i, j, n)],
                    name=f"bal_fg_mismo_periodo_{i}_{j}_{n}"
                )
    model.update()
    return model


def apply_mto_policy_mismo_periodo(model, vars_dict, data):
    """
    VARIANTE (no se usa en main.py): Contra Pedido si lo producido en un período cubriera
    la demanda de ese mismo período. Ojo que contradice el Anexo A ("lo embotellado en un
    nodo queda disponible una etapa después"), por eso la dejamos solo para comparar.
    Política Contra Pedido (MTO), como la definimos con el profe:
    se espera a conocer la demanda del período y recién ahí se produce, sin
    anticiparse con inventario. Entonces:
        - la producción del período cubre la demanda de ese mismo período
          (usar_produccion_del_mismo_periodo)
        - z_l = 0            -> no se posterga (todo se produce acoplado, w_bl)
        - w_b = 0, s_b = 0   -> no hay stock sin etiquetar
        - s_bl = 0           -> no hay stock de producto terminado
    Si alcanza la capacidad, se produce justo la demanda y no quedan atrasos;
    si no alcanza, lo que falta queda como atraso (b_bl).
    """
    print("Aplicando política Contra Pedido (MTO): se produce la demanda del período, sin inventarios...")

    usar_produccion_del_mismo_periodo(model, vars_dict, data)

    z_l = vars_dict['z_l']
    w_b = vars_dict['w_b']
    s_b = vars_dict['s_b']
    s_bl = vars_dict['s_bl']

    for n in data['nodos']:
        for i in data['vinos']:
            # sin stock sin etiquetar (ahora lo dejamos explícito)
            model.addConstr(w_b[i, n] == 0, name=f"MTO_wb_zero_{i}_{n}")
            model.addConstr(s_b[i, n] == 0, name=f"MTO_sb_zero_{i}_{n}")
            for j in data['etiquetas_por_vino'][i]:
                # sin etiquetado separado (la Big-M de core_model obliga w_l = 0)
                model.addConstr(z_l[i, j, n] == 0, name=f"MTO_zl_zero_{i}_{j}_{n}")
                # sin stock de producto terminado
                model.addConstr(s_bl[i, j, n] == 0, name=f"MTO_sbl_zero_{i}_{j}_{n}")

    model.update()
    return model


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