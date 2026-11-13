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

from backend.normalizer import normalize_landmarks, normalize_multi_hand_landmarks
from backend.hand_tracking import HandTracker
from backend.classifier_local import (
    LocalGestureClassifier,
    GESTURE_CATALOG,
    get_canonical_hand_pose,
)
from backend.classifier_gemini import GeminiGestureClassifier
from backend.stabilizer import TemporalStabilizer
from backend.hardware_controller import HardwareController
from backend.conversation_engine import (
    ConversationEngine,
    CONVERSATIONAL_SIGNS_CATALOG,
    get_sign_3d_poses,
)
from backend.lsc_alphabet import LSC_ALPHABET_CATALOG, CHAR_TO_LSC_ID
from backend.motion_analyzer import KinematicMotionAnalyzer


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
        self.interaction_mode: str = "SIGN_LANGUAGE"  # "SIGN_LANGUAGE" (Traductor Conversacional) | "OS_CONTROL" (Mouse/Click)
        self.video_source: str = "AUTO"  # "LOCAL" | "MOBILE" | "SIMULATOR" | "AUTO"
        self.simulated_gesture: str = "G1"
        self.sign_history: List[Dict[str, Any]] = []
        self.conversation_engine = ConversationEngine()
        self.motion_analyzer = KinematicMotionAnalyzer()
        self.hand_tracker = HandTracker(max_hands=2, grace_sec=0.15, match_dist=0.35)
        self.multi_hand_landmarks: List[np.ndarray] = []
        self.multi_handedness: List[str] = []

        self.local_classifier = LocalGestureClassifier(model_dir=model_dir)
        self.gemini_classifier = GeminiGestureClassifier(fallback_classifier=self.local_classifier)
        self.stabilizer = TemporalStabilizer(buffer_size=8, min_confidence=0.78, cooldown_sec=1.15)
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
        self.recent_primary_vectors: List[List[float]] = []

        # Interpolación suave para el simulador 3D cuando no hay cámara física activa
        self._sim_current_pose = get_canonical_hand_pose("G1").copy()
        self._sim_secondary_pose: Optional[np.ndarray] = None
        self.latest_rendered_b64: str = ""
        self.latest_tts_seq: int = 0
        self.latest_tts_text: Optional[str] = None
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
                num_hands=2,
                min_hand_detection_confidence=0.48,
                min_hand_presence_confidence=0.48,
                min_tracking_confidence=0.48,
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

    def set_interaction_mode(self, interaction_mode: str) -> str:
        imode = interaction_mode.upper().strip()
        if imode in ("OS_CONTROL", "SIGN_LANGUAGE"):
            self.interaction_mode = imode
            self.stabilizer.reset()
            if imode == "SIGN_LANGUAGE":
                self.hardware.pointer_enabled = False
        return self.interaction_mode

    def reset_detection(self) -> Dict[str, Any]:
        """Reinicia el buffer de estabilización temporal y el historial de detección de señas."""
        self.stabilizer.reset()
        self.motion_analyzer.reset()
        self.sign_history.clear()
        return {
            "reset": True,
            "interaction_mode": self.interaction_mode,
            "buffer_size": self.stabilizer.buffer_size,
        }

    def set_simulated_gesture(self, gesture_id: str) -> str:
        gid = gesture_id.upper().strip()
        if len(gid) == 1 and gid in CHAR_TO_LSC_ID:
            gid = CHAR_TO_LSC_ID[gid]
        if gid in GESTURE_CATALOG or gid in LSC_ALPHABET_CATALOG or gid in CONVERSATIONAL_SIGNS_CATALOG:
            self.simulated_gesture = gid
            # Al seleccionar una pose del simulador, activar vista SIMULATOR y apagar puntero
            self.video_source = "SIMULATOR"
            self.hardware.pointer_enabled = False
            if gid in ("G1", "G2", "G3", "G4", "G5"):
                self.interaction_mode = "OS_CONTROL"
            elif gid in LSC_ALPHABET_CATALOG or gid in CONVERSATIONAL_SIGNS_CATALOG:
                self.interaction_mode = "SIGN_LANGUAGE"
        return self.simulated_gesture

    def set_sign_submode(self, submode: str) -> str:
        self.stabilizer.reset()
        return self.conversation_engine.set_submode(submode)

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

    def detect_all_hands_from_bgr(self, frame_bgr: np.ndarray) -> Tuple[List[np.ndarray], List[str]]:
        """
        Extrae los 21 puntos clave 3D (x, y, z) de hasta 2 manos simultáneas junto con su lateralidad
        (Right / Left) y aplica el HandTracker con filtro 1€ vectorizado y persistencia temporal anti-jitter.
        """
        if self._landmarker is None:
            return [], []
        try:
            import mediapipe as mp
            rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            result = self._landmarker.detect(mp_image)
            raw_dets: List[Dict[str, Any]] = []

            h, w = frame_bgr.shape[:2]
            aspect = float(w) / max(1.0, float(h))

            if result.hand_landmarks and len(result.hand_landmarks) > 0:
                for idx, hand in enumerate(result.hand_landmarks):
                    pts = np.array([[lm.x, lm.y, lm.z] for lm in hand], dtype=np.float32)
                    label = "Right"
                    if result.handedness and len(result.handedness) > idx and len(result.handedness[idx]) > 0:
                        label = result.handedness[idx][0].category_name
                    world_pts = None
                    if getattr(result, "hand_world_landmarks", None) and len(result.hand_world_landmarks) > idx:
                        world_pts = np.array([[lm.x, lm.y, lm.z] for lm in result.hand_world_landmarks[idx]], dtype=np.float32)
                    raw_dets.append({"img": pts, "world": world_pts, "label": label})

                tracked = self.hand_tracker.update(raw_dets, aspect=aspect, now=time.perf_counter())
                hands_list = [t["landmarks"] for t in tracked]
                handedness_list = [t["label"] for t in tracked]
                return hands_list, handedness_list
            else:
                # Mantener periodo de gracia si la mano se perdió por 1 fotograma transitorio
                tracked = self.hand_tracker.update([], aspect=aspect, now=time.perf_counter())
                if tracked:
                    return [t["landmarks"] for t in tracked], [t["label"] for t in tracked]
                return [], []
        except Exception:
            return [], []

    def detect_landmarks_from_bgr(self, frame_bgr: np.ndarray) -> Optional[np.ndarray]:
        """Extrae los 21 puntos clave 3D de la mano primaria (con preservación de compatibilidad)."""
        hands, labels = self.detect_all_hands_from_bgr(frame_bgr)
        self.multi_hand_landmarks = hands
        self.multi_handedness = labels
        return hands[0] if hands else None

    def generate_simulator_bimanual_frame(
        self,
        width: int = 800,
        height: int = 500,
        anim_frame: Optional[Dict[str, Any]] = None,
    ) -> Tuple[np.ndarray, np.ndarray, Optional[np.ndarray]]:
        """
        Genera el lienzo del Modelo 3D de Manos (unimanual o bimanual) para:
        1. Reproducir frases completas traducidas a Lengua de Señas Colombiana + Deletreo LSC.
        2. Simular cualquiera de las 27 letras del Abecedario LSC (A-Z + Ñ) o las 46 señas conversacionales.
        """
        canvas = np.full((height, width, 3), (13, 9, 8), dtype=np.uint8)

        step = 40
        for x in range(0, width, step):
            cv2.line(canvas, (x, 0), (x, height), (26, 22, 18), 1)
        for y in range(0, height, step):
            cv2.line(canvas, (0, y), (width, y), (26, 22, 18), 1)

        cx, cy = width // 2, height // 2 + 20
        cv2.circle(canvas, (cx, cy), 175, (42, 34, 24), 1, cv2.LINE_AA)
        cv2.circle(canvas, (cx, cy), 110, (34, 28, 20), 1, cv2.LINE_AA)
        cv2.line(canvas, (cx - 195, cy), (cx + 195, cy), (38, 30, 22), 1, cv2.LINE_AA)
        cv2.line(canvas, (cx, cy - 195), (cx, cy + 195), (38, 30, 22), 1, cv2.LINE_AA)

        t = time.perf_counter()
        breath_x = math.sin(t * 2.1) * 0.004
        breath_y = math.cos(t * 1.7) * 0.004
        offset = np.array([breath_x, breath_y, 0.0], dtype=np.float32)

        target_secondary: Optional[np.ndarray] = None

        if anim_frame is not None:
            target_primary = anim_frame["primary_pose"]
            target_secondary = anim_frame.get("secondary_pose")
            phrase_txt = anim_frame.get("phrase", "")
            step_idx = anim_frame.get("step_index", 1)
            total_steps = anim_frame.get("total_steps", 1)
            label_txt = anim_frame.get("label", "")
            desc_txt = anim_frame.get("description", "")

            # Banner superior de traducción de frase en Modelo 3D de Manos
            cv2.rectangle(canvas, (18, 48), (width - 18, 108), (24, 18, 14), -1)
            cv2.rectangle(canvas, (18, 48), (width - 18, 108), (157, 255, 0), 1)
            cv2.putText(
                canvas,
                f"INTÉRPRETE 3D DE MANOS LSC [{step_idx}/{total_steps}] :: \"{phrase_txt[:46]}\"",
                (30, 72),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.52,
                (157, 255, 0),
                2,
                cv2.LINE_AA,
            )
            cv2.putText(
                canvas,
                f"ACTIVO: [{anim_frame['sign_id']}] {label_txt} - {desc_txt[:62]}",
                (30, 96),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.46,
                (255, 240, 0),
                1,
                cv2.LINE_AA,
            )
        else:
            gid = self.simulated_gesture
            t_phase = (t % 1.35) / 1.35
            if gid in LSC_ALPHABET_CATALOG:
                meta_l = LSC_ALPHABET_CATALOG[gid]
                # Para letras estáticas mantener pose pura si aún no ha disparado o usar fase suave
                use_phase = t_phase if meta_l["is_dynamic"] else 0.0
                target_primary, target_secondary = get_sign_3d_poses(gid, t_phase=use_phase)
                title_line = f"ABECEDARIO LSC 3D :: [{meta_l['letter']}] {meta_l['full_name']} - {meta_l['motion_hint']}"
            elif gid in CONVERSATIONAL_SIGNS_CATALOG:
                meta_s = CONVERSATIONAL_SIGNS_CATALOG[gid]
                target_primary, target_secondary = get_sign_3d_poses(gid, t_phase=t_phase)
                title_line = f"SEÑA LSC 3D :: [{gid}] {meta_s['label']}"
            else:
                meta = GESTURE_CATALOG.get(gid, GESTURE_CATALOG["G0"])
                target_primary = get_canonical_hand_pose(gid)
                title_line = f"SIMULADOR 3D :: [{gid}] {meta['short_label']}"

            cv2.putText(
                canvas,
                title_line[:78],
                (24, height - 22),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.52,
                (255, 240, 0),
                1,
                cv2.LINE_AA,
            )

        self._sim_current_pose = 0.65 * self._sim_current_pose + 0.35 * (target_primary + offset)
        if target_secondary is not None:
            if self._sim_secondary_pose is None:
                self._sim_secondary_pose = target_secondary.copy()
            else:
                self._sim_secondary_pose = 0.65 * self._sim_secondary_pose + 0.35 * (target_secondary - offset)
            sec_out = self._sim_secondary_pose.copy()
        else:
            self._sim_secondary_pose = None
            sec_out = None

        return canvas, self._sim_current_pose.copy(), sec_out

    def generate_simulator_frame_and_pose(self, width: int = 800, height: int = 500) -> Tuple[np.ndarray, np.ndarray]:
        """Preserva compatibilidad retornando (canvas, primary_pose)."""
        canvas, p_pose, _ = self.generate_simulator_bimanual_frame(width=width, height=height)
        return canvas, p_pose

    def draw_hud_skeleton(
        self,
        frame_bgr: np.ndarray,
        landmarks: Optional[np.ndarray],
        stabilized: Dict[str, Any],
        secondary_landmarks: Optional[np.ndarray] = None,
        inter_hand: Optional[Dict[str, Any]] = None,
    ) -> np.ndarray:
        """
        Renderiza los esqueletos anatómicos de 1 o 2 manos (bimanual) y sus relaciones
        espaciales (halo de contacto, conexión inter-manual y lateralidad) siguiendo DESIGN.md.
        """
        out = frame_bgr.copy()
        if landmarks is None and secondary_landmarks is None:
            return out

        h, w = out.shape[:2]

        def draw_single_skeleton(pts_arr: np.ndarray, b_color: Tuple[int, int, int], j_color: Tuple[int, int, int], is_primary: bool):
            pts_px = [(int(lm[0] * w), int(lm[1] * h)) for lm in pts_arr]

            # Halo translúcido
            overlay = out.copy()
            for i, j in HAND_CONNECTIONS:
                cv2.line(overlay, pts_px[i], pts_px[j], b_color, 5, cv2.LINE_AA)
            cv2.addWeighted(overlay, 0.28, out, 0.72, 0, out)

            # Huesos principales
            for i, j in HAND_CONNECTIONS:
                cv2.line(out, pts_px[i], pts_px[j], b_color, 2, cv2.LINE_AA)

            # Puntos y nudillos
            fingertips = {4, 8, 12, 16, 20}
            for idx, (px, py) in enumerate(pts_px):
                if idx == 0:
                    cv2.circle(out, (px, py), 8, (255, 255, 255), -1, cv2.LINE_AA)
                    cv2.circle(out, (px, py), 11, b_color, 2, cv2.LINE_AA)
                elif idx in fingertips:
                    cv2.circle(out, (px, py), 7, j_color, -1, cv2.LINE_AA)
                    cv2.circle(out, (px, py), 10, b_color, 1, cv2.LINE_AA)
                else:
                    cv2.circle(out, (px, py), 4, (248, 250, 252), -1, cv2.LINE_AA)

            # Retícula de puntero si aplica a la mano primaria
            if is_primary and self.hardware.pointer_enabled and len(pts_px) > 8:
                ix, iy = pts_px[8]
                cv2.circle(out, (ix, iy), 18, (0, 240, 255), 2, cv2.LINE_AA)
                cv2.circle(out, (ix, iy), 4, (0, 255, 157), -1, cv2.LINE_AA)
                cv2.line(out, (ix - 24, iy), (ix - 10, iy), (0, 240, 255), 2, cv2.LINE_AA)
                cv2.line(out, (ix + 10, iy), (ix + 24, iy), (0, 240, 255), 2, cv2.LINE_AA)
                cv2.line(out, (ix, iy - 24), (ix, iy - 10), (0, 240, 255), 2, cv2.LINE_AA)
                cv2.line(out, (ix, iy + 10), (ix, iy + 24), (0, 240, 255), 2, cv2.LINE_AA)

            return pts_px

        # 1. Mano primaria (Derecha / Dominante)
        pts_px_0 = None
        if landmarks is not None:
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
                joint_color = (255, 240, 0)   # #00F0FF Puntas
            pts_px_0 = draw_single_skeleton(landmarks, bone_color, joint_color, is_primary=True)

        # 2. Mano secundaria (Izquierda / No-dominante en gestos bimanuales)
        pts_px_1 = None
        if secondary_landmarks is not None:
            sec_bone_color = (235, 85, 168)   # #A855F7 Liquid Violet
            sec_joint_color = (255, 175, 225)
            pts_px_1 = draw_single_skeleton(secondary_landmarks, sec_bone_color, sec_joint_color, is_primary=False)

        # 3. Dibujar interacción inter-manual si hay 2 manos
        if pts_px_0 is not None and pts_px_1 is not None and inter_hand:
            p0_wrist = pts_px_0[0]
            p1_wrist = pts_px_1[0]
            p0_palm = pts_px_0[9]
            p1_palm = pts_px_1[9]

            # Línea de enlace inter-manual
            if inter_hand.get("hands_touching") or inter_hand.get("palms_together") or inter_hand.get("fist_on_palm_help"):
                cv2.line(out, p0_palm, p1_palm, (157, 255, 0), 2, cv2.LINE_AA)
                cv2.circle(out, ((p0_palm[0] + p1_palm[0]) // 2, (p0_palm[1] + p1_palm[1]) // 2), 7, (157, 255, 0), -1, cv2.LINE_AA)

            # Cartel visual de reconocimiento bimanual en cabecera
            if inter_hand.get("fist_on_palm_help"):
                cv2.putText(out, "BIMANUAL: AUXILIO / ASISTENCIA SOS", (w // 2 - 165, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (0, 60, 255), 2, cv2.LINE_AA)
            elif inter_hand.get("palms_together"):
                cv2.putText(out, "BIMANUAL: PALMAS UNIDAS (POR FAVOR)", (w // 2 - 165, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (157, 255, 0), 2, cv2.LINE_AA)
            elif inter_hand.get("both_open_forward"):
                cv2.putText(out, "BIMANUAL: ESPERA / PAUSA", (w // 2 - 120, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (0, 220, 255), 2, cv2.LINE_AA)

        return out

    def process_step(self, local_cam_bgr: Optional[np.ndarray] = None) -> Dict[str, Any]:
        """
        Ejecuta un ciclo completo del pipeline con soporte bimanual, traducción
        conversacional continua y emulación de periféricos.
        """
        now = time.perf_counter()
        dt = max(1e-4, now - self._last_frame_ts)
        self._last_frame_ts = now
        inst_fps = 1.0 / dt
        self._fps_ema = 0.85 * self._fps_ema + 0.15 * min(60.0, inst_fps)

        # Verificar expiración de stream móvil (> 3s sin frames)
        if self.mobile_connected and (time.time() - self.last_mobile_frame_ts) > 3.5:
            self.mobile_connected = False

        # Selección de fuente de video y detección de manos
        active_source = "SIMULATOR"
        frame_bgr: Optional[np.ndarray] = None
        landmarks: Optional[np.ndarray] = None
        multi_hand_data: Dict[str, Any] = normalize_multi_hand_landmarks([])

        # Verificar si el Reproductor Visual de Manos 3D está animando una frase traducida
        anim_frame = self.conversation_engine.get_active_hand_animation_frame()

        if anim_frame is not None:
            frame_bgr, landmarks, sec_sim = self.generate_simulator_bimanual_frame(anim_frame=anim_frame)
            active_source = "MODELO_3D_LSC"
            self.hardware.pointer_enabled = False
            if sec_sim is not None:
                multi_hand_data = normalize_multi_hand_landmarks([landmarks, sec_sim], ["Right", "Left"])
            else:
                multi_hand_data = normalize_multi_hand_landmarks([landmarks], ["Right"])
        elif self.video_source == "SIMULATOR":
            frame_bgr, landmarks, sec_sim = self.generate_simulator_bimanual_frame()
            active_source = "SIMULATOR_3D"
            self.hardware.pointer_enabled = False
            if sec_sim is not None:
                multi_hand_data = normalize_multi_hand_landmarks([landmarks, sec_sim], ["Right", "Left"])
            else:
                multi_hand_data = normalize_multi_hand_landmarks([landmarks], ["Right"])
        elif self.video_source == "MOBILE":
            if self.mobile_connected and self.mobile_frame_bgr is not None and (time.time() - self.last_mobile_frame_ts) <= 3.5:
                frame_bgr = self.mobile_frame_bgr.copy()
                active_source = "MOBILE_CAM"
                hands_list, handedness_list = self.detect_all_hands_from_bgr(frame_bgr)
                if hands_list:
                    landmarks = hands_list[0]
                    multi_hand_data = normalize_multi_hand_landmarks(hands_list, handedness_list)
            else:
                frame_bgr, landmarks = self.generate_mobile_standby_frame()
                active_source = "MOBILE_CTRL"
                if landmarks is not None:
                    multi_hand_data = normalize_multi_hand_landmarks([landmarks], ["Right"])
        elif self.video_source == "AUTO" and self.mobile_connected and self.mobile_frame_bgr is not None:
            frame_bgr = self.mobile_frame_bgr.copy()
            active_source = "MOBILE_CAM"
            hands_list, handedness_list = self.detect_all_hands_from_bgr(frame_bgr)
            if hands_list:
                landmarks = hands_list[0]
                multi_hand_data = normalize_multi_hand_landmarks(hands_list, handedness_list)
        elif self.video_source in ("LOCAL", "AUTO") and local_cam_bgr is not None:
            frame_bgr = cv2.flip(local_cam_bgr, 1)
            active_source = "LOCAL_CAM"
            hands_list, handedness_list = self.detect_all_hands_from_bgr(frame_bgr)
            if hands_list:
                landmarks = hands_list[0]
                multi_hand_data = normalize_multi_hand_landmarks(hands_list, handedness_list)

        # Fallback al Simulador 3D si no hay cámara disponible
        if frame_bgr is None:
            frame_bgr, landmarks, sec_sim = self.generate_simulator_bimanual_frame()
            active_source = "SIMULATOR_3D"
            self.hardware.pointer_enabled = False
            if sec_sim is not None:
                multi_hand_data = normalize_multi_hand_landmarks([landmarks, sec_sim], ["Right", "Left"])
            else:
                multi_hand_data = normalize_multi_hand_landmarks([landmarks], ["Right"])

        # Si hay cámara activa pero no se detecta una mano en escena
        hand_detected = landmarks is not None
        if hand_detected and active_source in ("LOCAL_CAM", "MOBILE_CAM"):
            p_vec = (multi_hand_data.get("primary") or {}).get("vector_63d")
            if p_vec is not None and len(p_vec) == 63:
                self.recent_primary_vectors.append(list(p_vec))
                if len(self.recent_primary_vectors) > 15:
                    self.recent_primary_vectors = self.recent_primary_vectors[-15:]
        pointer_info = {"active": False, "cursor": [int(self.hardware.curr_x), int(self.hardware.curr_y)], "pinching": False, "clicked": False}

        # Actualizar análisis cinemático de movimiento
        secondary_pts = multi_hand_data["secondary"]["landmarks"] if multi_hand_data.get("is_bimanual") else None
        motion_data = self.motion_analyzer.update(landmarks, secondary_pts, timestamp=now)

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
                "motion": motion_data,
            }
            stabilized = self.stabilizer.update(raw_pred)
        else:
            # 1. Normalización de vectores primarios (63 floats)
            vector_63d, telemetry = normalize_landmarks(landmarks)
            telemetry["motion"] = motion_data

            # Signing Space Gate: detectar si la mano está en reposo sobre el teclado/escritorio (borde inferior)
            is_resting_hand = (
                active_source in ("LOCAL_CAM", "MOBILE_CAM")
                and float(landmarks[0][1]) > 0.94
                and float(landmarks[9][1]) > 0.88
            )

            if is_resting_hand:
                raw_pred = {
                    "gesture_id": "G0",
                    "name": GESTURE_CATALOG["G0"]["name"],
                    "short_label": "MANO EN REPOSO",
                    "action": "NONE",
                    "action_label": "Mano en reposo — Eleva la mano frente al pecho para interactuar",
                    "confidence": 0.0,
                    "probabilities": {k: 0.0 for k in GESTURE_CATALOG},
                    "latency_ms": 1.0,
                    "engine": "Signing Space Gate",
                    "semantic_note": "Mano en reposo",
                }
            else:
                # 2. Dirección del cursor del mouse si el modo puntero está activado y NO es simulador
                if self.hardware.pointer_enabled and active_source != "SIMULATOR_3D" and len(landmarks) > 8:
                    index_pt = (float(landmarks[8][0]), float(landmarks[8][1]))
                    thumb_pt = (float(landmarks[4][0]), float(landmarks[4][1]))
                    pointer_info = self.hardware.update_pointer(
                        index_pt,
                        thumb_pt,
                        stabilize_aim=bool(telemetry.get("is_l_gesture", False)),
                    )

                # 3. Inferencia según Switch [OFFLINE vs ONLINE] y Modo de Interacción
                if self.mode == "ONLINE":
                    ok_enc, buf_raw = cv2.imencode(".jpg", frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
                    jpeg_bytes = buf_raw.tobytes() if ok_enc else None
                    raw_pred = self.gemini_classifier.predict(
                        jpeg_bytes, vector_63d, telemetry, interaction_mode=self.interaction_mode
                    )
                elif self.interaction_mode == "OS_CONTROL":
                    # MODO CONTROL OS: Inferencia exclusiva de comandos periféricos (G0..G5)
                    raw_pred = self.local_classifier.predict(vector_63d, telemetry)
                else:
                    # MODO TRADUCTOR DE SEÑAS: Inferencia de Lengua de Señas LSC y Abecedario
                    # NUNCA se contamina con los comandos G1..G5 de control de mouse
                    bimanual_match = self.conversation_engine.classify_bimanual_gesture(multi_hand_data, motion=motion_data)
                    if bimanual_match:
                        meta = self.conversation_engine.get_sign_meta(bimanual_match["sign_id"])
                        raw_pred = {
                            "gesture_id": bimanual_match["sign_id"],
                            "name": meta["label"],
                            "short_label": meta["label"],
                            "sign_label": meta["label"],
                            "sign_message": meta["default_phrase"],
                            "action": "NONE",
                            "action_label": "Traducción Bimanual",
                            "confidence": bimanual_match["confidence"],
                            "is_dynamic": bimanual_match.get("is_dynamic", False),
                        }
                    else:
                        unimanual_match = self.conversation_engine.classify_unimanual_gesture(multi_hand_data, motion=motion_data)
                        if unimanual_match:
                            meta = self.conversation_engine.get_sign_meta(unimanual_match["sign_id"])
                            raw_pred = {
                                "gesture_id": unimanual_match["sign_id"],
                                "name": meta["label"],
                                "short_label": meta["label"],
                                "sign_label": meta["label"],
                                "sign_message": meta["default_phrase"],
                                "action": "NONE",
                                "action_label": "Traducción Unimanual",
                                "confidence": unimanual_match["confidence"],
                                "is_dynamic": unimanual_match.get("is_dynamic", False),
                            }
                        else:
                            # En Modo Señas, si no coincide ninguna seña con alta certeza, es Rechazo Activo G0
                            raw_pred = {
                                "gesture_id": "G0",
                                "name": GESTURE_CATALOG["G0"]["name"],
                                "short_label": "DESCONOCIDO",
                                "sign_label": "DESCONOCIDO",
                                "sign_message": "Esperando seña intencional...",
                                "action": "NONE",
                                "action_label": "Esperando seña intencional",
                                "confidence": 0.0,
                                "probabilities": {k: 0.0 for k in GESTURE_CATALOG},
                                "latency_ms": 1.2,
                                "engine": "LSC Recognition Engine",
                                "semantic_note": "Postura no reconocida como seña",
                            }

            # 4. Estabilización Temporal (Buffer N=8, Umbral >= 0.85 con soporte dinámico y Cloud)
            stabilized = self.stabilizer.update(raw_pred)
            if self.mode == "ONLINE" and raw_pred.get("cloud_verified"):
                stabilized["cloud_verified"] = True
                stabilized["engine"] = raw_pred.get("engine", "Gemini Online")
                if "sign_label" in raw_pred:
                    stabilized["sign_label"] = raw_pred["sign_label"]
                if "sign_message" in raw_pred:
                    stabilized["sign_message"] = raw_pred["sign_message"]

            # 5. Ejecución según Modo de Interacción (Control OS vs Lenguaje de Señas Conversacional)
            if stabilized["triggered"]:
                if self.interaction_mode == "SIGN_LANGUAGE":
                    from datetime import datetime
                    ts = datetime.now().strftime("%H:%M:%S")
                    sign_entry = {
                        "timestamp": ts,
                        "gesture_id": stabilized["stabilized_id"],
                        "sign_label": stabilized.get("sign_label", stabilized["short_label"]),
                        "sign_message": stabilized.get("sign_message", ""),
                        "confidence": stabilized["confidence"],
                    }
                    self.sign_history.insert(0, sign_entry)
                    self.sign_history = self.sign_history[:15]
                    self.hardware.event_log.appendleft({
                        "timestamp": ts,
                        "gesture_id": stabilized["stabilized_id"],
                        "gesture_name": f"[SEÑA] {sign_entry['sign_label']}",
                        "action": "SIGN_MESSAGE",
                        "executed_os": False,
                        "detail": sign_entry["sign_message"],
                    })
                else:
                    self.hardware.execute_action(
                        gesture_id=stabilized["stabilized_id"],
                        action_code=stabilized["action"],
                        gesture_name=stabilized["name"],
                    )

        # 6. Mapeo y procesamiento en el Motor Conversacional (tokens continuos y TTS)
        tts_to_speak = None
        conv_sign = None
        if self.interaction_mode == "SIGN_LANGUAGE":
            if anim_frame is not None:
                # Si el Modelo 3D de Manos está reproduciendo una frase, mostrar la seña/letra actual sin agregarla al buffer saliente
                stabilized["stabilized_id"] = anim_frame["sign_id"]
                stabilized["sign_label"] = anim_frame["label"]
                stabilized["sign_message"] = anim_frame["subtitle"]
                stabilized["name"] = anim_frame["description"]
                stabilized["ring_progress"] = anim_frame["progress"]
            else:
                conv_sign = self.conversation_engine.process_frame_sign(
                    raw_gesture_id=stabilized.get("stabilized_id", "G0"),
                    confidence=float(stabilized.get("confidence", 0.0)),
                    multi_hand=multi_hand_data,
                    is_triggered=bool(stabilized.get("triggered", False)),
                    motion=motion_data,
                    is_online=(self.mode == "ONLINE"),
                    simulator_hint=(self.simulated_gesture if active_source == "SIMULATOR_3D" else None),
                )
                if conv_sign:
                    stabilized["stabilized_id"] = conv_sign["sign_id"]
                    stabilized["name"] = conv_sign["label"]
                    stabilized["sign_label"] = conv_sign["label"]
                    stabilized["sign_message"] = conv_sign["default_phrase"]
                    stabilized["sign_emoji"] = conv_sign["emoji"]
                    stabilized["sign_category"] = conv_sign["category"]
            tts_to_speak = self.conversation_engine.pop_tts_queue()
            if tts_to_speak:
                self.latest_tts_seq += 1
                self.latest_tts_text = tts_to_speak

        # 7. Renderizado HUD bimanual sobre el frame y codificación JPEG
        secondary_landmarks = multi_hand_data["secondary"]["landmarks"] if multi_hand_data.get("is_bimanual") else None
        inter_hand = multi_hand_data.get("inter_hand")
        rendered_bgr = self.draw_hud_skeleton(frame_bgr, landmarks, stabilized, secondary_landmarks, inter_hand)

        ok, jpeg_buf = cv2.imencode(".jpg", rendered_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        frame_b64 = base64.b64encode(jpeg_buf.tobytes()).decode("ascii") if ok else ""
        self.latest_rendered_b64 = frame_b64

        landmarks_list = (
            [[round(float(p[0]), 4), round(float(p[1]), 4), round(float(p[2]), 4)] for p in landmarks]
            if landmarks is not None
            else []
        )
        secondary_landmarks_list = (
            [[round(float(p[0]), 4), round(float(p[1]), 4), round(float(p[2]), 4)] for p in secondary_landmarks]
            if secondary_landmarks is not None
            else []
        )

        return {
            "mode": self.mode,
            "interaction_mode": self.interaction_mode,
            "sign_submode": self.conversation_engine.sign_submode,
            "source": active_source,
            "hand_detected": hand_detected,
            "hands_count": multi_hand_data.get("hands_count", 0),
            "bimanual": multi_hand_data.get("is_bimanual", False),
            "fps": round(self._fps_ema, 1),
            "latency_ms": raw_pred.get("latency_ms", 12.5),
            "engine_label": raw_pred.get("engine", ""),
            "semantic_note": raw_pred.get("semantic_note", ""),
            "prediction": raw_pred,
            "stabilizer": stabilized,
            "telemetry": telemetry,
            "motion": motion_data,
            "landmarks": landmarks_list,
            "secondary_landmarks": secondary_landmarks_list,
            "inter_hand": inter_hand,
            "hardware_enabled": self.hardware.enabled,
            "pointer_enabled": self.hardware.pointer_enabled,
            "pointer": pointer_info,
            "events": self.hardware.get_recent_events()[:8],
            "sign_history": self.sign_history[:8],
            "conversation": self.conversation_engine.get_state(),
            "tts_to_speak": tts_to_speak,
            "mobile_connected": self.mobile_connected,
            "simulated_gesture": self.simulated_gesture,
            "frame_b64": frame_b64,
        }

    # Métodos de control conversacional y Modelo 3D de Manos
    def commit_conversation_sentence(self, custom_phrase: Optional[str] = None) -> Dict[str, Any]:
        return self.conversation_engine.commit_sentence(custom_phrase)

    def add_hearing_spoken_text(self, text: str) -> Dict[str, Any]:
        return self.conversation_engine.add_hearing_message(text)

    def translate_phrase_to_hands(self, text: str) -> Dict[str, Any]:
        self.interaction_mode = "SIGN_LANGUAGE"
        res = self.conversation_engine.add_hearing_message(text, animate_hands=True)
        return res.get("animation") or res

    def add_manual_sign_token(self, sign_id: str) -> Dict[str, Any]:
        return self.conversation_engine.add_manual_sign_or_letter(sign_id)

    def backspace_conversation_token(self) -> Dict[str, Any]:
        return self.conversation_engine.backspace()

    def clear_conversation_tokens(self) -> Dict[str, Any]:
        self.conversation_engine.clear_tokens()
        return {"cleared": True}

