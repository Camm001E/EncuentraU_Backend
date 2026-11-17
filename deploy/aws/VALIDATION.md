# Verificacion local de preparacion AWS

Fecha: 2026-11-13. Solo copias; sin publicaciones ni recursos AWS creados.

## Chat entre dos cuentas

Prueba reproducible: tests/test_chat_two_accounts.py. Dos cuentas aisladas ingresan mediante email y contrasena por la API, consultan /auth/me, esperan la aprobacion administrativa, intercambian mensajes, marcan lectura y vuelven a ingresar. Los mensajes persisten, los reintentos no duplican y los indicadores is_mine corresponden a cada cuenta. Un tercero, un administrador ajeno y una peticion anonima no pueden acceder.

La prueba corre tanto en SQLite como en PostgreSQL aislado con migraciones reales. El paquete de chat y reclamaciones obtuvo 107 pruebas aprobadas. La interfaz de chat obtuvo 48 pruebas aprobadas. Es una aceptacion automatizada por API y widgets; no es una prueba manual de dos navegadores en AWS.

## Correccion previa a publicacion

El analisis inicial de fotos antes permitia acceso sin login. Ahora exige usuario activo y el frontend usa el cliente autenticado, que invalida sesiones vencidas y descarta respuestas de sesiones anteriores. 38 comprobaciones de chat, autorizacion y proveedores aprobadas despues del cambio. Las pruebas de proveedor usan dobles controlados, sin consumir APIs de pago en esta etapa. Suite completa Flutter: 273 pruebas aprobadas; analisis sin hallazgos.

## Empaquetado

Backend Docker construido localmente. Se verificaron migraciones desde una base vacia, health de PostgreSQL, registro y login de dos cuentas, reinicio del contenedor y persistencia de cuentas y archivos en volumen. Los datos y contenedores temporales de esta comprobacion se eliminaron al terminar. Compose valida y Caddy valida su configuracion. No se verificaron todavia certificados publicos, DNS, permisos IAM ni conectividad real a RDS.

El archivo README.md de este directorio define los recursos y pasos pendientes. No declarar entrega de produccion hasta completar su aceptacion HTTPS y restauracion de backups.

Compilacion web final completada correctamente. Imagen web reconstruida con el cambio de autenticacion. Originales verificados por SHA-256: 7917 archivos backend y 3355 frontend; cero modificados, perdidos o adicionales. No se realizaron commits, pushes ni despliegues AWS en esta etapa.
