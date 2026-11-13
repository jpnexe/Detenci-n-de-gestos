"""
Gestor de Calibración Personalizada y Conversión de Imágenes a Señas — SignBridge Extended.

Permite:
1. Calibrar señas o letras existentes (L_H, L_V, S_HOLA, etc.) capturando muestras reales
   normalizadas 63D de la mano del usuario para eliminar confusiones anatómicas.
2. Convertir imágenes de señas (fotos o diagramas con indicaciones) en señas operativas
   extrayendo landmarks 3D con MediaPipe y analizando movimiento/significado con Gemini.
"""

from __future__ import annotations

import json
import os
import re
import threading
from typing import Any, Dict, List, Optional

import cv2
import numpy as np

from backend.normalizer import normalize_landmarks


DEFAULT_STORAGE_PATH = os.path.join("models", "custom_signs.json")


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na < 1e-8 or nb < 1e-8:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _slug_sign_id(name: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9]+", "_", (name or "").strip().upper()).strip("_")
    if not clean:
        clean = "PERSONALIZADA"
    if not clean.startswith(("S_", "L_", "C_")):
        clean = f"C_{clean}"
    return clean[:32]


class CustomSignStore:
    """Almacén persistente en JSON para calibraciones y señas creadas por el usuario."""

    def __init__(self, storage_path: str = DEFAULT_STORAGE_PATH):
        self.storage_path = storage_path
        self._lock = threading.Lock()
        self.signs: Dict[str, Dict[str, Any]] = {}
        self.load()

    def load(self) -> None:
        with self._lock:
            if not os.path.exists(self.storage_path):
                self.signs = {}
                return
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self.signs = data
            except Exception:
                self.signs = {}

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.storage_path) or ".", exist_ok=True)
        with self._lock:
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(self.signs, f, ensure_ascii=False, indent=2)

    def list_signs(self) -> List[Dict[str, Any]]:
        with self._lock:
            result = []
            for sid, item in self.signs.items():
                result.append({
                    "id": sid,
                    "label": item.get("label", sid),
                    "emoji": item.get("emoji", "🤟"),
                    "category": item.get("category", "Personalizada"),
                    "default_phrase": item.get("default_phrase", item.get("label", sid)),
                    "description": item.get("description", ""),
                    "motion_hint": item.get("motion_hint", ""),
                    "motion_type": item.get("motion_type", "STATIC"),
                    "sample_count": len(item.get("prototypes_63d", [])),
                    "source": item.get("source", "calibration"),
                })
            return result

    def add_calibration_samples(
        self,
        sign_id: str,
        vectors_63d: List[List[float]],
        label: Optional[str] = None,
        default_phrase: Optional[str] = None,
        description: Optional[str] = None,
        motion_type: str = "STATIC",
        source: str = "calibration",
    ) -> Dict[str, Any]:
        valid_vecs = [
            [round(float(v), 5) for v in vec]
            for vec in vectors_63d
            if isinstance(vec, (list, tuple, np.ndarray)) and len(vec) == 63
        ]
        if not valid_vecs:
            return {"ok": False, "error": "No hay vectores 63D válidos para calibrar."}

        sid = sign_id.strip().upper()
        with self._lock:
            existing = self.signs.get(sid, {})
            prev_vecs = list(existing.get("prototypes_63d", []))
            # Conservar hasta 12 prototipos representativos más recientes
            merged = (prev_vecs + valid_vecs)[-12:]
            entry = {
                "id": sid,
                "label": label or existing.get("label") or sid,
                "emoji": existing.get("emoji", "🤟"),
                "category": existing.get("category", "Personalizada"),
                "default_phrase": default_phrase or existing.get("default_phrase") or label or sid,
                "description": description or existing.get("description") or "Seña calibrada con muestras reales.",
                "motion_hint": existing.get("motion_hint", ""),
                "motion_type": motion_type or existing.get("motion_type", "STATIC"),
                "prototypes_63d": merged,
                "source": source,
            }
            self.signs[sid] = entry
        self.save()
        return {"ok": True, "sign_id": sid, "sample_count": len(merged), "entry": entry}

    def delete_sign(self, sign_id: str) -> bool:
        sid = sign_id.strip().upper()
        with self._lock:
            if sid in self.signs:
                del self.signs[sid]
                removed = True
            else:
                removed = False
        if removed:
            self.save()
        return removed

    @staticmethod
    def _matches_motion(motion_type: str, motion_primary: Dict[str, Any]) -> bool:
        mt = (motion_type or "STATIC").upper()
        if mt == "STATIC":
            return True
        if mt == "OSCILLATE_X":
            return bool(motion_primary.get("is_oscillating_x"))
        if mt == "OSCILLATE_Y":
            return bool(motion_primary.get("is_oscillating_y"))
        if mt == "MOVE_DOWN":
            return bool(motion_primary.get("is_moving_down"))
        if mt == "MOVE_UP":
            return bool(motion_primary.get("is_moving_up"))
        if mt == "MOVE_HORIZ":
            return bool(motion_primary.get("is_moving_horiz") or motion_primary.get("trace_h"))
        return True

    def match_prototype(
        self,
        vector_63d: List[float],
        motion_primary: Optional[Dict[str, Any]] = None,
        min_sim: float = 0.925,
    ) -> Optional[Dict[str, Any]]:
        """Busca si el vector 63D actual coincide con alguna seña/letra calibrada."""
        if vector_63d is None or len(vector_63d) != 63:
            return None
        query = np.asarray(vector_63d, dtype=np.float32)
        motion_p = motion_primary or {}

        best_sid = None
        best_sim = 0.0
        best_entry = None

        with self._lock:
            items = list(self.signs.items())

        for sid, entry in items:
            protos = entry.get("prototypes_63d") or []
            if not protos:
                continue
            mt = entry.get("motion_type", "STATIC")
            if not self._matches_motion(mt, motion_p):
                continue

            max_p_sim = 0.0
            for p in protos:
                if len(p) != 63:
                    continue
                sim = _cosine_similarity(query, np.asarray(p, dtype=np.float32))
                if sim > max_p_sim:
                    max_p_sim = sim

            if max_p_sim >= min_sim and max_p_sim > best_sim:
                best_sim = max_p_sim
                best_sid = sid
                best_entry = entry

        if best_sid is None or best_entry is None:
            return None

        return {
            "sign_id": best_sid,
            "label": best_entry.get("label", best_sid),
            "default_phrase": best_entry.get("default_phrase", best_entry.get("label", best_sid)),
            "description": best_entry.get("description", ""),
            "confidence": round(min(0.99, best_sim), 3),
            "engine": "Custom Calibrated Prototype (63D)",
            "is_dynamic": best_entry.get("motion_type", "STATIC") != "STATIC",
        }

    def get_custom_prompt_block(self) -> str:
        """Genera un bloque de texto con las señas personalizadas para el prompt de Gemini Online."""
        with self._lock:
            custom_items = [
                (sid, item)
                for sid, item in self.signs.items()
                if sid.startswith("C_")
            ]
        if not custom_items:
            return ""
        lines = ["SEÑAS PERSONALIZADAS DEL USUARIO:"]
        for sid, item in custom_items:
            desc = item.get("description") or item.get("default_phrase") or item.get("label")
            hint = item.get("motion_hint")
            extra = f" (Movimiento: {hint})" if hint else ""
            lines.append(f'- "{sid}": {item.get("label", sid)} — {desc}{extra}.')
        return "\n".join(lines)


def import_sign_from_image(
    store: CustomSignStore,
    image_bytes: bytes,
    mime_type: str,
    sign_name: str,
    meaning: str,
    instructions: str,
    hand_landmarker: Any,
    gemini_classifier: Any,
) -> Dict[str, Any]:
    """
    Convierte una imagen de seña (con o sin indicaciones) en una seña operativa:
    1. Extrae landmarks 3D (63D) mediante MediaPipe si hay una mano visible en la imagen.
    2. Analiza imagen + indicaciones con Gemini Vision para extraer significado y tipo de movimiento.
    3. Guarda la seña en CustomSignStore para uso local y en Gemini Online.
    """
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if bgr is None:
        return {"ok": False, "error": "No se pudo decodificar la imagen subida."}

    # 1. Extraer landmarks 3D con MediaPipe
    extracted_vectors: List[List[float]] = []
    if hand_landmarker is not None:
        try:
            import mediapipe as mp
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            res = hand_landmarker.detect(mp_image)
            if res and res.hand_landmarks:
                for hand_lms in res.hand_landmarks[:1]:
                    pts = np.array([[lm.x, lm.y, lm.z] for lm in hand_lms], dtype=np.float32)
                    vec_63d = normalize_landmarks(pts)
                    extracted_vectors.append([round(float(x), 5) for x in vec_63d])
        except Exception:
            pass

    # 2. Analizar imagen e indicaciones con Gemini Vision (si está disponible)
    gemini_meta: Dict[str, Any] = {}
    client = getattr(gemini_classifier, "_client", None) if gemini_classifier else None
    if client is not None:
        try:
            from google.genai import types
            model_name = getattr(gemini_classifier, "model_name", "gemini-3.5-flash-lite") or "gemini-3.5-flash-lite"
            prompt = (
                "Analiza esta imagen de Lengua de Señas y las indicaciones proporcionadas.\n"
                f"Nombre sugerido: '{sign_name}'. Significado sugerido: '{meaning}'. Indicaciones: '{instructions}'.\n"
                "Responde ÚNICAMENTE en JSON válido con estas claves:\n"
                '{"label": "Nombre corto", "default_phrase": "Frase en español", '
                '"description": "Cómo colocar dedos y mano", "motion_hint": "Indicaciones de movimiento si hay", '
                '"motion_type": "STATIC"|"OSCILLATE_X"|"OSCILLATE_Y"|"MOVE_DOWN"|"MOVE_UP"|"MOVE_HORIZ"}'
            )
            resp = client.models.generate_content(
                model=model_name,
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type=(mime_type or "image/jpeg").split(";")[0]),
                    prompt,
                ],
                config=types.GenerateContentConfig(temperature=0.1, response_mime_type="application/json"),
            )
            parsed = json.loads((resp.text or "{}").strip())
            if isinstance(parsed, dict):
                gemini_meta = parsed
        except Exception:
            pass

    final_label = (sign_name or gemini_meta.get("label") or meaning or "Nueva Seña").strip()
    final_phrase = (meaning or gemini_meta.get("default_phrase") or final_label).strip()
    final_desc = (instructions or gemini_meta.get("description") or f"Seña importada: {final_label}").strip()
    final_hint = (gemini_meta.get("motion_hint") or instructions or "").strip()
    final_motion_type = str(gemini_meta.get("motion_type") or "STATIC").upper()
    if final_motion_type not in {"STATIC", "OSCILLATE_X", "OSCILLATE_Y", "MOVE_DOWN", "MOVE_UP", "MOVE_HORIZ"}:
        final_motion_type = "STATIC"

    sid = _slug_sign_id(final_label)

    with store._lock:
        store.signs[sid] = {
            "id": sid,
            "label": final_label,
            "emoji": "🖼️",
            "category": "Personalizada (Imagen)",
            "default_phrase": final_phrase,
            "description": final_desc,
            "motion_hint": final_hint,
            "motion_type": final_motion_type,
            "prototypes_63d": extracted_vectors,
            "source": "image_import",
        }
    store.save()

    return {
        "ok": True,
        "sign_id": sid,
        "landmarks_detected": len(extracted_vectors) > 0,
        "gemini_analyzed": bool(gemini_meta),
        "entry": store.signs[sid],
        "message": (
            f"Seña '{final_label}' ({sid}) creada correctamente. "
            + ("Mano 3D extraída de la imagen." if extracted_vectors else "Sin mano fotográfica directa (activa en Gemini Online o calibra 10 muestras con tu cámara).")
        ),
    }


custom_sign_store = CustomSignStore()
