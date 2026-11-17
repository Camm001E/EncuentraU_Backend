# Prueba entre dos cuentas — 16 de noviembre de 2026

Se crearon reportes de prueba separados en la aplicación publicada. Cada cuenta
describió el objeto con palabras distintas, sin marca ni análisis visual previo
en los campos de los reportes. Las fotografías provenían del conjunto autorizado.
Los reportes reales de limpiador facial no se editaron.

| Descripciones | Puntaje de búsqueda | Comparación visual ejecutada |
| --- | ---: | --- |
| Termo / botella para agua | 81, posible | No en esta ronda |
| Billetera / cartera de bolsillo | 81, posible | Incierta: caras distintas |
| Sombrilla / paraguas plegable | 84, posible | No en esta ronda |
| Cartuchera / estuche | 84, posible | Compatible, evidencia genérica |

Los cuatro pares se recuperaron desde ambas cuentas. Los 12 cruces entre objetos
distintos de este grupo se descartaron, también en ambos sentidos. Estos cruces
comprueban el filtro de candidatos; no son 12 comparaciones con un modelo visual.
Los puntajes ordenan candidatos y no representan probabilidades de propiedad.

La cartuchera fue comparada por OpenAI sin fallback. La billetera usó Gemini como
respaldo y quedó incierta: una fotografía muestra el exterior y otra el interior
y canto. No se convirtió ese resultado en una coincidencia confirmada. Para ese
caso hace falta otra foto de una misma cara visible en ambas imágenes.

## Correcciones encontradas

La normalización de plurales convertía «paraguas» en «paragua», pero la tabla de
equivalencias buscaba la forma sin normalizar. Ahora las claves se procesan como
las entradas. Se cubren también las variantes plurales de archivador y smartphone.
No se modificaron pesos, umbrales, prompts ni cuotas de los proveedores.

La exclusión de coincidencias con reclamaciones durante una actualización SQL
comparaba también filas ajenas. Ahora comprueba si el identificador del candidato
actual pertenece a una reclamación. Una reclamación ajena ya no bloquea el
recálculo. La prueba de regresión crea
un caso protegido y otro independiente, cambia un atributo del segundo y exige
que su puntuación se actualice mientras el primero permanece intacto.
La comprobación en producción reprodujo el puntaje desactualizado antes del
cambio y verificó su descenso después, con el caso cerrado intacto. Los dos
reportes técnicos usados para esta comprobación se cancelaron al finalizar.

## Recorrido comprobado

Con la cartuchera se simuló una reclamación, revisión administrativa, conversación
y entrega. No fue una entrega física ni una reclamación real de propiedad.

- Inicio de sesión de las dos cuentas verificadas.
- Fotografías privadas, candidato y comparación visual.
- Reclamación y aprobación administrativa; una cuenta normal no puede aprobar.
- Mensajes en ambos sentidos mediante HTTP y notificaciones WebSocket/Redis.
- Envío y recepción en dos sesiones de navegador separadas, sin recargar el chat.
- Reintento con el mismo identificador de mensaje sin crear duplicados.
- Historial disponible al iniciar una sesión nueva y acceso ajeno rechazado.
- Cierre bloqueado antes de obtener ambas confirmaciones.
- Segunda confirmación desde la interfaz; cierre administrativo posterior.
- Ambos reportes resueltos, eventos de auditoría y chat conservado en modo lectura.
- Nuevos mensajes rechazados después del cierre.

Los reportes de prueba que no completaron una entrega se cancelaron. El caso
completado conserva su historial identificado como prueba técnica. Los resultados
privados y las credenciales quedan fuera del repositorio.

La regresión de esta revisión aprobó 175 pruebas de coincidencias y 151 pruebas
de integración y recorrido. Se omitió la variante SQLite del nuevo caso de
recálculo porque usa bloqueos y upserts de PostgreSQL; su variante PostgreSQL
pasó. El análisis estático y la comprobación de formato de cambios también pasaron.

Esta muestra verifica esos casos y el recorrido descrito. No estima precisión
general, no prueba todas las familias de objetos y no garantiza ausencia de
errores. La coincidencia visual de un diseño tampoco identifica un ejemplar único.
