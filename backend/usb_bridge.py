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
import urllib.request
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


def _find_installed_package(adb_path: str, serial: str, candidates: List[str]) -> Optional[str]:
    """Busca si alguno de los paquetes Android candidatos está instalado en el dispositivo."""
    try:
        proc = _run_adb(adb_path, ["-s", serial, "shell", "pm", "list", "packages"], timeout=5.0)
        lines = [line.strip().replace("package:", "") for line in proc.stdout.splitlines()]
        for cand in candidates:
            if cand in lines:
                return cand
    except Exception:
        pass
    return None


def _probe_mjpeg_url(port: int) -> str:
    """Detecta qué ruta HTTP de DroidCam/DroidCam OBS responde en localhost:<port>."""
    paths = ["/video", "/mjpegfeed?640x480", "/mjpegfeed"]
    for p in paths:
        url = f"http://127.0.0.1:{port}{p}"
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=1.2) as resp:
                if resp.status == 200:
                    return url
        except Exception:
            continue
    return f"http://127.0.0.1:{port}/video"


def setup_signbridge_usb_bridge(
    port: int = 8000,
    server_port: int = 8000,
    open_on_phone: bool = True,
    launch_app: bool = False,
) -> Dict[str, Any]:
    """
    Configura `adb reverse tcp:<port> tcp:<server_port>` para conectar por cable USB:
    - Si `launch_app=False`: abre `/mobile?autostart=1` en el navegador del celular (sin instalar nada).
    - Si `launch_app=True`: abre la app instalada `com.signbridge.extended` usando el túnel USB.
    """
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
        rev = _run_adb(
            adb_path,
            ["-s", target_serial, "reverse", f"tcp:{port}", f"tcp:{server_port}"],
            timeout=5.0,
        )
        if rev.returncode != 0:
            err = (rev.stderr or rev.stdout or "Error ejecutando adb reverse").strip()
            return {"ok": False, "error": err, **status}

        mobile_usb_url = f"http://127.0.0.1:{port}/mobile?autostart=1"
        opened = False

        if launch_app:
            app_pkg = _find_installed_package(
                adb_path, target_serial, ["com.signbridge.extended"]
            )
            if not app_pkg:
                return {
                    "ok": False,
                    "error": "La app SignBridge (com.signbridge.extended) no está instalada en el celular. Usa el modo 'Sin App (Navegador)' o instala el APK.",
                    **status,
                }
            if open_on_phone:
                launch = _run_adb(
                    adb_path,
                    [
                        "-s", target_serial, "shell", "monkey",
                        "-p", app_pkg, "-c", "android.intent.category.LAUNCHER", "1",
                    ],
                    timeout=5.0,
                )
                opened = launch.returncode == 0
            return {
                "ok": True,
                "mode": "SIGNBRIDGE_APP_USB",
                "port": port,
                "server_port": server_port,
                "device": authorized[0],
                "mobile_usb_url": f"127.0.0.1:{port}",
                "opened_on_phone": opened,
                "message": (
                    f"Túnel USB App activo ({authorized[0]['model']}, puerto {port} -> PC {server_port}). "
                    f"En la app SignBridge usa host 127.0.0.1:{port}."
                ),
                **status,
            }

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
            "port": port,
            "server_port": server_port,
            "device": authorized[0],
            "mobile_usb_url": mobile_usb_url,
            "opened_on_phone": opened,
            "message": (
                f"Túnel USB Sin App activo en {authorized[0]['model']} (puerto {port} -> PC {server_port}). "
                f"Si no abrió solo, abre {mobile_usb_url} en Chrome del celular."
            ),
            **status,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), **status}


def setup_droidcam_usb_bridge(port: int = 4747, open_on_phone: bool = True) -> Dict[str, Any]:
    """Configura `adb forward tcp:<port> tcp:<port>` para conectar DroidCam / DroidCam OBS por cable USB."""
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

        droid_pkg = _find_installed_package(
            adb_path,
            target_serial,
            ["com.dev47apps.droidcam", "com.dev47apps.obsdroidcam", "com.dev47apps.droidcamx"],
        )
        if open_on_phone and droid_pkg:
            _run_adb(
                adb_path,
                [
                    "-s", target_serial, "shell", "monkey",
                    "-p", droid_pkg, "-c", "android.intent.category.LAUNCHER", "1",
                ],
                timeout=5.0,
            )

        stream_url = _probe_mjpeg_url(port)
        return {
            "ok": True,
            "mode": "DROIDCAM_USB",
            "port": port,
            "device": authorized[0],
            "droidcam_package": droid_pkg,
            "stream_url": stream_url,
            "message": (
                f"Túnel DroidCam USB activo en {authorized[0]['model']} (puerto {port}). "
                f"Stream: {stream_url}. Asegúrate de pulsar Play/Iniciar en DroidCam en el celular."
            ),
            **status,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), **status}

