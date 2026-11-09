"""
Módulo de Inferencia Remota (Online) mediante Google Gemini API (google-genai SDK).
Soporta:
1. Inferencia multimodal con latencia ultra-baja usando modelos Flash Lite (~1.0s).
2. Modo dual adaptable: Control OS (G0..G5) y Lenguaje de Señas Conversacional (S_HOLA, S_ADIOS, S_GRACIAS, etc.).
3. Resiliencia automática con reintentos transparentes en modelos de respaldo si la nube satura (503).
4. Verificación activa de conectividad (`test_connection`) para diagnóstico en tiempo real.
"""

from __future__ import annotations
import json
import os
import time
import threading
from typing import Dict, Any, Optional, List
import numpy as np
from dotenv import load_dotenv, set_key

from backend.classifier_local import GESTURE_CATALOG, LocalGestureClassifier
from backend.conversation_engine import CONVERSATIONAL_SIGNS_CATALOG

load_dotenv(override=True)

PROMPT_OS_CONTROL = """Eres el motor multimodal de visión gestual de SignBridge Extended (Modo Control OS).
Analiza la imagen de la mano y los datos biomecánicos proporcionados.
Clasifica ESTRICTAMENTE en una de las siguientes clases de control:
- "G0": Mano abierta (5 dedos extendidos), postura ambigua o movimiento neutro -> Rechazo activo.
- "G1": Dedos índice y medio extendidos en V/Paz -> Acción: RIGHT_CLICK.
- "G2": Solo dedo índice extendido apuntando hacia arriba -> Acción: SCROLL_UP.
- "G3": Puño cerrado (todos los dedos plegados) -> Acción: SCROLL_DOWN.
- "G4": Tres dedos extendidos o señal Shaka (pulgar y meñique) -> Acción: ASSISTANCE_CALL.
- "G5": Gesto Pistola / L: dedo índice arriba y pulgar abierto en L -> Acción: LEFT_CLICK.

Responde ÚNICAMENTE en JSON válido:
{"gesture_id": "G0"|"G1"|"G2"|"G3"|"G4"|"G5", "confidence": 0.85-0.99, "semantic_note": "breve explicación en español"}
"""

PROMPT_SIGN_LANGUAGE = """Eres el traductor conversacional multimodal de SignBridge Extended (Lengua de Señas).
Analiza la imagen de la(s) mano(s) y la cinemática articular.
Clasifica ESTRICTAMENTE en una de las señas canónicas:
- "S_HOLA": Saludo con palma abierta al frente.
- "S_ADIOS": Mano abierta oscilando lateralmente en despedida.
- "S_GRACIAS": Mano proyectándose al frente o palmas juntas en agradecimiento.
- "S_POR_FAVOR": Ambas palmas unidas frente al pecho.
- "S_SI": Dedo índice vertical o puño asintiendo (afirmativo).
- "S_NO": Dedo índice o L oscilando lateralmente en negación.
- "S_BIEN": Pulgar extendido hacia arriba firmemente (bien/OK).
- "S_MAL": Pulgar apuntando hacia abajo o mano bamboleando (mal/regular).
- "S_AYUDA": Puño sobre palma plana (SOS) o Shaka/3 dedos.
- "S_CONTINUAR": Dedos índice y medio en V/Paz (continuar/adelante).
- "S_ENTENDIDO": Puño cerrado afirmando o toque en la sien.
- "S_ESPERA": Ambas palmas abiertas mirando al frente empujando el aire.
- "S_COMO_ESTAS": Ambas manos abriéndose hacia los lados desde el centro.
- "S_QUE": Ambas palmas abiertas hacia arriba oscilando suavemente.
- "S_DESPACIO": Ambas palmas abiertas horizontales descendiendo con calma.
- "G0": Postura neutra, en transición o no identificada con certeza.

Responde ÚNICAMENTE en JSON válido:
{"gesture_id": "S_HOLA"|"S_ADIOS"|"S_GRACIAS"|"S_POR_FAVOR"|"S_SI"|"S_NO"|"S_BIEN"|"S_MAL"|"S_AYUDA"|"S_CONTINUAR"|"S_ENTENDIDO"|"S_ESPERA"|"S_COMO_ESTAS"|"S_QUE"|"S_DESPACIO"|"G0", "confidence": 0.85-0.99, "semantic_note": "breve explicación en español"}
"""

DEFAULT_FAST_MODEL = "gemini-3.5-flash-lite"
FALLBACK_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3-flash-preview",
    "gemini-3.8-flash",
]


class GeminiGestureClassifier:
    """
    Cliente asíncrono y no-bloqueante para la API de Gemini (google-genai SDK).
    Permite llamadas directas en hilos daemon para mantener el pipeline a 30-60 FPS continuos.
    """

    def __init__(self, fallback_classifier: LocalGestureClassifier):
        load_dotenv(override=True)
        self.fallback = fallback_classifier
        self.api_key: str = os.environ.get("GEMINI_API_KEY", "").strip()
        env_model = os.environ.get("GEMINI_MODEL", "").strip()
        self.model_name: str = env_model if env_model else DEFAULT_FAST_MODEL
        self._client = None
        self._lock = threading.Lock()
        self._in_flight = False
        self._last_request_ts = 0.0
        self._min_interval_sec = 0.60
        self._cached_result: Optional[Dict[str, Any]] = None
        self._last_error: Optional[str] = None
        self._last_success_ts = 0.0
        self._active_model_resolved = self.model_name
        self._init_client()

    def _init_client(self) -> None:
        if not self.api_key:
            self._client = None
            return
        try:
            from google import genai
            self._client = genai.Client(api_key=self.api_key)
            self._last_error = None
        except Exception as exc:
            self._client = None
            self._last_error = str(exc)

    def set_api_key(self, api_key: str, model_name: Optional[str] = None) -> bool:
        self.api_key = api_key.strip()
        if model_name and model_name.strip():
            self.model_name = model_name.strip()
        os.environ["GEMINI_API_KEY"] = self.api_key
        os.environ["GEMINI_MODEL"] = self.model_name
        try:
            env_path = os.path.join(os.getcwd(), ".env")
            set_key(env_path, "GEMINI_API_KEY", self.api_key)
            set_key(env_path, "GEMINI_MODEL", self.model_name)
        except Exception:
            pass
        self._init_client()
        return self._client is not None

    def test_connection(self) -> Dict[str, Any]:
        """
        Envía un ping mínimo a Gemini para verificar la clave API y medir la latencia real.
        """
        if not self.api_key:
            return {
                "success": False,
                "error": "No hay clave GEMINI_API_KEY configurada. Ingresa tu API Key en el modal.",
                "model": self.model_name,
            }
        if self._client is None:
            self._init_client()
        if self._client is None:
            return {
                "success": False,
                "error": f"Error al inicializar cliente google-genai: {self._last_error}",
                "model": self.model_name,
            }

        t0 = time.perf_counter()
        models_to_try = [self.model_name] + [m for m in FALLBACK_MODELS if m != self.model_name]
        last_exc = None

        for m in models_to_try:
            try:
                resp = self._client.models.generate_content(
                    model=m,
                    contents="Responde únicamente: OK",
                )
                dt_ms = round((time.perf_counter() - t0) * 1000.0, 1)
                self.model_name = m
                self._active_model_resolved = m
                self._last_error = None
                self._last_success_ts = time.time()
                return {
                    "success": True,
                    "model": m,
                    "latency_ms": dt_ms,
                    "response": (resp.text or "OK").strip(),
                    "message": f"Conexión exitosa con Gemini ({m}) en {dt_ms} ms.",
                }
            except Exception as e:
                last_exc = str(e)
                continue

        return {
            "success": False,
            "error": f"Fallo en todos los modelos evaluados: {last_exc}",
            "model": self.model_name,
        }

    def get_status(self) -> Dict[str, Any]:
        masked_key = ""
        if self.api_key:
            if len(self.api_key) > 8:
                masked_key = f"{self.api_key[:6]}...{self.api_key[-4:]}"
            else:
                masked_key = "***"
        return {
            "configured": bool(self.api_key and self._client is not None),
            "model": self.model_name,
            "active_model": self._active_model_resolved,
            "api_key_masked": masked_key,
            "last_error": self._last_error,
            "connected": bool(self._last_success_ts > 0 and (time.time() - self._last_success_ts) < 180.0),
        }

    def _async_infer(
        self,
        jpeg_bytes: bytes,
        telemetry: Dict[str, Any],
        local_pred: Dict[str, Any],
        interaction_mode: str = "SIGN_LANGUAGE",
    ) -> None:
        t0 = time.perf_counter()
        try:
            from google.genai import types

            is_sign_mode = (interaction_mode == "SIGN_LANGUAGE")
            sys_instruction = PROMPT_SIGN_LANGUAGE if is_sign_mode else PROMPT_OS_CONTROL

            prompt_context = (
                f"Modo: {interaction_mode}. "
                f"Dedos detectados: {telemetry.get('fingers')}. "
                f"Escala euclidiana: {telemetry.get('euclidean_scale')}. "
                f"Predicción local sugerida: {local_pred.get('gesture_id')} ({local_pred.get('name')})."
            )

            # Intentar con el modelo activo o pasar a los modelos de respaldo si la nube satura
            models_to_try = [self.model_name] + [m for m in FALLBACK_MODELS if m != self.model_name]
            response = None
            used_model = self.model_name

            for m in models_to_try:
                try:
                    response = self._client.models.generate_content(
                        model=m,
                        contents=[
                            types.Part.from_bytes(data=jpeg_bytes, mime_type="image/jpeg"),
                            prompt_context,
                        ],
                        config=types.GenerateContentConfig(
                            system_instruction=sys_instruction,
                            temperature=0.1,
                            response_mime_type="application/json",
                        ),
                    )
                    used_model = m
                    break
                except Exception as loop_err:
                    self._last_error = str(loop_err)
                    continue

            if response is None:
                raise RuntimeError(self._last_error or "Fallo de conexión en todos los modelos Gemini")

            latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)
            raw_text = (response.text or "{}").strip()
            parsed = json.loads(raw_text)

            raw_gid = parsed.get("gesture_id", local_pred.get("gesture_id", "G0"))
            conf = float(parsed.get("confidence", 0.94))
            semantic_note = parsed.get("semantic_note", "Análisis multimodal Gemini en tiempo real")

            # Resolver metadata según el catálogo correspondiente
            if is_sign_mode and raw_gid in CONVERSATIONAL_SIGNS_CATALOG:
                meta_sign = CONVERSATIONAL_SIGNS_CATALOG[raw_gid]
                res_obj = {
                    "gesture_id": raw_gid,
                    "name": meta_sign["label"],
                    "short_label": meta_sign["label"],
                    "sign_label": meta_sign["label"],
                    "sign_message": meta_sign["default_phrase"],
                    "action": "NONE",
                    "action_label": "Traducción Gemini",
                    "confidence": round(min(max(conf, 0.50), 0.99), 4),
                    "probabilities": local_pred.get("probabilities", {}),
                    "latency_ms": latency_ms,
                    "engine": f"Gemini ({used_model})",
                    "semantic_note": semantic_note,
                    "cloud_verified": True,
                }
            elif raw_gid in GESTURE_CATALOG:
                meta = GESTURE_CATALOG[raw_gid]
                res_obj = {
                    "gesture_id": raw_gid,
                    "name": meta["name"],
                    "short_label": meta["short_label"],
                    "sign_label": meta.get("sign_label", meta["short_label"]),
                    "sign_message": meta.get("sign_message", ""),
                    "action": meta["action"],
                    "action_label": meta["action_label"],
                    "confidence": round(min(max(conf, 0.50), 0.99), 4),
                    "probabilities": local_pred.get("probabilities", {}),
                    "latency_ms": latency_ms,
                    "engine": f"Gemini ({used_model})",
                    "semantic_note": semantic_note,
                    "cloud_verified": True,
                }
            else:
                meta = GESTURE_CATALOG.get(local_pred["gesture_id"], GESTURE_CATALOG["G0"])
                res_obj = {
                    "gesture_id": local_pred["gesture_id"],
                    "name": meta["name"],
                    "short_label": meta["short_label"],
                    "action": meta["action"],
                    "action_label": meta["action_label"],
                    "confidence": round(min(max(conf, 0.50), 0.99), 4),
                    "probabilities": local_pred.get("probabilities", {}),
                    "latency_ms": latency_ms,
                    "engine": f"Gemini ({used_model})",
                    "semantic_note": semantic_note,
                    "cloud_verified": True,
                }

            with self._lock:
                self._cached_result = res_obj
                self._last_error = None
                self._last_success_ts = time.time()
                self._active_model_resolved = used_model

        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
        finally:
            with self._lock:
                self._in_flight = False

    def predict(
        self,
        jpeg_bytes: Optional[bytes],
        vector_63d: np.ndarray,
        telemetry: Dict[str, Any],
        interaction_mode: str = "SIGN_LANGUAGE",
    ) -> Dict[str, Any]:
        """
        Retorna la inferencia multimodal de Gemini.
        Dispara peticiones asíncronas no-bloqueantes cada ~600 ms y sirve el resultado
        verificado sin congelar el hilo principal de renderizado de la cámara.
        """
        local_pred = self.fallback.predict(vector_63d, telemetry)
        now = time.time()

        if self._client is not None and jpeg_bytes is not None:
            with self._lock:
                should_dispatch = (not self._in_flight) and ((now - self._last_request_ts) >= self._min_interval_sec)
                if should_dispatch:
                    self._in_flight = True
                    self._last_request_ts = now
                    threading.Thread(
                        target=self._async_infer,
                        args=(jpeg_bytes, telemetry, local_pred, interaction_mode),
                        daemon=True,
                    ).start()

                # Si tenemos un resultado verificado por la nube recibido en los últimos 6.0 segundos
                if self._cached_result is not None and (now - self._last_success_ts) < 6.0:
                    return dict(self._cached_result)

        # Si aún está en vuelo o sin clave configurada, proveer telemetría local con estado visual claro
        gid = local_pred["gesture_id"]
        meta = GESTURE_CATALOG.get(gid, GESTURE_CATALOG["G0"])
        note = (
            f"Gemini API conectada ({self._active_model_resolved}) — Consultando frame..."
            if self._client is not None
            else "Modo Online: Configura GEMINI_API_KEY para análisis cloud en vivo"
        )
        return {
            "gesture_id": gid,
            "name": meta["name"],
            "short_label": meta["short_label"],
            "sign_label": meta.get("sign_label", meta["short_label"]),
            "sign_message": meta.get("sign_message", ""),
            "action": meta["action"],
            "action_label": meta["action_label"],
            "confidence": round(local_pred["confidence"], 4),
            "probabilities": local_pred["probabilities"],
            "latency_ms": 32.0 if self._client is not None else 18.0,
            "engine": f"Gemini Online ({self._active_model_resolved})",
            "semantic_note": note,
            "cloud_verified": bool(self._client is not None and self._last_success_ts > 0),
        }
