"""
Módulo Karaoke: Sistema optimizado de generación de video karaoke
Usa archivos ya procesados del proyecto principal
Integrado como servicio en el backend principal
"""

import os
import json
import subprocess
import threading
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime
from dotenv import load_dotenv

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.job import MEDIA_DIR, SUBTITULOS_ASS, VIDEO_INSTRUMENTAL, VIDEO_KARAOKE, Job

# Cargar variables de entorno
load_dotenv()

# Configuración Karaoke optimizada - usar estructura del proyecto principal
KARAOKE_PRESET_X264 = os.getenv("KARAOKE_PRESET_X264", "veryfast")
KARAOKE_CRF = int(os.getenv("KARAOKE_CRF", "20"))

# Timeouts para FFmpeg (en segundos)
FFMPEG_TIMEOUT_COMPOSICION = 1800  # 30 minutos para composición final
FFMPEG_TIMEOUT_RESIZE = int(
    os.getenv("FFMPEG_TIMEOUT_RESIZE", "300")
)  # 5 minutos para resize

# Crear router para el servicio Karaoke
karaoke_router = APIRouter(prefix="/karaoke", tags=["karaoke"])

# Estados de jobs en memoria (en producción usar Redis/DB)
estados_jobs = {}


# Función utilitaria para ser llamada desde main.py
def generar_karaoke_desde_main(job: Job) -> Dict[str, Any]:
    """
    Función para ser llamada desde main.py después del procesamiento principal.
    Genera el video karaoke de forma síncrona y retorna el resultado.
    """
    try:
        # Validar que existan los archivos necesarios
        info_archivos = validar_archivos_entrada_karaoke(job)

        # Generar video karaoke
        video_karaoke = componer_video_karaoke(job)

        return {
            "success": True,
            "video_karaoke_path": video_karaoke,
            "job_id": job.id,
            "archivos_origen": info_archivos,
        }

    except HTTPException as e:
        error_msg = (
            e.detail.get("mensaje", str(e.detail))
            if isinstance(e.detail, dict)
            else str(e.detail)
        )
        return {"success": False, "error": error_msg, "job_id": job.id}
    except Exception as e:
        return {"success": False, "error": f"Error interno: {str(e)}", "job_id": job.id}


# Modelos Pydantic para respuestas
class RespuestaEjecutar(BaseModel):
    """Respuesta del endpoint ejecutar"""

    job_id: str
    status: str  # "queued", "done", "processing", "error"
    mensaje: Optional[str] = None


class RespuestaEstado(BaseModel):
    """Respuesta del endpoint estado"""

    status: str
    progreso: Optional[int] = Field(None, ge=0, le=100)
    mensaje: Optional[str] = None
    timestamp: Optional[str] = None
    error: Optional[str] = None


def get_video_resolution(path: Path):
    """Devuelve (width, height) del primer stream de video usando ffprobe."""
    try:
        # Convertir ruta a forward slashes para ffprobe en Windows
        path_str = str(path).replace("\\", "/")

        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0:s=x",
            path_str,
        ]
        out = subprocess.check_output(
            cmd, text=True, stderr=subprocess.STDOUT, timeout=10
        )
        out = out.strip()
        if not out:
            return None
        parts = out.split("x")
        if len(parts) != 2:
            return None
        return int(parts[0]), int(parts[1])
    except Exception as e:
        print(f"Warning: No se pudo obtener resolución de {path}: {e}")
        return None


def validar_archivos_entrada_karaoke(job: Job) -> Dict[str, Any]:
    """Valida que existan los archivos necesarios del proyecto principal para karaoke"""

    if not os.path.exists(job.video_instrumental_file):
        raise HTTPException(
            status_code=404,
            detail={
                "codigo": "404_VIDEO_NO_ENCONTRADO",
                "mensaje": f"No se encontró video instrumental: {job.video_instrumental_file}",
            },
        )

    if not os.path.exists(job.subtitulos_ass_file):
        raise HTTPException(
            status_code=404,
            detail={
                "codigo": "404_ASS_NO_ENCONTRADO",
                "mensaje": f"No se encontraron subtítulos ASS: {job.subtitulos_ass_file}",
            },
        )

    # Verificar tamaño del video
    tamaño_mb = os.path.getsize(job.video_instrumental_file) / (1024 * 1024)

    return {
        "video_instrumental": job.video_instrumental_file,
        "subtitulos_ass": job.subtitulos_ass_file,
        "tamaño_mb": tamaño_mb,
    }


def componer_video_karaoke(job: Job) -> Path:
    """Compone el video karaoke usando el video instrumental + subtítulos ASS"""
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        job.video_instrumental_file,  # Video instrumental (ya tiene audio)
        "-vf",
        f"subtitles={job.subtitulos_ass_file}",  # Agregar subtítulos ASS
        "-c:v",
        "libx264",
        "-preset",
        KARAOKE_PRESET_X264,
        "-crf",
        str(KARAOKE_CRF),
        "-c:a",
        "copy",  # Mantener audio sin recodificar
        job.video_karaoke_file,
    ]

    try:
        print("Incrustando subtítulos ASS con ffmpeg...")
        with open(job.log_file, "w", encoding="utf-8") as log_file:
            log_file.write(f"=== Composición final karaoke - {datetime.now()} ===\n")
            log_file.write(f"Video instrumental (usado): {job.video_instrumental_file}\n")
            log_file.write(f"Subtítulos ASS: {job.subtitulos_ass_file}\n")
            log_file.write(f"Output: {job.video_karaoke_file}\n")
            log_file.write(f"Comando: {' '.join(cmd)}\n\n")

            # Ejecutar FFmpeg con timeout
            actualizar_estado_karaoke(
                job,
                "componiendo",
                85,
                "Incrustando subtítulos y codificando video karaoke",
            )
            proceso = subprocess.run(
                cmd,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
                check=True,
                timeout=FFMPEG_TIMEOUT_COMPOSICION,
            )

        if not os.path.exists(job.video_karaoke_file):
            raise subprocess.CalledProcessError(1, cmd, "Video karaoke no generado")

        # Actualizar estado final
        actualizar_estado_karaoke(
            job, "done", 100, "Video karaoke generado exitosamente"
        )
        return job.video_karaoke_file

    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=500,
            detail={
                "codigo": "500_FFMPEG_TIMEOUT",
                "mensaje": f"Timeout en composición: proceso excedió {FFMPEG_TIMEOUT_COMPOSICION} segundos",
            },
        )
    except subprocess.CalledProcessError as e:
        # Leer el log para obtener más información del error
        error_details = f"FFmpeg falló con código {e.returncode}"
        if os.path.exists(job.log_file):
            try:
                with open(job.log_file, "r", encoding="utf-8") as f:
                    log_content = f.read()
                    error_details += f". Log: {log_content[-500:]}"
            except:
                pass

        raise HTTPException(
            status_code=500,
            detail={
                "codigo": "500_FFMPEG_ERROR",
                "mensaje": f"Error en composición de video karaoke: {error_details}",
            },
        )


def actualizar_estado_karaoke(
    job: Job, estado: str, progreso: int = 0, mensaje: str = None
):
    """Actualiza el estado del job karaoke en el archivo JSON"""

    info_estado = {
        "status": estado,
        "progreso": progreso,
        "timestamp": datetime.now().isoformat(),
        "mensaje": mensaje,
    }

    # Mantener error si existe
    archivo_estado = job.estado_actual_file
    if os.path.exists(archivo_estado):
        try:
            with open(archivo_estado, "r", encoding="utf-8") as f:
                estado_previo = json.load(f)
                if estado_previo.get("error"):
                    info_estado["error"] = estado_previo["error"]
        except:
            pass

    with open(archivo_estado, "w", encoding="utf-8") as f:
        json.dump(info_estado, f, ensure_ascii=False, indent=2)

    # También actualizar en memoria
    estados_jobs[job.id] = info_estado


def ejecutar_pipeline_karaoke(job_id: str):
    """Ejecuta el pipeline de generación de video karaoke"""
    try:
        # 1. Validar archivos de entrada del proyecto principal
        job = Job(job_id)

        # Medida de seguridad: No hacer nada si el job no existe
        if not os.path.exists(job.job_dir):
            return

        job.crear_directorios()

        actualizar_estado_karaoke(
            job, "validando_archivos", 20, "Validando archivos del proyecto principal"
        )

        info_archivos = validar_archivos_entrada_karaoke(job)

        # 2. Componer video karaoke directamente
        actualizar_estado_karaoke(
            job, "generando_video", 50, "Componiendo video karaoke"
        )

        video_karaoke = componer_video_karaoke(job)

        # 3. Finalizar
        actualizar_estado_karaoke(
            job, "done", 100, "Video karaoke generado exitosamente"
        )

    except HTTPException as e:
        # Extraer el mensaje del detalle si es un dict, sino usar el detalle completo
        if isinstance(e.detail, dict):
            mensaje_error = e.detail.get("mensaje", str(e.detail))
        else:
            mensaje_error = str(e.detail)
        actualizar_estado_error_karaoke(job, mensaje_error)
    except Exception as e:
        actualizar_estado_error_karaoke(job, f"Error interno: {str(e)}")


def actualizar_estado_error_karaoke(job: Job, mensaje_error: str):
    """Actualiza el estado a error con mensaje"""

    try:
        info_estado = {
            "status": "error",
            "progreso": 0,
            "timestamp": datetime.now().isoformat(),
            "error": mensaje_error,
            "mensaje": "Error durante el procesamiento",
        }

        with open(job.estado_actual_file, "w", encoding="utf-8") as f:
            json.dump(info_estado, f, ensure_ascii=False, indent=2)

        # También actualizar en memoria
        estados_jobs[job.id] = info_estado

    except Exception as e_interno:
        print(f"Error actualizando estado de error: {e_interno}")


def leer_estado_job_karaoke(job: Job) -> Dict[str, Any]:
    """Lee el estado actual del job desde archivo o memoria"""

    # Primero intentar leer desde archivo
    if os.path.exists(job.estado_actual_file):
        try:
            with open(job.estado_actual_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    # Fallback: buscar en memoria
    if job.id in estados_jobs:
        return estados_jobs[job.id]

    # Estado por defecto
    return {
        "status": "not_found",
        "progreso": 0,
        "timestamp": datetime.now().isoformat(),
        "mensaje": "Job no encontrado",
    }


# Endpoints principales del servicio Karaoke
@karaoke_router.post("/ejecutar/{job_id}", response_model=RespuestaEjecutar)
async def ejecutar_karaoke(job_id: str):
    """
    Endpoint karaoke: usa archivos ya generados por el proyecto principal
    """
    try:
        # 1. Resolver rutas usando la estructura del proyecto principal
        job = Job(job_id)

        # Medida de seguridad: No hacer nada si el job no existe
        if not os.path.exists(job.job_dir):
            return

        job.crear_directorios()

        # 2. Verificar si ya existe el video karaoke (idempotencia)
        if os.path.exists(job.video_karaoke_file):
            return RespuestaEjecutar(
                job_id=job_id,
                status="done",
                mensaje="Video karaoke ya generado previamente",
            )

        # 3. Verificar estado actual
        estado_actual = leer_estado_job_karaoke(job)
        if estado_actual.get("status") in [
            "processing",
            "validando_archivos",
            "generando_video",
        ]:
            return RespuestaEjecutar(
                job_id=job_id, status="processing", mensaje="Job ya en procesamiento"
            )

        # 4. Iniciar procesamiento asíncrono
        actualizar_estado_karaoke(job, "queued", 0, "Job encolado para procesamiento")

        # Ejecutar en hilo separado para no bloquear FastAPI
        hilo_procesamiento = threading.Thread(
            target=ejecutar_pipeline_karaoke, args=(job_id,), daemon=True
        )
        hilo_procesamiento.start()

        return RespuestaEjecutar(
            job_id=job_id, status="queued", mensaje="Procesamiento iniciado"
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "codigo": "500_ERROR_INTERNO",
                "mensaje": f"Error interno: {str(e)}",
            },
        )


@karaoke_router.get("/estado/{job_id}", response_model=RespuestaEstado)
async def consultar_estado_karaoke(job_id: str):
    """
    Consulta el estado de un job karaoke específico
    """
    try:
        job = Job(job_id)
        estado = leer_estado_job_karaoke(job)

        return RespuestaEstado(
            status=estado.get("status", "not_found"),
            progreso=estado.get("progreso", 0),
            mensaje=estado.get("mensaje"),
            timestamp=estado.get("timestamp"),
            error=estado.get("error"),
        )

    except Exception as e:
        return RespuestaEstado(
            status="error", mensaje=f"Error consultando estado: {str(e)}"
        )


@karaoke_router.get("/descargar/{job_id}")
async def descargar_video_karaoke(job_id: str):
    """
    Sirve el video karaoke MP4 generado para descarga
    """
    try:
        job = Job(job_id)

        if not os.path.exists(job.video_karaoke_file):
            raise HTTPException(
                status_code=404,
                detail={
                    "codigo": "404_VIDEO_NO_ENCONTRADO",
                    "mensaje": f"Video karaoke no encontrado para job {job_id}",
                },
            )

        # Verificar que el archivo es accesible
        try:
            tamaño = os.path.getsize(job.video_karaoke_file)
            if tamaño == 0:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "codigo": "404_VIDEO_VACIO",
                        "mensaje": "El video existe pero está vacío",
                    },
                )
        except OSError:
            raise HTTPException(
                status_code=500,
                detail={
                    "codigo": "500_VIDEO_INACCESIBLE",
                    "mensaje": "No se puede acceder al archivo de video",
                },
            )

        return FileResponse(
            path=job.video_karaoke_file,
            filename=f"karaoke_{job_id}.mp4",
            media_type="video/mp4",
            headers={
                "Content-Disposition": f"attachment; filename=karaoke_{job_id}.mp4"
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "codigo": "500_ERROR_DESCARGA",
                "mensaje": f"Error en descarga: {str(e)}",
            },
        )


@karaoke_router.get("/preview/{job_id}")
async def preview_video_karaoke(job_id: str):
    """
    Sirve el video karaoke para previsualización en el navegador.
    Permite reproducción directa sin descarga forzada.
    """
    try:
        job = Job(job_id)

        if not os.path.exists(job.video_karaoke_preview_file):
            raise HTTPException(
                status_code=404,
                detail={
                    "codigo": "404_VIDEO_NO_ENCONTRADO",
                    "mensaje": f"Video karaoke no encontrado para job {job_id}",
                },
            )

        # Verificar que el archivo es accesible y no está vacío
        try:
            tamaño = os.path.getsize(job.video_karaoke_preview_file)
            if tamaño == 0:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "codigo": "404_VIDEO_VACIO",
                        "mensaje": "El video existe pero está vacío",
                    },
                )
        except OSError:
            raise HTTPException(
                status_code=500,
                detail={
                    "codigo": "500_VIDEO_INACCESIBLE",
                    "mensaje": "No se puede acceder al archivo de video",
                },
            )

        # Retornar video para visualización en navegador (sin forzar descarga)
        return FileResponse(
            path=job.video_karaoke_preview_file,
            filename=f"karaoke_{job_id}_preview.mp4",
            media_type="video/mp4",
            headers={
                "Content-Disposition": f"inline; filename=karaoke_{job_id}_preview.mp4",
                "Accept-Ranges": "bytes",
                "Cache-Control": "no-cache",
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "codigo": "500_ERROR_PREVIEW",
                "mensaje": f"Error en preview: {str(e)}",
            },
        )


@karaoke_router.get("/info")
async def info_karaoke():
    """
    Información del servicio Karaoke
    """
    return {
        "servicio": "Servicio Video Karaoke",
        "version": "1.0.0",
        "descripcion": "Sistema integrado que usa archivos del proyecto principal",
        "endpoints": {
            "ejecutar": "POST /karaoke/ejecutar/{job_id}",
            "estado": "GET /karaoke/estado/{job_id}",
            "preview": "GET /karaoke/preview/{job_id}",
            "descargar": "GET /karaoke/descargar/{job_id}",
            "info": "GET /karaoke/info",
            "health": "GET /karaoke/health",
        },
        "archivos_necesarios": {
            "video_instrumental": VIDEO_INSTRUMENTAL,
            "subtitulos_ass": SUBTITULOS_ASS,
        },
        "salida": {"video_karaoke":  VIDEO_KARAOKE},
        "configuracion": {"preset_x264": KARAOKE_PRESET_X264, "crf": KARAOKE_CRF},
    }


# Health check del servicio karaoke
@karaoke_router.get("/health")
async def health_check_karaoke():
    """Health check del servicio karaoke"""
    try:
        # Verificar FFmpeg
        ffmpeg_ok = False
        try:
            subprocess.run(
                ["ffmpeg", "-version"], capture_output=True, check=True, timeout=5
            )
            ffmpeg_ok = True
        except:
            pass

        # Verificar estructura de directorios del proyecto principal
        dirs_ok = all(
            [
                Path(MEDIA_DIR).exists(),
            ]
        )

        # Verificar permisos de escritura
        write_ok = False
        try:
            test_file = Path(MEDIA_DIR + "/test_write.tmp")
            test_file.write_text("test")
            test_file.unlink()
            write_ok = True
        except:
            pass

        status = "healthy" if (ffmpeg_ok and dirs_ok and write_ok) else "unhealthy"

        return {
            "status": status,
            "checks": {
                "ffmpeg_disponible": ffmpeg_ok,
                "directorio_media_ok": dirs_ok,
                "permisos_escritura": write_ok,
            },
            "timestamp": datetime.now().isoformat(),
            "version": "1.0.0",
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat(),
        }
