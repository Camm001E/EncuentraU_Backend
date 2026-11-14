# EncuentraU en AWS

Despliegue inicial verificado en noviembre de 2026. La plantilla y los scripts pertenecen a la copia de trabajo. No contienen claves, contrasenas, correo de facturacion ni rutas personales. Los artefactos de comprobacion y las credenciales locales quedan en `build/`, excluido de Git. No es necesario publicar los repositorios para desplegar.

## Arquitectura

Internet -> Caddy HTTPS -> Flutter web y FastAPI -> PostgreSQL RDS privado.

- EC2 `t3.small`, creditos CPU en modo **standard**, 20 GB gp3 cifrados para el sistema.
- Otro volumen EBS gp3 cifrado de 20 GB para fotos, montado en `/mnt/encuentrau`. Se conserva al retirar la infraestructura.
- RDS PostgreSQL `db.t4g.micro`, 20 GB, Single-AZ, cifrado y proteccion contra borrado. Puerto 5432 solo desde el servidor. Conexion TLS `verify-full`, usuario de aplicacion con permisos limitados; migraciones con credenciales separadas.
- Redis privado dentro de Compose: avisos de cambios del chat, limite de contenedor 128 MB. Los mensajes duraderos estan en PostgreSQL, no en Redis.
- WebSocket autenticado; la aplicacion vuelve a consultar el historial autorizado por HTTP. La aprobacion administrativa habilita el chat entre participantes.
- S3 privado para transferir imagenes y respaldar fotos; ninguna foto se publica directamente. Secretos en Secrets Manager y archivo del servidor con modo 600.
- Administracion mediante Systems Manager. Solo 80/443 TCP publicos; sin SSH, API ni Redis expuestos directamente.

Es una instalacion economica de un solo servidor, **sin alta disponibilidad**. Escalar requiere almacenamiento compartido y limites/cache distribuidos.

## HTTPS sin comprar dominio

El despliegue inicial utiliza un nombre de `sslip.io` que resuelve a la IP elastica. Caddy obtiene y renueva el certificado. Esta opcion depende del servicio DNS gratuito externo. Para un dominio propio: apuntar DNS a la IP, cambiar `SITE_DOMAIN` y `CORS_ORIGINS`, recompilar Flutter con el origen HTTPS y desplegar la imagen nueva.

No cambiar la IP sin actualizar el nombre y reconstruir Flutter: la URL de la API queda compilada.

## Construccion e instalacion

1. Revisar cuenta, perfil y region; usar una infraestructura exclusiva de EncuentraU. `infrastructure.json` crea recursos nuevos y conserva los datos persistentes al retirar la pila.
2. Construir backend con Docker y frontend con `deploy/aws/build.ps1` de su repositorio, pasando el origen HTTPS real. Usar etiquetas de version, nunca incluir `.env`, caches ajenas ni credenciales en las imagenes.
3. Transferir los archivos `docker save` al bucket privado. En el servidor, descargar los objetos por su clave exacta y ejecutar `docker load`; el rol no necesita listar todo el bucket.
4. Instalar Docker Compose >=2.30. En la entrega se verifico el SHA256 oficial de Compose 2.39.4 antes de instalarlo.
5. Colocar `compose.yaml`, `encuentrau.service`, `init_database.py` y `bootstrap_host.py` en `/opt/encuentrau`. Crear `manifest.json` con las salidas `DataVolume`, `DbEndpoint`, `DbSecret`, `Bucket` de CloudFormation y el campo `Domain`.
6. Preparar el secreto `encuentrau/runtime`: `OPENAI_API_KEY`, `GEMINI_API_KEY`, `JWT_SECRET_KEY`, `DB_APP_PASSWORD`, `INITIAL_ADMIN_PASSWORD`. No usar valores en argumentos, logs o archivos versionados. El secreto maestro de RDS lo administra AWS.
7. Ejecutar `python3 bootstrap_host.py` desde `/opt/encuentrau`, mediante SSM. Es un instalador inicial: verifica el disco, crea filesystem solo si esta vacio, monta fotos, aplica migraciones, crea administrador, cambia a usuario limitado y arranca Compose. Revisar antes de reutilizarlo en una actualizacion.

El administrador inicial es Camila, con correo configurado mediante `ADMIN_EMAIL` y contrasena aleatoria entregada por archivo privado. El correo real se mantiene fuera del repositorio. El instalador usa el codigo `ADMIN-CAMILA` para evitar duplicar la cuenta si cambia su direccion. No existe una contrasena predeterminada en el repositorio.

Nunca ejecutar `docker compose config` sin `--quiet` en logs compartidos: puede expandir secretos. Nunca usar `down -v` para actualizar.

## Respaldos y costos

- RDS: retencion automatica de **1 dia**, limite que acepto el plan gratuito de esta cuenta. Recuperacion a un punto en el tiempo disponible; restauracion aislada de RDS y fotos ensayada, incluidos login, historial y reinicio. Ver `RESTORE_RUNBOOK.md`.
- Fotos: temporizador diario a las 06:00 UTC, S3 cifrado y versionado. Se conserva el respaldo actual y las versiones anteriores expiran despues de 7 dias. Se verifico descarga y lectura de las fotos de prueba del archivo respaldado.
- Artefactos de instalacion: vencimiento de 14 dias; versiones antiguas, 7 dias. Mantener las imagenes originales en almacenamiento local privado si se necesita reconstruir mas tarde.
- Presupuesto mensual de EncuentraU: USD 55, calculado sin descontar creditos; avisos reales a USD 20, 35, 45 y 55, mas aviso de prevision al 100%. El destinatario se configura fuera del repositorio. **Son avisos, no un corte automatico del gasto.**
- Estimacion inicial: USD 40-55/mes para esta configuracion con uso ligero. Trafico, fotos y uso pueden aumentarla. OpenAI y Gemini tienen facturacion separada de AWS.

No hay apagado automatico el 7 de diciembre. La continuidad depende de credito disponible, servicio AWS y uso; revisar consumo real porque la facturacion tiene retraso.

## Aceptacion realizada

Sobre HTTPS publico: salud de PostgreSQL, registro/login, fotos privadas, coincidencia, reclamacion/aprobacion, mensajes en ambos sentidos con dos WebSockets y Redis, denegacion a terceros y administrador ajeno, lectura de mensajes, doble confirmacion y cierre de entrega. Tras reiniciar la API persistieron acceso, mensajes y fotos. Chrome verifico ingreso y restauracion de sesion; se revisaron las vistas de escritorio y movil.

Las tres cuentas de aceptacion quedaron desactivadas. El caso tecnico cerrado se conserva identificado como prueba para respetar la auditoria inmutable de entregas.

OpenAI y Gemini respondieron desde AWS por separado y sin fallback en una foto real. Esta es una prueba de integracion, no una nueva medicion de precision. La IA puede diferir en nombres de objetos y no demuestra propiedad.

## Operacion y limites pendientes

Revisar avisos de presupuesto, cuota y facturacion de proveedores IA. El analisis exige autenticacion y cupos persistentes por cuenta/hora/dia y globales por dia/mes. Las comparaciones cacheadas no descuentan de nuevo. Ver `AI_QUOTAS.md`. Estos cupos no sustituyen proteccion general contra ataques ni un limite monetario del proveedor. La verificacion de correo usa Amazon SES con limites persistentes; ver `EMAIL_VERIFICATION.md`. La recuperacion de contrasenas usa el mismo presupuesto de SES; ver `PASSWORD_RECOVERY.md`.

Antes de una entrega con SLA: probar carga con el volumen esperado y acordar monitorizacion/soporte. La restauracion completa ya se ensayo en un entorno privado y temporal, retirado despues de verificarlo. La disponibilidad de un unico servidor no equivale a un servicio tolerante a fallos.

Para rollback, conservar imagenes previas compatibles con el esquema. No hacer downgrades destructivos automaticos; restaurar base y fotos coordinadamente si fuera necesario.

Referencias: [TLS de RDS](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/PostgreSQL.Concepts.General.SSL.html), [persistencia EBS](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/preserving-volumes-on-termination.html), [Compose 2.39.4](https://github.com/docker/compose/releases/tag/v2.39.4).
