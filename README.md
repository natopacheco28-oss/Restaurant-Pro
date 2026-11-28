# Restaurante Pro

**Punto de venta y administración para restaurantes en Windows** — con la misma
filosofía portable de ABCell Pro: un ejecutable, los datos junto a él y
respaldos locales. Interfaz **Fluent Design** (PySide6 + PySide6-Fluent-Widgets)
sobre **SQLite**.

![Build](https://github.com/natopacheco28-oss/Restaurant-Pro/actions/workflows/build.yml/badge.svg)

---

## ✨ Características

### 🧾 1. Caja (punto de venta)
- Cuadrícula de productos por categoría con búsqueda rápida.
- Carrito con cantidades, **notas por producto** («sin cebolla»), descuento
  (monto o %) y propina opcional (con % sugerido configurable).
- Tipo de pedido: **Mesa / Para llevar / A domicilio** (con cliente).
- Métodos de pago: **efectivo, tarjeta, transferencia**, con cálculo de cambio.
- **Apertura y cierre de caja (corte)**: fondo inicial, ventas por método de
  pago, efectivo esperado y diferencia.
- Ticket impreso al cobrar y **reimpresión de tickets anteriores**.
- El inventario se descuenta automáticamente por las **recetas** ligadas.

### 📚 2. Catálogo
- Productos y categorías: nombre, precio, categoría, imagen opcional
  (se copia a `data/imgs`) y disponibilidad.
- **Receta opcional**: insumos del inventario que consume cada producto.
- Alta/edición/baja con confirmación y validación (nombre no vacío,
  precio ≥ 0, sin duplicados).
- Las tablas y listas se actualizan al instante **sin reiniciar** el programa.

### 📦 3. Inventario (almacén con 5 vistas)
- **Insumos**: unidad, stock, mínimo, **ideal de reposición**, costo,
  proveedor e insignias de estado (Normal / Bajo / Agotado).
- **Kardex inmutable**: fecha/hora, insumo, tipo (entrada, salida, merma o
  desperdicio, ajuste, consumo por venta), cantidad, costo unitario, **lote**,
  proveedor, motivo y usuario. Los movimientos **no se editan ni se borran**
  (solo se corrigen con un ajuste). Filtrable por insumo, tipo, fechas y
  motivo, con **exportación a Excel/CSV**.
- **Por caducar**: cada entrada lleva **lote** y **fecha de caducidad**
  opcionales; días de aviso por insumo (o el global de Ajustes). Las salidas
  descuentan **primero el lote que caduca antes (PEPS/FEFO)**. Semáforo
  vencido (rojo) / próximo (naranja) / vigente (verde) con acciones rápidas:
  dar salida o marcar merma con su motivo.
- **Sin movimiento**: insumos con existencia sin salidas en X días
  (configurable, 30 por defecto) con días estancados, **valor inmovilizado**
  y sugerencia (promoción, menú del día, platillo especial o merma).
- **Compras**: lista de compras sugerida (stock ideal − stock, o mínimo × 2),
  editable, agrupada por proveedor con costo estimado, exportable a
  **Excel/CSV/PDF o impresora de tickets**, con historial y estado
  (pendiente/comprada) y **conversión de la lista en entradas con un clic**.
- Las entradas y salidas manuales requieren la clave maestra (modo edición,
  una vez por sesión).

### 🔔 Notificaciones del almacén
- Al abrir el programa y luego cada cierto tiempo (QTimer configurable,
  30 min por defecto) revisa stock bajo, por caducar/vencidos y sin movimiento.
- **Campana con contador** en la barra lateral (encima del engrane de
  Ajustes) que abre el centro de notificaciones (lista de alertas con «Ver» → va directo al insumo,
  «Posponer» 1 hora y «Atendida»).
- Resumen automático al abrir («Hoy: 3 por caducar, 5 en stock bajo»).
- Una alerta **atendida no vuelve** mientras la condición no cambie; una
  **pospuesta** reaparece al expirar.
- Opcional: **notificación de Windows (bandeja)** si el programa está
  minimizado.

### 📊 4. Estadísticas
- Ventas por día/semana/mes con filtro por **rango de fechas** (preajustes o
  fechas personalizadas).
- Productos más vendidos, ventas por método de pago, **ticket promedio** y
  ventas por hora.
- **Almacén**: tarjetas de valor del inventario, stock bajo, por caducar,
  merma del periodo y valor inmovilizado; gráficas de **merma por motivo**,
  **consumo por insumo** y **movimientos del kardex por día**.
- Gráficas **QtCharts** con estilo Fluent y modo claro/oscuro automático.
- **Exportar a Excel** (multi-hoja) **o CSV**.

### 🔐 Seguridad — clave maestra
- Se configura en el **primer arranque** con un asistente de bienvenida
  (pedir y confirmar clave, entrada oculta).
- Se guarda **solo como hash PBKDF2-HMAC-SHA256 con sal** (200 000
  iteraciones) — nunca en texto plano.
- Para **editar Catálogo o Inventario** se pide la clave **una sola vez por
  sesión**, con indicador visible de «modo edición activo» y botón para
  bloquear de nuevo. Se bloquea automáticamente al cerrar el programa.
- Menú **oculto con `Ctrl+P`** (sin botón visible que lo delate) con dos
  opciones: cambiar la clave maestra y **borrar base de datos y órdenes** —
  reinicia ventas, órdenes, sesiones de caja, kardex, lotes, listas de
  compras y alertas atendidas (el stock vuelve a 0), conservando catálogo,
  insumos y ajustes. Pide escribir «BORRAR» para confirmar y crea un
  **respaldo de seguridad** antes de eliminar.
- Límite de intentos fallidos con **retraso progresivo** (1s → 2s → 4s… máx 60s).

> ¿Olvidaste la clave? No existe recuperación automática (por diseño). Para
> reconfigurar, cierra el programa y borra `data/security.json`; tus datos no
> se pierden, solo la clave.

### 💾 Datos portables
- Toda la información vive **junto al .exe**:

  ```
  RestaurantePro/
  ├── RestaurantePro.exe
  ├── data/
  │   ├── restaurante.db      ← base de datos SQLite
  │   ├── config.json         ← configuración (Ajustes)
  │   ├── security.json       ← hash de la clave maestra
  │   ├── imgs/               ← logo personalizado e imágenes de productos
  │   └── logs/               ← registros rotativos
  └── backups/                ← respaldos automáticos y manuales
  ```

- La ruta se detecta con `sys.executable` cuando está empaquetado, **no** con
  el directorio de trabajo.
- Si no hay permisos de escritura se muestra un mensaje claro sugiriendo mover
  el programa a `C:\RestaurantePro`.
- **Respaldo automático al cerrar** con fecha y hora en el nombre
  (`backup_20250101_120000_auto.db`), conservando los últimos **10**.
- Botones **«Respaldar ahora»** y **«Restaurar respaldo»** (con confirmación
  y copia previa de la base actual). Carpeta de respaldos configurable.
- **Migraciones de esquema versionadas** (`PRAGMA user_version`) para
  actualizar sin perder datos. La v2 añadió lotes con caducidad, kardex
  extendido, stock ideal, listas de compras y alertas atendidas — sin tocar
  los datos existentes.

### ⚙️ Ajustes
- Datos del restaurante: nombre, eslogan, teléfono, dirección, **RFC/dato
  fiscal**, redes sociales, **logo con vista previa**, políticas.
- Moneda, **porcentaje de impuesto**, **propina sugerida**, mensaje al pie del
  ticket — todo se refleja en los tickets impresos.
- **Inventario y alertas**: días de aviso de caducidad por defecto, días para
  considerar «sin movimiento», frecuencia de revisión de alertas, activar o
  desactivar cada tipo de notificación y notificaciones de Windows.
- Tema **claro / oscuro / automático** y **color de acento**.
- Datos y respaldos (carpeta configurable, respaldar/restaurar, abrir carpeta).

### 🖨️ Impresión de tickets
- Papel **58 mm (32 caracteres)** o **80 mm (48 caracteres)**, seleccionable.
- Impresión por la impresora de Windows vía **win32print RAW + ESC/POS**
  (logo en blanco y negro rasterizado, corte de papel y apertura de cajón
  opcionales) con **alternativa por QPrinter** y elección desde la lista de
  impresoras instaladas.
- Ticket con datos del restaurante, folio, fecha, mesero, tipo de pedido,
  productos alineados (cantidad × nombre + importe), notas, subtotal,
  impuesto, propina, total, pago, cambio y pie personalizado.
- Impresión **directa y sin ventanas** (impresora configurada →
  predeterminada de Windows → primera disponible), con **detección
  automática de papel 58/80 mm** y realineado del ticket al ancho real
  (sin recortes ni impresión «en escalera»). Botón **«Imprimir ticket de
  prueba (demo)»** con datos de demostración y **vista previa**.

### 🎨 Identidad visual
- Usa los archivos propios `assets/logo.png` y `assets/icon.ico` (generados a
  partir del logo oficial). El splash de arranque muestra el logo centrado
  sobre fondo limpio con **animación de aparición** (bootlogo). En el
  primer arranque el bootlogo **se cierra solo** antes del asistente, para
  que la ventana de configuración quede libre para escribir.

---

## 🚀 Desarrollo

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt -r requirements-dev.txt
python main.py
```

Requisitos: **Python 3.11+**. En el primer arranque el asistente pedirá crear
la clave maestra.

### Pruebas

```bash
pytest                          # 86 pruebas unitarias (servicios, almacén, seguridad, BD, tickets, respaldos)
python scripts/smoke_test.py    # importa todos los módulos de la app
```

### Estructura del código

```
main.py                     ← punto de entrada
app/
├── application.py          ← arranque: permisos, tema, splash, asistente, ventana
├── context.py              ← contenedor de servicios activos (ctx)
├── signals.py              ← bus de señales (actualización sin reiniciar)
├── core/
│   ├── paths.py            ← rutas portables junto al .exe
│   ├── settings.py         ← configuración JSON con defaults fusionados
│   ├── database.py         ← SQLite (WAL, claves foráneas, transacciones)
│   ├── migrations.py       ← migraciones versionadas (v1 base + v2 almacén)
│   ├── export.py           ← exportación a CSV / Excel / PDF
│   ├── security.py         ← PBKDF2 + modo edición + retraso progresivo
│   ├── backup.py           ← respaldos con retención de 10
│   └── services/           ← catálogo, inventario (kardex/lotes), caja,
│                             listas de compras, alertas y estadísticas
├── printing/
│   ├── ticket_builder.py   ← texto del ticket alineado (32/48 caracteres)
│   ├── escpos.py           ← comandos ESC/POS + logo rasterizado
│   └── printer.py          ← win32print RAW y QPrinter
└── ui/
    ├── splash.py           ← bootlogo animado
    ├── first_run.py        ← asistente de primer arranque
    ├── main_window.py      ← navegación lateral + campana de alertas + Ctrl+P
    ├── common.py           ← widgets compartidos (banner de edición, tarjetas…)
    ├── dialogs/            ← cobro, caja, tickets, catálogo, inventario, compras,
    │                          notificaciones y seguridad
    └── modules/            ← Caja, Catálogo, Inventario (5 vistas),
                               Estadísticas y Ajustes
```

---

## 📦 Obtener el .exe (sin instalar Python)

GitHub Actions compila el ejecutable automáticamente:

1. **Push a `main`** (o ejecutar manualmente el workflow *«Restaurante Pro
   (tests + EXE de Windows)»* desde la pestaña **Actions**).
2. Al terminar, descarga el artefacto **RestaurantePro-Windows.zip** en la
   misma ejecución del workflow.
3. En cada **tag `v*`** (ej. `v1.0.0`) se crea además un **Release** con el
   zip adjunto.

El zip contiene la carpeta portable:

```
RestaurantePro.exe
_internal/…
```

Cópiala donde quieras (ej. `C:\RestaurantePro`) y ejecuta el `.exe`: las
carpetas `data/` y `backups/` se crean junto a él en el primer arranque.

---

## 🔧 Añadir una migración de esquema

En `app/core/migrations.py`, agrega una nueva versión **sin tocar las
anteriores**:

```python
MIGRATIONS[2] = ["""
ALTER TABLE products ADD COLUMN cost REAL NOT NULL DEFAULT 0;
"""]
```

Al abrir el programa se aplicará solo esa versión, conservando todos los datos.

---

## 🧾 Formato del ticket

```
            MI FONDA
       ¡Cocina hecha con amor!
        Tel: 961 123 4567
========================================
Folio: #000042
Fecha: 2025-06-15 13:45:00
Pedido: Mesa
Mesero: Ana
----------------------------------------
1 x Hamburguesa clásica            $120.00
  » sin cebolla
1 x Coca 500 ml                     $25.00
----------------------------------------
Subtotal                           $145.00
Descuento                           -$5.00
Impuesto (16%)                      $22.40
Propina                             $20.00
TOTAL                              $182.40
Pago (Efectivo)                    $200.00
Cambio                              $17.60
========================================
     ¡Gracias por su preferencia!
```

---

*Restaurante Pro v1.0.0 — hecho con PySide6, PySide6-Fluent-Widgets y SQLite.*
