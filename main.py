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
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import qrcode

from backend.pipeline import SignBridgePipeline
from backend.classifier_local import GESTURE_CATALOG


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
    """Hilo lector no-bloqueante para cv2.VideoCapture(0)."""

    def __init__(self):
        self.cap: Optional[cv2.VideoCapture] = None
        self.latest_frame = None
        self.available = False
        self.running = False
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        try:
            cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
            if not cap.isOpened():
                cap = cv2.VideoCapture(0)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                cap.set(cv2.CAP_PROP_FPS, 30)
                self.cap = cap
                while self.running:
                    ok, frame = cap.read()
                    if ok and frame is not None and frame.size > 0:
                        with self._lock:
                            self.latest_frame = frame
                            self.available = True
                    else:
                        time.sleep(0.05)
            else:
                self.available = False
        except Exception:
            self.available = False

    def read(self):
        with self._lock:
            return None if self.latest_frame is None else self.latest_frame.copy()

    def stop(self) -> None:
        self.running = False
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
    simulated_gesture: Optional[str] = None  # "G0".."G4"
    hardware_enabled: Optional[bool] = None
    pointer_enabled: Optional[bool] = None  # Modo control directo de mouse
    min_confidence: Optional[float] = None
    buffer_size: Optional[int] = None


class ManualTriggerRequest(BaseModel):
    gesture_id: str


@app.get("/", response_class=HTMLResponse)
async def serve_hud():
    with open(os.path.join("static", "index.html"), "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/mini", response_class=HTMLResponse)
async def serve_mini_hud():
    with open(os.path.join("static", "mini.html"), "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/mobile", response_class=HTMLResponse)
async def serve_mobile():
    with open(os.path.join("static", "mobile.html"), "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


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


@app.get("/api/catalog")
async def api_catalog():
    return {"catalog": GESTURE_CATALOG}


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
    new_mode = pipeline.set_mode(payload.mode)
    return {
        "mode": new_mode,
        "gemini": pipeline.gemini_classifier.get_status(),
    }


@app.post("/api/config")
async def api_update_config(payload: ConfigUpdateRequest):
    if payload.video_source is not None:
        pipeline.set_video_source(payload.video_source)
    if payload.simulated_gesture is not None:
        pipeline.set_simulated_gesture(payload.simulated_gesture)
    if payload.hardware_enabled is not None:
        pipeline.hardware.enabled = bool(payload.hardware_enabled)
    if payload.pointer_enabled is not None:
        # Solo permitir activar puntero si NO estamos en modo SIMULATOR
        if pipeline.video_source != "SIMULATOR":
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
        "simulated_gesture": pipeline.simulated_gesture,
        "hardware_enabled": pipeline.hardware.enabled,
        "pointer_enabled": pipeline.hardware.pointer_enabled,
        "min_confidence": pipeline.stabilizer.min_confidence,
        "buffer_size": pipeline.stabilizer.buffer_size,
    }


@app.post("/api/trigger")
async def api_manual_trigger(payload: ManualTriggerRequest):
    gid = payload.gesture_id.upper().strip()
    if gid not in GESTURE_CATALOG:
        return JSONResponse({"error": "Gesto inválido"}, status_code=400)
    meta = GESTURE_CATALOG[gid]
    ev = pipeline.hardware.execute_action(gid, meta["action"], meta["name"])
    pipeline.stabilizer.pulse_until = time.time() + 0.7
    return {"triggered": True, "event": ev}


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
                    elif cmd == "SET_GESTURE":
                        pipeline.set_simulated_gesture(data.get("gesture_id", "G1"))
                    elif cmd == "SET_POINTER":
                        if pipeline.video_source != "SIMULATOR":
                            pipeline.hardware.pointer_enabled = bool(data.get("enabled", False))
                        else:
                            pipeline.hardware.pointer_enabled = False
                    elif cmd == "SET_SOURCE":
                        src = data.get("source", "AUTO")
                        pipeline.set_video_source(src)
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
        while connected:
            local_frame = camera_worker.read() if camera_worker.available else None
            packet = pipeline.process_step(local_cam_bgr=local_frame)
            await websocket.send_json(packet)
            await asyncio.sleep(0.038)  # ~26 FPS constantes para HUD
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
    (APK Android / PWA), devolviendo telemetría y vista procesada en tiempo real.
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
                elif msg_type == "SET_POINTER":
                    pipeline.hardware.pointer_enabled = bool(payload.get("enabled", False))
                elif msg_type == "TOUCH_MOVE":
                    tx = float(payload.get("x", 0.5))
                    ty = float(payload.get("y", 0.5))
                    pinch = bool(payload.get("pinch", False))
                    if pipeline.video_source not in ("MOBILE", "LOCAL"):
                        pipeline.video_source = "MOBILE"
                    pipeline.receive_mobile_touch(tx, ty, pinch=pinch)
                elif msg_type == "SET_MODE":
                    pipeline.set_mode(payload.get("mode", "OFFLINE"))
                elif msg_type == "SIMULATE":
                    gid = payload.get("gesture_id", "G1")
                    if gid in GESTURE_CATALOG:
                        pipeline.simulated_gesture = gid
                elif msg_type == "TRIGGER":
                    gid = payload.get("gesture_id", "G1")
                    if gid in GESTURE_CATALOG:
                        pipeline.simulated_gesture = gid
                        meta = GESTURE_CATALOG[gid]
                        pipeline.hardware.execute_action(gid, meta["action"], meta["name"])
                        pipeline.stabilizer.pulse_until = time.time() + 0.7

            cur_gid = (
                pipeline.stabilizer.buffer[-1]
                if pipeline.stabilizer.buffer
                else (pipeline.stabilizer.last_triggered_gesture or "G0")
            )
            meta_cur = GESTURE_CATALOG.get(cur_gid, GESTURE_CATALOG["G0"])

            await websocket.send_json({
                "status": "streaming",
                "mode": pipeline.mode,
                "video_source": pipeline.video_source,
                "mobile_cam_active": pipeline.video_source == "MOBILE",
                "pointer_enabled": pipeline.hardware.pointer_enabled,
                "stabilized_id": cur_gid,
                "short_label": meta_cur["short_label"],
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

