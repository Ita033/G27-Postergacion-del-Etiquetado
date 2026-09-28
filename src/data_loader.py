"""Datos hardcodeados de la instancia de referencia P12.

Este módulo reemplaza la lectura del Excel. Mantiene exactamente la estructura
`data[...]` que utilizan core_model.py, policies.py y kpi_calculator.py.
"""

# =============================================================================
# 1. PRODUCTOS
# =============================================================================

VINOS = [1, 2]

ETIQ = {
    1: [1, 2, 3],
    2: [1, 2],
}

PROD = [(i, j) for i in VINOS for j in ETIQ[i]]


# =============================================================================
# 2. CONFIGURACIÓN GENERAL
# =============================================================================

CAP = 84.0                       # horas disponibles por período
PERIODOS_HORIZONTE = 3

N_TANQ = 20                      # estanques intermedios disponibles por período
VOL_TANQ = 10000.0               # litros por estanque
VOL_BOT = 0.75                   # litros por botella
Q_TANQ = VOL_TANQ / VOL_BOT      # 13.333,33 botellas por estanque


# =============================================================================
# 3. TIEMPOS DE PROCESO
# =============================================================================

# Horas por botella
T_WB = 0.00014                   # solo embotellar
T_WBL = 0.00028                  # embotellar + etiquetar acoplado
T_WL = 0.00028                   # solo etiquetar

# Horas de set-up
S_WB = 1.5                       # set-up de embotellado
S_WBL = 1.5                      # set-up conjunto embotellado + etiquetado
S_WL = 0.5                       # set-up de etiquetado


# =============================================================================
# 4. COSTOS
# =============================================================================

# Costo por set-up
C_ZB = 1500.0
C_ZBL = 1500.0
C_ZL = 500.0

# Costo por botella por período
C_SB = 10.0                      # inventario WIP sin etiquetar
C_SBL = 15.0                     # inventario producto terminado
C_BBL = 15000.0                  # backorder


# =============================================================================
# 5. INVENTARIOS INICIALES
# =============================================================================

INV_INICIAL_WIP = 0.0
INV_INICIAL_FG = 0.0
INV_INICIAL_BO = 0.0


# =============================================================================
# 6. ÁRBOL DE ESCENARIOS
# =============================================================================
# nodo: (período, estado_demanda, nodo_antecesor, probabilidad_condicional)
#
# IMPORTANTE:
# - ARBOL guarda probabilidades CONDICIONALES, tal como el Anexo A.
# - El modelo usa probabilidades INCONDICIONALES por nodo, por lo que se calculan
#   más abajo multiplicando las probabilidades a lo largo de cada camino.
# =============================================================================

ARBOL = {
    1:  (1, "Media", 0, 1.0),

    2:  (2, "Alta",  1, 0.3),
    3:  (2, "Media", 1, 0.4),
    4:  (2, "Baja",  1, 0.3),

    5:  (3, "Alta",  2, 0.7),
    6:  (3, "Media", 2, 0.3),

    7:  (3, "Alta",  3, 1 / 3),
    8:  (3, "Media", 3, 1 / 3),
    9:  (3, "Baja",  3, 1 / 3),

    10: (3, "Media", 4, 0.6),
    11: (3, "Baja",  4, 0.4),
}

NODOS = sorted(ARBOL)
PERIODOS_NODO = {n: ARBOL[n][0] for n in NODOS}
ESTADOS_DEMANDA = {n: ARBOL[n][1] for n in NODOS}
ANTECESORES = {n: ARBOL[n][2] for n in NODOS}
PROB_CONDICIONALES = {n: float(ARBOL[n][3]) for n in NODOS}


def _calcular_probabilidades_incondicionales():
    """Calcula P(nodo) a partir de las probabilidades condicionales del árbol."""
    probabilidades = {}
    for n in NODOS:
        ant = ANTECESORES[n]
        p_cond = PROB_CONDICIONALES[n]
        probabilidades[n] = p_cond if ant == 0 else probabilidades[ant] * p_cond
    return probabilidades


PROBABILIDADES = _calcular_probabilidades_incondicionales()


# =============================================================================
# 7. DEMANDA
# =============================================================================
# DEM[(vino, etiqueta)] = demanda en nodos 1,...,11
# =============================================================================

DEM = {
    (1, 1): [
        23525, 53218, 34328, 18118, 81856, 45302,
        50426, 31482, 12538, 30856, 10426,
    ],

    (1, 2): [
        24328, 15184, 28525, 45832, 24546, 31371,
        23569, 40767, 57965, 20546, 45569,
    ],

    (1, 3): [
        20368, 38150, 21080, 6762, 4920, 25765,
        35043, 25646, 16248, 10920, 11043,
    ],

    (2, 1): [
        21080, 39387, 30368, 12646, 34115, 22773,
        37045, 27831, 18616, 24115, 17045,
    ],

    (2, 2): [
        22991, 38048, 27991, 14949, 33440, 22824,
        35085, 25147, 15209, 23440, 15085,
    ],
}

# El resto del proyecto espera demandas con clave (vino, etiqueta, nodo).
DEMANDAS = {
    (i, j, n): float(valores[n - 1])
    for (i, j), valores in DEM.items()
    for n in NODOS
}


# =============================================================================
# 8. COTAS BIG-M
# =============================================================================
# Misma lógica que tenía el data_loader original: máximo teórico si todas las
# 84 h del período se dedicaran a una sola operación, sin descontar set-ups.
# =============================================================================

M_WB = CAP / T_WB
M_WBL = CAP / T_WBL
M_WL = CAP / T_WL


# =============================================================================
# 9. NIVELES DE REFERENCIA PARA ANÁLISIS POSTERIOR
# =============================================================================
# Están en el Anexo A. El modelo actual todavía no los usa directamente, pero
# quedan disponibles sin depender del Excel para futuros experimentos.
# =============================================================================

NIVELES_VARIABILIDAD = [0.10, 0.30, 0.50]
NIVELES_CAPACIDAD = [21.0, 42.0, 63.0, 84.0]
NIVELES_ETIQUETAS_POSTERGABLES = [0, 2, 3, 4, 5]
NIVELES_CORRELACION = ["positiva", "negativa"]


# =============================================================================
# 10. VALIDACIONES BÁSICAS
# =============================================================================

def _validar_datos():
    # Debe existir demanda para cada uno de los 5 productos y 11 nodos.
    assert set(DEM) == set(PROD), "DEM no contiene exactamente los productos definidos."
    assert all(len(valores) == len(NODOS) for valores in DEM.values()), \
        "Cada producto debe tener una demanda para cada nodo."

    # Las probabilidades de los nodos terminales deben sumar 1.
    terminales = [n for n in NODOS if n not in ANTECESORES.values()]
    suma_terminales = sum(PROBABILIDADES[n] for n in terminales)
    assert abs(suma_terminales - 1.0) < 1e-9, \
        f"Las probabilidades terminales suman {suma_terminales}, no 1."


_validar_datos()


# =============================================================================
# 11. FUNCIÓN DE CARGA COMPATIBLE CON EL RESTO DEL PROYECTO
# =============================================================================

def load_data(filepath=None):
    """Devuelve los datos del caso P12 sin leer ningún archivo Excel.

    `filepath` se conserva como argumento opcional para mantener compatibilidad
    con el main.py antiguo. Se ignora deliberadamente.
    """

    data = {
        # Conjuntos y árbol
        'vinos': VINOS.copy(),
        'etiquetas_por_vino': {i: etiquetas.copy() for i, etiquetas in ETIQ.items()},
        'nodos': NODOS.copy(),
        'antecesores': ANTECESORES.copy(),
        'probabilidades': PROBABILIDADES.copy(),
        'estados_demanda': ESTADOS_DEMANDA.copy(),
        'periodos_nodo': PERIODOS_NODO.copy(),
        'demandas': DEMANDAS.copy(),

        # Configuración
        'capacidad_horas': CAP,
        'periodos_horizonte': PERIODOS_HORIZONTE,
        'estanques_disp': N_TANQ,
        'cap_estanque': VOL_TANQ,
        'tamano_botella': VOL_BOT,

        # Inventarios iniciales
        'inv_inicial_wip': INV_INICIAL_WIP,
        'inv_inicial_fg': INV_INICIAL_FG,
        'inv_inicial_bo': INV_INICIAL_BO,

        # Tiempos unitarios
        't_wb': T_WB,
        't_wbl': T_WBL,
        't_wl': T_WL,

        # Tiempos de set-up
        't_zb': S_WB,
        't_zbl': S_WBL,
        't_zl': S_WL,

        # Costos
        'C_zb': C_ZB,
        'C_zbl': C_ZBL,
        'C_zl': C_ZL,
        'C_sb': C_SB,
        'C_sbl': C_SBL,
        'C_bbl': C_BBL,

        # Big-M
        'M_wb': M_WB,
        'M_wbl': M_WBL,
        'M_wl': M_WL,

        # Extras útiles para análisis futuros (no afectan el modelo actual)
        'productos': PROD.copy(),
        'q_tanque_botellas': Q_TANQ,
        'prob_condicionales': PROB_CONDICIONALES.copy(),
        'niveles_variabilidad': NIVELES_VARIABILIDAD.copy(),
        'niveles_capacidad': NIVELES_CAPACIDAD.copy(),
        'niveles_etiquetas_postergables': NIVELES_ETIQUETAS_POSTERGABLES.copy(),
        'niveles_correlacion': NIVELES_CORRELACION.copy(),
    }

    print("=" * 80)
    print(" DATOS P12 CARGADOS DESDE EL CÓDIGO (sin Excel)")
    print("=" * 80)
    print(f"• Capacidad por período          : {CAP:.1f} h")
    print(f"• Horizonte                      : {PERIODOS_HORIZONTE} períodos")
    print(f"• Productos                      : {PROD}")
    print(f"• Nodos del árbol                : {len(NODOS)}")
    print(f"• Prob. nodos terminales         : "
          f"{sum(PROBABILIDADES[n] for n in [5, 6, 7, 8, 9, 10, 11]):.4f}")
    print("=" * 80)

    return data


if __name__ == "__main__":
    datos = load_data()
    print("\nProbabilidades incondicionales por nodo:")
    for n in datos['nodos']:
        print(f"Nodo {n:2d}: {datos['probabilidades'][n]:.6f}")
