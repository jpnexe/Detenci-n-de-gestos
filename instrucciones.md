# Especificaciones Técnicas y Requerimientos Funcionales — SignBridge Extended

## 1. System Prompt para el Agente Programador

> **Instrucción de Rol para el Agente:** "Actúa como un Ingeniero Senior de Software y Especialista en Computer Vision. Desarrollarás **SignBridge Extended**, un sistema gestual multiplataforma (escritorio y móvil Android vía APK/PWA) con lógica central en **Python 3.10+**. La arquitectura integra:
>
> 1. Un pipeline de IA local en Python usando OpenCV + MediaPipe Hand Landmarker + clasificador TensorFlow/Keras / YOLO.
>
> 2. Un módulo de inferencia en la nube mediante la API de Gemini multimodal con switch dinámico en tiempo de ejecución.
>
> 3. Un servidor local en Python (FastAPI + WebSockets) que genera un QR para convertir cualquier teléfono móvil en cámara remota inalámbrica.
>
> 4. Una interfaz visual líquida y translúcida basada estrictamente en `DESIGN.md` (Liquid Glassmorphism), con emulación de hardware (scroll, clic derecho y llamadas de asistencia)."

## 2. Pila Tecnológica (Stack 100% Definido)

* **Motor Central e Inteligencia Artificial:** `Python 3.10+`

  * Visión por computador: `opencv-python`, `mediapipe` (versión Tasks Vision o Solutions).

  * Inferencia Local (Offline): `tensorflow` / `tflite-runtime` o `ultralytics` (YOLOv8-pose).

  * Inferencia Remota (Online): `google-genai` (SDK oficial para modelos Gemini).

  * Emulación de acciones de sistema: `pyautogui` / `pynput` (desplazamiento arriba/abajo, clic derecho).

* **Servidor Local de Video y Emparejamiento QR:**

  * Framework backend: `FastAPI` + `uvicorn`.

  * Comunicación bidireccional y streaming: `WebSockets` (transmisión de fotogramas JPEG en Base64 o binario).

  * Generación de QR local: librería Python `qrcode[pil]`.

* **Capa de Presentación e Interfaz de Usuario:**

  * Interfaz Web / HUD: HTML5, TailwindCSS (configurado con los tokens de `DESIGN.md`), Lucide Icons y JavaScript Vanilla/React embebido.

  * Soporte APK Móvil: Capacitor / PWA nativa empaquetable para Android que expone la vista de la cámara al escanear el QR o ejecuta el cliente autónomo.

## 3. Arquitectura del Pipeline en Python

```
                       ┌────────────────────────────────────────┐
                       │           ENTRADA DE VÍDEO             │
                       │  • Opción A: cv2.VideoCapture(0)       │
                       │  • Opción B: WebSocket Stream (Móvil)   │
                       └───────────────────┬────────────────────┘
                                           │
                                           ▼
                       ┌────────────────────────────────────────┐
                       │     DETECCIÓN DE PUNTOS CLAVE          │
                       │   MediaPipe Hands (21 Landmarks 3D)    │
                       └───────────────────┬────────────────────┘
                                           │
                                           ▼
                       ┌────────────────────────────────────────┐
                       │     NORMALIZACIÓN DE VECTORES          │
                       │ • Resta del punto base (Muñeca [0])     │
                       │ • Escalado por distancia euclidiana    │
                       │   Vector resultante: 63 floats         │
                       └───────────────────┬────────────────────┘
                                           │
                        ┌──────────────────┴──────────────────┐
                        │                                     │
           [SWITCH = OFFLINE]                        [SWITCH = ONLINE]
                        │                                     │
                        ▼                                     ▼
      ┌──────────────────────────────────┐  ┌──────────────────────────────────┐
      │     CLASIFICADOR LOCAL (TF)      │  │        GEMINI 3 API CLIENT       │
      │ • MLP / TFLite (Entrada: 63D)    │  │ • Frame Base64 + Prompt estricto │
      │ • Latencia: ~12-20 ms            │  │ • Latencia: ~350-600 ms          │
      │ • Inferencia local sin internet  │  │ • Análisis contextual y semántico│
      └─────────────────┬────────────────┘  └─────────────────┬────────────────┘
                        │                                     │
                        └──────────────────┬──────────────────┘
                                           │
                                           ▼
                       ┌────────────────────────────────────────┐
                       │   ESTABILIZACIÓN TEMPORAL & RECHAZO    │
                       │ • Buffer circular de N fotogramas (N=8)│
                       │ • Umbral de confianza: min >= 0.85     │
                       │ • Clase 'Desconocido' activa           │
                       └───────────────────┬────────────────────┘
                                           │
                                           ▼
                       ┌────────────────────────────────────────┐
                       │       EJECUCIÓN & TELEMETRÍA           │
                       │ • Acciones OS: Scroll, Clic Derecho    │
                       │ • HUD Liquid Glassmorphism (WebSocket) │
                       └────────────────────────────────────────┘

```

## 4. Matriz de Gestos y Acciones de Periféricos

El sistema debe mapear estrictamente los gestos a eventos reales:

| ID | Gesto Físico | Condición Geométrica / Semántica | Acción en Python (`pyautogui` / Web) |
| ----- | ----- | ----- | ----- |
| `G0` | Mano abierta / Movimiento caótico | Coordenadas fuera de rangos de comando o confianza `< 0.85` | **Rechazo activo:** Retorna `Clase: Desconocido`. Cero activación accidental (`--liquid-rose`). |
| `G1` | Dedos índice y medio alzados juntos (Paz / V) | Puntas `8` y `12` extendidas; anular `16` y meñique `20` plegados | **Clic Derecho:** Ejecuta `pyautogui.rightClick()` con cooldown antirrebote. |
| `G2` | Dedo índice extendido apuntando arriba | Punta `8` extendida (`y_8 < y_6`); dedos `12, 16, 20` plegados | **Scroll Arriba:** Ejecuta `pyautogui.scroll(+350)` de forma fluida. |
| `G3` | Puño cerrado / Pulgar e índice hacia abajo | Dedos plegados (`8, 12, 16, 20` debajo de articulaciones MCP/PIP) | **Scroll Abajo:** Ejecuta `pyautogui.scroll(-350)` de forma fluida. |
| `G4` | Tres dedos extendidos (`8, 12, 16`) o Señal Shaka (Pulgar `4` + Meñique `20`) | Puntas `8, 12, 16` extendidas (o `4` y `20` extendidas) | **Llamada de Asistencia:** Dispara alerta sonora/visual prioritaria en HUD y notificación de asistencia. |
| `PINCH` | Pellizco Dedo Índice + Pulgar | Distancia euclidiana entre punta `4` y punta `8` `< 0.055` | **Clic Izquierdo:** Ejecuta `pyautogui.click()` en las coordenadas activas del puntero. |

## 5. Control de Puntero (Mouse Tracking) y Ventana Flotante (PiP)

1. **Dirección Dinámica del Cursor del Mouse:**
   * Al activar el interruptor `PUNTERO: ON`, el sistema rastrea la punta del dedo índice (`INDEX_TIP [8]`).
   * Mapeo de coordenadas relativas con zona de confort central (15% a 85%) hacia la resolución de pantalla nativa (`screen_w`, `screen_h`).
   * Filtro de suavizado exponencial (lerp con $\alpha = 0.38$) para eliminar temblores fisiológicos de la mano y garantizar movimientos fluidos.
   * Gesto de pellizco (*pinch* entre índice `8` y pulgar `4`) para disparar clics izquierdos naturales sin perder la posición del cursor.

2. **Ventana Flotante y Picture-in-Picture (PiP):**
   * **Mini HUD Flotante (`/mini`):** Ventana emergente compacta de 380x460 px con selector de puntero y estado de gestos.
   * **Picture-in-Picture Nativo:** Botón `PiP` que desacopla la transmisión de video con los landmarks 3D sobre cualquier otra aplicación en Windows (Chrome, Word, escritorio, etc.).

## 6. Normalización Matemática y Estabilización Temporal

1. **Invarianza a Traslación y Escala (63 floats):**
   * Sea $P_i = (x_i, y_i, z_i)$ para $i \in \{0, \dots, 20\}$, donde $P_0$ es la muñeca (`WRIST`).
   * Traslación al origen: $P'_i = P_i - P_0$.
   * Factor de escala euclidiano: $d_{\max} = \max_{i} \|P'_i\|_2$ (con $\epsilon = 10^{-6}$).
   * Vector normalizado: $V = \text{flatten}(P'_i / d_{\max}) \in \mathbb{R}^{63}$.

2. **Buffer Circular y Anillo de Retención (`N = 8`):**
   * Se almacenan las últimas $N = 8$ predicciones con confianza $\ge 0.85$.
   * El progreso de estabilidad $S \in [0.0, 1.0]$ se calcula como la fracción de fotogramas en el buffer que coinciden con el gesto activo $G_k$ ($k \neq 0$).
   * Al alcanzar $S = 1.0$, se ejecuta la acción de periférico, se emite el pulso `--liquid-emerald` (`#00FF9D`) y se aplica un período de enfriamiento (*cooldown*).

## 5. Normalización Matemática y Estabilización Temporal

1. **Invarianza a Traslación y Escala (63 floats):**
   * Sea $P_i = (x_i, y_i, z_i)$ para $i \in \{0, \dots, 20\}$, donde $P_0$ es la muñeca (`WRIST`).
   * Traslación al origen: $P'_i = P_i - P_0$.
   * Factor de escala euclidiano: $d_{\max} = \max_{i} \|P'_i\|_2$ (con $\epsilon = 10^{-6}$).
   * Vector normalizado: $V = \text{flatten}(P'_i / d_{\max}) \in \mathbb{R}^{63}$.

2. **Buffer Circular y Anillo de Retención (`N = 8`):**
   * Se almacenan las últimas $N = 8$ predicciones con confianza $\ge 0.85$.
   * El progreso de estabilidad $S \in [0.0, 1.0]$ se calcula como la fracción de fotogramas en el buffer que coinciden con el gesto activo $G_k$ ($k \neq 0$).
   * Al alcanzar $S = 1.0$, se ejecuta la acción de periférico, se emite el pulso `--liquid-emerald` (`#00FF9D`) y se aplica un período de enfriamiento (*cooldown*).

