"""
Módulo de Normalización Matemática de Vectores 3D (MediaPipe 21 Landmarks -> 63 floats).
Implementa invarianza a traslación (resta de muñeca [0]) y escalado por distancia euclidiana máxima.
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
    
    Pasos:
    1. Resta del punto base (Muñeca [0]): P'_i = P_i - P_0
    2. Escalado por distancia euclidiana máxima: d_max = max_i ||P'_i||_2
    3. Aplanado a vector 1D de 63 elementos en [-1.0, 1.0].
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

    # Análisis geométrico de extensión de dedos y pellizco (Pinch = Clic Izquierdo)
    finger_states = analyze_finger_extension(normalized_pts)
    pinch_dist = float(np.linalg.norm(normalized_pts[THUMB_TIP, :2] - normalized_pts[INDEX_TIP, :2]))
    is_pinch = bool(pinch_dist < 0.075)

    telemetry = {
        "wrist": [round(float(wrist[0]), 4), round(float(wrist[1]), 4), round(float(wrist[2]), 4)],
        "index_tip": [round(float(pts[INDEX_TIP][0]), 4), round(float(pts[INDEX_TIP][1]), 4), round(float(pts[INDEX_TIP][2]), 4)],
        "middle_tip": [round(float(pts[MIDDLE_TIP][0]), 4), round(float(pts[MIDDLE_TIP][1]), 4), round(float(pts[MIDDLE_TIP][2]), 4)],
        "euclidean_scale": round(max_dist, 4),
        "vector_norm": round(float(np.linalg.norm(vector_63d)), 4),
        "vector_sample": [round(float(x), 3) for x in vector_63d[:12]],
        "fingers": finger_states,
        "is_pinch": is_pinch,
        "pinch_distance": round(pinch_dist, 4),
    }

    return vector_63d, telemetry


def analyze_finger_extension(norm_pts: np.ndarray) -> Dict[str, bool]:
    """
    Evalúa biomecánicamente qué dedos están extendidos usando coordenadas normalizadas
    respecto a la muñeca y articulaciones PIP/MCP.
    En imagen (y crece hacia abajo), un dedo apuntando arriba tiene y_tip < y_pip,
    y su distancia radial a la muñeca es mayor en la punta que en la articulación PIP.
    """
    def is_finger_extended(mcp_idx: int, pip_idx: int, dip_idx: int, tip_idx: int) -> bool:
        dist_tip = np.linalg.norm(norm_pts[tip_idx, :2])
        dist_pip = np.linalg.norm(norm_pts[pip_idx, :2])
        dist_mcp = np.linalg.norm(norm_pts[mcp_idx, :2])
        # Criterio combinado: punta más alejada de la muñeca que PIP y por encima de PIP
        vertical_up = norm_pts[tip_idx, 1] < (norm_pts[pip_idx, 1] - 0.04)
        radial_out = dist_tip > (dist_pip * 1.12) and dist_tip > (dist_mcp * 1.25)
        return bool(vertical_up and radial_out)

    # Pulgar: comparamos distancia de la punta (4) al MCP del meñique (17) vs IP (3) al MCP (17)
    dist_thumb_tip_pinky = np.linalg.norm(norm_pts[THUMB_TIP, :2] - norm_pts[PINKY_MCP, :2])
    dist_thumb_ip_pinky = np.linalg.norm(norm_pts[THUMB_IP, :2] - norm_pts[PINKY_MCP, :2])
    dist_thumb_mcp_pinky = np.linalg.norm(norm_pts[THUMB_MCP, :2] - norm_pts[PINKY_MCP, :2])
    thumb_extended = bool(dist_thumb_tip_pinky > dist_thumb_ip_pinky * 1.12 and dist_thumb_tip_pinky > dist_thumb_mcp_pinky * 1.15)

    return {
        "thumb": thumb_extended,
        "index": is_finger_extended(INDEX_MCP, INDEX_PIP, INDEX_DIP, INDEX_TIP),
        "middle": is_finger_extended(MIDDLE_MCP, MIDDLE_PIP, MIDDLE_DIP, MIDDLE_TIP),
        "ring": is_finger_extended(RING_MCP, RING_PIP, RING_DIP, RING_TIP),
        "pinky": is_finger_extended(PINKY_MCP, PINKY_PIP, PINKY_DIP, PINKY_TIP),
    }

