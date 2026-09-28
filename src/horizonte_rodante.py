"""
horizonte_rodante.py
 
Resolver el modelo período a período (horizonte rodante), partiendo cada vez con el
inventario con que cerró el período anterior.
 
Cómo funciona, siguiendo un camino del árbol (por ejemplo N1 -> N3 -> N8):
  Período 1: se resuelve el árbol completo desde N1 y se aplican SOLO las decisiones de N1.
  Período 2: se revela en qué nodo se está (N3). Se vuelve a resolver, pero solo el
             subárbol que cuelga de N3 (N3, N7, N8, N9), partiendo con:
               - el inventario sin etiquetar, el terminado y los atrasos al cierre de N1
               - lo que se embotelló en N1 y todavía viene en camino (llega a N3,
                 porque lo embotellado queda disponible una etapa después)
             y se aplican SOLO las decisiones de N3.
  Período 3: lo mismo desde N8, con lo que quedó al cierre de N3.
 
En el subárbol las probabilidades son condicionales (p_n / p_raíz): una vez que
sabemos que estamos en N3, las ramas N2 y N4 ya no pueden ocurrir.
 
Como el árbol y las probabilidades no cambian, cada nueva corrida debería repetir lo que
el modelo completo ya había decidido para ese nodo. Por eso al final comparamos el costo
esperado del horizonte rodante con el del modelo completo: si coinciden, queda verificado
que el modelo no usa información futura (no anticipatividad).
"""
import io
import contextlib
 
from gurobipy import GRB
 
from src.core_model import build_base_model
 
 
# -----------------------------------------------------------------------------
# Árbol
# -----------------------------------------------------------------------------
def hijos(data, n):
    """Nodos que cuelgan directamente de n."""
    return [h for h in data['nodos'] if data['antecesores'][h] == n]
 
 
def subarbol(data, raiz):
    """La raíz y todos sus descendientes, en el mismo orden que data['nodos']."""
    incluidos = {raiz}
    for n in data['nodos']:  # los nodos vienen ordenados por período, el padre antes que el hijo
        if data['antecesores'][n] in incluidos:
            incluidos.add(n)
    return [n for n in data['nodos'] if n in incluidos]
 
 
def caminos(data):
    """Todos los caminos desde el nodo 1 hasta una hoja (los 7 escenarios del árbol)."""
    raiz = [n for n in data['nodos'] if data['antecesores'][n] == 0][0]
    resultado = []
 
    def bajar(n, camino):
        h = hijos(data, n)
        if not h:
            resultado.append(camino)
        for k in h:
            bajar(k, camino + [k])
 
    bajar(raiz, [raiz])
    return resultado
 
 
def datos_subarbol(data, raiz, condiciones_iniciales=None):
    """
    Copia de data restringida al subárbol que cuelga de `raiz`:
      - nodos: solo la raíz y sus descendientes
      - antecesores: la raíz pasa a colgar del nodo 0 (el cierre del período anterior)
      - probabilidades: condicionales a estar en la raíz (p_n / p_raiz)
      - condiciones_iniciales: estado con que se parte (None = inicio del horizonte, Anexo A)
    El resto de los datos (costos, tiempos, demandas) no cambia.
    """
    d = dict(data)
    nodos = subarbol(data, raiz)
    p_raiz = data['probabilidades'][raiz]
 
    d['nodos'] = nodos
    d['antecesores'] = {n: (0 if n == raiz else data['antecesores'][n]) for n in nodos}
    d['probabilidades'] = {n: data['probabilidades'][n] / p_raiz for n in nodos}
    d['condiciones_iniciales'] = condiciones_iniciales
    return d
 
 
# -----------------------------------------------------------------------------
# Modelo
# -----------------------------------------------------------------------------
def resolver(data_sub, politica=None):
    """Arma el modelo sobre data_sub, le aplica la política (si hay) y lo resuelve."""
    # core_model y las políticas imprimen cosas, las escondemos
    with contextlib.redirect_stdout(io.StringIO()):
        m, v = build_base_model(data_sub)
        if politica is not None:
            m = politica(m, v, data_sub)
        m.setParam('MIPGap', 0)  # óptimo exacto, para poder comparar costos sin ruido
        m.optimize()
    if m.Status != GRB.OPTIMAL:
        raise RuntimeError(f"El modelo no llegó al óptimo (status {m.Status})")
    return m, v
 
 
def costo_nodo(v, data, n):
    """Costo que se paga en el nodo n: set-ups + inventarios + atrasos (sin ponderar por probabilidad)."""
    vinos, etiquetas = data['vinos'], data['etiquetas_por_vino']
    setups = sum(data['C_zb'] * v['z_b'][i, n].X
                 + sum(data['C_zbl'] * v['z_bl'][i, j, n].X + data['C_zl'] * v['z_l'][i, j, n].X
                       for j in etiquetas[i])
                 for i in vinos)
    inventarios = sum(data['C_sb'] * v['s_b'][i, n].X
                      + sum(data['C_sbl'] * v['s_bl'][i, j, n].X + data['C_bbl'] * v['b_bl'][i, j, n].X
                            for j in etiquetas[i])
                      for i in vinos)
    return setups + inventarios
 
 
def estado_al_cierre(v, data, n):
    """
    Lo que queda al cierre del nodo n y se traspasa al período siguiente:
    inventarios y atrasos, más lo que se embotelló en n y llega recién al nodo siguiente.
    """
    vinos, etiquetas = data['vinos'], data['etiquetas_por_vino']
    return {
        's_b': {i: v['s_b'][i, n].X for i in vinos},
        'w_b': {i: v['w_b'][i, n].X for i in vinos},
        's_bl': {(i, j): v['s_bl'][i, j, n].X for i in vinos for j in etiquetas[i]},
        'b_bl': {(i, j): v['b_bl'][i, j, n].X for i in vinos for j in etiquetas[i]},
        'w_bl': {(i, j): v['w_bl'][i, j, n].X for i in vinos for j in etiquetas[i]},
    }
 
 
# -----------------------------------------------------------------------------
# Horizonte rodante
# -----------------------------------------------------------------------------
def recorrer_camino(data, camino, politica=None, mostrar=True):
    """
    Recorre un camino del árbol (ej. [1, 3, 8]) resolviendo el modelo una vez por período.
    Devuelve (filas con lo decidido en cada período, costo total del camino).
    """
    # Revisamos que el camino tenga sentido: parte en la raíz y cada nodo es hijo del anterior
    if data['antecesores'][camino[0]] != 0:
        raise ValueError(f"El camino debe partir en la raíz del árbol, no en N{camino[0]}")
    for a, b in zip(camino, camino[1:]):
        if data['antecesores'][b] != a:
            raise ValueError(f"N{b} no es hijo de N{a}")
 
    vinos, etiquetas = data['vinos'], data['etiquetas_por_vino']
    filas = []
    condiciones = None  # período 1: se parte con lo del Anexo A
 
    for n in camino:
        # Se resuelve desde el nodo que efectivamente ocurrió, con lo que quedó del período anterior
        data_sub = datos_subarbol(data, n, condiciones)
        m, v = resolver(data_sub, politica)
 
        # De esta corrida solo se implementa lo del nodo n
        filas.append({
            'Período': data['periodos_nodo'][n],
            'Nodo': f"N{n}",
            # Con qué se parte: WIP que quedó del período anterior y lo embotellado que llega recién ahora
            'Parte con WIP': sum(condiciones['s_b'].values()) if condiciones else data['inv_inicial_wip'] * len(vinos),
            'Llega embotellado': (sum(condiciones['w_b'].values()) + sum(condiciones['w_bl'].values())) if condiciones
                                 else sum(data['demandas'][(i, j, n)] for i in vinos for j in etiquetas[i]),
            'Embotellar sin etiqueta': sum(v['w_b'][i, n].X for i in vinos),
            'Embotellar y etiquetar': sum(v['w_bl'][i, j, n].X for i in vinos for j in etiquetas[i]),
            'Etiquetar desde WIP': sum(v['w_l'][i, j, n].X for i in vinos for j in etiquetas[i]),
            'WIP al cierre': sum(v['s_b'][i, n].X for i in vinos),
            'Terminado al cierre': sum(v['s_bl'][i, j, n].X for i in vinos for j in etiquetas[i]),
            'Atrasos al cierre': sum(v['b_bl'][i, j, n].X for i in vinos for j in etiquetas[i]),
            'Costo del nodo': costo_nodo(v, data, n),
            'Costo esperado desde aquí': m.ObjVal,
        })
 
        # Lo que se traspasa al período siguiente
        condiciones = estado_al_cierre(v, data, n)
 
    total = sum(f['Costo del nodo'] for f in filas)
    if mostrar:
        print(f"\nCamino {' -> '.join('N' + str(n) for n in camino)}")
        print(f"{'Per':>3} {'Nodo':>4} {'Parte WIP':>10} {'Llega emb.':>10} {'Embot.':>9} {'Acopl.':>9} {'Etiq.':>9} "
              f"{'WIP fin':>9} {'Term. fin':>9} {'Atraso':>8} {'Costo nodo':>12} {'E[costo] desde aquí':>20}")
        for f in filas:
            print(f"{f['Período']:>3} {f['Nodo']:>4} {f['Parte con WIP']:>10,.0f} {f['Llega embotellado']:>10,.0f} {f['Embotellar sin etiqueta']:>9,.0f} "
                  f"{f['Embotellar y etiquetar']:>9,.0f} {f['Etiquetar desde WIP']:>9,.0f} {f['WIP al cierre']:>9,.0f} "
                  f"{f['Terminado al cierre']:>9,.0f} {f['Atrasos al cierre']:>8,.0f} {f['Costo del nodo']:>12,.0f} "
                  f"{f['Costo esperado desde aquí']:>20,.0f}")
        print(f"Costo total de este camino: {total:,.0f}")
    return filas, total
 
 
def evaluar_todos_los_caminos(data, politica=None, nombre="Postergación"):
    """
    Corre el horizonte rodante en los 7 caminos del árbol y compara el costo esperado
    (cada camino ponderado por la probabilidad de su hoja) con el del modelo completo.
    """
    # Modelo completo: una sola corrida con todo el árbol
    m_full, v_full = resolver(datos_subarbol(data, caminos(data)[0][0]), politica)
 
    print(f"\n{nombre}: horizonte rodante vs modelo completo, camino por camino")
    print(f"{'Camino':<18} {'Prob.':>6} {'Costo rodante':>15} {'Costo modelo completo':>22}")
    esperado = 0.0
    for camino in caminos(data):
        _, total = recorrer_camino(data, camino, politica, mostrar=False)
        total_full = sum(costo_nodo(v_full, data, n) for n in camino)
        p_hoja = data['probabilidades'][camino[-1]]
        esperado += p_hoja * total
        print(f"{' -> '.join('N' + str(n) for n in camino):<18} {p_hoja:>6.3f} {total:>15,.0f} {total_full:>22,.0f}")
 
    print(f"{'Costo esperado':<18} {'':>6} {esperado:>15,.0f} {m_full.ObjVal:>22,.0f}")
    dif = abs(esperado - m_full.ObjVal)
    if dif <= 1e-6 * max(1.0, m_full.ObjVal):
        print("-> Coinciden: volver a resolver en cada período no cambia el costo esperado,")
        print("   o sea el modelo completo ya decidía cada nodo sin usar información futura.")
    else:
        print(f"-> Diferencia de {dif:,.0f}. Revisar (puede haber óptimos alternativos o un error).")
    return esperado, m_full.ObjVal