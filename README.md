# EncuentraU AI API

API de reconocimiento visual y evaluación de coincidencias entre objetos perdidos
y encontrados, sin persistencia por ahora.

## Funciones incluidas

- `GET /health`: comprueba que el servidor está disponible.
- `POST /api/v1/ai/analyze`: recibe una fotografía y una descripción.
- `POST /api/v1/matches/evaluate`: compara dos objetos y devuelve evidencias.
- Validación de JPEG, PNG y WEBP.
- Límite configurable de tamaño.
- Análisis con Gemini mediante el SDK oficial `google-genai`.
- Respuesta JSON validada con Pydantic.
- Pruebas automáticas que no consumen la API de Gemini.

## 1. Preparar el entorno

Desde la carpeta `backend`:

```bash
python -m venv .venv
```

En Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```

En Linux o macOS:

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt
```

## 2. Configurar Gemini

1. Crea una clave gratuita en Google AI Studio.
2. Copia `.env.example` como `.env`.
3. Reemplaza el valor de `GEMINI_API_KEY`.

El archivo `.env` está ignorado por Git y no debe publicarse.

## 3. Ejecutar

```bash
uvicorn app.main:app --reload --port 8000
```

Abre:

```text
http://127.0.0.1:8000/docs
```

En `POST /api/v1/ai/analyze`, selecciona **Try it out**, escribe la descripción,
elige una fotografía y ejecuta la petición.

## 4. Ejecutar pruebas

```bash
pytest
ruff check .
```

Las pruebas utilizan un analizador falso para verificar el endpoint y el contrato
JSON sin consumir cuota de Gemini.

## Contrato de salida

```json
{
  "object_detected": true,
  "object_type": "audifonos inalambricos",
  "category": "electronica",
  "primary_color": "negro",
  "secondary_colors": [],
  "brand": null,
  "shape": "intraurales con estuche rectangular",
  "visible_features": ["estuche negro"],
  "visible_text": [],
  "image_quality": "buena",
  "confidence": "alta",
  "requires_another_photo": false,
  "warnings": []
}
```

La confianza es orientativa. El usuario siempre podrá confirmar o corregir los
atributos antes de guardarlos.

## Motor de coincidencias

`POST /api/v1/matches/evaluate` recibe JSON con `lost` y `found`. Los campos de
cada objeto son opcionales; si faltan datos, el factor correspondiente aporta cero
puntos y se marca como `unknown`. Se rechazan campos adicionales y fechas inválidas
con HTTP 422.

Ejemplo para Postman (`Content-Type: application/json`):

```json
{
  "lost": {
    "object_type": "audífonos Bluetooth",
    "category": "electronica",
    "primary_color": "negro",
    "secondary_colors": [],
    "brand": "JBL",
    "shape": "estuche ovalado",
    "visible_features": ["audífonos intraurales", "estuche compacto", "puerto USB-C"],
    "visible_text": ["JBL"],
    "location": "Cafetería central",
    "event_date": "2026-09-01",
    "description": "Audífonos Bluetooth negros en estuche ovalado compacto."
  },
  "found": {
    "object_type": "auriculares inalámbricos",
    "category": "electronica",
    "primary_color": "negro",
    "secondary_colors": [],
    "brand": "JBL",
    "shape": "estuche ovalado",
    "visible_features": ["audífonos intraurales", "estuche compacto", "puerto USB-C"],
    "visible_text": ["JBL"],
    "location": "Cafetería central",
    "event_date": "2026-09-01",
    "description": "Audífonos inalámbricos negros en estuche ovalado compacto."
  }
}
```

Este ejemplo devuelve `percentage: 100`, `level: "high"`, ocho `factors` y una
lista vacía de `warnings`. Cada factor contiene `name`, `label`, `weight`, `score`,
`status` (`match`, `partial`, `different` o `unknown`) y `explanation`.

| Factor | Puntos máximos | Comparación |
| --- | ---: | --- |
| Tipo de objeto | 20 | Palabras normalizadas y sinónimos explícitos |
| Categoría | 10 | Igualdad del texto normalizado |
| Color | 12 | Principal igual: 100%; coincidencia entre colores secundarios: 50% |
| Marca | 12 | Igualdad del texto normalizado |
| Características visuales | 18 | Palabras de forma, rasgos visibles y texto visible |
| Lugar | 12 | Palabras compartidas |
| Fecha | 6 | Misma fecha: 100%; 1–3 días: 75%; 4–7: 50%; 8–14: 25% |
| Descripción | 10 | Palabras compartidas |

Las comparaciones por palabras usan intersección dividida por unión (Jaccard),
omiten artículos y preposiciones y normalizan mayúsculas, tildes y puntuación.
Hay un vocabulario pequeño y explícito para auriculares/audífonos,
Bluetooth/inalámbricos y variantes de algunos colores. No se hace inferencia
semántica ni se llama a Gemini desde este endpoint.

`percentage` es la suma redondeada de los puntos de los factores; los puntos
ausentes no se redistribuyen. Es una puntuación de evidencias, no una probabilidad
calibrada de identidad. Los niveles son `high` desde 85, `possible` desde 65 y
`low` por debajo de 65. Para obtener `high`, además debe coincidir el tipo de
objeto y no puede haber contradicciones de tipo, categoría o marca. Un hallazgo
anterior a la pérdida tampoco puede ser `high`. Por eso, una marca contradictoria
con todos los demás campos iguales devuelve 88 puntos y nivel `possible`.

Una fecha anterior a la pérdida o más de 14 días después aporta cero puntos.
Valores vacíos o marcadores como `desconocido`, `sin marca` y `no visible` no
cuentan como evidencia, aunque se repitan en ambos objetos. Las coincidencias
parciales y las contradicciones quedan visibles en los factores.

Para comparar análisis reales, copia únicamente los atributos del objeto desde
`/api/v1/ai/analyze` y añade `location`, `event_date` y `description` del reporte.
Los metadatos `object_detected`, `image_quality`, `confidence`,
`requires_another_photo` y `warnings` no forman parte de `MatchableObject`.
Si Gemini no detecta un objeto o pide otra foto, revisa el análisis antes de
evaluar coincidencias. Las pruebas del motor usan datos controlados y no validan
el reconocimiento de fotografías reales.
