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

## Escenarios del bloque `factorial`

El Anexo A pide caracterizar el beneficio de la postergación combinando capacidad (21, 42, 63 y 84 h) × variabilidad (CV de 10, 30 y 50 %) × correlación entre productos. El bloque `factorial` genera esas demandas con `demanda_transformada` (en `analisis_resultados.py`) y resuelve las tres políticas y las combinaciones de etiquetas postergables en los 36 escenarios.

### Cómo se generan las demandas (rama por rama)

El modelo decide parado en un nodo, mirando a sus hijos. Por eso lo que se controla es la demanda de **los hijos de cada nodo**, no la de todo el período mezclado. Para cada nodo `n` y cada producto:

```
demanda_hijo = m × (1 + CV × z_hijo)
```

*   **`m`:** media de los hijos de `n` en el Anexo A (media condicional). Mantiene la relación entre períodos (después de "Alta" siguen demandas altas) y la media de cada período.
*   **`z`:** tiene media 0 y varianza 1 entre los hijos de `n`, ponderando por la probabilidad condicional. Así el CV de los hijos de cada nodo es exactamente el pedido (es la definición del Anexo: desviación estándar como fracción de la media, por producto). El código lo verifica en cada escenario.

Según el entorno, `z` sale de:

*   **Original:** las desviaciones del Anexo entre los hijos de `n`. Se mantienen sus correlaciones.
*   **Positiva:** un factor que sigue los estados (Alta > Media > Baja), igual para todas las etiquetas. Correlación +1.
*   **Negativa:** las etiquetas de un vino se reparten en ángulos iguales entre dos factores sin correlación entre ellos. Correlación −1/(m−1), con m = número de etiquetas: −0,5 en el vino 1 y −1 en el vino 2. Es la correlación negativa común más extrema posible, porque Var(Σz) = m + m(m−1)ρ ≥ 0.

Si alguna demanda saliera negativa el código se detiene en vez de cortarla a 0 (cortar cambiaría la media y el CV). Las tablas `08_validacion_cv` y `08_validacion_correlacion` muestran el CV y la correlación de los hijos de cada nodo.

### Limitaciones que quedan

*   **Nodos con 2 hijos (N2 y N4):** con dos escenarios cualquier correlación es +1 o −1. Ahí el vino 2 queda en −1, pero el vino 1 (3 etiquetas) no puede tener sus tres correlaciones negativas a la vez: (1,1) queda en −1 con (1,2) y (1,3), y (1,2) con (1,3) en +1. Se evitaría con un árbol de al menos 3 hijos por nodo.
*   **Correlación entre vinos:** en positiva y negativa la primera etiqueta de cada vino sigue los estados del árbol, así que (1,1) y (2,1) quedan con correlación +1 (en el Anexo es 0,97).
*   **Las probabilidades y los estados del árbol** son los del Anexo en todos los escenarios; solo cambian las demandas.

Dos observaciones sobre los datos del Anexo:

*   **CV del caso base:** el caso base tiene un CV de ~33–56 % en el período 2, más cerca del nivel alto que del bajo.
*   **Correlación del vino 1:** el Anexo dice que el vino 1 tiene correlaciones negativas, pero en los datos (1,1) y (1,3) tienen correlación +1. En el vino 1 las correlaciones son mixtas.

Hasta la versión `baac601` la demanda se generaba por período (mezclando todos los nodos), lo que solo cumplía el CV en la primera decisión y desordenaba los estados del árbol. Con la generación rama por rama los costos de postergación subieron entre 7 y 25 % en "original" y "negativa" y hasta 90 % en "positiva", pero el ahorro porcentual frente a contra stock casi no cambió.

### Conclusiones

Las 468 corridas del bloque (36 escenarios × 3 políticas y 10 combinaciones de etiquetas) terminaron en el óptimo (gap 1e-8) y la selección de etiquetas quedó certificada en todos los escenarios. Ahorro de postergar frente a contra stock (MTS):

| Capacidad | Correlación negativa | Original (Anexo) | Correlación positiva |
|-----------|---------------------:|-----------------:|---------------------:|
| 84 h      | 91–92 %              | 64–65 %          | 33–34 %              |
| 63 h      | 90–99,9 %            | 63–99,5 %        | 33–99,4 %            |
| 42 h      | 88–95 %              | 66–91 %          | 40–84 %              |
| 21 h      | 15 %                 | 15 %             | 13–15 %              |

1.  **Postergar siempre es lo más barato.** Gana en los 36 escenarios. Está garantizado, porque contra stock y contra pedido son el modelo de postergación con más restricciones. Contra pedido es siempre la peor política (cientos o miles de millones en atrasos).
2.  **Con capacidad holgada (84 h), el ahorro depende de la correlación y casi nada del CV.** El ahorro es ~92 % con correlación negativa, ~65 % con la del Anexo y ~33 % con positiva, para cualquier CV. Una botella sin etiquetar sirve para cualquier etiqueta de su vino: si las demandas se compensan, el total del vino es estable y el WIP cubre lo que se pida (*risk pooling*). Si suben y bajan juntas, esa ventaja casi desaparece. Un CV más alto sube los costos de todas las políticas en proporción parecida, así que el ahorro porcentual se mantiene.
3.  **Con capacidad intermedia (63 h), postergar protege el servicio.** Postergación no tiene atrasos en ningún escenario de 63 u 84 h. Contra stock sí atrasa pedidos con 63 h cuando la demanda varía mucho: con correlación positiva desde CV 30 %, y en los tres entornos con CV 50 %. En esos casos su costo se dispara y el ahorro de postergar llega a 91–99,9 %. Para postergación, bajar de 84 a 63 h cuesta poco (entre 1 y 14 % más).
4.  **Con capacidad ajustada (42 h), todas las políticas atrasan pedidos, pero postergación mucho menos.** Por ejemplo, con CV 30 % y la correlación del Anexo atrasa 17.740 botellas·período, frente a 75.955 de contra stock. Aquí sí importa el CV: con correlación positiva el ahorro cae de 84 % (CV 10 %) a 40 % (CV 50 %).
5.  **Con 21 h la línea no da abasto.** Todas las políticas cuestan entre $3.000 y $4.100 millones, con la línea a ~100 % y solo ~55–59 % de la demanda atendida a tiempo. El ahorro de postergar se reduce a ~15 % y ya no depende de la correlación: falta capacidad, no flexibilidad.
6.  **Cuánto se posterga depende del entorno.** Con 84 h y correlación negativa se etiqueta el 100 % desde el WIP. Con correlación positiva y CV 50 % baja a 77 %. Con CV 50 %, el WIP esperado pasa de ~19.000 botellas·período con correlación negativa a ~164.000 con positiva: cuando las etiquetas no se compensan, hay que guardar más botellas sin etiquetar para cubrir las variaciones.
7.  **Qué etiquetas postergar (con 84 h, como % del costo sin postergar):**
    *   **Correlación negativa:** el beneficio está en postergar todo. Con 2 etiquetas conviene el vino 2 (correlación −1): 63 %. Con 3, el vino 1 completo: 45 %. Con 4: 29 %. Con las 5: 8–9 %. La última etiqueta, la que completa los dos vinos, todavía aporta mucho (de 29 % a 8–9 %).
    *   **Original:** con 2 etiquetas conviene (1,1) y (1,2), que en el Anexo tienen correlación −0,99. Esas dos dejan el costo en 56 % y las 5 en 35–36 %.
    *   **Positiva:** cada etiqueta agrega un poco: 84 % con 2, 79 % con 3, 72 % con 4 y 67 % con 5.
    *   **Capacidad intermedia:** con 63 h y CV 50 %, postergar solo 2 etiquetas ya evita casi todos los atrasos de contra stock y baja el costo a ~1 % del de no postergar en los entornos original y negativa. Con correlación positiva hacen falta 4 etiquetas para llegar a ese nivel.
