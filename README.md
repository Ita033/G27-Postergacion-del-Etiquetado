# G27-Postergacion-del-Etiquetado

Modelo de Programación Estocástica Multietapa (MS-MIP) para evaluar políticas de postergación de etiquetado en una viña exportadora, desarrollado como Proyecto de Capstone (ICS2122).

El modelo evalúa los beneficios de la **postergación del etiquetado** bajo incertidumbre en la demanda: se puede embotellar sin etiqueta (inventario WIP) y etiquetar recién cuando se conoce mejor la demanda de cada mercado. Se compara contra producir contra stock y contra pedido, siguiendo a Varas et al. (2018).

---

## Instalación

Requiere **Python 3.10+** y una **licencia de Gurobi** (la académica sirve) configurada en el equipo.

```bash
pip install -r requirements.txt
```

`matplotlib` solo se usa para los gráficos de `analisis_resultados.py`. Sin él igual se generan todas las tablas.

---

## Estructura del Repositorio

```
├── main.py                  # Pipeline principal (políticas + 32 combinaciones + re-planificación)
├── combinaciones_32.py      # Ranking de qué etiquetas conviene postergar (2^5 = 32 corridas)
├── pruebas_enteras.py       # Compara variables de cantidad continuas vs enteras
├── analisis_resultados.py   # Análisis de sensibilidad completo (tablas CSV + gráficos)
├── requirements.txt
├── data/
│   └── P12 Anexo A Datos.xlsx   # Anexo A original (referencia; el código ya no lo lee)
└── src/
    ├── data_loader.py       # Datos de la instancia P12, escritos en el código
    ├── core_model.py        # Formulación MS-MIP en Gurobi (modelo base = postergación)
    ├── policies.py          # Restricciones de las políticas contra pedido y contra stock
    ├── kpi_calculator.py    # KPIs esperados y desglose de producción por período
    └── replanificacion.py   # Re-planificación período a período y chequeo de no anticipatividad
```

*   **`src/data_loader.py`**: Contiene los parámetros de la instancia P12 del Anexo A (productos, capacidad de 84 h, estanques, tiempos, costos, árbol de 11 nodos con probabilidades condicionales y demandas). Calcula las probabilidades incondicionales y las cotas Big-M, valida los datos y los entrega con `load_data()`. El Excel de `data/` se mantiene como respaldo, pero no se lee.
*   **`src/core_model.py`**: `build_base_model(data)` arma el modelo base de **Programación Estocástica Multietapa (MS-MIP)**: balances de inventario WIP y producto terminado con atrasos, capacidad de la línea en horas, capacidad de estanques, activación de *set-ups* mediante *Big-M* y costo esperado ponderado por la probabilidad de cada nodo. El nodo 0 artificial fija las condiciones iniciales (o, al re-planificar, el estado con que cerró el período anterior).
*   **`src/policies.py`**: Funciones que agregan restricciones al modelo base para representar las políticas alternativas (`apply_mto_policy`, `apply_mts_policy`).
*   **`src/kpi_calculator.py`**: `extract_results` lee la solución de Gurobi y calcula costo, WIP, producto terminado, atrasos y *set-ups* esperados, además del tiempo de resolución.
*   **`src/replanificacion.py`**: Recorre cada uno de los 7 caminos del árbol resolviendo el subárbol desde el nodo que ocurrió, con horizonte decreciente (3, 2 y 1 períodos), y compara el costo esperado con el del modelo completo.

---

## Políticas de Producción Evaluadas

1.  **Postergación (modelo base):**
    Permite embotellar sin etiqueta (WIP) y etiquetar después desde ese inventario, además de producir acoplado. El modelo decide libremente cuándo embotellar y cuándo etiquetar.
2.  **Contra Stock (MTS):**
    Prohíbe el WIP y las operaciones de solo embotellar o solo etiquetar (`s_b = w_b = w_l = 0`). Todo se embotella y etiqueta acoplado y por adelantado, acumulando producto terminado para cubrir la demanda.
3.  **Contra Pedido (MTO, Varas et al. 2018):**
    Sin etiquetado separado (`z_l = 0`) y sin inventario de producto terminado (`s_bl = 0`). Como no puede sobrar nada, solo se produce lo que es seguro que se va a pedir y el resto queda como atraso que se cubre en la etapa siguiente.

---

## Ejecución

Todos los scripts se corren desde la raíz del repositorio.

### Pipeline principal

```bash
python main.py
```

Resuelve las tres políticas e imprime sus KPIs, corre el análisis de las 32 combinaciones y la re-planificación período a período. Genera:

*   `resultados_comparativos.csv`: costo y KPIs esperados de cada política.
*   `resultados_combinaciones.csv`: costo esperado de cada una de las 32 combinaciones de productos postergables.

Al final se muestra la verificación de **no anticipatividad**: el costo esperado re-planificando en cada período debe coincidir con el del modelo completo para las tres políticas.

Resultados de referencia con los datos del Anexo A:

| Política            | Costo esperado ($) |
|---------------------|-------------------:|
| Postergación        |            617.164 |
| Contra Stock (MTS)  |          1.918.302 |
| Contra Pedido (MTO) |      1.861.097.600 |

### Scripts complementarios

```bash
python combinaciones_32.py   # solo el ranking de las 32 combinaciones
python pruebas_enteras.py    # continuas vs enteras -> resultados_enteras.csv
```

`pruebas_enteras.py` resuelve cada política con las cantidades (`w`, `s`, `b`) continuas y enteras para justificar el uso de variables continuas. Con los datos actuales ambas versiones dan el mismo costo.

### Análisis de sensibilidad

```bash
python analisis_resultados.py                       # todos los bloques (~1 minuto)
python analisis_resultados.py --bloques base capacidad
python analisis_resultados.py --salida otra/carpeta --limite-segundos 120
```

Escribe tablas CSV (separador `;` y coma decimal, para abrir directo en Excel), gráficos PNG y un `ejecucion.json` con la configuración de la corrida en `results/analisis_validado/`. Los bloques disponibles son:

| Bloque       | Qué hace | Archivos |
|--------------|----------|----------|
| `base`       | Compara políticas, costo por camino, estadísticas de demanda, postergación por producto y detalle por nodo y período | `01_*` a `04_*` |
| `seleccion`  | Subconjuntos de etiquetas postergables (0 o al menos 2 etiquetas por vino) y límite de vinos, para cada nivel de capacidad | `05_*` |
| `capacidad`  | Políticas con 21, 42, 63 y 84 horas por período | `06_*` |
| `inventario` | Sensibilidad a los costos de inventario y a un límite de bodega | `07_*` |
| `factorial`  | Diseño factorial de variabilidad de la demanda (CV 10/30/50 %) × correlación (original, positiva, negativa) × capacidad | `08_*` |

En `07_capacidad_bodega.csv` aparecen modelos infactibles (estado Gurobi 3) cuando la bodega total es de 90.000 botellas o menos. Es esperable: la producción predefinida que cubre la demanda del nodo 1 ya supera ese límite.

---

## Limitaciones actuales y trabajo futuro: escenarios del bloque `factorial`

El Anexo A pide caracterizar el beneficio de la postergación combinando capacidad × variabilidad (CV de 10, 30 y 50 %) × correlación entre productos (positiva y negativa). Hoy el bloque `factorial` genera esas demandas con `demanda_transformada` (en `analisis_resultados.py`). El generador es correcto para lo que promete, pero lo que controla no es exactamente el escenario teórico que se quiere comparar. Queda pendiente para una siguiente etapa.

### Qué hace hoy y qué está bien

Para cada producto y período t ≥ 2: `demanda = media × (1 + CV × z)`, donde `z` tiene media 0 y varianza 1 ponderando por la probabilidad de los nodos del período.

*   **Media:** se mantiene la del Anexo en cada período.
*   **CV:** es exacto en cada período (es la definición del Anexo: desviación estándar como fracción de la media, por producto).
*   **Positiva:** todas las etiquetas de un vino usan el mismo `z` (correlación +1).
*   **Negativa:** se usan dos vectores ortonormales `a` y `b` rotados en ángulos iguales. La correlación queda en −1/(m−1), con m = número de etiquetas (−0,5 en el vino 1 y −1 en el vino 2), que es la correlación negativa común más extrema posible.
*   **Original:** escala las desviaciones del Anexo, así que mantiene sus correlaciones y la forma del árbol.
*   **Sin truncar:** si una demanda saliera negativa el código se detiene en vez de cortarla a 0, lo que cambiaría la media y el CV.

### Limitaciones

Los momentos se controlan **por período, mezclando todos los nodos**. En un modelo multietapa lo que importa es la incertidumbre que queda **al decidir en cada nodo**, o sea, la distribución de sus hijos.

1.  **El CV objetivo solo se cumple en la primera decisión (desde N1).** Desde los nodos del período 2, el CV condicional de la demanda del período 3 queda en 0,09–0,34 en "original", 0,10–0,13 en "positiva" y 0,02–0,21 en "negativa" (con CV objetivo de 30 %). Por eso la diferencia entre entornos mezcla el efecto de la correlación con un cambio en la incertidumbre del período 3.
2.  **"Negativa" no es negativa en la segunda decisión.** Desde N3 la correlación entre (1,1) y (1,2) es −0,15, y desde N4 es +1.
3.  **En positiva y negativa se pierden los estados del árbol.** `z` sale de un coseno, y con probabilidades simétricas (0,3 / 0,4 / 0,3) los nodos "Alta" y "Baja" quedan con la misma demanda (N2 = N4 y N7 = N9), y "Media" queda como la más baja.
4.  **Se pierde la relación entre períodos.** La demanda del período 3 no depende de la del nodo padre: por ejemplo, N11 (Baja → Baja) queda como el nodo con más demanda.
5.  **La correlación entre vinos no se controla.** La primera etiqueta de cada vino usa el mismo `z`, así que (1,1) y (2,1) quedan con correlación +1. En el Anexo es 0,97, por lo que el efecto es menor.

Dos observaciones sobre los datos del Anexo que conviene tener presentes:

*   **CV del caso base:** el caso base ya tiene un CV de ~33–56 % en el período 2, más cerca del nivel alto que del bajo.
*   **Correlación del vino 1:** el Anexo dice que el vino 1 tiene correlaciones negativas, pero en los datos (1,1) y (1,3) tienen correlación +1. En el vino 1 las correlaciones son mixtas.

### Qué habría que hacer

Generar la demanda **rama por rama**: para cada nodo padre `n`, construir la demanda de sus hijos con

*   **Media:** la media condicional del Anexo para esos hijos, para mantener la relación entre períodos (después de "Alta" siguen demandas altas).
*   **CV:** el objetivo, exacto pero **condicional** a estar en `n`.
*   **Correlación:** la pedida entre etiquetas del mismo vino, también condicional a `n`.
*   **Positiva y negativa:** un `z` que respete el orden Alta > Media > Baja (al menos para la primera etiqueta de cada vino).
*   **Original:** el mismo tratamiento rama por rama, escalando las desviaciones del Anexo dentro de cada grupo de hermanos, para que los tres entornos tengan la misma incertidumbre en cada decisión y solo cambie la correlación.

Restricción del árbol que hay que declarar: los nodos con 2 hijos (N2 y N4) solo admiten correlaciones de ±1. Ahí el vino 2 puede quedar en −1, pero el vino 1 (3 etiquetas) no puede tener las tres correlaciones negativas a la vez. Una opción es dejar (1,1) en −1 con (1,2) y (1,3), lo que deja (1,2) con (1,3) en +1. Se podría evitar con un árbol de al menos 3 hijos por nodo.

Cuando se implemente, cambian solo las tablas `08_*`. `main.py` y los demás bloques no usan este generador. Un prototipo preliminar (no incluido en el repositorio) dio:

*   **Costos:** suben entre 7 y 25 % en "original" y "negativa", y hasta 90 % en "positiva" (antes el período 3 tenía menos incertidumbre que la pedida).
*   **Ahorro frente a contra stock:** casi no cambia (~33 % positiva, ~65 % original, ~91 % negativa a 84 h).
*   **Orden de los entornos:** "negativa ahorra más que original y original más que positiva" pasó de cumplirse en 9 a 11 de las 12 combinaciones de CV y capacidad.

Es decir, se esperan los mismos resultados cualitativos con números más defendibles.
