"""
Puente USB (ADB) para SignBridge Extended.

Permite usar la cámara del teléfono Android por cable USB de dos formas:
1. Modo SignBridge USB Nativo (`adb reverse tcp:8000 tcp:8000`):
   El teléfono se conecta directamente al servidor local en `127.0.0.1:8000`
   por cable USB sin depender de Wi-Fi ni configuración de red.
2. Modo DroidCam USB (`adb forward tcp:4747 tcp:4747`):
   Redirige el stream HTTP MJPEG de DroidCam desde el celular hacia
   `http://127.0.0.1:4747/video` para capturarlo con baja latencia en OpenCV.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any, Dict, List, Optional


def find_adb_executable() -> Optional[str]:
    """Localiza el ejecutable `adb` en PATH o en ubicaciones estándar del Android SDK."""
    in_path = shutil.which("adb")
    if in_path:
        return in_path

    candidates: List[str] = []
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    user_profile = os.environ.get("USERPROFILE", "")
    android_home = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT") or ""

    if android_home:
        candidates.append(os.path.join(android_home, "platform-tools", "adb.exe"))
        candidates.append(os.path.join(android_home, "platform-tools", "adb"))
    if local_app_data:
        candidates.append(os.path.join(local_app_data, "Android", "Sdk", "platform-tools", "adb.exe"))
    if user_profile:
        candidates.append(os.path.join(user_profile, "AppData", "Local", "Android", "Sdk", "platform-tools", "adb.exe"))
    candidates.extend([
        r"C:\Android\platform-tools\adb.exe",
        r"C:\platform-tools\adb.exe",
    ])

    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


def _run_adb(adb_path: str, args: List[str], timeout: float = 5.0) -> subprocess.CompletedProcess:
    """Ejecuta un comando ADB sin mostrar ventana de consola en Windows."""
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(
        [adb_path, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=creationflags,
    )


def get_adb_devices() -> Dict[str, Any]:
    """Retorna el estado de ADB y la lista de dispositivos Android conectados por USB."""
    adb_path = find_adb_executable()
    if not adb_path:
        return {
            "adb_available": False,
            "adb_path": None,
            "devices": [],
            "authorized_count": 0,
            "error": "No se encontró adb.exe en el sistema (Android SDK platform-tools).",
        }

    try:
        proc = _run_adb(adb_path, ["devices", "-l"], timeout=5.0)
        devices: List[Dict[str, str]] = []
        for raw_line in proc.stdout.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("List of devices"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                serial = parts[0]
                state = parts[1]
                model = ""
                for token in parts[2:]:
                    if token.startswith("model:"):
                        model = token.split(":", 1)[1].replace("_", " ")
                        break
                devices.append({
                    "serial": serial,
                    "state": state,
                    "model": model or "Android Device",
                })

        authorized = [d for d in devices if d["state"] == "device"]
        return {
            "adb_available": True,
            "adb_path": adb_path,
            "devices": devices,
            "authorized_count": len(authorized),
            "error": None,
        }
    except Exception as exc:
        return {
            "adb_available": True,
            "adb_path": adb_path,
            "devices": [],
            "authorized_count": 0,
            "error": str(exc),
        }


def setup_signbridge_usb_bridge(port: int = 8000, open_on_phone: bool = True) -> Dict[str, Any]:
    """Configura `adb reverse tcp:<port> tcp:<port>` para usar `/mobile` por USB."""
    status = get_adb_devices()
    if not status["adb_available"]:
        return {"ok": False, "error": status["error"], **status}

    authorized = [d for d in status["devices"] if d["state"] == "device"]
    if not authorized:
        unauthorized = [d for d in status["devices"] if d["state"] == "unauthorized"]
        if unauthorized:
            return {
                "ok": False,
                "error": "Celular detectado, pero falta aceptar la huella de 'Depuración USB' en la pantalla del teléfono.",
                **status,
            }
        return {
            "ok": False,
            "error": "No se detectó ningún celular Android por USB. Conecta el cable y activa 'Depuración USB' en Opciones de desarrollador.",
            **status,
        }

    adb_path = status["adb_path"]
    target_serial = authorized[0]["serial"]
    try:
        rev = _run_adb(adb_path, ["-s", target_serial, "reverse", f"tcp:{port}", f"tcp:{port}"], timeout=5.0)
        if rev.returncode != 0:
            err = (rev.stderr or rev.stdout or "Error ejecutando adb reverse").strip()
            return {"ok": False, "error": err, **status}

        mobile_usb_url = f"http://127.0.0.1:{port}/mobile"
        opened = False
        if open_on_phone:
            launch = _run_adb(
                adb_path,
                [
                    "-s",
                    target_serial,
                    "shell",
                    "am",
                    "start",
                    "-a",
                    "android.intent.action.VIEW",
                    "-d",
                    mobile_usb_url,
                ],
                timeout=5.0,
            )
            opened = launch.returncode == 0

        return {
            "ok": True,
            "mode": "SIGNBRIDGE_USB",
            "device": authorized[0],
            "mobile_usb_url": mobile_usb_url,
            "opened_on_phone": opened,
            "message": (
                f"Túnel USB activo en {authorized[0]['model']}. "
                f"Abre {mobile_usb_url} en el celular (o usa la app SignBridge en modo USB 127.0.0.1)."
            ),
            **status,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), **status}


def setup_droidcam_usb_bridge(port: int = 4747) -> Dict[str, Any]:
    """Configura `adb forward tcp:<port> tcp:<port>` para conectar DroidCam por cable USB."""
    status = get_adb_devices()
    if not status["adb_available"]:
        return {"ok": False, "error": status["error"], **status}

    authorized = [d for d in status["devices"] if d["state"] == "device"]
    if not authorized:
        unauthorized = [d for d in status["devices"] if d["state"] == "unauthorized"]
        if unauthorized:
            return {
                "ok": False,
                "error": "Acepta el aviso de 'Depuración USB' en la pantalla del teléfono.",
                **status,
            }
        return {
            "ok": False,
            "error": "No se detectó ningún celular Android por USB con Depuración USB activa.",
            **status,
        }

    adb_path = status["adb_path"]
    target_serial = authorized[0]["serial"]
    try:
        fwd = _run_adb(adb_path, ["-s", target_serial, "forward", f"tcp:{port}", f"tcp:{port}"], timeout=5.0)
        if fwd.returncode != 0:
            err = (fwd.stderr or fwd.stdout or "Error ejecutando adb forward").strip()
            return {"ok": False, "error": err, **status}

        stream_url = f"http://127.0.0.1:{port}/video"
        return {
            "ok": True,
            "mode": "DROIDCAM_USB",
            "device": authorized[0],
            "stream_url": stream_url,
            "message": (
                f"Túnel DroidCam USB activo en {authorized[0]['model']}. "
                f"Asegúrate de tener abierta la app DroidCam en el celular."
            ),
            **status,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), **status}

