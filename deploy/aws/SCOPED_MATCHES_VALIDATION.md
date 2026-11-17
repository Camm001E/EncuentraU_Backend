# Coincidencias por reporte — 17 de noviembre de 2026

La búsqueda desde un reporte y el registro de un objeto abren una vista limitada
a ese reporte. La consulta usa `report_id` y valida su pertenencia a la cuenta;
no basta con participar en una coincidencia para consultar el reporte ajeno.
El historial general sigue disponible en Coincidencias.

La interfaz separa candidatos, descartados y cerrados. Los descartados incluyen
rechazos y comparaciones visuales con diferencias; los cerrados incluyen reportes
resueltos o cancelados. Los grupos se calculan sobre las páginas cargadas. La
tarjeta identifica el reporte propio y el comparado y presenta el puntaje como
valor sobre 100, separado de la evidencia visual.

La migración `0010_match_visual_review` conserva las comparaciones de fotos en
PostgreSQL. Cada orientación guarda su resultado, sin invertir explicaciones de
primera/segunda imagen. Cambiar una foto invalida el resultado correspondiente.
Repetir la comparación con los mismos hashes y configuración reutiliza el
resultado sin reservar cuota ni llamar de nuevo al proveedor. Una primera
comparación desde la otra cuenta puede requerir una llamada propia.

`semantic-v8` corrige una contradicción geométrica: «alargado» describe una
proporción y no contradice necesariamente «ovalado». No los convierte en
sinónimos. Contornos incompatibles siguen produciendo diferencias. No se
modificaron los pesos ni los umbrales.

El caso observado de batería portátil tenía 67 puntos históricos. Los lugares
registrados eran diferentes (uno era una fecha) y había una contradicción falsa
entre dos descripciones de un detalle inferior. La evaluación nueva elimina esa
contradicción, sin alterar el caso aceptado y cerrado. La comparación de sus fotos
con OpenAI devolvió compatibilidad visual; la segunda solicitud reutilizó el
resultado guardado. Ni el puntaje ni la similitud prueban propiedad.

Validación automatizada: 292 pruebas frontend y 237 backend aprobadas; una variante
SQLite se omite porque necesita bloqueos PostgreSQL, cuya variante sí pasó.
Incluye propiedad, paginación, categorías de visualización, persistencia, cuotas,
invalidación de fotos y preservación de decisiones históricas.

Los reportes y resultados de prueba con datos privados permanecen fuera de Git.
Los modelos de los proveedores y los cupos desactivados no se cambiaron.

La comprobación en navegador de la versión publicada pasó con dos cuentas: cada
búsqueda abrió solo el reporte seleccionado y su candidato; descartados y cerrados
quedaron separados. No hubo errores JavaScript. Los dos reportes temporales se
cancelaron al terminar, sin modificar los reportes reales.
