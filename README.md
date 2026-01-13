# Proyecto Backend Final - Remoción de Voz y Subtítulos Multilingües (WhisperX)

## Descripción General

- Recibe un video (MP4) en un único endpoint `/procesar-video`.
- Extrae el audio (WAV) y crea un video sin audio.
- Usa Spleeter para separar el WAV en `vocals.wav` y `accompaniment.wav`.
- Reconstruye el MP4 final combinando el video original (sin audio) + `accompaniment.wav` (solo instrumental).
- Transcribe `vocals.wav` con WhisperX (en un entorno separado) para generar un SRT a nivel de palabras y lo convierte a ASS (karaoke).
- Persiste archivos multimedia intermedios y subtítulos en disco y registra metadatos en la base de datos.
- Devuelve únicamente el MP4 final (video + instrumental) al cliente.

## Estructura del Proyecto

```
app/
  main.py          # Aplicación FastAPI, endpoint único /procesar-video (llama a WhisperX mediante subprocess)
  subtitles.py     # Utilidades SRT -> ASS (sin interfaz gráfica)
  models.py        # Modelos SQLAlchemy (Media)
  database.py      # Configuración de conexión a BD
  whisperx_run.py  # CLI usado para ejecutar WhisperX
media/
  audios/          # Archivos WAV extraídos
  videos/          # Video sin audio
  subtitulos/
    subtitulos_srt/  # SRT generados (desde vocals.wav mediante WhisperX)
    subtitulos_ass/  # ASS generados (desde SRT)
pretrained_models/   # Caché de Spleeter (si está presente)
venv/                # Entorno de la API (TensorFlow, FastAPI, Spleeter)
venv_torch/          # Entorno de WhisperX (PyTorch CPU o CUDA)
```

## Requisitos

- Python 3.10 (recomendado)
- FFmpeg disponible en PATH
- PostgreSQL en ejecución y accesible
- Dependencias (instalar desde requirements.txt)
- WhisperX y PyTorch instalados en un entorno separado `venv_torch` (ver abajo)

## Variables de Entorno (.env)

```
DB_USER=postgres
DB_PASSWORD=tu_contraseña
DB_HOST=localhost
DB_PORT=5432
DB_NAME=media_db
```

## Instalación

### 1) Entorno de la API (venv)

```
py -3.10 -m venv venv
venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 2) Creación

.env:

```
DB_USER=postgres
DB_PASSWORD=tu_contraseña
DB_HOST=localhost
DB_PORT=5432
DB_NAME=media_db
```

Crea la base de datos en PostgreSQL.
ORM crea la tabla media en la base de datos.

### 3) Entorno de WhisperX (venv_torch)

Solo CPU (funciona en cualquier máquina):

```
py -3.10 -m venv venv_torch
venv_torch\Scripts\activate
python -m pip install --upgrade pip
pip install whisperx
```

## Ejecución

### Opción 1: Activar entorno virtual y ejecutar

```powershell
venv\Scripts\activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Opción 2: Ejecutar directamente con Python 3.10 del venv

```powershell
venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## API

### POST /procesar-video/

- multipart/form-data con campo `file` (MP4)
- Flujo:

  1. Guardar MP4 temporal
  2. Extraer WAV y crear video sin audio
  3. Registrar ambos en la BD
  4. Spleeter 2-stems -> `vocals.wav` y `accompaniment.wav`
  5. Reconstruir MP4 final: video(sin audio) + `accompaniment.wav`
  6. Transcribir `vocals.wav` con WhisperX (ejecuta mediante `venv_torch`) -> SRT (a nivel de palabras, autodetección de idioma si no se proporciona)
  7. Convertir SRT -> ASS (karaoke)
  8. Guardar SRT en `media/subtitulos/subtitulos_srt/` y ASS en `media/subtitulos/subtitulos_ass/`
  9. Registrar subtítulos en la BD
  10. Responder con archivo MP4 sin subitulos únicamente

- Respuesta: archivo `video/mp4` (video final sin voces)

## Configuración (variables de entorno)

`app/whisperx_run.py` soporta las siguientes variables de entorno:

- `WHISPERX_DEVICE`: `cpu`
- `WHISPERX_MODEL`: `large-v2`
- `WHISPERX_BATCH`: `16`
- `WHISPERX_COMPUTE_TYPE`: `float32`
- `REM WHISPERX_LANGUAGE`sin definir para autodetección multilingüe
- `OMP_NUM_THREADS`: `2`
- `MKL_NUM_THREADS`: `2`

## Notas

- Las carpetas temporales de salida de Spleeter `output_<uuid>` se limpian después del procesamiento.
- Los subtítulos finales permanecen en `media/subtitulos/...` con nombres que coinciden con la base del MP4 final (ej., `<uuid>_sin_voces.srt/.ass`).

##

**Resumen:** Procesa un MP4, separa voces con Spleeter, reconstruye un MP4 sin voces y genera subtítulos palabra a palabra con WhisperX ejecutado en un entorno separado (`venv_torch`). Por defecto se autodetecta el idioma (multilingüe).

## Autenticación (JWT)

El backend ahora incluye endpoints protegidos para autenticación JWT:

- `POST /register` — Registrar usuario nuevo: `{ "name": "Test", "email": "test@dominio.com", "password": "mi_clave" }`
- `POST /login` — Iniciar sesión: `{ "email": "test@dominio.com", "password": "mi_clave" }`
- `POST /refresh` — Renovar token con refresh_token.
- `GET /me` — Obtener usuario autenticado.

Todos los requests a `/procesar-video/` requieren enviar el header `Authorization: Bearer <access_token>`.

### Variables de entorno JWT

```
JWT_SECRET_KEY=alguna_clave_segura
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7
```

## CORS y headers expuestos (dev y prod)

En desarrollo se permiten los orígenes:

```
http://localhost:5173
http://127.0.0.1:5173
```

Además, se exponen los siguientes headers para que el frontend pueda leerlos:

```
X-Job-ID, X-Video-Type, X-Archivos-Generados, Content-Disposition
```

Si tu frontend en producción vive en otro dominio, agrega su origen a la lista `origins` o hazlo configurable por entorno (por ejemplo, leyendo `FRONTEND_ORIGIN` desde `.env`).

Ejemplo sugerido de variables de entorno adicionales:

```
# Origen del frontend (producción)
FRONTEND_ORIGIN=https://tu-frontend.com
```

Ajusta el middleware CORS para incluir esta variable en `allow_origins`.

## Respuesta de `/procesar-video/`: karaoke vs instrumental

El endpoint `/procesar-video/` devuelve un archivo `video/mp4`. Según disponibilidad, puede ser:

- **Karaoke** (preferido): incluye subtítulos embebidos. Se indica con header `X-Video-Type: karaoke` y se devuelve un filename sugerido terminando en `_karaoke.mp4`.
- **Instrumental** (fallback): si no se generó karaoke, devuelve el instrumental. Header `X-Video-Type: instrumental` y filename sugerido `_instrumental.mp4`.

Headers relevantes en la respuesta:

- `X-Job-ID`: identificador de la sesión/proceso para posteriores descargas.
- `X-Video-Type`: `karaoke` o `instrumental`.
- `X-Archivos-Generados`: JSON con rutas internas de archivos generados.
- `Content-Disposition`: puede estar presente para sugerir nombre de archivo; también exponer este header en CORS (ya configurado).

## Consumo recomendado desde Frontend

- Enviar `Authorization: Bearer <access_token>`.
- Leer `X-Video-Type` para asignar un nombre de descarga coherente (`<nombre>_karaoke.mp4` o `<nombre>_instrumental.mp4`).
- Leer `X-Job-ID` para habilitar descargas adicionales con endpoints `/descargar/...`.

### Requisitos Python (nuevos)

- python-jose[cryptography]
- passlib[bcrypt]
- email-validator

Incluidos ya en requirements.txt. Ejecuta:

```
pip install -r requirements.txt
```

para instalar dependencias de autenticación JWT.
