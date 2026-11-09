Implementation Plan
Plan Maestro de Implementación: Lengua de Señas Colombiana (LSC), Conversación Fluida y Avatar 3D de Manos

Proyecto: SignBridge Extended v4.0 — Especialización en Lengua de Señas Colombiana (LSC)
Objetivo Principal: Incorporar el Abecedario Dactilológico Colombiano completo (27 letras: A–Z + Ñ), expandir el catálogo conversacional a +45 señas estructuradas para sostener diálogos reales, refinar la precisión biomecánica/cinemática del detector y garantizar la traducción en doble vía:

Señas en cámara
→
→ Texto conjugado y Voz (TTS).
Frases / Voz / Texto
→
→ Modelo 3D de Manos Animado que ejecuta secuencialmente las señas y el deletreo acompañados de su texto.

1. ¿De Dónde Salen los Gestos y Cómo se Parametrizan?

Para que el sistema reconozca las señas con rigor técnico y sin depender de bases de datos externas pesadas en tiempo de ejecución, los gestos provienen de tres fuentes integradas:

Fuente Lingüística Oficial (INSOR / FENASCOL — Colombia):
Abecedario Dactilológico LSC: Basado exactamente en la lámina oficial proporcionada de 27 signos manuales (A a Z incluyendo Ñ), respetando las particularidades propias de Colombia (por ejemplo, en LSC la U se articula con índice y meñique extendidos, las letras M, N, Ñ se articulan con los dedos apuntando hacia abajo, y la S se traza dinámicamente con el índice en el aire).
Vocabulario Conversacional LSC: Basado en los parámetros formacionales de la LSC: configuración manual (queirema), orientación de la palma (queirotropema), punto de contacto/espacio (toponema) y movimiento (kinema).
Fuente Matemática y Sintética (Generador Anatómico 3D en backend/classifier_local.py):
Cada letra del abecedario y cada seña conversacional se codifica como un tensor canónico de 21 puntos clave 3D
(
𝑥
,
𝑦
,
𝑧
)
(x,y,z) (y 42 puntos en señas bimanuales).
Estas matrices alimentan dos subsistemas a la vez:
Hacia adelante (Reconocimiento): Generan miles de muestras sintéticas con rotaciones 3D (
±
18
∘
±18
∘
), variaciones de escala y ruido gaussiano fisiológico para entrenar el modelo neuronal gesture_mlp.keras y validar reglas geométricas.
Hacia atrás (Traducción Texto
→
→ Manos 3D): Sirven como keyframes (fotogramas clave) para que el Modelo 3D de Manos interpole suavemente las articulaciones y represente en pantalla cualquier palabra o frase dicha o escrita. 2. Especificación Técnica del Abecedario LSC (27 Letras: A–Z + Ñ)

Abecedario en Lengua de Señas Colombiana

A partir de la lámina proporcionada, el abecedario LSC se divide en 21 configuraciones estáticas/posturales y 6 letras dinámicas con trayectoria cinemática:

Letra Tipo Configuración Anatómica en LSC (según lámina oficial) Criterio Biomecánico / Cinemático (21 Landmarks)
A Estática Puño cerrado con el pulgar extendido lateralmente hacia arriba. thumb=True, index=middle=ring=pinky=False, pts[4].y < pts[2].y.
B Estática 4 dedos largos extendidos y unidos, pulgar doblado sobre la palma. index=middle=ring=pinky=True, thumb=False, separación spread(8,12) < 0.045.
C Estática Mano semi-curvada formando un arco lateral en "C". Curvatura intermedia (45° < curl < 115°) en los 4 dedos + arco entre pts[4] y pts[8] (0.08 < d < 0.18).
D Estática Índice extendido vertical arriba; medio, anular y meñique tocan la punta del pulgar. index=True, middle=ring=pinky=False, distancia d(4, 12) < 0.075, orientación UP.
E Estática Los 4 dedos doblados en garra (PIP/DIP flexionados) y pulgar recogido bajo ellos. curl > 120° con MCP semi-abierto (d_tip_to_palm > d_fist), thumb=False, sin contacto con pts[4].
F Estática Índice extendido hacia arriba con el pulgar apoyado/cruzado sobre el lado radial; medio, anular y meñique doblados. index=True, middle=ring=pinky=False, contacto estrecho entre pulgar pts[4] y base/lado del índice pts[6].
G Dinámica / Lat. Mano horizontal con índice apuntando hacia el costado (izquierda) y ligero giro/movimiento en la punta. index=True, middle=ring=pinky=False, dirección del índice HORIZONTAL (abs(dx) > abs(dy)).
H Dinámica / Lat. Índice y medio extendidos juntos en posición horizontal con desplazamiento lateral. index=middle=True, ring=pinky=False, dirección HORIZONTAL (abs(dx) > abs(dy)).
I Estática Solo el dedo meñique (20) extendido verticalmente hacia arriba; demás plegados. pinky=True, thumb=index=middle=ring=False, sin descenso en curva J.
J Dinámica Dedo meñique extendido trazando una curva en "J" (baja verticalmente y sube en gancho). Postura base I (pinky=True) + trayectoria cinemática en J (net_dy > 0.06 seguido de curvatura lateral).
K Estática Índice y medio separados en V inclinada/oblicua con el pulgar apoyado en el espacio central. index=middle=True, ring=pinky=False, pulgar proyectado entre pts[5] y pts[9], inclinación oblicua.
L Estática Índice extendido verticalmente arriba y pulgar extendido horizontalmente formando ángulo de
90
∘
90
∘
. thumb=True, index=True, middle=ring=pinky=False, ángulo ∠(4-2, 8-5) ≈ 75°–105°.
M Estática Mano colgante hacia abajo con 3 dedos (índice, medio y anular) extendidos apuntando al suelo. index=middle=ring=True, pinky=False, dirección DOWN (pts[8].y > pts[5].y y pts[12].y > pts[9].y).
N Estática Mano colgante hacia abajo con 2 dedos (índice y medio) extendidos apuntando al suelo (estática). index=middle=True, ring=pinky=False, dirección DOWN (pts[8].y > pts[5].y), is_oscillating_x=False.
Ñ Dinámica Misma postura que la N (índice y medio apuntando hacia abajo) con movimiento oscilatorio lateral. Postura N (dirección DOWN) + cinemática is_oscillating_x=True (vaivén horizontal de muñeca/dedos).
O Estática Todas las yemas de los dedos se unen con el pulgar formando un círculo cerrado "O". Distancia media de puntas (8,12,16) -> 4 pequeña (< 0.068) con cavidad circular interna.
P Estática Índice apuntando verticalmente hacia abajo con pulgar y medio haciendo figura de apoyo. index=True apuntando DOWN (pts[8].y > pts[5].y), middle=ring=pinky=False o semi-flexionados.
Q Estática Todas las yemas de los 5 dedos unidas en racimo apuntando hacia arriba (capullo). Orientación UP, las 5 puntas (4,8,12,16,20) convergen en el extremo superior (spread_all < 0.065).
R Estática Dedos índice y medio extendidos y cruzados entre sí. index=middle=True, ring=pinky=False, cruce torsional en X ((pts[8].x - pts[12].x) invierte el signo de (pts[5].x - pts[9].x)).
S Dinámica Dedo índice extendido trazando la silueta de una "S" en el aire. index=True, middle=ring=pinky=False + trayectoria cinemática serpenteante (oscillations_x >= 2 + descenso vertical net_dy > 0.05).
T Estática Índice y medio juntos en oblicuo con el pulgar asomando/contactando entre ellos. Configuración compacta oblicua con d(4, 6) < 0.055 e índice/medio juntos en diagonal.
U Estática Índice (8) y meñique (20) extendidos verticalmente; medio y anular plegados bajo el pulgar. index=True, pinky=True, middle=ring=False (rasgo distintivo clave del abecedario LSC).
V Estática Dedos índice y medio extendidos arriba y separados en "V". index=middle=True, ring=pinky=False, orientación UP, abducción spread(8,12) >= 0.055.
W Estática Dedos índice, medio y anular extendidos arriba y separados en "W"; meñique y pulgar plegados. index=middle=ring=True, pinky=False, orientación UP.
X Estática Dedo índice encorvado en forma de gancho; demás dedos cerrados en puño. middle=ring=pinky=False, índice en semi-flexión (bend_mcp < 45° pero bend_pip > 65°).
Y Estática Dedos pulgar y meñique extendidos (Shaka); índice, medio y anular plegados. thumb=True, pinky=True, index=middle=ring=False.
Z Dinámica Dedos índice y medio juntos trazando una "Z" en el aire (horizontal
→
→ diagonal
→
→ horizontal). index=True (con middle junto) + detector de trayectoria en zigzag is_z_trajectory=True. 3. Ampliación del Vocabulario Conversacional (+45 Señas en 7 Categorías)

Para que una persona pueda sostener una conversación fluida de principio a fin (saludar, presentarse, hacer preguntas, expresar necesidades, hablar de estudios/trabajo y despedirse), expandimos el catálogo de backend/conversation_engine.py de 18 a 46 señas conversacionales:

3.1 Nuevas Categorías y Señas a Implementar
Pronombres y Sujetos (6 señas):
S_YO ("Yo" — índice apuntando al pecho propio).
S_TU ("Tú / Usted" — índice apuntando hacia el interlocutor al frente).
S_EL ("Él / Ella" — índice apuntando lateralmente).
S_NOSOTROS ("Nosotros" — dos dedos o mano en arco en el pecho).
S_AMIGO ("Amigo / Compañero" — manos entrelazadas o toque cálido en el pecho).
S_PROFESOR ("Profesor / Docente" — configuración en P/enseñanza proyectada desde la sien/frente).
Saludos y Cortesía (8 señas):
S_HOLA ("Hola"), S_BUENOS_DIAS ("Buenos días"), S_BUENAS_TARDES ("Buenas tardes"), S_BUENAS_NOCHES ("Buenas noches"), S_ADIOS ("Adiós / Hasta luego"), S_GRACIAS ("Gracias"), S_POR_FAVOR ("Por favor"), S_MUCHO_GUSTO ("Mucho gusto"), S_DISCULPA ("Perdón / Disculpa").
Verbos de Conversación Diaria (10 señas):
S_QUERER ("Quiero / Deseo" — manos abiertas atrayendo hacia el pecho).
S_NECESITAR ("Necesito" — índice/pulgar con movimiento firme hacia abajo).
S_COMER ("Comer / Alimentación" — mano en capullo Q acercándose a la boca/parte superior).
S_AGUA ("Beber / Agua" — letra L/pulgar hacia la boca).
S_ESTUDIAR ("Estudiar / Aprender" — palma base abierta y mano dominante leyendo/absorbiendo).
S_TRABAJAR ("Trabajar" — ambos puños golpeando suavemente muñeca con muñeca).
S_HABLAR ("Hablar / Comunicar" — índices alternando frente al rostro/pecho).
S_IR ("Ir" — índice proyectándose hacia adelante/arriba).
S_ENTENDIDO ("Entiendo / Comprendido"), S_NO_ENTIENDO ("No entiendo" — índice en sien con negación).
Preguntas e Interrogativos (7 señas):
S_COMO_ESTAS ("¿Cómo estás?"), S_QUE ("¿Qué?"), S_DONDE ("¿Dónde?"), S_CUANDO ("¿Cuándo?"), S_QUIEN ("¿Quién?"), S_POR_QUE ("¿Por qué?"), S_CUANTO ("¿Cuánto?" — dedos abriéndose progresivamente en conteo).
Respuestas, Estado de Ánimo y Salud (8 señas):
S_SI ("Sí"), S_NO ("No"), S_BIEN ("Bien"), S_MAL ("Mal"), S_REGULAR ("Más o menos" — palma horizontal basculando), S_FELIZ ("Feliz / Contento"), S_CANSADO ("Cansado"), S_OCUPADO ("Ocupado").
Tiempo y Lugares Cotidianos (4 señas):
S_HOY ("Hoy / Ahora"), S_MANANA ("Mañana"), S_CASA ("Casa" — ambas manos formando un techo en triángulo
∧
∧ uniendo las puntas), S_UNIVERSIDAD ("Universidad / Clase").
Emergencias y Control del Diálogo (4 señas):
S_AYUDA ("Ayuda / SOS"), S_MEDICO ("Médico / Dolor"), S_ESPERA ("Espera un momento"), S_DESPACIO ("Más despacio"), S_REPETIR ("¿Puedes repetir?"), S_CONTINUAR ("Continuar"). 4. El Componente de Traducción en Doble Vía (Textual + Modelo 3D de Manos)

El profesor pidió específicamente que la traducción funcione de dos maneras complementarias:

4.1 Vía 1: De Lengua de Señas a Texto Natural y Voz (Glosas LSC
→
→ Español)
En LSC, la estructura gramatical suele ser Sujeto–Objeto–Verbo (SOV) o telegráfica (ej. YO + IR + CASA o HOLA + NOMBRE + J-U-A-N).
Implementaremos en backend/conversation_engine.py:
Modo Deletreo Dactilológico Integrado: Cuando el usuario realiza letras del abecedario (L_A .. L_Z), estas se concatenan formando una palabra en tiempo real (ej. C + A + R + L + O + S
→
→ "CARLOS") sin espacios intermedios hasta insertar una seña léxica o pausa.
Motor Gramatical Local (Offline) + Fusión Semántica Gemini (Online):
Transforma secuencias de glosas como ["Yo", "Querer", "Ayuda", "Por favor"] en oraciones naturales conjugadas: "Yo quiero ayuda, por favor." o ["Hola", "¿Cómo estás?", "Yo", "Bien"]
→
→ "Hola, ¿cómo estás? Yo estoy muy bien."
4.2 Vía 2: De Frases / Voz / Texto a Modelo 3D de Manos Animado ("Intérprete Visual de Manos")
Cuando el oyente habla por micrófono (STT), escribe cualquier frase en un cuadro de texto o selecciona una frase conversacional, el sistema activa el Reproductor Visual de Manos 3D (Sign Player):
Traductor Inverso (Español
→
→ Secuencia de Señas LSC + Deletreo):
Toma la oración de entrada (ej. "Hola amigo, ¿dónde estás?" o "Mi nombre es Luis").
Limpia signos de puntuación, busca coincidencias de frases y palabras en el catálogo de 46 señas conversacionales (con lematización/sinónimos en español: "quiero/queremos/deseo"
→
→ S_QUERER).
Si una palabra no existe como seña léxica (por ejemplo, un nombre propio como "Luis" o un término técnico), el motor la descompone automáticamente letra por letra en el Abecedario LSC ([L_L, L_U, L_I, L_S]).
Animador 3D Bimanual y Unimanual en Pantalla:
Utiliza interpolación cinemática suave (slerp/lerp a 30 FPS) sobre esqueletos 3D de 1 o 2 manos (con articulaciones anatómicas, volumen visual, código de color para mano dominante y mano base, y flechas de movimiento para señas dinámicas como J, Z, Ñ, S, Hola, ¿Cómo estás?).
Muestra simultáneamente:
El Modelo 3D de Manos ejecutando cada seña o letra de la frase.
Una Barra de Subtítulos Sincronizada que resalta en tiempo real qué palabra o letra de la frase se está articulando con las manos y su descripción biomecánica. 5. Pulido de la Detección Biomecánica y Cinemática

Para que las 27 letras del abecedario LSC y las 46 señas conversacionales se detecten sin ambigüedades ni falsos positivos, realizaremos mejoras profundas en el pipeline de visión:

5.1 Mejoras en backend/hand_tracking.py y backend/normalizer.py
Clasificación de 3 Estados por Dedo (EXTENDED, HOOK/CURVED, FOLDED):
Actualmente cada dedo es solo booleano (True/False). Añadiremos el estado intermedio hook (curvatura entre
55
∘
55
∘
y
125
∘
125
∘
) indispensable para distinguir:
Letra C y E (4 dedos en gancho/arco) vs. B (4 dedos rectos) vs. A (puño cerrado).
Letra X (solo dedo índice en gancho) vs. D (índice recto arriba).
Vector de Orientación de Dedos en el Espacio (finger_direction: UP, DOWN, SIDE, CAMERA):
Calculado con el vector unitario desde el nudillo base (INDEX_MCP [5]) hasta la punta (INDEX_TIP [8]).
Permite separar con 100% de exactitud:
V (índice+medio apuntando UP) vs. H (índice+medio apuntando SIDE) vs. N / Ñ (índice+medio apuntando DOWN).
W (3 dedos UP) vs. M (3 dedos DOWN).
D (índice UP) vs. G (índice SIDE) vs. P (índice DOWN).
Métricas de Separación (spread) y Cruce (cross) Inter-digital:
index_middle_spread: Distancia normalizada entre INDEX_TIP [8] y MIDDLE_TIP [12] para diferenciar V (abiertos en V) de U/B/H/N (juntos) y R (cruzados en torsión).
thumb_contact_finger: Identifica cuál dedo toca la punta del pulgar (THUMB_TIP [4]) para separar D (pulgar toca medio/anular), F (pulgar apoya en índice), O (pulgar toca todos formando aro) y Q (racimo superior).
Nuevos Patrones Bimanuales en normalize_multi_hand_landmarks:
roof_triangle_casa: Puntas de índices y medios de ambas manos tocándose en ángulo
∧
∧ para S_CASA.
wrists_crossed_or_tapping: Muñecas/puños próximos para S_TRABAJAR y S_AMIGO.
book_open_estudiar: Una mano plana horizontal y la otra encima para S_ESTUDIAR.
5.2 Mejoras en backend/motion_analyzer.py
Reconocedor de Trazos en el Aire (Air-Stroke Trajectory Classifier):
Analiza la ventana de los últimos 18–24 fotogramas de INDEX_TIP [8] y PINKY_TIP [20] para detectar las firmas cinemáticas de:
Letra J: Descenso vertical (dy > 0.06) seguido de giro ascendente lateral con meñique activo.
Letra Z: Tres segmentos direccionales o 2 inversiones horizontales combinadas con descenso diagonal (rev_x >= 2 y net_dy > 0.04).
Letra S: Oscilación horizontal suave mientras el dedo índice desciende (rev_x >= 2, net_dy > 0.05 con solo index=True).
Letra Ñ: Oscilación horizontal (is_oscillating_x=True) con dedos apuntando hacia abajo (DOWN). 6. Archivos a Modificar y Crear
Archivo Cambios Planificados
backend/hand_tracking.py Añadir detección de estado en gancho (finger_hooks), dirección 3D de apuntado (UP, DOWN, SIDE), apertura inter-digital (spread) y cruce (is_crossed_r).
backend/normalizer.py Exponer las nuevas métricas geométricas finas para el abecedario LSC y los nuevos patrones inter-manuales (roof_triangle, wrists_together, hand_to_mouth_zone).
backend/motion_analyzer.py Añadir reconocimiento de trazos dinámicos de letras (trace_J, trace_Z, trace_S, wave_N_tilde) y movimientos conversacionales.
backend/lsc_alphabet.py (Nuevo) Catálogo completo de las 27 letras del Abecedario LSC (A–Z + Ñ), sus poses anatómicas 3D canónicas (21x3), su clasificador geométrico/cinemático de alta precisión y generador de trayectorias para el Avatar 3D.
backend/conversation_engine.py Expandir CONVERSATIONAL_SIGNS_CATALOG a +45 señas en 7 categorías, integrar el sub-modo de deletreo dactilológico LSC, el Motor Gramatical de Conjugación en Español, y el Traductor Inverso (Frase/Texto
→
→ Secuencia de Poses 3D de Manos).
backend/pipeline.py Integrar el selector de sub-modo (CONVERSATION / ALPHABET_LSC / HYBRID), conectar el HandTracker con filtro
1
€
1€ en tiempo real y soportar la reproducción animada de frases en el Modelo 3D de Manos (unimanual y bimanual).
main.py Nuevos endpoints REST y comandos WebSocket: /api/conversation/translate_to_hands (envía una frase y activa el modelo 3D de manos), /api/alphabet/catalog y selector de modo dactilológico.
static/index.html y static/mobile.html Añadir el panel interactivo "Intérprete de Frases con Modelo de Manos 3D", el selector de Abecedario LSC (A–Z + Ñ) con guía visual interactiva de la lámina colombiana, y controles de deletreo + conversación fluida.
test_pipeline.py Suite de pruebas automatizadas verificando las 27 letras del abecedario LSC, las señas conversacionales, la conjugación de oraciones y la traducción inversa de frases al modelo 3D de manos. 7. Plan de Verificación y Pruebas
Prueba Unitaria de las 27 Letras LSC: Verificar que cada pose canónica y sus variaciones con ruido de A a Z (incluyendo Ñ) sean clasificadas con confianza
≥
0.90
≥0.90.
Prueba de Conversación Completa (Señas
→
→ Texto/Voz): Simular y probar secuencias conversacionales reales (ej. HOLA + COMO_ESTAS, YO + ESTUDIAR + UNIVERSIDAD, deletreo de nombres con el abecedario LSC) y comprobar la generación de texto fluido y salida TTS.
Prueba de Traducción Inversa (Texto/Voz
→
→ Modelo de Manos 3D): Ingresar frases en español (por voz o texto) y verificar que el modelo de manos 3D reproduzca secuencialmente cada seña conversacional y deletree en LSC las palabras fuera del diccionario mostrando el texto sincronizado.
