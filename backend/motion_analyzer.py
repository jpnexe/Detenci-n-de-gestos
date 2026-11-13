"""
Analizador Cinemático y de Trayectoria de Movimiento — SignBridge Extended v3.0.

Rastrea la dinámica temporal de las articulaciones de la mano a lo largo de una ventana
deslizante (~15-25 fotogramas, 0.5-0.8s) para detectar gestos que requieren movimiento:
1. Trazo dinámico de letras dactilológicas (J trazada con meñique, Z trazada con índice, S).
2. Oscilación horizontal (saludo / adiós / negación lateral con índice / virgulilla Ñ).
3. Oscilación vertical (asentimiento afirmativo S_SI).
4. Desplazamiento descendente (repetición / más despacio).
5. Movimiento bimanual relativo (divergencia "¿cómo estás?", convergencia "mucho gusto",
   oscilación dual "¿qué? / ¿dónde?").
"""

from __future__ import annotations
import math
import time
from collections import deque
from typing import Dict, Any, List, Optional, Tuple
import numpy as np


class HandMotionHistory:
    """Almacena el historial de posiciones de una mano para análisis cinemático y de trazo."""

    def __init__(self, maxlen: int = 24):
        self.maxlen = maxlen
        # Entradas: (
        #   timestamp,
        #   wrist_x, wrist_y,
        #   index_tip_x, index_tip_y,
        #   palm_x, palm_y,
        #   pinky_tip_x, pinky_tip_y,
        #   thumb_tip_x, thumb_tip_y
        # )
        self.history: deque = deque(maxlen=maxlen)
        self.j_latch_until: float = 0.0
        self.z_latch_until: float = 0.0
        self.s_latch_until: float = 0.0
        self.h_latch_until: float = 0.0

    def append(self, pts: np.ndarray, timestamp: float) -> None:
        """Agrega los puntos clave normalizados [0..1] de la mano."""
        wrist = pts[0]
        thumb = pts[4]
        index_tip = pts[8]
        palm = pts[9]
        pinky_tip = pts[20] if len(pts) > 20 else pts[17]
        self.history.append((
            float(timestamp),
            float(wrist[0]), float(wrist[1]),
            float(index_tip[0]), float(index_tip[1]),
            float(palm[0]), float(palm[1]),
            float(pinky_tip[0]), float(pinky_tip[1]),
            float(thumb[0]), float(thumb[1]),
        ))

    def clear(self) -> None:
        self.history.clear()
        self.j_latch_until = 0.0
        self.z_latch_until = 0.0
        self.s_latch_until = 0.0
        self.h_latch_until = 0.0

    def analyze(self, now: Optional[float] = None) -> Dict[str, Any]:
        """
        Calcula velocidades, desplazamientos acumulados, cambios de sentido (oscilación)
        y patrones cinemáticos de trazo de letras (J, Z, S, H, G).
        """
        cur_time = now if now is not None else (self.history[-1][0] if self.history else time.time())
        n = len(self.history)
        if n < 4:
            is_j_latched = (cur_time < self.j_latch_until)
            is_z_latched = (cur_time < self.z_latch_until)
            is_s_latched = (cur_time < self.s_latch_until)
            is_h_latched = (cur_time < self.h_latch_until)
            return {
                "speed": 0.0,
                "is_moving": False,
                "is_oscillating_x": False,
                "is_oscillating_y": False,
                "is_moving_down": False,
                "is_moving_up": False,
                "is_moving_horiz": False,
                "trace_j": is_j_latched,
                "trace_z": is_z_latched,
                "trace_s": is_s_latched,
                "trace_h": is_h_latched,
                "oscillations_x": 0,
                "oscillations_y": 0,
                "net_dx": 0.0,
                "net_dy": 0.0,
                "path_length": 0.0,
                "efficiency": 0.0,
            }

        t_start = self.history[0][0]
        t_end = self.history[-1][0]
        dt_total = max(1e-4, t_end - t_start)

        # Extracción de coordenadas clave temporales
        wxs = [entry[1] for entry in self.history]
        wys = [entry[2] for entry in self.history]
        ixs = [entry[3] for entry in self.history]
        iys = [entry[4] for entry in self.history]
        pxs = [entry[5] for entry in self.history]  # palm_x
        pys = [entry[6] for entry in self.history]  # palm_y
        pinky_xs = [entry[7] for entry in self.history]  # pinky_tip_x
        pinky_ys = [entry[8] for entry in self.history]  # pinky_tip_y

        # 1. Desplazamiento de la palma y velocidad del centro de masa
        net_dx = pxs[-1] - pxs[0]
        net_dy = pys[-1] - pys[0]
        net_dist = math.hypot(net_dx, net_dy)

        path_len = 0.0
        for i in range(1, n):
            path_len += math.hypot(pxs[i] - pxs[i-1], pys[i] - pys[i-1])

        speed = path_len / dt_total
        efficiency = net_dist / max(1e-4, path_len)

        # Longitud y velocidad de la punta del dedo meñique e índice
        path_len_pinky = sum(math.hypot(pinky_xs[i] - pinky_xs[i-1], pinky_ys[i] - pinky_ys[i-1]) for i in range(1, n))
        speed_pinky = path_len_pinky / dt_total

        path_len_index = sum(math.hypot(ixs[i] - ixs[i-1], iys[i] - iys[i-1]) for i in range(1, n))
        speed_index = path_len_index / dt_total

        # 2. Conteo de cambios de sentido (Oscilación horizontal y vertical)
        def count_reversals(series: List[float], min_amp: float = 0.018) -> Tuple[int, float]:
            reversals = 0
            max_amp = 0.0
            last_dir = 0
            peak_val = series[0]

            for i in range(1, len(series)):
                diff = series[i] - series[i-1]
                if abs(diff) < 0.0025:
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

        # Oscilación horizontal: Palma (adiós), Índice (negación NO), Mano colgada (virgulilla Ñ)
        rev_x_palm, amp_x_palm = count_reversals(pxs, min_amp=0.024)
        rev_x_index, amp_x_index = count_reversals(ixs, min_amp=0.024)
        rev_x_wrist, amp_x_wrist = count_reversals(wxs, min_amp=0.024)
        max_rev_x = max(rev_x_palm, rev_x_index, rev_x_wrist)
        max_amp_x = max(amp_x_palm, amp_x_index, amp_x_wrist)

        is_oscillating_x = (max_rev_x >= 2 and max_amp_x >= 0.030)

        # Oscilación vertical: Índice o muñeca asintiendo (S_SI)
        rev_y_index, amp_y_index = count_reversals(iys, min_amp=0.022)
        rev_y_palm, amp_y_palm = count_reversals(pys, min_amp=0.022)
        max_rev_y = max(rev_y_index, rev_y_palm)
        max_amp_y = max(amp_y_index, amp_y_palm)

        is_oscillating_y = (max_rev_y >= 2 and max_amp_y >= 0.026)

        # Desplazamientos directos continuos (eje Y pantalla: positivo = abajo)
        is_moving_down = (net_dy > 0.042) and (efficiency > 0.50) and (speed > 0.07)
        is_moving_up = (net_dy < -0.042) and (efficiency > 0.50) and (speed > 0.07)
        is_moving_horiz = (abs(net_dx) > 0.034) and (efficiency > 0.45) and (speed > 0.055 or speed_index > 0.055)

        # 3. DETECCIÓN DE TRAZO DE LA LETRA 'J' (Meñique dibujando gancho hacia abajo y curva)
        # Una 'J' en LSC/Dactilología se realiza descendiendo y luego curvando hacia adentro/arriba
        trace_j = False
        is_j_latched = (cur_time < self.j_latch_until)

        if n >= 6 and (speed_pinky >= 0.06 or speed >= 0.06):
            # Evaluamos la trayectoria del meñique (o de la palma si el movimiento es de muñeca)
            deepest_idx = int(np.argmax(pinky_ys))
            deepest_y = pinky_ys[deepest_idx]

            # El punto más bajo (máximo Y en pantalla) no debe ser el primer punto
            if deepest_idx >= 2:
                # Descenso previo al gancho
                down_drop = deepest_y - min(pinky_ys[:deepest_idx + 1])
                # Rango horizontal cubierto durante el trazo
                span_x = max(pinky_xs) - min(pinky_xs)
                # Elevación posterior en el gancho (el meñique sube al finalizar la curva de la J)
                hook_up = deepest_y - pinky_ys[-1]

                # Condición 1: Descenso notable + elevación final en gancho + barrido horizontal
                is_hook_motion = (down_drop >= 0.028) and (span_x >= 0.016) and (hook_up >= 0.008)

                # Condición 2: Descenso con curva lateral suave aunque no se eleve exageradamente
                is_curved_swoop = (down_drop >= 0.032) and (span_x >= 0.022) and (deepest_idx <= n - 2)

                if is_hook_motion or is_curved_swoop:
                    self.j_latch_until = cur_time + 0.65  # Retención temporal de 650ms para confirmación
                    trace_j = True

        if not trace_j and is_j_latched:
            trace_j = True

        # 4. DETECCIÓN DE TRAZO DE LA LETRA 'Z' (Índice trazando zigzag)
        # Trazo Z: derecha -> diagonal abajo-izquierda -> derecha (mínimo 2 inversiones horizontales con descenso)
        trace_z = False
        is_z_latched = (cur_time < self.z_latch_until)

        if n >= 7 and (speed_index >= 0.06):
            z_span_x = max(ixs) - min(ixs)
            z_span_y = max(iys) - min(iys)
            if rev_x_index >= 2 and z_span_x >= 0.028 and z_span_y >= 0.028:
                self.z_latch_until = cur_time + 0.65
                trace_z = True

        if not trace_z and is_z_latched:
            trace_z = True

        # 5. DETECCIÓN DE TRAZO DE LA LETRA 'S' (exige amplitud real en X e Y y velocidad activa)
        trace_s = False
        is_s_latched = (cur_time < self.s_latch_until)
        if n >= 7 and rev_x_index >= 2 and amp_x_index >= 0.028 and (max(iys) - min(iys) >= 0.030) and speed_index >= 0.055:
            self.s_latch_until = cur_time + 0.55
            trace_s = True
        elif is_s_latched:
            trace_s = True

        # 6. DETECCIÓN DE DESLIZAMIENTO LATERAL (LETRA 'H' Y 'G')
        # La 'H' y 'G' implican mantener dedos horizontales y desplazarlos lateralmente con predominancia horizontal clara
        trace_h = False
        is_h_latched = (cur_time < self.h_latch_until)
        idx_dx = ixs[-1] - ixs[0]
        idx_dy = iys[-1] - iys[0]
        is_idx_horiz = (abs(idx_dx) >= 0.032) and (abs(idx_dx) > 1.15 * max(1e-4, abs(idx_dy)))
        is_palm_horiz = (abs(net_dx) >= 0.032) and (abs(net_dx) > 1.15 * max(1e-4, abs(net_dy)))
        if n >= 5 and (speed >= 0.055 or speed_index >= 0.055) and (is_idx_horiz or is_palm_horiz):
            self.h_latch_until = cur_time + 0.55
            trace_h = True
        elif is_h_latched:
            trace_h = True

        return {
            "speed": round(speed, 3),
            "speed_pinky": round(speed_pinky, 3),
            "speed_index": round(speed_index, 3),
            "is_moving": (speed > 0.05 or speed_pinky > 0.05 or speed_index > 0.05),
            "is_oscillating_x": is_oscillating_x,
            "is_oscillating_y": is_oscillating_y,
            "is_moving_down": is_moving_down,
            "is_moving_up": is_moving_up,
            "is_moving_horiz": is_moving_horiz,
            "trace_j": trace_j,
            "trace_z": trace_z,
            "trace_s": trace_s,
            "trace_h": trace_h,
            "oscillations_x": max_rev_x,
            "oscillations_y": max_rev_y,
            "amp_x": round(max_amp_x, 3),
            "amp_y": round(max_amp_y, 3),
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

        p_motion = self.primary_history.analyze(now=now)
        s_motion = self.secondary_history.analyze(now=now)

        # Análisis bimanual cinemático con umbrales calibrados
        bimanual_motion = {
            "is_diverging": False,
            "is_converging": False,
            "both_moving_down": False,
            "both_moving_up": False,
            "both_oscillating": False,
            "one_moving_horiz": False,
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

                # Divergencia: manos separándose activamente (ej. ¿Cómo estás? / Buenos días)
                if (d1 - d0) > 0.038 and d_rate > 0.075:
                    bimanual_motion["is_diverging"] = True
                # Convergencia: manos acercándose activamente (ej. Mucho gusto / Por favor)
                elif (d0 - d1) > 0.038 and d_rate < -0.075:
                    bimanual_motion["is_converging"] = True

            # Ambas manos descendiendo con calma (ej. Más despacio / Repetir)
            if p_motion.get("is_moving_down") and s_motion.get("is_moving_down"):
                bimanual_motion["both_moving_down"] = True

            # Ambas manos ascendiendo (ej. Feliz / Celebración)
            if p_motion.get("is_moving_up") and s_motion.get("is_moving_up"):
                bimanual_motion["both_moving_up"] = True

            # Ambas manos oscilando (ej. ¿Qué? / ¿Dónde?)
            if (p_motion.get("is_oscillating_x") or p_motion.get("is_oscillating_y")) and \
               (s_motion.get("is_oscillating_x") or s_motion.get("is_oscillating_y")):
                bimanual_motion["both_oscillating"] = True

            # Una mano deslizándose horizontalmente sobre la otra (ej. Buenas tardes)
            if p_motion.get("is_moving_horiz") or s_motion.get("is_moving_horiz"):
                bimanual_motion["one_moving_horiz"] = True

        return {
            "primary": p_motion,
            "secondary": s_motion,
            "bimanual": bimanual_motion,
        }
