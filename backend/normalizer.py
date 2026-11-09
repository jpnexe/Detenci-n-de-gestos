"""
Módulo de Normalización Matemática de Vectores 3D (MediaPipe 21 Landmarks -> 63 floats).
Implementa invarianza a traslación (resta de muñeca [0]), escalado por distancia euclidiana máxima
y detección biomecánica de alta precisión basada en ángulos articulares 3D (MCP/PIP/DIP)
calculados en un espacio isótropo (corrección de relación de aspecto de la cámara).

Las métricas inter-manuales se expresan en múltiplos del tamaño de la palma, de modo que las
señas bimanuales se reconocen igual cerca o lejos de la cámara.
"""

from __future__ import annotations
from typing import Dict, List, Optional, Tuple, Any
import numpy as np

from backend.hand_tracking import (
    aspect_correct,
    finger_scores,
    palm_orientation,
    scores_to_margins,
    scores_to_states,
)


# Índices anatómicos de MediaPipe Hands (21 Landmarks)
WRIST = 0
THUMB_CMC, THUMB_MCP, THUMB_IP, THUMB_TIP = 1, 2, 3, 4
INDEX_MCP, INDEX_PIP, INDEX_DIP, INDEX_TIP = 5, 6, 7, 8
MIDDLE_MCP, MIDDLE_PIP, MIDDLE_DIP, MIDDLE_TIP = 9, 10, 11, 12
RING_MCP, RING_PIP, RING_DIP, RING_TIP = 13, 14, 15, 16
PINKY_MCP, PINKY_PIP, PINKY_DIP, PINKY_TIP = 17, 18, 19, 20

FINGERTIPS = (THUMB_TIP, INDEX_TIP, MIDDLE_TIP, RING_TIP, PINKY_TIP)


def _r(v: float, nd: int = 4) -> float:
    return round(float(v), nd)


def normalize_landmarks(
    landmarks_3d: List[Tuple[float, float, float]] | np.ndarray,
    finger_states: Optional[Dict[str, bool]] = None,
    finger_margins: Optional[Dict[str, float]] = None,
    aspect: float = 1.0,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """
    Normaliza 21 puntos clave 3D (x, y, z) en un vector invariante de 63 floats.

    finger_states / finger_margins: estados precalculados por el HandTracker (con hysteresis
    y world landmarks). Si no se proveen se calculan sin estado a partir de los landmarks.
    aspect: relación ancho/alto del fotograma de origen para corregir la anisotropía.
    """
    pts_raw = np.asarray(landmarks_3d, dtype=np.float32)
    if pts_raw.shape != (21, 3):
        pts_raw = pts_raw.reshape(21, 3)
    pts = aspect_correct(pts_raw, aspect) if abs(aspect - 1.0) > 1e-3 else pts_raw.copy()

    # 1. Traslación al origen (Muñeca = [0, 0, 0])
    wrist = pts[WRIST].copy()
    translated = pts - wrist

    # 2. Distancia euclidiana de cada landmark respecto a la muñeca
    distances = np.linalg.norm(translated, axis=1)
    max_dist = float(np.max(distances))
    if max_dist < 1e-6:
        max_dist = 1.0

    # 3. Escalado y flatten (63 floats)
    normalized_pts = translated / max_dist
    vector_63d = normalized_pts.flatten().astype(np.float32)

    # 4. Ángulo de orientación planar (eje Muñeca [0] -> Nudillo Medio [9])
    axis_vec = normalized_pts[MIDDLE_MCP, :2]
    orientation_rad = float(np.arctan2(axis_vec[1], axis_vec[0]))
    orientation_deg = round(float(np.degrees(orientation_rad)), 2)

    # 5. Estado biomecánico de los dedos (ángulos articulares 3D)
    if finger_states is None:
        scores = finger_scores(normalized_pts)
        finger_states = scores_to_states(scores)
        finger_margins = scores_to_margins(scores)
    if finger_margins is None:
        finger_margins = {k: 1.0 for k in finger_states}

    long_margins = [float(finger_margins.get(k, 1.0)) for k in ("thumb", "index", "middle", "ring", "pinky")]
    finger_certainty = 0.5 * (sum(long_margins) / len(long_margins)) + 0.5 * min(long_margins)

    thumb_index_dist = float(np.linalg.norm(normalized_pts[THUMB_TIP, :2] - normalized_pts[INDEX_TIP, :2]))
    is_l_gesture = bool(
        finger_states["index"]
        and finger_states["thumb"]
        and not finger_states["middle"]
        and not finger_states["ring"]
        and not finger_states["pinky"]
    )

    telemetry = {
        "wrist": [_r(pts_raw[WRIST][0]), _r(pts_raw[WRIST][1]), _r(pts_raw[WRIST][2])],
        "index_tip": [_r(pts_raw[INDEX_TIP][0]), _r(pts_raw[INDEX_TIP][1]), _r(pts_raw[INDEX_TIP][2])],
        "middle_tip": [_r(pts_raw[MIDDLE_TIP][0]), _r(pts_raw[MIDDLE_TIP][1]), _r(pts_raw[MIDDLE_TIP][2])],
        "euclidean_scale": _r(max_dist),
        "orientation_deg": orientation_deg,
        "vector_norm": _r(np.linalg.norm(vector_63d)),
        "vector_sample": [round(float(x), 3) for x in vector_63d[:12]],
        "fingers": {k: bool(v) for k, v in finger_states.items()},
        "finger_margins": {k: round(float(v), 3) for k, v in finger_margins.items()},
        "finger_certainty": round(float(finger_certainty), 3),
        "is_l_gesture": is_l_gesture,
        "is_pinch": is_l_gesture,
        "pinch_distance": _r(thumb_index_dist),
    }

    return vector_63d, telemetry


def analyze_finger_extension(norm_pts: np.ndarray) -> Dict[str, bool]:
    """
    Evalúa biomecánicamente qué dedos están extendidos (sin estado temporal) mediante la
    curvatura acumulada de las articulaciones MCP, PIP y DIP y la abducción del pulgar.
    Se conserva por compatibilidad; el pipeline usa el HandTracker con hysteresis.
    """
    return scores_to_states(finger_scores(norm_pts))


def _palm_size(pts_iso: np.ndarray) -> float:
    """Tamaño de referencia de la mano (muñeca -> nudillo medio) en el plano de imagen."""
    return max(1e-4, float(np.linalg.norm(pts_iso[WRIST, :2] - pts_iso[MIDDLE_MCP, :2])))


def _build_hand_entry(
    pts: np.ndarray,
    label: str,
    info: Optional[Dict[str, Any]],
    aspect: float,
) -> Dict[str, Any]:
    fingers = info.get("fingers") if info else None
    margins = info.get("finger_margins") if info else None
    vec, telem = normalize_landmarks(pts, fingers, margins, aspect)
    iso = aspect_correct(pts, aspect)
    palm = info.get("palm") if (info and info.get("palm")) else palm_orientation(iso)
    return {
        "landmarks": pts,
        "iso": iso,
        "vector_63d": vec,
        "telemetry": telem,
        "label": label,
        "palm": palm,
        "palm_size": _palm_size(iso),
        "finger_certainty": telem["finger_certainty"],
    }


def normalize_multi_hand_landmarks(
    hands_list: List[np.ndarray],
    handedness_list: Optional[List[str]] = None,
    hand_infos: Optional[List[Dict[str, Any]]] = None,
    aspect: float = 1.0,
) -> Dict[str, Any]:
    """
    Normaliza y analiza espacialmente de 0 a 2 manos simultáneas, extrayendo métricas
    biomecánicas individuales y relaciones inter-manuales (distancia entre palmas,
    yemas de dedos, orientación relativa y contacto bimanual) requeridas para la traducción
    conversacional continua. Las distancias inter-manuales se normalizan por el tamaño
    de la palma (invariantes a la distancia de la cámara).
    """
    hands_count = len(hands_list)
    if hands_count == 0:
        return {
            "hands_count": 0,
            "is_bimanual": False,
            "primary": None,
            "secondary": None,
            "inter_hand": None,
        }

    def _info(i: int) -> Optional[Dict[str, Any]]:
        return hand_infos[i] if (hand_infos and len(hand_infos) > i) else None

    h0 = np.asarray(hands_list[0], dtype=np.float32).reshape(21, 3)
    lbl0 = handedness_list[0] if (handedness_list and len(handedness_list) > 0) else "Right"
    primary = _build_hand_entry(h0, lbl0, _info(0), aspect)

    if hands_count == 1:
        return {
            "hands_count": 1,
            "is_bimanual": False,
            "primary": primary,
            "secondary": None,
            "inter_hand": None,
        }

    h1 = np.asarray(hands_list[1], dtype=np.float32).reshape(21, 3)
    lbl1 = handedness_list[1] if (handedness_list and len(handedness_list) > 1) else "Left"
    secondary = _build_hand_entry(h1, lbl1, _info(1), aspect)

    a = primary["iso"]
    b = secondary["iso"]
    ps = 0.5 * (primary["palm_size"] + secondary["palm_size"])

    def d(p: np.ndarray, q: np.ndarray) -> float:
        return float(np.linalg.norm(p[:2] - q[:2])) / ps

    # Relaciones geométricas inter-manuales (en múltiplos del tamaño de palma)
    wrist_dist = d(a[WRIST], b[WRIST])
    palm_dist = d(a[MIDDLE_MCP], b[MIDDLE_MCP])
    index_tip_dist = d(a[INDEX_TIP], b[INDEX_TIP])
    thumb_tip_dist = d(a[THUMB_TIP], b[THUMB_TIP])
    dy_wrist = (float(a[WRIST, 1]) - float(b[WRIST, 1])) / ps
    dx_wrist = (float(a[WRIST, 0]) - float(b[WRIST, 0])) / ps

    # Distancia mínima entre cualquier yema de ambas manos
    tips_a = a[list(FINGERTIPS), :2]
    tips_b = b[list(FINGERTIPS), :2]
    pair_d = np.linalg.norm(tips_a[:, None, :] - tips_b[None, :, :], axis=2) / ps
    min_tip_dist = float(np.min(pair_d))

    # Índice de una mano tocando la muñeca de la otra (pulso -> Médico)
    idx_to_other_wrist = min(d(a[INDEX_TIP], b[WRIST]), d(b[INDEX_TIP], a[WRIST]))

    hands_touching = bool(min_tip_dist < 0.45 or palm_dist < 0.8)

    f0 = primary["telemetry"]["fingers"]
    f1 = secondary["telemetry"]["fingers"]
    n_long0 = sum(1 for k in ("index", "middle", "ring", "pinky") if f0[k])
    n_long1 = sum(1 for k in ("index", "middle", "ring", "pinky") if f1[k])
    h0_is_flat = n_long0 == 4
    h1_is_flat = n_long1 == 4
    h0_is_fist = n_long0 == 0
    h1_is_fist = n_long1 == 0
    horizontal0 = primary["palm"].get("facing") == "horizontal"
    horizontal1 = secondary["palm"].get("facing") == "horizontal"

    # Patrón bimanual 1: Palmas juntas (Rezo / Por favor)
    palms_together = bool(
        n_long0 >= 3 and n_long1 >= 3
        and palm_dist < 0.85
        and min_tip_dist < 0.55
    )

    # Patrón bimanual 2: Puño sobre palma (Seña bimanual de Auxilio / Asistencia SOS)
    fist_on_palm_help = False
    if (h0_is_flat and h1_is_fist) or (h1_is_flat and h0_is_fist):
        flat, fist = (a, b) if h0_is_flat else (b, a)
        # El puño reposa sobre (o justo encima de) la palma plana
        fist_above = float(fist[MIDDLE_MCP, 1]) <= float(flat[MIDDLE_MCP, 1]) + 0.35 * ps
        fist_on_palm_help = bool(palm_dist < 1.5 and fist_above)

    # Patrón bimanual 3: Ambas manos abiertas mirando a la cámara (Espera / Calma)
    both_open_forward = bool(
        h0_is_flat and h1_is_flat
        and not (horizontal0 and horizontal1)
        and 1.0 < palm_dist < 5.5
        and abs(dy_wrist) < 1.2
        and not palms_together
    )

    # Patrón bimanual 4: Ambas palmas abiertas hacia arriba (¿Cómo estás? / ¿Qué?)
    both_question = bool(
        not palms_together
        and 1.0 < palm_dist < 5.5
        and abs(dy_wrist) < 1.2
        and (
            (h0_is_flat and h1_is_flat and horizontal0 and horizontal1)
            or (f0["index"] and f0["thumb"] and f1["index"] and f1["thumb"]
                and not (h0_is_flat and h1_is_flat))
        )
    )

    # Patrón bimanual 5: Índice tocando la muñeca opuesta (Médico / Pulso)
    index_on_wrist = bool(
        idx_to_other_wrist < 0.7
        and (f0["index"] or f1["index"])
        and not palms_together
    )

    inter_hand = {
        "palm_size": _r(ps),
        "wrist_dist": _r(wrist_dist),
        "palm_dist": _r(palm_dist),
        "index_tip_dist": _r(index_tip_dist),
        "thumb_tip_dist": _r(thumb_tip_dist),
        "min_tip_dist": _r(min_tip_dist),
        "index_to_wrist": _r(idx_to_other_wrist),
        "dy_wrist": _r(dy_wrist),
        "dx_wrist": _r(dx_wrist),
        "hands_touching": hands_touching,
        "palms_together": palms_together,
        "fist_on_palm_help": fist_on_palm_help,
        "both_open_forward": both_open_forward,
        "both_question": both_question,
        "index_on_wrist": index_on_wrist,
    }

    return {
        "hands_count": 2,
        "is_bimanual": True,
        "primary": primary,
        "secondary": secondary,
        "inter_hand": inter_hand,
    }
