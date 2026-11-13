"""
Motor Híbrido de Transcripción de Voz (STT) para SignBridge Extended.

Provee respaldo robusto cuando la Web Speech API del navegador falla
(errores 'network', navegadores sin soporte, Android WebView o HTTP local):
1. Transcripción de audio grabado en el navegador/móvil (WebM/OGG/WAV/MP4) vía Gemini Audio.
2. Grabación directa desde el micrófono del PC con `sounddevice` + auto-corte por silencio (VAD)
   y parada manual, transcrita vía Gemini Audio (online) o Windows Speech Recognition (offline).
"""

from __future__ import annotations

import io
import os
import subprocess
import tempfile
import threading
import time
import wave
from typing import Any, Dict, Optional

import numpy as np

try:
    import sounddevice as sd
except Exception:
    sd = None

try:
    from google.genai import types
except Exception:
    types = None


def _pcm_int16_to_wav_bytes(pcm_data: np.ndarray, sample_rate: int = 16000) -> bytes:
    """Convierte un arreglo int16 mono a bytes WAV válidos en memoria."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data.tobytes())
    return buf.getvalue()


def _transcribe_with_gemini(
    audio_bytes: bytes,
    mime_type: str,
    gemini_classifier: Any,
) -> Optional[str]:
    """Transcribe audio en español usando el cliente google-genai configurado en el pipeline."""
    if not gemini_classifier or not getattr(gemini_classifier, "api_key", None) or types is None:
        return None
    client = getattr(gemini_classifier, "_client", None) or getattr(gemini_classifier, "client", None)
    if client is None:
        try:
            init_fn = getattr(gemini_classifier, "_init_client", None)
            if callable(init_fn):
                init_fn()
            client = getattr(gemini_classifier, "_client", None)
        except Exception:
            client = None
    if client is None:
        return None

    model_name = getattr(gemini_classifier, "model_name", "gemini-3.5-flash-lite") or "gemini-3.5-flash-lite"
    prompt = (
        "Transcribe exactamente lo que dice la persona en este audio en español. "
        "Devuelve ÚNICAMENTE el texto hablado, sin comillas, sin explicaciones ni etiquetas. "
        "Si solo hay silencio o ruido sin palabras claras, responde exactamente: [SILENCIO]"
    )
    clean_mime = (mime_type or "audio/webm").split(";")[0].strip()

    models_to_try = [model_name]
    for fb in ("gemini-3.5-flash-lite", "gemini-2.5-flash-lite", "gemini-2.5-flash"):
        if fb not in models_to_try:
            models_to_try.append(fb)

    for candidate_model in models_to_try:
        try:
            response = client.models.generate_content(
                model=candidate_model,
                contents=[
                    types.Part.from_bytes(data=audio_bytes, mime_type=clean_mime),
                    prompt,
                ],
                config=types.GenerateContentConfig(temperature=0.0),
            )
            text = (response.text or "").strip()
            if not text or "[SILENCIO]" in text.upper():
                return ""
            return text.strip("\"' ")
        except Exception as exc:
            err = str(exc)
            if "404" in err or "NOT_FOUND" in err or "429" in err or "RESOURCE_EXHAUSTED" in err:
                continue
            return None
    return None


def _transcribe_wav_windows_offline(wav_bytes: bytes) -> Optional[str]:
    """Respaldo offline en Windows usando System.Speech.Recognition sobre un archivo WAV."""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            tf.write(wav_bytes)
            tmp_path = tf.name

        ps_script = (
            "Add-Type -AssemblyName System.Speech; "
            "$culture = [System.Globalization.CultureInfo]::GetCultureInfo('es-ES'); "
            "try { $rec = New-Object System.Speech.Recognition.SpeechRecognitionEngine($culture) } "
            "catch { $rec = New-Object System.Speech.Recognition.SpeechRecognitionEngine }; "
            "$rec.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar)); "
            f"$rec.SetInputToWaveFile('{tmp_path.replace(chr(39), chr(39)*2)}'); "
            "$res = $rec.Recognize(); "
            "if ($res -ne $null) { Write-Output $res.Text }"
        )
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=10.0,
            creationflags=creationflags,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    except Exception:
        pass
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
    return None


def transcribe_audio_bytes(
    audio_bytes: bytes,
    mime_type: str,
    gemini_classifier: Any,
) -> Dict[str, Any]:
    """Transcribe bytes de audio recibidos desde el navegador o el teléfono."""
    if not audio_bytes or len(audio_bytes) < 256:
        return {"ok": False, "text": "", "error": "Audio demasiado corto o vacío."}

    text = _transcribe_with_gemini(audio_bytes, mime_type, gemini_classifier)
    if text is not None:
        if not text:
            return {"ok": False, "text": "", "error": "No se detectó voz clara en el audio."}
        return {"ok": True, "text": text, "engine": "gemini_audio"}

    if "wav" in (mime_type or "").lower():
        offline_text = _transcribe_wav_windows_offline(audio_bytes)
        if offline_text:
            return {"ok": True, "text": offline_text, "engine": "windows_speech_offline"}

    return {
        "ok": False,
        "text": "",
        "error": "No se pudo transcribir el audio. Verifica tu conexión/API key de Gemini o escribe la frase.",
    }


class PcMicRecorder:
    """Grabador de micrófono del PC con parada manual y detección automática de silencio."""

    def __init__(self):
        self._lock = threading.Lock()
        self._recording = False
        self._stop_requested = False
        self._chunks: list[np.ndarray] = []
        self._thread: Optional[threading.Thread] = None
        self._last_result: Optional[Dict[str, Any]] = None
        self._sample_rate = 16000

    @property
    def is_recording(self) -> bool:
        with self._lock:
            return self._recording

    def start(self, gemini_classifier: Any, max_seconds: float = 10.0) -> Dict[str, Any]:
        if sd is None:
            return {"ok": False, "error": "sounddevice no está disponible en Python."}

        with self._lock:
            if self._recording:
                return {"ok": True, "recording": True, "message": "Ya grabando desde el micrófono del PC."}
            self._recording = True
            self._stop_requested = False
            self._chunks = []
            self._last_result = None

        self._thread = threading.Thread(
            target=self._record_worker,
            args=(gemini_classifier, max_seconds),
            daemon=True,
        )
        self._thread.start()
        return {"ok": True, "recording": True, "message": "Escuchando micrófono del PC..."}

    def stop_and_get_result(self, timeout: float = 12.0) -> Dict[str, Any]:
        with self._lock:
            self._stop_requested = True
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        with self._lock:
            if self._last_result is not None:
                return self._last_result
            return {"ok": False, "text": "", "error": "Tiempo de espera agotado procesando el audio."}

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "recording": self._recording,
                "result": self._last_result,
            }

    def _record_worker(self, gemini_classifier: Any, max_seconds: float) -> None:
        sample_rate = self._sample_rate
        block_size = 1600  # 100 ms por bloque
        speech_detected = False
        silence_blocks = 0
        max_silence_blocks = 12  # ~1.2 s de silencio después de hablar
        max_rms = 0.0
        start_time = time.time()
        captured: list[np.ndarray] = []

        def callback(indata, frames, time_info, status):
            chunk = indata[:, 0].copy()
            captured.append(chunk)

        try:
            with sd.InputStream(
                samplerate=sample_rate,
                channels=1,
                dtype="int16",
                blocksize=block_size,
                callback=callback,
            ):
                processed_idx = 0
                while True:
                    time.sleep(0.1)
                    with self._lock:
                        stop_now = self._stop_requested
                    elapsed = time.time() - start_time

                    while processed_idx < len(captured):
                        blk = captured[processed_idx]
                        processed_idx += 1
                        rms = float(np.sqrt(np.mean(blk.astype(np.float32) ** 2)))
                        if rms > max_rms:
                            max_rms = rms
                        if rms > 220.0:
                            speech_detected = True
                            silence_blocks = 0
                        elif speech_detected:
                            silence_blocks += 1

                    if stop_now or elapsed >= max_seconds:
                        break
                    if speech_detected and silence_blocks >= max_silence_blocks and elapsed >= 1.2:
                        break

            if not captured:
                res = {"ok": False, "text": "", "error": "No se recibió audio del micrófono del PC."}
            elif max_rms < 120.0:
                res = {"ok": False, "text": "", "error": "No se detectó voz. Habla más cerca del micrófono."}
            else:
                pcm = np.concatenate(captured, axis=0)
                wav_bytes = _pcm_int16_to_wav_bytes(pcm, sample_rate=sample_rate)
                res = transcribe_audio_bytes(wav_bytes, "audio/wav", gemini_classifier)
        except Exception as exc:
            res = {"ok": False, "text": "", "error": f"Error accediendo al micrófono del PC: {exc}"}

        with self._lock:
            self._last_result = res
            self._recording = False


pc_mic_recorder = PcMicRecorder()

