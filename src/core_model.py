import gurobipy as gp
from gurobipy import GRB

def build_base_model(data):
    """
    Construye el modelo base (Postergación) de Programación Estocástica Multietapa.
    Retorna el objeto del modelo Gurobi y un diccionario con las variables 
    para poder modificarlas o extraer resultados fácilmente.
    """
    print("Construyendo el modelo base en Gurobi (Postergación habilitada)...")
    
    # Crear entorno mudo para no saturar la consola, a menos que queramos ver el log
    env = gp.Env(empty=True)
    env.setParam("OutputFlag", 0)
    env.start()
    
    m = gp.Model("Wine_Postponement_Model", env=env)
    
    # =========================================================================
    # Desempaquetar conjuntos de datos
    # =========================================================================
    vinos = data['vinos']
    etiquetas = data['etiquetas_por_vino']
    nodos = data['nodos'] # Nodos reales del 1 al 11
    nodos_ext = [0] + nodos # Nodo 0 artificial para condiciones iniciales
    antecesores = data['antecesores']
    prob = data['probabilidades']
    
    # =========================================================================
    # 1. Variables de Decisión
    # =========================================================================
    # Variables Continuas: Flujos de producción
    w_b = m.addVars(vinos, nodos_ext, vtype=GRB.CONTINUOUS, name="w_b")
    w_bl = m.addVars([(i, j, n) for i in vinos for j in etiquetas[i] for n in nodos_ext], vtype=GRB.CONTINUOUS, name="w_bl")
    w_l = m.addVars([(i, j, n) for i in vinos for j in etiquetas[i] for n in nodos_ext], vtype=GRB.CONTINUOUS, name="w_l")
    
    # Variables Continuas: Inventarios y Servicio
    s_b = m.addVars(vinos, nodos_ext, vtype=GRB.CONTINUOUS, name="s_b")
    s_bl = m.addVars([(i, j, n) for i in vinos for j in etiquetas[i] for n in nodos_ext], vtype=GRB.CONTINUOUS, name="s_bl")
    b_bl = m.addVars([(i, j, n) for i in vinos for j in etiquetas[i] for n in nodos_ext], vtype=GRB.CONTINUOUS, name="b_bl")
    
    # Variables Binarias: Set-ups (Solo ocurren en los nodos reales)
    z_b = m.addVars(vinos, nodos, vtype=GRB.BINARY, name="z_b")
    z_bl = m.addVars([(i, j, n) for i in vinos for j in etiquetas[i] for n in nodos], vtype=GRB.BINARY, name="z_bl")
    z_l = m.addVars([(i, j, n) for i in vinos for j in etiquetas[i] for n in nodos], vtype=GRB.BINARY, name="z_l")
    
    # =========================================================================
    # 2. Restricciones de Condiciones Iniciales (Nodo 0)
    # =========================================================================
    for i in vinos:
        # Inventarios iniciales WIP
        m.addConstr(s_b[i, 0] == data['inv_inicial_wip'], name=f"init_sb_{i}")
        m.addConstr(w_b[i, 0] == 0, name=f"init_wb_{i}")
        
        for j in etiquetas[i]:
            # Inventarios y backorders iniciales FG
            m.addConstr(s_bl[i, j, 0] == data['inv_inicial_fg'], name=f"init_sbl_{i}_{j}")
            m.addConstr(b_bl[i, j, 0] == data['inv_inicial_bo'], name=f"init_bbl_{i}_{j}")
            m.addConstr(w_l[i, j, 0] == 0, name=f"init_wl_{i}_{j}")
            
            # IMPORTANTE: Según el Anexo A, la demanda del nodo 1 se satisface 
            # con producción predefinida equivalente a esa demanda en t=0.
            m.addConstr(w_bl[i, j, 0] == data['demandas'][(i, j, 1)], name=f"init_wbl_{i}_{j}")

    # =========================================================================
    # 3. Restricciones Estructurales (Nodos 1 al 11)
    # =========================================================================
    for n in nodos:
        ant = antecesores[n]
        
        # A. Capacidad de Línea
        tiempo_b = gp.quicksum(data['t_wb'] * w_b[i, n] + data['t_zb'] * z_b[i, n] for i in vinos)
        tiempo_bl = gp.quicksum(data['t_wbl'] * w_bl[i, j, n] + data['t_zbl'] * z_bl[i, j, n] for i in vinos for j in etiquetas[i])
        tiempo_l = gp.quicksum(data['t_wl'] * w_l[i, j, n] + data['t_zl'] * z_l[i, j, n] for i in vinos for j in etiquetas[i])
        
        m.addConstr(tiempo_b + tiempo_bl + tiempo_l <= data['capacidad_horas'], name=f"capacidad_nodo_{n}")
        
        for i in vinos:
            # B. Ecuación de Balance WIP (Botellas sin etiquetar)
            m.addConstr(s_b[i, n] == s_b[i, ant] + w_b[i, ant] - gp.quicksum(w_l[i, j, n] for j in etiquetas[i]), name=f"bal_wip_{i}_{n}")
            
            # C. Lógicas Big-M para solo embotellado
            m.addConstr(w_b[i, n] <= data['M_wb'] * z_b[i, n], name=f"bigM_b_{i}_{n}")
            
            for j in etiquetas[i]:
                # D. Ecuación de Balance Producto Terminado (FG)
                m.addConstr(
                    s_bl[i, j, n] - b_bl[i, j, n] == s_bl[i, j, ant] - b_bl[i, j, ant] + w_bl[i, j, ant] + w_l[i, j, n] - data['demandas'][(i, j, n)], 
                    name=f"bal_fg_{i}_{j}_{n}"
                )
                
                # E. Lógicas Big-M para operaciones de etiquetado
                m.addConstr(w_bl[i, j, n] <= data['M_wbl'] * z_bl[i, j, n], name=f"bigM_bl_{i}_{j}_{n}")
                m.addConstr(w_l[i, j, n] <= data['M_wl'] * z_l[i, j, n], name=f"bigM_l_{i}_{j}_{n}")

    # =========================================================================
    # 4. Función Objetivo Estocástica (Minimizar Costo Esperado)
    # =========================================================================
    obj = gp.LinExpr()
    
    for n in nodos:
        p_n = prob[n]
        
        costos_setup = gp.quicksum(data['C_zb'] * z_b[i, n] for i in vinos) + \
                       gp.quicksum(data['C_zbl'] * z_bl[i, j, n] + data['C_zl'] * z_l[i, j, n] for i in vinos for j in etiquetas[i])
                       
        costos_inv_y_bo = gp.quicksum(data['C_sb'] * s_b[i, n] for i in vinos) + \
                          gp.quicksum(data['C_sbl'] * s_bl[i, j, n] + data['C_bbl'] * b_bl[i, j, n] for i in vinos for j in etiquetas[i])
                          
        obj += p_n * (costos_setup + costos_inv_y_bo)
        
    m.setObjective(obj, GRB.MINIMIZE)
    
    m.update()
    
    # Agrupamos las variables en un diccionario para poder manipularlas desde policies.py
    vars_dict = {
        'w_b': w_b, 'w_bl': w_bl, 'w_l': w_l,
        's_b': s_b, 's_bl': s_bl, 'b_bl': b_bl,
        'z_b': z_b, 'z_bl': z_bl, 'z_l': z_l
    }
    
    return m, vars_dict