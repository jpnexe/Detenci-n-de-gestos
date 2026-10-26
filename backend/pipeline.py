"""
Pipeline Central de Visión por Computador — SignBridge Extended.
Conecta:
  Entrada de Video (Webcam Local / WebSocket Móvil / Simulador 3D)
  -> MediaPipe Hand Landmarker (21 Landmarks 3D)
  -> Normalización Matemática (63 floats)
  -> Switch Dinámico [OFFLINE: TF-MLP | ONLINE: Gemini API]
  -> Estabilización Temporal (Buffer Circular N=8, Confianza >= 0.85)
  -> Emulación de Periféricos (pyautogui) y Telemetría HUD.
"""

from __future__ import annotations
import base64
import math
import os
import time
from typing import Dict, Any, List, Optional, Tuple
import cv2
import numpy as np

from backend.normalizer import normalize_landmarks
from backend.classifier_local import (
    LocalGestureClassifier,
    GESTURE_CATALOG,
    get_canonical_hand_pose,
)
from backend.classifier_gemini import GeminiGestureClassifier
from backend.stabilizer import TemporalStabilizer
from backend.hardware_controller import HardwareController


# Conexiones anatómicas entre los 21 puntos clave de MediaPipe Hands
HAND_CONNECTIONS: List[Tuple[int, int]] = [
    (0, 1), (1, 2), (2, 3), (3, 4),        # Pulgar
    (0, 5), (5, 6), (6, 7), (7, 8),        # Índice
    (5, 9), (9, 10), (10, 11), (11, 12),   # Medio
    (9, 13), (13, 14), (14, 15), (15, 16), # Anular
    (13, 17), (0, 17), (17, 18), (18, 19), (19, 20), # Meñique y palma
]


class SignBridgePipeline:
    def __init__(self, model_dir: str = "models"):
        self.model_dir = model_dir
        self.hand_task_path = os.path.join(model_dir, "hand_landmarker.task")
        self.mode: str = "OFFLINE"  # "OFFLINE" | "ONLINE"
        self.video_source: str = "AUTO"  # "LOCAL" | "MOBILE" | "SIMULATOR" | "AUTO"
        self.simulated_gesture: str = "G1"

        self.local_classifier = LocalGestureClassifier(model_dir=model_dir)
        self.gemini_classifier = GeminiGestureClassifier(fallback_classifier=self.local_classifier)
        self.stabilizer = TemporalStabilizer(buffer_size=8, min_confidence=0.85, cooldown_sec=1.15)
        self.hardware = HardwareController(enabled=True)

        self._landmarker = None
        self._init_mediapipe()

        # Estado de FPS y frames móviles
        self._last_frame_ts = time.perf_counter()
        self._fps_ema = 30.0
        self.mobile_connected = False
        self.last_mobile_frame_ts = 0.0
        self.mobile_frame_bgr: Optional[np.ndarray] = None
        self.mobile_client_count = 0

        # Interpolación suave para el simulador 3D cuando no hay cámara física activa
        self._sim_current_pose = get_canonical_hand_pose("G1").copy()
        self.latest_rendered_b64: str = ""
        self.mobile_touch_xy: Optional[Tuple[float, float]] = None
        self.last_mobile_touch_ts: float = 0.0

    def _init_mediapipe(self) -> None:
        if not os.path.exists(self.hand_task_path):
            return
        try:
            import mediapipe as mp
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision as mp_vision

            base_options = mp_python.BaseOptions(model_asset_path=self.hand_task_path)
            options = mp_vision.HandLandmarkerOptions(
                base_options=base_options,
                running_mode=mp_vision.RunningMode.IMAGE,
                num_hands=1,
                min_hand_detection_confidence=0.55,
                min_hand_presence_confidence=0.55,
                min_tracking_confidence=0.55,
            )
            self._landmarker = mp_vision.HandLandmarker.create_from_options(options)
        except Exception:
            self._landmarker = None

    def set_mode(self, mode: str) -> str:
        mode_up = mode.upper().strip()
        if mode_up in ("OFFLINE", "ONLINE"):
            self.mode = mode_up
            self.stabilizer.reset()
        return self.mode

    def set_simulated_gesture(self, gesture_id: str) -> str:
        gid = gesture_id.upper().strip()
        if gid in GESTURE_CATALOG:
            self.simulated_gesture = gid
            # Al seleccionar una pose del simulador, activar vista SIMULATOR y apagar puntero
            self.video_source = "SIMULATOR"
            self.hardware.pointer_enabled = False
        return self.simulated_gesture

    def set_video_source(self, source: str) -> str:
        src = source.upper().strip()
        if src in ("AUTO", "LOCAL", "MOBILE", "SIMULATOR"):
            self.video_source = src
            self.stabilizer.reset()
            if src == "SIMULATOR":
                self.hardware.pointer_enabled = False
        return self.video_source

    def receive_mobile_frame(self, image_bytes: bytes, auto_switch: bool = False) -> bool:
        """Decodifica un fotograma JPEG enviado desde el teléfono móvil vía WebSocket."""
        try:
            arr = np.frombuffer(image_bytes, dtype=np.uint8)
            bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if bgr is not None:
                self.mobile_frame_bgr = bgr
                self.last_mobile_frame_ts = time.time()
                self.mobile_connected = True
                if auto_switch and self.video_source != "MOBILE":
                    self.video_source = "MOBILE"
                return True
        except Exception:
            pass
        return False

    def receive_mobile_touch(self, norm_x: float, norm_y: float, pinch: bool = False) -> Dict[str, Any]:
        """Permite dirigir el puntero del PC desde el panel táctil del modo Control Móvil."""
        self.last_mobile_touch_ts = time.time()
        self.mobile_connected = True
        self.mobile_touch_xy = (norm_x, norm_y)
        self.hardware.pointer_enabled = True
        thumb_xy = (norm_x, norm_y) if pinch else (norm_x + 0.2, norm_y + 0.2)
        return self.hardware.update_pointer(
            (norm_x, norm_y),
            thumb_xy,
            stabilize_aim=pinch,
            trigger_tap_click=pinch,
        )

    def generate_mobile_standby_frame(self, width: int = 800, height: int = 500) -> Tuple[np.ndarray, Optional[np.ndarray]]:
        """
        Renderiza el visor del Modo Cámara/Control Móvil cuando se selecciona desde el PC
        o mientras se enlaza el stream inalámbrico del teléfono.
        """
        canvas = np.full((height, width, 3), (15, 10, 8), dtype=np.uint8)
        step = 40
        for x in range(0, width, step):
            cv2.line(canvas, (x, 0), (x, height), (28, 22, 16), 1)
        for y in range(0, height, step):
            cv2.line(canvas, (0, y), (width, y), (28, 22, 16), 1)

        cx, cy = width // 2, height // 2
        cv2.circle(canvas, (cx, cy), 140, (60, 48, 20), 1, cv2.LINE_AA)
        cv2.circle(canvas, (cx, cy), 85, (80, 64, 24), 1, cv2.LINE_AA)

        status_txt = (
            "CELULAR CONECTADO - MODO CONTROL REMOTO ACTIVO"
            if self.mobile_client_count > 0
            else "MODO CAMARA MOVIL - ESPERANDO CONEXION DEL CELULAR (QR)"
        )
        color_txt = (157, 255, 0) if self.mobile_client_count > 0 else (255, 240, 0)
        cv2.putText(
            canvas,
            status_txt,
            (28, 42),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.58,
            color_txt,
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            canvas,
            "Abre /mobile en tu telefono o usa el boton 'Vista Movil APK' para probar",
            (28, height - 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            (184, 163, 148),
            1,
            cv2.LINE_AA,
        )

        # Si el usuario está deslizando en el touchpad móvil o enviando gestos desde el móvil
        if (time.time() - self.last_mobile_touch_ts) < 2.0 and self.mobile_touch_xy is not None:
            tx, ty = self.mobile_touch_xy
            pose = get_canonical_hand_pose(self.simulated_gesture).copy()
            dx = tx - pose[8, 0]
            dy = ty - pose[8, 1]
            pose[:, 0] = np.clip(pose[:, 0] + dx, 0.05, 0.95)
            pose[:, 1] = np.clip(pose[:, 1] + dy, 0.05, 0.95)
            return canvas, pose

        if self.mobile_client_count > 0:
            pose = get_canonical_hand_pose(self.simulated_gesture).copy()
            return canvas, pose

        return canvas, None

    def detect_landmarks_from_bgr(self, frame_bgr: np.ndarray) -> Optional[np.ndarray]:
        """Extrae los 21 puntos clave 3D (x, y, z) usando MediaPipe HandLandmarker."""
        if self._landmarker is None:
            return None
        try:
            import mediapipe as mp
            rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            result = self._landmarker.detect(mp_image)
            if result.hand_landmarks and len(result.hand_landmarks) > 0:
                hand = result.hand_landmarks[0]
                pts = np.array([[lm.x, lm.y, lm.z] for lm in hand], dtype=np.float32)
                return pts
        except Exception:
            pass
        return None

    def generate_simulator_frame_and_pose(self, width: int = 800, height: int = 500) -> Tuple[np.ndarray, np.ndarray]:
        """
        Genera un lienzo técnico oscuro (#08090D) con retícula espacial y una pose 3D
        anatómica animada para demostración o cuando no hay cámara física disponible.
        """
        canvas = np.full((height, width, 3), (13, 9, 8), dtype=np.uint8)  # BGR de #08090D

        # Dibujar cuadrícula sutil de calibración óptica
        step = 40
        for x in range(0, width, step):
            cv2.line(canvas, (x, 0), (x, height), (26, 22, 18), 1)
        for y in range(0, height, step):
            cv2.line(canvas, (0, y), (width, y), (26, 22, 18), 1)

        # Círculo central de referencia polar
        cx, cy = width // 2, height // 2 + 20
        cv2.circle(canvas, (cx, cy), 175, (42, 34, 24), 1, cv2.LINE_AA)
        cv2.circle(canvas, (cx, cy), 110, (34, 28, 20), 1, cv2.LINE_AA)
        cv2.line(canvas, (cx - 195, cy), (cx + 195, cy), (38, 30, 22), 1, cv2.LINE_AA)
        cv2.line(canvas, (cx, cy - 195), (cx, cy + 195), (38, 30, 22), 1, cv2.LINE_AA)

        meta = GESTURE_CATALOG.get(self.simulated_gesture, GESTURE_CATALOG["G0"])
        cv2.putText(
            canvas,
            f"SIMULADOR 3D :: [{self.simulated_gesture}] {meta['short_label']}",
            (24, height - 22),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 240, 0),
            1,
            cv2.LINE_AA,
        )

        # Interpolar suavemente hacia la pose objetivo seleccionada
        target_pose = get_canonical_hand_pose(self.simulated_gesture)
        t = time.perf_counter()
        # Micro-oscilación fisiológica realista
        breath_x = math.sin(t * 2.1) * 0.006
        breath_y = math.cos(t * 1.7) * 0.005
        offset = np.array([breath_x, breath_y, 0.0], dtype=np.float32)

        self._sim_current_pose = 0.72 * self._sim_current_pose + 0.28 * (target_pose + offset)
        return canvas, self._sim_current_pose.copy()

    def draw_hud_skeleton(
        self,
        frame_bgr: np.ndarray,
        landmarks: Optional[np.ndarray],
        stabilized: Dict[str, Any],
    ) -> np.ndarray:
        """
        Renderiza los 21 puntos clave y conexiones sobre el fotograma siguiendo
        estrictamente la colorimetría de DESIGN.md:
        - --liquid-cyan (#00F0FF) para detección activa / Modo Online
        - --liquid-amber (#FFB800) para Modo Offline
        - --liquid-emerald (#00FF9D) para pulso de acción confirmada
        - --liquid-rose (#FF3366) para rechazo activo (G0)
        """
        out = frame_bgr.copy()
        if landmarks is None:
            return out

        h, w = out.shape[:2]

        # Selección de color primario según estado semántico (BGR)
        if stabilized.get("pulse_emerald"):
            bone_color = (157, 255, 0)    # #00FF9D Liquid Emerald
            joint_color = (200, 255, 120)
        elif stabilized.get("rejected"):
            bone_color = (102, 51, 255)   # #FF3366 Liquid Rose
            joint_color = (140, 100, 255)
        elif self.mode == "ONLINE":
            bone_color = (255, 240, 0)    # #00F0FF Liquid Cyan
            joint_color = (255, 250, 160)
        else:
            bone_color = (0, 184, 255)    # #FFB800 Liquid Amber
            joint_color = (255, 240, 0)   # #00F0FF Puntas clave

        pts_px = [(int(lm[0] * w), int(lm[1] * h)) for lm in landmarks]

        # Halo translúcido alrededor de las conexiones
        overlay = out.copy()
        for i, j in HAND_CONNECTIONS:
            cv2.line(overlay, pts_px[i], pts_px[j], bone_color, 5, cv2.LINE_AA)
        cv2.addWeighted(overlay, 0.28, out, 0.72, 0, out)

        # Huesos nítidos principales
        for i, j in HAND_CONNECTIONS:
            cv2.line(out, pts_px[i], pts_px[j], bone_color, 2, cv2.LINE_AA)

        # Articulaciones y puntas (4, 8, 12, 16, 20 destacadas)
        fingertips = {4, 8, 12, 16, 20}
        for idx, (px, py) in enumerate(pts_px):
            if idx == 0:
                cv2.circle(out, (px, py), 8, (255, 255, 255), -1, cv2.LINE_AA)
                cv2.circle(out, (px, py), 11, bone_color, 2, cv2.LINE_AA)
            elif idx in fingertips:
                cv2.circle(out, (px, py), 7, joint_color, -1, cv2.LINE_AA)
                cv2.circle(out, (px, py), 10, bone_color, 1, cv2.LINE_AA)
            else:
                cv2.circle(out, (px, py), 4, (248, 250, 252), -1, cv2.LINE_AA)

        # Si el modo Puntero de Mouse está activo, dibujar retícula en el dedo índice (8)
        if self.hardware.pointer_enabled and len(pts_px) > 8:
            ix, iy = pts_px[8]
            cv2.circle(out, (ix, iy), 18, (0, 240, 255), 2, cv2.LINE_AA)
            cv2.circle(out, (ix, iy), 4, (0, 255, 157), -1, cv2.LINE_AA)
            cv2.line(out, (ix - 24, iy), (ix - 10, iy), (0, 240, 255), 2, cv2.LINE_AA)
            cv2.line(out, (ix + 10, iy), (ix + 24, iy), (0, 240, 255), 2, cv2.LINE_AA)
            cv2.line(out, (ix, iy - 24), (ix, iy - 10), (0, 240, 255), 2, cv2.LINE_AA)
            cv2.line(out, (ix, iy + 10), (ix, iy + 24), (0, 240, 255), 2, cv2.LINE_AA)

        return out

    def process_step(self, local_cam_bgr: Optional[np.ndarray] = None) -> Dict[str, Any]:
        """
        Ejecuta un ciclo completo del pipeline y retorna el paquete de telemetría + frame Base64.
        """
        now = time.perf_counter()
        dt = max(1e-4, now - self._last_frame_ts)
        self._last_frame_ts = now
        inst_fps = 1.0 / dt
        self._fps_ema = 0.85 * self._fps_ema + 0.15 * min(60.0, inst_fps)

        # Verificar expiración de stream móvil (> 3s sin frames)
        if self.mobile_connected and (time.time() - self.last_mobile_frame_ts) > 3.5:
            self.mobile_connected = False

        # Selección de fuente de video
        active_source = "SIMULATOR"
        frame_bgr: Optional[np.ndarray] = None
        landmarks: Optional[np.ndarray] = None

        if self.video_source == "SIMULATOR":
            frame_bgr, landmarks = self.generate_simulator_frame_and_pose()
            active_source = "SIMULATOR_3D"
            self.hardware.pointer_enabled = False
        elif self.video_source == "MOBILE":
            if self.mobile_connected and self.mobile_frame_bgr is not None and (time.time() - self.last_mobile_frame_ts) <= 3.5:
                frame_bgr = self.mobile_frame_bgr.copy()
                active_source = "MOBILE_CAM"
                landmarks = self.detect_landmarks_from_bgr(frame_bgr)
            else:
                frame_bgr, landmarks = self.generate_mobile_standby_frame()
                active_source = "MOBILE_CTRL"
        elif self.video_source == "AUTO" and self.mobile_connected and self.mobile_frame_bgr is not None:
            frame_bgr = self.mobile_frame_bgr.copy()
            active_source = "MOBILE_CAM"
            landmarks = self.detect_landmarks_from_bgr(frame_bgr)
        elif self.video_source in ("LOCAL", "AUTO") and local_cam_bgr is not None:
            frame_bgr = cv2.flip(local_cam_bgr, 1)
            active_source = "LOCAL_CAM"
            landmarks = self.detect_landmarks_from_bgr(frame_bgr)

        # Fallback al Simulador 3D si no hay cámara disponible
        if frame_bgr is None:
            frame_bgr, landmarks = self.generate_simulator_frame_and_pose()
            active_source = "SIMULATOR_3D"
            self.hardware.pointer_enabled = False

        # Si hay cámara activa pero no se detecta una mano en escena
        hand_detected = landmarks is not None
        pointer_info = {"active": False, "cursor": [int(self.hardware.curr_x), int(self.hardware.curr_y)], "pinching": False, "clicked": False}

        if not hand_detected:
            raw_pred = {
                "gesture_id": "G0",
                "name": GESTURE_CATALOG["G0"]["name"],
                "short_label": "SIN MANO EN ESCENA",
                "action": "NONE",
                "action_label": "Esperando detección de mano (21 Landmarks)",
                "confidence": 0.0,
                "probabilities": {k: 0.0 for k in GESTURE_CATALOG},
                "latency_ms": 4.2,
                "engine": "MediaPipe Hand Landmarker",
            }
            telemetry = {
                "wrist": [0.0, 0.0, 0.0],
                "index_tip": [0.0, 0.0, 0.0],
                "middle_tip": [0.0, 0.0, 0.0],
                "euclidean_scale": 0.0,
                "vector_norm": 0.0,
                "vector_sample": [0.0] * 6,
                "fingers": {"thumb": False, "index": False, "middle": False, "ring": False, "pinky": False},
            }
            stabilized = self.stabilizer.update(raw_pred)
        else:
            # 1. Normalización de vectores (Resta de muñeca [0] + Escalado euclidiano -> 63 floats)
            vector_63d, telemetry = normalize_landmarks(landmarks)

            # 2. Dirección del cursor del mouse si el modo puntero está activado y NO es simulador
            if self.hardware.pointer_enabled and active_source != "SIMULATOR_3D" and len(landmarks) > 8:
                index_pt = (float(landmarks[8][0]), float(landmarks[8][1]))
                thumb_pt = (float(landmarks[4][0]), float(landmarks[4][1]))
                pointer_info = self.hardware.update_pointer(
                    index_pt,
                    thumb_pt,
                    stabilize_aim=bool(telemetry.get("is_l_gesture", False)),
                )

            # 3. Inferencia según Switch [OFFLINE vs ONLINE]
            if self.mode == "ONLINE":
                ok_enc, buf_raw = cv2.imencode(".jpg", frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
                jpeg_bytes = buf_raw.tobytes() if ok_enc else None
                raw_pred = self.gemini_classifier.predict(jpeg_bytes, vector_63d, telemetry)
            else:
                raw_pred = self.local_classifier.predict(vector_63d, telemetry)

            # 4. Estabilización Temporal (Buffer N=8, Umbral >= 0.85)
            stabilized = self.stabilizer.update(raw_pred)

            # 5. Ejecución de periféricos si el anillo de retención completó el 100%
            if stabilized["triggered"]:
                self.hardware.execute_action(
                    gesture_id=stabilized["stabilized_id"],
                    action_code=stabilized["action"],
                    gesture_name=stabilized["name"],
                )

        # 5. Renderizado de esqueleto sobre el frame y codificación JPEG para el HUD
        rendered_bgr = self.draw_hud_skeleton(frame_bgr, landmarks, stabilized)
        ok, jpeg_buf = cv2.imencode(".jpg", rendered_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        frame_b64 = base64.b64encode(jpeg_buf.tobytes()).decode("ascii") if ok else ""
        self.latest_rendered_b64 = frame_b64

        landmarks_list = (
            [[round(float(p[0]), 4), round(float(p[1]), 4), round(float(p[2]), 4)] for p in landmarks]
            if landmarks is not None
            else []
        )

        return {
            "mode": self.mode,
            "source": active_source,
            "hand_detected": hand_detected,
            "fps": round(self._fps_ema, 1),
            "latency_ms": raw_pred.get("latency_ms", 12.5),
            "engine_label": raw_pred.get("engine", ""),
            "semantic_note": raw_pred.get("semantic_note", ""),
            "prediction": raw_pred,
            "stabilizer": stabilized,
            "telemetry": telemetry,
            "landmarks": landmarks_list,
            "hardware_enabled": self.hardware.enabled,
            "pointer_enabled": self.hardware.pointer_enabled,
            "pointer": pointer_info,
            "events": self.hardware.get_recent_events()[:8],
            "mobile_connected": self.mobile_connected,
            "simulated_gesture": self.simulated_gesture,
            "frame_b64": frame_b64,
        }

