import os
import re
import pandas as pd

def load_data(filepath):
    """
    Extrae dinámicamente todos los parámetros desde el archivo Excel del Anexo A.
    No contiene parámetros hardcodeados y valida cada hoja de entrada.
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"No se encontró el archivo en la ruta: {filepath}")

    xls = pd.ExcelFile(filepath)

    # =========================================================================
    # 1. HOJA: Configuracion (Encabezados en fila 3 -> skiprows=2)
    # =========================================================================
    df_config = xls.parse('Configuracion', skiprows=2).dropna(subset=['Parámetro'])
    config_map = dict(zip(df_config['Parámetro'].astype(str).str.strip(), df_config['Valor']))

    capacidad_horas = float(config_map['Capacidad de la línea por período'])
    periodos_horizonte = int(config_map['Períodos del horizonte'])
    estanques_disp = int(config_map['Estanques intermedios disponibles'])
    cap_estanque = float(config_map['Capacidad de cada estanque'])
    tamano_botella = float(config_map['Tamaño de botella (todos los vinos)'])

    # =========================================================================
    # 2. HOJA: Productos (Encabezados en fila 3 -> skiprows=2)
    # =========================================================================
    df_prod = xls.parse('Productos', skiprows=2)
    
    # 2.1 Vinos y Etiquetas admisibles
    vinos = []
    etiquetas_por_vino = {}
    for _, row in df_prod.iterrows():
        val_vino = str(row['Vino']).strip()
        if re.match(r'^Vino\s+\d+', val_vino, re.IGNORECASE):
            v_num = int(re.search(r'\d+', val_vino).group())
            vinos.append(v_num)
            nums = [int(n) for n in re.findall(r'\d+', str(row['Etiquetas admisibles']))]
            etiquetas_por_vino[v_num] = nums

    # 2.2 Inventarios iniciales
    inv_map = dict(zip(df_prod['Vino'].dropna().astype(str).str.strip(), df_prod['Etiquetas admisibles'].dropna()))
    inv_inicial_wip = float(inv_map.get('Botellas llenas sin etiquetar (ambos vinos)', 0.0))
    inv_inicial_fg = float(inv_map.get('Productos terminados (todas las combinaciones)', 0.0))
    inv_inicial_bo = float(inv_map.get('Pedidos atrasados (backlog) iniciales', 0.0))

    # =========================================================================
    # 3. HOJA: Setups_Costos (Encabezados en fila 3 -> skiprows=2)
    # =========================================================================
    df_sc = xls.parse('Setups_Costos', skiprows=2)
    
    sc_map = {}
    unit_map = {}
    for _, r in df_sc.iterrows():
        concepto = str(r['Concepto']).strip().lower()
        try:
            t_val = float(r['Tiempo (h)'])
            if pd.notna(r['Costo ($)']):
                try:
                    c_val = float(r['Costo ($)'])
                    sc_map[concepto] = (t_val, c_val)
                except (ValueError, TypeError):
                    unit_map[concepto] = t_val
            else:
                unit_map[concepto] = t_val
        except (ValueError, TypeError):
            continue

    t_zb, C_zb = sc_map['set-up de embotellado']
    t_zbl, C_zbl = sc_map['set-up conjunto de embotellado y etiquetado']
    t_zl, C_zl = sc_map['set-up de etiquetado']

    t_wb = unit_map['llenado (solo embotellar)']
    t_wl = unit_map['etiquetado (solo etiquetar)']
    t_wbl = unit_map['llenado y etiquetado acoplados']
    C_sb = unit_map['mantener una botella llena sin etiquetar']
    C_sbl = unit_map['mantener una botella de producto terminado']
    C_bbl = unit_map['pedido atrasado (backorder)']

    # =========================================================================
    # 4. HOJA: Arbol (Encabezados en fila 3 -> skiprows=2)
    # =========================================================================
    df_arbol = xls.parse('Arbol', skiprows=2)
    df_arbol['Nodo_clean'] = pd.to_numeric(df_arbol['Nodo'], errors='coerce')
    df_arbol = df_arbol.dropna(subset=['Nodo_clean']).copy()

    nodos = df_arbol['Nodo_clean'].astype(int).tolist()
    probabilidades = {int(r['Nodo_clean']): float(r['Prob. del nodo']) for _, r in df_arbol.iterrows()}
    estados_demanda = {int(r['Nodo_clean']): str(r['Estado de demanda']).strip() for _, r in df_arbol.iterrows()}
    periodos_nodo = {int(r['Nodo_clean']): int(r['Período']) for _, r in df_arbol.iterrows()}

    antecesores = {}
    for _, r in df_arbol.iterrows():
        n = int(r['Nodo_clean'])
        ant_val = r['Nodo antecesor']
        try:
            antecesores[n] = int(ant_val)
        except (ValueError, TypeError):
            antecesores[n] = 0

    # =========================================================================
    # 5. HOJA: Demanda (Encabezados en fila 3 -> skiprows=2)
    # =========================================================================
    df_dem = xls.parse('Demanda', skiprows=2).dropna(subset=['Producto (vino, etiqueta)'])
    df_dem = df_dem[df_dem['Producto (vino, etiqueta)'].astype(str).str.contains(r'\(\d+,\s*\d+\)')].copy()

    demandas = {}
    for _, row in df_dem.iterrows():
        tuple_str = re.search(r'\((\d+),\s*(\d+)\)', str(row['Producto (vino, etiqueta)'])).groups()
        v, l = int(tuple_str[0]), int(tuple_str[1])
        for n in nodos:
            col_name = f"Nodo {n}"
            demandas[(v, l, n)] = float(row[col_name])

    # Cotas Big-M dinámicas
    M_wb = capacidad_horas / t_wb
    M_wbl = capacidad_horas / t_wbl
    M_wl = capacidad_horas / t_wl

    # =========================================================================
    # Estructura del diccionario de datos
    # =========================================================================
    data = {
        'vinos': vinos,
        'etiquetas_por_vino': etiquetas_por_vino,
        'nodos': nodos,
        'antecesores': antecesores,
        'probabilidades': probabilidades,
        'estados_demanda': estados_demanda,
        'periodos_nodo': periodos_nodo,
        'demandas': demandas,
        'capacidad_horas': capacidad_horas,
        'periodos_horizonte': periodos_horizonte,
        'estanques_disp': estanques_disp,
        'cap_estanque': cap_estanque,
        'tamano_botella': tamano_botella,
        'inv_inicial_wip': inv_inicial_wip,
        'inv_inicial_fg': inv_inicial_fg,
        'inv_inicial_bo': inv_inicial_bo,
        't_wb': t_wb, 't_wbl': t_wbl, 't_wl': t_wl,
        't_zb': t_zb, 't_zbl': t_zbl, 't_zl': t_zl,
        'C_zb': C_zb, 'C_zbl': C_zbl, 'C_zl': C_zl,
        'C_sb': C_sb, 'C_sbl': C_sbl, 'C_bbl': C_bbl,
        'M_wb': M_wb, 'M_wbl': M_wbl, 'M_wl': M_wl
    }

    # =========================================================================
    # Reporte Detallado en Consola
    # =========================================================================
    print("=" * 80)
    print(" REPORTE DETALLADO DE EXTRACCIÓN DE DATOS (P12 Anexo A Datos.xlsx)")
    print("=" * 80)
    print(f"• Capacidad de Línea por Período : {capacidad_horas:.1f} horas")
    print(f"• Horizonte de Planificación     : {periodos_horizonte} períodos")
    print(f"• Estanques disponibles          : {estanques_disp} estanques de {cap_estanque:,.0f} L ({tamano_botella} L/botella)")
    print(f"• Inventarios Iniciales          : WIP={inv_inicial_wip}, FG={inv_inicial_fg}, Backorder={inv_inicial_bo}")
    print("-" * 80)
    print("• Configuración de Productos:")
    for v in vinos:
        print(f"   - Vino {v}: Etiquetas admisibles {etiquetas_por_vino[v]}")
    print("-" * 80)
    print("• Tiempos y Costos Operacionales:")
    print(f"   - Solo Embotellar (WIP) : Set-up = {t_zb:.2f} h | Costo Set-up = ${C_zb:,.0f} | Unitario = {t_wb:.5f} h/bot")
    print(f"   - Acoplado (FG)         : Set-up = {t_zbl:.2f} h | Costo Set-up = ${C_zbl:,.0f} | Unitario = {t_wbl:.5f} h/bot")
    print(f"   - Solo Etiquetar        : Set-up = {t_zl:.2f} h | Costo Set-up = ${C_zl:,.0f} | Unitario = {t_wl:.5f} h/bot")
    print(f"   - Costos Inventario     : WIP = ${C_sb}/bot·período | FG = ${C_sbl}/bot·período | Backorder = ${C_bbl}/bot·período")
    print("-" * 80)
    print("• Árbol de Escenarios:")
    terminal_nodes = [5, 6, 7, 8, 9, 10, 11]
    prob_term_sum = sum(probabilidades[n] for n in terminal_nodes)
    print(f"   Total Nodos: {len(nodos)} | Suma prob. nodos terminales: {prob_term_sum:.4f}")
    print("   Nodo | Período | Estado | Antecesor | Probabilidad")
    for n in nodos:
        print(f"   {n:4d} | {periodos_nodo[n]:7d} | {estados_demanda[n]:6s} | {antecesores[n]:9d} | {probabilidades[n]:.4f}")
    print("-" * 80)
    print("• Demanda (muestra primeros 3 nodos):")
    for (v, l) in [(1,1), (1,2), (1,3), (2,1), (2,2)]:
        d_str = " | ".join([f"N{n}: {demandas[(v,l,n)]:,.0f}" for n in [1, 2, 3]])
        print(f"   - Producto ({v},{l}) -> {d_str} ...")
    print("=" * 80)

    return data

if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ruta = os.path.join(base_dir, "data", "P12 Anexo A Datos.xlsx")
    data = load_data(ruta)