# Preparacion de entrega en AWS

Estado: archivos preparados localmente. No se han creado recursos, subido imagenes ni publicado repositorios. Esta propuesta usa una instancia EC2 Linux x86_64 con Docker Compose, RDS PostgreSQL privado y EBS cifrado separado para fotos. No presupone que esos recursos ya existan. Si hay infraestructura AWS previa, revisar y adaptar antes de ejecutar.

## Arquitectura y limites

Internet -> Caddy HTTPS en EC2 -> web Flutter y API FastAPI -> RDS privado. Las fotos privadas las sirve la API despues de autorizar, nunca Caddy. Un proceso API mantiene coherentes los limites y cache de revision visual en memoria. Esta instalacion inicial tiene un unico servidor; no ofrece alta disponibilidad. Escalar requiere almacenamiento compartido y limites/cache distribuidos.

El endpoint de analisis de fotos exige una cuenta activa autenticada; el frontend adjunta el token de sesion y procesa la expiracion. Esto no sustituye cuotas y limites de consumo por usuario.

El chat recibe avisos WebSocket mediante Redis privado y reconcilia el historial HTTP cada 30 segundos como respaldo. Redis se ejecuta en la instancia, sin puerto publico; su memoria esta limitada a 128 MB. No se requiere ElastiCache para esta configuracion inicial. La aprobacion administrativa abre la conversacion entre los dos participantes. La IA no concede acceso al chat.

## Lo necesario antes de publicar

- Cuenta AWS de destino, region, dominio HTTPS y presupuesto. Revisar recursos existentes sin reemplazarlos.
- EC2 x86_64, Docker y Compose >=2.30; acceso por Systems Manager, IMDSv2 obligatorio, rol de instancia limitado. No incluir claves AWS ni secretos en user-data.
- Entrada publica solo 80/443 para Caddy y emision HTTPS; ningun puerto publico 8000/5432/22. Salida a RDS y HTTPS para IA/certificados. Configurar DNS del dominio a una IP estable de la instancia.
- RDS PostgreSQL en subredes privadas, cifrado, proteccion de borrado y backups. Puerto 5432 permitido solo desde el grupo de seguridad EC2. Usuario de aplicacion propio y privilegios ajustados; ejecutar migraciones con rol adecuado.
- Volumen EBS de datos cifrado montado en /mnt/encuentrau, con DeleteOnTermination=false. Crear uploads con propietario 10001:10001. Montaje persistente y obligatorio antes de arrancar; confirmar con mountpoint. No usar el disco efimero para fotos.
- Guardar DATABASE_URL, JWT_SECRET_KEY y claves IA en Secrets Manager. Materializar runtime.env en /etc/encuentrau con acceso exclusivo del administrador (chmod 600), sin registrar su contenido. Mantener JWT estable entre reinicios. No copiar el .env de desarrollo completo.
- Descargar el bundle CA oficial de RDS a /etc/encuentrau/rds-ca.pem y conectar con sslmode=verify-full. Credenciales URL-encoded. Configurar CORS_ORIGINS al origen HTTPS exacto.
- Backups de RDS y EBS con retencion y una restauracion probada; alertas de disponibilidad, errores, disco y gasto de IA. Definir proteccion contra abuso/rate limits antes de exposicion publica; no se ha implementado un limitador global distribuido.

## Construccion local (no publica)

Backend, desde su copia:

```sh
docker build -t encuentrau-api:release-001 .
```

Frontend, desde su copia, reemplazando el dominio:

```powershell
./deploy/aws/build.ps1 -PublicOrigin https://app.su-dominio.com -ImageTag encuentrau-web:release-001
```

La URL queda compilada en Flutter; el build de prueba existente usa localhost y NO es un paquete final para el dominio. El script obliga a recompilar. No copiar .dart_tool, build ni entornos virtuales de los originales.

Las imagenes se pueden transferir mas adelante mediante ECR privado o docker save/load. No ejecutar push ni copiar secretos a las imagenes. Registrar digests de las imagenes aprobadas; evitar latest. .dockerignore usa una lista de archivos permitidos.

## Activacion posterior, solo cuando se autorice

En EC2, con los dos tags ya cargados, Compose y archivos de configuracion preparados:

```sh
mountpoint /mnt/encuentrau
# Desde el directorio que contiene compose.yaml y deployment.env:
docker compose --env-file deployment.env config --quiet
# Backup previo a cada migracion. Una sola ejecucion, sin trafico:
docker compose --env-file deployment.env run --rm --no-deps api alembic upgrade head
docker compose --env-file deployment.env up -d
```

No usar `docker compose config` sin --quiet en un registro compartido: puede expandir secretos. El servicio API no publica puertos. Su healthcheck exige PostgreSQL disponible; la web espera al servicio saludable. Se incluye encuentrau.service para instalar en /etc/systemd/system, con Compose y deployment.env en /opt/encuentrau. La unidad comprueba el montaje EBS antes de arrancar. Configurar /etc/fstab y verificar la ruta de docker en la distribucion elegida. Habilitarla solo despues de migrar y validar la configuracion.

Crear administrador mediante `python -m app.cli.create_admin` en el contenedor con entrada interactiva, nunca contrasenas en argumentos ni un usuario administrador publico de prueba.

## Aceptacion y rollback

Validar HTTPS y certificado, /health/database, registro/login de dos cuentas de prueba, reportes con fotos, coincidencia, reclamacion, aprobacion administrativa, chat bidireccional y entrega. Intentar acceso con tercero y administrador ajeno; comprobar 404. Reiniciar API y confirmar mensajes y fotos conservados. Comprobar desde dos navegadores/dispositivos y cerrar las cuentas de prueba al finalizar.

Para rollback, conservar tags anteriores y backups. Revertir imagenes solo si el esquema sigue siendo compatible. No ejecutar downgrades destructivos automaticos; restaurar RDS y EBS de forma coordinada y probar antes de cambiar trafico. Nunca usar docker compose down -v para una actualizacion.

## Fuentes verificadas

- Persistencia EBS: https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/preserving-volumes-on-termination.html
- TLS de RDS: https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/PostgreSQL.Concepts.General.SSL.html

## Pendiente para declarar entrega

Infraestructura y dominio reales, carga protegida de secretos, migracion y administrador de produccion, proteccion contra abuso, alertas/backups/restauracion y aceptacion de extremo a extremo en HTTPS. La validacion local de chat no sustituye esa aceptacion. La IA conserva los limites documentados en el cierre de IA.
