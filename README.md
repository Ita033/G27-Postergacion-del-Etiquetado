# G27-Postergacion-del-Etiquetado

Modelo de Programación Estocástica Multietapa (MS-MIP) para evaluar políticas de postergación de etiquetado en una viña exportadora como Proyecto de Capstone (ICS2122).

Este proyecto implementa un modelo de optimización matemática para evaluar los beneficios de la **postergación del etiquetado** en una viña orientada a la exportación bajo incertidumbre en la demanda.

---

## Estructura del Repositorio

El proyecto está diseñado bajo una arquitectura modular en Python:

*   **`data/`**: Contiene el archivo de datos oficial (`P12 Anexo A Datos.xlsx`) con la configuración de la línea, costos, tiempos y el árbol de escenarios de demanda.
*   **`src/data_loader.py`**: Script de extracción dinámica y estructuración de parámetros desde las hojas del archivo Excel del Anexo A.
*   **`src/core_model.py`**: Contiene la formulación matemática base del modelo de **Programación Estocástica Multietapa (MS-MIP)** en Gurobi, incorporando balances de inventario WIP, producto terminado, restricciones de capacidad y activación de *set-ups* mediante *Big-M*.
*   **`src/policies.py`**: Módulo que inyecta restricciones lógicas al modelo base para simular y comparar políticas de producción alternativas (MTO y MTS).
*   **`src/kpi_calculator.py`**: Extrae la solución óptima de Gurobi, calcula los costos esperados ponderados por la probabilidad de cada nodo, registra los tiempos de resolución del *solver* y consolida los KPIs.
*   **`main.py`**: Script orquestador principal que ejecuta secuencialmente los escenarios de evaluación y genera la tabla comparativa de resultados.

---

## Políticas de Producción Evaluadas

El modelo contrasta tres estrategias operativas para la línea de envasado:

1.  **Postergación (Modelo Base / Híbrido Óptimo):** 
    Permite mantener inventario de botellas llenas sin etiquetar (WIP) como inventario en proceso. El sistema decide libremente cuándo embotellar y posterga el etiquetado hasta conocer de manera más precisa los requerimientos de los distintos mercados, minimizando costos y evitando riesgos de asignación errónea.
2.  **Make-to-Stock (MTS - Contra Stock Tradicional):** 
    Prohíbe el uso de inventario WIP y operaciones desacopladas. Todo el volumen de producción se embotella y etiqueta de forma estrictamente acoplada y anticipada según pronóstico, acumulando stock de producto terminado para asegurar la demanda.
3.  **Make-to-Order Realista (MTO - Make-to-Forecast):** 
    Prohíbe el almacenamiento de inventario intermedio (WIP) y de producto terminado entre períodos. La producción acoplada en cada nodo se ajusta al valor esperado (promedio ponderado) de la demanda futura, reflejando el comportamiento ante la incertidumbre cuando no se almacena inventario.

---

## Ejecución

Asegúrate de tener instaladas las dependencias necesarias (`pandas`, `openpyxl`, `gurobipy`) y tu licencia académica de Gurobi configurada. Ejecuta el pipeline completo desde la terminal con:

```bash
python main.py