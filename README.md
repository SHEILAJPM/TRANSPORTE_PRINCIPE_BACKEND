# Transporte Príncipe — Backend

Sistema integral de gestión de transporte de carga pesada (Perú). FastAPI + PostgreSQL (SQLAlchemy 2.0 async) + Alembic, con integración obligatoria a **apisunat.pe**.

## 1. Estructura de carpetas

```
TRANSPORTE_PRINCIPE_BACKEND/
├── alembic/                        # Migraciones de base de datos
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
├── app/
│   ├── main.py                     # Punto de entrada FastAPI
│   ├── core/
│   │   ├── config.py                # Settings (.env) vía pydantic-settings
│   │   ├── database.py              # Engine + AsyncSession
│   │   └── security.py              # JWT + hashing de contraseñas
│   ├── models/                      # Entidades SQLAlchemy (ver sección 2)
│   │   ├── base.py                  # Base, UUIDPKMixin, TimestampMixin
│   │   ├── enums.py
│   │   ├── empresa.py               # Datos fiscales + logo propio
│   │   ├── usuario.py
│   │   ├── cliente.py               # Autocompletado por apisunat.pe
│   │   ├── chofer.py                # Brevete A-III-C, examen médico
│   │   ├── flota.py                 # Tracto, Carreta + dimensiones RNV
│   │   ├── mantenimiento.py         # Mantenimiento preventivo por Km
│   │   ├── cotizacion.py
│   │   ├── viaje.py
│   │   ├── comprobante.py           # GuiaRemision, Factura
│   │   ├── pesos_medidas.py         # Constancia DS 058-2003-MTC
│   │   ├── gasto_viaje.py           # Combustible/peaje/viático/adelanto (offline)
│   │   ├── novedad_viaje.py
│   │   ├── liquidacion.py           # Dietas + nocturnidad
│   │   ├── correlativo.py           # Contador atómico de numeración
│   │   └── sunat_log.py             # Auditoría de consultas a apisunat.pe
│   ├── schemas/                     # DTOs Pydantic (request/response)
│   ├── api/
│   │   ├── deps.py                  # get_current_user, etc.
│   │   └── v1/
│   │       ├── router.py            # Agregador de routers
│   │       └── endpoints/
│   │           ├── sunat.py          # Consulta RUC/DNI + autocompletar cliente
│   │           ├── cotizaciones.py   # Conversión de 1 clic
│   │           ├── liquidaciones.py  # Cálculo de pago al chofer + rentabilidad
│   │           └── ...               # empresa, flota, choferes, viajes, gastos,
│   │                                 #   pesos_medidas, reportes (mismo patrón)
│   ├── services/                    # Lógica de negocio (ver sección 3)
│   │   ├── sunat_service.py
│   │   ├── cotizacion_service.py
│   │   ├── liquidacion_service.py
│   │   ├── reportes_service.py       # Rentabilidad por viaje
│   │   ├── alertas_service.py        # Vencimientos SOAT/CITV/MTC/licencia
│   │   ├── storage_service.py        # Logo dinámico (local/S3)
│   │   └── pdf_service.py            # Jinja2 + WeasyPrint
│   ├── tasks/                       # Celery (alertas diarias de vencimiento)
│   ├── templates/pdf/               # Plantillas HTML de cotización/factura/guía/constancia
│   └── utils/
│       ├── correlativos.py          # Numeración atómica (COT-, VJ-, CPM-, series SUNAT)
│       └── dinero.py                # Redondeo monetario consistente (Decimal)
├── tests/
├── alembic.ini
├── docker-compose.yml               # api + db (Postgres) + redis + celery worker/beat
├── Dockerfile
├── requirements.txt
└── .env.example
```

## 2. Modelo de datos (PostgreSQL)

Todas las tablas usan PK `UUID` (`gen_random_uuid` a nivel de aplicación) y `creado_en/actualizado_en` con `TIMESTAMPTZ`. Resumen de entidades y llaves foráneas:

| Tabla | Campos clave | FKs |
|---|---|---|
| `empresas` | `ruc` (unique), `logo_url`, `apisunat_token` | — |
| `usuarios` | `email` (unique), `rol` (enum) | `empresa_id → empresas`, `chofer_id → choferes` |
| `clientes` | `numero_documento` (unique), `fuente_datos` | — |
| `choferes` | `dni` (unique), `licencia_numero` (unique), `licencia_categoria` default `A-III-C` | — |
| `tractos` | `placa` (unique), `largo_m/ancho_m/alto_m`, `configuracion_vehicular`, `peso_bruto_max_kg`, `soat/citv/mtc_vencimiento` | — |
| `carretas` | ídem `tractos` + `tipo_carreta` | — |
| `mantenimientos_vehiculo` | `tipo_mantenimiento`, `kilometraje_actual_registro` | `tracto_id` **xor** `carreta_id` (CHECK) |
| `cotizaciones` | `numero` (unique), `precio_base/monto_igv/precio_total`, `condiciones_comerciales` | `empresa_id`, `cliente_id`, `usuario_id` |
| `viajes` | `numero` (unique), `modalidad` (CON_RUC/SIN_RUC), `dias_viaje/noches_viaje`, `tarifa_diaria_chofer/bono_nocturno_chofer` | `cotizacion_id`, `cliente_id`, `tracto_id`, `carreta_id`, `chofer_id`, `propietario_usuario_id` |
| `guias_remision` | `serie+numero` (unique), `peso_bruto_total_kg`, `estado_sunat` | `viaje_id` (unique), `cotizacion_id`, `cliente_id` |
| `facturas` | `serie+numero` (unique), `subtotal/igv/total` | `viaje_id`, `cotizacion_id`, `cliente_id`, `guia_remision_id` |
| `constancias_pesos_medidas` | `numero` (unique), `peso_bruto_kg/tara_kg/peso_neto_kg`, snapshot de dimensiones | `guia_remision_id` (unique), `viaje_id`, `tracto_id`, `carreta_id`, `chofer_id`, `generador_carga_cliente_id` |
| `gastos_viaje` | `tipo_gasto` (enum), `uuid_dispositivo` (unique, soporte offline) | `viaje_id`, `registrado_por_chofer_id` |
| `novedades_viaje` | `tipo_novedad`, `latitud/longitud`, `uuid_dispositivo` (offline) | `viaje_id` |
| `liquidaciones_chofer` | `monto_dietas`, `saldo_rendicion_cuentas`, `neto_a_pagar_chofer` | `viaje_id` (unique), `chofer_id` |
| `correlativos` | `tipo+serie` (unique), `ultimo_numero` | — |
| `consultas_sunat_log` | `numero_documento`, `respuesta_json` (JSONB) | `usuario_id` |

Notas de diseño:
- **Dimensiones vehiculares** (`DimensionesVehicularesMixin` en `flota.py`) están en `tractos` y `carretas` como campos editables, no como tabla de catálogo fija, porque el Anexo IV del RNV define límites por configuración (C-2, C-3, T3S3, etc.) pero cada unidad puede variar dentro de ese límite.
- **`ConstanciaPesosMedidas`** guarda una *copia* (snapshot) de las dimensiones/peso máximo del vehículo al momento de emitirse, editable manualmente, porque la ficha del vehículo puede cambiar después sin alterar constancias ya emitidas.
- La **rentabilidad por viaje** (`reportes_service.calcular_rentabilidad_viaje`) se calcula on-demand (no es una tabla física) a partir de `viajes.ingreso_flete_neto`, `gastos_viaje` y `liquidaciones_chofer`, para no duplicar datos que ya viven en otras tablas.
- `correlativos` centraliza la numeración de `COT-`, `VJ-`, `CPM-` y las series SUNAT de guías/facturas con `SELECT ... FOR UPDATE`, evitando colisiones bajo concurrencia.

## 3. Servicios clave

### a) `app/services/sunat_service.py` — Integración con apisunat.pe
`ApiSunatService` es un cliente `httpx.AsyncClient` con `Authorization: Bearer <APISUNAT_TOKEN>`, reintentos (`tenacity`) ante errores de red, y manejo explícito de 404/401/429. `obtener_o_crear_cliente(...)` envuelve la consulta: si el cliente ya existe localmente no vuelve a llamar a la API (salvo `forzar_actualizacion=True`), registra cada intento en `consultas_sunat_log` (éxito o error) y crea/actualiza el `Cliente` con razón social, dirección, distrito/provincia/departamento (RUC) o nombre completo (DNI).

> Los nombres de campo del JSON de respuesta (`ruc`, `razon_social`, `dni`, `nombres`, etc.) están mapeados según la convención más común de APIs de consulta SUNAT en Perú — ajústalos en `consultar_ruc`/`consultar_dni` en cuanto tengas la documentación oficial de tu cuenta de apisunat.pe.

### b) `app/services/cotizacion_service.py` — Conversión de 1 clic
`convertir_cotizacion_a_viajes(...)` valida que la cotización esté `APROBADA` y no convertida, exige una `AsignacionUnidad` (tracto + chofer + fecha de salida, carreta opcional) por cada camión de `cantidad_camiones`, y en una sola transacción:
1. Crea el/los `Viaje` copiando cliente, ruta y condiciones desde la cotización (peso e importe se prorratean entre las unidades).
2. Genera la `GuiaRemision` (numeración por serie SUNAT).
3. Genera la `Factura` vinculada a esa guía, con el mismo subtotal/IGV/total de la cotización.
4. Genera la `ConstanciaPesosMedidas` con el snapshot de dimensiones del tracto/carreta y los datos del chofer.

Si cualquier paso falla, nada se persiste (rollback del `db.commit()` en el endpoint). Ningún dato se vuelve a digitar: todo viaja por FK o copia puntual desde la cotización.

### c) `app/services/liquidacion_service.py` — Pago al chofer
`calcular_liquidacion(...)` implementa la fórmula exacta:

```
monto_dietas            = (dias_viaje × tarifa_diaria) + (noches_viaje × bono_nocturno)
saldo_rendicion_cuentas = total_adelantos_recibidos − total_gastos_operativos
neto_a_pagar_chofer     = monto_dietas − saldo_rendicion_cuentas
```

Donde `total_gastos_operativos` es la suma de `gastos_viaje` de tipo `COMBUSTIBLE + PEAJE + VIATICO + OTRO` (el `ADELANTO` es el efectivo entregado, no un gasto). Si `saldo_rendicion_cuentas` es positivo, el chofer se quedó con efectivo de la empresa y se le descuenta de sus dietas; si es negativo, gastó de su bolsillo y la empresa se lo reembolsa sumándolo a sus dietas. `generar_liquidacion_viaje(...)` calcula `dias_viaje/noches_viaje` automáticamente a partir de `fecha_salida_real`/`fecha_llegada_real` (bloques de 24h) y persiste/actualiza `LiquidacionChofer`.

`reportes_service.calcular_rentabilidad_viaje(...)` cierra el ciclo financiero: `ganancia_neta = ingreso_flete_neto − (total_gastos_operativos + monto_dietas)`.

## 4. Cómo correr el proyecto

```bash
cp .env.example .env            # completar APISUNAT_TOKEN, credenciales de DB, etc.
docker compose up -d db redis
pip install -r requirements.txt
alembic revision --autogenerate -m "esquema inicial"
alembic upgrade head
uvicorn app.main:app --reload
```

Documentación interactiva: `http://localhost:8000/docs`.

## 5. Endpoints disponibles

`app/api/v1/router.py` integra 54 endpoints en 13 routers (`auth`, `usuarios`, `empresa`, `flota`, `choferes`, `clientes`, `sunat`, `cotizaciones`, `viajes`, `gastos`, `pesos_medidas`, `liquidaciones`, `reportes`):

| Router | Endpoints | Notas |
|---|---|---|
| `auth` | `POST /auth/registro-empresa`, `POST /auth/login`, `GET /auth/me` | El registro crea Empresa + primer Usuario ADMIN y autologuea (único endpoint público). |
| `usuarios` | CRUD (`POST/GET/PATCH`) | Solo ADMIN; gestiona cuentas de la empresa (incluida la vinculación `chofer_id` para la app del chofer). |
| `empresa` | `GET/PATCH /empresa`, `POST /empresa/logo` | Datos fiscales + logotipo dinámico (PNG/JPG/WEBP/SVG) vía `StorageService`. |
| `flota` | CRUD `tractos`/`carretas`, `mantenimientos` anidados, `GET /flota/alertas-vencimiento` | Alertas reutilizan `alertas_service` (SOAT/CITV/MTC/licencia/examen médico). |
| `choferes` | CRUD | — |
| `clientes` | `GET /clientes?q=`, `GET /clientes/{id}` | Búsqueda local (razón social o documento) para no repetir consultas a apisunat.pe si el cliente ya existe. |
| `cotizaciones` | `POST/GET /cotizaciones`, `GET/PATCH(/estado) /cotizaciones/{id}`, `POST /cotizaciones/{id}/convertir-a-viaje` | `crear_cotizacion` calcula IGV/total; `cambiar_estado_cotizacion` valida transiciones (BORRADOR→ENVIADA→APROBADA/RECHAZADA); solo una cotización `APROBADA` puede convertirse. |
| `viajes` | `POST /viajes/activar`, `GET /viajes`, `GET/PATCH /viajes/{id}(/estado)`, novedades anidadas | `activar` es la "Activación de Viaje por el Propietario" (módulo 5): emite GRE + Constancia (+ Factura si `CON_RUC`) sin pasar por una cotización, vía `viaje_service.activar_viaje` (mismo patrón que la conversión de 1 clic). |
| `gastos` | `POST/GET /viajes/{id}/gastos` | Idempotente por `uuid_dispositivo` para reintentos de sincronización offline de la app del chofer. |
| `pesos_medidas` | `GET /pesos-medidas/autocompletar-vehiculo/{placa}`, `POST`, `GET /por-viaje`, `GET /por-guia-remision`, `PATCH` | El autocompletado y la construcción de la Constancia se centralizaron en `pesos_medidas_service.construir_constancia_pesos_medidas`, reutilizada también por `cotizacion_service` y `viaje_service`. |
| `reportes` | `GET /reportes/viajes` | Buscador avanzado (cliente, placa, ciudad origen/destino, rango de fechas) con ingreso/egresos/ganancia neta calculados en una sola consulta agregada. |

Los roles (`RolUsuario`) se aplican vía `require_roles(...)` en `app/api/deps.py`: `ADMIN` para empresa/usuarios, `ADMIN`+`OPERADOR` para flota/choferes/viajes, y un chofer autenticado solo puede reportar gastos/novedades o cambiar el estado de **su propio** viaje (`usuario.chofer_id == viaje.chofer_id`).
