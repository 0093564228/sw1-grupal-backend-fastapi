import os
import uuid

MEDIA_DIR = "media"

JOB_DIR = MEDIA_DIR + "/{job_id}"

VIDEOS_DIR = JOB_DIR + "/videos"
AUDIOS_DIR = JOB_DIR + "/audios"
IMAGENES_DIR = JOB_DIR + "/imagenes"
SUBTITULOS_DIR = JOB_DIR + "/subtitulos"
BITACORA_DIR = JOB_DIR + "/bitacora"

VIDEO_ORIGINAL = VIDEOS_DIR + "/original.mp4"
VIDEO_SIN_AUDIO = VIDEOS_DIR + "/sin_audio.mp4"
VIDEO_INSTRUMENTAL = VIDEOS_DIR + "/instrumental.mp4"
VIDEO_KARAOKE = VIDEOS_DIR + "/karaoke.mp4"
VIDEO_KARAOKE_PREVIEW = VIDEOS_DIR + "/karaoke.mp4"

AUDIO_ORIGINAL = AUDIOS_DIR + "/original.wav"
AUDIO_VOCALS = AUDIOS_DIR + "/original/vocals.wav"
AUDIO_INSTRUMENTAL = AUDIOS_DIR + "/original/accompaniment.wav"

IMAGEN_THUMBNAIL = IMAGENES_DIR + "/thumbnail.jpg"

SUBTITULOS_SRT = SUBTITULOS_DIR + "/subtitulo.srt"
SUBTITULOS_ASS = SUBTITULOS_DIR + "/subtitulo.ass"

ARCHIVO_ESTADO = BITACORA_DIR + "/estado.json"
ARCHIVO_LOG = BITACORA_DIR + "/ffmpeg.log"


class Job:

    def __init__(self, job_id: str = str(uuid.uuid4())):
        self.id = job_id

        self.audio_original_file = AUDIO_ORIGINAL.format(job_id=job_id)
        self.audio_instrumental_file = AUDIO_INSTRUMENTAL.format(job_id=job_id)
        self.audio_vocals_file = AUDIO_VOCALS.format(job_id=job_id)
        
        self.video_original_file = VIDEO_ORIGINAL.format(job_id=job_id)
        self.video_sin_audio_file = VIDEO_SIN_AUDIO.format(job_id=job_id)
        self.video_instrumental_file = VIDEO_INSTRUMENTAL.format(job_id=job_id)
        self.video_karaoke_file = VIDEO_KARAOKE.format(job_id=job_id)
        self.video_karaoke_preview_file = VIDEO_KARAOKE_PREVIEW.format(job_id=job_id)

        self.imagen_thumbnail_file = IMAGEN_THUMBNAIL.format(job_id=job_id)
        
        self.subtitulos_srt_file = SUBTITULOS_SRT.format(job_id=job_id)
        self.subtitulos_ass_file = SUBTITULOS_ASS.format(job_id=job_id)

        self.log_file = ARCHIVO_LOG.format(job_id=job_id)
        self.estado_actual_file = ARCHIVO_ESTADO.format(job_id=job_id)

        self.media_dir = MEDIA_DIR
        self.job_dir = JOB_DIR.format(job_id=job_id)
        self.videos_dir = VIDEOS_DIR.format(job_id=job_id)
        self.audios_dir = AUDIOS_DIR.format(job_id=job_id)
        self.bitacora_dir = BITACORA_DIR.format(job_id=job_id)
        self.imagenes_dir = IMAGENES_DIR.format(job_id=job_id)

    def crear_directorios(self):
        os.makedirs(self.media_dir, exist_ok=True)
        os.makedirs(self.job_dir, exist_ok=True)
        os.makedirs(self.videos_dir, exist_ok=True)
        os.makedirs(self.audios_dir, exist_ok=True)
        os.makedirs(self.imagenes_dir, exist_ok=True)
        os.makedirs(self.bitacora_dir, exist_ok=True)
