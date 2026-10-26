"""
Módulo de Normalización Matemática de Vectores 3D (MediaPipe 21 Landmarks -> 63 floats).
Implementa invarianza a traslación (resta de muñeca [0]), escalado por distancia euclidiana máxima
y detección biomecánica de alta precisión referenciada al hueso metacarpiano de la palma (0 -> 9)
y ángulos articulares (ley de cosenos en PIP/DIP).
"""

from __future__ import annotations
from typing import Dict, List, Tuple, Any
import numpy as np


# Índices anatómicos de MediaPipe Hands (21 Landmarks)
WRIST = 0
THUMB_CMC, THUMB_MCP, THUMB_IP, THUMB_TIP = 1, 2, 3, 4
INDEX_MCP, INDEX_PIP, INDEX_DIP, INDEX_TIP = 5, 6, 7, 8
MIDDLE_MCP, MIDDLE_PIP, MIDDLE_DIP, MIDDLE_TIP = 9, 10, 11, 12
RING_MCP, RING_PIP, RING_DIP, RING_TIP = 13, 14, 15, 16
PINKY_MCP, PINKY_PIP, PINKY_DIP, PINKY_TIP = 17, 18, 19, 20


def normalize_landmarks(landmarks_3d: List[Tuple[float, float, float]] | np.ndarray) -> Tuple[np.ndarray, Dict[str, Any]]:
    """
    Normaliza 21 puntos clave 3D (x, y, z) en un vector invariante de 63 floats.
    """
    pts = np.asarray(landmarks_3d, dtype=np.float32)
    if pts.shape != (21, 3):
        pts = pts.reshape(21, 3)

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

    # 5. Análisis biomecánico por ángulos articulares y longitud metacarpiana de la palma
    finger_states = analyze_finger_extension(normalized_pts)
    thumb_index_dist = float(np.linalg.norm(normalized_pts[THUMB_TIP, :2] - normalized_pts[INDEX_TIP, :2]))
    is_l_gesture = bool(
        finger_states["index"]
        and finger_states["thumb"]
        and not finger_states["middle"]
        and not finger_states["ring"]
        and not finger_states["pinky"]
    )

    telemetry = {
        "wrist": [round(float(wrist[0]), 4), round(float(wrist[1]), 4), round(float(wrist[2]), 4)],
        "index_tip": [round(float(pts[INDEX_TIP][0]), 4), round(float(pts[INDEX_TIP][1]), 4), round(float(pts[INDEX_TIP][2]), 4)],
        "middle_tip": [round(float(pts[MIDDLE_TIP][0]), 4), round(float(pts[MIDDLE_TIP][1]), 4), round(float(pts[MIDDLE_TIP][2]), 4)],
        "euclidean_scale": round(max_dist, 4),
        "orientation_deg": orientation_deg,
        "vector_norm": round(float(np.linalg.norm(vector_63d)), 4),
        "vector_sample": [round(float(x), 3) for x in vector_63d[:12]],
        "fingers": finger_states,
        "is_l_gesture": is_l_gesture,
        "is_pinch": is_l_gesture,
        "pinch_distance": round(thumb_index_dist, 4),
    }

    return vector_63d, telemetry


def analyze_finger_extension(norm_pts: np.ndarray) -> Dict[str, bool]:
    """
    Evalúa biomecánicamente qué dedos están extendidos usando como referencia rígida
    el tamaño de la palma (distancia Muñeca [0] -> Nudillo Medio [9]) y el coseno del ángulo articular PIP.
    Esto evita que al cerrar el puño (donde d_max disminuye) se distorsionen los umbrales del pulgar o meñique.
    """
    palm_len = max(0.15, float(np.linalg.norm(norm_pts[MIDDLE_MCP, :2])))

    def is_finger_extended(mcp_idx: int, pip_idx: int, dip_idx: int, tip_idx: int, min_palm_ratio: float = 1.32) -> bool:
        v1 = norm_pts[pip_idx, :2] - norm_pts[mcp_idx, :2]
        v2 = norm_pts[tip_idx, :2] - norm_pts[pip_idx, :2]
        n1 = float(np.linalg.norm(v1))
        n2 = float(np.linalg.norm(v2))
        cos_angle = float(np.dot(v1, v2) / max(1e-6, n1 * n2))

        span_tip_mcp = float(np.linalg.norm(norm_pts[tip_idx, :2] - norm_pts[mcp_idx, :2]))
        dist_tip_wrist = float(np.linalg.norm(norm_pts[tip_idx, :2]))
        dist_pip_wrist = float(np.linalg.norm(norm_pts[pip_idx, :2]))

        # Rectitud de la falange + punta más alejada de la muñeca que el PIP + extensión respecto a la palma
        straight = cos_angle > 0.48
        open_span = span_tip_mcp > (n1 * 1.30)
        radial_out = dist_tip_wrist > (dist_pip_wrist * 1.07) and (dist_tip_wrist / palm_len) > min_palm_ratio
        return bool(straight and open_span and radial_out)

    # Pulgar: evaluar rectitud (CMC->MCP->TIP) y abducción lateral respecto al tamaño rígido de la palma
    vt1 = norm_pts[THUMB_MCP, :2] - norm_pts[THUMB_CMC, :2]
    vt2 = norm_pts[THUMB_TIP, :2] - norm_pts[THUMB_MCP, :2]
    cos_thumb = float(np.dot(vt1, vt2) / max(1e-6, float(np.linalg.norm(vt1) * np.linalg.norm(vt2))))

    dist_thumb_tip_pinky = float(np.linalg.norm(norm_pts[THUMB_TIP, :2] - norm_pts[PINKY_MCP, :2]))
    dist_thumb_ip_pinky = float(np.linalg.norm(norm_pts[THUMB_IP, :2] - norm_pts[PINKY_MCP, :2]))
    dist_thumb_index_mcp = float(np.linalg.norm(norm_pts[THUMB_TIP, :2] - norm_pts[INDEX_MCP, :2]))
    dist_thumb_middle_mcp = float(np.linalg.norm(norm_pts[THUMB_TIP, :2] - norm_pts[MIDDLE_MCP, :2]))

    thumb_extended = bool(
        cos_thumb > 0.45
        and dist_thumb_tip_pinky > (dist_thumb_ip_pinky * 1.08)
        and (dist_thumb_index_mcp / palm_len) > 0.48
        and (dist_thumb_middle_mcp / palm_len) > 0.62
    )

    return {
        "thumb": thumb_extended,
        "index": is_finger_extended(INDEX_MCP, INDEX_PIP, INDEX_DIP, INDEX_TIP, 1.32),
        "middle": is_finger_extended(MIDDLE_MCP, MIDDLE_PIP, MIDDLE_DIP, MIDDLE_TIP, 1.34),
        "ring": is_finger_extended(RING_MCP, RING_PIP, RING_DIP, RING_TIP, 1.28),
        "pinky": is_finger_extended(PINKY_MCP, PINKY_PIP, PINKY_DIP, PINKY_TIP, 1.16),
    }
