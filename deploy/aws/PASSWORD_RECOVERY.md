# Recuperación de contraseña

En el inicio de sesión, **Olvidé mi contraseña** permite pedir un código por
correo y establecer una nueva contraseña de 8 a 128 caracteres. El usuario
confirma la contraseña dos veces y después inicia sesión normalmente.

`POST /api/v1/auth/password/request` recibe solamente el correo. Devuelve la
misma respuesta para cuentas existentes, inexistentes, inactivas o limitadas.
El envío se procesa después de responder, con una sesión de base independiente;
la respuesta no garantiza entrega al buzón. Si el proceso se interrumpe o SES
falla, se puede volver a solicitar el código después de la espera. No hay una
cola durable de envíos.

`POST /api/v1/auth/password/confirm` recibe correo, código y `new_password`.
No requiere conocer la contraseña anterior. El código:

- Tiene ocho dígitos aleatorios, vence en diez minutos y solo se consume una vez.
- Se guarda como HMAC, separado de los códigos de verificación de correo.
- Permite cinco intentos y se reemplaza al enviar uno nuevo.
- Respeta 60 segundos entre envíos y tres envíos por cuenta y hora.
- Comparte con verificación el presupuesto diario de correo y la separación
  global de dos segundos. Los fallos de envío también consumen presupuesto.

Los bloqueos de fila de PostgreSQL impiden consumir un código dos veces o
superar los intentos mediante solicitudes simultáneas. Un cambio exitoso conserva
el ID, rol, reportes, chat e historial. Verifica el buzón existente e incrementa
`session_version`: los JWT anteriores dejan de servir por HTTP y los WebSocket
se cierran en su próxima comprobación, como máximo en el ciclo de 15 segundos.
Solicitar un código por sí solo no invalida sesiones ni cambia la contraseña.

La migración `0009_password_recovery` agrega columnas sin modificar contraseñas
o permisos existentes. Hacer respaldo antes de aplicarla. Una vez utilizados
los nuevos restablecimientos, no volver a una API que ignore `session_version`
sin invalidar también sus JWT: la versión antigua no conoce esa revocación.

Los tests incluyen expiración, reuso, otra cuenta, cuenta inactiva, contraseñas
inválidas, presupuesto compartido, fallos de SES, concurrencia PostgreSQL y
revocación de un WebSocket abierto. El frontend prueba validación, espera,
errores y borrado de campos sensibles. Los tests automatizados usan correo
simulado; la entrega al buzón se comprueba aparte con cuentas autorizadas.

Referencia de diseño: [recuperación de contraseña de OWASP](https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html).

## Validación del 16 de noviembre de 2026

La suite completa aprobó 769 pruebas y omitió una variante SQLite que exige
bloqueos de PostgreSQL. Después pasó una prueba adicional del recorrido completo
con dos cuentas nuevas, PostgreSQL y Redis reales y un buzón simulado: registro,
verificación, fotografías de prueba, coincidencia, reclamación, aprobación,
chat bidireccional, recuperación, nuevo ingreso, historial conservado y entrega
confirmada por ambos participantes y cerrada por el administrador. Esta prueba
no evalúa la precisión de los modelos de IA ni la entrega de correos externos.

En AWS se publicó la migración y se comprobó desde la interfaz pública una
recuperación con correo real. La contraseña anterior y el JWT previo fueron
rechazados; la cuenta conservó su ID y pudo iniciar sesión y recargar la página.
La pantalla móvil de 390 px también permitió solicitar recuperación y mostró
correctamente el rechazo de un código inválido. La segunda cuenta recibió su
correo, según confirmó la persona que realizó la prueba, pero no completó su
verificación antes del vencimiento. El recorrido completo con ambas cuentas
en producción queda pendiente; no se sustituyó esa verificación por cambios
directos en la base de datos.
