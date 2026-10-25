"""
Controlador de Emulación de Hardware y Periféricos (pyautogui).
Ejecuta Scroll Arriba, Scroll Abajo, Clic Derecho y Llamadas de Asistencia.
"""

from __future__ import annotations
from collections import deque
from datetime import datetime
from typing import Deque, Dict, Any, List
import threading
import time


class HardwareController:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self.pointer_enabled = False  # Modo Control de Puntero de Mouse
        self.pyautogui_available = False
        self._pyautogui = None
        self.screen_w = 1920
        self.screen_h = 1080
        self.curr_x = 960.0
        self.curr_y = 540.0
        self.smoothing = 0.38  # Lerp anti-jitter (0.0 a 1.0)
        self.pointer_gain = 1.30  # Ganancia para alcanzar las 4 esquinas de la pantalla fácilmente
        self.last_pinch_click_time = 0.0
        self.is_pinching = False
        self.event_log: Deque[Dict[str, Any]] = deque(maxlen=25)
        self._init_pyautogui()

    def _init_pyautogui(self) -> None:
        try:
            import pyautogui
            pyautogui.FAILSAFE = False
            pyautogui.PAUSE = 0.005
            self._pyautogui = pyautogui
            self.pyautogui_available = True
            sz = pyautogui.size()
            self.screen_w = int(sz.width)
            self.screen_h = int(sz.height)
            self.curr_x = self.screen_w / 2.0
            self.curr_y = self.screen_h / 2.0
        except Exception:
            self.pyautogui_available = False

    def update_pointer(self, index_tip_xy: tuple[float, float], thumb_tip_xy: tuple[float, float]) -> Dict[str, Any]:
        """
        Dirige la posición del cursor de mouse en tiempo real mediante la punta del dedo índice (8).
        Rango ampliado ergonómico para alcanzar esquinas (como el botón Inicio de Windows) con facilidad.
        Calcula la distancia al pulgar (4) para ejecutar clic izquierdo por pellizco (pinch).
        """
        if not (self.enabled and self.pointer_enabled and self.pyautogui_available and self._pyautogui):
            return {"active": False, "cursor": [int(self.curr_x), int(self.curr_y)], "pinching": False, "clicked": False}

        raw_x, raw_y = index_tip_xy

        # Zona activa ergonómica de control:
        # X: [0.24, 0.76] -> Mover la mano un poco a la izquierda ya alcanza el borde izquierdo completo (0 px)
        # Y: [0.18, 0.64] -> Bajar la mano a 0.64 (altura natural sobre la mesa) ya alcanza la barra inferior de Windows (1080 px)
        m_x1, m_x2 = 0.24, 0.76
        m_y1, m_y2 = 0.18, 0.64

        norm_x = (raw_x - m_x1) / max(1e-4, m_x2 - m_x1)
        norm_y = (raw_y - m_y1) / max(1e-4, m_y2 - m_y1)

        # Aplicar ganancia centrada para alcanzar con soltura todos los bordes
        cx, cy = 0.5, 0.5
        norm_x = cx + (norm_x - cx) * self.pointer_gain
        norm_y = cy + (norm_y - cy) * self.pointer_gain

        norm_x = max(0.0, min(1.0, norm_x))
        norm_y = max(0.0, min(1.0, norm_y))

        target_x = norm_x * (self.screen_w - 1)
        target_y = norm_y * (self.screen_h - 1)

        # Si el usuario empuja hacia un borde o esquina, acelerar la convergencia para llegar a 0 px / screen_max
        at_edge = (norm_x <= 0.01 or norm_x >= 0.99 or norm_y <= 0.01 or norm_y >= 0.99)
        lerp_factor = 0.55 if at_edge else self.smoothing

        # Filtro de suavizado exponencial (lerp anti-temblor)
        self.curr_x = (1.0 - lerp_factor) * self.curr_x + lerp_factor * target_x
        self.curr_y = (1.0 - lerp_factor) * self.curr_y + lerp_factor * target_y

        px = max(0, min(self.screen_w - 1, int(round(self.curr_x))))
        py = max(0, min(self.screen_h - 1, int(round(self.curr_y))))

        # Adherencia firme a bordes y esquinas (para alcanzar con facilidad el botón Inicio de Windows y bordes de pantalla)
        if norm_x <= 0.015:
            px = 0
            self.curr_x = 0.0
        elif norm_x >= 0.985:
            px = self.screen_w - 1
            self.curr_x = float(px)

        if norm_y <= 0.015:
            py = 0
            self.curr_y = 0.0
        elif norm_y >= 0.985:
            py = self.screen_h - 1
            self.curr_y = float(py)

        # Mover mouse de forma no-bloqueante
        try:
            self._pyautogui.moveTo(px, py)
        except Exception:
            pass

        # Detección de pellizco (Pinch = Clic Izquierdo)
        dx = raw_x - thumb_tip_xy[0]
        dy = raw_y - thumb_tip_xy[1]
        dist_pinch = (dx * dx + dy * dy) ** 0.5

        now = time.time()
        clicked = False
        if dist_pinch < 0.055:  # Puntas unidas
            if not self.is_pinching and (now - self.last_pinch_click_time) > 0.40:
                self.is_pinching = True
                self.last_pinch_click_time = now
                clicked = True
                try:
                    self._pyautogui.click()
                    self.event_log.appendleft({
                        "timestamp": datetime.now().strftime("%H:%M:%S.%f")[:-3],
                        "gesture_id": "PINCH",
                        "gesture_name": "Pellizco Índice-Pulgar",
                        "action": "LEFT_CLICK",
                        "executed_os": True,
                        "detail": f"Clic Izquierdo en ({px}, {py})",
                    })
                except Exception:
                    pass
        else:
            self.is_pinching = False

        return {
            "active": True,
            "cursor": [px, py],
            "pinching": self.is_pinching,
            "clicked": clicked,
        }

    def execute_action(self, gesture_id: str, action_code: str, gesture_name: str) -> Dict[str, Any]:
        """
        Ejecuta la acción física de sistema operativo asociada al gesto confirmado
        y registra el evento en la bitácora de telemetría.
        """
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        executed_os = False
        detail = ""

        if action_code == "NONE" or gesture_id == "G0":
            return {"executed": False, "action": "NONE"}

        if self.enabled and self.pyautogui_available and self._pyautogui is not None:
            try:
                if action_code == "LEFT_CLICK":
                    threading.Thread(target=self._pyautogui.click, daemon=True).start()
                    executed_os = True
                    detail = "pyautogui.click() (Clic Izquierdo) disparado en OS"
                elif action_code == "RIGHT_CLICK":
                    threading.Thread(target=self._pyautogui.rightClick, daemon=True).start()
                    executed_os = True
                    detail = "pyautogui.rightClick() disparado en OS"
                elif action_code == "SCROLL_UP":
                    threading.Thread(target=self._pyautogui.scroll, args=(350,), daemon=True).start()
                    executed_os = True
                    detail = "pyautogui.scroll(+350) ejecutado"
                elif action_code == "SCROLL_DOWN":
                    threading.Thread(target=self._pyautogui.scroll, args=(-350,), daemon=True).start()
                    executed_os = True
                    detail = "pyautogui.scroll(-350) ejecutado"
                elif action_code == "ASSISTANCE_CALL":
                    threading.Thread(target=self._beep_assistance, daemon=True).start()
                    executed_os = True
                    detail = "Llamada de Asistencia / Alerta Prioritaria emitida"
            except Exception as exc:
                detail = f"Simulado en HUD ({exc})"
        else:
            detail = (
                "Alerta Prioritaria de Asistencia activada"
                if action_code == "ASSISTANCE_CALL"
                else f"Emulación HUD ({action_code}) — Control OS en pausa"
            )

        event = {
            "timestamp": timestamp,
            "gesture_id": gesture_id,
            "gesture_name": gesture_name,
            "action": action_code,
            "executed_os": executed_os,
            "detail": detail,
        }
        self.event_log.appendleft(event)
        return event

    def _beep_assistance(self) -> None:
        try:
            import winsound
            winsound.Beep(880, 180)
            winsound.Beep(1175, 240)
        except Exception:
            pass

    def get_recent_events(self) -> List[Dict[str, Any]]:
        return list(self.event_log)

