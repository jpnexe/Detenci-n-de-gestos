"""
Módulo de Estabilización Temporal y Rechazo Activo (instrucciones.md Sección 3 y 5).
- Buffer circular de N=8 fotogramas.
- Umbral mínimo de confianza: >= 0.85 (cualquier predicción inferior se rechaza a G0).
- Cálculo de progreso del Anillo de Estabilidad Temporal (0.0 a 1.0) para el HUD.
"""

from __future__ import annotations
from collections import deque
import time
from typing import Deque, Dict, Any, Optional

from backend.classifier_local import GESTURE_CATALOG


class TemporalStabilizer:
    def __init__(
        self,
        buffer_size: int = 8,
        min_confidence: float = 0.85,
        cooldown_sec: float = 1.15,
    ):
        self.buffer_size = buffer_size
        self.min_confidence = min_confidence
        self.cooldown_sec = cooldown_sec
        self.buffer: Deque[str] = deque(maxlen=buffer_size)
        self.conf_buffer: Deque[float] = deque(maxlen=buffer_size)
        self.last_trigger_time: float = 0.0
        self.last_triggered_gesture: Optional[str] = None
        self.pulse_until: float = 0.0

    def reset(self) -> None:
        self.buffer.clear()
        self.conf_buffer.clear()
        self.last_triggered_gesture = None
        self.pulse_until = 0.0

    def update(self, raw_prediction: Dict[str, Any]) -> Dict[str, Any]:
        """
        Procesa una predicción cruda (Offline u Online), aplica el filtro de rechazo
        por umbral de confianza >= 0.85 y calcula el estado del anillo de retención.
        """
        now = time.time()
        gid = raw_prediction.get("gesture_id", "G0")
        conf = float(raw_prediction.get("confidence", 0.0))

        # Regla de Rechazo Activo: confianza < min_confidence pasa forzosamente a G0 (Desconocido)
        rejected_by_threshold = False
        if conf < self.min_confidence:
            gid = "G0"
            rejected_by_threshold = True

        self.buffer.append(gid)
        self.conf_buffer.append(conf)

        # Conteo de consistencia en la ventana circular N=8
        if gid == "G0":
            matching_frames = 0
            ring_progress = 0.0
        else:
            matching_frames = sum(1 for item in self.buffer if item == gid)
            ring_progress = round(min(1.0, matching_frames / float(self.buffer_size)), 3)

        in_cooldown = (now - self.last_trigger_time) < self.cooldown_sec
        triggered = False

        # Si el buffer circular completo (N=8) confirma el mismo comando y no estamos en cooldown
        if gid != "G0" and matching_frames >= self.buffer_size and not in_cooldown:
            triggered = True
            self.last_trigger_time = now
            self.last_triggered_gesture = gid
            self.pulse_until = now + 0.65
            # Reiniciar parcialmente el buffer tras disparo para requerir nueva retención deliberada
            self.buffer.clear()

        pulse_active = now < self.pulse_until
        meta = GESTURE_CATALOG.get(gid, GESTURE_CATALOG["G0"])

        return {
            "stabilized_id": gid,
            "name": meta["name"],
            "short_label": meta["short_label"],
            "sign_label": meta.get("sign_label", meta["short_label"]),
            "sign_message": meta.get("sign_message", ""),
            "action": meta["action"],
            "action_label": meta["action_label"],
            "confidence": round(conf, 4),
            "avg_confidence": round(sum(self.conf_buffer) / max(1, len(self.conf_buffer)), 4),
            "buffer_size": self.buffer_size,
            "matching_frames": matching_frames,
            "ring_progress": 1.0 if pulse_active else ring_progress,
            "triggered": triggered,
            "pulse_emerald": pulse_active,
            "in_cooldown": in_cooldown,
            "rejected": (gid == "G0"),
            "rejected_by_threshold": rejected_by_threshold,
            "buffer_snapshot": list(self.buffer),
        }

