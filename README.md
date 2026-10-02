# Dash_Nivelacion_MPME

Tablero de Balance de Inventario de Materias Primas y Material de Empaque
vs Politicas MRP, por compania (Global / Super / Trululu / Bianchi).

## Estado actual

- `app/styles.py` y `app/components.py`: paleta, header, tarjetas, pildoras
  y tabla de detalle del mockup.
- `app/logic_inventario.py`: logica del Cuadro 1 (Inventario y Necesidad),
  con datos sinteticos con la misma forma ancha de la consulta real.
- `app/data.py`: conexion a Snowflake (llave privada .p8) y la consulta
  consolidada real (`QUERY_INVENTARIO_NECESIDAD`). Aun no esta conectada a
  `main.py` (main sigue usando los datos sinteticos de `logic_inventario`).
- `app/main.py`: Cuadro 1 con filtros en linea (Orden, Semana, Grupo).

Pendiente: adaptar `construir_filas_inventario_necesidad` para leer las
columnas reales de `cargar_inventario_necesidad()` en vez de los datos
sinteticos, y el segundo cuadro.

## Correr localmente

```bash
cd Dash_Nivelacion_MPME
pip install -r requirements.txt
streamlit run app/main.py
```

## Configuracion pendiente antes de desplegar

- El `.env` con las credenciales de Snowflake es el mismo `.env` general
  de todos los proyectos del usuario (ruta fija en `app/data.py`).
- Variables esperadas: `SF_USER`, `SF_ACCOUNT`, `SF_PRIVATE_KEY_PATH`,
  `SF_ROLE`, `SF_WAREHOUSE`.
