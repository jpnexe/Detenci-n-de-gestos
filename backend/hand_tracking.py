"""
Seguimiento Temporal de Manos y Análisis Biomecánico Robusto — SignBridge Extended.

Mejoras de precisión respecto al análisis estático por fotograma:
1. Filtro 1€ vectorizado (21x3) por mano: elimina el temblor (jitter) de MediaPipe sin
   introducir rezago cuando la mano se mueve rápido.
2. Identidad persistente de cada mano (asignación por proximidad + lateralidad): la mano
   primaria no "salta" entre manos cuando MediaPipe reordena sus resultados.
3. Ángulos articulares 3D sobre world landmarks (metros, invariantes a rotación,
   perspectiva y relación de aspecto de la cámara).
4. Puntuación continua por dedo con hysteresis: un dedo cerca del umbral no parpadea
   entre EXTENDIDO / PLEGADO, y se expone un margen de certeza para calcular la confianza.
5. Periodo de gracia: si MediaPipe pierde la mano 1-3 fotogramas se mantiene la última
   pose en vez de emitir un "sin mano" espurio que reinicia el estabilizador.
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


# Índices anatómicos de MediaPipe Hands (21 Landmarks)
WRIST = 0
THUMB_CMC, THUMB_MCP, THUMB_IP, THUMB_TIP = 1, 2, 3, 4
INDEX_MCP, INDEX_PIP, INDEX_DIP, INDEX_TIP = 5, 6, 7, 8
MIDDLE_MCP, MIDDLE_PIP, MIDDLE_DIP, MIDDLE_TIP = 9, 10, 11, 12
RING_MCP, RING_PIP, RING_DIP, RING_TIP = 13, 14, 15, 16
PINKY_MCP, PINKY_PIP, PINKY_DIP, PINKY_TIP = 17, 18, 19, 20

FINGER_NAMES = ("thumb", "index", "middle", "ring", "pinky")
LONG_FINGERS = {
    "index": (INDEX_MCP, INDEX_PIP, INDEX_DIP, INDEX_TIP),
    "middle": (MIDDLE_MCP, MIDDLE_PIP, MIDDLE_DIP, MIDDLE_TIP),
    "ring": (RING_MCP, RING_PIP, RING_DIP, RING_TIP),
    "pinky": (PINKY_MCP, PINKY_PIP, PINKY_DIP, PINKY_TIP),
}

# Calibración de la curvatura acumulada (MCP + PIP + DIP, en grados).
# Dedo recto ≈ 10-35°, puño cerrado ≈ 180-260°. Punto medio de decisión ≈ 92°.
CURL_MIDPOINT_DEG = 92.0
CURL_HALF_SPAN_DEG = 50.0
# Banda de hysteresis sobre la puntuación normalizada [-1, 1]
FINGER_HYSTERESIS = 0.12


# ---------------------------------------------------------------------------
# Utilidades geométricas
# ---------------------------------------------------------------------------
def _angle_deg(v1: np.ndarray, v2: np.ndarray) -> float:
    n1 = float(np.linalg.norm(v1))
    n2 = float(np.linalg.norm(v2))
    if n1 < 1e-9 or n2 < 1e-9:
        return 0.0
    c = float(np.dot(v1, v2) / (n1 * n2))
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def aspect_correct(pts: np.ndarray, aspect: float) -> np.ndarray:
    """
    Convierte landmarks normalizados de imagen (x/ancho, y/alto, z ~ escala de x) a un
    espacio isótropo donde una unidad mide lo mismo en ambos ejes (unidades de alto).
    Sin esta corrección, en una cámara 4:3 los ángulos horizontales quedan comprimidos.
    """
    out = np.asarray(pts, dtype=np.float32).reshape(21, 3).copy()
    out[:, 0] *= aspect
    out[:, 2] *= aspect
    return out


def finger_scores(pts3d: np.ndarray) -> Dict[str, float]:
    """
    Calcula una puntuación continua en [-1, 1] por dedo (positivo = extendido) a partir de
    puntos 3D isótropos (world landmarks o landmarks de imagen corregidos por aspecto).
    """
    p = np.asarray(pts3d, dtype=np.float32).reshape(21, 3)
    scores: Dict[str, float] = {}

    # Dedos largos: curvatura acumulada en MCP, PIP y DIP
    for name, (mcp, pip, dip, tip) in LONG_FINGERS.items():
        bend_mcp = _angle_deg(p[mcp] - p[WRIST], p[pip] - p[mcp])
        bend_pip = _angle_deg(p[pip] - p[mcp], p[dip] - p[pip])
        bend_dip = _angle_deg(p[dip] - p[pip], p[tip] - p[dip])
        curl = bend_mcp + bend_pip + bend_dip
        s_curl = (CURL_MIDPOINT_DEG - curl) / CURL_HALF_SPAN_DEG

        # Refuerzo radial: la punta debe alejarse de la muñeca más que el PIP
        d_tip = float(np.linalg.norm(p[tip] - p[WRIST]))
        d_pip = float(np.linalg.norm(p[pip] - p[WRIST]))
        radial = max(-1.0, min(1.0, (d_tip / max(1e-6, d_pip) - 1.08) / 0.25))
        s = 0.75 * s_curl + 0.25 * radial
        scores[name] = float(max(-1.0, min(1.0, s)))

    # Pulgar: rectitud de la cadena + abducción respecto al índice + orientación hacia afuera
    palm_width = max(1e-6, float(np.linalg.norm(p[INDEX_MCP] - p[PINKY_MCP])))
    bend_thumb = (
        _angle_deg(p[THUMB_MCP] - p[THUMB_CMC], p[THUMB_IP] - p[THUMB_MCP])
        + _angle_deg(p[THUMB_IP] - p[THUMB_MCP], p[THUMB_TIP] - p[THUMB_IP])
    )
    abduction = float(np.linalg.norm(p[THUMB_TIP] - p[INDEX_MCP])) / palm_width
    outward = float(np.linalg.norm(p[THUMB_TIP] - p[PINKY_MCP])) / max(
        1e-6, float(np.linalg.norm(p[THUMB_MCP] - p[PINKY_MCP]))
    )
    s_straight = (65.0 - bend_thumb) / 35.0
    s_abd = (abduction - 0.72) / 0.25
    s_out = (outward - 1.0) / 0.2
    scores["thumb"] = float(max(-1.0, min(1.0, min(s_straight, s_abd, s_out))))
    return scores


def palm_orientation(pts3d: np.ndarray) -> Dict[str, Any]:
    """
    Normal de la palma (producto cruz muñeca->índice x muñeca->meñique). Se usa solo la
    componente dominante (sin signo) para distinguir palma vertical (mirando a la cámara)
    de palma horizontal (mirando arriba/abajo), lo cual es robusto a la lateralidad.
    """
    p = np.asarray(pts3d, dtype=np.float32).reshape(21, 3)
    n = np.cross(p[INDEX_MCP] - p[WRIST], p[PINKY_MCP] - p[WRIST])
    norm = float(np.linalg.norm(n))
    if norm < 1e-9:
        return {"normal": [0.0, 0.0, 1.0], "facing": "camera"}
    n = n / norm
    ay, az = abs(float(n[1])), abs(float(n[2]))
    facing = "horizontal" if ay > az * 1.15 else "camera"
    return {"normal": [round(float(n[0]), 3), round(float(n[1]), 3), round(float(n[2]), 3)], "facing": facing}


def scores_to_states(scores: Dict[str, float], prev: Optional[Dict[str, bool]] = None,
                     hysteresis: float = FINGER_HYSTERESIS) -> Dict[str, bool]:
    """Convierte puntuaciones en estados booleanos aplicando hysteresis si hay estado previo."""
    states: Dict[str, bool] = {}
    for name in FINGER_NAMES:
        s = scores.get(name, -1.0)
        if prev is None or name not in prev:
            states[name] = s > 0.0
        elif prev[name]:
            states[name] = s > -hysteresis
        else:
            states[name] = s > hysteresis
    return states


def scores_to_margins(scores: Dict[str, float]) -> Dict[str, float]:
    """Margen de certeza [0, 1] de cada dedo (distancia a la frontera de decisión)."""
    return {k: round(float(min(1.0, abs(v) / 0.6)), 3) for k, v in scores.items()}


# ---------------------------------------------------------------------------
# Filtro 1€ vectorizado
# ---------------------------------------------------------------------------
class OneEuroArray:
    """Filtro 1€ aplicado elemento a elemento sobre un arreglo NumPy de forma fija."""

    def __init__(self, min_cutoff: float, beta: float, d_cutoff: float = 1.0):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self.x_prev: Optional[np.ndarray] = None
        self.dx_prev: Optional[np.ndarray] = None
        self.t_prev: Optional[float] = None

    @staticmethod
    def _alpha(cutoff, dt: float):
        tau = 1.0 / (2.0 * math.pi * np.maximum(1e-4, cutoff))
        return 1.0 / (1.0 + tau / dt)

    def reset(self) -> None:
        self.x_prev = None
        self.dx_prev = None
        self.t_prev = None

    def __call__(self, x: np.ndarray, t: float) -> np.ndarray:
        x = np.asarray(x, dtype=np.float32)
        if self.x_prev is None or self.t_prev is None or self.x_prev.shape != x.shape:
            self.x_prev = x.copy()
            self.dx_prev = np.zeros_like(x)
            self.t_prev = t
            return x.copy()
        dt = max(1.0 / 120.0, min(0.25, t - self.t_prev))
        self.t_prev = t
        dx = (x - self.x_prev) / dt
        a_d = self._alpha(self.d_cutoff, dt)
        dx_hat = a_d * dx + (1.0 - a_d) * self.dx_prev
        cutoff = self.min_cutoff + self.beta * np.abs(dx_hat)
        a = self._alpha(cutoff, dt)
        x_hat = a * x + (1.0 - a) * self.x_prev
        self.x_prev = x_hat.astype(np.float32)
        self.dx_prev = dx_hat.astype(np.float32)
        return self.x_prev.copy()


# ---------------------------------------------------------------------------
# Seguimiento de manos
# ---------------------------------------------------------------------------
class _Track:
    _next_id = 1

    def __init__(self, label: str, now: float):
        self.id = _Track._next_id
        _Track._next_id += 1
        self.label = label
        self._label_votes = 0
        self.f_img = OneEuroArray(min_cutoff=1.7, beta=10.0, d_cutoff=1.0)
        self.f_world = OneEuroArray(min_cutoff=2.0, beta=25.0, d_cutoff=1.0)
        self.img: Optional[np.ndarray] = None
        self.world: Optional[np.ndarray] = None
        self.states: Optional[Dict[str, bool]] = None
        self.scores: Dict[str, float] = {}
        self.last_seen = now
        self.age = 0

    def update_label(self, new_label: str) -> None:
        # La lateralidad cambia solo tras varios fotogramas consistentes (evita parpadeos)
        if new_label == self.label:
            self._label_votes = 0
            return
        self._label_votes += 1
        if self._label_votes >= 5:
            self.label = new_label
            self._label_votes = 0


class HandTracker:
    """
    Mantiene la identidad, el suavizado y el estado biomecánico de hasta 2 manos a lo largo
    del tiempo. Recibe detecciones crudas de MediaPipe y devuelve manos estabilizadas.
    """

    def __init__(self, max_hands: int = 2, grace_sec: float = 0.12, match_dist: float = 0.30):
        self.max_hands = max_hands
        self.grace_sec = grace_sec
        self.match_dist = match_dist
        self.tracks: List[_Track] = []
        self.primary_id: Optional[int] = None

    def reset(self) -> None:
        self.tracks.clear()
        self.primary_id = None

    def _assign(self, dets: List[Dict[str, Any]], aspect: float) -> List[Tuple[int, int]]:
        """Asignación óptima (fuerza bruta, n <= 2) detecciones -> tracks por coste."""
        if not dets or not self.tracks:
            return []
        pairs: List[Tuple[float, int, int]] = []
        for di, d in enumerate(dets):
            w = np.array([d["img"][WRIST, 0] * aspect, d["img"][WRIST, 1]])
            c = np.array([d["img"][MIDDLE_MCP, 0] * aspect, d["img"][MIDDLE_MCP, 1]])
            for ti, t in enumerate(self.tracks):
                if t.img is None:
                    continue
                tw = np.array([t.img[WRIST, 0] * aspect, t.img[WRIST, 1]])
                tc = np.array([t.img[MIDDLE_MCP, 0] * aspect, t.img[MIDDLE_MCP, 1]])
                cost = 0.5 * float(np.linalg.norm(w - tw)) + 0.5 * float(np.linalg.norm(c - tc))
                if d["label"] != t.label:
                    cost += 0.08
                if cost <= self.match_dist:
                    pairs.append((cost, di, ti))
        pairs.sort()
        used_d, used_t, result = set(), set(), []
        for cost, di, ti in pairs:
            if di in used_d or ti in used_t:
                continue
            used_d.add(di)
            used_t.add(ti)
            result.append((di, ti))
        return result

    def update(
        self,
        detections: List[Dict[str, Any]],
        aspect: float = 1.0,
        now: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        detections: lista de dicts {"img": (21,3), "world": (21,3)|None, "label": str}.
        Devuelve manos ordenadas [primaria, secundaria] con landmarks suavizados y estado.
        """
        if now is None:
            now = time.perf_counter()

        dets = detections[: self.max_hands]
        matches = self._assign(dets, aspect)
        matched_d = {di for di, _ in matches}
        matched_t = {ti for _, ti in matches}

        # Nuevos tracks para detecciones sin asignar
        for di, d in enumerate(dets):
            if di not in matched_d:
                t = _Track(d["label"], now)
                self.tracks.append(t)
                matches.append((di, len(self.tracks) - 1))
                matched_t.add(len(self.tracks) - 1)

        # Actualizar tracks asignados
        for di, ti in matches:
            d = dets[di]
            t = self.tracks[ti]
            t.update_label(d["label"])
            t.img = t.f_img(d["img"], now)
            if d.get("world") is not None:
                t.world = t.f_world(d["world"], now)
            else:
                t.world = None
                t.f_world.reset()
            geo = t.world if t.world is not None else aspect_correct(t.img, aspect)
            t.scores = finger_scores(geo)
            t.states = scores_to_states(t.scores, t.states)
            t.last_seen = now
            t.age += 1

        # Eliminar tracks expirados (fuera del periodo de gracia)
        self.tracks = [
            t for i, t in enumerate(self.tracks)
            if i in matched_t or (now - t.last_seen) <= self.grace_sec
        ]
        if len(self.tracks) > self.max_hands:
            self.tracks.sort(key=lambda t: t.last_seen, reverse=True)
            self.tracks = self.tracks[: self.max_hands]

        live = [t for t in self.tracks if t.img is not None and t.states is not None]
        if not live:
            self.primary_id = None
            return []

        # Selección estable de la mano primaria
        ids = {t.id for t in live}
        if self.primary_id not in ids:
            rights = [t for t in live if t.label == "Right"]
            pool = rights if rights else live
            # Preferir la mano más grande (más cercana a la cámara)
            def _size(t: _Track) -> float:
                a = aspect_correct(t.img, aspect)
                return float(np.linalg.norm(a[WRIST, :2] - a[MIDDLE_MCP, :2]))
            self.primary_id = max(pool, key=_size).id

        live.sort(key=lambda t: 0 if t.id == self.primary_id else 1)
        out: List[Dict[str, Any]] = []
        for t in live:
            geo = t.world if t.world is not None else aspect_correct(t.img, aspect)
            out.append({
                "track_id": t.id,
                "landmarks": t.img.copy(),
                "world": None if t.world is None else t.world.copy(),
                "label": t.label,
                "fingers": dict(t.states),
                "finger_scores": {k: round(v, 3) for k, v in t.scores.items()},
                "finger_margins": scores_to_margins(t.scores),
                "palm": palm_orientation(geo),
                "held": (now - t.last_seen) > 1e-6,
            })
        return out
