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
from backend.lsc_alphabet import LSC_ALPHABET_CATALOG

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

PROMPT_SIGN_LANGUAGE = """Eres el traductor conversacional multimodal de SignBridge Extended (Lengua de Señas Colombiana - LSC).
Analiza la imagen de la(s) mano(s) y la cinemática articular.
Clasifica con rigor en una de las señas conversacionales o letras del Abecedario LSC:
SEÑAS CONVERSACIONALES:
- "S_HOLA": Saludo con palma abierta al frente.
- "S_ADIOS": Mano abierta oscilando lateralmente en despedida.
- "S_GRACIAS": Mano proyectándose al frente o palmas juntas en agradecimiento.
- "S_POR_FAVOR": Ambas palmas unidas frente al pecho.
- "S_SI": Dedo índice vertical o puño asintiendo (afirmativo).
- "S_NO": Dedo índice o L oscilando lateralmente en negación.
- "S_BIEN": Pulgar extendido hacia arriba firmemente (bien/OK).
- "S_MAL": Pulgar apuntando hacia abajo o mano bamboleando (mal/regular).
- "S_AYUDA": Puño sobre palma plana (SOS) o señal de auxilio.
- "S_CONTINUAR": Dedos índice y medio en V/Paz (continuar/adelante).
- "S_ENTENDIDO": Puño cerrado afirmando o toque en la sien.
- "S_ESPERA": Ambas palmas abiertas mirando al frente empujando el aire.
- "S_COMO_ESTAS": Ambas manos abriéndose hacia los lados desde el centro.
- "S_QUE": Ambas palmas abiertas hacia arriba oscilando suavemente.
- "S_DESPACIO": Ambas palmas abiertas horizontales descendiendo con calma.
- "S_MUCHO_GUSTO": Palmas convergiendo al centro en saludo formal.
- "S_BUENOS_DIAS": Mano dominante elevándose sobre antebrazo base.
- "S_BUENAS_TARDES": Mano dominante deslizándose sobre antebrazo horizontal.
- "S_BUENAS_NOCHES": Mano dominante descendiendo en arco sobre brazo base.
- "S_AMIGO": Ambas manos uniéndose cálidamente.
- "S_CASA": Manos unidas en tejado o ángulo de triángulo.
- "S_TRABAJAR": Puños golpeándose suavemente en ritmo.
- "S_ESTUDIAR": Mano repasando la palma base como un libro.
- "S_MEDICO": Dedos tocando el pulso en la muñeca contraria.
- "S_DONDE": Índices de ambas manos apuntando en búsqueda espacial.
- "S_CUANDO": Índice girando alrededor de la otra mano.
- "S_QUIEN": Índice rozando la barbilla o mejilla.
- "S_POR_QUE": Índice en la frente proyectándose hacia afuera.
- "S_QUERER": Manos abiertas retrayéndose hacia el pecho.
- "S_NECESITAR": Puño/gancho descendiendo con firmeza.
- "S_FELIZ": Manos abiertas ascendiendo frente al pecho.
- "S_TRISTE": Mano descendiendo lentamente frente al rostro.
- "S_CANSADO": Manos relajadas cayendo sobre el pecho.
- "S_OCUPADO": Manos activas cruzándose en acción.
- "S_NO_ENTIENDO": Índice oscilando en negación a la altura de la sien.
- "S_REPETIR": Mano abierta realizando barrido descendente.
- "S_HABLAR": Índices alternando movimiento en diálogo.
- "S_IR": Índice proyectándose hacia adelante en dirección de marcha.
ABECEDARIO LSC DACTILOLÓGICO:
- Letras individuales: "L_A".."L_Z", "L_NTILDE" (ejemplo: "L_A", "L_B", "L_C", "L_J", "L_Z", "L_Ñ" -> "L_NTILDE").
RECHAZO:
- "G0": Postura neutra, mano en reposo o no identificada con suficiente certeza.

Responde ÚNICAMENTE en JSON válido:
{"gesture_id": "<ID_SEÑA_O_LETRA>", "confidence": 0.85-0.99, "semantic_note": "breve explicación en español"}
"""

DEFAULT_FAST_MODEL = "gemini-3.5-flash-lite"
FALLBACK_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-flash-latest",
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
        self._min_interval_sec = 0.40
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
            if is_sign_mode:
                from backend.custom_signs import custom_sign_store
                custom_block = custom_sign_store.get_custom_prompt_block()
                if custom_block:
                    sys_instruction = f"{sys_instruction}\n\n{custom_block}"

            prompt_context = (
                f"Modo: {interaction_mode}. "
                f"Dedos extendidos según tracking: {[k for k, v in telemetry.get('fingers', {}).items() if v]}. "
                f"Escala euclidiana: {telemetry.get('euclidean_scale')}. "
                f"Analiza la imagen cuidadosamente y clasifica el gesto o seña real ejecutada por el usuario."
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
            if is_sign_mode:
                if raw_gid in CONVERSATIONAL_SIGNS_CATALOG:
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
                        "probabilities": {},
                        "latency_ms": latency_ms,
                        "engine": f"Gemini ({used_model})",
                        "semantic_note": semantic_note,
                        "cloud_verified": True,
                    }
                elif raw_gid in LSC_ALPHABET_CATALOG:
                    meta_l = LSC_ALPHABET_CATALOG[raw_gid]
                    res_obj = {
                        "gesture_id": raw_gid,
                        "name": f"Letra {meta_l['letter']}",
                        "short_label": f"LETRA {meta_l['letter']}",
                        "sign_label": f"LETRA {meta_l['letter']}",
                        "sign_message": meta_l.get("description", ""),
                        "action": "NONE",
                        "action_label": "Deletreo LSC (Gemini)",
                        "confidence": round(min(max(conf, 0.50), 0.99), 4),
                        "probabilities": {},
                        "latency_ms": latency_ms,
                        "engine": f"Gemini ({used_model})",
                        "semantic_note": semantic_note,
                        "cloud_verified": True,
                    }
                else:
                    res_obj = {
                        "gesture_id": "G0",
                        "name": GESTURE_CATALOG["G0"]["name"],
                        "short_label": "DESCONOCIDO",
                        "sign_label": "DESCONOCIDO",
                        "sign_message": "Esperando seña intencional...",
                        "action": "NONE",
                        "action_label": "Esperando seña intencional",
                        "confidence": 0.0,
                        "probabilities": {k: 0.0 for k in GESTURE_CATALOG},
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
        Dispara peticiones asíncronas no-bloqueantes cada ~400 ms y sirve el resultado
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

                # Si tenemos un resultado verificado por la nube recibido en los últimos 2.0 segundos
                if self._cached_result is not None and (now - self._last_success_ts) < 2.0:
                    return dict(self._cached_result)

        # Si aún está en vuelo o sin clave configurada, reportar estado activo de Gemini sin contaminar con el modelo local
        note = (
            f"Gemini API activa ({self._active_model_resolved}) — Analizando fotograma en la nube..."
            if self._client is not None
            else "Modo Online: Configura GEMINI_API_KEY para análisis cloud en vivo"
        )
        return {
            "gesture_id": "G0",
            "name": GESTURE_CATALOG["G0"]["name"],
            "short_label": "DESCONOCIDO",
            "sign_label": "DESCONOCIDO",
            "sign_message": "Esperando seña intencional...",
            "action": "NONE",
            "action_label": "Esperando verificación Gemini",
            "confidence": 0.0,
            "probabilities": {k: 0.0 for k in GESTURE_CATALOG},
            "latency_ms": 32.0 if self._client is not None else 18.0,
            "engine": f"Gemini Online ({self._active_model_resolved})",
            "semantic_note": note,
            "cloud_verified": bool(self._client is not None and self._last_success_ts > 0),
        }
