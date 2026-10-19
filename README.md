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
├── analisis_resultados.py   # Tablas de detalle de los resultados (CSV + gráficos)
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

### Análisis de resultados

```bash
python analisis_resultados.py                       # los dos bloques (unos segundos)
python analisis_resultados.py --bloques capacidad
python analisis_resultados.py --salida otra/carpeta --limite-segundos 120
```

Escribe tablas CSV (separador `;` y coma decimal, para abrir directo en Excel), gráficos PNG y un `ejecucion.json` con la configuración de la corrida en `results/analisis_validado/`. Los bloques disponibles son:

| Bloque      | Qué hace | Archivos |
|-------------|----------|----------|
| `base`      | Compara políticas, costo por camino, estadísticas de demanda (CV y correlaciones), postergación por producto y detalle por nodo y período | `01_*` a `04_*` |
| `capacidad` | Políticas con 21, 42, 63 y 84 horas por período | `06_*` |

### De dónde sale cada resultado de la presentación (entrega 2)

| Lámina | Contenido | Se obtiene de |
|--------|-----------|---------------|
| 16 | Correlación entre etiquetas | `03_correlaciones.csv`, filas del período 3 (nodos finales, ponderados por probabilidad) |
| 35–36 | Costo, ahorro, set-ups e inventarios de cada política | `main.py` → `resultados_comparativos.csv` (también en `01_politicas.csv`) |
| 35 | Nivel de servicio (100 % / 69 % / 100 %) | `01_politicas.csv`, columna `servicio_fifo_pct` (coincide con la fórmula de la lámina 46) |
| 37 | Costo de los caminos 1–2–6 y 1–4–11 | Re-planificación de `main.py` (`src/replanificacion.py`), también en `02_caminos.csv` |
| 38 | 32 combinaciones de postergación | `main.py` / `combinaciones_32.py` → `resultados_combinaciones.csv` |
| 39 | CV de la demanda del período 2 por etiqueta y por vino | `03_demanda_por_periodo.csv` |
| 40 | Tiempo de resolución y no anticipatividad | `main.py` (verificación al final de la re-planificación) |
| 49 | Ahorro y atraso según la capacidad de la línea | `06_capacidad.csv` |
