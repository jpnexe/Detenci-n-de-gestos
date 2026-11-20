"""
Modelo Secuencial Temporal (Dynamic Time Warping - DTW) para Gestos en Movimiento.

Complementa al clasificador estático 63D analizando la ventana temporal de trayectorias
de los últimos ~24 fotogramas (~0.8s) para reconocer trazos dinámicos (L_S, L_J, L_Z, L_H)
con invariancia a velocidad, tamaño y posición en pantalla.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple
import numpy as np


def _resample_trajectory(pts_2d: np.ndarray, n_points: int = 16) -> np.ndarray:
    """Remuestrea una trayectoria 2D (N x 2) a `n_points` equidistantes a lo largo del arco."""
    if len(pts_2d) < 2:
        return np.repeat(pts_2d[:1], n_points, axis=0)
    diffs = np.diff(pts_2d, axis=0)
    seg_lens = np.linalg.norm(diffs, axis=1)
    cum_len = np.concatenate([[0.0], np.cumsum(seg_lens)])
    total_len = float(cum_len[-1])
    if total_len < 1e-6:
        return np.repeat(pts_2d[:1], n_points, axis=0)
    target_dists = np.linspace(0.0, total_len, n_points)
    rx = np.interp(target_dists, cum_len, pts_2d[:, 0])
    ry = np.interp(target_dists, cum_len, pts_2d[:, 1])
    return np.stack([rx, ry], axis=1)


def _normalize_trajectory(pts_2d: np.ndarray) -> np.ndarray:
    """Centra y normaliza una trayectoria 2D por su escala espacial."""
    centered = pts_2d - np.mean(pts_2d, axis=0, keepdims=True)
    scale = float(np.max(np.linalg.norm(centered, axis=1)))
    if scale < 1e-6:
        return centered
    return centered / scale


def _dtw_distance(seq_a: np.ndarray, seq_b: np.ndarray) -> float:
    """Calcula la distancia Dynamic Time Warping normalizada entre dos secuencias 2D."""
    n, m = len(seq_a), len(seq_b)
    dtw = np.full((n + 1, m + 1), np.inf, dtype=np.float32)
    dtw[0, 0] = 0.0
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = float(np.linalg.norm(seq_a[i - 1] - seq_b[j - 1]))
            dtw[i, j] = cost + min(dtw[i - 1, j], dtw[i, j - 1], dtw[i - 1, j - 1])
    return float(dtw[n, m] / (n + m))


def _build_canonical_trajectories() -> Dict[str, np.ndarray]:
    """Genera las plantillas de trayectoria 2D canónicas (coordenadas de imagen: +x derecha, +y abajo)."""
    t = np.linspace(0.0, 1.0, 16)

    # L_S: Curva en S (inicia arriba-derecha -> curva izquierda -> curva derecha -> termina abajo-izquierda)
    s_x = 0.35 * np.cos(t * math.pi * 1.9 + 0.3) - 0.15 * np.sin(t * math.pi)
    s_y = -0.6 + 1.2 * t
    traj_s = _normalize_trajectory(np.stack([s_x, s_y], axis=1))

    # L_S espejo (por si el usuario la traza al revés / mano contraria en cámara espejo)
    traj_s_mirror = _normalize_trajectory(np.stack([-s_x, s_y], axis=1))

    # L_Z: Trazo en Z (derecha -> diagonal abajo-izquierda -> derecha)
    z_pts = np.array([
        [-0.5, -0.5], [0.0, -0.5], [0.5, -0.5],
        [0.15, -0.15], [-0.15, 0.15], [-0.5, 0.5],
        [0.0, 0.5], [0.5, 0.5],
    ], dtype=np.float32)
    traj_z = _normalize_trajectory(_resample_trajectory(z_pts, 16))
    traj_z_mirror = _normalize_trajectory(np.stack([-traj_z[:, 0], traj_z[:, 1]], axis=1))

    # L_J: Baja verticalmente y hace gancho hacia la izquierda y ligeramente arriba
    j_pts = np.array([
        [0.15, -0.6], [0.15, -0.2], [0.15, 0.2], [0.12, 0.45],
        [0.0, 0.55], [-0.20, 0.48], [-0.30, 0.30],
    ], dtype=np.float32)
    traj_j = _normalize_trajectory(_resample_trajectory(j_pts, 16))
    traj_j_mirror = _normalize_trajectory(np.stack([-traj_j[:, 0], traj_j[:, 1]], axis=1))

    return {
        "L_S": traj_s,
        "L_S_M": traj_s_mirror,
        "L_Z": traj_z,
        "L_Z_M": traj_z_mirror,
        "L_J": traj_j,
        "L_J_M": traj_j_mirror,
    }


CANONICAL_TRAJECTORIES = _build_canonical_trajectories()


class DynamicTrajectoryClassifier:
    """
    Evalúa trayectorias recientes (index_tip / pinky_tip) mediante DTW para distinguir
    con alta precisión trazos dinámicos como 'S', 'Z' y 'J' frente a posturas estáticas.
    """

    def classify_trajectory(
        self,
        pts_2d: List[Tuple[float, float]],
        candidate_ids: Tuple[str, ...],
        min_span: float = 0.045,
        max_dtw_dist: float = 0.34,
    ) -> Optional[Dict[str, float | str]]:
        if len(pts_2d) < 7:
            return None

        arr = np.asarray(pts_2d[-20:], dtype=np.float32)
        span_x = float(np.max(arr[:, 0]) - np.min(arr[:, 0]))
        span_y = float(np.max(arr[:, 1]) - np.min(arr[:, 1]))
        if max(span_x, span_y) < min_span:
            return None

        # Exigir recorrido mínimo real para descartar micro-temblores
        path_len = float(np.sum(np.linalg.norm(np.diff(arr, axis=0), axis=1)))
        if path_len < min_span * 1.4:
            return None

        norm_q = _normalize_trajectory(_resample_trajectory(arr, 16))

        best_id: Optional[str] = None
        best_dist = 999.0

        for cid in candidate_ids:
            for key in (cid, f"{cid}_M"):
                tmpl = CANONICAL_TRAJECTORIES.get(key)
                if tmpl is None:
                    continue
                d = _dtw_distance(norm_q, tmpl)
                if d < best_dist:
                    best_dist = d
                    best_id = cid

        if best_id is None or best_dist > max_dtw_dist:
            return None

        conf = max(0.86, min(0.99, 1.0 - best_dist * 0.45))
        return {"sign_id": best_id, "confidence": round(conf, 3), "dtw_distance": round(best_dist, 4)}


dynamic_trajectory_classifier = DynamicTrajectoryClassifier()

