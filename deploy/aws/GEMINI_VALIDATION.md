# Revisión del respaldo Gemini

Fecha: 15 de noviembre de 2026. Análisis `visual-v3`.

## Qué se corrigió

La aplicación ya no acepta «pin», «chapa» o «insignia» apoyándose únicamente en
un dibujo y un contorno. Si Gemini no describe un mecanismo de sujeción visible,
la respuesta conserva los rasgos observados, usa un tipo no confirmado y pide
una foto del reverso. No transforma automáticamente el objeto en un espejo.
Una negación, un alfiler dibujado o un enganche descrito como posible no sirven
como evidencia. Con un imperdible visible se conserva la identificación.

Es una comprobación limitada de la evidencia que devuelve el proveedor, no una
segunda lectura de los píxeles ni un detector universal de alucinaciones. Si el
modelo inventara el propio mecanismo, esta comprobación podría no detectarlo.
La regla no cambia anillos, billeteras, estuches ni los pesos de coincidencia.

## Corrección sobre el anillo

La segunda fotografía muestra claramente una piedra transparente rectangular
y pequeñas incrustaciones. Por tanto, llamar «inventada» a la piedra fue una
conclusión demasiado tajante basada solo en la vista trasera. Esa valoración se
retira. No se eliminan piedras reales de las descripciones para aparentar una
mejora. Las dos vistas siguen identificándose como anillo; las fotografías no
permiten certificar que el material sea oro o diamante.

## Pruebas con imágenes

La comprobación final usó diez fotografías y Gemini por separado, sin OpenAI
ni fallback. Las diez devolvieron una respuesta válida. Esto no representa un
porcentaje de precisión general: son casos de desarrollo revisados manualmente.

| Caso | Resultado observado |
| --- | --- |
| Espejo, frente decorado | Tipo no confirmado y petición del reverso; no se acepta «chapa» sin sujeción |
| Espejo, otra cara | Propuesta de espejo de bolsillo con petición de otra vista |
| Anillo, dos vistas | Anillo; conserva la piedra real, sin certificar su material |
| Pin de control con imperdible visible | Chapa; se conserva sin exigir otra foto |
| Billetera, botella, estuche textil, estuche de auriculares y pinza | Conservan su familia; la regla no los modifica |

El control del imperdible procede de la [tienda de Wikimedia](https://store.wikimedia.org/products/wikipedia-globe-buttons).
Las fotos, claves y respuestas completas se guardan fuera de Git.

## Alternativas descartadas y consumo

Se conservaron los resultados de 60 intentos con imágenes durante la revisión,
incluidos 18 errores de proveedor. Varias configuraciones de Flash completo
resolvieron mejor el frente del espejo, pero también devolvieron 429 y tiempos
de espera agotados, incluso en pruebas espaciadas. No se adoptaron. Tampoco se
contó como mejora el mero hecho de aumentar el razonamiento de Flash-Lite.

Se mantiene `gemini-3.5-flash-lite` como respaldo de OpenAI. La comprobación
funciona dentro de la llamada existente: no agrega consultas, reintentos ni
tokens generados. Siguen vigentes el límite de salida de 8192 tokens y los cupos
persistentes. No se habilitó facturación ni se ampliaron cuotas de proveedores.

## Regresión de código

Pasaron 756 pruebas con PostgreSQL y Redis aislados; se omitió una variante
SQLite que necesita bloqueos de PostgreSQL. La revisión incluye mecanismos
visibles, negados, dibujados o supuestos, y comprueba que no se añada otra llamada
al proveedor. También se corrigió una expectativa inestable de una prueba de
chat: cuando dos mensajes comparten fecha, el orden se desempata por su id,
como ya establece la paginación. No cambió el comportamiento del chat.

## Comprobación en AWS

La versión quedó publicada y respondió desde el contenedor de la API. En dos
llamadas adicionales se simuló un fallo del principal y se consultó realmente a
Gemini: el espejo pidió otra vista y el anillo conservó su gema rectangular.
Ambas respuestas registraron `fallback_used=true` y `visual-v3`. No se cambió
OpenAI como principal para los usuarios. La página, la salud de la API y la base
de datos respondieron 200, y el administrador conservó su acceso verificado.
