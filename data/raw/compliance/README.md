# Datos de entrada de compliance

## `evidencia_sintetica.csv` (SINTÉTICO, para demo y tests)

Formato acordado (una fila por caso):

| columna | obligatoria | formato | significado |
|---|---|---|---|
| `obligacion_codigo` | sí | `BAN-004` (categoría) o `BAN-004-05` (obligación concreta) | qué obligación evidencia la fila |
| `sujeto_id` | sí | texto | identificador interno del caso (ROS, registro, capacitación…) |
| `fecha_evento` | sí | `AAAA-MM-DD` | hecho que dispara el plazo (p. ej. calificación de la operación como sospechosa) |
| `fecha_cumplimiento` | no | `AAAA-MM-DD` | cuándo se cumplió; vacío = pendiente |
| `fecha_corte` | no | `AAAA-MM-DD` | corte de la evidencia; la `fecha_corte` del reporte tiene prioridad |

Con un código de categoría, la fila se evalúa contra **cada obligación validada** de esa categoría. Para apuntar a una sola, usa su código concreto (`BAN-004-05`).

## `feriados.csv`

Es una **lista de ejemplo** de feriados nacionales del Perú, usada para los plazos en días hábiles. **No es fuente oficial:** verifícala y actualízala con el calendario publicado en El Peruano antes de usarla en serio.
