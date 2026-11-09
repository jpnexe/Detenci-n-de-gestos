"""
Analizador Cinemático y de Trayectoria de Movimiento — SignBridge Extended v3.0.

Rastrea la dinámica temporal de las articulaciones de la mano a lo largo de una ventana
deslizante (~15-25 fotogramas, 0.5-0.8s) para detectar gestos que requieren movimiento:
1. Oscilación horizontal (saludo / adiós / negación lateral con índice).
2. Oscilación vertical (asentimiento afirmativo).
3. Desplazamiento descendente (repetición / más despacio).
4. Movimiento bimanual relativo (divergencia "¿cómo estás?", convergencia "mucho gusto",
   oscilación dual "¿qué? / ¿dónde?").
"""

from __future__ import annotations
import math
import time
from collections import deque
from typing import Dict, Any, List, Optional, Tuple
import numpy as np


class HandMotionHistory:
    """Almacena el historial de posiciones de una mano para análisis cinemático."""

    def __init__(self, maxlen: int = 24):
        self.maxlen = maxlen
        # Entradas: (timestamp, wrist_x, wrist_y, index_tip_x, index_tip_y, palm_x, palm_y)
        self.history: deque = deque(maxlen=maxlen)

    def append(self, pts: np.ndarray, timestamp: float) -> None:
        """Agrega los puntos clave normalizados [0..1] de la mano."""
        wrist = pts[0]
        index_tip = pts[8]
        palm = pts[9]
        self.history.append((
            timestamp,
            float(wrist[0]), float(wrist[1]),
            float(index_tip[0]), float(index_tip[1]),
            float(palm[0]), float(palm[1])
        ))

    def clear(self) -> None:
        self.history.clear()

    def analyze(self) -> Dict[str, Any]:
        """
        Calcula velocidades, desplazamientos acumulados, cambios de sentido (oscilación)
        y dirección predominante del movimiento.
        """
        n = len(self.history)
        if n < 4:
            return {
                "speed": 0.0,
                "is_moving": False,
                "is_oscillating_x": False,
                "is_oscillating_y": False,
                "is_moving_down": False,
                "is_moving_up": False,
                "oscillations_x": 0,
                "oscillations_y": 0,
                "net_dx": 0.0,
                "net_dy": 0.0,
                "path_length": 0.0,
                "efficiency": 0.0,
            }

        t_start, wx_start, wy_start, ix_start, iy_start, px_start, py_start = self.history[0]
        t_end, wx_end, wy_end, ix_end, iy_end, px_end, py_end = self.history[-1]
        dt_total = max(1e-4, t_end - t_start)

        # Usar la palma/muñeca como referencia del centro de masa de la mano
        xs = [entry[5] for entry in self.history]  # palm_x
        ys = [entry[6] for entry in self.history]  # palm_y
        ts = [entry[0] for entry in self.history]

        # También analizar la punta del índice para gestos de señalamiento/negación (S_NO, S_SI)
        ixs = [entry[3] for entry in self.history]
        iys = [entry[4] for entry in self.history]

        # Desplazamientos netos y longitud de trayectoria
        net_dx = px_end - px_start
        net_dy = py_end - py_start
        net_dist = math.hypot(net_dx, net_dy)

        path_len = 0.0
        for i in range(1, n):
            path_len += math.hypot(xs[i] - xs[i-1], ys[i] - ys[i-1])

        speed = path_len / dt_total
        efficiency = net_dist / max(1e-4, path_len)

        # Detección de oscilación en X (cambios de signo en la velocidad horizontal)
        # Se evalúa tanto la palma (adiós/saludo) como el dedo índice (negación NO)
        def count_reversals(series: List[float], min_amp: float = 0.025) -> Tuple[int, float]:
            reversals = 0
            max_amp = 0.0
            last_dir = 0  # +1 o -1
            peak_val = series[0]

            for i in range(1, len(series)):
                diff = series[i] - series[i-1]
                if abs(diff) < 0.003:
                    continue
                cur_dir = 1 if diff > 0 else -1
                if last_dir != 0 and cur_dir != last_dir:
                    amp = abs(series[i-1] - peak_val)
                    if amp >= min_amp:
                        reversals += 1
                        if amp > max_amp:
                            max_amp = amp
                    peak_val = series[i-1]
                last_dir = cur_dir
            return reversals, max_amp

        rev_x_palm, amp_x_palm = count_reversals(xs, min_amp=0.028)
        rev_x_index, amp_x_index = count_reversals(ixs, min_amp=0.035)
        rev_y_index, amp_y_index = count_reversals(iys, min_amp=0.030)

        is_oscillating_x = (rev_x_palm >= 2 and amp_x_palm >= 0.035) or (rev_x_index >= 2 and amp_x_index >= 0.040)
        is_oscillating_y = (rev_y_index >= 2 and amp_y_index >= 0.035)

        # Desplazamiento descendente continuo (pantalla Y aumenta hacia abajo)
        is_moving_down = (net_dy > 0.075) and (efficiency > 0.58) and (speed > 0.12)
        is_moving_up = (net_dy < -0.075) and (efficiency > 0.58) and (speed > 0.12)

        return {
            "speed": round(speed, 3),
            "is_moving": speed > 0.10,
            "is_oscillating_x": is_oscillating_x,
            "is_oscillating_y": is_oscillating_y,
            "is_moving_down": is_moving_down,
            "is_moving_up": is_moving_up,
            "oscillations_x": max(rev_x_palm, rev_x_index),
            "oscillations_y": rev_y_index,
            "amp_x": round(max(amp_x_palm, amp_x_index), 3),
            "amp_y": round(amp_y_index, 3),
            "net_dx": round(net_dx, 3),
            "net_dy": round(net_dy, 3),
            "path_length": round(path_len, 3),
            "efficiency": round(efficiency, 3),
        }


class KinematicMotionAnalyzer:
    """
    Rastreador cinemático bimanual completo.
    Conecta con el pipeline para dotar a la clasificación gestual de discriminación dinámica.
    """

    def __init__(self, history_size: int = 24):
        self.primary_history = HandMotionHistory(maxlen=history_size)
        self.secondary_history = HandMotionHistory(maxlen=history_size)
        self.bimanual_dist_history: deque = deque(maxlen=history_size)
        self.last_update_ts = 0.0

    def reset(self) -> None:
        self.primary_history.clear()
        self.secondary_history.clear()
        self.bimanual_dist_history.clear()

    def update(
        self,
        primary_pts: Optional[np.ndarray],
        secondary_pts: Optional[np.ndarray] = None,
        timestamp: Optional[float] = None
    ) -> Dict[str, Any]:
        now = timestamp if timestamp is not None else time.perf_counter()

        # Actualizar historial mano primaria
        if primary_pts is not None and len(primary_pts) >= 21:
            self.primary_history.append(primary_pts, now)
        else:
            self.primary_history.clear()

        # Actualizar historial mano secundaria
        if secondary_pts is not None and len(secondary_pts) >= 21:
            self.secondary_history.append(secondary_pts, now)
        else:
            self.secondary_history.clear()

        p_motion = self.primary_history.analyze()
        s_motion = self.secondary_history.analyze()

        # Análisis bimanual cinemático
        bimanual_motion = {
            "is_diverging": False,
            "is_converging": False,
            "both_moving_down": False,
            "both_oscillating": False,
            "divergence_rate": 0.0,
        }

        if primary_pts is not None and secondary_pts is not None:
            dist = float(np.linalg.norm(primary_pts[0, :2] - secondary_pts[0, :2]))
            self.bimanual_dist_history.append((now, dist))

            if len(self.bimanual_dist_history) >= 4:
                t0, d0 = self.bimanual_dist_history[0]
                t1, d1 = self.bimanual_dist_history[-1]
                dt = max(1e-4, t1 - t0)
                d_rate = (d1 - d0) / dt
                bimanual_motion["divergence_rate"] = round(d_rate, 3)

                # Divergencia: manos separándose activamente (ej. ¿Cómo estás?)
                if (d1 - d0) > 0.08 and d_rate > 0.15:
                    bimanual_motion["is_diverging"] = True
                # Convergencia: manos acercándose activamente (ej. Mucho gusto / Por favor)
                elif (d0 - d1) > 0.08 and d_rate < -0.15:
                    bimanual_motion["is_converging"] = True

            # Ambas manos descendiendo con calma (ej. Más despacio)
            if p_motion.get("is_moving_down") and s_motion.get("is_moving_down"):
                bimanual_motion["both_moving_down"] = True

            # Ambas manos oscilando (ej. ¿Qué? / ¿Dónde?)
            if (p_motion.get("is_oscillating_x") or p_motion.get("is_oscillating_y")) and \
               (s_motion.get("is_oscillating_x") or s_motion.get("is_oscillating_y")):
                bimanual_motion["both_oscillating"] = True

        return {
            "primary": p_motion,
            "secondary": s_motion,
            "bimanual": bimanual_motion,
        }

