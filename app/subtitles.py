"""
Módulo de subtitulos.
Permite la creación de subtitulos.
"""

import re

DEFAULT_VIDEO = {
    "width": 1920,
    "height": 1080,
    "font_size": 50,
    "margin_left": 30,
    "margin_right": 30,
    "margin_vertical": 45,
}

DEFAULT_GROUP = {
    "pause_threshold_ms": 800,
}

DEFAULT_STYLE = {
    "name": "Karaoke",
    "font": "Arial Black",
    "primary": "&H00FFFF00",
    "secondary": "&H00FF00FF",
    "outline": "&H00000000",
    "back": "&H80000000",
    "outline_width": 3,
    "shadow": 2,
    "alignment": 2,  # bottom-center
}

VOWELS = set("aeiouáéíóúüAEIOUÁÉÍÓÚÜ")


def segundos_a_tiempo_srt(segundos: float) -> str:
    """
    Convierte segundos a tiempo en formato SRT.
    """
    segundos = float(segundos)
    horas, resto = divmod(segundos, 3600)
    minutos, resto = divmod(resto, 60)
    segs, frac = divmod(resto, 1)
    return f"{horas:02.0f}:{minutos:02.0f}:{segs:02.0f},{(frac * 1000):03.0f}"


def parse_time_to_ms(time_str: str) -> int:
    """
    Convierte un tiempo en formato SRT a milisegundos.
    """
    m = re.match(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})", time_str)
    if not m:
        raise ValueError(f"Formato de tiempo inválido: {time_str}")
    h, mm, s, ms = map(int, m.groups())
    return h * 3600000 + mm * 60000 + s * 1000 + ms


def parse_srt_word_level(path: str):
    """
    Parsea un archivo SRT y devuelve una lista de palabras con sus tiempos de inicio y fin.
    """
    with open(path, "r", encoding="utf-8") as f:
        content = f.read().strip()
    blocks = re.split(r"\n\s*\n", content)
    words = []
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue
        tline = lines[1]
        m = re.match(r"([\d:,]+)\s*-->\s*([\d:,]+)", tline)
        if not m:
            continue
        start_ms = parse_time_to_ms(m.group(1))
        end_ms = parse_time_to_ms(m.group(2))
        text = " ".join(lines[2:]).strip()
        if text:
            words.append(
                {"text": text, "start_ms": start_ms, "end_ms": end_ms}
            )
    return words


def split_syllables(word: str):
    """
    Divide una palabra en sílabas.
    """
    if not word:
        return [word]
    if all(not ch.isalpha() for ch in word):
        return [word]

    parts = []
    i = 0
    n = len(word)

    def is_consonant(idx: int):
        return (
            0 <= idx < n
            and word[idx].isalpha()
            and word[idx] not in VOWELS
        )

    def is_vowel(idx: int):
        return 0 <= idx < n and word[idx] in VOWELS

    while i < n:
        j = i
        if not word[j].isalpha():
            parts.append(word[j])
            i = j + 1
            continue

        if is_consonant(j):
            if j + 1 < n:
                digraph = word[j : j + 2].lower()
                if digraph in ("ch", "ll", "rr"):
                    j += 2
                else:
                    j += 1
            else:
                j += 1

        if is_vowel(j):
            while is_vowel(j):
                j += 1
        else:
            parts.append(word[i:j])
            i = j
            continue

        if is_consonant(j) and is_consonant(j + 1):
            parts.append(word[i:j])
            i = j
        else:
            if is_consonant(j) and is_vowel(j + 1):
                parts.append(word[i:j])
                i = j
            else:
                if is_consonant(j):
                    j += 1
                parts.append(word[i:j])
                i = j

    return [p for p in parts if p]


def estimate_char_width(font_size: int) -> float:
    """
    Estima el ancho de un carácter en píxeles.
    """
    return font_size * 0.6


def available_width(cfg_video) -> float:
    """
    Calcula el ancho disponible para el texto.
    """
    return (
        cfg_video["width"]
        - cfg_video["margin_left"]
        - cfg_video["margin_right"]
    )


def should_wrap_line(current_words, next_word, cfg_video) -> bool:
    """
    Determina si se debe envolver una línea de texto.
    """
    if not current_words:
        return False
    current_text = " ".join(w["text"] for w in current_words)
    cand = f"{current_text} {next_word['text']}"
    char_w = estimate_char_width(cfg_video["font_size"])
    return len(cand) * char_w > available_width(cfg_video)


def group_words(words, cfg_video, cfg_group):
    """
    Agrupa las palabras en frases.
    """
    if not words:
        return []

    phrases = []
    current = [words[0]]

    for i in range(1, len(words)):
        prev_w = words[i - 1]
        w = words[i]
        pause = w["start_ms"] - prev_w["end_ms"]

        should_split = (
            pause > cfg_group["pause_threshold_ms"]
            or prev_w["text"].rstrip().endswith((".", "!", "?"))
            and pause > 500
            or should_wrap_line(current, w, cfg_video)
        )
        if should_split:
            if current:
                phrases.append(current)
            current = [w]
        else:
            current.append(w)

    if current:
        phrases.append(current)

    optimized = []
    i = 0
    while i < len(phrases):
        cur = phrases[i]
        if len(cur) < 4 and i + 1 < len(phrases):
            nxt = phrases[i + 1]
            pause_between = nxt[0]["start_ms"] - cur[-1]["end_ms"]
            comb = cur + nxt
            char_w = estimate_char_width(cfg_video["font_size"])
            fits = len(
                " ".join(w["text"] for w in comb)
            ) * char_w <= available_width(cfg_video)
            if pause_between < 600 and fits:
                optimized.append(comb)
                i += 2
                continue
        optimized.append(cur)
        i += 1

    return optimized


def ms_to_ass_time(ms: int) -> str:
    """
    Convierte milisegundos a tiempo en formato ASS.
    """
    h = ms // 3600000
    m = (ms % 3600000) // 60000
    s = (ms % 60000) // 1000
    cs = (ms % 1000) // 10
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def ass_header(cfg_video, style) -> str:
    """
    Genera el encabezado de un archivo de subtitulos en formato ASS.
    """
    return (
        "[Script Info]\n"
        f"Title: Karaoke\n"
        "ScriptType: v4.00+\n"
        "Collisions: Normal\n"
        "PlayDepth: 0\n"
        "Timer: 100.0000\n"
        f"Video Aspect Ratio: {cfg_video['width']}:{cfg_video['height']}\n"
        "WrapStyle: 0\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: {style['name']},{style['font']},{cfg_video['font_size']},"
        f"{style['primary']},{style['secondary']},"
        f"{style['outline']},{style['back']},1,0,0,0,100,100,0,0,1,"
        f"{style['outline_width']},{style['shadow']},"
        f"{style['alignment']},{cfg_video['margin_left']},"
        f"{cfg_video['margin_right']},{cfg_video['margin_vertical']},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, "
        "MarginR, MarginV, Effect, Text\n"
    )


def ass_line(phrase_words, _cfg_video) -> str:
    """
    Genera una línea de subtitulos en formato ASS.
    """
    start_ms = phrase_words[0]["start_ms"]
    end_ms = phrase_words[-1]["end_ms"]
    start = ms_to_ass_time(start_ms)
    end = ms_to_ass_time(end_ms)

    def has_letters(tok: str) -> bool:
        return any(ch.isalpha() for ch in tok)

    karaoke_text = ""
    for idx, w in enumerate(phrase_words):
        dur_cs = max(0, round((w["end_ms"] - w["start_ms"]) / 10))
        tokens = split_syllables(w["text"]) or [w["text"]]
        timed_tokens = [t for t in tokens if has_letters(t)]
        timed_total_chars = sum(len(t) for t in timed_tokens)

        if timed_total_chars == 0:
            first = True
            for tok in tokens:
                if first and dur_cs > 0:
                    karaoke_text += f"{{\\kf{dur_cs}}}{tok}"
                    first = False
                else:
                    karaoke_text += f"{{\\kf0}}{tok}"
        else:
            allocated_cs = 0
            remaining_timed = sum(1 for t in tokens if has_letters(t))
            for tok in tokens:
                if has_letters(tok):
                    remaining_timed -= 1
                    if remaining_timed == 0:
                        cs = (
                            max(1, dur_cs - allocated_cs)
                            if dur_cs > 0
                            else 0
                        )
                    else:
                        exact = dur_cs * (
                            len(tok) / (timed_total_chars or 1)
                        )
                        cs = max(1, round(exact)) if dur_cs > 0 else 0
                    allocated_cs += cs
                    karaoke_text += f"{{\\kf{cs}}}{tok}"
                else:
                    karaoke_text += f"{{\\kf0}}{tok}"

        if idx < len(phrase_words) - 1:
            nxt = phrase_words[idx + 1]
            pause_ms = max(0, nxt["start_ms"] - w["end_ms"])
            pause_cs = max(0, round(pause_ms / 10))
            karaoke_text += f"{{\\kf{pause_cs}}} "

    return f"Dialogue: 0,{start},{end},Karaoke,,0,0,0,,{karaoke_text}"


def write_ass(phrases, output_path: str, cfg_video, style) -> None:
    """
    Escribe las frases en un archivo de subtitulos en formato ASS.
    """
    header = ass_header(cfg_video, style)
    lines = [ass_line(p, cfg_video) for p in phrases]
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(lines))


def convertir_srt_a_ass(
    srt_path: str,
    ass_output: str,
    cfg_video=None,
    cfg_group=None,
    style=None,
):
    """
    Convierte un archivo SRT a un archivo ASS.
    """
    cfg_video = cfg_video or DEFAULT_VIDEO
    cfg_group = cfg_group or DEFAULT_GROUP
    style = style or DEFAULT_STYLE

    words = parse_srt_word_level(srt_path)
    if not words:
        raise ValueError("El SRT no contiene palabras válidas.")

    phrases = group_words(words, cfg_video, cfg_group)
    write_ass(phrases, ass_output, cfg_video, style)

    return {
        "phrases": len(phrases),
        "words": len(words),
        "ass": ass_output,
    }
