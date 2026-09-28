"""
replanificacion.py

Re-planificación período a período (horizonte decreciente): se vuelve a resolver el modelo
en cada período, partiendo con el inventario con que cerró el período anterior.

Ojo, no es un horizonte rodante en sentido estricto: en un horizonte rodante el horizonte
avanza (se agrega un período nuevo al final) y se actualizan los pronósticos. Acá el árbol
y las probabilidades no cambian y el horizonte se achica (3, 2 y 1 períodos), así que lo
usamos para mostrar qué se sabe y qué se decide en cada período, y para verificar que el
modelo no usa información futura (no anticipatividad).

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
esperado re-planificando con el del modelo completo: si coinciden, queda verificado
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
# Re-planificación período a período
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
            parte_atrasos = data['inv_inicial_bo'] * sum(len(etiquetas[i]) for i in vinos)
            # Anexo A: la demanda del nodo 1 se cubre con producción predefinida (embotellada y etiquetada)
            llega_sin_etiqueta = 0.0
            llega_etiquetado = sum(data['demandas'][(i, j, n)] for i in vinos for j in etiquetas[i])
            llega = llega_etiquetado
        else:
            parte_wip = sum(condiciones['s_b'].values())
            parte_terminado = sum(condiciones['s_bl'].values())
            parte_atrasos = sum(condiciones['b_bl'].values())
            llega_sin_etiqueta = sum(condiciones['w_b'].values())   # embotellado sin etiqueta en el nodo anterior
            llega_etiquetado = sum(condiciones['w_bl'].values())    # embotellado y etiquetado en el nodo anterior
            llega = llega_sin_etiqueta + llega_etiquetado

        # 1) Se resuelve desde el nodo que ocurrió
        data_sub = datos_subarbol(data, n, condiciones)
        m, v = resolver(data_sub, politica)

        # Demanda del nodo cubierta a tiempo, producto por producto: lo que queda atrasado al
        # cierre (b_bl) se descuenta de la demanda de este período (los atrasos antiguos se
        # entregan primero). Entregado = demanda + atrasos que venían - atrasos al cierre.
        a_tiempo = sum(data['demandas'][(i, j, n)] - min(data['demandas'][(i, j, n)], v['b_bl'][i, j, n].X)
                       for i in vinos for j in etiquetas[i])
        entregado = sum(data['demandas'][(i, j, n)] + v['b_bl'][i, j, 0].X - v['b_bl'][i, j, n].X
                        for i in vinos for j in etiquetas[i])

        # 2) De esta corrida solo se aplica lo del nodo n
        periodos.append({
            'viene_de': data['antecesores'][n],
            'llega_sin_etiqueta': llega_sin_etiqueta,
            'llega_etiquetado': llega_etiquetado,
            'parte_atrasos': parte_atrasos,
            'demanda_a_tiempo': a_tiempo,
            'entregado': entregado,
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
    print(f"Camino {nombre_camino(camino)}")

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


def correr_todos_los_caminos(data, politicas):
    """
    Re-planifica período a período en los 7 caminos del árbol para cada política.
    politicas: diccionario {nombre: función de policies.py o None para postergación}
    Devuelve resultados[nombre][camino] = lista de períodos (lo que entrega recorrer_camino).
    """
    return {nombre: {tuple(c): recorrer_camino(data, c, politica) for c in caminos(data)}
            for nombre, politica in politicas.items()}


def mostrar_por_nodo(data, resultados):
    """
    Una tabla por nodo del árbol comparando las políticas: qué llega, qué decide cada
    política en ese nodo, con qué cierra y cuánto cuesta ese período.
    En un árbol a cada nodo se llega por un único camino, así que lo que se decide en un
    nodo es siempre lo mismo, sin importar qué pase después.
    """
    f = lambda x: f"{x:,.0f}"
    nombres = list(resultados)

    # Lo que pasó en cada nodo, para cada política (se toma de cualquier camino que pase por él)
    por_nodo = {nombre: {} for nombre in nombres}
    for nombre in nombres:
        for periodos in resultados[nombre].values():
            for p in periodos:
                por_nodo[nombre].setdefault(p['nodo'], p)

    cols = [("Llega emb.", 'llega_embotellado'), ("Embot. s/et", 'embotella_sin_etiqueta'),
            ("Embot.+etiq", 'embotella_y_etiqueta'), ("Etiqueta", 'etiqueta_desde_wip'),
            ("Fin s/etiq", 'cierra_wip'), ("Fin termin.", 'cierra_terminado'),
            ("Atrasadas", 'cierra_atrasos')]
    ancho_nombre = max(len(x) for x in nombres) + 2
    encabezado = f"  {'Política':<{ancho_nombre}}" + "".join(f"{c:>12}" for c, _ in cols) + f"{'Costo período':>16}"

    print("\nQué hace cada política en cada nodo (botellas):")
    print("  Llega emb.  = lo embotellado en el período anterior, que recién llega a este nodo")
    print("  Embot. s/et = embotella sin etiqueta (queda como WIP y llega al período siguiente)")
    print("  Embot.+etiq = embotella y etiqueta juntos (llega al período siguiente)")
    print("  Etiqueta    = etiqueta botellas del WIP (cubre la demanda de este mismo período)")
    print("  Fin ...     = lo que queda al cierre del nodo y pasa al período siguiente")

    for n in data['nodos']:
        padre = data['antecesores'][n]
        desde = "inicio del horizonte" if padre == 0 else f"se llega desde N{padre}"
        demanda = por_nodo[nombres[0]][n]['demanda']
        print(f"\nN{n} | período {data['periodos_nodo'][n]} | {desde} | prob. {data['probabilidades'][n]:.3f}"
              f" | demanda {f(demanda)}")
        print(encabezado)
        for nombre in nombres:
            p = por_nodo[nombre][n]
            print(f"  {nombre:<{ancho_nombre}}" + "".join(f"{f(p[k]):>12}" for _, k in cols)
                  + f"{'$' + f(p['costo_periodo']):>16}")



def _pesos(x):
    """Formato corto para costos: $1,092,645 o, sobre 100 millones, $1,119.5M."""
    return f"${x / 1e6:,.1f}M" if abs(x) >= 1e8 else f"${x:,.0f}"


def mostrar_por_camino(data, resultados, abreviaturas=None):
    """
    Una tabla por cada uno de los 7 caminos del árbol.
      - Columnas: los 3 períodos del camino y, dentro de cada período, las políticas.
      - Filas: el balance de cada período, agrupado en botellas sin etiquetar, botellas
        terminadas y pedidos, más lo que se produce para el período siguiente y el costo.
    Leyendo una fila de izquierda a derecha se ve cómo el "Cierre" de un período pasa a ser
    el "Inicio" del siguiente.
    """
    nombres = list(resultados)
    abreviaturas = abreviaturas or {x: x[:9] for x in nombres}
    todos = caminos(data)
    W_GRUPO, W_CONCEPTO, W_NUM = 13, 31, 10
    n_pol = len(nombres)
    w_periodo = W_NUM * n_pol + (n_pol - 1)  # ancho de un bloque de período (con separadores)

    def separador(c='-'):
        return "+" + c * (W_GRUPO + 2) + "+" + c * (W_CONCEPTO + 2) + ("+" + c * (w_periodo + 2)) * 3 + "+"

    def fila(grupo, concepto, celdas_por_periodo):
        txt = f"| {grupo:<{W_GRUPO}} | {concepto:<{W_CONCEPTO}} |"
        for celdas in celdas_por_periodo:
            txt += " " + " ".join(f"{x:>{W_NUM}}" for x in celdas) + " |"
        print(txt)

    # (grupo, concepto, clave o función, es_costo)
    FILAS = [
        ("SIN ETIQUETAR", "  Inicio (del período anterior)", 'parte_wip'),
        ("", "+ Llega (embotellado antes)", 'llega_sin_etiqueta'),
        ("", "- Se etiqueta ahora", 'etiqueta_desde_wip'),
        ("", "= Cierre (pasa al siguiente)", 'cierra_wip'),
        None,
        ("TERMINADAS", "  Inicio (del período anterior)", 'parte_terminado'),
        ("", "+ Llega (embot.+etiq. antes)", 'llega_etiquetado'),
        ("", "+ Se etiqueta ahora", 'etiqueta_desde_wip'),
        ("", "- Se entrega a clientes", 'entregado'),
        ("", "= Cierre (pasa al siguiente)", 'cierra_terminado'),
        None,
        ("PEDIDOS", "  Atrasos al inicio", 'parte_atrasos'),
        ("", "+ Demanda del nodo", 'demanda'),
        ("", "- Se entrega a clientes", 'entregado'),
        ("", "= Atrasos al cierre", 'cierra_atrasos'),
        ("", "  Demanda cubierta a tiempo", 'demanda_a_tiempo'),
        None,
        ("PRODUCE PARA", "  Embotella sin etiqueta", 'embotella_sin_etiqueta'),
        ("EL SIGUIENTE", "  Embotella y etiqueta juntos", 'embotella_y_etiqueta'),
        None,
        ("COSTO", "  Costo del período", 'costo_periodo'),
    ]

    print("\nPolíticas: " + " | ".join(f"{abreviaturas[x]} = {x}" for x in nombres))
    print("En el período 1, 'Llega (embot.+etiq. antes)' es la producción predefinida del Anexo A.")
    print("Costos sobre $100 millones se muestran en millones (M).")

    for k, c in enumerate(todos, start=1):
        per = [[resultados[x][tuple(c)][t] for x in nombres] for t in range(len(c))]  # per[t][política]
        print(f"\nCAMINO {k} de {len(todos)}: {nombre_camino(c)}   (probabilidad del camino {data['probabilidades'][c[-1]]:.3f})")
        print(separador('='))
        # Encabezado: período, nodo y demanda; y debajo las políticas
        cab = f"| {'':<{W_GRUPO}} | {'':<{W_CONCEPTO}} |"
        for t, n in enumerate(c):
            cab += " " + f"Período {per[t][0]['periodo']} - N{n}".center(w_periodo) + " |"
        print(cab)
        cab = f"| {'':<{W_GRUPO}} | {'(botellas)':<{W_CONCEPTO}} |"
        for t, n in enumerate(c):
            cab += " " + " ".join(f"{abreviaturas[x]:>{W_NUM}}" for x in nombres) + " |"
        print(cab)
        print(separador('='))

        for item in FILAS:
            if item is None:
                print(separador())
                continue
            grupo, concepto, clave = item
            celdas = []
            for t in range(len(c)):
                vals = [p[clave] for p in per[t]]
                celdas.append([_pesos(x) if clave == 'costo_periodo' else f"{x:,.0f}" for x in vals])
            fila(grupo, concepto, celdas)
        print(separador('='))

        totales = [sum(p['costo_periodo'] for p in resultados[x][tuple(c)]) for x in nombres]
        print("  Costo total del camino: " + " | ".join(f"{x} ${t:,.0f}" for x, t in zip(nombres, totales)))

        # Chequeo: los balances tienen que cuadrar (si no, hay un error en el traspaso)
        for fila_t in per:
            for p in fila_t:
                assert abs(p['parte_wip'] + p['llega_sin_etiqueta'] - p['etiqueta_desde_wip'] - p['cierra_wip']) < 1e-3
                assert abs(p['parte_terminado'] + p['llega_etiquetado'] + p['etiqueta_desde_wip']
                           - p['entregado'] - p['cierra_terminado']) < 1e-3
                assert abs(p['parte_atrasos'] + p['demanda'] - p['entregado'] - p['cierra_atrasos']) < 1e-3

def comparar_con_modelo_completo(data, politicas, resultados=None):
    """
    Costo de cada camino re-planificando período a período, para cada política, y comparación del costo
    esperado con resolver el modelo completo una sola vez.
      - Costo de un camino = suma de lo que se paga en sus 3 períodos.
      - Costo esperado = cada camino ponderado por la probabilidad de su hoja.
    Si coinciden, el modelo completo ya decidía cada período sin usar información futura
    (no anticipatividad).
    """
    f = lambda x: f"{x:,.0f}"
    todos = caminos(data)
    if resultados is None:
        resultados = correr_todos_los_caminos(data, politicas)
    nombres = list(politicas)

    costos = {x: {tuple(c): sum(p['costo_periodo'] for p in resultados[x][tuple(c)]) for c in todos}
              for x in nombres}
    completo = {x: resolver(datos_subarbol(data, todos[0][0]), politicas[x])[0].ObjVal for x in nombres}

    ancho = max(16, max(len(x) for x in nombres) + 2)
    print("\nCosto total de cada camino (suma de sus 3 períodos):")
    print(f"  {'Camino':<20} {'Prob.':>6}" + "".join(f"{x:>{ancho}}" for x in nombres))
    for c in todos:
        p_hoja = data['probabilidades'][c[-1]]
        print(f"  {nombre_camino(c):<20} {p_hoja:>6.3f}"
              + "".join(f"{'$' + f(costos[x][tuple(c)]):>{ancho}}" for x in nombres))

    esperado = {x: sum(data['probabilidades'][c[-1]] * costos[x][tuple(c)] for c in todos) for x in nombres}
    coincide = {x: abs(esperado[x] - completo[x]) <= 1e-6 * max(1.0, completo[x]) for x in nombres}
    print("  " + "-" * (27 + ancho * len(nombres)))
    print(f"  {'Costo esperado (re-planif.)':<27}" + "".join(f"{'$' + f(esperado[x]):>{ancho}}" for x in nombres))
    print(f"  {'Costo esperado (completo)':<27}" + "".join(f"{'$' + f(completo[x]):>{ancho}}" for x in nombres))
    print(f"  {'¿Coinciden?':<27}" + "".join(f"{('Sí' if coincide[x] else 'NO'):>{ancho}}" for x in nombres))

    if all(coincide.values()):
        print("\nConclusión: re-planificar en cada período da el mismo costo que resolver el árbol completo")
        print("una vez. O sea, el modelo multietapa ya decidía cada período usando solo la información")
        print("disponible en ese momento (no anticipatividad).")
    else:
        print("\nOjo: hay diferencias entre re-planificar y el modelo completo. Revisar.")
    return esperado, completo
