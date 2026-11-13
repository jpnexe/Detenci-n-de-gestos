"""
Servidor Principal FastAPI + WebSockets — SignBridge Extended.
Provee:
- HUD Principal Liquid Glassmorphic (/)
- Cliente Móvil / PWA de Cámara Inalámbrica (/mobile)
- WebSocket de Telemetría y Video en Tiempo Real (/ws/hud)
- WebSocket de Recepción de Cámara Remota Móvil (/ws/mobile)
- Generador de Código QR de Emparejamiento (/api/qr)
- API REST de Control Dinámico (/api/status, /api/mode, /api/config, /api/catalog)
"""

from __future__ import annotations
import asyncio
import base64
import io
import json
import os
import socket
import threading
import time
import webbrowser
from typing import Optional

import cv2
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import qrcode

from backend.pipeline import SignBridgePipeline
from backend.classifier_local import GESTURE_CATALOG
from backend.conversation_engine import CONVERSATIONAL_SIGNS_CATALOG
from backend.lsc_alphabet import LSC_ALPHABET_CATALOG
from backend.usb_bridge import (
    get_adb_devices,
    setup_droidcam_usb_bridge,
    setup_signbridge_usb_bridge,
)
from backend.speech_transcriber import pc_mic_recorder, transcribe_audio_bytes
from backend.custom_signs import custom_sign_store, import_sign_from_image


app = FastAPI(
    title="SignBridge Extended — Liquid Glassmorphic Gesture OS",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

pipeline = SignBridgePipeline(model_dir="models")


def get_local_ip() -> str:
    """Obtiene la IP LAN real del equipo para el emparejamiento QR móvil."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.2)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"


class LocalCameraWorker:
    """
    Hilo lector no-bloqueante multi-fuente para cámaras locales, cámaras virtuales
    (DroidCam Virtual Cam, OBS, Iriun) y streams HTTP/MJPEG (DroidCam USB/Wi-Fi).
    """

    def __init__(self):
        self.cap: Optional[cv2.VideoCapture] = None
        self.latest_frame = None
        self.available = False
        self.running = False
        self.target: object = 0  # int (0, 1, 2...) o str URL ("http://127.0.0.1:4747/video")
        self.backend_label: str = "NONE"
        self.last_error: Optional[str] = None
        self._reconnect_event = threading.Event()
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    @staticmethod
    def _normalize_target(target: object) -> object:
        if isinstance(target, int):
            return target
        text = str(target).strip()
        if text.isdigit():
            return int(text)
        return text

    def _open_capture(self, target: object) -> tuple[Optional[cv2.VideoCapture], str]:
        """Intenta abrir un índice o URL probando los backends más compatibles en Windows."""
        target = self._normalize_target(target)
        is_url = isinstance(target, str)

        if is_url:
            backends = [("FFMPEG", cv2.CAP_FFMPEG), ("ANY", cv2.CAP_ANY)]
        else:
            backends = [
                ("DSHOW", cv2.CAP_DSHOW),
                ("MSMF", cv2.CAP_MSMF),
                ("ANY", cv2.CAP_ANY),
            ]

        for label, backend in backends:
            cap = None
            try:
                cap = cv2.VideoCapture(target, backend)
                if not cap.isOpened():
                    cap.release()
                    continue

                # Reducir buffer al mínimo para evitar latencia acumulada (clave en DroidCam)
                try:
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                except Exception:
                    pass

                if not is_url:
                    try:
                        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                        cap.set(cv2.CAP_PROP_FPS, 30)
                    except Exception:
                        pass

                # Validar que realmente entregue un frame válido (algunos drivers virtuales abren en negro/error)
                for _ in range(4):
                    ok, frame = cap.read()
                    if ok and frame is not None and frame.size > 0:
                        return cap, label
                    time.sleep(0.05)

                cap.release()
            except Exception:
                if cap is not None:
                    try:
                        cap.release()
                    except Exception:
                        pass

        return None, "NONE"

    def _loop(self) -> None:
        initial_auto_probed = False
        while self.running:
            self._reconnect_event.clear()
            current_target = self.target
            cap, backend_label = self._open_capture(current_target)

            # Si el índice 0 por defecto no existe al arrancar, buscar en índices 1..3 (p.ej. DroidCam)
            if cap is None and not initial_auto_probed and current_target == 0:
                initial_auto_probed = True
                for probe_idx in (1, 2, 3):
                    if not self.running or self._reconnect_event.is_set():
                        break
                    probe_cap, probe_label = self._open_capture(probe_idx)
                    if probe_cap is not None:
                        cap, backend_label = probe_cap, probe_label
                        self.target = probe_idx
                        current_target = probe_idx
                        break
            initial_auto_probed = True

            if cap is None:
                self.available = False
                self.backend_label = "NONE"
                self.last_error = f"No se pudo abrir la fuente de cámara: {current_target}"
                self._reconnect_event.wait(timeout=1.5)
                continue

            self.cap = cap
            self.backend_label = backend_label
            self.last_error = None
            fail_streak = 0

            try:
                while self.running and not self._reconnect_event.is_set():
                    ok, frame = cap.read()
                    if ok and frame is not None and frame.size > 0:
                        fail_streak = 0
                        with self._lock:
                            self.latest_frame = frame
                            self.available = True
                    else:
                        fail_streak += 1
                        if fail_streak >= 25:
                            self.available = False
                            self.last_error = "Stream interrumpido, reconectando..."
                            break
                        time.sleep(0.03)
            except Exception as exc:
                self.available = False
                self.last_error = str(exc)
            finally:
                try:
                    cap.release()
                except Exception:
                    pass
                self.cap = None

            if self.running and not self._reconnect_event.is_set():
                self._reconnect_event.wait(timeout=1.0)

    def switch_target(self, target: object) -> dict:
        """Cambia dinámicamente el índice o URL de la cámara sin reiniciar el servidor."""
        normalized = self._normalize_target(target)
        with self._lock:
            self.target = normalized
            self.latest_frame = None
            self.available = False
        self._reconnect_event.set()
        return {"target": normalized}

    def scan_cameras(self, max_index: int = 4) -> list[dict]:
        """Escanea los índices 0..max_index para listar cámaras físicas y virtuales disponibles."""
        found = []
        active_idx = self.target if isinstance(self.target, int) else None
        for idx in range(max_index + 1):
            if active_idx == idx and self.available:
                found.append({
                    "index": idx,
                    "label": f"Cámara {idx} (Activa · {self.backend_label})",
                    "active": True,
                })
                continue
            cap, label = self._open_capture(idx)
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass
                found.append({
                    "index": idx,
                    "label": f"Cámara {idx} ({label})",
                    "active": False,
                })
        return found

    def read(self):
        with self._lock:
            return None if self.latest_frame is None else self.latest_frame.copy()

    def stop(self) -> None:
        self.running = False
        self._reconnect_event.set()
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass


camera_worker = LocalCameraWorker()


def _auto_open_browser(port: int = 8000) -> None:
    """Abre automáticamente el navegador predeterminado una vez que el servidor esté listo."""
    time.sleep(1.2)
    try:
        webbrowser.open(f"http://localhost:{port}")
    except Exception:
        pass


@app.on_event("startup")
async def on_startup():
    camera_worker.start()
    threading.Thread(target=_auto_open_browser, args=(8000,), daemon=True).start()


@app.on_event("shutdown")
async def on_shutdown():
    camera_worker.stop()


# Modelos Pydantic para endpoints REST
class ModeSwitchRequest(BaseModel):
    mode: str  # "OFFLINE" | "ONLINE"
    gemini_api_key: Optional[str] = None
    gemini_model: Optional[str] = None


class ConfigUpdateRequest(BaseModel):
    video_source: Optional[str] = None  # "AUTO" | "LOCAL" | "MOBILE" | "SIMULATOR"
    interaction_mode: Optional[str] = None  # "OS_CONTROL" | "SIGN_LANGUAGE"
    simulated_gesture: Optional[str] = None  # "G0".."G5"
    hardware_enabled: Optional[bool] = None
    pointer_enabled: Optional[bool] = None  # Modo control directo de mouse
    min_confidence: Optional[float] = None
    buffer_size: Optional[int] = None


class ManualTriggerRequest(BaseModel):
    gesture_id: str


class HearingMessageRequest(BaseModel):
    text: str


class CommitSentenceRequest(BaseModel):
    phrase: Optional[str] = None


class SubmodeRequest(BaseModel):
    submode: str  # "HYBRID" | "CONVERSATION" | "ALPHABET_LSC"


class TranslateToHandsRequest(BaseModel):
    text: str


class AddTokenRequest(BaseModel):
    sign_id: str


class CameraSelectRequest(BaseModel):
    target: str  # "0", "1", "2" o URL como "http://127.0.0.1:4747/video"
    activate_local: bool = True


class UsbConnectRequest(BaseModel):
    mode: str = "SIGNBRIDGE_USB"  # "SIGNBRIDGE_USB" | "DROIDCAM_USB"
    port: Optional[int] = None
    open_on_phone: bool = True


class SpeechTranscribeRequest(BaseModel):
    audio_base64: str
    mime_type: str = "audio/webm"
    translate_to_hands: bool = True


class CalibrateSignRequest(BaseModel):
    sign_id: str
    label: Optional[str] = None
    default_phrase: Optional[str] = None
    motion_type: str = "STATIC"


class ImportSignImageRequest(BaseModel):
    image_base64: str
    mime_type: str = "image/jpeg"
    sign_name: str = ""
    meaning: str = ""
    instructions: str = ""


@app.get("/", response_class=HTMLResponse)
async def serve_hud():
    with open(os.path.join("static", "index.html"), "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/favicon.ico", include_in_schema=False)
async def serve_favicon():
    ico_path = os.path.join("static", "favicon.ico")
    if os.path.exists(ico_path):
        return FileResponse(ico_path, media_type="image/x-icon")
    return FileResponse(os.path.join("static", "logo.png"), media_type="image/png")


@app.get("/mini", response_class=HTMLResponse)
async def serve_mini_hud():
    with open(os.path.join("static", "mini.html"), "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/mobile", response_class=HTMLResponse)
async def serve_mobile():
    with open(os.path.join("static", "mobile.html"), "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/apk")
async def download_apk():
    """Permite descargar directamente el APK compilado desde apk_estractor/SignBridge_v2.apk."""
    apk_path = os.path.join("apk_estractor", "SignBridge_v2.apk")
    if not os.path.exists(apk_path):
        return JSONResponse(
            {"error": "El APK aún no ha sido compilado. Ejecuta python Compilador.py primero."},
            status_code=404,
        )
    return FileResponse(
        path=apk_path,
        media_type="application/vnd.android.package-archive",
        filename="SignBridge_v2.apk",
    )


@app.get("/api/status")
async def api_status(request: Request):
    local_ip = get_local_ip()
    port = request.url.port or 8000
    return {
        "status": "online",
        "local_ip": local_ip,
        "port": port,
        "mobile_url": f"http://{local_ip}:{port}/mobile",
        "ws_mobile_url": f"ws://{local_ip}:{port}/ws/mobile",
        "mode": pipeline.mode,
        "video_source": pipeline.video_source,
        "simulated_gesture": pipeline.simulated_gesture,
        "local_camera_available": camera_worker.available,
        "camera_target": camera_worker.target,
        "camera_backend": camera_worker.backend_label,
        "camera_error": camera_worker.last_error,
        "mobile_connected": pipeline.mobile_connected,
        "mobile_clients": pipeline.mobile_client_count,
        "hardware_enabled": pipeline.hardware.enabled,
        "pointer_enabled": pipeline.hardware.pointer_enabled,
        "gemini": pipeline.gemini_classifier.get_status(),
        "stabilizer": {
            "buffer_size": pipeline.stabilizer.buffer_size,
            "min_confidence": pipeline.stabilizer.min_confidence,
        },
    }


@app.get("/api/cameras")
async def api_list_cameras():
    """Lista las cámaras físicas/virtuales detectadas (incluyendo DroidCam) y el estado USB ADB."""
    loop = asyncio.get_running_loop()
    cameras = await loop.run_in_executor(None, camera_worker.scan_cameras, 4)
    usb_status = await loop.run_in_executor(None, get_adb_devices)
    return {
        "active_target": camera_worker.target,
        "available": camera_worker.available,
        "backend": camera_worker.backend_label,
        "error": camera_worker.last_error,
        "cameras": cameras,
        "usb": usb_status,
    }


@app.post("/api/camera/select")
async def api_select_camera(payload: CameraSelectRequest):
    """Cambia en caliente la cámara local o la URL de DroidCam (ej. 0, 1, 2 o http://IP:4747/video)."""
    target = payload.target.strip()
    if not target:
        return JSONResponse({"ok": False, "error": "Destino de cámara vacío."}, status_code=400)
    res = camera_worker.switch_target(target)
    if payload.activate_local:
        pipeline.set_video_source("LOCAL")
    return {
        "ok": True,
        "target": res["target"],
        "video_source": pipeline.video_source,
    }


@app.post("/api/usb/connect")
async def api_usb_connect(payload: UsbConnectRequest, request: Request):
    """
    Configura conexión por cable USB mediante ADB:
    - SIGNBRIDGE_USB: `adb reverse tcp:8000 tcp:8000` (cámara y audio por cable USB)
    - DROIDCAM_USB: `adb forward tcp:4747 tcp:4747` + conecta OpenCV a http://127.0.0.1:4747/video
    """
    mode = payload.mode.upper().strip()
    loop = asyncio.get_running_loop()
    if mode == "DROIDCAM_USB":
        port = payload.port or 4747
        res = await loop.run_in_executor(None, setup_droidcam_usb_bridge, port)
        if res.get("ok"):
            camera_worker.switch_target(res["stream_url"])
            pipeline.set_video_source("LOCAL")
        return res

    port = payload.port or (request.url.port or 8000)
    res = await loop.run_in_executor(
        None, setup_signbridge_usb_bridge, port, payload.open_on_phone
    )
    if res.get("ok"):
        pipeline.set_video_source("MOBILE")
    return res


@app.get("/api/catalog")
async def api_catalog():
    return {"catalog": GESTURE_CATALOG}


@app.get("/api/conversation/catalog")
async def api_conversation_catalog():
    return {
        "catalog": CONVERSATIONAL_SIGNS_CATALOG,
        "alphabet_catalog": LSC_ALPHABET_CATALOG,
    }


@app.post("/api/conversation/submode")
async def api_conversation_submode(payload: SubmodeRequest):
    return pipeline.set_sign_submode(payload.submode)


@app.post("/api/conversation/translate_to_hands")
async def api_conversation_translate_to_hands(payload: TranslateToHandsRequest):
    return pipeline.translate_phrase_to_hands(payload.text)


@app.post("/api/speech/transcribe")
async def api_speech_transcribe(payload: SpeechTranscribeRequest):
    """Transcribe audio grabado desde el navegador/móvil y lo traduce a texto + señas 3D."""
    b64 = payload.audio_base64 or ""
    if "," in b64:
        b64 = b64.split(",", 1)[1]
    try:
        audio_bytes = base64.b64decode(b64)
    except Exception:
        return JSONResponse({"ok": False, "error": "Audio Base64 inválido."}, status_code=400)

    loop = asyncio.get_running_loop()
    res = await loop.run_in_executor(
        None,
        transcribe_audio_bytes,
        audio_bytes,
        payload.mime_type,
        pipeline.gemini_classifier,
    )
    if res.get("ok") and res.get("text"):
        if payload.translate_to_hands:
            pipeline.set_video_source("SIMULATOR")
            anim = pipeline.translate_phrase_to_hands(res["text"])
            res["animation"] = anim
        else:
            pipeline.add_hearing_spoken_text(res["text"])
    return res


@app.post("/api/speech/pc/start")
async def api_speech_pc_start():
    """Inicia la captura de voz directa desde el micrófono del PC (respaldo infalible)."""
    return pc_mic_recorder.start(pipeline.gemini_classifier, max_seconds=10.0)


@app.post("/api/speech/pc/stop")
async def api_speech_pc_stop():
    """Detiene la captura del micrófono del PC, transcribe y anima en Manos 3D."""
    loop = asyncio.get_running_loop()
    res = await loop.run_in_executor(None, pc_mic_recorder.stop_and_get_result, 12.0)
    if res.get("ok") and res.get("text"):
        pipeline.set_video_source("SIMULATOR")
        res["animation"] = pipeline.translate_phrase_to_hands(res["text"])
    return res


@app.get("/api/speech/pc/status")
async def api_speech_pc_status():
    """Consulta el estado del grabador de micrófono del PC (detecta auto-corte por silencio)."""
    status = pc_mic_recorder.get_status()
    res = status.get("result")
    if not status["recording"] and res and res.get("ok") and res.get("text") and not res.get("_dispatched"):
        res["_dispatched"] = True
        pipeline.set_video_source("SIMULATOR")
        res["animation"] = pipeline.translate_phrase_to_hands(res["text"])
    return status


@app.get("/api/custom_signs")
async def api_list_custom_signs():
    """Lista todas las señas personalizadas y calibraciones reales guardadas."""
    return {"signs": custom_sign_store.list_signs()}


@app.post("/api/custom_signs/calibrate")
async def api_calibrate_custom_sign(payload: CalibrateSignRequest):
    """Captura los últimos frames reales de la mano en cámara para calibrar una letra o seña."""
    samples = list(pipeline.recent_primary_vectors[-10:])
    if not samples:
        return JSONResponse(
            {"ok": False, "error": "No se detecta una mano activa en cámara. Muestra tu mano y vuelve a pulsar."},
            status_code=400,
        )
    sid = payload.sign_id.strip().upper()
    meta = pipeline.conversation_engine.get_sign_meta(sid)
    res = custom_sign_store.add_calibration_samples(
        sign_id=sid,
        vectors_63d=samples,
        label=payload.label or meta.get("label") or sid,
        default_phrase=payload.default_phrase or meta.get("default_phrase") or sid,
        motion_type=payload.motion_type,
        source="camera_calibration",
    )
    return res


@app.post("/api/custom_signs/from_image")
async def api_import_sign_from_image(payload: ImportSignImageRequest):
    """Convierte una imagen de seña (con indicaciones/significado) en una seña reconocible por el programa."""
    b64 = payload.image_base64 or ""
    if "," in b64:
        b64 = b64.split(",", 1)[1]
    try:
        image_bytes = base64.b64decode(b64)
    except Exception:
        return JSONResponse({"ok": False, "error": "Imagen Base64 inválida."}, status_code=400)

    loop = asyncio.get_running_loop()
    res = await loop.run_in_executor(
        None,
        import_sign_from_image,
        custom_sign_store,
        image_bytes,
        payload.mime_type,
        payload.sign_name,
        payload.meaning,
        payload.instructions,
        pipeline._landmarker,
        pipeline.gemini_classifier,
    )
    return res


@app.delete("/api/custom_signs/{sign_id}")
async def api_delete_custom_sign(sign_id: str):
    """Elimina una calibración o seña personalizada."""
    removed = custom_sign_store.delete_sign(sign_id)
    return {"ok": removed, "sign_id": sign_id.upper()}


@app.post("/api/conversation/add_token")
async def api_conversation_add_token(payload: AddTokenRequest):
    return pipeline.add_manual_sign_token(payload.sign_id)


@app.get("/api/conversation/state")
async def api_conversation_state():
    return pipeline.conversation_engine.get_state()


@app.post("/api/gemini/test")
async def api_test_gemini():
    """Prueba en tiempo real la conectividad con Gemini API y reporta latencia y respuesta."""
    return pipeline.gemini_classifier.test_connection()


@app.post("/api/conversation/hearing")
async def api_conversation_hearing(payload: HearingMessageRequest):
    res = pipeline.add_hearing_spoken_text(payload.text)
    return res


@app.post("/api/conversation/commit")
async def api_conversation_commit(payload: CommitSentenceRequest):
    res = pipeline.commit_conversation_sentence(payload.phrase)
    return res


@app.post("/api/conversation/backspace")
async def api_conversation_backspace():
    return pipeline.backspace_conversation_token()


@app.post("/api/conversation/clear")
async def api_conversation_clear():
    return pipeline.clear_conversation_tokens()


@app.get("/api/qr")
async def api_qr(request: Request):
    """Genera el código QR en Base64 para emparejar el teléfono móvil como cámara inalámbrica."""
    local_ip = get_local_ip()
    port = request.url.port or 8000
    mobile_url = f"http://{local_ip}:{port}/mobile"

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=2,
    )
    qr.add_data(mobile_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#08090D", back_color="#F8FAFC")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    return {
        "qr_base64": f"data:image/png;base64,{qr_b64}",
        "mobile_url": mobile_url,
        "local_ip": local_ip,
        "port": port,
        "ws_endpoint": f"ws://{local_ip}:{port}/ws/mobile",
        "mobile_connected": pipeline.mobile_connected,
    }


@app.post("/api/mode")
async def api_set_mode(payload: ModeSwitchRequest):
    if payload.gemini_api_key is not None and payload.gemini_api_key.strip():
        pipeline.gemini_classifier.set_api_key(
            payload.gemini_api_key.strip(),
            payload.gemini_model,
        )
    elif payload.gemini_model is not None and payload.gemini_model.strip():
        pipeline.gemini_classifier.model_name = payload.gemini_model.strip()
    new_mode = pipeline.set_mode(payload.mode)
    return {
        "mode": new_mode,
        "gemini": pipeline.gemini_classifier.get_status(),
    }


@app.post("/api/config")
async def api_update_config(payload: ConfigUpdateRequest):
    if payload.video_source is not None:
        pipeline.set_video_source(payload.video_source)
    if payload.interaction_mode is not None:
        pipeline.set_interaction_mode(payload.interaction_mode)
    if payload.simulated_gesture is not None:
        pipeline.set_simulated_gesture(payload.simulated_gesture)
    if payload.hardware_enabled is not None:
        pipeline.hardware.enabled = bool(payload.hardware_enabled)
    if payload.pointer_enabled is not None:
        # Solo permitir activar puntero si NO estamos en modo SIMULATOR ni en SIGN_LANGUAGE
        if pipeline.video_source != "SIMULATOR" and pipeline.interaction_mode != "SIGN_LANGUAGE":
            pipeline.hardware.pointer_enabled = bool(payload.pointer_enabled)
        else:
            pipeline.hardware.pointer_enabled = False
    if payload.min_confidence is not None:
        pipeline.stabilizer.min_confidence = max(0.50, min(0.99, float(payload.min_confidence)))
    if payload.buffer_size is not None:
        new_n = max(3, min(20, int(payload.buffer_size)))
        pipeline.stabilizer.buffer_size = new_n
        pipeline.stabilizer.buffer = type(pipeline.stabilizer.buffer)(maxlen=new_n)
        pipeline.stabilizer.conf_buffer = type(pipeline.stabilizer.conf_buffer)(maxlen=new_n)

    return {
        "video_source": pipeline.video_source,
        "interaction_mode": pipeline.interaction_mode,
        "simulated_gesture": pipeline.simulated_gesture,
        "hardware_enabled": pipeline.hardware.enabled,
        "pointer_enabled": pipeline.hardware.pointer_enabled,
        "min_confidence": pipeline.stabilizer.min_confidence,
        "buffer_size": pipeline.stabilizer.buffer_size,
    }


@app.post("/api/reset")
async def api_reset_detection():
    """Reinicia el buffer de estabilidad temporal y la detección activa."""
    return pipeline.reset_detection()


@app.post("/api/trigger")
async def api_manual_trigger(payload: ManualTriggerRequest):
    gid = payload.gesture_id.upper().strip()
    if gid in GESTURE_CATALOG:
        meta = GESTURE_CATALOG[gid]
        ev = pipeline.hardware.execute_action(gid, meta["action"], meta["name"])
        pipeline.stabilizer.pulse_until = time.time() + 0.7
        return {"triggered": True, "event": ev}
    elif gid in CONVERSATIONAL_SIGNS_CATALOG or gid in LSC_ALPHABET_CATALOG:
        pipeline.set_simulated_gesture(gid)
        res = pipeline.add_manual_sign_token(gid)
        return {"triggered": True, "conversation": res}
    return JSONResponse({"error": "Gesto inválido"}, status_code=400)


@app.websocket("/ws/hud")
async def ws_hud_endpoint(websocket: WebSocket):
    """
    Canal bidireccional de baja latencia entre el motor Python y el HUD Liquid Glassmorphic.
    Usa dos corrutinas separadas (recepción y emisión) para evitar cancelaciones de WebSocket.
    """
    await websocket.accept()
    connected = True

    async def receive_commands():
        nonlocal connected
        try:
            while connected:
                msg_text = await websocket.receive_text()
                try:
                    data = json.loads(msg_text)
                    cmd = data.get("type")
                    if cmd == "SET_MODE":
                        pipeline.set_mode(data.get("mode", "OFFLINE"))
                    elif cmd == "SET_INTERACTION_MODE":
                        pipeline.set_interaction_mode(data.get("interaction_mode", "OS_CONTROL"))
                    elif cmd == "RESET_DETECTION":
                        pipeline.reset_detection()
                    elif cmd == "SET_GESTURE":
                        pipeline.set_simulated_gesture(data.get("gesture_id", "G1"))
                    elif cmd == "SET_POINTER":
                        if pipeline.video_source != "SIMULATOR" and pipeline.interaction_mode != "SIGN_LANGUAGE":
                            pipeline.hardware.pointer_enabled = bool(data.get("enabled", False))
                        else:
                            pipeline.hardware.pointer_enabled = False
                    elif cmd == "SET_SOURCE":
                        src = data.get("source", "AUTO")
                        pipeline.set_video_source(src)
                    elif cmd == "CONVERSATION_COMMIT":
                        pipeline.commit_conversation_sentence(data.get("phrase"))
                    elif cmd == "CONVERSATION_BACKSPACE":
                        pipeline.backspace_conversation_token()
                    elif cmd == "CONVERSATION_CLEAR":
                        pipeline.clear_conversation_tokens()
                    elif cmd == "HEARING_SPEECH":
                        pipeline.add_hearing_spoken_text(data.get("text", ""))
                    elif cmd == "SET_SIGN_SUBMODE":
                        pipeline.set_sign_submode(data.get("submode", "HYBRID"))
                    elif cmd == "TRANSLATE_TO_HANDS":
                        pipeline.translate_phrase_to_hands(data.get("text", ""))
                    elif cmd == "ADD_SIGN_TOKEN":
                        pipeline.add_manual_sign_token(data.get("sign_id", ""))
                    elif cmd == "CLIENT_FRAME":
                        b64_str = data.get("frame", "")
                        if "," in b64_str:
                            b64_str = b64_str.split(",", 1)[1]
                        pipeline.receive_mobile_frame(base64.b64decode(b64_str))
                except Exception:
                    pass
        except WebSocketDisconnect:
            connected = False
        except Exception:
            connected = False

    recv_task = asyncio.create_task(receive_commands())
    try:
        target_dt = 0.033  # ~30 FPS constantes y fluidos
        while connected:
            t_loop_start = time.perf_counter()
            local_frame = camera_worker.read() if camera_worker.available else None
            # Ejecutar procesamiento CPU-intensivo (MediaPipe + OpenCV) en hilo secundario para no bloquear el event loop
            packet = await asyncio.to_thread(pipeline.process_step, local_frame)
            await websocket.send_json(packet)
            t_elapsed = time.perf_counter() - t_loop_start
            sleep_sec = max(0.002, target_dt - t_elapsed)
            await asyncio.sleep(sleep_sec)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        connected = False
        recv_task.cancel()


@app.websocket("/ws/mobile")
async def ws_mobile_endpoint(websocket: WebSocket):
    """
    Canal WebSocket dedicado para recibir el stream de cámara y comandos del Modo Control Móvil
    (APK Android / PWA), devolviendo telemetría completa y vista procesada en tiempo real.
    """
    await websocket.accept()
    pipeline.mobile_client_count += 1
    pipeline.mobile_connected = True
    try:
        while True:
            message = await websocket.receive()
            if "bytes" in message and message["bytes"]:
                pipeline.receive_mobile_frame(message["bytes"], auto_switch=True)
            elif "text" in message and message["text"]:
                payload = json.loads(message["text"])
                msg_type = payload.get("type")
                if msg_type == "FRAME":
                    b64_data = payload.get("data", "")
                    if "," in b64_data:
                        b64_data = b64_data.split(",", 1)[1]
                    if b64_data:
                        pipeline.receive_mobile_frame(
                            base64.b64decode(b64_data),
                            auto_switch=bool(payload.get("auto_switch", True)),
                        )
                elif msg_type == "ACTIVATE_MOBILE_CAM":
                    enabled = bool(payload.get("enabled", True))
                    pipeline.set_video_source("MOBILE" if enabled else "AUTO")
                elif msg_type == "SET_SOURCE":
                    pipeline.set_video_source(payload.get("source", "MOBILE"))
                elif msg_type == "SET_INTERACTION_MODE":
                    pipeline.set_interaction_mode(payload.get("interaction_mode", "OS_CONTROL"))
                elif msg_type == "RESET_DETECTION":
                    pipeline.reset_detection()
                elif msg_type == "SET_POINTER":
                    if pipeline.video_source != "SIMULATOR" and pipeline.interaction_mode != "SIGN_LANGUAGE":
                        pipeline.hardware.pointer_enabled = bool(payload.get("enabled", False))
                    else:
                        pipeline.hardware.pointer_enabled = False
                elif msg_type == "SET_HARDWARE":
                    pipeline.hardware.enabled = bool(payload.get("enabled", True))
                elif msg_type == "TOUCH_MOVE":
                    tx = float(payload.get("x", 0.5))
                    ty = float(payload.get("y", 0.5))
                    pinch = bool(payload.get("pinch", False))
                    if pipeline.video_source not in ("MOBILE", "LOCAL"):
                        pipeline.video_source = "MOBILE"
                    pipeline.receive_mobile_touch(tx, ty, pinch=pinch)
                elif msg_type == "SET_MODE":
                    if payload.get("gemini_api_key"):
                        pipeline.gemini_classifier.set_api_key(
                            str(payload.get("gemini_api_key")).strip(),
                            payload.get("gemini_model"),
                        )
                    pipeline.set_mode(payload.get("mode", "OFFLINE"))
                elif msg_type == "SET_GEMINI_KEY":
                    key_val = str(payload.get("api_key", "")).strip()
                    model_val = payload.get("model") or "gemini-3-flash-preview"
                    if key_val:
                        pipeline.gemini_classifier.set_api_key(key_val, model_val)
                        pipeline.set_mode("ONLINE")
                elif msg_type == "SIMULATE":
                    gid = payload.get("gesture_id", "G1")
                    pipeline.set_simulated_gesture(gid)
                elif msg_type == "TRIGGER":
                    gid = payload.get("gesture_id", "G1")
                    if gid in GESTURE_CATALOG:
                        pipeline.simulated_gesture = gid
                        meta = GESTURE_CATALOG[gid]
                        pipeline.hardware.execute_action(gid, meta["action"], meta["name"])
                        pipeline.stabilizer.pulse_until = time.time() + 0.7
                    elif gid in CONVERSATIONAL_SIGNS_CATALOG or gid in LSC_ALPHABET_CATALOG:
                        pipeline.set_simulated_gesture(gid)
                        pipeline.add_manual_sign_token(gid)
                elif msg_type == "CONVERSATION_COMMIT":
                    pipeline.commit_conversation_sentence(payload.get("phrase"))
                elif msg_type == "CONVERSATION_BACKSPACE":
                    pipeline.backspace_conversation_token()
                elif msg_type == "CONVERSATION_CLEAR":
                    pipeline.clear_conversation_tokens()
                elif msg_type == "HEARING_SPEECH":
                    pipeline.add_hearing_spoken_text(payload.get("text", ""))
                elif msg_type == "SET_SIGN_SUBMODE":
                    pipeline.set_sign_submode(payload.get("submode", "HYBRID"))
                elif msg_type == "TRANSLATE_TO_HANDS":
                    pipeline.translate_phrase_to_hands(payload.get("text", ""))
                elif msg_type == "ADD_SIGN_TOKEN":
                    pipeline.add_manual_sign_token(payload.get("sign_id", ""))

            # Si el navegador del PC está cerrado o en segundo plano, el APK impulsa el pipeline
            if (time.perf_counter() - pipeline._last_frame_ts) > 0.032:
                local_frame = camera_worker.read() if camera_worker.available else None
                await asyncio.to_thread(pipeline.process_step, local_frame)

            cur_gid = (
                pipeline.stabilizer.buffer[-1]
                if pipeline.stabilizer.buffer
                else (pipeline.stabilizer.last_triggered_gesture or "G0")
            )
            if cur_gid in GESTURE_CATALOG:
                meta_cur = GESTURE_CATALOG[cur_gid]
            elif cur_gid in CONVERSATIONAL_SIGNS_CATALOG:
                s_meta = CONVERSATIONAL_SIGNS_CATALOG[cur_gid]
                meta_cur = {
                    "short_label": s_meta["label"],
                    "sign_label": f"SEÑA ({s_meta['label']})",
                    "sign_message": s_meta["default_phrase"],
                    "action_label": f"Seña LSC ({s_meta['category']})",
                }
            elif cur_gid in LSC_ALPHABET_CATALOG:
                l_meta = LSC_ALPHABET_CATALOG[cur_gid]
                meta_cur = {
                    "short_label": f"LETRA {l_meta['letter']}",
                    "sign_label": f"ABECEDARIO LSC ({l_meta['letter']})",
                    "sign_message": l_meta["description"],
                    "action_label": f"Deletreo LSC ({'DINÁMICO' if l_meta.get('is_dynamic') else 'ESTÁTICO'})",
                }
            else:
                meta_cur = GESTURE_CATALOG["G0"]
            gem_status = pipeline.gemini_classifier.get_status()

            extra_tts = pipeline.conversation_engine.pop_tts_queue()
            if extra_tts:
                pipeline.latest_tts_seq += 1
                pipeline.latest_tts_text = extra_tts

            await websocket.send_json({
                "status": "streaming",
                "mode": pipeline.mode,
                "interaction_mode": pipeline.interaction_mode,
                "video_source": pipeline.video_source,
                "simulated_gesture": pipeline.simulated_gesture,
                "mobile_cam_active": pipeline.video_source == "MOBILE",
                "pointer_enabled": pipeline.hardware.pointer_enabled,
                "hardware_enabled": pipeline.hardware.enabled,
                "fps": round(pipeline._fps_ema, 1),
                "gemini_configured": gem_status.get("configured", False),
                "gemini_model": gem_status.get("model", "gemini-3-flash-preview"),
                "stabilized_id": cur_gid,
                "short_label": meta_cur["short_label"],
                "sign_label": meta_cur.get("sign_label", meta_cur["short_label"]),
                "sign_message": meta_cur.get("sign_message", ""),
                "action_label": meta_cur["action_label"],
                "ring_progress": (
                    sum(1 for x in pipeline.stabilizer.buffer if x == cur_gid)
                    / float(pipeline.stabilizer.buffer_size)
                    if pipeline.stabilizer.buffer and cur_gid != "G0"
                    else 0.0
                ),
                "confidence": round(
                    pipeline.stabilizer.conf_buffer[-1] if pipeline.stabilizer.conf_buffer else 0.0, 3
                ),
                "events": pipeline.hardware.get_recent_events()[:6],
                "sign_history": pipeline.sign_history[:6],
                "conversation": pipeline.conversation_engine.get_state(),
                "tts_to_speak": pipeline.latest_tts_text,
                "tts_seq": pipeline.latest_tts_seq,
                "bimanual": len(pipeline.multi_hand_landmarks) >= 2,
                "hands_count": len(pipeline.multi_hand_landmarks),
                "hud_frame_b64": pipeline.latest_rendered_b64,
            })
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        pipeline.mobile_client_count = max(0, pipeline.mobile_client_count - 1)
        if pipeline.mobile_client_count == 0:
            pipeline.mobile_connected = False


if __name__ == "__main__":
    import uvicorn
    local_lan_ip = get_local_ip()
    print("=" * 64)
    print("  [*] SignBridge Extended v2.0 - Liquid Glassmorphic OS")
    print(f"  [+] HUD Local:         http://localhost:8000")
    print(f"  [+] Mini HUD Flotante: http://localhost:8000/mini")
    print(f"  [+] Camara QR Movil:   http://{local_lan_ip}:8000/mobile")
    print("  [*] Abriendo navegador automaticamente...")
    print("=" * 64)
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)

