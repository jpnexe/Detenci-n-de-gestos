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

from backend.normalizer import normalize_landmarks, extract_biomech_signature


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
        self._compiled: Dict[str, Dict[str, Any]] = {}
        self.load()

    def _rebuild_cache_locked(self) -> None:
        """Precalcula matrices NumPy (63D, Bio16D y centroide) para inferencia < 0.01 ms."""
        compiled: Dict[str, Dict[str, Any]] = {}
        for sid, entry in self.signs.items():
            protos = [
                np.asarray(p, dtype=np.float32)
                for p in (entry.get("prototypes_63d") or [])
                if len(p) == 63
            ]
            if not protos:
                continue
            p_mat = np.stack(protos, axis=0)
            p_norms = np.maximum(1e-8, np.linalg.norm(p_mat, axis=1, keepdims=True))
            p_unit = (p_mat / p_norms).astype(np.float32)
            bio_list = [extract_biomech_signature(p.reshape(21, 3)) for p in p_mat]
            b_unit = np.stack(bio_list, axis=0).astype(np.float32)
            centroid = np.mean(p_unit, axis=0)
            c_norm = float(np.linalg.norm(centroid))
            if c_norm > 1e-8:
                centroid = (centroid / c_norm).astype(np.float32)
            compiled[sid] = {
                "p_unit": p_unit,
                "b_unit": b_unit,
                "centroid": centroid,
                "motion_type": entry.get("motion_type", "STATIC"),
                "entry": entry,
            }
        self._compiled = compiled

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
            self._rebuild_cache_locked()

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.storage_path) or ".", exist_ok=True)
        with self._lock:
            self._rebuild_cache_locked()
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
        min_sim: float = 0.905,
        bio_sig: Optional[Any] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Busca si el vector 63D actual coincide con alguna seña/letra calibrada combinando:
        - Máxima similitud coseno contra muestras reales
        - Promedio Top-K (hasta 3 muestras más cercanas) y centroide de clase
        - Descriptor biomecánico 16D invariante a distancia y rotación leve
        """
        if vector_63d is None or len(vector_63d) != 63:
            return None
        with self._lock:
            compiled = self._compiled
            if not compiled:
                return None
            items = list(compiled.items())

        query = np.asarray(vector_63d, dtype=np.float32)
        q_norm = float(np.linalg.norm(query))
        if q_norm < 1e-8:
            return None
        query = query / q_norm
        q_bio = (
            np.asarray(bio_sig, dtype=np.float32)
            if bio_sig is not None and len(bio_sig) == 16
            else extract_biomech_signature(query.reshape(21, 3))
        )
        motion_p = motion_primary or {}

        best_sid = None
        best_sim = 0.0
        best_entry = None

        for sid, comp in items:
            if not self._matches_motion(comp["motion_type"], motion_p):
                continue
            sims = comp["p_unit"] @ query
            b_sims = comp["b_unit"] @ q_bio
            max_p_sim = float(np.max(sims))
            k = min(3, sims.shape[0])
            top_k_sim = float(np.mean(np.partition(sims, -k)[-k:]))
            centroid_sim = float(np.dot(comp["centroid"], query))
            max_bio_sim = float(np.max(b_sims))

            score = (
                0.42 * max_p_sim
                + 0.23 * top_k_sim
                + 0.15 * centroid_sim
                + 0.20 * max(0.0, max_bio_sim)
            )

            if score >= min_sim and score > best_sim:
                best_sim = score
                best_sid = sid
                best_entry = comp["entry"]

        if best_sid is None or best_entry is None:
            return None

        return {
            "sign_id": best_sid,
            "label": best_entry.get("label", best_sid),
            "default_phrase": best_entry.get("default_phrase", best_entry.get("label", best_sid)),
            "description": best_entry.get("description", ""),
            "confidence": round(min(0.99, best_sim), 3),
            "engine": "Custom Calibrated Multi-Sample (63D + Bio16D)",
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
