# EncuentraU · Backend

API de EncuentraU para reportar objetos perdidos y encontrados, buscar coincidencias y coordinar su devolución. Está construida con FastAPI y PostgreSQL.

## Funciones

- Registro, inicio de sesión, recuperación de contraseña y permisos por cuenta.
- Verificación de correo por código, con vencimiento, consumo único y reenvíos limitados.
- Reportes con fotografías privadas, edición y búsqueda de coincidencias.
- Análisis de imágenes con OpenAI y Gemini como respaldo, configurados en el servidor.
- Reclamación de objetos, revisión administrativa y chat privado entre participantes autorizados.
- Confirmaciones de entrega e historial de auditoría.
- Límites de consumo de IA configurables por cuenta y para toda la aplicación.

La IA compara características visibles y ayuda a buscar; una similitud no demuestra propiedad. La revisión de la reclamación y las confirmaciones siguen siendo necesarias.

## Búsqueda y comparación de objetos

La búsqueda compara reportes activos de personas distintas: uno perdido y otro encontrado. El motor `semantic-v8` tiene en cuenta las características del objeto, la descripción, el lugar y la fecha. Reconoce variantes como «sombrilla/paraguas» y distingue el producto de su envase.

Al buscar desde un reporte, la respuesta incluye solo sus candidatos. Los casos descartados y cerrados se muestran aparte. El puntaje sobre 100 sirve para ordenar la búsqueda; no representa una probabilidad de identidad o de propiedad.

La comparación visual revisa las dos fotos y explica sus semejanzas, diferencias o falta de evidencia. OpenAI es el proveedor principal y Gemini actúa como respaldo ante los errores previstos por la integración. Las comparaciones guardadas se reutilizan mientras las fotos y la configuración aplicable no cambien.

Más detalles en [las reglas de comparación](deploy/aws/PRODUCT_CONTEXT_VALIDATION.md) y [las consultas por reporte](deploy/aws/SCOPED_MATCHES_VALIDATION.md).

## Arquitectura

```text
Flutter → API FastAPI → casos de uso → dominio
                         ↓
                PostgreSQL / fotos privadas / proveedores IA
                         ↓
                  Redis → WebSocket → Flutter
```

`app/api` contiene rutas, autenticación y respuestas HTTP. `app/application` coordina los casos de uso; `app/domain` define reglas y contratos; `app/infrastructure` implementa persistencia, almacenamiento, eventos e integración con proveedores. `alembic` mantiene el esquema de la base de datos.

Los mensajes se guardan en PostgreSQL. Redis distribuye avisos de cambios y WebSocket los lleva a las cuentas autorizadas; el cliente consulta el historial mediante la API. Redis no es el respaldo de los mensajes ni el registro de cupos de IA.

## Desarrollo local

Se necesitan Python 3.12, PostgreSQL y Redis. Desde la raíz del repositorio, en PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Completar `.env` con credenciales locales, una clave JWT aleatoria de al menos 32 bytes y las claves de los proveedores. No versionar ese archivo. `.env.example` incluye OpenAI como principal y Gemini como respaldo; los valores de ejemplo deben reemplazarse.

```powershell
docker compose up -d postgres
docker run -d --name encuentrau-redis-dev -p 127.0.0.1:6379:6379 redis:7.4-alpine
alembic upgrade head
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Si PostgreSQL o Redis ya están disponibles, usar sus conexiones en `.env` sin crear instancias adicionales. CORS debe incluir el origen exacto del frontend.

- Estado de API: `GET /health`.
- Estado de base de datos: `GET /health/database`.
- Documentación local: `http://127.0.0.1:8000/docs`.
- Rutas de aplicación: `/api/v1`; requieren autenticación según la operación.

Las fotos se sirven a través de rutas autorizadas. No publicar el directorio de archivos como contenido estático.

## Pruebas

```powershell
python -m pytest tests
```

Las pruebas de integración requieren `TEST_DATABASE_URL` apuntando a una base **exclusiva de pruebas**, con `_test` en el nombre. Pueden crear y eliminar tablas: nunca usar la base de desarrollo compartida ni producción. La prueba de WebSocket también requiere `TEST_REDIS_URL` de una instancia aislada. Sin esas variables, algunas pruebas se omiten.

La suite cubre autenticación, permisos, reportes, fotos, coincidencias, reclamaciones, chat, entregas y cupos. Las pruebas automatizadas de proveedores no sustituyen una evaluación con fotografías reales.

## AWS y operación

La aplicación está publicada por HTTPS en [EncuentraU](https://encuentrau.3.131.242.200.sslip.io).

Caddy sirve Flutter y dirige la API hacia FastAPI. PostgreSQL corre en RDS privado; Redis permanece en la red interna. Las fotos están en un volumen cifrado con respaldo diario a S3. El acceso de operación utiliza Systems Manager y los secretos se configuran fuera de Git.

- [Instalación, infraestructura y costos](deploy/aws/README.md).
- [Cupos de IA y respuestas 429](deploy/aws/AI_QUOTAS.md).
- [Verificación de correo y configuración de envíos](deploy/aws/EMAIL_VERIFICATION.md).
- [Restauración de base y fotografías](deploy/aws/RESTORE_RUNBOOK.md).

El procedimiento de restauración incluye una comprobación aislada de la base, las fotos y el acceso de los usuarios. Consultar el documento enlazado antes de intervenir producción.

Los cupos internos de IA están desactivados para la entrega. Se pueden activar mediante la configuración del servidor; no se reactivan solos. Los avisos de AWS no detienen el gasto y las llamadas a OpenAI y Gemini se facturan por separado.

La instalación utiliza un solo servidor y DNS externo gratuito, sin alta disponibilidad. Antes de ampliar el uso, revisar capacidad, presupuesto y soporte. La [recuperación de contraseña](deploy/aws/PASSWORD_RECOVERY.md) tiene su propia guía de configuración.
