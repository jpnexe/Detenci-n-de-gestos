"""
SignBridge Extended v2.0 — Compilador Automático de APK Android (Compilador.py)
Empaqueta la interfaz móvil optimizada (static/mobile.html), genera el logo oficial Liquid Glassmorphic
(static/logo.png) en todas las densidades Android (mdpi a xxxhdpi), compila el contenedor nativo
Android con soporte WebRTC de cámara, vibración háptica y WebSocket LAN, y deposita el APK firmado
listo para instalar en la carpeta `apk_estractor/SignBridge_v2.apk`.

Uso:
    python Compilador.py
"""

import os
import shutil
import socket
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent
STATIC_DIR = PROJECT_ROOT / "static"
OUTPUT_DIR = PROJECT_ROOT / "apk_estractor"
BUILD_DIR = PROJECT_ROOT / ".android_build_cache"
APK_FILENAME = "SignBridge_v2.apk"


def get_local_ip() -> str:
    """Detecta la IP LAN actual del PC para preconfigurarla por defecto dentro del APK."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "192.168.1.100"


def generate_official_logo(logo_path: Path, force_regenerate: bool = False) -> None:
    """
    Genera el logo oficial de SignBridge Extended v2.0 (Liquid Glassmorphic 21-Landmark Cyber Hand)
    en alta definición (renderizado supersampling 1024x1024 -> 512x512 RGBA).
    """
    if logo_path.exists() and not force_regenerate:
        return

    size = 1024
    img = np.zeros((size, size, 4), dtype=np.uint8)

    # 1. Fondo Squircle Obsidian (#0B0F19) con brillo radial cian/índigo
    yy, xx = np.mgrid[0:size, 0:size]
    cx, cy = size // 2, size // 2
    dist_center = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)

    # Máscara squircle (superelipse suave)
    nx = np.abs((xx - cx) / (size * 0.46))
    ny = np.abs((yy - cy) / (size * 0.46))
    squircle_val = (nx ** 4.2 + ny ** 4.2) ** (1.0 / 4.2)
    mask = (squircle_val <= 1.0).astype(np.uint8) * 255

    # Gradiente radial oscuro Liquid Glass
    glow = np.clip(1.0 - (dist_center / (size * 0.55)), 0.0, 1.0)
    b_ch = (25 + glow * 55).astype(np.uint8)
    g_ch = (15 + glow * 42).astype(np.uint8)
    r_ch = (11 + glow * 14).astype(np.uint8)

    img[:, :, 0] = b_ch
    img[:, :, 1] = g_ch
    img[:, :, 2] = r_ch
    img[:, :, 3] = mask

    # Dibujar sobre capa BGR para aplicar antialiasing y luego restaurar canal alfa
    canvas = img[:, :, :3].copy()

    # 2. Borde exterior de cristal y anillo de retención temporal
    cv2.circle(canvas, (cx, cy), 410, (55, 40, 28), 6, cv2.LINE_AA)
    cv2.ellipse(canvas, (cx, cy), (392, 392), -90, 0, 265, (212, 182, 6), 18, cv2.LINE_AA)
    cv2.ellipse(canvas, (cx, cy), (392, 392), -90, 265, 345, (129, 185, 16), 22, cv2.LINE_AA)

    # 3. Coordenadas de los 21 Landmarks de la mano biomecánica en el logo
    pts = {
        0: (512, 790),   # Muñeca
        1: (395, 735), 2: (315, 650), 3: (275, 555), 4: (325, 470),     # Pulgar
        5: (425, 560), 6: (395, 435), 7: (375, 355), 8: (355, 275),     # Índice
        9: (495, 540), 10: (495, 395), 11: (495, 295), 12: (495, 205),  # Medio
        13: (565, 555), 14: (580, 420), 15: (590, 325), 16: (600, 240), # Anular
        17: (630, 590), 18: (665, 480), 19: (690, 400), 20: (710, 325), # Meñique
    }

    connections = [
        (0, 1), (1, 2), (2, 3), (3, 4),
        (0, 5), (5, 6), (6, 7), (7, 8),
        (0, 9), (9, 10), (10, 11), (11, 12),
        (0, 13), (13, 14), (14, 15), (15, 16),
        (0, 17), (17, 18), (18, 19), (19, 20),
        (5, 9), (9, 13), (13, 17), (0, 17),
    ]

    # Halo exterior de las conexiones (Glow Cian Eléctrico #06B6D4 -> BGR 212, 182, 6)
    glow_layer = canvas.copy()
    for a, b in connections:
        cv2.line(glow_layer, pts[a], pts[b], (241, 102, 99), 26, cv2.LINE_AA)
    canvas = cv2.addWeighted(glow_layer, 0.32, canvas, 0.68, 0)

    for a, b in connections:
        cv2.line(canvas, pts[a], pts[b], (212, 182, 6), 11, cv2.LINE_AA)

    # Línea de interacción Pinza Clic (Pulgar [4] <-> Índice [8]) en Verde Esmeralda (#10B981)
    cv2.line(canvas, pts[4], pts[8], (129, 185, 16), 7, cv2.LINE_AA)
    mid_pinch = ((pts[4][0] + pts[8][0]) // 2, (pts[4][1] + pts[8][1]) // 2)
    cv2.circle(canvas, mid_pinch, 26, (129, 185, 16), 4, cv2.LINE_AA)

    # 4. Nodos articulares (21 Landmarks)
    fingertips = {4, 8, 12, 16, 20}
    for idx, pt in pts.items():
        if idx == 0:
            cv2.circle(canvas, pt, 24, (129, 185, 16), -1, cv2.LINE_AA)
            cv2.circle(canvas, pt, 12, (252, 250, 248), -1, cv2.LINE_AA)
        elif idx in fingertips:
            cv2.circle(canvas, pt, 20, (129, 185, 16), -1, cv2.LINE_AA)
            cv2.circle(canvas, pt, 10, (252, 250, 248), -1, cv2.LINE_AA)
        else:
            cv2.circle(canvas, pt, 15, (212, 182, 6), -1, cv2.LINE_AA)
            cv2.circle(canvas, pt, 7, (252, 250, 248), -1, cv2.LINE_AA)

    img[:, :, :3] = canvas
    img[mask == 0] = (0, 0, 0, 0)

    logo_512 = cv2.resize(img, (512, 512), interpolation=cv2.INTER_AREA)
    logo_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(logo_path), logo_512)

    # Generar también static/favicon.ico a partir del logo oficial
    ico_path = logo_path.parent / "favicon.ico"
    generate_favicon_ico(logo_path, ico_path)


def generate_favicon_ico(logo_path: Path, ico_path: Path) -> None:
    """Genera el archivo multi-resolución static/favicon.ico a partir de static/logo.png."""
    try:
        from PIL import Image
        im = Image.open(logo_path)
        im.save(ico_path, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
    except Exception:
        pass


def locate_android_toolchain():
    """Localiza el Android SDK (aapt2, d8, zipalign, apksigner, android.jar) y el JDK (javac, keytool)."""
    local_app_data = os.environ.get("LOCALAPPDATA", r"C:\Users\NOSE - PC\AppData\Local")
    sdk_candidates = [
        os.environ.get("ANDROID_HOME", ""),
        os.environ.get("ANDROID_SDK_ROOT", ""),
        os.path.join(local_app_data, "Android", "Sdk"),
        r"C:\Android\Sdk",
    ]
    sdk_dir = None
    for c in sdk_candidates:
        if c and os.path.isdir(c):
            sdk_dir = Path(c)
            break
    if not sdk_dir:
        raise RuntimeError("No se encontró Android SDK en el sistema.")

    # Buscar build-tools más reciente
    bt_root = sdk_dir / "build-tools"
    bt_versions = sorted([d for d in bt_root.iterdir() if d.is_dir()], reverse=True)
    if not bt_versions:
        raise RuntimeError(f"No se encontraron build-tools en {bt_root}")
    build_tools = bt_versions[0]

    # Buscar plataforma Android (preferir android-35 o android-36)
    plat_root = sdk_dir / "platforms"
    plat_candidates = sorted([d for d in plat_root.iterdir() if d.is_dir() and (d / "android.jar").exists()])
    if not plat_candidates:
        raise RuntimeError(f"No se encontraron plataformas android.jar en {plat_root}")
    # Elegir android-35 si existe por compatibilidad estable, si no la primera disponible
    android_jar = next(
        (d / "android.jar" for d in plat_candidates if d.name == "android-35"),
        plat_candidates[0] / "android.jar",
    )

    # Buscar JDK (Android Studio JBR o JAVA_HOME)
    jdk_candidates = [
        Path(r"C:\Program Files\Android\Android Studio\jbr\bin"),
        Path(os.environ.get("JAVA_HOME", "")) / "bin" if os.environ.get("JAVA_HOME") else None,
    ]
    jdk_bin = None
    for jc in jdk_candidates:
        if jc and (jc / "javac.exe").exists():
            jdk_bin = jc
            break
    if not jdk_bin:
        raise RuntimeError("No se encontró javac.exe (JDK / Android Studio JBR).")

    return {
        "sdk_dir": sdk_dir,
        "build_tools": build_tools,
        "android_jar": android_jar,
        "jdk_bin": jdk_bin,
        "aapt2": build_tools / "aapt2.exe",
        "d8": build_tools / "d8.bat",
        "zipalign": build_tools / "zipalign.exe",
        "apksigner": build_tools / "apksigner.bat",
        "javac": jdk_bin / "javac.exe",
        "keytool": jdk_bin / "keytool.exe",
    }


def write_android_project_files(res_dir: Path, src_dir: Path, manifest_path: Path, logo_src: Path):
    """Genera los recursos Android (iconos mipmap, valores, AndroidManifest.xml y MainActivity.java)."""
    # 1. Generar iconos en todas las densidades Android desde static/logo.png
    logo_img = cv2.imread(str(logo_src), cv2.IMREAD_UNCHANGED)
    densities = {
        "mipmap-mdpi": 48,
        "mipmap-hdpi": 72,
        "mipmap-xhdpi": 96,
        "mipmap-xxhdpi": 144,
        "mipmap-xxxhdpi": 192,
    }
    for folder_name, px in densities.items():
        d_path = res_dir / folder_name
        d_path.mkdir(parents=True, exist_ok=True)
        resized = cv2.resize(logo_img, (px, px), interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(d_path / "ic_launcher.png"), resized)

    # 2. values/strings.xml y styles.xml
    val_dir = res_dir / "values"
    val_dir.mkdir(parents=True, exist_ok=True)
    (val_dir / "strings.xml").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="app_name">SignBridge v2.0</string>
</resources>
""",
        encoding="utf-8",
    )

    # 3. AndroidManifest.xml con soporte de Cámara, Vibración Háptica y Tráfico LAN Cleartext (ws:// y http://)
    manifest_path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.signbridge.extended"
    android:versionCode="20"
    android:versionName="2.0.0">

    <uses-sdk android:minSdkVersion="24" android:targetSdkVersion="34" />

    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />
    <uses-permission android:name="android.permission.ACCESS_WIFI_STATE" />
    <uses-permission android:name="android.permission.CAMERA" />
    <uses-permission android:name="android.permission.VIBRATE" />
    <uses-permission android:name="android.permission.WAKE_LOCK" />

    <uses-feature android:name="android.hardware.camera" android:required="false" />
    <uses-feature android:name="android.hardware.camera.autofocus" android:required="false" />
    <uses-feature android:name="android.hardware.camera.front" android:required="false" />

    <application
        android:label="@string/app_name"
        android:icon="@mipmap/ic_launcher"
        android:roundIcon="@mipmap/ic_launcher"
        android:usesCleartextTraffic="true"
        android:hardwareAccelerated="true"
        android:theme="@android:style/Theme.DeviceDefault.NoActionBar">

        <activity
            android:name="com.signbridge.extended.MainActivity"
            android:exported="true"
            android:configChanges="orientation|screenSize|keyboardHidden"
            android:screenOrientation="portrait">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
""",
        encoding="utf-8",
    )

    # 4. MainActivity.java con servidor virtual HTTPS de assets (para contexto seguro WebRTC getUserMedia)
    #    y MIXED_CONTENT_ALWAYS_ALLOW (para conectar por WebSocket ws:// a la IP local del PC)
    pkg_dir = src_dir / "com" / "signbridge" / "extended"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / "MainActivity.java").write_text(
        """package com.signbridge.extended;

import android.Manifest;
import android.app.Activity;
import android.content.Context;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.view.Window;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.PermissionRequest;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import java.io.InputStream;
import java.util.HashMap;
import java.util.Map;

public class MainActivity extends Activity {
    private WebView webView;
    private static final int CAMERA_PERM_CODE = 101;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        Window window = getWindow();
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            window.setStatusBarColor(Color.parseColor("#0B0F19"));
            window.setNavigationBarColor(Color.parseColor("#08090D"));
        }

        requestCameraPermissionIfNeeded();

        webView = new WebView(this);
        webView.setBackgroundColor(Color.parseColor("#0B0F19"));
        setContentView(webView);

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setAllowFileAccess(true);
        settings.setAllowContentAccess(true);
        settings.setMediaPlaybackRequiresUserGesture(false);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            settings.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        }

        webView.addJavascriptInterface(new NativeBridge(this), "SignBridgeNative");

        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onPermissionRequest(final PermissionRequest request) {
                runOnUiThread(new Runnable() {
                    @Override
                    public void run() {
                        request.grant(request.getResources());
                    }
                });
            }
        });

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                if (uri != null && "appassets.androidplatform.net".equals(uri.getHost())) {
                    String path = uri.getPath();
                    if (path == null || path.equals("/") || path.isEmpty()) {
                        path = "mobile.html";
                    } else if (path.startsWith("/")) {
                        path = path.substring(1);
                    }
                    try {
                        InputStream is = getAssets().open(path);
                        String mime = "text/html";
                        if (path.endsWith(".png")) mime = "image/png";
                        else if (path.endsWith(".json")) mime = "application/json";
                        else if (path.endsWith(".js")) mime = "application/javascript";
                        else if (path.endsWith(".css")) mime = "text/css";

                        Map<String, String> headers = new HashMap<>();
                        headers.put("Access-Control-Allow-Origin", "*");
                        return new WebResourceResponse(mime, "UTF-8", 200, "OK", headers, is);
                    } catch (Exception e) {
                        return super.shouldInterceptRequest(view, request);
                    }
                }
                return super.shouldInterceptRequest(view, request);
            }
        });

        webView.loadUrl("https://appassets.androidplatform.net/mobile.html");
    }

    private void requestCameraPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(new String[]{Manifest.permission.CAMERA}, CAMERA_PERM_CODE);
            }
        }
    }

    public class NativeBridge {
        private Context ctx;
        NativeBridge(Context c) {
            this.ctx = c;
        }

        @JavascriptInterface
        public void vibrate(int ms) {
            try {
                Vibrator v = (Vibrator) ctx.getSystemService(Context.VIBRATOR_SERVICE);
                if (v != null && v.hasVibrator()) {
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                        v.vibrate(VibrationEffect.createOneShot(ms, VibrationEffect.DEFAULT_AMPLITUDE));
                    } else {
                        v.vibrate(ms);
                    }
                }
            } catch (Exception ignored) {}
        }

        @JavascriptInterface
        public void requestCamera() {
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    requestCameraPermissionIfNeeded();
                }
            });
        }
    }

    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }
}
""",
        encoding="utf-8",
    )


def run_cmd(cmd_list, env=None, desc=""):
    """Ejecuta un comando del toolchain de Android y verifica su código de salida."""
    res = subprocess.run(
        [str(x) for x in cmd_list],
        env=env,
        capture_output=True,
        text=True,
        shell=False,
    )
    if res.returncode != 0:
        raise RuntimeError(
            f"Error en {desc}:\nComando: {' '.join(str(x) for x in cmd_list)}\n"
            f"STDOUT: {res.stdout}\nSTDERR: {res.stderr}"
        )
    return res


def compile_apk():
    t0 = time.time()
    print("=" * 68)
    print("  [*] SignBridge Extended v2.0 - Compilador Nativo de APK Android")
    print("=" * 68)

    # 1. Asegurar carpeta de salida apk_estractor y logo oficial
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    logo_path = STATIC_DIR / "logo.png"
    ico_path = STATIC_DIR / "favicon.ico"
    print("  [1/6] Verificando y generando Logo Oficial y Favicon (static/logo.png, static/favicon.ico)...")
    generate_official_logo(logo_path)
    if not ico_path.exists():
        generate_favicon_ico(logo_path, ico_path)

    # 2. Localizar Android SDK y JDK
    print("  [2/6] Detectando Android SDK y OpenJDK en el sistema...")
    tools = locate_android_toolchain()
    env = os.environ.copy()
    env["JAVA_HOME"] = str(tools["jdk_bin"].parent)
    env["PATH"] = f"{tools['jdk_bin']};{tools['build_tools']};{env.get('PATH', '')}"
    print(f"        + SDK Build-Tools: {tools['build_tools'].name}")
    print(f"        + Android Platform: {tools['android_jar'].parent.name}")

    # 3. Preparar árbol temporal de compilación
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    res_dir = BUILD_DIR / "res"
    src_dir = BUILD_DIR / "src"
    obj_dir = BUILD_DIR / "obj"
    dex_dir = BUILD_DIR / "dex"
    compiled_res_zip = BUILD_DIR / "compiled_res.zip"
    manifest_path = BUILD_DIR / "AndroidManifest.xml"
    for d in (res_dir, src_dir, obj_dir, dex_dir):
        d.mkdir(parents=True, exist_ok=True)

    print("  [3/6] Generando iconos multi-densidad y código nativo Android...")
    write_android_project_files(res_dir, src_dir, manifest_path, logo_path)

    # 4. Compilar y enlazar recursos con AAPT2
    print("  [4/6] Compilando recursos y manifiesto con AAPT2...")
    run_cmd(
        [tools["aapt2"], "compile", "--dir", res_dir, "-o", compiled_res_zip],
        env=env,
        desc="aapt2 compile",
    )

    unsigned_apk = BUILD_DIR / "unsigned.apk"
    run_cmd(
        [
            tools["aapt2"],
            "link",
            "-o",
            unsigned_apk,
            "-I",
            tools["android_jar"],
            "--manifest",
            manifest_path,
            "--java",
            src_dir,
            compiled_res_zip,
        ],
        env=env,
        desc="aapt2 link",
    )

    # 5. Compilar clases Java (MainActivity.java + R.java) y convertir a DEX con D8
    print("  [5/6] Compilando motor nativo Java y empaquetando assets móviles...")
    java_files = list(src_dir.rglob("*.java"))
    run_cmd(
        [
            tools["javac"],
            "--release",
            "11",
            "-encoding",
            "UTF-8",
            "-cp",
            tools["android_jar"],
            "-d",
            obj_dir,
            *java_files,
        ],
        env=env,
        desc="javac",
    )

    class_files = list(obj_dir.rglob("*.class"))
    run_cmd(
        [
            tools["d8"],
            "--min-api",
            "24",
            "--lib",
            tools["android_jar"],
            "--output",
            dex_dir,
            *class_files,
        ],
        env=env,
        desc="d8 dexing",
    )

    # Inyectar classes.dex y los archivos de static/ (mobile.html con IP LAN por defecto, logo.png, manifest.json)
    local_ip = get_local_ip()
    default_host = f"{local_ip}:8000"
    mobile_html_content = (STATIC_DIR / "mobile.html").read_text(encoding="utf-8")
    mobile_html_compiled = mobile_html_content.replace("__DEFAULT_PC_HOST__", default_host)

    with zipfile.ZipFile(unsigned_apk, "a", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(dex_dir / "classes.dex", "classes.dex")
        zf.writestr("assets/mobile.html", mobile_html_compiled.encode("utf-8"))
        zf.write(STATIC_DIR / "logo.png", "assets/logo.png")
        if (STATIC_DIR / "manifest.json").exists():
            zf.write(STATIC_DIR / "manifest.json", "assets/manifest.json")

    # 6. Alinear (zipalign) y firmar criptográficamente (apksigner) hacia apk_estractor/
    print("  [6/6] Alineando y firmando el paquete APK final...")
    aligned_apk = BUILD_DIR / "aligned.apk"
    run_cmd(
        [tools["zipalign"], "-p", "-f", "4", unsigned_apk, aligned_apk],
        env=env,
        desc="zipalign",
    )

    keystore_path = PROJECT_ROOT / "models" / "signbridge_release.keystore"
    keystore_path.parent.mkdir(parents=True, exist_ok=True)
    if not keystore_path.exists():
        run_cmd(
            [
                tools["keytool"],
                "-genkeypair",
                "-v",
                "-keystore",
                keystore_path,
                "-alias",
                "signbridge",
                "-keyalg",
                "RSA",
                "-keysize",
                "2048",
                "-validity",
                "10000",
                "-storepass",
                "signbridge2026",
                "-keypass",
                "signbridge2026",
                "-dname",
                "CN=SignBridge Extended, OU=AI Biomechanics, O=SignBridge, L=Bogota, S=CO, C=CO",
            ],
            env=env,
            desc="keytool keystore generation",
        )

    final_apk_path = OUTPUT_DIR / APK_FILENAME
    if final_apk_path.exists():
        final_apk_path.unlink()

    run_cmd(
        [
            tools["apksigner"],
            "sign",
            "--ks",
            keystore_path,
            "--ks-key-alias",
            "signbridge",
            "--ks-pass",
            "pass:signbridge2026",
            "--key-pass",
            "pass:signbridge2026",
            "--out",
            final_apk_path,
            aligned_apk,
        ],
        env=env,
        desc="apksigner",
    )

    # Limpiar caché temporal de compilación
    shutil.rmtree(BUILD_DIR, ignore_errors=True)

    elapsed = time.time() - t0
    size_kb = final_apk_path.stat().st_size / 1024.0
    print("=" * 68)
    print(f"  [OK] APK COMPILADO EXITOSAMENTE EN {elapsed:.2f}s")
    print(f"  [+] Archivo APK:  {final_apk_path}")
    print(f"  [+] Tamaño:       {size_kb:.1f} KB")
    print(f"  [+] Host PC LAN:  {default_host} (preconfigurado en el APK)")
    print("=" * 68)
    return final_apk_path


if __name__ == "__main__":
    compile_apk()

