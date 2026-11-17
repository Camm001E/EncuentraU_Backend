# Cupos de inteligencia artificial

Estado desde el 16 de noviembre de 2026: los cupos internos están desactivados
para las pruebas de entrega, por decisión del responsable del proyecto.
`AI_QUOTA_ENABLED=false` omite todos los límites descritos abajo sin borrar sus
contadores. El instalador conserva esta configuración. No hay reactivación
automática programada; para habilitarlos se debe cambiar el indicador a `true`.

Los cupos de produccion se guardan en PostgreSQL; Redis y los reinicios no los reinician. Se aplican a todas las cuentas, incluido el administrador. Las transacciones bloquean los contadores en el mismo orden y reservan todos los limites juntos. Si alguno se excede, no se descuenta ninguno.

| Ambito | Unidades |
| --- | ---: |
| Por cuenta y hora | 6 |
| Por cuenta y dia | 20 |
| Toda la aplicacion por dia | 120 |
| Toda la aplicacion por mes | 1200 |

Un analisis reserva **2 unidades** (principal y posible respaldo). Una comparacion nueva reserva **3** (principal, posible respaldo y auditoria). Es una reserva conservadora: no se devuelven unidades por errores ni por usar menos proveedores. Abrir una comparacion aun vigente en cache no vuelve a descontar. La reserva ocurre despues de comprobar acceso y existencia de las fotos.

Los periodos siguen America/Bogota: hora completa, medianoche y primer dia del mes. No son ventanas moviles. Los registros expirados se conservan 40 dias adicionales y se limpian al reservar. Los limites cuentan intentos, **no dolares**: tokens, precios y facturacion de cada proveedor siguen siendo independientes de AWS.

Al agotarse el cupo, la API devuelve 429 y `Retry-After` en segundos hasta que todos los limites excedidos puedan renovarse. Si falla el registro contable, devuelve 503 sin llamar a proveedores. Los reportes, fotos existentes y mensajes siguen disponibles. No se reintenta automaticamente una operacion rechazada.

Para activar los cupos, aplicar primero `alembic upgrade head` y configurar `AI_QUOTA_ENABLED=true`. Los cuatro limites se configuran con `AI_QUOTA_USER_HOUR`, `AI_QUOTA_USER_DAY`, `AI_QUOTA_GLOBAL_DAY` y `AI_QUOTA_GLOBAL_MONTH`. No borrar los contadores para resolver incidencias.

Pruebas: concurrencia real en PostgreSQL, rollback completo al rechazar, reconexion, limite compartido entre cuentas, limite mensual, limites de calendario y bloqueo del proveedor cuando el registro falla. La comparacion cacheada no consume otra reserva.
