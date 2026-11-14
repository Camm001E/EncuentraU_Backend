# Búsqueda por producto y envase

La revisión `semantic-v6` corrige un descarte prematuro: un reporte describía
«jabón facil» y otro «botella dispensadora de limpiador facial». Las descripciones
aportaban el mismo propósito, pero el filtro de nombres impedía mostrar el par
antes de que el usuario pudiera comparar las fotos.

El buscador consulta también el producto mencionado en la descripción cuando
uno de los títulos identifica un envase. Usa familias explícitas de productos
de cuidado personal; no utiliza la marca, el usuario o el identificador de un
reporte para activar esta regla. No corrige ni reescribe el formulario del usuario.

La regla permite recuperar una **posible coincidencia**, siempre sujeta al
umbral normal. No modifica los pesos, no suma puntos por nombres distintos y
no permite clasificar como alta una coincidencia recuperada de esta manera.
El caso observado obtiene 73 puntos con sus campos originales. Es una puntuación
de ordenación, no una probabilidad de identidad o propiedad.

Productos con propósitos explícitos distintos se descartan incluso si comparten
la palabra «botella», la marca, el color y la forma. También se contrastan usos
como facial/manos/vajilla y presentaciones explícitamente sólida/líquida. Los
textos negados o insuficientes no activan la recuperación por contexto.

Las pruebas incluyen champú, acondicionador, crema, perfume, dentífrico,
desodorante, objetos de otras familias y envases sin contenido identificado.
Dos pruebas HTTP con PostgreSQL comprueban recuperación desde ambas cuentas,
conservación de los reportes y exclusión de un producto distinto en un envase
similar. Las fotografías y resultados privados de comprobación no se versionan.

Esta corrección no implica comprensión universal de cualquier descripción.
Los casos sin evidencia suficiente todavía pueden no producir candidatos.
Compartir producto, marca y presentación tampoco demuestra que dos fotografías
correspondan al mismo ejemplar: siguen siendo necesarias la revisión visual,
la evidencia privada, la aprobación administrativa y las confirmaciones.

Tras actualizar la API, **Buscar coincidencias** recalcula los candidatos
pendientes con esta versión. Las decisiones históricas aceptadas o rechazadas
conservan sus métricas y su versión.


## Comprobación en producción

La API actualizada recuperó el mismo candidato desde las dos cuentas de prueba:
73 puntos y nivel posible. Se verificó que los campos de ambos reportes y los
hashes de sus fotografías permanecieran iguales antes y después del cálculo.
La comparación visual de las fotografías originales respondió `consistent`,
sin contradicciones estructurales y con evidencia genérica del diseño. Esto
respalda presentar el candidato, pero no identifica un ejemplar único.

Como control negativo, la fotografía del limpiador frente a una botella
deportiva respondió `different`, por diferencias de forma y cierre. Ambas
comparaciones usaron OpenAI sin fallback; no se atribuyen estos resultados a
Gemini. La regresión general terminó con 790 pruebas aprobadas y una omitida;
las dos pruebas de integración de contexto añadidas después también aprobaron.
