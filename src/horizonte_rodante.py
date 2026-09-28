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
def nombre_camino(camino):
    """[1, 3, 8] -> 'N1 -> N3 -> N8'"""
    return " -> ".join(f"N{n}" for n in camino)


def recorrer_camino(data, camino, politica=None):
    """
    Recorre un camino del árbol (ej. [1, 3, 8]) resolviendo el modelo una vez por período.
    En cada período:
      1) se resuelve desde el nodo que ocurrió, partiendo con lo que dejó el período anterior
      2) se aplica SOLO lo que el modelo decide para ese nodo
      3) lo que queda al cierre se traspasa al período siguiente
    Devuelve una lista con lo que pasó en cada período (una fila por período).
    """
    # Revisamos que el camino tenga sentido: parte en la raíz y cada nodo es hijo del anterior
    if data['antecesores'][camino[0]] != 0:
        raise ValueError(f"El camino debe partir en la raíz del árbol, no en N{camino[0]}")
    for a, b in zip(camino, camino[1:]):
        if data['antecesores'][b] != a:
            raise ValueError(f"N{b} no es hijo de N{a}")

    vinos, etiquetas = data['vinos'], data['etiquetas_por_vino']
    periodos = []
    condiciones = None  # período 1: se parte con lo del Anexo A

    for n in camino:
        # Con qué se parte este período
        if condiciones is None:
            parte_wip = data['inv_inicial_wip'] * len(vinos)
            parte_terminado = data['inv_inicial_fg'] * sum(len(etiquetas[i]) for i in vinos)
            # Anexo A: la demanda del nodo 1 se cubre con producción predefinida
            llega = sum(data['demandas'][(i, j, n)] for i in vinos for j in etiquetas[i])
        else:
            parte_wip = sum(condiciones['s_b'].values())
            parte_terminado = sum(condiciones['s_bl'].values())
            llega = sum(condiciones['w_b'].values()) + sum(condiciones['w_bl'].values())

        # 1) Se resuelve desde el nodo que ocurrió
        data_sub = datos_subarbol(data, n, condiciones)
        m, v = resolver(data_sub, politica)

        # 2) De esta corrida solo se aplica lo del nodo n
        periodos.append({
            'periodo': data['periodos_nodo'][n],
            'nodo': n,
            'demanda': sum(data['demandas'][(i, j, n)] for i in vinos for j in etiquetas[i]),
            'parte_wip': parte_wip,
            'parte_terminado': parte_terminado,
            'llega_embotellado': llega,
            'embotella_sin_etiqueta': sum(v['w_b'][i, n].X for i in vinos),
            'embotella_y_etiqueta': sum(v['w_bl'][i, j, n].X for i in vinos for j in etiquetas[i]),
            'etiqueta_desde_wip': sum(v['w_l'][i, j, n].X for i in vinos for j in etiquetas[i]),
            'cierra_wip': sum(v['s_b'][i, n].X for i in vinos),
            'cierra_terminado': sum(v['s_bl'][i, j, n].X for i in vinos for j in etiquetas[i]),
            'cierra_atrasos': sum(v['b_bl'][i, j, n].X for i in vinos for j in etiquetas[i]),
            'costo_periodo': costo_nodo(v, data, n),
        })

        # 3) Lo que se traspasa al período siguiente
        condiciones = estado_al_cierre(v, data, n)

    return periodos


def mostrar_camino(camino, periodos):
    """Imprime período a período lo que pasó en un camino, en palabras."""
    f = lambda x: f"{x:,.0f}"
    print(f"\nEjemplo: se recorre el camino {nombre_camino(camino)}")
    print("En cada período se vuelve a resolver el modelo desde el nodo que ocurrió,")
    print("partiendo con lo que dejó el período anterior, y se aplica solo lo de ese período.")

    for k, p in enumerate(periodos):
        print(f"\n  PERÍODO {p['periodo']}: se está en N{p['nodo']} (demanda del nodo: {f(p['demanda'])} botellas)")
        print(f"    Parte con : {f(p['parte_wip'])} sin etiquetar y {f(p['parte_terminado'])} terminadas en bodega,")
        if k == 0:
            print(f"                y {f(p['llega_embotellado'])} botellas de producción predefinida (Anexo A: cubren la demanda de N1)")
        else:
            print(f"                y le llegan {f(p['llega_embotellado'])} botellas embotelladas en el período anterior")
        print(f"    Decide    : embotellar sin etiqueta {f(p['embotella_sin_etiqueta'])}"
              f" | embotellar y etiquetar {f(p['embotella_y_etiqueta'])}"
              f" | etiquetar desde el WIP {f(p['etiqueta_desde_wip'])}")
        print(f"    Cierra con: {f(p['cierra_wip'])} sin etiquetar | {f(p['cierra_terminado'])} terminadas"
              f" | {f(p['cierra_atrasos'])} atrasadas")
        print(f"    Costo del período: ${f(p['costo_periodo'])}")
        if k + 1 < len(periodos):
            print(f"    -> Pasan al período {p['periodo'] + 1}: {f(p['cierra_wip'])} sin etiquetar, "
                  f"{f(p['cierra_terminado'])} terminadas y {f(p['embotella_sin_etiqueta'] + p['embotella_y_etiqueta'])} "
                  f"botellas que vienen en camino")

    total = sum(p['costo_periodo'] for p in periodos)
    print(f"\n  Costo total del camino {nombre_camino(camino)}: ${f(total)}")


def comparar_con_modelo_completo(data, politicas):
    """
    Para cada política corre el horizonte rodante en los 7 caminos del árbol y compara con
    resolver el modelo completo una sola vez.
      - Costo de cada camino = suma de lo que se paga en sus 3 períodos.
      - Costo esperado = cada camino ponderado por la probabilidad de su hoja.
    Si el costo esperado coincide, el modelo completo ya decidía cada período sin usar
    información futura (no anticipatividad).
    politicas: diccionario {nombre: función de policies.py o None para postergación}
    """
    f = lambda x: f"{x:,.0f}"
    todos = caminos(data)
    costos = {}   # costos[nombre][camino] = costo del camino con horizonte rodante
    completo = {}  # costo esperado del modelo completo (una sola corrida)
    for nombre, politica in politicas.items():
        costos[nombre] = {tuple(c): sum(p['costo_periodo'] for p in recorrer_camino(data, c, politica))
                          for c in todos}
        m_full, _ = resolver(datos_subarbol(data, todos[0][0]), politica)
        completo[nombre] = m_full.ObjVal

    nombres = list(politicas)
    ancho = max(18, max(len(x) for x in nombres) + 2)
    print("\nCosto de cada camino re-planificando en cada período (horizonte rodante):")
    print(f"{'Camino':<18} {'Prob.':>6}" + "".join(f"{x:>{ancho}}" for x in nombres))
    for c in todos:
        p_hoja = data['probabilidades'][c[-1]]
        print(f"{nombre_camino(c):<18} {p_hoja:>6.3f}" + "".join(f"{f(costos[x][tuple(c)]):>{ancho}}" for x in nombres))

    esperado = {x: sum(data['probabilidades'][c[-1]] * costos[x][tuple(c)] for c in todos) for x in nombres}
    print("-" * (25 + ancho * len(nombres)))
    print(f"{'Costo esperado (rodante)':<25}" + "".join(f"{f(esperado[x]):>{ancho}}" for x in nombres))
    print(f"{'Costo esperado (completo)':<25}" + "".join(f"{f(completo[x]):>{ancho}}" for x in nombres))
    iguales = all(abs(esperado[x] - completo[x]) <= 1e-6 * max(1.0, completo[x]) for x in nombres)
    print(f"{'¿Coinciden?':<25}" + "".join(f"{('Sí' if abs(esperado[x] - completo[x]) <= 1e-6 * max(1.0, completo[x]) else 'NO'):>{ancho}}" for x in nombres))

    if iguales:
        print("\nConclusión: re-planificar en cada período da el mismo costo que resolver el árbol completo")
        print("una vez. O sea, el modelo multietapa ya decidía cada período usando solo la información")
        print("disponible en ese momento (no anticipatividad).")
    else:
        print("\nOjo: hay diferencias entre el horizonte rodante y el modelo completo. Revisar.")
    return esperado, completo
