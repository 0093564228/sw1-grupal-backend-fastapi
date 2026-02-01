from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException, status, BackgroundTasks

from typing import List
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import subprocess
import os
import json
import zipfile
import tempfile
import shutil
from sqlalchemy.orm import Session

from app.database import engine
from app.models import Base, User, Album, Video
from app.schemas import (
    UserCreate,
    UserResponse,
    LoginRequest,
    Token,
    TokenRefresh,
    AlbumCreate,
    AlbumResponse,
    AlbumBase,
    VideoResponse,
    VideoUpdate,
)
from app.auth import (
    get_password_hash,
    authenticate_user,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    get_db,
)
from app.subtitles import convertir_srt_a_ass, segundos_a_tiempo_srt
from app.karaoke import karaoke_router, generar_karaoke_desde_main

from app.job import Job

Base.metadata.create_all(bind=engine)

app = FastAPI()

origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "X-Job-ID",
        "X-Video-Type",
        "X-Archivos-Generados",
        "Content-Disposition",
    ],
)

app.include_router(karaoke_router)


@app.get("/")
def root():
    return {"message": "Backend running", "docs": "/docs", "redoc": "/redoc"}


@app.post("/register", response_model=UserResponse)
def register(user: UserCreate, db: Session = Depends(get_db)):
    existing_user = db.query(User).filter(User.email == user.email).first()
    if existing_user:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered"
        )
    hashed_password = get_password_hash(user.password)
    db_user = User(name=user.name, email=user.email, password=hashed_password)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


@app.post("/login", response_model=Token)
def login(login_data: LoginRequest, db: Session = Depends(get_db)):
    user = authenticate_user(db, login_data.email, login_data.password)
    if not user:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = create_refresh_token(data={"sub": str(user.id)})
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


@app.post("/refresh", response_model=Token)
def refresh_token(token_data: TokenRefresh):
    payload = decode_token(token_data.refresh_token)
    if payload.get("type") != "refresh":
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type"
        )
    user_id = payload.get("sub")
    if user_id is None:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )
    access_token = create_access_token(data={"sub": user_id})
    refresh_token = create_refresh_token(data={"sub": user_id})
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


@app.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@app.post("/procesar-video/")
async def procesar_video(
    album_id: int = Form(...),
    file: UploadFile = File(...),
    language: str = Form("auto"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
): 
    # Validar que el album existe y pertenece al usuario
    album = db.query(Album).filter(Album.id == album_id).first()
    if not album:
        raise HTTPException(status_code=404, detail="Álbum no encontrado")
    if album.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No autorizado para este álbum")

    # Capturar nombre original del archivo para el nombre de salida
    original_filename = file.filename or "video"
    base_name = os.path.splitext(original_filename)[0]
    # Sanitizar nombre para evitar problemas con caracteres especiales
    base_name = "".join(
        c for c in base_name if c.isalnum() or c in (" ", "-", "_")
    ).strip()

    # Generar UUID único para toda la sesión
    job = Job()
    job.crear_directorios()

    try:
        with open(job.video_original_file, "wb") as f:
            f.write(await file.read())

        # Obtener audio (original)
        subprocess.run(
            ["ffmpeg", "-i", job.video_original_file, "-q:a", "0", "-map", "a", job.audio_original_file, "-y"],
            check=True,
        )

        # Obtener video (sin audio)
        subprocess.run(
            [
                "ffmpeg",
                "-i",
                job.video_original_file,
                "-c",
                "copy",
                "-an",
                job.video_sin_audio_file,
                "-y",
            ],
            check=True,
        )

        # Obtener duración del video usando ffprobe
        duration_in_seconds = 0
        try:
            probe = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    job.video_original_file,
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            duration_in_seconds = int(float(probe.stdout.strip()))
        except Exception as e:
            print(f"Error obteniendo duración: {e}")

        # Crear entidad Video
        video_entity = Video(
            name=base_name,
            job_id=job.id,
            duration_in_seconds=duration_in_seconds,
            format="mp4",
            album_id=album_id,
        )
        db.add(video_entity)
        db.commit()
        db.refresh(video_entity)

        # Generar Thumbnail
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-ss",
                    "00:00:05",
                    "-i",
                    job.video_original_file,
                    "-vframes",
                    "1",
                    job.imagen_thumbnail_file,
                    "-y",
                ],
                check=True,
            )

        except Exception as e:
            print(f"Error generando thumbnail: {e}")

        # Usar ruta completa del ejecutable spleeter en el entorno virtual
        project_root = os.path.dirname(os.path.dirname(__file__))  # Raíz del proyecto
        spleeter_executable = os.path.join(
            project_root, "venv", "Scripts", "spleeter.exe"
        )

        subprocess.run(
            [
                spleeter_executable,
                "separate",
                "-p",
                "spleeter:2stems",
                "-o",
                job.audios_dir,
                job.audio_original_file,
            ],
            check=True,
        )
        print("Etapa: Separación de stems completada (Spleeter).")

        if not os.path.exists(job.audio_instrumental_file):
            return JSONResponse(
                {"error": "Archivo de audio instrumental no encontrado"}, status_code=500
            )

        subprocess.run(
            [
                "ffmpeg",
                "-i",
                job.video_sin_audio_file,
                "-i",
                job.audio_instrumental_file,
                "-c:v",
                "copy",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                job.video_instrumental_file,
                "-y",
            ],
            check=True,
        )

        # --- Generación de subtítulos (SRT y ASS) desde vocals.wav ---

        try:
            # Ejecutar WhisperX en entorno separado (venv_torch) con autodetección de idioma y device
            # Calcular ruta relativa al venv_torch desde la ubicación actual
            project_root = os.path.dirname(
                os.path.dirname(__file__)
            )  # Subir desde app/ a raíz
            venv_torch_python = os.getenv(
                "WHISPERX_PY",
                os.path.join(project_root, "venv_torch", "Scripts", "python.exe"),
            )
            audio_in = job.audio_vocals_file if os.path.exists(job.audio_vocals_file) else job.audio_original_file

            # Asegurar rutas absolutas y cwd=raíz del proyecto para resolver import de `app.*`
            project_root = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..")
            )
            script_path = os.path.join(project_root, "app", "whisperx_run.py")

            try:
                print(f"Iniciando WhisperX: {venv_torch_python}")
                print(f"Script: {script_path}")
                print(f"Audio: {audio_in}")
                print(f"SRT output: {job.subtitulos_srt_file}")
                print(f"Idioma: {language}")

                resultado_whisperx = subprocess.run(
                    [
                        venv_torch_python,
                        script_path,
                        "--audio",
                        audio_in,
                        "--srt",
                        job.subtitulos_srt_file,
                        "--language",
                        language,
                    ],
                    check=False,  # No lanzar excepción, capturar el código
                    cwd=project_root,
                    capture_output=True,
                    text=True,
                )

                if resultado_whisperx.returncode != 0:
                    print(f"ERROR WhisperX - Código: {resultado_whisperx.returncode}")
                    print(f"STDOUT:\n{resultado_whisperx.stdout}")
                    print(f"STDERR:\n{resultado_whisperx.stderr}")
                    raise subprocess.CalledProcessError(
                        resultado_whisperx.returncode,
                        "whisperx_run.py",
                        output=resultado_whisperx.stdout,
                        stderr=resultado_whisperx.stderr,
                    )

                print("Etapa: Transcripción completada (WhisperX) y SRT generado.")

                # Verificar que el SRT fue creado
                if not os.path.exists(job.subtitulos_srt_file):
                    raise FileNotFoundError(
                        f"WhisperX no generó el archivo SRT: {job.subtitulos_srt_file}"
                    )

            except subprocess.CalledProcessError as e:
                print(f"ERROR: WhisperX falló")
                print(f"Código de error: {e.returncode}")
                if e.stderr:
                    print(f"STDERR: {e.stderr}")
                raise
            except FileNotFoundError as e:
                print(f"ERROR: {e}")
                raise

            # Intentar convertir SRT -> ASS (karaoke) si el SRT existe
            if os.path.exists(job.subtitulos_srt_file):
                try:
                    print("Etapa: Convirtiendo SRT a ASS (karaoke)...")
                    convertir_srt_a_ass(job.subtitulos_srt_file, job.subtitulos_ass_file)
                    print(f"Conversión SRT->ASS completada: {job.subtitulos_ass_file}")
                except Exception as e:
                    print(f"ERROR en conversión SRT->ASS: {e}")
                    raise

            # Verificar si el ASS fue creado exitosamente (lo importante para karaoke)
            if os.path.exists(job.subtitulos_ass_file):
                # --- Generación automática de video karaoke ---
                try:
                    print("Etapa: Generando video karaoke (incrustando subtitles)...")
                    resultado_karaoke = generar_karaoke_desde_main(job)
                    if resultado_karaoke["success"]:
                        # Agregar el video karaoke a la base de datos
                        print(f"Video karaoke generado: {job.video_karaoke_file}")
                    else:
                        print(
                            f"Error generando karaoke: {resultado_karaoke.get('error', 'Error desconocido')}"
                        )
                except Exception as e:
                    # No interrumpir el flujo principal si falla el karaoke
                    print(f"Warning: No se pudo generar video karaoke: {e}")
                    import traceback

                    traceback.print_exc()
                # --- Fin generación karaoke ---
            else:
                print(f"WARNING: Archivo ASS no fue generado: {job.subtitulos_ass_file}")

        except Exception as e:
            # Log detallado del error pero no interrumpir la respuesta principal
            print(f"ERROR en generación de subtítulos/karaoke: {e}")
            import traceback

            traceback.print_exc()
        # --- Fin subtítulos ---

        # Si se generó el karaoke exitosamente, descargar karaoke; sino, instrumental
        if os.path.exists(job.video_karaoke_file):
            # Descargar video karaoke (final deseado) con nombre original
            return FileResponse(
                path=job.video_karaoke_file,
                media_type="video/mp4",
                filename=f"{base_name}_karaoke.mp4",
                headers={
                    "X-Job-ID": job.id,
                    "X-Video-Type": "karaoke",
                    "X-Archivos-Generados": json.dumps(
                        {
                            "video_instrumental": job.video_instrumental_file,
                            "subtitulos_srt": (
                                job.subtitulos_srt_file if os.path.exists(job.subtitulos_srt_file) else None
                            ),
                            "subtitulos_ass": (
                                job.subtitulos_ass_file if os.path.exists(job.subtitulos_ass_file) else None
                            ),
                            "video_karaoke": job.video_karaoke_file,
                        }
                    ),
                },
            )
        else:
            # Fallback: descargar video instrumental si no hay karaoke
            return FileResponse(
                path=job.video_instrumental_file,
                media_type="video/mp4",
                filename=f"{base_name}_instrumental.mp4",
                headers={
                    "X-Job-ID": job.id,
                    "X-Video-Type": "instrumental",
                    "X-Karaoke-Error": "Video karaoke no generado",
                },
            )

    except subprocess.CalledProcessError as e:
        db.rollback()
        return JSONResponse(
            {"error": f"Error procesando el video: {str(e)}"}, status_code=500
        )


def eliminar_archivo(path: str):
    """Delete the file if it exists."""
    try:
        if os.path.exists(path):
            os.remove(path)
            print(f"Deleted temp file: {path}")
    except Exception as e:
        print(f"Error deleting file {path}: {e}")


@app.get("/descargar/todo/{job_id}")
async def descargar_todo(job_id: str, background_tasks: BackgroundTasks):
    """
    Endpoint para descargar todos los archivos generados en un ZIP.

    Incluye:
    - Video karaoke procesado
    - Audio original
    - Audio vocals
    - Audio instrumental
    """
    temp_zip_path = ""

    try:
        # Verificar que existen los archivos necesarios
        files_to_zip = []

        job = Job(job_id)

        # Video karaoke
        if os.path.exists(job.video_karaoke_file):
            files_to_zip.append((job.video_karaoke_file, f"{job_id}_karaoke.mp4"))

        # Audio original
        if os.path.exists(job.audio_original_file):
            files_to_zip.append((job.audio_original_file, f"{job_id}_original.wav"))

        # Audio vocals
        if os.path.exists(job.audio_vocals_file):
            files_to_zip.append((job.audio_vocals_file, f"{job_id}_vocals.wav"))

        # Audio instrumental
        if os.path.exists(job.audio_instrumental_file):
            files_to_zip.append((job.audio_instrumental_file, f"{job_id}_instrumental.wav"))

        if not files_to_zip:
            return JSONResponse(
                {"error": "No se encontraron archivos para descargar"}, status_code=404
            )

        # Crear ZIP temporal
        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as temp_zip:
            temp_zip_path = temp_zip.name

            with zipfile.ZipFile(temp_zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                for file_path, filename in files_to_zip:
                    if os.path.exists(file_path):
                        zipf.write(file_path, filename)

            # Asegurarse de que el ZIP es eliminado después de retornarlo
            background_tasks.add_task(eliminar_archivo, temp_zip_path)

            # Retornar el ZIP
            return FileResponse(
                path=temp_zip_path,
                media_type="application/zip",
                filename=f"{job_id}_completo.zip",
                headers={
                    "Content-Disposition": f"attachment; filename={job_id}_completo.zip"
                },
            )

    except Exception as e:
        eliminar_archivo(temp_zip_path)
        return JSONResponse({"error": f"Error creando ZIP: {str(e)}"}, status_code=500)


@app.get("/descargar/{tipo}/{job_id}")
async def descargar_archivo(tipo: str, job_id: str):
    """
    Endpoint para descargar archivos generados durante el procesamiento.

    Tipos disponibles:
    - video_instrumental: Video sin voces
    - video_karaoke: Video karaoke con subtítulos
    - video_karaoke_preview: Vista previa del video karaoke (inline)
    - subtitulos_srt: Subtítulos en formato SRT
    - subtitulos_ass: Subtítulos en formato ASS para karaoke
    - audio_original: Audio original del video
    - audio_vocals: Solo las voces extraídas
    - audio_instrumental: Solo la música de fondo
    """
    job = Job(job_id)
    try:
        if tipo == "video_instrumental":
            file_path = job.video_instrumental_file
            media_type = "video/mp4"
            filename = f"{job_id}_instrumental.mp4"
            disposition = "attachment"
        elif tipo == "video_karaoke":
            file_path = job.video_karaoke_file
            media_type = "video/mp4"
            filename = f"{job_id}_karaoke.mp4"
            disposition = "attachment"
        elif tipo == "video_karaoke_preview":
            file_path = job.video_karaoke_preview_file
            media_type = "video/mp4"
            filename = f"{job_id}_karaoke_preview.mp4"
            disposition = "inline"
        elif tipo == "subtitulos_srt":
            file_path = job.subtitulos_srt_file
            media_type = "text/plain"
            filename = f"{job_id}_subtitulos.srt"
            disposition = "attachment"
        elif tipo == "subtitulos_ass":
            file_path = job.subtitulos_ass_file
            media_type = "text/plain"
            filename = f"{job_id}_karaoke.ass"
            disposition = "attachment"
        elif tipo == "audio_original":
            file_path = job.audio_original_file
            media_type = "audio/wav"
            filename = f"{job_id}_original.wav"
            disposition = "attachment"
        elif tipo == "audio_vocals":
            file_path = job.audio_vocals_file
            media_type = "audio/wav"
            filename = f"{job_id}_vocals.wav"
            disposition = "attachment"
        elif tipo == "audio_instrumental":
            file_path = job.audio_instrumental_file
            media_type = "audio/wav"
            filename = f"{job_id}_instrumental.wav"
            disposition = "attachment"
        elif tipo == "thumbnail":
            file_path = job.imagen_thumbnail_file
            media_type = "image/jpeg"
            filename = f"{job_id}_thumbnail.jpg"
            disposition = "inline"
        else:
            return JSONResponse({"error": "Tipo de archivo no válido"}, status_code=400)

        if not os.path.exists(file_path):
            return JSONResponse(
                {"error": f"Archivo {tipo} no encontrado para job {job_id}"},
                status_code=404,
            )

        headers = {"Content-Disposition": f"{disposition}; filename={filename}"}

        # Para preview, agregar headers adicionales para mejor reproducción
        if tipo == "video_karaoke_preview":
            headers.update({"Accept-Ranges": "bytes", "Cache-Control": "no-cache"})

        return FileResponse(
            path=file_path, media_type=media_type, filename=filename, headers=headers
        )

    except Exception as e:
        return JSONResponse(
            {"error": f"Error descargando archivo: {str(e)}"}, status_code=500
        )


@app.get("/albums/{id}/videos")
def get_album_videos(
    id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    album = db.query(Album).filter(Album.id == id).first()
    if not album:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Álbum no encontrado"
        )
    if album.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado"
        )
    
    return album.videos


@app.get("/videos/{job_id}", response_model=VideoResponse)
def get_video(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    video = db.query(Video).filter(Video.job_id == job_id).first()
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Video no encontrado"
        )
    # Verificar que el álbum del video pertenezca al usuario del video (acceso indirecto)
    # OJO: La tabla Video no tiene user_id directo, se accede via álbum.
    album = db.query(Album).filter(Album.id == video.album_id).first()
    if not album or album.user_id != current_user.id:
        raise HTTPException(
             status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado"
        )
    return video


@app.put("/videos/{job_id}/album", response_model=VideoResponse)
def move_video_album(
    job_id: str,
    target_album_id: int = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    video = db.query(Video).filter(Video.job_id == job_id).first()
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Video no encontrado"
        )

    # Verificar propiedad del video actual
    current_album = db.query(Album).filter(Album.id == video.album_id).first()
    if not current_album or current_album.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado para este video"
        )

    # Verificar existencia y propiedad del álbum destino
    target_album = db.query(Album).filter(Album.id == target_album_id).first()
    if not target_album:
        raise HTTPException(
             status_code=status.HTTP_404_NOT_FOUND, detail="Álbum destino no encontrado"
        )
    if target_album.user_id != current_user.id:
        raise HTTPException(
             status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado para el álbum destino"
        )

    video.album_id = target_album_id
    db.commit()
    db.refresh(video)
    return video


@app.put("/videos/{job_id}", response_model=VideoResponse)
def update_video(
    job_id: str,
    payload: VideoUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    video = db.query(Video).filter(Video.job_id == job_id).first()
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Video no encontrado"
        )
    
    # Verificar propiedad (via álbum)
    album = db.query(Album).filter(Album.id == video.album_id).first()
    if not album or album.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado"
        )

    if payload.name is not None:
        video.name = payload.name

    db.commit()
    db.refresh(video)
    return video


@app.delete("/videos/{job_id}", status_code=204)
def delete_video(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    video = db.query(Video).filter(Video.job_id == job_id).first()
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Video no encontrado"
        )

    # Verificar propiedad (via álbum)
    album = db.query(Album).filter(Album.id == video.album_id).first()
    if not album or album.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado"
        )

    # 1. Eliminar directorio físico (media/{job_id})
    if video.job_id:
        try:
            job_instance = Job(video.job_id)
            if os.path.exists(job_instance.job_dir):
                shutil.rmtree(job_instance.job_dir)
                print(f"Directorio eliminado: {job_instance.job_dir}")
            else:
                print(f"Directorio no encontrado: {job_instance.job_dir}")
        except Exception as e:
            print(f"Error eliminando directorio físico: {e}")
            # No bloqueamos la eliminación de la DB, pero logueamos error

    # 2. Eliminar de la base de datos
    db.delete(video)
    db.commit()
    return



@app.get("/albums", response_model=List[AlbumResponse])
def get_albums(
    userId: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.id != userId:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado"
        )
    albums = db.query(Album).filter(Album.user_id == userId).all()
    return albums


@app.post("/albums", response_model=AlbumResponse)
def create_album(
    payload: AlbumCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.id != payload.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado"
        )
    album = Album(
        name=payload.name, description=payload.description, user_id=payload.user_id
    )
    db.add(album)
    db.commit()
    db.refresh(album)
    return album

@app.get("/albums/{id}", response_model=AlbumResponse)
def read_album(
    id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    album = db.query(Album).filter(Album.id == id).first()
    if not album:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Álbum no encontrado"
        )
    if album.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado"
        )
    return album

@app.put("/albums/{id}", response_model=AlbumResponse)
def update_album(
    id: int,
    payload: AlbumBase,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    album = db.query(Album).filter(Album.id == id).first()
    if not album:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Álbum no encontrado"
        )
    if album.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado"
        )
    if payload.name is not None:
        album.name = payload.name
    if payload.description is not None:
        album.description = payload.description
    db.commit()
    db.refresh(album)
    return album


@app.delete("/albums/{id}", status_code=204)
def delete_album(
    id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    album = db.query(Album).filter(Album.id == id).first()
    if not album:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Álbum no encontrado"
        )
    if album.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado"
        )
    db.delete(album)
    db.commit()
    return
