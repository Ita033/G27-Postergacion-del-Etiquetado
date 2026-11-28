# G27-Postergacion-del-Etiquetado

Modelo de programación estocástica multietapa (MS-MIP) para evaluar la **postergación del etiquetado** en una viña exportadora con demanda incierta. Proyecto Capstone ICS2122, Grupo 27.

---

## Estructura del repositorio

| Archivo | Qué hace |
|---|---|
| `src/data_loader.py` | Datos de la instancia P12 (Anexo A) escritos en el código. Calcula las probabilidades de los nodos y las cotas Big-M. No lee el Excel. |
| `src/core_model.py` | Modelo base con postergación en Gurobi: balances de inventario sin etiqueta (WIP), terminado y atrasos, capacidad, estanques y set-ups. |
| `src/policies.py` | Restricciones de los casos base: contra stock (MTS) y contra pedido sin stock (MTO). |
| `src/kpi_calculator.py` | KPI de la comparación de políticas de `main.py`. |
| `src/replanificacion.py` | Replanificación período a período en los 7 caminos del árbol (verificación de no anticipatividad). |
| `main.py` | Resuelve las tres políticas y la replanificación por caminos. |
| `pruebas_enteras.py` | Compara el modelo con cantidades continuas y enteras. |
| `analisis.py` | Análisis de sensibilidad y comparaciones adicionales. |
| `escalamiento.py` | Tiempos de resolución con 6, 30 y 150 etiquetas y horizontes de 3 a 8 semanas. |
| `graficos/graficos_informe.py` | Figuras D.1 y D.2 del informe (PDF y PNG en `graficos/informe/`). |
| `graficos/graficos.py` | Figuras de la presentación y Figura D.5 del informe (PNG en `graficos/presentacion/`). |
| `data/P12 Anexo A Datos.xlsx` | Datos originales del Anexo A, como respaldo. |

---

## Políticas comparadas

1. **Postergación (modelo base):** se puede embotellar sin etiqueta, guardar ese inventario y etiquetarlo después, cuando se conoce la demanda.
2. **Contra stock (MTS):** no se posterga. Todo se embotella y etiqueta junto, y se puede guardar producto terminado.
3. **Contra pedido sin stock (MTO):** no se posterga ni se guarda inventario entre períodos. Lo que no se cubre queda atrasado.

`analisis.py` compara además con una política híbrida (cada etiqueta elige MTS o MTO) y con un plan estático (las mismas decisiones en todos los nodos de un período).

---

## Instalación

Se usó Python 3.11 y Gurobi 13.0.3, con licencia académica.

```bash
pip install -r requirements.txt
```

## Ejecución

Todos los comandos se ejecutan desde la raíz del proyecto.

| Comando | Qué hace | Salida |
|---|---|---|
| `python main.py` | Compara las tres políticas y replanifica por caminos | `resultados_comparativos.csv`; la replanificación se muestra en consola |
| `python pruebas_enteras.py` | Continuas vs. enteras | `resultados_enteras.csv` |
| `python analisis.py` | Todos los análisis. Se puede correr uno solo con `capacidad`, `barrido`, `factorial`, `etiquetas`, `benchmarks`, `whatif` o `computo` | `out_1` a `out_6` |
| `python escalamiento.py` | Escalamiento con 6, 30 y 150 etiquetas. Puede tardar horas (límite de 2000 s por instancia) | `out_7_escalamiento_realista.xlsx` |
| `python graficos/graficos_informe.py` | Figuras D.1 y D.2 | `graficos/informe/` |
| `python graficos/graficos.py` | Figuras de la presentación y Figura D.5 | `graficos/presentacion/` |

---

## Qué archivo respalda cada resultado del informe

| Resultado | Archivo |
|---|---|
| Tabla 5.1 | `resultados_comparativos.csv` (costos, inventarios, atrasos, set-ups) y `out_4` y `out_1` con 84 h (servicio, atraso terminal, utilización) |
| Tabla 5.2 y §4.5.1 (no anticipatividad) | Salida en consola de `main.py` |
| Tabla 5.3 | `out_4_benchmarks_hibrido_vms.xlsx` |
| Tabla 5.4 y Figura D.2 | `out_1b_barrido_capacidad.xlsx` (hoja `Barrido_3h`) |
| §5.2.2 | `out_1_capacidad_y_saturacion.xlsx` (hoja `Niveles_Anexo_A`) |
| Figura D.1 y §5.2.1 | `out_2_factorial_K_CV_Corr.xlsx` |
| Tablas 5.5, 5.6 y D.1 | `out_3_etiquetas_y_tasa_sku.xlsx` (hoja `Todas_Combinaciones`) |
| Figura D.3 | `out_3_etiquetas_y_tasa_sku.xlsx` (hoja `Mejores_por_K_y_PL`) |
| Tabla 5.7 y Figura D.4 | `out_5_whatif_costos_y_borde.xlsx` |
| Tabla 5.8 y Figura D.5 | `out_7_escalamiento_realista.xlsx` |
| Tiempos de §6.1 | `out_6_escalamiento_computacional.xlsx` |

### Notas

- **Tabla 5.5:** elige la combinación más barata con *hasta* k etiquetas. Se obtiene de la hoja `Todas_Combinaciones`. La hoja `Mejores_por_K_y_PL` elige con *exactamente* k etiquetas (Figura D.3).
- **Tasa de postergación:** botellas etiquetadas desde el inventario sin etiqueta en los períodos 2 y 3, divididas por la demanda de esos períodos. Mide volumen, no entregas, así que puede superar 100%.
- **Escalamiento:** las instancias son sintéticas (unas 100.000 botellas por semana repartidas entre las etiquetas). Con 30 y 150 etiquetas, los tiempos de set-up se reducen a 1/3 y 1/15 para que la línea siga siendo factible. Gurobi se detiene con un gap de 0,5%.
- **Resultados sin código en el repositorio:** no se guardan las horas esperadas, la holgura mínima ni los inventarios máximos de la Tabla 5.1, ni los datos por nodo de la Figura C.1. Las Figuras C.1, D.3 y D.4 no tienen script para generarlas.
- La hoja `Barrido_Fino_4h` de `out_1` es de una versión anterior y no se usa.
