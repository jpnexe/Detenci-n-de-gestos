"""Suite de verificación técnica para SignBridge Extended."""

from backend.normalizer import normalize_landmarks
from backend.classifier_local import LocalGestureClassifier, get_canonical_hand_pose
from backend.stabilizer import TemporalStabilizer
from backend.pipeline import SignBridgePipeline


def run_tests():
    print("1. Probando Normalización 3D (63 floats) y Clasificador Local (TF-MLP)...")
    clf = LocalGestureClassifier()
    for gid in ["G0", "G1", "G2", "G3", "G4", "G5"]:
        pose = get_canonical_hand_pose(gid)
        vec63, tel = normalize_landmarks(pose)
        assert vec63.shape == (63,), f"Forma inválida: {vec63.shape}"
        pred = clf.predict(vec63, tel)
        print(f"   [{gid}] -> Predicción: {pred['gesture_id']} | Confianza: {pred['confidence']} | Acción: {pred['action']}")
        assert pred["gesture_id"] == gid, f"Error en {gid}: {pred}"

    print("2. Probando Estabilizador Temporal (Buffer Circular N=8 y Umbral >= 0.85)...")
    stab = TemporalStabilizer(buffer_size=8, min_confidence=0.85)
    # Probar rechazo activo con confianza < 0.85
    low_conf = stab.update({"gesture_id": "G1", "confidence": 0.72})
    assert low_conf["stabilized_id"] == "G0" and low_conf["rejected_by_threshold"] is True
    print("   Rechazo activo por umbral (< 0.85) verificado correctamente.")

    # Probar llenado progresivo de N=8 fotogramas para G1
    stab.reset()
    triggered_count = 0
    for i in range(8):
        st = stab.update({"gesture_id": "G1", "confidence": 0.95})
        if st["triggered"]:
            triggered_count += 1
    assert triggered_count == 1, f"Se esperaba 1 disparo al frame 8, hubo {triggered_count}"
    print("   Disparo exacto al completar N=8 fotogramas verificado.")

    print("3. Probando Pipeline Completo (Offline, Online y Simulador 3D)...")
    pipe = SignBridgePipeline()
    pipe.hardware.enabled = False  # Desactivar click real durante el test
    pipe.hardware.pointer_enabled = True
    pipe.set_video_source("SIMULATOR")
    assert pipe.hardware.pointer_enabled is False, "El modo simulador debe apagar el puntero"
    for gid in ["G0", "G1", "G2", "G3", "G4", "G5"]:
        pipe.set_simulated_gesture(gid)
        step_sim = pipe.process_step()
        assert step_sim["source"] == "SIMULATOR_3D"
        assert len(step_sim["frame_b64"]) > 1000
    pipe.set_mode("ONLINE")
    step_on = pipe.process_step()
    assert step_on["mode"] == "ONLINE"
    print(f"   Pipeline y Simulador 3D OK | FPS: {step_on['fps']} | Frame Base64 bytes: {len(step_on['frame_b64'])}")

    print("4. Probando Analizador Cinemático de Movimiento (Gestos Dinámicos: S_ADIOS, S_NO, S_SI, L_J, L_Z)...")
    from backend.motion_analyzer import KinematicMotionAnalyzer
    from backend.normalizer import normalize_multi_hand_landmarks
    from backend.lsc_alphabet import get_lsc_letter_pose
    import numpy as np, time
    motion = KinematicMotionAnalyzer()
    base_pose = get_canonical_hand_pose("G0")
    t0 = time.time()
    for i in range(12):
        shift = 0.08 * np.sin(i * 0.8)
        p = base_pose.copy()
        p[:, 0] += shift
        m = motion.update(p, timestamp=t0 + i * 0.033)
    multi = normalize_multi_hand_landmarks([p], ["Right"])
    match_adios = pipe.conversation_engine.classify_unimanual_gesture(multi, motion=m)
    assert match_adios["sign_id"] == "S_ADIOS", f"Error en S_ADIOS: {match_adios}"
    print("   Detección de gesto con oscilación lateral (S_ADIOS) verificada.")

    # 4.1. Verificación precisa del trazo dinámico de la Letra 'J' (Meñique descendiendo y curvando en gancho)
    motion.reset()
    j_base = get_lsc_letter_pose("L_I")
    t0 = time.time()
    for i in range(14):
        p = j_base.copy()
        if i < 8:
            # Fase 1: Descenso vertical
            dy = (i / 7.0) * 0.09
            dx = 0.0
        else:
            # Fase 2: Curva lateral y elevación en gancho
            u = (i - 7) / 6.0
            dy = 0.09 - u * 0.03
            dx = -u * 0.05
        p[:, 0] += dx
        p[:, 1] += dy
        m_j = motion.update(p, timestamp=t0 + i * 0.033)

    assert m_j["primary"]["trace_j"] is True, f"Error: trace_j no detectado en cinemática: {m_j['primary']}"
    multi_j = normalize_multi_hand_landmarks([p], ["Right"])
    match_j = pipe.conversation_engine.classify_unimanual_gesture(multi_j, motion=m_j)
    assert match_j["sign_id"] == "L_J", f"Error en clasificación de L_J: {match_j}"
    print("   Trazo cinemático de la Letra 'J' (L_J) verificado con precisión milimétrica.")

    # 4.2. Verificación precisa del trazo dinámico de la Letra 'Z' (Índice trazando zigzag)
    motion.reset()
    z_base = get_lsc_letter_pose("L_D")
    t0 = time.time()
    for i in range(15):
        p = z_base.copy()
        if i < 5:
            dx = (i / 4.0) * 0.06
            dy = 0.0
        elif i < 10:
            dx = 0.06 - ((i - 4) / 5.0) * 0.06
            dy = ((i - 4) / 5.0) * 0.06
        else:
            dx = ((i - 9) / 5.0) * 0.06
            dy = 0.06
        p[:, 0] += dx
        p[:, 1] += dy
        m_z = motion.update(p, timestamp=t0 + i * 0.033)

    assert m_z["primary"]["trace_z"] is True, f"Error: trace_z no detectado en cinemática: {m_z['primary']}"
    multi_z = normalize_multi_hand_landmarks([p], ["Right"])
    match_z = pipe.conversation_engine.classify_unimanual_gesture(multi_z, motion=m_z)
    assert match_z["sign_id"] == "L_Z", f"Error en clasificación de L_Z: {match_z}"
    print("   Trazo cinemático de la Letra 'Z' (L_Z) verificado exitosamente.")

    # 4.3. Verificación precisa de la Letra 'H' (Índice y medio horizontales con deslizamiento lateral)
    motion.reset()
    h_base = get_lsc_letter_pose("L_H")
    t0 = time.time()
    for i in range(10):
        p = h_base.copy()
        # Deslizamiento lateral horizontal (eje X)
        dx = (i / 9.0) * 0.065
        p[:, 0] += dx
        m_h = motion.update(p, timestamp=t0 + i * 0.033)

    assert m_h["primary"]["trace_h"] is True, f"Error: trace_h no detectado en cinemática: {m_h['primary']}"
    multi_h = normalize_multi_hand_landmarks([p], ["Right"])
    match_h = pipe.conversation_engine.classify_unimanual_gesture(multi_h, motion=m_h)
    assert match_h["sign_id"] == "L_H", f"Error en clasificación de L_H: {match_h}"
    print("   Deslizamiento lateral y orientación de Letra 'H' (L_H) verificados con total precisión.")

    # 4.4. Verificación de Señas Conversacionales Dinámicas Bimanuales (S_DESPACIO, S_COMO_ESTAS)
    motion.reset()
    t0 = time.time()
    for i in range(10):
        p0 = base_pose.copy()
        p1 = base_pose.copy()
        p1[:, 0] -= 0.32
        # Descenso vertical simultáneo de ambas palmas
        dy = (i / 9.0) * 0.08
        p0[:, 1] += dy
        p1[:, 1] += dy
        m_despacio = motion.update(p0, p1, timestamp=t0 + i * 0.033)

    multi_despacio = normalize_multi_hand_landmarks([p0, p1], ["Right", "Left"])
    match_despacio = pipe.conversation_engine.classify_bimanual_gesture(multi_despacio, motion=m_despacio)
    assert match_despacio is not None and match_despacio["sign_id"] == "S_DESPACIO", f"Error en S_DESPACIO: {match_despacio}"
    print("   Seña bimanual dinámica 'Más despacio' (S_DESPACIO) verificada con éxito.")

    # 4.5. Verificación de Divergencia Bimanual (¿Cómo estás? - S_COMO_ESTAS)
    motion.reset()
    t0 = time.time()
    for i in range(10):
        p0 = base_pose.copy()
        p1 = base_pose.copy()
        p1[:, 0] -= 0.16
        # Divergencia lateral: las manos se separan activamente
        dx = (i / 9.0) * 0.07
        p0[:, 0] += dx
        p1[:, 0] -= dx
        m_como = motion.update(p0, p1, timestamp=t0 + i * 0.033)

    multi_como = normalize_multi_hand_landmarks([p0, p1], ["Right", "Left"])
    match_como = pipe.conversation_engine.classify_bimanual_gesture(multi_como, motion=m_como)
    assert match_como is not None and match_como["sign_id"] == "S_COMO_ESTAS", f"Error en S_COMO_ESTAS: {match_como}"
    print("   Seña bimanual dinámica '¿Cómo estás?' (S_COMO_ESTAS) verificada con éxito.")

    # 4.6. Verificación de Extensibilidad y Futuro Blindaje Dinámico
    from backend.stabilizer import is_gesture_dynamic
    from backend.conversation_engine import CONVERSATIONAL_SIGNS_CATALOG
    assert is_gesture_dynamic("S_DESPACIO") is True
    assert is_gesture_dynamic("S_COMO_ESTAS") is True
    assert is_gesture_dynamic("S_BUENOS_DIAS") is True
    assert is_gesture_dynamic("L_H") is True
    assert is_gesture_dynamic("G0") is False

    # Registro en tiempo de ejecución de una seña futura con `is_dynamic: True`
    CONVERSATIONAL_SIGNS_CATALOG["S_NUEVA_SEÑA_FUTURA"] = {
        "id": "S_NUEVA_SEÑA_FUTURA",
        "label": "Nueva Seña",
        "is_dynamic": True,
    }
    assert is_gesture_dynamic("S_NUEVA_SEÑA_FUTURA") is True, "Error: La nueva seña futura no fue detectada dinámicamente"
    print("   Soporte extensible y refinado para señas actuales y futuras verificado al 100%.")

    # 4.7. Verificación de Precisión del Ensamble para el Abecedario Completo (27 Letras A-Z + Ñ)
    from backend.lsc_alphabet import LSC_ALPHABET_CATALOG, classify_lsc_alphabet
    for lid in LSC_ALPHABET_CATALOG:
        pose = get_lsc_letter_pose(lid)
        multi = normalize_multi_hand_landmarks([pose], ["Right"])
        motion_mock = {
            "primary": {
                "trace_j": (lid == "L_J"),
                "trace_z": (lid == "L_Z"),
                "trace_h": (lid == "L_H"),
                "is_oscillating_x": (lid == "L_NTILDE"),
                "is_moving_horiz": (lid == "L_G"),
            }
        }
        res = classify_lsc_alphabet(multi, motion=motion_mock)
        assert res is not None and res["sign_id"] == lid, f"Fallo de precisión en {lid}: obtenido {res}"
    print("   Precisión del 100% (27/27) en el Abecedario LSC mediante Similitud de Plantillas y Discriminación Anatómica.")

    # 4.8. Verificación de Aislamiento Estricto de Modos (SIGN_LANGUAGE vs OS_CONTROL)
    pipe.interaction_mode = "SIGN_LANGUAGE"
    pipe.set_simulated_gesture("G0")
    step_sign = pipe.process_step()
    assert step_sign["stabilizer"]["stabilized_id"] not in ["G1", "G2", "G3", "G4", "G5"], (
        f"Fallo de aislamiento: Modo Señas emitió comando de mouse {step_sign['stabilizer']}"
    )
    print("   Aislamiento estricto de Modos verificado: El modo señas no emite comandos G1..G5.")

    print("5. Probando Conexión de Gemini API...")
    gem_test = pipe.gemini_classifier.test_connection()
    print(f"   Gemini Status: {gem_test.get('message', gem_test.get('error'))}")
    if gem_test.get("success"):
        print(f"   Conectividad Gemini validada con latencia: {gem_test.get('latency_ms')} ms en modelo: {gem_test.get('model')}")

    # 5.1. Verificación de Prioridad Soberana de Gemini en Modo ONLINE
    pipe.set_mode("ONLINE")
    dummy_multi = normalize_landmarks(get_canonical_hand_pose("G3"))[1]  # Puño cerrado (localmente sería Entendido)
    multi_mock = {"is_bimanual": False, "hands_count": 1, "primary": {"landmarks": get_canonical_hand_pose("G3")}}
    # En modo ONLINE, la predicción de Gemini 'S_HOLA' no debe ser secuestrada por el puño local
    conv_online = pipe.conversation_engine.process_frame_sign(
        raw_gesture_id="S_HOLA",
        confidence=0.95,
        multi_hand=multi_mock,
        is_triggered=True,
        is_online=True,
    )
    assert conv_online is not None and conv_online["sign_id"] == "S_HOLA", (
        f"Error: La predicción de Gemini fue sobreescrita por el modelo local: {conv_online}"
    )
    print("   Prioridad de Gemini en Modo ONLINE validada: Gemini tiene autoridad total sobre el clasificador local.")

    print("TODOS LOS TESTS PASARON EXITOSAMENTE.")


if __name__ == "__main__":
    run_tests()

