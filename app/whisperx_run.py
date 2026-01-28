import argparse
import os
import sys
from pathlib import Path

import torch.serialization
from torch.torch_version import TorchVersion
from omegaconf.base import Metadata
from omegaconf.listconfig import ListConfig, ContainerMetadata
from omegaconf.nodes import AnyNode
from typing import Any
from collections import defaultdict
from pyannote.audio.core.model import Introspection
from pyannote.audio.core.task import Specifications, Problem, Resolution

torch.serialization.add_safe_globals([
    ListConfig,
    ContainerMetadata,
    Any,
    list,
    defaultdict,
    dict,
    int,
    AnyNode,
    Metadata,
    TorchVersion,
    Introspection,
    Specifications,
    Problem,
    Resolution,
])

def env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


def as_int(name: str, default: int) -> int:
    try:
        value = env(name)
        return int(value) if value is not None else default
    except Exception:
        return default


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Transcribe audio en ESPAÑOL a SRT palabra a palabra con WhisperX (optimizado para Spanish)."
    )
    parser.add_argument(
        "--audio",
        required=True,
        help="Ruta del archivo de audio a transcribir (DEBE SER ESPAÑOL)",
    )
    parser.add_argument(
        "--language",
        default="auto",
        choices=["auto", "es", "en", "pt"],
        help="Idioma del audio: auto, es, en, pt",
    )
    parser.add_argument(
        "--srt",
        required=True,
        help="Ruta de salida para el archivo SRT",
    )
    parser.add_argument(
        "--device",
        default=None,
        help="Dispositivo a usar (cuda, cpu)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Modelo Whisper a usar (tiny, base, small, medium, large-v2)",
    )
    parser.add_argument(
        "--batch_size",
        type=int,
        default=None,
        help="Tamaño del batch para transcripción",
    )
    args = parser.parse_args()

    audio_path = args.audio
    srt_path = args.srt

    # Lógica de idioma
    LANGUAGE = args.language
    if LANGUAGE == "auto":
        LANGUAGE = None  # WhisperX usa None para autodetección

    # Validaciones iniciales
    if not os.path.exists(audio_path):
        print(f"ERROR: No existe el audio: {audio_path}", file=sys.stderr)
        sys.exit(2)

    if not audio_path.lower().endswith((".wav", ".mp3", ".m4a", ".flac", ".ogg")):
        print(
            f"WARNING: Archivo de audio podría no ser válido: {audio_path}",
            file=sys.stderr,
        )

    try:
        # Asegurar que la raíz del proyecto esté en sys.path para poder importar `app.*`
        project_root = Path(__file__).resolve().parents[1]
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))

        print(f"[WhisperX] Project root: {project_root}", file=sys.stderr)
        print(f"[WhisperX] Audio: {audio_path}", file=sys.stderr)
        print(f"[WhisperX] Output SRT: {srt_path}", file=sys.stderr)

        import torch

        print(
            f"[WhisperX] PyTorch disponible, CUDA: {torch.cuda.is_available()}",
            file=sys.stderr,
        )

        import whisperx

        print(f"[WhisperX] WhisperX importado correctamente", file=sys.stderr)

        from app.subtitles import segundos_a_tiempo_srt

        # 1) Device: CLI > ENV > autodetect
        device = (
            args.device
            or env("WHISPERX_DEVICE")
            or ("cuda" if torch.cuda.is_available() else "cpu")
        )
        print(f"[WhisperX] Device seleccionado: {device}", file=sys.stderr)

        # 2) Modelo: CLI > ENV > default (optimizado para español: medium)
        # Para transcripción en español, 'medium' ofrece buen balance velocidad/precisión
        # 'base' es más rápido, 'large-v2' es más preciso pero mucho más lento
        model_name = args.model or env("WHISPERX_MODEL") or "medium"
        print(f"[WhisperX] Modelo: {model_name}", file=sys.stderr)

        # 3) Compute type por device (se puede forzar por ENV)
        compute_type = env("WHISPERX_COMPUTE_TYPE")
        if not compute_type:
            compute_type = "float16" if device == "cuda" else "float32"
        print(f"[WhisperX] Compute type: {compute_type}", file=sys.stderr)

        # 4) Batch-size: CLI > ENV > default (optimizado para español)
        # Para español con modelo medium, usar batch más pequeño en CPU
        default_batch = 4 if device == "cpu" else 16
        batch_size = (
            args.batch_size
            if args.batch_size is not None
            else as_int("WHISPERX_BATCH", default_batch)
        )
        print(f"[WhisperX] Batch size: {batch_size}", file=sys.stderr)

        # 5) Idioma
        print(
            f"[WhisperX] Idioma seleccionado: {LANGUAGE if LANGUAGE else 'AUTO (detectar)'}",
            file=sys.stderr,
        )

        # 6) Limitar threads BLAS (opcional)
        omp = as_int("OMP_NUM_THREADS", 0)
        mkl = as_int("MKL_NUM_THREADS", 0)
        if omp:
            os.environ["OMP_NUM_THREADS"] = str(omp)
        if mkl:
            os.environ["MKL_NUM_THREADS"] = str(mkl)

        print(
            f"[WhisperX] Cargando modelo {model_name}...",
            file=sys.stderr,
        )
        model = whisperx.load_model(
            model_name, device, compute_type=compute_type, language=LANGUAGE
        )
        print(
            f"[WhisperX] Modelo cargado correctamente (optimizado para español)",
            file=sys.stderr,
        )

        print(f"[WhisperX] Cargando audio...", file=sys.stderr)
        audio = whisperx.load_audio(audio_path)
        print(
            f"[WhisperX] Audio cargado (duración: {len(audio) / 16000:.2f}s)",
            file=sys.stderr,
        )

        print(f"[WhisperX] Transcribiendo...", file=sys.stderr)
        result = model.transcribe(audio, batch_size=batch_size)
        print(f"[WhisperX] Transcripción completada", file=sys.stderr)

        # Obtener el idioma para alineación
        # Si LANGUAGE es None (auto), usar el idioma detectado por Whisper
        align_language = LANGUAGE if LANGUAGE else result.get("language")

        print(f"[WhisperX] Idioma detectado/usado: {align_language}", file=sys.stderr)

        print(f"[WhisperX] Alineando timestamps...", file=sys.stderr)
        align_model, metadata = whisperx.load_align_model(
            language_code=align_language,
            device=device,
        )
        aligned = whisperx.align(
            result["segments"],
            align_model,
            metadata,
            audio,
            device,
            return_char_alignments=False,
        )
        print(f"[WhisperX] Alineamiento completado", file=sys.stderr)

        word_segments = aligned.get("word_segments") or []
        print(f"[WhisperX] Palabras extraídas: {len(word_segments)}", file=sys.stderr)

        if not word_segments:
            print(f"WARNING: No se extrajeron palabras del audio", file=sys.stderr)

        lines = []
        for i, w in enumerate(word_segments, 1):
            start, end = w.get("start"), w.get("end")
            text = (w.get("word") or "").strip()
            if start is None or end is None or not text:
                continue
            lines.append(
                f"{i}\n{segundos_a_tiempo_srt(start)} --> {segundos_a_tiempo_srt(end)}\n{text}\n\n"
            )

        os.makedirs(os.path.dirname(srt_path), exist_ok=True)
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write("".join(lines))

        print(f"✓ SRT creado exitosamente: {srt_path}", file=sys.stderr)
        print(
            f"[WhisperX] device={device} model={model_name} batch={batch_size} compute_type={compute_type} language={LANGUAGE} palabras={len(word_segments)}"
        )

    except ImportError as e:
        print(f"ERROR: No se pudo importar módulo requerido: {e}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError as e:
        print(f"ERROR: Archivo no encontrado: {e}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
