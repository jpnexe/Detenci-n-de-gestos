"""
Controlador de Emulación de Hardware y Periféricos (pyautogui + Win32 user32.SetCursorPos).
Incluye Filtro 1€ Adaptativo por Velocidad, Anclaje Pre-Pinch e Interpolador Sub-Frame a 120 Hz
para movimientos de cursor sedosos, precisos y sin sensación de rezago.
"""

from __future__ import annotations
from collections import deque
from datetime import datetime
from typing import Deque, Dict, Any, List, Optional
import ctypes
import math
import threading
import time


class OneEuroFilter1D:
    """
    Filtro 1€ (1-Euro Filter) de suavizado adaptativo por velocidad:
    - A baja velocidad (apuntando a un botón): alta atenuación de temblor (min_cutoff bajo).
    - A alta velocidad (cruzando la pantalla): alta frecuencia de corte (beta * |velocidad|)
      para seguimiento instantáneo sin sentirse pegado ni con retraso.
    """

    def __init__(self, min_cutoff: float = 1.25, beta: float = 0.042, d_cutoff: float = 1.0):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self.x_prev: Optional[float] = None
        self.dx_prev: float = 0.0
        self.t_prev: Optional[float] = None

    @staticmethod
    def _alpha(cutoff: float, dt: float) -> float:
        tau = 1.0 / (2.0 * math.pi * max(1e-4, cutoff))
        return 1.0 / (1.0 + tau / max(1e-4, dt))

    def filter(self, x: float, now: Optional[float] = None) -> float:
        if now is None:
            now = time.perf_counter()
        if self.x_prev is None or self.t_prev is None:
            self.x_prev = x
            self.t_prev = now
            return x

        dt = max(0.016, min(0.25, now - self.t_prev))
        self.t_prev = now

        # Derivada filtrada (velocidad del movimiento)
        dx = (x - self.x_prev) / dt
        a_d = self._alpha(self.d_cutoff, dt)
        dx_hat = a_d * dx + (1.0 - a_d) * self.dx_prev
        self.dx_prev = dx_hat

        # Frecuencia de corte adaptativa según la rapidez de la mano
        cutoff = self.min_cutoff + self.beta * abs(dx_hat)
        a = self._alpha(cutoff, dt)
        x_hat = a * x + (1.0 - a) * self.x_prev
        self.x_prev = x_hat
        return x_hat


class HardwareController:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self.pointer_enabled = False  # Modo Control de Puntero de Mouse
        self.pyautogui_available = False
        self._pyautogui = None
        self._user32 = None

        self.screen_w = 1920
        self.screen_h = 1080
        self.curr_x = 960.0
        self.curr_y = 540.0
        self.target_x = 960.0
        self.target_y = 540.0
        self.last_target_update_ts = 0.0

        # Parámetros ergonómicos y filtros adaptativos 1€ (calibrados para coordenadas [0..1])
        self.smoothing = 0.38
        self.pointer_gain = 1.26
        self.deadzone_px = 1.5  # Micro-zona muerta anti-temblor subpíxel
        self._filter_x = OneEuroFilter1D(min_cutoff=1.60, beta=2.80, d_cutoff=1.2)
        self._filter_y = OneEuroFilter1D(min_cutoff=1.60, beta=2.80, d_cutoff=1.2)

        self.last_pinch_click_time = 0.0
        self.is_pinching = False
        self.event_log: Deque[Dict[str, Any]] = deque(maxlen=25)

        self._init_pyautogui()
        self._start_120hz_cursor_interpolator()

    def _init_pyautogui(self) -> None:
        # Inicializar API nativa Win32 (SetCursorPos = 0ms de bloqueo)
        try:
            if hasattr(ctypes, "windll"):
                self._user32 = ctypes.windll.user32
        except Exception:
            self._user32 = None

        try:
            import pyautogui
            pyautogui.FAILSAFE = False
            pyautogui.PAUSE = 0.0
            self._pyautogui = pyautogui
            self.pyautogui_available = True
            sz = pyautogui.size()
            self.screen_w = int(sz.width)
            self.screen_h = int(sz.height)
            self.curr_x = self.screen_w / 2.0
            self.curr_y = self.screen_h / 2.0
            self.target_x = self.curr_x
            self.target_y = self.curr_y
        except Exception:
            self.pyautogui_available = False

    def _set_os_cursor(self, px: int, py: int) -> None:
        """Mueve el cursor físico usando la llamada nativa Win32 (0ms overhead) o pyautogui de respaldo."""
        if self._user32 is not None:
            try:
                self._user32.SetCursorPos(int(px), int(py))
                return
            except Exception:
                pass
        if self._pyautogui is not None:
            try:
                self._pyautogui.moveTo(int(px), int(py), _pause=False)
            except Exception:
                pass

    def _start_120hz_cursor_interpolator(self) -> None:
        """
        Hilo interpolador sub-frame a 120 Hz:
        Suaviza los ~25 FPS de la cámara convirtiéndolos en deslizamientos continuos de 120 FPS
        en la pantalla de Windows, sin sentirse pegado ni con saltos entre fotogramas.
        """
        def _loop():
            while True:
                time.sleep(0.008)  # ~120 Hz
                if not (self.enabled and self.pointer_enabled and self.pyautogui_available):
                    continue
                if (time.perf_counter() - self.last_target_update_ts) > 0.25:
                    continue

                dx = self.target_x - self.curr_x
                dy = self.target_y - self.curr_y
                dist = math.hypot(dx, dy)

                if dist < 0.35:
                    continue

                # Paso adaptativo a 120 Hz: rápido en distancias largas, sedoso en micro-ajustes
                step_gain = min(0.55, max(0.24, dist / 95.0))
                self.curr_x += dx * step_gain
                self.curr_y += dy * step_gain

                px = max(0, min(self.screen_w - 1, int(round(self.curr_x))))
                py = max(0, min(self.screen_h - 1, int(round(self.curr_y))))
                self._set_os_cursor(px, py)

        t = threading.Thread(target=_loop, daemon=True)
        t.start()

    def update_pointer(self, index_tip_xy: tuple[float, float], thumb_tip_xy: tuple[float, float]) -> Dict[str, Any]:
        """
        Dirige la posición del cursor de mouse en tiempo real mediante la punta del dedo índice (8)
        con Filtro 1€ adaptativo por velocidad y estabilización Pre-Pinch al hacer clic con el pulgar (4).
        """
        if not (self.enabled and self.pointer_enabled and self.pyautogui_available and self._pyautogui):
            return {"active": False, "cursor": [int(self.curr_x), int(self.curr_y)], "pinching": False, "clicked": False}

        raw_x, raw_y = index_tip_xy

        # Distancia de pellizco (Pinch = Clic Izquierdo)
        dx_p = raw_x - thumb_tip_xy[0]
        dy_p = raw_y - thumb_tip_xy[1]
        dist_pinch = math.hypot(dx_p, dy_p)

        # Zona activa ergonómica de control para alcanzar las 4 esquinas y la barra de tareas sin esfuerzo
        m_x1, m_x2 = 0.24, 0.76
        m_y1, m_y2 = 0.18, 0.64

        norm_x = (raw_x - m_x1) / max(1e-4, m_x2 - m_x1)
        norm_y = (raw_y - m_y1) / max(1e-4, m_y2 - m_y1)

        cx, cy = 0.5, 0.5
        norm_x = cx + (norm_x - cx) * self.pointer_gain
        norm_y = cy + (norm_y - cy) * self.pointer_gain

        norm_x = max(0.0, min(1.0, norm_x))
        norm_y = max(0.0, min(1.0, norm_y))

        now_perf = time.perf_counter()

        # 1. Filtrar coordenadas normalizadas con el Filtro 1€ Adaptativo por Velocidad
        filt_nx = self._filter_x.filter(norm_x, now_perf)
        filt_ny = self._filter_y.filter(norm_y, now_perf)

        raw_target_x = max(0.0, min(float(self.screen_w - 1), filt_nx * (self.screen_w - 1)))
        raw_target_y = max(0.0, min(float(self.screen_h - 1), filt_ny * (self.screen_h - 1)))

        # 2. Micro-zona muerta y Anclaje Pre-Pinch:
        #    Cuando el usuario empieza a juntar índice y pulgar (dist_pinch < 0.085),
        #    amortiguamos el desplazamiento para que el cursor no se mueva del botón al hacer clic.
        delta_target = math.hypot(raw_target_x - self.target_x, raw_target_y - self.target_y)
        if delta_target >= self.deadzone_px:
            if dist_pinch < 0.085:
                # Estabilizador Pre-Pinch (mantiene fijo el puntero sobre el objetivo mientras cierras la pinza)
                anchor_blend = 0.18
                self.target_x = (1.0 - anchor_blend) * self.target_x + anchor_blend * raw_target_x
                self.target_y = (1.0 - anchor_blend) * self.target_y + anchor_blend * raw_target_y
            else:
                self.target_x = raw_target_x
                self.target_y = raw_target_y

        self.last_target_update_ts = now_perf

        # Actualizar también un paso inmediato para respuesta instantánea en el mismo frame
        step_dx = self.target_x - self.curr_x
        step_dy = self.target_y - self.curr_y
        dist_curr = math.hypot(step_dx, step_dy)
        immediate_gain = min(0.68, max(0.32, dist_curr / 110.0))
        self.curr_x += step_dx * immediate_gain
        self.curr_y += step_dy * immediate_gain

        px = max(0, min(self.screen_w - 1, int(round(self.curr_x))))
        py = max(0, min(self.screen_h - 1, int(round(self.curr_y))))
        self._set_os_cursor(px, py)

        # 3. Detección de pellizco (Pinch = Clic Izquierdo)
        now = time.time()
        clicked = False
        if dist_pinch < 0.055:  # Puntas unidas
            if not self.is_pinching and (now - self.last_pinch_click_time) > 0.40:
                self.is_pinching = True
                self.last_pinch_click_time = now
                clicked = True
                try:
                    threading.Thread(target=self._pyautogui.click, daemon=True).start()
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
