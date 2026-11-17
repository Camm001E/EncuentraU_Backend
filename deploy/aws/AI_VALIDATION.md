# Revisión del reconocimiento visual

Fecha: 15 de noviembre de 2026. Versión del análisis: `visual-v2`.

Este documento conserva la evaluación de esa versión. La [revisión posterior
de Gemini](GEMINI_VALIDATION.md) describe `visual-v3` y corrige la valoración
inicial sobre la piedra del anillo al comprobar su segunda fotografía.

## Cambios

Las instrucciones separan la familia visible del objeto de su uso supuesto,
contenido, marca o modelo. Se solicita otra vista cuando no se puede determinar
la familia, pero estar cerrado no obliga por sí solo a repetir la foto.
Gemini recibe la descripción como entrada del usuario, separada de las
instrucciones del sistema. Ambos proveedores rechazan una detección sin tipo y
una ausencia de objeto que no solicite otra foto. Gemini limita la salida a
8192 tokens. No cambiaron las ponderaciones ni los umbrales de coincidencia.
La normalización `semantic-v5` reconoce «bolsita con cremallera» como estuche
genérico, conservando los calificadores de uso. Así no descarta un neceser por
esa diferencia de vocabulario. La equivalencia no se aplica a bolsos, bolsas de
compras ni a una bolsita sin cierre descrito, y no demuestra identidad.

## Comprobación con fotos

Se emplearon 13 fotografías de 10 objetos, incluyendo dos vistas de algunos
objetos y descripciones deliberadamente incorrectas. Las primeras comparaciones
usaron las mismas fotos y modelos antes y después. Después se ajustaron los
casos fallidos y se volvieron a comprobar; esas repeticiones son pruebas de
desarrollo, no una medición independiente de precisión.

Hubo 91 intentos en total: 85 devolvieron un análisis y 6 fallaron. Una respuesta
válida no equivale a una identificación correcta. Los fallos originales se
conservaron aunque una repetición posterior respondiera. Tres de los fallos
corresponden a una prueba de Gemini 3.8 Flash, que no se adoptó. Los modelos
configurados siguen siendo OpenAI `gpt-5.4` y Gemini `gemini-3.5-flash-lite`.

| Caso revisado | Antes | Última comprobación de OpenAI |
| --- | --- | --- |
| Espejo cerrado, solo cara decorada | Chapa decorativa | Pieza circular decorada; pide reverso o lateral para identificarla |
| Estuche textil cerrado | Neceser o cosmetiquera, suponiendo su uso | Bolsita con cremallera, sin afirmar qué contiene o para qué se usa |
| Billetera cerrada | Billetera | Billetera, sin exigir abrirla |
| Estuche de auriculares cerrado | Estuche de carga | Conserva el estuche como objeto; no afirma que se vean los auriculares |

La revisión también incluyó botella, archivador, anillo, sacapuntas, pinza de
cabello y llaves. Gemini siguió confundiendo el frontal del espejo con una
chapa y describiendo una piedra que no se distingue en el anillo. Es una
limitación pendiente, no un acierto. OpenAI sigue como principal; el respaldo
se activa ante los fallos operativos permitidos, no como voto de confirmación.

No se calculó un porcentaje general de precisión ni se entrenó un modelo.
Las fotos y respuestas completas permanecen fuera de Git. Esta muestra no
demuestra que se pueda reconocer cualquier objeto ni distinguir dos unidades
idénticas. La evidencia visual orienta la búsqueda y no acredita propiedad.

## Regresión

Pasaron 733 pruebas del backend con PostgreSQL y Redis aislados; se omitió una
variante SQLite que requiere bloqueos de PostgreSQL. Tras el último ajuste de
instrucciones y límite de salida pasaron además las 34 pruebas de proveedores.
Estas pruebas de código usan respuestas controladas y no sustituyen las fotos
reales descritas arriba.

La corrección de vocabulario pasó otras 208 comprobaciones de coincidencias,
semántica y persistencia/versionado. Al comparar dos descripciones reales de la
misma foto del estuche, el resultado dejó de ser «incompatible» y pasó a
«posible», sin alcanzar el nivel alto. No se modificaron coincidencias cerradas.

Por HTTPS, la versión `visual-v2` respondió con OpenAI, sin fallback: reconoció
la billetera cerrada sin pedir otra foto y pidió reverso o lateral para el
objeto circular decorado. También respondieron salud de API, base de datos e
inicio de sesión con correo verificado. Estas dos llamadas de despliegue son
adicionales a los 91 intentos de la comparación local.
