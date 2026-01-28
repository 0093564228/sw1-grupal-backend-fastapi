from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException, status
from typing import List
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import subprocess
import os
import uuid
import shutil
import json
import zipfile
import tempfile
from sqlalchemy.orm import Session

from app.database import SessionLocal, engine
from app.models import Base, Media, User, Project
from app.schemas import (
    UserCreate,
    UserResponse,
    LoginRequest,
    Token,
    TokenRefresh,
    ProjectCreate,
    ProjectResponse,
    ProjectBase,
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
    file: UploadFile = File(...),
    language: str = Form("auto"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    # Capturar nombre original del archivo para el nombre de salida
    original_filename = file.filename or "video"
    base_name = os.path.splitext(original_filename)[0]
    # Sanitizar nombre para evitar problemas con caracteres especiales
    base_name = "".join(
        c for c in base_name if c.isalnum() or c in (" ", "-", "_")
    ).strip()

    os.makedirs("media/videos", exist_ok=True)
    os.makedirs("media/audios", exist_ok=True)

    # Generar UUID único para toda la sesión
    session_uuid = str(uuid.uuid4())

    input_temp = f"{session_uuid}.mp4"
    output_dir = f"output_{session_uuid}"
    audio_file = f"media/audios/{session_uuid}.wav"
    video_sin_audio_file = f"media/videos/{session_uuid}_sin_audio.mp4"
    final_filename = f"{session_uuid}_sin_voces.mp4"

    try:
        with open(input_temp, "wb") as f:
            f.write(await file.read())

        subprocess.run(
            ["ffmpeg", "-i", input_temp, "-q:a", "0", "-map", "a", audio_file, "-y"],
            check=True,
        )

        subprocess.run(
            [
                "ffmpeg",
                "-i",
                input_temp,
                "-c",
                "copy",
                "-an",
                video_sin_audio_file,
                "-y",
            ],
            check=True,
        )

        db.add(
            Media(
                name=os.path.basename(audio_file),
                path=audio_file,
                format="wav",
                type="audio",
            )
        )

        db.add(
            Media(
                name=os.path.basename(video_sin_audio_file),
                path=video_sin_audio_file,
                format="mp4",
                type="video",
            )
        )

        db.commit()

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
                output_dir,
                audio_file,
            ],
            check=True,
        )
        print("Etapa: Separación de stems completada (Spleeter).")

        audio_basename = os.path.splitext(os.path.basename(audio_file))[0]
        instrumental_path = os.path.join(
            output_dir, audio_basename, "accompaniment.wav"
        )
        vocals_path = os.path.join(output_dir, audio_basename, "vocals.wav")

        if not os.path.exists(instrumental_path):
            return JSONResponse(
                {"error": "Archivo instrumental no encontrado"}, status_code=500
            )

        # Crear carpetas permanentes para archivos de audio separados
        audio_permanent_dir = os.path.join("media", "audios", session_uuid)
        os.makedirs(audio_permanent_dir, exist_ok=True)

        # Copiar archivos de audio separados a ubicación permanente
        permanent_instrumental = os.path.join(audio_permanent_dir, "accompaniment.wav")
        permanent_vocals = os.path.join(audio_permanent_dir, "vocals.wav")

        shutil.copy2(instrumental_path, permanent_instrumental)
        shutil.copy2(vocals_path, permanent_vocals)

        subprocess.run(
            [
                "ffmpeg",
                "-i",
                video_sin_audio_file,
                "-i",
                instrumental_path,
                "-c:v",
                "copy",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                final_filename,
                "-y",
            ],
            check=True,
        )

        # --- Generación de subtítulos (SRT y ASS) desde vocals.wav ---
        video_karaoke_path = None  # Inicializar aquí para scope global

        try:
            # Crear carpetas de salida para subtítulos
            os.makedirs(
                os.path.join("media", "subtitulos", "subtitulos_srt"), exist_ok=True
            )
            os.makedirs(
                os.path.join("media", "subtitulos", "subtitulos_ass"), exist_ok=True
            )

            # Usar UUID de sesión como base_id para coherencia
            base_id = session_uuid
            srt_path = os.path.join(
                "media", "subtitulos", "subtitulos_srt", f"{base_id}.srt"
            )
            ass_path = os.path.join(
                "media", "subtitulos", "subtitulos_ass", f"{base_id}.ass"
            )

            # Ejecutar WhisperX en entorno separado (venv_torch) con autodetección de idioma y device
            # Calcular ruta relativa al venv_torch desde la ubicación actual
            project_root = os.path.dirname(
                os.path.dirname(__file__)
            )  # Subir desde app/ a raíz
            venv_torch_python = os.getenv(
                "WHISPERX_PY",
                os.path.join(project_root, "venv_torch", "Scripts", "python.exe"),
            )
            audio_in = vocals_path if os.path.exists(vocals_path) else audio_file

            # Asegurar rutas absolutas y cwd=raíz del proyecto para resolver import de `app.*`
            project_root = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..")
            )
            script_path = os.path.join(project_root, "app", "whisperx_run.py")

            try:
                print(f"Iniciando WhisperX: {venv_torch_python}")
                print(f"Script: {script_path}")
                print(f"Audio: {audio_in}")
                print(f"SRT output: {srt_path}")
                print(f"Idioma: {language}")

                resultado_whisperx = subprocess.run(
                    [
                        venv_torch_python,
                        script_path,
                        "--audio",
                        audio_in,
                        "--srt",
                        srt_path,
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
                if not os.path.exists(srt_path):
                    raise FileNotFoundError(
                        f"WhisperX no generó el archivo SRT: {srt_path}"
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
            if os.path.exists(srt_path):
                try:
                    print("Etapa: Convirtiendo SRT a ASS (karaoke)...")
                    convertir_srt_a_ass(srt_path, ass_path)
                    db.add(
                        Media(
                            name=os.path.basename(srt_path),
                            path=srt_path,
                            format="srt",
                            type="subtitle",
                        )
                    )
                    print(f"Conversión SRT->ASS completada: {ass_path}")
                except Exception as e:
                    print(f"ERROR en conversión SRT->ASS: {e}")
                    raise

            # Verificar si el ASS fue creado exitosamente (lo importante para karaoke)
            if os.path.exists(ass_path):
                db.add(
                    Media(
                        name=os.path.basename(ass_path),
                        path=ass_path,
                        format="ass",
                        type="subtitle",
                    )
                )
                db.commit()

                # --- Generación automática de video karaoke ---
                try:
                    print("Etapa: Generando video karaoke (incrustando subtitles)...")
                    resultado_karaoke = generar_karaoke_desde_main(base_id)
                    if resultado_karaoke["success"]:
                        # Agregar el video karaoke a la base de datos
                        video_karaoke_path = resultado_karaoke["video_karaoke_path"]
                        db.add(
                            Media(
                                name=os.path.basename(video_karaoke_path),
                                path=video_karaoke_path,
                                format="mp4",
                                type="video_karaoke",
                            )
                        )
                        db.commit()
                        print(f"Video karaoke generado: {video_karaoke_path}")
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
                print(f"WARNING: Archivo ASS no fue generado: {ass_path}")

        except Exception as e:
            # Log detallado del error pero no interrumpir la respuesta principal
            print(f"ERROR en generación de subtítulos/karaoke: {e}")
            import traceback

            traceback.print_exc()
        # --- Fin subtítulos ---

        # Si se generó el karaoke exitosamente, descargar karaoke; sino, instrumental
        if video_karaoke_path and os.path.exists(video_karaoke_path):
            # Descargar video karaoke (final deseado) con nombre original
            return FileResponse(
                path=video_karaoke_path,
                media_type="video/mp4",
                filename=f"{base_name}_karaoke.mp4",
                headers={
                    "X-Job-ID": session_uuid,
                    "X-Video-Type": "karaoke",
                    "X-Archivos-Generados": json.dumps(
                        {
                            "video_instrumental": final_filename,
                            "subtitulos_srt": (
                                srt_path if os.path.exists(srt_path) else None
                            ),
                            "subtitulos_ass": (
                                ass_path if os.path.exists(ass_path) else None
                            ),
                            "video_karaoke": video_karaoke_path,
                        }
                    ),
                },
            )
        else:
            # Fallback: descargar video instrumental si no hay karaoke
            return FileResponse(
                path=final_filename,
                media_type="video/mp4",
                filename=f"{base_name}_instrumental.mp4",
                headers={
                    "X-Job-ID": session_uuid,
                    "X-Video-Type": "instrumental",
                    "X-Karaoke-Error": "Video karaoke no generado",
                },
            )

    except subprocess.CalledProcessError as e:
        db.rollback()
        return JSONResponse(
            {"error": f"Error procesando el video: {str(e)}"}, status_code=500
        )

    finally:
        if os.path.exists(input_temp):
            os.remove(input_temp)
        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)


@app.get("/descargar/todo/{job_id}")
async def descargar_todo(job_id: str):
    """
    Endpoint para descargar todos los archivos generados en un ZIP.

    Incluye:
    - Video karaoke procesado
    - Audio original
    - Audio vocals
    - Audio instrumental
    """
    try:
        # Verificar que existen los archivos necesarios
        files_to_zip = []

        # Video karaoke
        video_karaoke_path = f"media/videos/{job_id}_karaoke.mp4"
        if os.path.exists(video_karaoke_path):
            files_to_zip.append((video_karaoke_path, f"{job_id}_karaoke.mp4"))

        # Audio original
        audio_original_path = f"media/audios/{job_id}.wav"
        if os.path.exists(audio_original_path):
            files_to_zip.append((audio_original_path, f"{job_id}_original.wav"))

        # Audio vocals
        audio_vocals_path = f"media/audios/{job_id}/vocals.wav"
        if os.path.exists(audio_vocals_path):
            files_to_zip.append((audio_vocals_path, f"{job_id}_vocals.wav"))

        # Audio instrumental
        audio_instrumental_path = f"media/audios/{job_id}/accompaniment.wav"
        if os.path.exists(audio_instrumental_path):
            files_to_zip.append((audio_instrumental_path, f"{job_id}_instrumental.wav"))

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
    try:
        if tipo == "video_instrumental":
            file_path = f"{job_id}_sin_voces.mp4"
            media_type = "video/mp4"
            filename = f"{job_id}_instrumental.mp4"
            disposition = "attachment"
        elif tipo == "video_karaoke":
            file_path = f"media/videos/{job_id}_karaoke.mp4"
            media_type = "video/mp4"
            filename = f"{job_id}_karaoke.mp4"
            disposition = "attachment"
        elif tipo == "video_karaoke_preview":
            file_path = f"media/videos/{job_id}_karaoke.mp4"
            media_type = "video/mp4"
            filename = f"{job_id}_karaoke_preview.mp4"
            disposition = "inline"
        elif tipo == "subtitulos_srt":
            file_path = f"media/subtitulos/subtitulos_srt/{job_id}.srt"
            media_type = "text/plain"
            filename = f"{job_id}_subtitulos.srt"
            disposition = "attachment"
        elif tipo == "subtitulos_ass":
            file_path = f"media/subtitulos/subtitulos_ass/{job_id}.ass"
            media_type = "text/plain"
            filename = f"{job_id}_karaoke.ass"
            disposition = "attachment"
        elif tipo == "audio_original":
            file_path = f"media/audios/{job_id}.wav"
            media_type = "audio/wav"
            filename = f"{job_id}_original.wav"
            disposition = "attachment"
        elif tipo == "audio_vocals":
            file_path = f"media/audios/{job_id}/vocals.wav"
            media_type = "audio/wav"
            filename = f"{job_id}_vocals.wav"
            disposition = "attachment"
        elif tipo == "audio_instrumental":
            file_path = f"media/audios/{job_id}/accompaniment.wav"
            media_type = "audio/wav"
            filename = f"{job_id}_instrumental.wav"
            disposition = "attachment"
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


@app.get("/projects", response_model=List[ProjectResponse])
def get_projects(
    userId: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.id != userId:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado"
        )
    projects = db.query(Project).filter(Project.user_id == userId).all()
    return projects


@app.post("/projects", response_model=ProjectResponse)
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.id != payload.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado"
        )
    project = Project(
        name=payload.name, description=payload.description, user_id=payload.user_id
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@app.put("/projects/{id}", response_model=ProjectResponse)
def update_project(
    id: int,
    payload: ProjectBase,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.query(Project).filter(Project.id == id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Proyecto no encontrado"
        )
    if project.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado"
        )
    if payload.name is not None:
        project.name = payload.name
    if payload.description is not None:
        project.description = payload.description
    db.commit()
    db.refresh(project)
    return project


@app.delete("/projects/{id}", status_code=204)
def delete_project(
    id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.query(Project).filter(Project.id == id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Proyecto no encontrado"
        )
    if project.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado"
        )
    db.delete(project)
    db.commit()
    return
