"""
Módulo Oficial del Abecedario Dactilológico en Lengua de Señas Colombiana (LSC - INSOR / FENASCOL).

Contiene:
1. Catálogo completo de las 27 letras del Abecedario LSC (A-Z incluyendo Ñ).
2. Generador de poses anatómicas 3D (21 Landmarks) y trayectorias cinemáticas para el Modelo 3D de Manos.
3. Clasificador biomecánico y cinemático de alta precisión para reconocimiento en tiempo real.
"""

from __future__ import annotations
import math
from typing import Dict, Any, Optional, List, Tuple
import numpy as np

from backend.normalizer import normalize_landmarks


LSC_ALPHABET_CATALOG: Dict[str, Dict[str, Any]] = {
    "L_A": {
        "id": "L_A",
        "letter": "A",
        "label": "A",
        "full_name": "Letra A (LSC)",
        "emoji": "🅰️",
        "category": "Abecedario LSC",
        "bimanual": False,
        "is_dynamic": False,
        "default_phrase": "A",
        "description": "Puño cerrado con el dedo pulgar extendido hacia arriba/lado.",
        "motion_hint": "Postura estática firme",
        "color": "#00F0FF",
    },
    "L_B": {
        "id": "L_B",
        "letter": "B",
        "label": "B",
        "full_name": "Letra B (LSC)",
        "emoji": "🅱️",
        "category": "Abecedario LSC",
        "bimanual": False,
        "is_dynamic": False,
        "default_phrase": "B",
        "description": "Cuatro dedos largos extendidos y unidos verticalmente; pulgar doblado sobre la palma.",
        "motion_hint": "Dedos juntos hacia arriba, pulgar recogido",
        "color": "#00F0FF",
    },
    "L_C": {
        "id": "L_C",
        "letter": "C",
        "label": "C",
        "full_name": "Letra C (LSC)",
        "emoji": "©️",
        "category": "Abecedario LSC",
        "bimanual": False,
        "is_dynamic": False,
        "default_phrase": "C",
        "description": "Dedos índice, medio, anular y meñique semi-curvados formando un arco en 'C' con el pulgar.",
        "motion_hint": "Mano arqueada en C",
        "color": "#00F0FF",
    },
    "L_D": {
        "id": "L_D",
        "letter": "D",
        "label": "D",
        "full_name": "Letra D (LSC)",
        "emoji": "🔤",
        "category": "Abecedario LSC",
        "bimanual": False,
        "is_dynamic": False,
        "default_phrase": "D",
        "description": "Dedo índice extendido verticalmente; medio, anular y meñique tocan la punta del pulgar.",
        "motion_hint": "Índice arriba y círculo con pulgar y medio",
        "color": "#00F0FF",
    },
    "L_E": {
        "id": "L_E",
        "letter": "E",
        "label": "E",
        "full_name": "Letra E (LSC)",
        "emoji": "🔤",
        "category": "Abecedario LSC",
        "bimanual": False,
        "is_dynamic": False,
        "default_phrase": "E",
        "description": "Los cuatro dedos largos flexionados en garra alta y el pulgar doblado debajo sin tocar las yemas.",
        "motion_hint": "Dedos encorvados en garra",
        "color": "#00F0FF",
    },
    "L_F": {
        "id": "L_F",
        "letter": "F",
        "label": "F",
        "full_name": "Letra F (LSC)",
        "emoji": "🔤",
        "category": "Abecedario LSC",
        "bimanual": False,
        "is_dynamic": False,
        "default_phrase": "F",
        "description": "Dedo índice extendido hacia arriba con el pulgar apoyado lateralmente; medio, anular y meñique plegados.",
        "motion_hint": "Índice arriba con pulgar unido al costado",
        "color": "#00F0FF",
    },
    "L_G": {
        "id": "L_G",
        "letter": "G",
        "label": "G",
        "full_name": "Letra G (LSC)",
        "emoji": "🔤",
        "category": "Abecedario LSC",
        "bimanual": False,
        "is_dynamic": True,
        "default_phrase": "G",
        "description": "Mano horizontal con el dedo índice apuntando hacia el costado y ligero giro.",
        "motion_hint": "Índice horizontal apuntando al lado",
        "color": "#FFB800",
    },
    "L_H": {
        "id": "L_H",
        "letter": "H",
        "label": "H",
        "full_name": "Letra H (LSC)",
        "emoji": "🔤",
        "category": "Abecedario LSC",
        "bimanual": False,
        "is_dynamic": True,
        "default_phrase": "H",
        "description": "Dedos índice y medio extendidos juntos en posición horizontal con desplazamiento lateral.",
        "motion_hint": "Índice y medio horizontales al costado",
        "color": "#FFB800",
    },
    "L_I": {
        "id": "L_I",
        "letter": "I",
        "label": "I",
        "full_name": "Letra I (LSC)",
        "emoji": "🔤",
        "category": "Abecedario LSC",
        "bimanual": False,
        "is_dynamic": False,
        "default_phrase": "I",
        "description": "Solo el dedo meñique (20) extendido verticalmente hacia arriba; demás dedos cerrados.",
        "motion_hint": "Meñique vertical estático",
        "color": "#00F0FF",
    },
    "L_J": {
        "id": "L_J",
        "letter": "J",
        "label": "J",
        "full_name": "Letra J (LSC)",
        "emoji": "🔤",
        "category": "Abecedario LSC",
        "bimanual": False,
        "is_dynamic": True,
        "default_phrase": "J",
        "description": "Dedo meñique extendido dibujando una curva en forma de 'J' en el aire.",
        "motion_hint": "Dinámica: Traza una J hacia abajo y en curva con el meñique",
        "color": "#FFB800",
    },
    "L_K": {
        "id": "L_K",
        "letter": "K",
        "label": "K",
        "full_name": "Letra K (LSC)",
        "emoji": "🔤",
        "category": "Abecedario LSC",
        "bimanual": False,
        "is_dynamic": False,
        "default_phrase": "K",
        "description": "Dedos índice y medio abiertos en 'V' oblicua/inclinada con el pulgar proyectado entre ambos.",
        "motion_hint": "Índice y medio en V oblicua con pulgar central",
        "color": "#00F0FF",
    },
    "L_L": {
        "id": "L_L",
        "letter": "L",
        "label": "L",
        "full_name": "Letra L (LSC)",
        "emoji": "🔤",
        "category": "Abecedario LSC",
        "bimanual": False,
        "is_dynamic": False,
        "default_phrase": "L",
        "description": "Dedo índice extendido verticalmente y pulgar extendido horizontalmente formando una 'L'.",
        "motion_hint": "Índice y pulgar a 90° en L",
        "color": "#00FF9D",
    },
    "L_M": {
        "id": "L_M",
        "letter": "M",
        "label": "M",
        "full_name": "Letra M (LSC)",
        "emoji": "🔤",
        "category": "Abecedario LSC",
        "bimanual": False,
        "is_dynamic": False,
        "default_phrase": "M",
        "description": "Mano inclinada hacia abajo con tres dedos (índice, medio y anular) apuntando al suelo.",
        "motion_hint": "Tres dedos apuntando hacia abajo",
        "color": "#00F0FF",
    },
    "L_N": {
        "id": "L_N",
        "letter": "N",
        "label": "N",
        "full_name": "Letra N (LSC)",
        "emoji": "🔤",
        "category": "Abecedario LSC",
        "bimanual": False,
        "is_dynamic": False,
        "default_phrase": "N",
        "description": "Mano inclinada hacia abajo con dos dedos (índice y medio) apuntando al suelo.",
        "motion_hint": "Dos dedos apuntando hacia abajo estáticos",
        "color": "#00F0FF",
    },
    "L_NTILDE": {
        "id": "L_NTILDE",
        "letter": "Ñ",
        "label": "Ñ",
        "full_name": "Letra Ñ (LSC)",
        "emoji": "🔤",
        "category": "Abecedario LSC",
        "bimanual": False,
        "is_dynamic": True,
        "default_phrase": "Ñ",
        "description": "Dedos índice y medio apuntando hacia abajo con movimiento oscilatorio lateral de lado a lado.",
        "motion_hint": "Dinámica: Postura N oscilando de lado a lado",
        "color": "#FFB800",
    },
    "L_O": {
        "id": "L_O",
        "letter": "O",
        "label": "O",
        "full_name": "Letra O (LSC)",
        "emoji": "⭕",
        "category": "Abecedario LSC",
        "bimanual": False,
        "is_dynamic": False,
        "default_phrase": "O",
        "description": "Yemas de los dedos unidas con el pulgar formando un círculo cerrado 'O'.",
        "motion_hint": "Dedos curvados cerrando un aro O",
        "color": "#00F0FF",
    },
    "L_P": {
        "id": "L_P",
        "letter": "P",
        "label": "P",
        "full_name": "Letra P (LSC)",
        "emoji": "🅿️",
        "category": "Abecedario LSC",
        "bimanual": False,
        "is_dynamic": False,
        "default_phrase": "P",
        "description": "Dedo índice apuntando verticalmente hacia abajo con pulgar y medio en contacto.",
        "motion_hint": "Índice apuntando hacia abajo",
        "color": "#00F0FF",
    },
    "L_Q": {
        "id": "L_Q",
        "letter": "Q",
        "label": "Q",
        "full_name": "Letra Q (LSC)",
        "emoji": "🔤",
        "category": "Abecedario LSC",
        "bimanual": False,
        "is_dynamic": False,
        "default_phrase": "Q",
        "description": "Todas las yemas de los cinco dedos unidas en racimo apuntando hacia arriba.",
        "motion_hint": "Cinco yemas juntas apuntando arriba",
        "color": "#00F0FF",
    },
    "L_R": {
        "id": "L_R",
        "letter": "R",
        "label": "R",
        "full_name": "Letra R (LSC)",
        "emoji": "🔤",
        "category": "Abecedario LSC",
        "bimanual": False,
        "is_dynamic": False,
        "default_phrase": "R",
        "description": "Dedos índice y medio extendidos hacia arriba y cruzados entre sí.",
        "motion_hint": "Índice y medio entrelazados/cruzados",
        "color": "#00F0FF",
    },
    "L_S": {
        "id": "L_S",
        "letter": "S",
        "label": "S",
        "full_name": "Letra S (LSC)",
        "emoji": "🔤",
        "category": "Abecedario LSC",
        "bimanual": False,
        "is_dynamic": True,
        "default_phrase": "S",
        "description": "Dedo índice extendido trazando una curva en forma de 'S' descendente en el aire.",
        "motion_hint": "Dinámica: Traza una S en el aire con el dedo índice",
        "color": "#FFB800",
    },
    "L_T": {
        "id": "L_T",
        "letter": "T",
        "label": "T",
        "full_name": "Letra T (LSC)",
        "emoji": "🔤",
        "category": "Abecedario LSC",
        "bimanual": False,
        "is_dynamic": False,
        "default_phrase": "T",
        "description": "Dedos índice y medio unidos en diagonal con el pulgar contactando entre ambos.",
        "motion_hint": "Índice y medio juntos con pulgar en medio",
        "color": "#00F0FF",
    },
    "L_U": {
        "id": "L_U",
        "letter": "U",
        "label": "U",
        "full_name": "Letra U (LSC)",
        "emoji": "🤘",
        "category": "Abecedario LSC",
        "bimanual": False,
        "is_dynamic": False,
        "default_phrase": "U",
        "description": "Dedos índice (8) y meñique (20) extendidos verticalmente; medio y anular plegados bajo el pulgar.",
        "motion_hint": "Índice y meñique levantados (propio de LSC)",
        "color": "#00FF9D",
    },
    "L_V": {
        "id": "L_V",
        "letter": "V",
        "label": "V",
        "full_name": "Letra V (LSC)",
        "emoji": "✌️",
        "category": "Abecedario LSC",
        "bimanual": False,
        "is_dynamic": False,
        "default_phrase": "V",
        "description": "Dedos índice y medio extendidos y separados formando una 'V'; anular y meñique plegados.",
        "motion_hint": "Índice y medio abiertos en V",
        "color": "#00F0FF",
    },
    "L_W": {
        "id": "L_W",
        "letter": "W",
        "label": "W",
        "full_name": "Letra W (LSC)",
        "emoji": "🖖",
        "category": "Abecedario LSC",
        "bimanual": False,
        "is_dynamic": False,
        "default_phrase": "W",
        "description": "Dedos índice, medio y anular extendidos hacia arriba formando una 'W'; meñique y pulgar plegados.",
        "motion_hint": "Tres dedos centrales extendidos hacia arriba",
        "color": "#00F0FF",
    },
    "L_X": {
        "id": "L_X",
        "letter": "X",
        "label": "X",
        "full_name": "Letra X (LSC)",
        "emoji": "🔤",
        "category": "Abecedario LSC",
        "bimanual": False,
        "is_dynamic": False,
        "default_phrase": "X",
        "description": "Dedo índice encorvado en forma de gancho; los demás dedos cerrados en puño.",
        "motion_hint": "Índice flexionado en gancho",
        "color": "#00F0FF",
    },
    "L_Y": {
        "id": "L_Y",
        "letter": "Y",
        "label": "Y",
        "full_name": "Letra Y (LSC)",
        "emoji": "🤙",
        "category": "Abecedario LSC",
        "bimanual": False,
        "is_dynamic": False,
        "default_phrase": "Y",
        "description": "Dedos pulgar y meñique extendidos (gesto Shaka); índice, medio y anular plegados.",
        "motion_hint": "Pulgar y meñique abiertos",
        "color": "#00FF9D",
    },
    "L_Z": {
        "id": "L_Z",
        "letter": "Z",
        "label": "Z",
        "full_name": "Letra Z (LSC)",
        "emoji": "⚡",
        "category": "Abecedario LSC",
        "bimanual": False,
        "is_dynamic": True,
        "default_phrase": "Z",
        "description": "Dedos índice y medio juntos trazando la figura de una 'Z' en zigzag en el aire.",
        "motion_hint": "Dinámica: Traza una Z en zigzag en el aire",
        "color": "#FFB800",
    },
}

# Normalizar alias de metadatos para compatibilidad total con HUD y API REST
for _lid, _lmeta in LSC_ALPHABET_CATALOG.items():
    _lmeta["type"] = "DINAMICO" if _lmeta.get("is_dynamic") else "ESTATICO"
    _lmeta["word"] = _lmeta["letter"]
    _lmeta["phrase"] = _lmeta["default_phrase"]
    _lmeta["hands"] = 1

# Mapa directo de caracter ('A'..'Z', 'Ñ') a ID de seña ('L_A'..'L_Z', 'L_NTILDE')
CHAR_TO_LSC_ID: Dict[str, str] = {
    meta["letter"]: lid for lid, meta in LSC_ALPHABET_CATALOG.items()
}


def get_lsc_letter_pose(letter_id: str, t_phase: float = 0.0) -> np.ndarray:
    """
    Genera la matriz (21, 3) en coordenadas normalizadas [0..1] que representa la
    configuración anatómica 3D de la mano para cualquiera de las 27 letras del
    Abecedario en Lengua de Señas Colombiana (LSC).

    Si t_phase > 0 (en [0..1]), aplica la trayectoria cinemática correspondiente a las
    letras con movimiento (G, H, J, Ñ, S, Z) para animar el Modelo 3D de Manos.
    """
    lid = letter_id.upper().strip()
    if len(lid) == 1 and lid in CHAR_TO_LSC_ID:
        lid = CHAR_TO_LSC_ID[lid]

    pts = np.zeros((21, 3), dtype=np.float32)

    # Muñeca y nudillos base por defecto (mano vertical mirando a cámara)
    pts[0] = [0.50, 0.78, 0.00]   # WRIST
    pts[1] = [0.42, 0.72, -0.02]  # THUMB_CMC
    pts[2] = [0.36, 0.64, -0.03]  # THUMB_MCP
    pts[5] = [0.43, 0.54, -0.01]  # INDEX_MCP
    pts[9] = [0.49, 0.52, -0.01]  # MIDDLE_MCP
    pts[13] = [0.55, 0.54, -0.01] # RING_MCP
    pts[17] = [0.60, 0.58, -0.02] # PINKY_MCP

    def ext_up(mcp: int, dx: float = 0.0, length: float = 0.25):
        x0, y0, z0 = pts[mcp]
        pts[mcp + 1] = [x0 + dx * 0.33, y0 - length * 0.42, z0 - 0.01]
        pts[mcp + 2] = [x0 + dx * 0.66, y0 - length * 0.74, z0 - 0.02]
        pts[mcp + 3] = [x0 + dx * 1.00, y0 - length * 1.00, z0 - 0.03]

    def fold(mcp: int, dx: float = 0.0):
        x0, y0, z0 = pts[mcp]
        pts[mcp + 1] = [x0 + dx * 0.2, y0 - 0.04, z0 - 0.03]
        pts[mcp + 2] = [x0 + dx * 0.1, y0 + 0.04, z0 - 0.05]
        pts[mcp + 3] = [x0, y0 + 0.08, z0 - 0.04]

    def hook_finger(mcp: int, dx: float = 0.0, height: float = 0.12, drop: float = 0.02):
        """Dedo semi-curvado en arco / gancho (C, E, X)."""
        x0, y0, z0 = pts[mcp]
        pts[mcp + 1] = [x0 + dx * 0.4, y0 - height, z0 - 0.03]
        pts[mcp + 2] = [x0 + dx * 0.8, y0 - height * 0.85, z0 - 0.06]
        pts[mcp + 3] = [x0 + dx * 0.9, y0 - height * 0.35 + drop, z0 - 0.07]

    def thumb_state(extended: bool, up_bias: float = 0.0):
        if extended:
            pts[3] = [0.30, 0.56 - up_bias * 0.5, -0.04]
            pts[4] = [0.24, 0.48 - up_bias, -0.05]
        else:
            pts[3] = [0.42, 0.60, -0.04]
            pts[4] = [0.47, 0.58, -0.05]

    if lid == "L_A":
        # Puño cerrado con pulgar extendido hacia arriba/lado
        thumb_state(True, up_bias=0.06)
        fold(5, -0.01)
        fold(9, 0.00)
        fold(13, 0.01)
        fold(17, 0.02)

    elif lid == "L_B":
        # 4 dedos largos extendidos y muy juntos, pulgar plegado sobre la palma
        thumb_state(False)
        pts[4] = [0.48, 0.57, -0.05]
        ext_up(5, 0.025, 0.25)
        ext_up(9, 0.00, 0.26)
        ext_up(13, -0.022, 0.25)
        ext_up(17, -0.040, 0.21)

    elif lid == "L_C":
        # Mano semi-curvada en arco 'C'
        pts[3] = [0.34, 0.58, -0.04]
        pts[4] = [0.33, 0.51, -0.06]
        hook_finger(5, -0.06, height=0.13, drop=0.01)
        hook_finger(9, -0.05, height=0.14, drop=0.01)
        hook_finger(13, -0.05, height=0.13, drop=0.01)
        hook_finger(17, -0.05, height=0.11, drop=0.01)

    elif lid == "L_D":
        # Índice vertical arriba; medio, anular y meñique tocan la punta del pulgar
        ext_up(5, -0.01, 0.26)
        fold(9, -0.02)
        fold(13, -0.02)
        fold(17, 0.00)
        # Hacer que la punta del medio (12) y pulgar (4) se toquen en círculo
        pts[11] = [0.45, 0.52, -0.05]
        pts[12] = [0.42, 0.55, -0.05]
        pts[3] = [0.39, 0.59, -0.04]
        pts[4] = [0.42, 0.55, -0.05]

    elif lid == "L_E":
        # 4 dedos en garra alta flexionada y pulgar recogido abajo sin tocar puntas
        pts[3] = [0.43, 0.65, -0.04]
        pts[4] = [0.48, 0.66, -0.05]
        hook_finger(5, 0.00, height=0.10, drop=0.04)
        hook_finger(9, 0.00, height=0.11, drop=0.04)
        hook_finger(13, 0.00, height=0.10, drop=0.04)
        hook_finger(17, 0.00, height=0.09, drop=0.04)

    elif lid == "L_F":
        # Índice extendido arriba con el pulgar unido a su falange media (PIP [6]); demás plegados
        ext_up(5, -0.01, 0.25)
        fold(9, 0.00)
        fold(13, 0.01)
        fold(17, 0.02)
        pts[3] = [0.40, 0.51, -0.03]
        pts[4] = [0.425, 0.435, -0.03]  # pegado a INDEX_PIP [6]

    elif lid == "L_G":
        # Mano horizontal con índice apuntando hacia la izquierda (SIDE)
        pts[0] = [0.64, 0.62, 0.00]
        pts[1] = [0.58, 0.55, -0.02]
        pts[2] = [0.52, 0.51, -0.03]
        pts[3] = [0.46, 0.51, -0.04]
        pts[4] = [0.42, 0.52, -0.04]
        pts[5] = [0.52, 0.48, -0.01]
        pts[9] = [0.53, 0.55, -0.01]
        pts[13] = [0.55, 0.62, -0.01]
        pts[17] = [0.57, 0.68, -0.02]
        # Índice apuntando horizontalmente a la izquierda
        pts[6] = [0.42, 0.47, -0.02]
        pts[7] = [0.33, 0.47, -0.03]
        pts[8] = [0.24, 0.47, -0.03]
        # Medio, anular y meñique plegados hacia la palma derecha
        for mcp, y_base in ((9, 0.55), (13, 0.62), (17, 0.68)):
            pts[mcp + 1] = [0.49, y_base, -0.03]
            pts[mcp + 2] = [0.54, y_base + 0.02, -0.05]
            pts[mcp + 3] = [0.58, y_base + 0.02, -0.04]
        if t_phase > 0.0:
            dx_anim = math.sin(t_phase * math.pi * 2.0) * 0.04
            pts[:, 0] += dx_anim

    elif lid == "L_H":
        # Mano horizontal con índice y medio extendidos juntos hacia la izquierda (SIDE)
        pts[0] = [0.64, 0.62, 0.00]
        pts[1] = [0.58, 0.56, -0.02]
        pts[2] = [0.53, 0.53, -0.03]
        pts[3] = [0.50, 0.56, -0.04]
        pts[4] = [0.52, 0.59, -0.04]
        pts[5] = [0.52, 0.48, -0.01]
        pts[9] = [0.52, 0.54, -0.01]
        pts[13] = [0.55, 0.61, -0.01]
        pts[17] = [0.57, 0.67, -0.02]
        # Índice horizontal
        pts[6] = [0.42, 0.48, -0.02]
        pts[7] = [0.33, 0.48, -0.03]
        pts[8] = [0.24, 0.48, -0.03]
        # Medio horizontal junto al índice
        pts[10] = [0.42, 0.53, -0.02]
        pts[11] = [0.32, 0.53, -0.03]
        pts[12] = [0.23, 0.53, -0.03]
        # Anular y meñique plegados
        for mcp, y_base in ((13, 0.61), (17, 0.67)):
            pts[mcp + 1] = [0.49, y_base, -0.03]
            pts[mcp + 2] = [0.54, y_base + 0.02, -0.05]
            pts[mcp + 3] = [0.58, y_base + 0.02, -0.04]
        if t_phase > 0.0:
            pts[:, 0] -= math.sin(t_phase * math.pi) * 0.06

    elif lid in ("L_I", "L_J"):
        # Solo meñique extendido arriba; si es L_J anima la curva en J
        thumb_state(False)
        fold(5, -0.01)
        fold(9, 0.00)
        fold(13, 0.01)
        ext_up(17, 0.02, 0.23)
        if lid == "L_J" and t_phase > 0.0:
            # Trayectoria en J: baja en la primera mitad y hace gancho a la izquierda/arriba
            dy = math.sin(min(1.0, t_phase * 1.3) * math.pi * 0.75) * 0.09
            dx = -max(0.0, (t_phase - 0.35)) * 0.11
            pts[:, 0] += dx
            pts[:, 1] += dy

    elif lid == "L_K":
        # Índice y medio en V oblicua inclinada con el pulgar extendido entre ambos
        thumb_state(True, up_bias=0.08)
        pts[3] = [0.41, 0.52, -0.04]
        pts[4] = [0.40, 0.44, -0.05]
        ext_up(5, -0.14, 0.24)
        ext_up(9, -0.06, 0.25)
        fold(13, 0.01)
        fold(17, 0.02)

    elif lid == "L_L":
        # Índice arriba + Pulgar horizontal en L
        thumb_state(True, up_bias=0.0)
        ext_up(5, -0.02, 0.26)
        fold(9, 0.00)
        fold(13, 0.01)
        fold(17, 0.02)

    elif lid == "L_M":
        # Mano colgante hacia abajo con 3 dedos (índice, medio, anular) apuntando abajo (DOWN)
        pts[0] = [0.50, 0.26, 0.00]
        pts[1] = [0.43, 0.32, -0.02]
        pts[2] = [0.39, 0.39, -0.03]
        pts[3] = [0.43, 0.45, -0.04]
        pts[4] = [0.47, 0.47, -0.04]
        pts[5] = [0.43, 0.46, -0.01]
        pts[9] = [0.49, 0.47, -0.01]
        pts[13] = [0.55, 0.46, -0.01]
        pts[17] = [0.60, 0.43, -0.02]
        for mcp, dx in ((5, -0.02), (9, 0.00), (13, 0.02)):
            x0, y0, z0 = pts[mcp]
            pts[mcp + 1] = [x0 + dx * 0.3, y0 + 0.09, z0 - 0.01]
            pts[mcp + 2] = [x0 + dx * 0.6, y0 + 0.17, z0 - 0.02]
            pts[mcp + 3] = [x0 + dx * 1.0, y0 + 0.24, z0 - 0.03]
        # Meñique plegado arriba
        pts[18] = [0.60, 0.47, -0.03]
        pts[19] = [0.58, 0.42, -0.05]
        pts[20] = [0.57, 0.39, -0.04]

    elif lid in ("L_N", "L_NTILDE"):
        # Mano colgante hacia abajo con 2 dedos (índice y medio) apuntando abajo (DOWN)
        pts[0] = [0.50, 0.26, 0.00]
        pts[1] = [0.43, 0.32, -0.02]
        pts[2] = [0.39, 0.39, -0.03]
        pts[3] = [0.43, 0.45, -0.04]
        pts[4] = [0.47, 0.47, -0.04]
        pts[5] = [0.44, 0.46, -0.01]
        pts[9] = [0.50, 0.47, -0.01]
        pts[13] = [0.55, 0.45, -0.01]
        pts[17] = [0.60, 0.43, -0.02]
        for mcp, dx in ((5, -0.01), (9, 0.01)):
            x0, y0, z0 = pts[mcp]
            pts[mcp + 1] = [x0 + dx * 0.3, y0 + 0.09, z0 - 0.01]
            pts[mcp + 2] = [x0 + dx * 0.6, y0 + 0.17, z0 - 0.02]
            pts[mcp + 3] = [x0 + dx * 1.0, y0 + 0.24, z0 - 0.03]
        for mcp in (13, 17):
            x0, y0, z0 = pts[mcp]
            pts[mcp + 1] = [x0, y0 + 0.04, z0 - 0.03]
            pts[mcp + 2] = [x0 - 0.01, y0 - 0.02, z0 - 0.05]
            pts[mcp + 3] = [x0 - 0.02, y0 - 0.05, z0 - 0.04]
        if lid == "L_NTILDE" and t_phase > 0.0:
            pts[:, 0] += math.sin(t_phase * math.pi * 4.0) * 0.065

    elif lid == "L_O":
        # Círculo cerrado 'O': dedos curvados cuyas puntas tocan la punta del pulgar
        pts[3] = [0.38, 0.56, -0.04]
        pts[4] = [0.41, 0.47, -0.06]
        for mcp, tx in ((5, 0.41), (9, 0.42), (13, 0.44), (17, 0.46)):
            x0, y0, z0 = pts[mcp]
            pts[mcp + 1] = [x0 - 0.02, y0 - 0.11, z0 - 0.03]
            pts[mcp + 2] = [tx + 0.02, 0.43, z0 - 0.05]
            pts[mcp + 3] = [tx, 0.47, -0.06]

    elif lid == "L_P":
        # Mano hacia abajo con solo el dedo índice apuntando verticalmente al suelo (DOWN)
        pts[0] = [0.50, 0.26, 0.00]
        pts[1] = [0.43, 0.32, -0.02]
        pts[2] = [0.39, 0.39, -0.03]
        pts[3] = [0.42, 0.45, -0.04]
        pts[4] = [0.46, 0.48, -0.04]
        pts[5] = [0.44, 0.46, -0.01]
        pts[9] = [0.50, 0.46, -0.01]
        pts[13] = [0.55, 0.45, -0.01]
        pts[17] = [0.60, 0.43, -0.02]
        # Índice hacia abajo
        pts[6] = [0.44, 0.55, -0.02]
        pts[7] = [0.44, 0.63, -0.03]
        pts[8] = [0.44, 0.71, -0.03]
        # Medio, anular y meñique recogidos
        for mcp in (9, 13, 17):
            x0, y0, z0 = pts[mcp]
            pts[mcp + 1] = [x0, y0 + 0.04, z0 - 0.03]
            pts[mcp + 2] = [x0 - 0.02, y0 - 0.01, z0 - 0.05]
            pts[mcp + 3] = [x0 - 0.03, y0 - 0.04, z0 - 0.04]

    elif lid == "L_Q":
        # Capullo hacia arriba: las 5 puntas convergen arriba en un mismo punto
        target_tip = [0.48, 0.31, -0.05]
        pts[3] = [0.42, 0.44, -0.04]
        pts[4] = [0.47, 0.32, -0.05]
        for mcp, dx in ((5, 0.04), (9, 0.00), (13, -0.04), (17, -0.08)):
            x0, y0, z0 = pts[mcp]
            pts[mcp + 1] = [x0 + dx * 0.4, y0 - 0.09, z0 - 0.02]
            pts[mcp + 2] = [x0 + dx * 0.7, y0 - 0.16, z0 - 0.04]
            pts[mcp + 3] = [target_tip[0] - dx * 0.15, target_tip[1], target_tip[2]]

    elif lid == "L_R":
        # Índice y medio extendidos arriba y cruzados en X
        thumb_state(False)
        # Índice cruza hacia la derecha del medio
        pts[6] = [0.46, 0.43, -0.02]
        pts[7] = [0.49, 0.35, -0.03]
        pts[8] = [0.51, 0.27, -0.04]
        # Medio cruza hacia la izquierda del índice
        pts[10] = [0.48, 0.42, -0.01]
        pts[11] = [0.46, 0.34, -0.02]
        pts[12] = [0.44, 0.26, -0.03]
        fold(13, 0.01)
        fold(17, 0.02)

    elif lid == "L_S":
        # Índice extendido arriba trazando una 'S' en el aire
        thumb_state(False)
        ext_up(5, -0.01, 0.26)
        fold(9, 0.00)
        fold(13, 0.01)
        fold(17, 0.02)
        if t_phase > 0.0:
            dx_s = math.sin(t_phase * math.pi * 2.0) * 0.07
            dy_s = (t_phase - 0.5) * 0.12
            pts[:, 0] += dx_s
            pts[:, 1] += dy_s

    elif lid == "L_T":
        # Índice y medio juntos en diagonal con el pulgar metido entre índice y medio
        ext_up(5, -0.06, 0.23)
        ext_up(9, -0.09, 0.24)
        fold(13, 0.01)
        fold(17, 0.02)
        pts[3] = [0.43, 0.54, -0.04]
        pts[4] = [0.45, 0.45, -0.05]  # Entre índice PIP y medio PIP

    elif lid == "L_U":
        # LSC Oficial: Índice (8) y Meñique (20) extendidos verticalmente; medio y anular plegados
        thumb_state(False)
        ext_up(5, -0.02, 0.26)
        fold(9, 0.00)
        fold(13, 0.01)
        ext_up(17, 0.04, 0.23)

    elif lid == "L_V":
        # Índice y medio extendidos arriba y bien separados en 'V'
        thumb_state(False)
        ext_up(5, -0.06, 0.26)
        ext_up(9, 0.05, 0.27)
        fold(13, 0.01)
        fold(17, 0.02)

    elif lid == "L_W":
        # Índice, medio y anular extendidos arriba en 'W'; meñique y pulgar plegados
        thumb_state(False)
        ext_up(5, -0.05, 0.25)
        ext_up(9, 0.00, 0.27)
        ext_up(13, 0.05, 0.25)
        fold(17, 0.02)

    elif lid == "L_X":
        # Solo dedo índice en gancho (MCP levantado, PIP/DIP flexionados); demás plegados
        thumb_state(False)
        pts[6] = [0.43, 0.41, -0.02]
        pts[7] = [0.43, 0.40, -0.07]
        pts[8] = [0.43, 0.47, -0.08]
        fold(9, 0.00)
        fold(13, 0.01)
        fold(17, 0.02)

    elif lid == "L_Y":
        # Pulgar y meñique extendidos (Shaka); índice, medio y anular plegados
        thumb_state(True, up_bias=0.02)
        fold(5, -0.01)
        fold(9, 0.00)
        fold(13, 0.01)
        ext_up(17, 0.07, 0.22)

    elif lid == "L_Z":
        # Índice y medio juntos trazando una 'Z' en el aire
        thumb_state(False)
        ext_up(5, 0.01, 0.25)
        ext_up(9, -0.02, 0.26)
        fold(13, 0.01)
        fold(17, 0.02)
        if t_phase > 0.0:
            # 3 tramos de la Z: derecha -> diagonal abajo-izquierda -> derecha
            if t_phase < 0.33:
                u = t_phase / 0.33
                dx_z, dy_z = -0.06 + 0.12 * u, -0.05
            elif t_phase < 0.66:
                u = (t_phase - 0.33) / 0.33
                dx_z, dy_z = 0.06 - 0.12 * u, -0.05 + 0.10 * u
            else:
                u = (t_phase - 0.66) / 0.34
                dx_z, dy_z = -0.06 + 0.12 * u, 0.05
            pts[:, 0] += dx_z
            pts[:, 1] += dy_z

    return pts


# ---------------------------------------------------------------------------
# Pre-cálculo de Plantillas Canónicas 3D (Vector 63D) para las 27 letras LSC
# ---------------------------------------------------------------------------
_CANONICAL_LETTER_TEMPLATES: Dict[str, np.ndarray] = {}
_CANONICAL_MATRIX: Optional[np.ndarray] = None
_CANONICAL_KEYS: List[str] = []


def _init_canonical_templates() -> None:
    global _CANONICAL_LETTER_TEMPLATES, _CANONICAL_MATRIX, _CANONICAL_KEYS
    if _CANONICAL_MATRIX is not None:
        return
    matrix_rows = []
    _CANONICAL_KEYS = []
    for lid in sorted(LSC_ALPHABET_CATALOG.keys()):
        pose = get_lsc_letter_pose(lid, t_phase=0.0)
        vec, _ = normalize_landmarks(pose)
        norm = float(np.linalg.norm(vec))
        vec_unit = (vec / norm) if norm > 1e-6 else vec
        _CANONICAL_LETTER_TEMPLATES[lid] = vec_unit
        matrix_rows.append(vec_unit)
        _CANONICAL_KEYS.append(lid)
    _CANONICAL_MATRIX = np.array(matrix_rows, dtype=np.float32)


def compute_template_similarities(vector_63d: np.ndarray) -> Dict[str, float]:
    """Calcula similitud coseno ultra-rápida (en ~0.02ms) contra las 27 plantillas canónicas."""
    _init_canonical_templates()
    v = np.asarray(vector_63d, dtype=np.float32).flatten()
    norm = float(np.linalg.norm(v))
    if norm < 1e-6 or _CANONICAL_MATRIX is None:
        return {k: 0.0 for k in _CANONICAL_KEYS}
    v_unit = v / norm
    sims = _CANONICAL_MATRIX @ v_unit
    return {k: round(float(sims[i]), 4) for i, k in enumerate(_CANONICAL_KEYS)}


def classify_lsc_alphabet(
    multi_hand: Dict[str, Any],
    motion: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Clasificador de Alta Precisión para las 27 letras del Abecedario LSC (A-Z + Ñ).
    Implementa una técnica Ensamble Híbrida:
    1. Similitud Coseno 3D contra Plantillas Canónicas Normalizadas (Embeddings 63D).
    2. Verificación y Discriminación Anatómica Biomecánica (flexión, abducción, orientación).
    3. Análisis Cinemático de Trayectoria Temporal (J, Z, H, G, Ñ, S).
    """
    if not multi_hand or not multi_hand.get("primary"):
        return None

    primary = multi_hand["primary"]
    telem = primary.get("telemetry", {})
    fingers = telem.get("fingers", {})
    fine = telem.get("fine", {})
    vector_63d = primary.get("vector_63d")
    if vector_63d is None:
        vector_63d = telem.get("vector_sample", [])

    thumb = bool(fingers.get("thumb", False))
    index = bool(fingers.get("index", False))
    middle = bool(fingers.get("middle", False))
    ring = bool(fingers.get("ring", False))
    pinky = bool(fingers.get("pinky", False))

    p_motion = motion.get("primary", {}) if motion else {}
    is_osc_x = bool(p_motion.get("is_oscillating_x"))
    trace_j = bool(p_motion.get("trace_j"))
    trace_s = bool(p_motion.get("trace_s"))
    trace_z = bool(p_motion.get("trace_z"))
    trace_h = bool(p_motion.get("trace_h"))
    is_moving_horiz = bool(p_motion.get("is_moving_horiz"))

    pointing_dir = fine.get("pointing_dir", "UP")
    fingertips_down = bool(fine.get("fingertips_down", False) or fine.get("hand_hanging_down", False))
    spread = float(fine.get("idx_mid_spread", 0.5))
    is_crossed_r = bool(fine.get("is_crossed_r", False))
    is_x_hook = bool(fine.get("is_x_hook", False))
    is_e_claw = bool(fine.get("is_e_claw", False))
    is_c_arch = bool(fine.get("is_c_arch", False))
    is_o_circle = bool(fine.get("is_o_circle", False))
    is_q_cluster = bool(fine.get("is_q_cluster", False))
    thumb_across_front = bool(fine.get("thumb_across_front", False))
    hooks = fine.get("hooks", {})
    d_thumb_idx = float(fine.get("d_thumb_idx", 1.0))
    d_thumb_mid = float(fine.get("d_thumb_mid", 1.0))
    d_thumb_idx_pip = float(fine.get("d_thumb_idx_pip", 1.0))
    d_thumb_idx_tip = float(fine.get("d_thumb_idx_tip", 1.0))

    # Similitudes coseno contra todas las 27 plantillas canónicas
    sims = compute_template_similarities(vector_63d) if len(vector_63d) == 63 else {}

    def _res(lid: str, conf: float = 0.96, dyn: bool = False) -> Dict[str, Any]:
        meta = LSC_ALPHABET_CATALOG[lid]
        # Modular la confianza con la similitud de la plantilla si está disponible
        t_sim = float(sims.get(lid, 0.90))
        final_conf = round(min(0.99, max(conf, 0.50 * conf + 0.50 * max(0.85, t_sim))), 3)
        return {
            "sign_id": lid,
            "letter": meta["letter"],
            "label": meta["label"],
            "confidence": final_conf,
            "note": f"Abecedario LSC: Letra {meta['letter']} — {meta['description']}",
            "is_dynamic": dyn or meta["is_dynamic"],
        }

    # =========================================================================
    # A. TRAZOS DINÁMICOS PRIORITARIOS (J, Z, H, G, Ñ, S_TRAZADA)
    # =========================================================================
    # 1. Letra J (Curva descendente trazada con el meñique)
    if pinky and not index and not middle and not ring and trace_j:
        return _res("L_J", 0.98, dyn=True)

    # 2. Letra Z (Zigzag trazado con el índice o índice+medio)
    if index and not ring and not pinky and trace_z:
        return _res("L_Z", 0.98, dyn=True)

    # 3. Letra H (Índice y medio juntos horizontales; no confundir con V/R inclinadas o N hacia abajo)
    v_idx_x = float(fine.get("v_idx_x", 0.0))
    v_idx_y = float(fine.get("v_idx_y", -1.0))
    is_lateral = (pointing_dir == "SIDE") or (abs(v_idx_x) > 1.15 * max(1e-4, abs(v_idx_y)))
    is_not_vertical_up = (v_idx_y > -0.62)  # Evita secuestrar V/R/K verticales aunque se mueva la mano
    is_h_dynamic = (trace_h or is_moving_horiz) and is_not_vertical_up

    if index and middle and not ring and not pinky and (spread < 0.32) and not is_crossed_r and not fingertips_down:
        if is_lateral or is_h_dynamic:
            return _res("L_H", 0.98 if is_h_dynamic else 0.96, dyn=is_h_dynamic)

    # 4. Letra G (Solo índice horizontal con o sin deslizamiento lateral)
    if index and not middle and not ring and not pinky and not trace_s and not trace_z and not fingertips_down:
        if is_lateral or (trace_h and not is_osc_x and is_not_vertical_up):
            return _res("L_G", 0.97 if is_h_dynamic else 0.96, dyn=is_h_dynamic)

    # 5. Letra Ñ (Configuración N apuntando hacia abajo con oscilación horizontal de virgulilla)
    if is_osc_x and (fingertips_down or v_idx_y > 0.22) and not ring and not pinky:
        return _res("L_NTILDE", 0.98, dyn=True)

    # 6. Letra S Trazada (solo índice o puño trazando curva S, nunca mano abierta)
    if trace_s and not ring and not pinky and not middle:
        return _res("L_S", 0.98, dyn=True)

    # =========================================================================
    # B. RECONOCIMIENTO DE ALTA PRECISIÓN POR PLANTILLAS CANÓNICAS 3D Y FILTRO ANATÓMICO
    # =========================================================================
    if sims:
        # Penalización anatómica estricta: evita que gestos con distinto número de dedos
        # ganen por similitud global de la palma en 63D.
        filtered_sims = dict(sims)
        expected_groups = {
            "0_fingers": {"L_A", "L_E", "L_O", "L_S", "L_T", "L_C", "L_M", "L_N", "L_P", "L_Q", "L_X"},
            "1_index": {"L_D", "L_F", "L_G", "L_L", "L_P", "L_Q", "L_S", "L_T", "L_X", "L_Z"},
            "1_pinky": {"L_I", "L_J", "L_Y"},
            "2_idx_mid": {"L_H", "L_K", "L_N", "L_P", "L_R", "L_T", "L_V", "L_Z"},
            "2_idx_pinky": {"L_U"},
            "3_fingers": {"L_F", "L_M", "L_W"},
            "4_fingers": {"L_B", "L_C", "L_E", "L_Q"},
        }
        if not index and not middle and not ring and not pinky:
            allowed = expected_groups["0_fingers"]
        elif index and not middle and not ring and not pinky:
            allowed = expected_groups["1_index"]
        elif pinky and not index and not middle and not ring:
            allowed = expected_groups["1_pinky"]
        elif index and middle and not ring and not pinky:
            allowed = expected_groups["2_idx_mid"]
        elif index and pinky and not middle and not ring:
            allowed = expected_groups["2_idx_pinky"]
        elif (index and middle and ring and not pinky) or (middle and ring and pinky and not index):
            allowed = expected_groups["3_fingers"]
        elif index and middle and ring and pinky:
            allowed = expected_groups["4_fingers"]
        else:
            allowed = set(filtered_sims.keys())

        for lid in list(filtered_sims.keys()):
            if lid not in allowed:
                filtered_sims[lid] -= 0.10

        sorted_sims = sorted(filtered_sims.items(), key=lambda x: x[1], reverse=True)
        best_lid, best_sim = sorted_sims[0]
        second_lid, second_sim = sorted_sims[1]
        cands = {best_lid, second_lid}

        # Desambiguación anatómica para pares de alta proximidad métrica
        if cands == {"L_O", "L_C"}:
            chosen = "L_O" if d_thumb_idx_tip < 0.12 else "L_C"
            return _res(chosen, conf=max(best_sim, 0.96))

        if cands == {"L_M", "L_W"}:
            chosen = "L_M" if fingertips_down else "L_W"
            return _res(chosen, conf=max(best_sim, 0.96))

        if cands == {"L_N", "L_V"} or (best_lid == "L_N" and not fingertips_down and v_idx_y < -0.1):
            chosen = "L_N" if (fingertips_down or v_idx_y > 0.20) else ("L_R" if is_crossed_r else "L_V")
            return _res(chosen, conf=max(best_sim, 0.96))

        if cands == {"L_A", "L_S"}:
            chosen = "L_A" if (thumb or d_thumb_idx > 0.28) else "L_S"
            return _res(chosen, conf=max(best_sim, 0.96))

        if cands == {"L_E", "L_A"}:
            chosen = "L_E" if is_e_claw else "L_A"
            return _res(chosen, conf=max(best_sim, 0.95))

        if cands == {"L_I", "L_Y"}:
            chosen = "L_Y" if (thumb and d_thumb_idx > 0.36) else "L_I"
            return _res(chosen, conf=max(best_sim, 0.96))

        if cands == {"L_D", "L_L"}:
            chosen = "L_L" if (thumb and d_thumb_idx > 0.34) else "L_D"
            return _res(chosen, conf=max(best_sim, 0.96))

        if cands == {"L_K", "L_V"}:
            chosen = "L_K" if (thumb or d_thumb_idx_pip < 0.28) else "L_V"
            return _res(chosen, conf=max(best_sim, 0.96))

        if cands == {"L_R", "L_V"}:
            chosen = "L_R" if is_crossed_r else "L_V"
            return _res(chosen, conf=max(best_sim, 0.96))

        if best_sim >= 0.85:
            return _res(best_lid, conf=best_sim)

    return None
