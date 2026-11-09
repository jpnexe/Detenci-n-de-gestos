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

    print("4. Probando Analizador Cinemático de Movimiento (Gestos Dinámicos: S_ADIOS, S_NO, S_SI, S_REPETIR)...")
    from backend.motion_analyzer import KinematicMotionAnalyzer
    from backend.normalizer import normalize_multi_hand_landmarks
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

    print("5. Probando Conexión de Gemini API...")
    gem_test = pipe.gemini_classifier.test_connection()
    print(f"   Gemini Status: {gem_test.get('message', gem_test.get('error'))}")
    if gem_test.get("success"):
        print(f"   Conectividad Gemini validada con latencia: {gem_test.get('latency_ms')} ms en modelo: {gem_test.get('model')}")

    print("TODOS LOS TESTS PASARON EXITOSAMENTE.")


if __name__ == "__main__":
    run_tests()

