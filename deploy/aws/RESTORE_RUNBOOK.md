# Ensayo de restauracion aislada

Este procedimiento verifica recuperacion sin cambiar el trafico ni la base productiva. Requiere autorizacion para una base RDS temporal y elimina sus recursos al terminar.

1. Confirmar identidad AWS, perfil, region y nombre exacto de la base de EncuentraU. Anotar inicio UTC y `LatestRestorableTime`. No operar otras cuentas/proyectos.
2. Restaurar con `restore-db-instance-to-point-in-time` hacia un identificador nuevo de pruebas. Mantener clase pequena, Single-AZ, mismo grupo de subredes y seguridad, acceso publico desactivado y backups de la copia desactivados. No sustituir la base original.
3. Esperar disponibilidad. Preparar un directorio nuevo y privado en el servidor y recuperar la version del respaldo de fotos correspondiente al punto restaurado. Validar cada entrada del tar: solo archivos/directorios, sin enlaces ni rutas fuera del destino.
4. Crear un archivo de entorno modo 600 con el endpoint **restaurado**, TLS verificado, JWT nuevo y claves IA vacias. Comprobar por codigo que el hostname no sea el productivo antes de cualquier escritura de prueba.
5. Arrancar API y Redis temporales en su propia red Docker. Usar puerto ligado a `127.0.0.1`, directorio de fotos recuperado y limites de memoria. No compartir Redis, JWT, volumen de fotos ni puertos publicos con produccion.
6. Verificar version de migraciones y registros conocidos; comparar SHA256 de cada foto recuperada con PostgreSQL. Probar login de dos cuentas exclusivamente en la copia, lectura autorizada de mensajes/fotos y estado de entrega. No llamar a proveedores IA.
7. Reiniciar la API restaurada y repetir las comprobaciones. Registrar resultados sin contrasenas ni tokens.
8. Eliminar contenedores y red temporales por nombre exacto. Eliminar solo el directorio temporal previamente resuelto. Eliminar la **base restaurada** sin snapshot final y sin conservar backups automaticos. Confirmar que deja de existir.
9. Comprobar HTTPS/DB de produccion y registrar duracion/costo estimado. Los presupuestos son alertas, no un tope duro.

## Ensayo ejecutado

Se recupero una instancia PostgreSQL desde los backups administrados de RDS y las fotos desde S3 versionado. Pasaron: esquema, dos hashes de fotos, dos mensajes, entrega completada, login de dos participantes y lectura HTTP. Las mismas verificaciones pasaron despues de reiniciar la API restaurada. El entorno temporal no publico puertos ni tenia claves IA. Los recursos temporales se retiraron al terminar.

El ensayo usa el conjunto tecnico de aceptacion. Para datos reales, seleccionar un punto de base y una version de fotos coherentes. La retencion RDS actual es de un dia y las fotos se respaldan diariamente: la ventana de perdida posible no es cero. Este ensayo no demuestra alta disponibilidad ni recuperacion de una caida regional.

Referencia: [Restauracion a un punto en el tiempo](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_PIT.html).
