"""
Motor de Traducción Conversacional Bidireccional de Lenguaje de Señas — SignBridge Extended v3.0.

Gestiona:
1. Catálogo de señas conversacionales bimanuales y unimanuales.
2. Buffer dinámico de tokens/glosas para construcción de oraciones continuas.
3. Clasificación heurística y biomecánica bimanual (contacto, orientación, gestos duales).
4. Historial conversacional bidireccional (Persona Sorda [Señas/TTS] <-> Oyente [Micrófono/STT]).
5. Fusión y síntesis de oraciones para Text-to-Speech (TTS).
"""

from __future__ import annotations
import time
from datetime import datetime
from typing import Dict, Any, List, Optional
import numpy as np


CONVERSATIONAL_SIGNS_CATALOG: Dict[str, Dict[str, Any]] = {
    "S_HOLA": {
        "id": "S_HOLA",
        "label": "Hola",
        "emoji": "👋",
        "category": "Cortesía",
        "bimanual": False,
        "default_phrase": "Hola, un gusto saludarte.",
        "description": "Mano abierta oscilando suavemente o palma al frente en saludo.",
        "color": "#00F0FF",
    },
    "S_GRACIAS": {
        "id": "S_GRACIAS",
        "label": "Gracias",
        "emoji": "🙏",
        "category": "Cortesía",
        "bimanual": False,
        "default_phrase": "Muchas gracias por tu ayuda.",
        "description": "Mano abierta desde el mentón proyectándose hacia adelante o palmas unidas.",
        "color": "#10B981",
    },
    "S_POR_FAVOR": {
        "id": "S_POR_FAVOR",
        "label": "Por favor",
        "emoji": "🤲",
        "category": "Cortesía",
        "bimanual": True,
        "default_phrase": "Por favor, te lo agradezco.",
        "description": "Ambas palmas abiertas juntas frente al pecho o frotándose con respeto.",
        "color": "#F59E0B",
    },
    "S_MUCHO_GUSTO": {
        "id": "S_MUCHO_GUSTO",
        "label": "Mucho gusto",
        "emoji": "🤝",
        "category": "Cortesía",
        "bimanual": True,
        "default_phrase": "Mucho gusto en conocerte y hablar contigo.",
        "description": "Ambas manos abiertas cruzándose o tocándose en el centro.",
        "color": "#06B6D4",
    },
    "S_ADIOS": {
        "id": "S_ADIOS",
        "label": "Adiós",
        "emoji": "👋",
        "category": "Cortesía",
        "bimanual": False,
        "default_phrase": "Hasta luego, que tengas un excelente día.",
        "description": "Mano dominante en alto despidiéndose.",
        "color": "#6366F1",
    },
    "S_SI": {
        "id": "S_SI",
        "label": "Sí / De acuerdo",
        "emoji": "👍",
        "category": "Respuestas",
        "bimanual": False,
        "default_phrase": "Sí, estoy de acuerdo con eso.",
        "description": "Dedo índice vertical o puño afirmativo con pulgar arriba.",
        "color": "#10B981",
    },
    "S_NO": {
        "id": "S_NO",
        "label": "No / Negación",
        "emoji": "👎",
        "category": "Respuestas",
        "bimanual": False,
        "default_phrase": "No, no estoy de acuerdo / No es posible.",
        "description": "Dedo índice y pulgar en L o gesto de negación.",
        "color": "#F43F5E",
    },
    "S_BIEN": {
        "id": "S_BIEN",
        "label": "Bien / Excelente",
        "emoji": "✨",
        "category": "Respuestas",
        "bimanual": False,
        "default_phrase": "Me encuentro muy bien, todo excelente.",
        "description": "Seña de paz y victoria (índice y medio extendidos).",
        "color": "#00F0FF",
    },
    "S_MAL": {
        "id": "S_MAL",
        "label": "Mal / Regular",
        "emoji": "⚠️",
        "category": "Respuestas",
        "bimanual": False,
        "default_phrase": "No me siento bien / Hay un inconveniente.",
        "description": "Mano plana horizontal oscilando suavemente con pulgar abajo.",
        "color": "#F59E0B",
    },
    "S_ENTENDIDO": {
        "id": "S_ENTENDIDO",
        "label": "Entendido",
        "emoji": "💡",
        "category": "Respuestas",
        "bimanual": False,
        "default_phrase": "He comprendido el mensaje con claridad.",
        "description": "Puño con pulgar arriba junto al pecho o toque en la sien.",
        "color": "#3B82F6",
    },
    "S_COMO_ESTAS": {
        "id": "S_COMO_ESTAS",
        "label": "¿Cómo estás?",
        "emoji": "❓",
        "category": "Preguntas",
        "bimanual": True,
        "default_phrase": "¿Cómo te encuentras el día de hoy?",
        "description": "Ambas manos abiertas sobre el pecho abriéndose con expresión interrogativa.",
        "color": "#8B5CF6",
    },
    "S_QUE": {
        "id": "S_QUE",
        "label": "¿Qué?",
        "emoji": "🧐",
        "category": "Preguntas",
        "bimanual": True,
        "default_phrase": "¿Qué necesitas o qué sucede?",
        "description": "Ambas palmas abiertas hacia arriba oscilando suavemente.",
        "color": "#A855F7",
    },
    "S_DONDE": {
        "id": "S_DONDE",
        "label": "¿Dónde?",
        "emoji": "📍",
        "category": "Preguntas",
        "bimanual": False,
        "default_phrase": "¿Dónde se encuentra ese lugar?",
        "description": "Dedo índice señalando con movimiento interrogativo.",
        "color": "#EC4899",
    },
    "S_DESPACIO": {
        "id": "S_DESPACIO",
        "label": "Más despacio",
        "emoji": "⏳",
        "category": "Preguntas",
        "bimanual": True,
        "default_phrase": "Por favor habla o señálame un poco más despacio.",
        "description": "Ambas palmas abiertas horizontales descendiendo con calma.",
        "color": "#14B8A6",
    },
    "S_AYUDA": {
        "id": "S_AYUDA",
        "label": "Ayuda / SOS",
        "emoji": "🆘",
        "category": "Emergencia",
        "bimanual": True,
        "default_phrase": "Necesito ayuda o asistencia prioritaria, por favor.",
        "description": "Puño dominante sobre palma no dominante horizontal, o Shaka / 3 dedos extendidos.",
        "color": "#EF4444",
    },
    "S_MEDICO": {
        "id": "S_MEDICO",
        "label": "Médico / Dolor",
        "emoji": "🩺",
        "category": "Emergencia",
        "bimanual": True,
        "default_phrase": "Necesito atención médica o tengo dolor.",
        "description": "Dedos índice y medio tocando la muñeca o zona de pulsaciones.",
        "color": "#F43F5E",
    },
    "S_ESPERA": {
        "id": "S_ESPERA",
        "label": "Espera un momento",
        "emoji": "✋",
        "category": "Control",
        "bimanual": True,
        "default_phrase": "Por favor espera un momento mientras respondo.",
        "description": "Ambas palmas abiertas mirando hacia el frente empujando el aire.",
        "color": "#EAB308",
    },
    "S_CONTINUAR": {
        "id": "S_CONTINUAR",
        "label": "Continuar",
        "emoji": "▶️",
        "category": "Control",
        "bimanual": False,
        "default_phrase": "Adelante, podemos continuar con la conversación.",
        "description": "Dedos índice y medio extendidos (seña de paz).",
        "color": "#10B981",
    },
}


class ConversationEngine:
    """
    Motor central de traducción y conversación bidireccional:
    - Persona Sorda (Señas bimanuales/unimanuales -> Frases acumuladas -> Text-to-Speech)
    - Oyente (Micrófono Speech-to-Text -> Subtítulos / Transcripción accesible)
    """

    def __init__(self):
        self.active_tokens: List[Dict[str, Any]] = []
        self.current_sentence: str = ""
        self.chat_history: List[Dict[str, Any]] = []
        self.last_added_sign_id: Optional[str] = None
        self.last_added_ts: float = 0.0
        self.cooldown_sec: float = 1.15
        self.gesture_released: bool = True  # Requiere soltar/neutralizar postura para repetir la misma seña
        self.max_tokens: int = 12           # Límite máximo para mantener el banner compacto y ligero
        self.tts_queue: List[str] = []

        # Mensaje de bienvenida inicial en el chat conversacional
        self._init_chat()

    def _init_chat(self) -> None:
        self.chat_history = [
            {
                "id": "msg_0",
                "sender": "SYSTEM",
                "sender_label": "SignBridge v3.0",
                "text": "Traductor Conversacional Bidireccional Activo. La persona sorda puede comunicarse por señas (1 o 2 manos) y el oyente respondiendo por voz.",
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "sign_ids": [],
            }
        ]

    def classify_bimanual_gesture(
        self,
        multi_hand: Dict[str, Any],
        motion: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Evalúa relaciones inter-manuales y dinámicas cinemáticas si hay 2 manos en escena
        para reconocer señas bimanuales canónicas (Ayuda, Por favor, Espera, ¿Cómo estás?,
        ¿Qué?, ¿Dónde?, Mucho gusto, Más despacio, Médico).
        """
        if not multi_hand or multi_hand.get("hands_count", 0) < 2:
            return None

        inter = multi_hand.get("inter_hand")
        if not inter:
            return None

        p0 = multi_hand["primary"]
        p1 = multi_hand["secondary"]
        f0 = p0["telemetry"]["fingers"]
        f1 = p1["telemetry"]["fingers"]

        b_motion = motion.get("bimanual", {}) if motion else {}
        p_motion = motion.get("primary", {}) if motion else {}
        s_motion = motion.get("secondary", {}) if motion else {}

        # 1. Puño sobre palma -> AYUDA / ASISTENCIA SOS (Seña bimanual oficial)
        if inter.get("fist_on_palm_help"):
            return {
                "sign_id": "S_AYUDA",
                "confidence": 0.98,
                "note": "Bimanual: Puño sobre palma plana",
                "is_dynamic": False,
            }

        # 2. Dedo índice tocando la muñeca de la otra mano -> MÉDICO / DOLOR
        wrist_dist = inter.get("wrist_dist", 1.0)
        idx_tip_dist = inter.get("index_tip_dist", 1.0)
        index_on_wrist = inter.get("index_on_wrist", False)
        if index_on_wrist or (wrist_dist < 0.28 and (f0["index"] or f1["index"]) and idx_tip_dist < 0.28):
            return {
                "sign_id": "S_MEDICO",
                "confidence": 0.96,
                "note": "Bimanual: Toque de pulso/muñeca",
                "is_dynamic": False,
            }

        # 3. Ambas palmas abiertas descendiendo con calma -> MÁS DESPACIO (S_DESPACIO)
        if (f0["index"] and f0["middle"] and f1["index"] and f1["middle"]) and (
            b_motion.get("both_moving_down") or
            (p_motion.get("is_moving_down") and s_motion.get("is_moving_down"))
        ):
            return {
                "sign_id": "S_DESPACIO",
                "confidence": 0.97,
                "note": "Bimanual dinámico: Palmas descendiendo con calma",
                "is_dynamic": True,
            }

        # 4. Ambas manos abriéndose hacia los lados desde el centro -> ¿CÓMO ESTÁS? (S_COMO_ESTAS)
        if inter.get("both_question") and b_motion.get("is_diverging"):
            return {
                "sign_id": "S_COMO_ESTAS",
                "confidence": 0.97,
                "note": "Bimanual dinámico: Manos abriéndose hacia los costados",
                "is_dynamic": True,
            }

        # 5. Ambas palmas abiertas hacia arriba oscilando suavemente -> ¿QUÉ? (S_QUE)
        if inter.get("both_question") and (
            b_motion.get("both_oscillating") or
            p_motion.get("is_oscillating_x") or
            s_motion.get("is_oscillating_x") or
            p_motion.get("is_oscillating_y") or
            s_motion.get("is_oscillating_y")
        ):
            return {
                "sign_id": "S_QUE",
                "confidence": 0.96,
                "note": "Bimanual dinámico: Palmas abiertas oscilando",
                "is_dynamic": True,
            }

        # 6. Índices de ambas manos apuntando hacia los costados en búsqueda -> ¿DÓNDE? (S_DONDE)
        if (f0["index"] and not f0["middle"] and not f0["ring"] and not f0["pinky"]) and \
           (f1["index"] and not f1["middle"] and not f1["ring"] and not f1["pinky"]):
            return {
                "sign_id": "S_DONDE",
                "confidence": 0.96,
                "note": "Bimanual: Índices señalando a los lados",
                "is_dynamic": bool(p_motion.get("is_oscillating_x") or s_motion.get("is_oscillating_x")),
            }

        # 7. Manos convergiendo desde los costados hacia el centro -> MUCHO GUSTO (S_MUCHO_GUSTO)
        if b_motion.get("is_converging") and inter.get("hands_touching"):
            return {
                "sign_id": "S_MUCHO_GUSTO",
                "confidence": 0.96,
                "note": "Bimanual dinámico: Manos encontrándose en el centro",
                "is_dynamic": True,
            }

        # 8. Palmas juntas frente al pecho -> POR FAVOR (S_POR_FAVOR)
        if inter.get("palms_together"):
            return {
                "sign_id": "S_POR_FAVOR",
                "confidence": 0.96,
                "note": "Bimanual: Palmas unidas frente al pecho",
                "is_dynamic": False,
            }

        # 9. Ambas manos abiertas hacia arriba estáticas -> ¿CÓMO ESTÁS? (Fallback de postura)
        if inter.get("both_question"):
            return {
                "sign_id": "S_COMO_ESTAS",
                "confidence": 0.94,
                "note": "Bimanual: Palmas abiertas hacia arriba",
                "is_dynamic": False,
            }

        # 10. Ambas manos abiertas hacia el frente empujando el aire -> ESPERA / PAUSA (S_ESPERA)
        if inter.get("both_open_forward"):
            return {
                "sign_id": "S_ESPERA",
                "confidence": 0.95,
                "note": "Bimanual: Ambas palmas abiertas al frente",
                "is_dynamic": False,
            }

        return None

    def get_sign_meta(self, sign_id: str) -> Dict[str, Any]:
        """Obtiene la metadata de una seña o un valor por defecto."""
        return CONVERSATIONAL_SIGNS_CATALOG.get(sign_id, {
            "id": sign_id,
            "label": sign_id,
            "emoji": "💬",
            "category": "General",
            "default_phrase": sign_id,
            "color": "#00F0FF",
        })

    def classify_unimanual_gesture(
        self,
        multi_hand: Dict[str, Any],
        motion: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Clasifica señas unimanuales integrando cinemática y análisis geométrico 3D:
        - Mano abierta oscilando lateralmente: S_ADIOS (👋 Adiós)
        - Mano abierta estática / frente: S_HOLA (👋 Hola)
        - Mano abierta descendiendo suavemente: S_REPETIR (🔄 Repetir)
        - Dedo índice o L oscilando lateralmente: S_NO (👆 No negación)
        - Dedo índice oscilando verticalmente: S_SI (☝️ Sí asentimiento)
        - Pulgar arriba: S_BIEN (👍 Bien / OK)
        - Pulgar abajo o mano oscilando hacia abajo: S_MAL (👎 Mal)
        - Paz / Victoria: S_CONTINUAR (✌️ Continuar)
        - Puño cerrado: S_ENTENDIDO (✊ Entendido)
        - Shaka / 3 Dedos: S_AYUDA (🆘 Ayuda SOS)
        """
        if not multi_hand or not multi_hand.get("primary"):
            return None

        primary = multi_hand["primary"]
        telem = primary.get("telemetry", {})
        fingers = telem.get("fingers", {})
        pts = primary.get("landmarks")

        thumb = fingers.get("thumb", False)
        index = fingers.get("index", False)
        middle = fingers.get("middle", False)
        ring = fingers.get("ring", False)
        pinky = fingers.get("pinky", False)

        p_motion = motion.get("primary", {}) if motion else {}
        is_waving_x = bool(p_motion.get("is_oscillating_x"))
        is_waving_y = bool(p_motion.get("is_oscillating_y"))
        is_moving_down = bool(p_motion.get("is_moving_down"))

        # 1. MANO ABIERTA (4 o 5 dedos extendidos)
        if index and middle and ring and pinky:
            # 1.1 Si la mano abierta oscila lateralmente en vaivén -> ADIÓS (S_ADIOS)
            if is_waving_x:
                return {
                    "sign_id": "S_ADIOS",
                    "confidence": 0.98,
                    "note": "Unimanual dinámico: Mano abierta oscilando en despedida",
                    "is_dynamic": True,
                }
            # 1.2 Si la mano abierta desciende suavemente -> REPETIR (S_REPETIR)
            if is_moving_down:
                return {
                    "sign_id": "S_REPETIR",
                    "confidence": 0.96,
                    "note": "Unimanual dinámico: Mano abierta descendiendo suavemente",
                    "is_dynamic": True,
                }
            # 1.3 Mano abierta estática / saludo al frente -> HOLA (S_HOLA)
            return {
                "sign_id": "S_HOLA",
                "confidence": 0.96,
                "note": "Unimanual: Palma abierta en saludo (Hola)",
                "is_dynamic": False,
            }

        # 2. PISTOLA / L (Índice y pulgar en L) o DEDO ÍNDICE SOLO
        if index and not middle and not ring and not pinky:
            # 2.1 Si hay oscilación horizontal (sacudida lateral de 'no') -> S_NO
            if is_waving_x:
                return {
                    "sign_id": "S_NO",
                    "confidence": 0.98,
                    "note": "Unimanual dinámico: Dedo índice oscilando en negación",
                    "is_dynamic": True,
                }
            # 2.2 Si hay oscilación vertical (asentimiento de 'sí') -> S_SI
            if is_waving_y:
                return {
                    "sign_id": "S_SI",
                    "confidence": 0.98,
                    "note": "Unimanual dinámico: Dedo índice asintiendo verticalmente",
                    "is_dynamic": True,
                }
            # 2.3 Postura L estática -> S_NO
            if thumb:
                return {
                    "sign_id": "S_NO",
                    "confidence": 0.96,
                    "note": "Unimanual: Índice y pulgar en L (No)",
                    "is_dynamic": False,
                }
            # 2.4 Dedo índice vertical estático -> S_SI
            return {
                "sign_id": "S_SI",
                "confidence": 0.96,
                "note": "Unimanual: Solo índice vertical (Sí)",
                "is_dynamic": False,
            }

        # 3. PULGAR ARRIBA (BIEN) / PULGAR ABAJO (MAL)
        # Evaluamos la posición vertical real de la punta del pulgar (Landmark 4) vs Muñeca (Landmark 0)
        if thumb and not index and not middle and not ring and not pinky and pts is not None and len(pts) >= 5:
            # En coordenadas de imagen: Y=0 es ARRIBA, Y=1 es ABAJO
            thumb_y = pts[4][1]
            wrist_y = pts[0][1]

            if thumb_y < (wrist_y - 0.05):
                return {
                    "sign_id": "S_BIEN",
                    "confidence": 0.97,
                    "note": "Unimanual: Pulgar arriba firme (Bien / OK)",
                    "is_dynamic": False,
                }
            elif thumb_y > (wrist_y + 0.04):
                return {
                    "sign_id": "S_MAL",
                    "confidence": 0.97,
                    "note": "Unimanual: Pulgar apuntando hacia abajo (Mal)",
                    "is_dynamic": False,
                }
            else:
                return {
                    "sign_id": "S_BIEN",
                    "confidence": 0.92,
                    "note": "Unimanual: Pulgar extendido (Bien)",
                    "is_dynamic": False,
                }

        # 4. MANO HORIZONTAL OSCILANDO / TILT (MAL / REGULAR)
        if is_waving_x and not index and not middle and thumb:
            return {
                "sign_id": "S_MAL",
                "confidence": 0.95,
                "note": "Unimanual dinámico: Bamboleo horizontal de desacuerdo",
                "is_dynamic": True,
            }

        # 5. PAZ / VICTORIA (Índice + Medio) -> CONTINUAR (S_CONTINUAR)
        if index and middle and not ring and not pinky:
            return {
                "sign_id": "S_CONTINUAR",
                "confidence": 0.96,
                "note": "Unimanual: Paz / Victoria (Continuar)",
                "is_dynamic": False,
            }

        # 6. PUÑO CERRADO (0 dedos) -> ENTENDIDO / ALTO (S_ENTENDIDO)
        if not index and not middle and not ring and not pinky and not thumb:
            return {
                "sign_id": "S_ENTENDIDO",
                "confidence": 0.97,
                "note": "Unimanual: Puño cerrado (Entendido)",
                "is_dynamic": False,
            }

        # 7. SHAKA / 3 DEDOS -> AYUDA SOS (S_AYUDA)
        if (index and middle and ring and not pinky) or (thumb and pinky and not index and not middle and not ring):
            return {
                "sign_id": "S_AYUDA",
                "confidence": 0.96,
                "note": "Unimanual: Señal Shaka o 3 dedos (Ayuda)",
                "is_dynamic": False,
            }

        return None

    def map_legacy_gesture_to_sign(self, gid: str) -> Optional[str]:
        """Mapea los gestos de 1 mano del modelo anterior a señas conversacionales."""
        mapping = {
            "G1": "S_CONTINUAR",  # Paz / Continuar
            "G2": "S_SI",         # Índice arriba -> Sí
            "G3": "S_ENTENDIDO",   # Puño -> Entendido / Alto
            "G4": "S_AYUDA",       # Shaka / 3 Dedos -> Ayuda
            "G5": "S_NO",          # Pistola L -> No / Cancelar
        }
        return mapping.get(gid)

    def process_frame_sign(
        self,
        raw_gesture_id: str,
        confidence: float,
        multi_hand: Dict[str, Any],
        is_triggered: bool,
        motion: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Evalúa el fotograma para la traducción conversacional:
        Prioridad 1: Señas bimanuales (si hay 2 manos)
        Prioridad 2: Señas unimanuales (si hay 1 mano detectada: Hola, Adiós, Bien, Mal, etc.)
        Prioridad 3: Mapeo de gestos canónicos G1..G5
        """
        sign_id = None
        sign_meta = None
        source_note = ""

        # Comprobar señas bimanuales si hay 2 manos en escena
        bimanual_match = self.classify_bimanual_gesture(multi_hand, motion=motion)
        if bimanual_match:
            sign_id = bimanual_match["sign_id"]
            confidence = max(confidence, bimanual_match["confidence"])
            source_note = bimanual_match["note"]
        else:
            # Comprobar señas unimanuales biomecánicas y cinemáticas
            unimanual_match = self.classify_unimanual_gesture(multi_hand, motion=motion)
            if unimanual_match:
                sign_id = unimanual_match["sign_id"]
                confidence = max(confidence, unimanual_match["confidence"])
                source_note = unimanual_match["note"]
            elif raw_gesture_id and raw_gesture_id in CONVERSATIONAL_SIGNS_CATALOG:
                sign_id = raw_gesture_id
                source_note = "Seña directa"
            elif raw_gesture_id and raw_gesture_id != "G0":
                sign_id = self.map_legacy_gesture_to_sign(raw_gesture_id)
                source_note = f"Mapeo de {raw_gesture_id}"

        if not sign_id or sign_id not in CONVERSATIONAL_SIGNS_CATALOG:
            self.gesture_released = True
            return None

        # Si el usuario cambió a una seña distinta a la última agregada
        if sign_id != self.last_added_sign_id:
            self.gesture_released = True

        sign_meta = CONVERSATIONAL_SIGNS_CATALOG[sign_id]

        # Si el gesto ha superado el buffer temporal de estabilización
        now = time.perf_counter()
        # Prevención de repetición continua: si es la misma seña consecutiva (ej. mantener mano en Hola),
        # solo se agrega si el usuario soltó/relajó la mano primero (gesture_released == True)
        # o tras una retención intencional deliberada (> 3.2s)
        can_trigger = False
        if is_triggered and (now - self.last_added_ts) > self.cooldown_sec:
            if sign_id != self.last_added_sign_id or self.gesture_released or (now - self.last_added_ts) > 3.2:
                can_trigger = True

        if can_trigger:
            self.last_added_ts = now
            self.last_added_sign_id = sign_id
            self.gesture_released = False
            token_entry = {
                "sign_id": sign_id,
                "label": sign_meta["label"],
                "emoji": sign_meta["emoji"],
                "default_phrase": sign_meta["default_phrase"],
                "timestamp": datetime.now().strftime("%H:%M:%S"),
            }
            self.active_tokens.append(token_entry)

            # Acotar buffer para que no crezca desmedidamente (máximo 12 tokens)
            if len(self.active_tokens) > self.max_tokens:
                self.active_tokens = self.active_tokens[-self.max_tokens:]

            self._update_sentence_from_tokens()

            # Encolar para pronunciación automática (TTS) de la palabra añadida
            self.tts_queue.append(sign_meta["label"])

        return {
            "sign_id": sign_id,
            "label": sign_meta["label"],
            "emoji": sign_meta["emoji"],
            "category": sign_meta["category"],
            "default_phrase": sign_meta["default_phrase"],
            "confidence": round(confidence, 3),
            "source_note": source_note,
        }

    def _update_sentence_from_tokens(self) -> None:
        """Construye la oración en español a partir de las glosas acumuladas en el buffer."""
        if not self.active_tokens:
            self.current_sentence = ""
            return

        # Concatenación inteligente con puntuación y conectores
        labels = [t["label"] for t in self.active_tokens]
        self.current_sentence = " ".join(labels)

    def commit_sentence(self, custom_phrase: Optional[str] = None) -> Dict[str, Any]:
        """
        Finaliza la oración en construcción generada por la persona sorda,
        la agrega al historial conversacional de chat y solicita reproducción TTS.
        """
        phrase = custom_phrase or self.current_sentence
        if not phrase and self.active_tokens:
            phrase = " ".join(t["label"] for t in self.active_tokens)

        if not phrase:
            return {"committed": False, "message": "Buffer vacío"}

        sign_ids = [t["sign_id"] for t in self.active_tokens]
        msg_id = f"msg_{len(self.chat_history)}"
        ts = datetime.now().strftime("%H:%M:%S")

        entry = {
            "id": msg_id,
            "sender": "DEAF",
            "sender_label": "Persona Sorda (Señas)",
            "text": phrase,
            "timestamp": ts,
            "sign_ids": sign_ids,
        }
        self.chat_history.append(entry)

        # Encolar la frase completa para TTS
        self.tts_queue.append(phrase)

        # Limpiar el buffer de construcción activo
        self.active_tokens.clear()
        self.current_sentence = ""
        self.last_added_sign_id = None
        self.gesture_released = True

        return {"committed": True, "entry": entry}

    def add_hearing_message(self, text: str) -> Dict[str, Any]:
        """
        Registra un mensaje de voz transcripto (STT) pronunciado por el oyente
        para que la persona sorda pueda leerlo en pantalla grande inmediatamente.
        """
        clean_text = text.strip()
        if not clean_text:
            return {"added": False}

        msg_id = f"msg_{len(self.chat_history)}"
        ts = datetime.now().strftime("%H:%M:%S")

        entry = {
            "id": msg_id,
            "sender": "HEARING",
            "sender_label": "Oyente (Voz)",
            "text": clean_text,
            "timestamp": ts,
            "sign_ids": [],
        }
        self.chat_history.append(entry)
        return {"added": True, "entry": entry}

    def backspace(self) -> Dict[str, Any]:
        """Elimina el último token del buffer."""
        if self.active_tokens:
            removed = self.active_tokens.pop()
            self._update_sentence_from_tokens()
            self.last_added_sign_id = self.active_tokens[-1]["sign_id"] if self.active_tokens else None
            self.gesture_released = True
            return {"removed": removed, "remaining": len(self.active_tokens)}
        return {"removed": None, "remaining": 0}

    def clear_tokens(self) -> None:
        """Limpia el buffer de construcción de oraciones."""
        self.active_tokens.clear()
        self.current_sentence = ""
        self.last_added_sign_id = None
        self.gesture_released = True

    def pop_tts_queue(self) -> Optional[str]:
        """Obtiene y limpia el próximo mensaje a pronunciar por el sintetizador de voz."""
        if self.tts_queue:
            return self.tts_queue.pop(0)
        return None

    def get_state(self) -> Dict[str, Any]:
        """Retorna el estado completo del motor conversacional para el cliente web/móvil."""
        return {
            "active_tokens": self.active_tokens,
            "current_sentence": self.current_sentence,
            "token_count": len(self.active_tokens),
            "chat_history": self.chat_history[-15:],  # Últimos 15 mensajes
            "catalog": CONVERSATIONAL_SIGNS_CATALOG,
        }

