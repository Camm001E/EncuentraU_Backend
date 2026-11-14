# Verificación de correo

Después de registrarse, la cuenta debe verificar su correo antes de entrar cuando `EMAIL_VERIFICATION_REQUIRED=true`. El formulario solicita correo, contraseña y un código de ocho dígitos. No se abre una sesión al registrar ni al confirmar el código: después se inicia sesión normalmente.

## Reglas

- Código aleatorio de un solo uso, válido durante diez minutos. Se guarda un HMAC ligado al usuario; no se almacena el código en claro.
- Cinco intentos incorrectos invalidan el código. Los intentos y la confirmación se serializan con bloqueos de filas en PostgreSQL.
- Reenviar invalida el código anterior. Hay una espera de 60 segundos y un máximo de tres envíos por cuenta en una ventana de una hora.
- El límite global inicial es 40 envíos por día UTC, con al menos dos segundos entre reservas globales. El contador es persistente y configurable mediante `EMAIL_DAILY_LIMIT`.
- Los errores o tiempos de espera del proveedor consumen la reserva para evitar reintentos ilimitados. El usuario puede volver a solicitar el envío después de la espera.
- Correo y contraseña se validan antes de enviar. Los códigos, contraseñas y destinatarios no se escriben en logs ni URLs. Las respuestas no se almacenan en caché.
- El requisito se aplica a todas las cuentas, incluido el administrador, y se vuelve a comprobar al usar un token existente o un WebSocket. Las cuentas inactivas siguen bloqueadas.

Verificar un buzón no acredita matrícula universitaria ni propiedad de un objeto. Para una contraseña olvidada existe un flujo separado: [recuperación de contraseña](PASSWORD_RECOVERY.md).

## Configuración de AWS

1. Verificar la identidad del remitente en Amazon SES, en la misma región del servidor, y obtener acceso de producción para enviar a destinatarios no prevalidados.
2. Configurar `EMAIL_SENDER` y `ADMIN_EMAIL` en el secreto privado `encuentrau/runtime`. El correo real no debe aparecer en Git. Mantener `EMAIL_VERIFICATION_REQUIRED=false` durante la preparación.
3. Autorizar exclusivamente `ses:SendEmail` sobre el ARN de la identidad verificada en el rol de la instancia. La instalación actual usa una política adicional `EncuentraUVerificationEmail`; conservarla al recrear el rol. No hace falta una clave estática de AWS en el contenedor.
4. Mantener IMDSv2 obligatorio y un hop limit de 2 para el contenedor. La plantilla lo contempla para instalaciones nuevas; actualizar una instancia existente sin reemplazarla.
5. Aplicar `alembic upgrade head` con las credenciales de migración y desplegar las imágenes nuevas de API y frontend. La revisión `0008_email_verification` conserva usuarios y datos y no marca ningún correo como verificado automáticamente.
6. Comprobar un envío real y acceso al buzón del administrador. Si tenía una dirección ficticia, actualizar únicamente su dirección con autorización, conservando ID, contraseña y permisos.
7. Activar `EMAIL_VERIFICATION_REQUIRED=true` en el entorno privado y mantener ese valor en Secrets Manager para reconstrucciones futuras. Verificar el administrador desde la pantalla pública y comprobar el acceso posterior. Las demás cuentas también deberán verificar su correo.

El proveedor mantiene la supresión de rebotes y quejas. La aceptación por SES no garantiza llegada a la bandeja principal: revisar spam y restricciones del receptor. El límite de envíos reduce consumo, pero no es un límite monetario de toda la cuenta AWS.

## Comprobación

Probar registro, bloqueo antes de verificar, envío, código incorrecto, vencimiento, reenvío, consumo único, ingreso posterior y denegación con tokens anteriores de una cuenta sin verificar. Las pruebas de concurrencia usan PostgreSQL aislado; los tests locales usan un buzón simulado y no envían correo real.

Para volver a la versión anterior, conservar las imágenes y la configuración previa. Las columnas nuevas son aditivas; no es necesario borrar usuarios ni ejecutar un downgrade destructivo. No desactivar el requisito como rutina para saltar un correo fallido.

Referencias: [identidades de SES](https://docs.aws.amazon.com/ses/latest/dg/verify-addresses-and-domains.html), [acceso de producción](https://docs.aws.amazon.com/ses/latest/dg/request-production-access.html), [IMDS en contenedores](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/instancedata-data-retrieval.html).
