# Tablero de Nivelación y Ventas Internas (MP y ME)

Este proyecto es una aplicación web interactiva desarrollada en **Streamlit**. Su propósito principal es presentar el balance de inventario de **Materias Primas (MP)** y **Material de Empaque (ME)** contrastado contra las políticas de necesidad MRP y entregas pendientes de órdenes de compra, facilitando la toma de decisiones sobre nivelaciones y ventas internas entre los diferentes centros físicos y razones sociales (Super, Trululu, Bianchi, Oka Loka, etc.).

## 🚀 Características Principales

- **Conexión Directa a Snowflake:** Extrae en tiempo real el consolidado de inventarios, necesidades MRP y entregas de OC mediante autenticación segura con llave privada (`.p8`).
- **Pestaña 1 - Inventario y Necesidad:** Visualización consolidada por lugar físico o razón social, con filtros dinámicos de semana (actual, próxima, actual+2), grupo de materiales, y modo (actual vs. simulado).
- **Pestaña 2 - Nivelaciones y Ventas Internas:** Motor de cálculo que sugiere traslados entre centros para optimizar el inventario (superávit vs. déficit), clasificando automáticamente entre "Nivelación" y "Venta Interna".
- **Buscador Integrado:** Funcionalidad de búsqueda en tiempo real para filtrar materiales por ID o Nombre en ambos cuadros.
- **Rendimiento Optimizado:** Uso intensivo de caché (`@st.cache_data`) en la lógica de negocio para una experiencia de usuario rápida y fluida sin reprocesamientos innecesarios de datos pesados.
- **UI/UX Corporativo:** Diseño de cabecera "Hero Header", componentes modulares, alineación optimizada de datos numéricos y manejo elegante de estados vacíos.

## 📁 Estructura del Proyecto

```text
/
├── app/
│   ├── main.py               # Punto de entrada de la aplicación Streamlit
│   ├── data.py               # Capa de datos y conexión a Snowflake
│   ├── logic_inventario.py   # Lógica de negocio (simulación y cálculos de traslados)
│   ├── components.py         # Componentes visuales HTML reutilizables (tarjetas, tablas)
│   ├── styles.py             # Reglas CSS globales y paleta de colores corporativos
│   └── static/               # Archivos estáticos (ej. logo corporativo)
├── requirements.txt          # Dependencias de Python
├── .gitignore                # Archivos ignorados por Git
└── README.md                 # Documentación del proyecto
```

## ⚙️ Requisitos y Configuración Local

1. **Clonar el repositorio y ubicarte en la raíz.**
2. **Instalar las dependencias:**
   ```bash
   pip install -r requirements.txt
   ```
3. **Configuración de Variables de Entorno:**
   El proyecto requiere un archivo `.env` en la raíz (u otra ruta accesible definida globalmente) con las siguientes variables para la conexión a Snowflake:
   ```env
   SF_USER=tu_usuario
   SF_ACCOUNT=tu_cuenta
   SF_PRIVATE_KEY_PATH=ruta/a/tu/llave_privada.p8
   SF_ROLE=tu_rol
   SF_WAREHOUSE=tu_warehouse
   ```

## ▶️ Ejecución

Para iniciar el tablero localmente, ejecuta el siguiente comando:

```bash
streamlit run app/main.py
```

La aplicación se abrirá automáticamente en tu navegador por defecto (normalmente en `http://localhost:8501`).
