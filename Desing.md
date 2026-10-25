# Sistema de Diseño UI/UX: Liquid Glassmorphic (SignBridge)

## 1. Manifiesto Visual y Filosofía
* **Identidad:** Interfaz táctil, fluida, translúcida y de estética técnica limpia ("Liquid Glass"). 
* **Prohibición de Diseños Genéricos:**
  * Prohibido el fondo blanco plano con tarjetas grises y sombras difusas (`box-shadow: 0 4px 6px rgba(0,0,0,0.1)`).
  * Prohibidos los degradados cliché de púrpura a azul estilo plantilla SaaS.
  * Prohibido el uso exclusivo de fuentes del sistema por defecto (como Inter o Arial sin tratar).
  * La interfaz debe parecer un panel de control háptico sobrepuesto a la transmisión de video, con reflejos especulares y desenfoque dinámico.

---

## 2. Tokens de Color y Colorimetría

| Token Semántico | Valor Hex / RGBA | Uso Obligatorio |
| :--- | :--- | :--- |
| `--bg-void` | `#08090D` | Fondo base del lienzo general cuando no hay feed de video completo. |
| `--glass-base` | `rgba(16, 20, 31, 0.60)` | Fondo de tarjetas primarias con desenfoque (`backdrop-filter`). |
| `--glass-elevated` | `rgba(28, 35, 54, 0.40)` | Paneles flotantes secundarios, controles y barras de herramientas. |
| `--border-specular` | `rgba(255, 255, 255, 0.12)` | Borde perimetral de 1px simulando refracción de luz sobre vidrio. |
| `--border-highlight` | `rgba(255, 255, 255, 0.25)` | Acento en el borde superior de las tarjetas para dar sensación de relieve. |
| `--liquid-cyan` | `#00F0FF` | Indicador de detección de gestos, coordenadas activas y modo Gemini. |
| `--liquid-amber` | `#FFB800` | Indicador de modo local fuera de línea (YOLO / TensorFlow). |
| `--liquid-emerald` | `#00FF9D` | Gesto confirmado, acción de hardware ejecutada, conexión QR activa. |
| `--liquid-rose` | `#FF3366` | Estado de rechazo / gesto desconocido / advertencia. |
| `--text-primary` | `#F8FAFC` | Tipografía principal, títulos y mensajes de acción directa. |
| `--text-secondary` | `#94A3B8` | Metadatos, etiquetas de confianza y latencia. |

---

## 3. Propiedades de Capas Vidriadas (Glassmorphism)

### Capa 1: Visualizador de Cámara (HUD Principal)
* **Fondo:** `rgba(10, 14, 23, 0.45)`
* **Filtro:** `backdrop-filter: blur(16px) saturate(160%)`
* **Borde:** `1px solid var(--border-specular)`
* **Radio de curvatura:** `24px` (`rounded-3xl` en Tailwind)
* **Sombra:** `0 12px 40px 0 rgba(0, 0, 0, 0.45)`

### Capa 2: Paneles de Control y Métricas Flotantes
* **Fondo:** `linear-gradient(135deg, rgba(255, 255, 255, 0.08) 0%, rgba(255, 255, 255, 0.02) 100%)` sobre `rgba(18, 22, 34, 0.70)`
* **Filtro:** `backdrop-filter: blur(20px) saturate(180%)`
* **Borde:** `1px solid var(--border-specular)` con borde superior `var(--border-highlight)`
* **Sombra interior:** `box-shadow: inset 0 1px 1px 0 rgba(255, 255, 255, 0.15)`
* **Radio:** `20px` (`rounded-2xl`)

### Capa 3: Modales Flotantes y Vista QR de Emparejamiento
* **Fondo:** `rgba(8, 11, 18, 0.85)`
* **Filtro:** `backdrop-filter: blur(32px) saturate(200%)`
* **Borde:** `1px solid rgba(0, 240, 255, 0.35)`
* **Radio:** `28px`

---

## 4. Tipografía y Estilo de Texto

* **Encabezados y Números de Métrica:** `Space Grotesk`, negrita (`font-bold`), con espaciado cerrado (`tracking-tight`) y números tabulares (`font-variant-numeric: tabular-nums`).
* **Etiquetas y Botones Operativos:** `Plus Jakarta Sans`, peso seminegrita (`font-semibold`), estilo de píldora interactiva con micro-animaciones al presionar (`active:scale-95 transition-transform duration-150`).
* **Telemetría y Puntos de Puntos Clave (Landmarks):** `JetBrains Mono` o fuente monoespaciada para coordenadas $(X, Y, Z)$ y latencia en milisegundos.

---

## 5. Componentes Clave y Reglas de Interacción

1. **Interruptor de Modo Dual (Switch Líquido Offline vs. Online):**
   * No usar un `checkbox` básico ni un botón plano.
   * Componente tipo cápsula deslizante con animación suave (`cubic-bezier(0.16, 1, 0.3, 1)`).
   * **Modo Offline:** Brillo ámbar (`#FFB800`), icono de procesador/red neuronal local, etiqueta: `OFFLINE (YOLO / TF-LITE)`.
   * **Modo Online:** Brillo cian (`#00F0FF`), icono de nube y chispa inteligente, etiqueta: `ONLINE (GEMINI 3 API)`.

2. **Anillo de Estabilidad Temporal (Prevención de Falsas Activaciones):**
   * Un anillo de progreso circular rodea la etiqueta del gesto detectado.
   * Se llena en el sentido de las agujas del reloj durante el tiempo de retención configurado (ej. 300 ms).
   * Al completarse, emite un pulso verde esmeralda (`#00FF9D`) que indica que la acción (clic, desplazamiento, alerta) fue disparada.

3. **Tarjeta de Escaneo QR (Modo Cámara Remota):**
   * Contenedor vidriado con contraste central: tarjeta interior clara donde se renderiza el código QR para fácil lectura del sensor móvil.
   * Información clara: IP Local, Puerto WebSocket y estado del enlace (*Esperando dispositivo* / *Streaming 60 FPS*).

4. **Diseño Adaptativo Móvil / APK:**
   * Botones de acción con área de impacto táctil mínima de $48 \times 48\text{ px}$.
   * Barra inferior flotante vidriada anclada a la zona segura (`safe-area-inset-bottom`) para alternar cámara frontal/trasera, catálogo de gestos y cambio de motor.
   