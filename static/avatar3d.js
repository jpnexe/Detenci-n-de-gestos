/**
 * SignBridge VRM Avatar + Kalidokit Hand Engine (Three.js + @pixiv/three-vrm + Kalidokit)
 *
 * Carga el modelo VRM 0.0 (/VRoid_avatares/Haiku.vrm) con VRMLoaderPlugin,
 * lo saca de la pose T a una postura natural de lengua de señas,
 * conecta los 21 landmarks de MediaPipe mediante Kalidokit.Hand.solve()
 * a todos los huesos de muñeca y falanges con suavizado slerp,
 * activa SpringBones (vrm.update(delta)) y parpadeo automático cada 3-5s.
 */
(function () {
  const AVATAR_PRESETS = {
    haiku_vrm: {
      name: 'Haiku VRM (VRoid Studio)',
      renderStyle: 'vrm',
      vrmUrl: '/VRoid_avatares/Haiku.vrm',
      showCharacter: true,
    },
    hasune_glb: {
      name: 'Student Hatsune 3D (GLB)',
      renderStyle: 'glb',
      glbUrl: '/avatares/Student%20Hatsune.glb',
      showCharacter: true,
    },
    miku_hd: {
      name: 'Miku HD (Imagen 2.5D)',
      renderStyle: 'image_bust',
      imageUrl: '/static/models/miku_bust.png',
      showCharacter: true,
    },
  };

  class VrmSignAvatar {
    constructor() {
      this.canvas = null;
      this.renderer = null;
      this.scene = null;
      this.camera = null;
      this.enabled = true;
      this.initialized = false;
      this.config = this._loadConfig();

      this.rootGroup = null;
      this.currentVrm = null;
      this.vrmLoadedUrl = null;
      this.vrmLoading = false;

      // Fallback GLB / Imagen 2.5D
      this.fallbackGroup = null;
      this.glbModel = null;
      this.glbLoadedUrl = null;
      this.glbLoading = false;

      // Landmarks suavizados
      this.primaryTarget = null;
      this.secondaryTarget = null;
      this.primarySmooth = null;
      this.secondarySmooth = null;

      // Cache matemático y vectores reutilizables para IK/slerp sin allocations en el loop
      this._vrmRigMetrics = null;
      this._tmpEuler = null;
      this._tmpQuat = null;
      this._tmpQuat2 = null;
      this._tmpQuat3 = null;
      this._tmpMat4 = null;
      this._vSh = null;
      this._vWrist = null;
      this._vElbow = null;
      this._vToW = null;
      this._vDirW = null;
      this._vPole = null;
      this._vBend = null;
      this._vX = null;
      this._vY = null;
      this._vZ = null;
      this._vTmp1 = null;
      this._vTmp2 = null;
      this._vFdir = null;
      this._vPalm = null;
      this._vA = null;
      this._vB = null;
      this._vC = null;
      this._handPointsBuf = [];
      this._boneQuatCache = {};

      // Estado de vida del avatar (parpadeo, seguimiento al mouse, expresiones y gestos en reposo)
      this.isAnimatingText = false;
      this.currentMood = 'neutral';
      this.animPhrase = '';
      this.animSignId = '';
      this.animProgress = 0;
      this.blinkTimer = 0;
      this.nextBlinkAt = 3.2 + Math.random() * 1.8;
      this._exprValues = {
        happy: 0,
        surprised: 0,
        relaxed: 0,
        sad: 0,
        aa: 0,
        ih: 0,
        ou: 0,
      };

      // Seguimiento al mouse cuando está inactiva
      this.mouseNorm = { x: 0, y: 0 };
      this.lastPointerMoveAt = 0;

      // Comportamiento autónomo en reposo (saludar, sonreír, señas breves)
      this.idleSeconds = 0;
      this.idleAction = null;
      this.idleActionTimer = 0;
      this.idleNextActionAt = 3.8;
      this._idleActionIdx = 0;
      this._idlePtsCache = Array.from({ length: 21 }, () => [0.5, 0.72, 0]);

      // Órbita suave con mouse
      this.orbitYaw = 0;
      this.orbitPitch = 0.02;
      this.isDragging = false;
      this.lastMouse = { x: 0, y: 0 };
      this._rafId = null;
      this._lastTime = performance.now();

      window.addEventListener('three-studio-ready', () => {
        if (this.canvas && !this.initialized) {
          this.init(this.canvas);
        }
      });
    }

    _loadConfig() {
      try {
        const raw = localStorage.getItem('sb_avatar3d_vrm_cfg');
        if (raw) {
          return { ...AVATAR_PRESETS.haiku_vrm, ...JSON.parse(raw) };
        }
      } catch (e) {}
      return { ...AVATAR_PRESETS.haiku_vrm };
    }

    _saveConfig() {
      try {
        localStorage.setItem('sb_avatar3d_vrm_cfg', JSON.stringify(this.config));
      } catch (e) {}
    }

    init(canvasEl) {
      if (!canvasEl) return false;
      this.canvas = canvasEl;
      if (typeof window.THREE === 'undefined') return false;
      if (this.initialized) return true;

      const THREE = window.THREE;
      this._tmpEuler = new THREE.Euler(0, 0, 0, 'XYZ');
      this._tmpQuat = new THREE.Quaternion();
      this._tmpQuat2 = new THREE.Quaternion();
      this._tmpQuat3 = new THREE.Quaternion();
      this._tmpMat4 = new THREE.Matrix4();
      this._vSh = new THREE.Vector3();
      this._vWrist = new THREE.Vector3();
      this._vElbow = new THREE.Vector3();
      this._vToW = new THREE.Vector3();
      this._vDirW = new THREE.Vector3();
      this._vPole = new THREE.Vector3();
      this._vBend = new THREE.Vector3();
      this._vX = new THREE.Vector3();
      this._vY = new THREE.Vector3();
      this._vZ = new THREE.Vector3();
      this._vTmp1 = new THREE.Vector3();
      this._vTmp2 = new THREE.Vector3();
      this._vFdir = new THREE.Vector3();
      this._vPalm = new THREE.Vector3();
      this._vA = new THREE.Vector3();
      this._vB = new THREE.Vector3();
      this._vC = new THREE.Vector3();
      this._handPointsBuf = Array.from({ length: 21 }, () => new THREE.Vector3());

      const w = Math.max(320, this.canvas.parentElement?.clientWidth || 640);
      const h = Math.max(260, this.canvas.parentElement?.clientHeight || 420);

      this.renderer = new THREE.WebGLRenderer({
        canvas: this.canvas,
        antialias: true,
        alpha: true,
        powerPreference: 'high-performance',
      });
      this.renderer.setClearColor(0x000000, 0);
      this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      this.renderer.setSize(w, h, false);
      if ('outputColorSpace' in this.renderer && THREE.SRGBColorSpace) {
        this.renderer.outputColorSpace = THREE.SRGBColorSpace;
      }

      // Fondo de aula con desenfoque ligero y viñeta sutil para integrar el avatar 3D
      this.canvas.style.backgroundImage = "linear-gradient(rgba(10, 14, 24, 0.16), rgba(10, 14, 24, 0.30)), url('/static/models/classroom_bg.jpg')";
      this.canvas.style.backgroundSize = 'cover';
      this.canvas.style.backgroundPosition = 'center center';
      this.canvas.style.backgroundRepeat = 'no-repeat';

      this.scene = new THREE.Scene();

      // Cámara en plano medio superior (cintura hacia arriba) para ver rostro y manos grandes y claros
      this.camera = new THREE.PerspectiveCamera(28, w / h, 0.1, 30);
      this.camera.position.set(0, 1.32, 1.48);
      this.camera.lookAt(0, 1.24, 0);

      // Iluminación cálida de aula (ventana a la izquierda) sin quemar la piel
      const ambientLight = new THREE.AmbientLight(0xfffaf2, 0.78);
      this.scene.add(ambientLight);

      const hemiLight = new THREE.HemisphereLight(0xfffbeb, 0x473b2f, 0.50);
      this.scene.add(hemiLight);

      const dirLight = new THREE.DirectionalLight(0xfff5e4, 1.15);
      dirLight.position.set(-1.2, 2.2, 2.4);
      this.scene.add(dirLight);

      this.rootGroup = new THREE.Group();
      this.scene.add(this.rootGroup);

      this.fallbackGroup = new THREE.Group();
      this.rootGroup.add(this.fallbackGroup);

      this._bindPointerEvents();
      this.buildCharacter();

      this.initialized = true;
      this._resize();
      window.addEventListener('resize', () => this._resize());
      this._animate();
      return true;
    }

    _bindPointerEvents() {
      const c = this.canvas;
      if (!c) return;
      c.addEventListener('pointerdown', (e) => {
        this.isDragging = true;
        this.lastMouse = { x: e.clientX, y: e.clientY };
      });
      window.addEventListener('pointerup', () => {
        this.isDragging = false;
      });
      window.addEventListener('pointermove', (e) => {
        const vw = Math.max(1, window.innerWidth || 1);
        const vh = Math.max(1, window.innerHeight || 1);
        this.mouseNorm.x = Math.max(-1, Math.min(1, (e.clientX / vw) * 2 - 1));
        this.mouseNorm.y = Math.max(-1, Math.min(1, (e.clientY / vh) * 2 - 1));
        this.lastPointerMoveAt = performance.now();

        if (!this.isDragging) return;
        const dx = e.clientX - this.lastMouse.x;
        const dy = e.clientY - this.lastMouse.y;
        this.lastMouse = { x: e.clientX, y: e.clientY };
        this.orbitYaw = Math.max(-0.75, Math.min(0.75, this.orbitYaw + dx * 0.006));
        this.orbitPitch = Math.max(-0.20, Math.min(0.35, this.orbitPitch + dy * 0.004));
      });
      c.addEventListener('dblclick', () => {
        this.orbitYaw = 0;
        this.orbitPitch = 0.02;
      });
    }

    buildCharacter() {
      if (!this.rootGroup) return;

      // Limpiar visibilidad de modos previos
      if (this.currentVrm && this.currentVrm.scene) {
        this.currentVrm.scene.visible = false;
      }
      if (this.fallbackGroup) {
        while (this.fallbackGroup.children.length > 0) {
          this.fallbackGroup.remove(this.fallbackGroup.children[0]);
        }
      }

      if (this.config.showCharacter === false) return;

      const style = this.config.renderStyle || 'vrm';
      if (style === 'vrm') {
        this.camera.position.set(0, 1.32, 1.48);
        this.camera.lookAt(0, 1.24, 0);
        this._loadVrmModel(this.config.vrmUrl || '/VRoid_avatares/Haiku.vrm');
      } else if (style === 'image_bust') {
        this.camera.position.set(0, 0.14, 2.85);
        this.camera.lookAt(0, 0.04, 0);
        const THREE = window.THREE;
        const texLoader = new THREE.TextureLoader();
        const tex = texLoader.load(this.config.imageUrl || '/static/models/miku_bust.png');
        if ('colorSpace' in tex && THREE.SRGBColorSpace) {
          tex.colorSpace = THREE.SRGBColorSpace;
        }
        const planeMat = new THREE.MeshBasicMaterial({
          map: tex,
          transparent: true,
          alphaTest: 0.05,
          side: THREE.DoubleSide,
        });
        const bustPlane = new THREE.Mesh(new THREE.PlaneGeometry(3.15, 1.76), planeMat);
        bustPlane.position.set(0, 0.05, -0.4);
        this.fallbackGroup.add(bustPlane);
      } else if (style === 'glb') {
        if (this._glbCameraFrame) {
          this.camera.position.set(0, this._glbCameraFrame.focusY + 0.03, this._glbCameraFrame.camZ);
          this.camera.lookAt(0, this._glbCameraFrame.focusY, 0);
        } else {
          this.camera.position.set(0, 1.15, 1.58);
          this.camera.lookAt(0, 1.12, 0);
        }
        this._loadFallbackGlb(this.config.glbUrl || '/avatares/Student%20Hatsune.glb');
      }
    }

    _loadVrmModel(url) {
      const THREE = window.THREE;
      const VRM_NS = window.THREE_VRM;
      if (!THREE.GLTFLoader || !VRM_NS || !VRM_NS.VRMLoaderPlugin) {
        console.warn('VRMLoaderPlugin no disponible todavía.');
        return;
      }

      if (this.currentVrm && this.vrmLoadedUrl === url) {
        this.currentVrm.scene.visible = true;
        return;
      }
      if (this.vrmLoading) return;
      this.vrmLoading = true;

      const loader = new THREE.GLTFLoader();
      loader.crossOrigin = 'anonymous';
      loader.register((parser) => new VRM_NS.VRMLoaderPlugin(parser));

      loader.load(
        url,
        (gltf) => {
          this.vrmLoading = false;
          const vrm = gltf.userData.vrm;
          if (!vrm) {
            console.error('El archivo no contiene datos VRM válidos:', url);
            return;
          }

          // Solo rotar si es VRM 0.0 (Haiku.vrm es VRM 1.0 y ya mira hacia +Z)
          const isVrm0 = Boolean(vrm.meta && vrm.meta.metaVersion === '0');
          if (isVrm0 && VRM_NS.VRMUtils && VRM_NS.VRMUtils.rotateVRM0) {
            VRM_NS.VRMUtils.rotateVRM0(vrm);
          }

          vrm.scene.traverse((obj) => {
            obj.frustumCulled = false;
          });

          if (this.currentVrm && this.currentVrm.scene) {
            this.rootGroup.remove(this.currentVrm.scene);
          }

          this.currentVrm = vrm;
          this.vrmLoadedUrl = url;
          this._boneQuatCache = {};
          this.rootGroup.add(vrm.scene);

          // Medir posiciones reales de hombros y longitudes de segmentos en espacio normalizedHumanBonesRoot
          vrm.scene.updateMatrixWorld(true);
          const fSign = isVrm0 ? -1 : 1;
          const humRoot = vrm.humanoid?.normalizedHumanBonesRoot;
          const shR = new THREE.Vector3(-0.11 * fSign, 1.29, 0);
          const shL = new THREE.Vector3(0.11 * fSign, 1.29, 0);
          let L1R = 0.22;
          let L2R = 0.215;
          let L1L = 0.22;
          let L2L = 0.215;

          if (humRoot && vrm.humanoid) {
            humRoot.updateMatrixWorld(true);
            const readLocalPos = (boneName) => {
              const node = vrm.humanoid.getNormalizedBoneNode(boneName);
              if (!node) return null;
              const pos = new THREE.Vector3();
              node.getWorldPosition(pos);
              humRoot.worldToLocal(pos);
              return pos;
            };
            const rUp = readLocalPos('rightUpperArm');
            const rLo = readLocalPos('rightLowerArm');
            const rHa = readLocalPos('rightHand');
            if (rUp) shR.copy(rUp);
            if (rUp && rLo) L1R = Math.max(0.14, rUp.distanceTo(rLo));
            if (rLo && rHa) L2R = Math.max(0.14, rLo.distanceTo(rHa));

            const lUp = readLocalPos('leftUpperArm');
            const lLo = readLocalPos('leftLowerArm');
            const lHa = readLocalPos('leftHand');
            if (lUp) shL.copy(lUp);
            if (lUp && lLo) L1L = Math.max(0.14, lUp.distanceTo(lLo));
            if (lLo && lHa) L2L = Math.max(0.14, lLo.distanceTo(lHa));
          }
          this._vrmRigMetrics = { isVrm0, fSign, shR, shL, L1R, L2R, L1L, L2L };

          // Encuadrar cámara por bounding box del modelo (plano medio superior: cintura hacia arriba)
          const box = new THREE.Box3().setFromObject(vrm.scene);
          const size = new THREE.Vector3();
          box.getSize(size);
          const h = Math.max(0.8, size.y || 1.55);
          const focusY = box.min.y + h * 0.72;
          this.camera.position.set(0, focusY + 0.03, h * 0.94);
          this.camera.lookAt(0, focusY, 0);

          // Aplicar postura inicial relajada (fuera de T-pose)
          this._poseVrmArmAndHand('Right', null, false, 1.0);
          this._poseVrmArmAndHand('Left', null, false, 1.0);
        },
        undefined,
        (err) => {
          this.vrmLoading = false;
          console.error('Error cargando VRM:', err);
        }
      );
    }

    _loadFallbackGlb(url) {
      const THREE = window.THREE;
      if (!THREE.GLTFLoader) return;
      if (this.glbModel && this.glbLoadedUrl === url) {
        this.fallbackGroup.add(this.glbModel);
        if (this._glbCameraFrame) {
          this.camera.position.set(0, this._glbCameraFrame.focusY + 0.03, this._glbCameraFrame.camZ);
          this.camera.lookAt(0, this._glbCameraFrame.focusY, 0);
        }
        return;
      }
      if (this.glbLoading) return;
      this.glbLoading = true;
      const loader = new THREE.GLTFLoader();
      loader.load(
        url,
        (gltf) => {
          this.glbLoading = false;
          this.glbLoadedUrl = url;
          const model = gltf.scene;
          model.updateMatrixWorld(true);
          const box = new THREE.Box3().setFromObject(model);
          const size = new THREE.Vector3();
          const center = new THREE.Vector3();
          box.getSize(size);
          box.getCenter(center);
          // Escala humana proporcional (~1.55 m) apoyada sobre el suelo y = 0
          const scale = 1.55 / Math.max(0.01, size.y);
          model.scale.setScalar(scale);
          model.position.set(-center.x * scale, -box.min.y * scale, -center.z * scale);

          this.glbBones = {};
          this.glbRestQuats = {};
          this.glbPrevQuats = {};

          const texLoader = new THREE.TextureLoader();
          const shadedTex = texLoader.load('/avatares/student_hatsune_tex.png');
          shadedTex.flipY = false;
          if ('colorSpace' in shadedTex && THREE.SRGBColorSpace) {
            shadedTex.colorSpace = THREE.SRGBColorSpace;
          }

          model.updateMatrixWorld(true);
          model.traverse((obj) => {
            if (obj.isMesh) {
              obj.frustumCulled = false;
              if (obj.material && !obj.material.map) {
                obj.material = new THREE.MeshStandardMaterial({
                  map: shadedTex,
                  color: 0xffffff,
                  roughness: 0.72,
                  metalness: 0.04,
                  side: THREE.DoubleSide,
                });
              }
            }
            if (obj.isBone && obj.name) {
              this.glbBones[obj.name] = obj;
              this.glbRestQuats[obj.name] = obj.quaternion.clone();
              this.glbPrevQuats[obj.name] = obj.quaternion.clone();
            }
          });

          this.glbModel = model;
          if (this.config.renderStyle === 'glb') {
            this.fallbackGroup.add(model);
            model.updateMatrixWorld(true);
            const framedBox = new THREE.Box3().setFromObject(model);
            const framedSize = new THREE.Vector3();
            framedBox.getSize(framedSize);
            const h = Math.max(0.8, framedSize.y || 1.55);
            const focusY = framedBox.min.y + h * 0.72;
            const camZ = h * 1.02;
            this._glbCameraFrame = { focusY, camZ };
            this.camera.position.set(0, focusY + 0.03, camZ);
            this.camera.lookAt(0, focusY, 0);
          }
        },
        undefined,
        () => {
          this.glbLoading = false;
        }
      );
    }

    _setGlbBoneWorldBasis(boneName, xAxis, yAxis, zAxis, alpha = 0.35) {
      const THREE = window.THREE;
      const bone = this.glbBones?.[boneName];
      if (!bone || !bone.parent) return;
      const mat = new THREE.Matrix4().makeBasis(xAxis, yAxis, zAxis);
      const targetWorldQ = new THREE.Quaternion().setFromRotationMatrix(mat);
      const parentWorldQ = new THREE.Quaternion();
      bone.parent.getWorldQuaternion(parentWorldQ);
      const targetLocalQ = parentWorldQ.invert().multiply(targetWorldQ);
      const prevQ = this.glbPrevQuats[boneName] || bone.quaternion.clone();
      prevQ.slerp(targetLocalQ, alpha);
      bone.quaternion.copy(prevQ);
      this.glbPrevQuats[boneName] = prevQ.clone();
      bone.updateMatrixWorld(true);
    }

    _setGlbFingerHingeLocal(boneName, curlRad, splayRad = 0, rollRad = 0, alpha = 0.48) {
      const THREE = window.THREE;
      const bone = this.glbBones?.[boneName];
      const restQ = this.glbRestQuats?.[boneName];
      if (!bone || !restQ) return;
      const deltaQ = new THREE.Quaternion().setFromEuler(new THREE.Euler(curlRad, rollRad, splayRad, 'XYZ'));
      const targetLocalQ = restQ.clone().multiply(deltaQ);
      const prevQ = this.glbPrevQuats[boneName] || bone.quaternion.clone();
      prevQ.slerp(targetLocalQ, alpha);
      bone.quaternion.copy(prevQ);
      this.glbPrevQuats[boneName] = prevQ.clone();
      bone.updateMatrixWorld(true);
    }

    _poseGlbArmAndHand(sidePrefix, pts, isActive) {
      const THREE = window.THREE;
      const isRight = sidePrefix === 'Right';
      const s = isRight ? 1 : -1;
      const armName = `${sidePrefix}Arm`;
      const foreArmName = `${sidePrefix}ForeArm`;
      const handName = `${sidePrefix}Hand`;

      if (!isActive || !pts || pts.length < 21) {
        const yArmIdle = new THREE.Vector3(-0.22 * s, -0.96, 0.06).normalize();
        const xArmIdle = new THREE.Vector3(0, 0.06 * s, 0.96 * s).addScaledVector(yArmIdle, -0.05).normalize();
        const zArmIdle = new THREE.Vector3().crossVectors(xArmIdle, yArmIdle).normalize();
        this._setGlbBoneWorldBasis(armName, xArmIdle, yArmIdle, zArmIdle, 0.22);

        const yFaIdle = new THREE.Vector3(-0.18 * s, -0.94, 0.24).normalize();
        const xFaIdle = new THREE.Vector3(0, 0.24 * s, 0.94 * s).addScaledVector(yFaIdle, -0.05).normalize();
        const zFaIdle = new THREE.Vector3().crossVectors(xFaIdle, yFaIdle).normalize();
        this._setGlbBoneWorldBasis(foreArmName, xFaIdle, yFaIdle, zFaIdle, 0.22);
        return;
      }

      const worldPts = pts.map((p) => new THREE.Vector3((p[0] - 0.5) * 1.8, -(p[1] - 0.5) * 1.5, -(p[2] || 0) * 1.1));
      const wrist = worldPts[0];
      const wx = Math.max(-0.35, Math.min(0.35, wrist.x));
      const wy = Math.max(-0.35, Math.min(0.35, wrist.y));

      const yArm = new THREE.Vector3(-0.20 * s + wx * 0.10, -0.86 + wy * 0.10, 0.42).normalize();
      const xArm = new THREE.Vector3(0, 0.42 * s, 0.86 * s);
      xArm.addScaledVector(yArm, -xArm.dot(yArm)).normalize();
      const zArm = new THREE.Vector3().crossVectors(xArm, yArm).normalize();
      this._setGlbBoneWorldBasis(armName, xArm, yArm, zArm, 0.30);

      const yFa = new THREE.Vector3(0.08 * s + wx * 0.18, 0.74 + wy * 0.20, 0.65).normalize();
      const zFa = new THREE.Vector3(0, -0.65, 0.74);
      zFa.addScaledVector(yFa, -zFa.dot(yFa)).normalize();
      const xFa = new THREE.Vector3().crossVectors(yFa, zFa).normalize();
      this._setGlbBoneWorldBasis(foreArmName, xFa, yFa, zFa, 0.34);

      const yHand = new THREE.Vector3().subVectors(worldPts[9], worldPts[0]).normalize();
      const zHand = new THREE.Vector3((worldPts[5].x - worldPts[17].x) * 0.25, (worldPts[9].z - worldPts[0].z) * 0.65, 0.92);
      zHand.addScaledVector(yHand, -zHand.dot(yHand)).normalize();
      const xHand = new THREE.Vector3().crossVectors(yHand, zHand).normalize();
      this._setGlbBoneWorldBasis(handName, xHand, yHand, zHand, 0.45);

      const fingerSpecs = [
        ['Index', 5, 6, 7, 8, -0.02],
        ['Middle', 9, 10, 11, 12, 0.0],
        ['Ring', 13, 14, 15, 16, 0.02],
        ['Pinky', 17, 18, 19, 20, 0.05],
      ];
      for (const [fName, i0, i1, i2, i3, baseSplay] of fingerSpecs) {
        const v1 = new THREE.Vector3().subVectors(worldPts[i1], worldPts[i0]).normalize();
        const v2 = new THREE.Vector3().subVectors(worldPts[i2], worldPts[i1]).normalize();
        const v3 = new THREE.Vector3().subVectors(worldPts[i3], worldPts[i2]).normalize();
        const a1 = Math.max(0, yHand.angleTo(v1) - 0.14);
        const a2 = Math.max(0, v1.angleTo(v2) - 0.08);
        const a3 = Math.max(0, v2.angleTo(v3) - 0.08);
        const mcpBoost = a2 > 1.0 ? (a2 - 1.0) * 0.42 : 0;
        const curl1 = Math.max(0, Math.min(1.25, a1 * 1.15 + mcpBoost));
        const curl2 = Math.max(0, Math.min(1.48, a2 * 0.80));
        const curl3 = Math.max(0, Math.min(1.15, a3 * 0.85));
        const extFactor = Math.max(0, 1.0 - curl1 / 0.75);
        const lat = v1.x - yHand.x;
        const splay = Math.max(-0.26, Math.min(0.26, (lat * 0.70 + baseSplay) * s * extFactor));
        this._setGlbFingerHingeLocal(`${sidePrefix}Hand${fName}1`, curl1, splay, 0, 0.52);
        this._setGlbFingerHingeLocal(`${sidePrefix}Hand${fName}2`, curl2, 0, 0, 0.52);
        this._setGlbFingerHingeLocal(`${sidePrefix}Hand${fName}3`, curl3, 0, 0, 0.52);
      }
    }

    _updateGlbPose(t) {
      if (!this.glbModel) return;
      const spine = this.glbBones?.['Spine1'] || this.glbBones?.['Spine'];
      if (spine && this.glbRestQuats[spine.name]) {
        spine.quaternion.copy(this.glbRestQuats[spine.name]);
        spine.rotation.x += Math.sin(t * 1.8) * 0.006;
      }
      const head = this.glbBones?.['Head'];
      if (head && this.glbRestQuats['Head']) {
        head.quaternion.copy(this.glbRestQuats['Head']);
        head.rotation.x += this.isAnimatingText ? Math.sin(t * 3.5) * 0.015 : Math.sin(t * 1.2) * 0.008;
        head.rotation.y += Math.sin(t * 0.6) * 0.012;
      }
      this.glbModel.updateMatrixWorld(true);
      this._poseGlbArmAndHand('Right', this.primarySmooth, Boolean(this.primarySmooth));
      this._poseGlbArmAndHand('Left', this.secondarySmooth, Boolean(this.secondarySmooth));
    }

    /**
     * Slerp suave hacia una rotación Euler (en radianes) sobre un hueso humanoide VRM normalizado.
     */
    _slerpVrmBoneEuler(boneName, rx, ry, rz, alpha = 0.25) {
      if (!this.currentVrm || !this.currentVrm.humanoid) return;
      const node = this.currentVrm.humanoid.getNormalizedBoneNode(boneName);
      if (!node) return;

      this._tmpEuler.set(rx, ry, rz, 'XYZ');
      this._tmpQuat.setFromEuler(this._tmpEuler);

      let cached = this._boneQuatCache[boneName];
      if (!cached) {
        cached = node.quaternion.clone();
        this._boneQuatCache[boneName] = cached;
      }
      cached.slerp(this._tmpQuat, alpha);
      node.quaternion.copy(cached);
    }

    /**
     * Proyecta y ortonormaliza un vector deseado contra `refAxis` (Gram-Schmidt).
     */
    _orthoAxis(desired, refAxis, out, fallback) {
      out.copy(desired).addScaledVector(refAxis, -desired.dot(refAxis));
      if (out.lengthSq() < 1e-6) {
        out.copy(fallback).addScaledVector(refAxis, -fallback.dot(refAxis));
      }
      if (out.lengthSq() < 1e-8) {
        out.set(0, 1, 0);
      }
      return out.normalize();
    }

    /**
     * Orienta un hueso VRM normalizado hacia una base ortonormal (xAxis, yAxis, zAxis)
     * definida en el espacio local de normalizedHumanBonesRoot, con slerp suave.
     */
    _slerpVrmBoneWorldBasis(boneName, xAxis, yAxis, zAxis, alpha = 0.25) {
      const hum = this.currentVrm?.humanoid;
      if (!hum) return;
      const node = hum.getNormalizedBoneNode(boneName);
      if (!node) return;

      this._tmpMat4.makeBasis(xAxis, yAxis, zAxis);
      this._tmpQuat.setFromRotationMatrix(this._tmpMat4);

      const humRoot = hum.normalizedHumanBonesRoot;
      if (humRoot) {
        humRoot.updateMatrixWorld(true);
        humRoot.getWorldQuaternion(this._tmpQuat3);
        this._tmpQuat.premultiply(this._tmpQuat3);
      }

      if (node.parent) {
        node.parent.updateMatrixWorld(true);
        node.parent.getWorldQuaternion(this._tmpQuat2);
        this._tmpQuat2.invert().multiply(this._tmpQuat);
      } else {
        this._tmpQuat2.copy(this._tmpQuat);
      }

      let cached = this._boneQuatCache[boneName];
      if (!cached) {
        cached = node.quaternion.clone();
        this._boneQuatCache[boneName] = cached;
      }
      cached.slerp(this._tmpQuat2, alpha);
      node.quaternion.copy(cached);
      node.updateMatrixWorld(true);
    }

    /**
     * Cinemática inversa analítica de 2 huesos (Hombro -> Codo -> Muñeca) y orientación
     * anatómica de la palma para VRM 1.0 y VRM 0.0, manteniendo los brazos al frente.
     */
    _poseVrmArmAndHand(side, pts, isActive, alpha = 0.24) {
      const THREE = window.THREE;
      const m = this._vrmRigMetrics;
      const hum = this.currentVrm?.humanoid;
      if (!m || !hum) return;

      const isRight = (side === 'Right');
      const s = isRight ? 1 : -1;
      const prefix = isRight ? 'right' : 'left';
      const fSign = m.fSign;
      const humRoot = hum.normalizedHumanBonesRoot;
      const shRest = isRight ? m.shR : m.shL;
      const L1 = isRight ? m.L1R : m.L1L;
      const L2 = isRight ? m.L2R : m.L2L;

      if (!isActive || !pts || pts.length < 21) {
        // Postura relajada con brazos abajo y levemente hacia adelante
        this._vDirW.set(-0.20 * s * fSign, -0.97, 0.08 * fSign).normalize();
        this._vX.copy(this._vDirW).multiplyScalar(-s * fSign);
        this._vTmp1.set(0, 0.08, 0.99 * fSign);
        this._vTmp2.set(0, 1, 0);
        this._orthoAxis(this._vTmp1, this._vX, this._vZ, this._vTmp2);
        this._vY.crossVectors(this._vZ, this._vX).normalize();
        this._slerpVrmBoneWorldBasis(`${prefix}UpperArm`, this._vX, this._vY, this._vZ, alpha);

        this._vDirW.set(-0.12 * s * fSign, -0.93, 0.34 * fSign).normalize();
        this._vX.copy(this._vDirW).multiplyScalar(-s * fSign);
        this._vTmp1.set(0.25 * s * fSign, 0.32, 0.91 * fSign);
        this._vTmp2.set(0, 1, 0);
        this._orthoAxis(this._vTmp1, this._vX, this._vZ, this._vTmp2);
        this._vY.crossVectors(this._vZ, this._vX).normalize();
        this._slerpVrmBoneWorldBasis(`${prefix}LowerArm`, this._vX, this._vY, this._vZ, alpha);

        this._slerpVrmBoneEuler(`${prefix}Hand`, 0, 0, 0, alpha);

        const curlSign = s * fSign;
        for (const fName of ['Index', 'Middle', 'Ring', 'Little']) {
          this._slerpVrmBoneEuler(`${prefix}${fName}Proximal`, 0, 0, 0.14 * curlSign, alpha);
          this._slerpVrmBoneEuler(`${prefix}${fName}Intermediate`, 0, 0, 0.18 * curlSign, alpha);
          this._slerpVrmBoneEuler(`${prefix}${fName}Distal`, 0, 0, 0.10 * curlSign, alpha);
        }
        const hasIntermediate = Boolean(hum.getNormalizedBoneNode(`${prefix}ThumbIntermediate`));
        const tb0 = hasIntermediate ? `${prefix}ThumbProximal` : `${prefix}ThumbMetacarpal`;
        const tb1 = hasIntermediate ? `${prefix}ThumbIntermediate` : `${prefix}ThumbProximal`;
        const tb2 = `${prefix}ThumbDistal`;
        this._slerpVrmBoneEuler(tb0, 0.22, -0.15 * curlSign, 0.08 * curlSign, alpha);
        this._slerpVrmBoneEuler(tb1, 0, -0.12 * curlSign, 0, alpha);
        this._slerpVrmBoneEuler(tb2, 0, -0.08 * curlSign, 0, alpha);
        return;
      }

      // Leer ancla actual del hombro en espacio normalizedHumanBonesRoot
      const upperNode = hum.getNormalizedBoneNode(`${prefix}UpperArm`);
      if (upperNode && humRoot) {
        upperNode.getWorldPosition(this._vSh);
        humRoot.worldToLocal(this._vSh);
      } else {
        this._vSh.copy(shRest);
      }

      // Landmarks a espacio local VRM
      const hp = this._handPointsBuf;
      for (let i = 0; i < 21; i++) {
        hp[i].set(
          (pts[i][0] - 0.5) * fSign,
          -(pts[i][1] - 0.5),
          -(pts[i][2] || 0) * fSign
        );
      }

      // Calcular dirección de dedos y orientación de palma primero para guiar codo y giro del antebrazo
      this._vFdir.subVectors(hp[9], hp[0]);
      if (this._vFdir.lengthSq() < 1e-6) this._vFdir.set(0, 1, 0);
      this._vFdir.normalize();

      this._vA.subVectors(hp[5], hp[0]);
      this._vB.subVectors(hp[17], hp[0]);
      this._vC.crossVectors(this._vA, this._vB).multiplyScalar(-s * fSign);
      if (this._vC.lengthSq() > 1e-6) {
        this._vC.normalize();
        if (this._vC.z * fSign < 0) {
          this._vC.z = -this._vC.z * 0.35;
        }
      } else {
        this._vC.set(0, 0, fSign);
      }
      this._vPalm.set(0, 0, 0.88 * fSign).addScaledVector(this._vC, 0.40).normalize();

      const clamp = THREE.MathUtils.clamp;
      const downFactor = clamp(-this._vFdir.y, 0, 1);

      // Objetivo de muñeca frente al pecho (baja levemente cuando los dedos apuntan abajo para evitar quiebre)
      const shViewerX = this._vSh.x * fSign;
      const wxViewer = isRight
        ? clamp((pts[0][0] - 0.5) * 0.44 - 0.08, shViewerX - 0.14, 0.05)
        : clamp((pts[0][0] - 0.5) * 0.44 + 0.08, -0.05, shViewerX + 0.14);
      const wy = clamp(
        this._vSh.y - 0.12 + (0.68 - pts[0][1]) * 0.45 - downFactor * 0.09,
        this._vSh.y - 0.28,
        this._vSh.y + 0.18
      );
      const wzViewer = clamp(0.24 - (pts[0][2] || 0) * 0.25, 0.20, 0.29);
      this._vWrist.set(wxViewer * fSign, wy, wzViewer * fSign);

      // Solver analítico 2-bone IK (Hombro -> Codo -> Muñeca); el codo sube/sale si la mano apunta abajo
      this._vToW.subVectors(this._vWrist, this._vSh);
      const rawDist = this._vToW.length();
      const dist = clamp(rawDist, Math.abs(L1 - L2) + 0.02, (L1 + L2) * 0.96);
      if (rawDist > 1e-5) {
        this._vDirW.copy(this._vToW).divideScalar(rawDist);
      } else {
        this._vDirW.set(0, -0.4, fSign).normalize();
      }
      const cosA = clamp((L1 * L1 + dist * dist - L2 * L2) / (2 * L1 * dist), -1, 1);
      const sinA = Math.sqrt(Math.max(0, 1 - cosA * cosA));
      this._vPole.set(
        (-0.35 - 0.32 * downFactor) * s * fSign,
        -0.92 + 1.15 * downFactor,
        (-0.08 - 0.07 * downFactor) * fSign
      ).normalize();
      this._vTmp2.set(0, -1, 0);
      this._orthoAxis(this._vPole, this._vDirW, this._vBend, this._vTmp2);
      this._vElbow
        .copy(this._vSh)
        .addScaledVector(this._vDirW, L1 * cosA)
        .addScaledVector(this._vBend, L1 * sinA);

      // UpperArm
      this._vTmp1.subVectors(this._vElbow, this._vSh).normalize();
      this._vX.copy(this._vTmp1).multiplyScalar(-s * fSign);
      this._vTmp1.set(0, 0.22 + 0.20 * downFactor, 0.97 * fSign);
      this._vTmp2.set(0, 1, 0);
      this._orthoAxis(this._vTmp1, this._vX, this._vZ, this._vTmp2);
      this._vY.crossVectors(this._vZ, this._vX).normalize();
      this._slerpVrmBoneWorldBasis(`${prefix}UpperArm`, this._vX, this._vY, this._vZ, alpha);

      // Dirección del antebrazo y límite biomecánico de flexión de muñeca
      this._vToW.subVectors(this._vWrist, this._vElbow).normalize();
      const dotWrist = this._vFdir.dot(this._vToW);
      if (dotWrist < 0.08) {
        // Evita doblar la muñeca > ~85° contra el antebrazo
        this._vFdir.addScaledVector(this._vToW, 0.08 - dotWrist).normalize();
      }

      // Base objetivo de la mano (para alinear el giro/pronación del antebrazo con la muñeca)
      this._vX.copy(this._vFdir).multiplyScalar(-s * fSign);
      this._vTmp1.copy(this._vPalm).multiplyScalar(-1);
      this._vTmp2.set(0, 0, -fSign);
      this._orthoAxis(this._vTmp1, this._vX, this._vY, this._vTmp2);
      this._vBend.crossVectors(this._vX, this._vY).normalize(); // thumbAxisWorld

      // LowerArm (suaviza la torsión de la manga siguiendo el giro de la mano)
      this._vX.copy(this._vToW).multiplyScalar(-s * fSign);
      this._vTmp1.set(0.82 * s * fSign, 0.05, 0.57 * fSign).multiplyScalar(0.35).addScaledVector(this._vBend, 0.65);
      this._vTmp2.set(0, 1, 0);
      this._orthoAxis(this._vTmp1, this._vX, this._vZ, this._vTmp2);
      this._vY.crossVectors(this._vZ, this._vX).normalize();
      this._slerpVrmBoneWorldBasis(`${prefix}LowerArm`, this._vX, this._vY, this._vZ, alpha);

      // Hand (muñeca y palma orientadas sin quiebre antinatural)
      this._vX.copy(this._vFdir).multiplyScalar(-s * fSign);
      this._vTmp1.copy(this._vPalm).multiplyScalar(-1);
      this._vTmp2.set(0, 0, -fSign);
      this._orthoAxis(this._vTmp1, this._vX, this._vY, this._vTmp2);
      this._vZ.crossVectors(this._vX, this._vY).normalize();
      this._slerpVrmBoneWorldBasis(`${prefix}Hand`, this._vX, this._vY, this._vZ, Math.min(1.0, alpha * 1.45));

      // Dedos con flexión limpia hacia la palma -Y sin hiperextensión trasera
      this._applyVrmHandFingers(side, pts, this._vFdir, this._vZ, Math.min(1.0, alpha * 1.85));
    }

    /**
     * Calcula flexión, apertura lateral y oposición del pulgar desde los 21 landmarks
     * con los signos exactos verificados para VRM 1.0 y VRM 0.0.
     */
    _applyVrmHandFingers(side, rawPts, fdir, thumbAxisWorld, alpha = 0.45) {
      const THREE = window.THREE;
      const hum = this.currentVrm?.humanoid;
      if (!hum || !rawPts || rawPts.length < 21) return;

      const clamp = THREE.MathUtils.clamp;
      const isRight = (side === 'Right');
      const s = isRight ? 1 : -1;
      const fSign = this._vrmRigMetrics?.fSign ?? 1;
      const curlSign = s * fSign;
      const prefix = isRight ? 'right' : 'left';
      const hp = this._handPointsBuf;

      const fingerSpecs = [
        ['Index', 5, 6, 7, 8, 0.015],
        ['Middle', 9, 10, 11, 12, 0.0],
        ['Ring', 13, 14, 15, 16, -0.015],
        ['Little', 17, 18, 19, 20, -0.03],
      ];

      for (const [fName, i0, i1, i2, i3, baseSplay] of fingerSpecs) {
        this._vA.subVectors(hp[i1], hp[i0]).normalize();
        this._vB.subVectors(hp[i2], hp[i1]).normalize();
        this._vC.subVectors(hp[i3], hp[i2]).normalize();

        const a1 = Math.max(0, fdir.angleTo(this._vA) - 0.12);
        const a2 = Math.max(0, this._vA.angleTo(this._vB) - 0.08);
        const a3 = Math.max(0, this._vB.angleTo(this._vC) - 0.08);

        const isStraight = (a2 < 0.22 && a3 < 0.22);
        const mcpBoost = a2 > 1.0 ? (a2 - 1.0) * 0.50 : 0;
        const curl1 = clamp(isStraight ? a1 * 0.22 : (a1 * 1.15 + mcpBoost), 0, 1.38);
        const curl2 = clamp(a2 * 0.72, 0, 1.52);
        const curl3 = clamp(a3 * 1.05, 0, 1.15);

        this._vTmp1.subVectors(this._vA, fdir);
        const radial = this._vTmp1.dot(thumbAxisWorld);
        const extFactor = isStraight ? 1.0 : Math.max(0, 1.0 - curl1 / 0.80);
        const splayY = clamp(radial * 0.75 + baseSplay * 0.4, -0.26, 0.26) * extFactor * curlSign;

        this._slerpVrmBoneEuler(`${prefix}${fName}Proximal`, 0, splayY, curl1 * curlSign, alpha);
        this._slerpVrmBoneEuler(`${prefix}${fName}Intermediate`, 0, 0, curl2 * curlSign, alpha);
        this._slerpVrmBoneEuler(`${prefix}${fName}Distal`, 0, 0, curl3 * curlSign, alpha);
      }

      // Pulgar (VRM 1.0: Metacarpal -> Proximal -> Distal | VRM 0.0: Proximal -> Intermediate -> Distal)
      const hasIntermediate = Boolean(hum.getNormalizedBoneNode(`${prefix}ThumbIntermediate`));
      const b0 = hasIntermediate ? `${prefix}ThumbProximal` : `${prefix}ThumbMetacarpal`;
      const b1 = hasIntermediate ? `${prefix}ThumbIntermediate` : `${prefix}ThumbProximal`;
      const b2 = `${prefix}ThumbDistal`;

      const palmW = Math.hypot(rawPts[5][0] - rawPts[17][0], rawPts[5][1] - rawPts[17][1]) + 1e-5;
      const tToPinky = Math.hypot(rawPts[4][0] - rawPts[17][0], rawPts[4][1] - rawPts[17][1]) / palmW;
      const fold = clamp((1.75 - tToPinky) / 1.10, 0, 1);

      this._vA.subVectors(hp[2], hp[1]).normalize();
      this._vB.subVectors(hp[3], hp[2]).normalize();
      this._vC.subVectors(hp[4], hp[3]).normalize();
      const ta1 = Math.max(0, this._vA.angleTo(this._vB) - 0.10);
      const ta2 = Math.max(0, this._vB.angleTo(this._vC) - 0.10);

      this._slerpVrmBoneEuler(
        b0,
        0.12 + fold * 0.45,
        (0.28 - fold * 0.92) * curlSign,
        fold * 0.22 * curlSign,
        alpha
      );
      this._slerpVrmBoneEuler(
        b1,
        0,
        (-fold * 0.35 - clamp(ta1 * 0.45, 0, 0.55)) * curlSign,
        fold * 0.15 * curlSign,
        alpha
      );
      this._slerpVrmBoneEuler(
        b2,
        0,
        (-fold * 0.25 - clamp(ta2 * 0.65, 0, 0.85)) * curlSign,
        0,
        alpha
      );
    }

    _lerpPts(cur, target, alpha) {
      if (!target || target.length < 21) return null;
      if (!cur || cur.length < 21) {
        return target.map((p) => [p[0], p[1], p[2] || 0]);
      }
      for (let i = 0; i < 21; i++) {
        cur[i][0] += (target[i][0] - cur[i][0]) * alpha;
        cur[i][1] += (target[i][1] - cur[i][1]) * alpha;
        cur[i][2] += ((target[i][2] || 0) - cur[i][2]) * alpha;
      }
      return cur;
    }

    updateFromPacket(data) {
      if (!this.initialized) return;
      this.primaryTarget = data.landmarks && data.landmarks.length >= 21 ? data.landmarks : null;
      this.secondaryTarget = data.secondary_landmarks && data.secondary_landmarks.length >= 21 ? data.secondary_landmarks : null;

      const anim = data.conversation && data.conversation.hand_animation;
      this.isAnimatingText = Boolean(anim && anim.active);
      this.animPhrase = this.isAnimatingText ? String(anim.phrase || anim.subtitle || anim.label || '').toLowerCase() : '';
      this.animSignId = this.isAnimatingText ? String(anim.sign_id || '').toUpperCase() : '';
      this.animProgress = this.isAnimatingText ? Number(anim.progress || 0) : 0;

      if (this.primaryTarget || this.secondaryTarget || this.isAnimatingText) {
        this.idleSeconds = 0;
        this.idleAction = null;
      }

      const sid = String(data.stabilized_id || '').toUpperCase();
      const ctx = `${sid} ${this.animSignId} ${this.animPhrase}`;

      if (/S_AYUDA|G4|AYUDA|PELIGRO|EMERGENCIA|DOLOR|MAL|\bNO\b/.test(ctx)) {
        this.currentMood = 'alert';
      } else if (/AMOR|QUIERO|CORAZON|FELIZ|S_FELIZ|ALEGR/.test(ctx)) {
        this.currentMood = 'love';
      } else if (/S_HOLA|S_GRACIAS|HOLA|GRACIAS|BUENOS|BIEN|AMIG/.test(ctx)) {
        this.currentMood = 'happy';
      } else if (/S_POR_FAVOR|S_SI|POR FAVOR|PERDON|DISCULPA|\bSI\b/.test(ctx)) {
        this.currentMood = 'polite';
      } else if (/S_COMO_ESTAS|S_QUE|COMO|QUE|QUIEN|DONDE|CUANDO|\?/.test(ctx)) {
        this.currentMood = 'surprised';
      } else {
        this.currentMood = 'neutral';
      }
    }

    /**
     * Construye poses de mano (21 landmarks) para saludar o hacer señas amistosas en reposo.
     */
    _buildIdleHandPose(kind, phase, t) {
      const pts = this._idlePtsCache;
      const setP = (i, x, y, z = 0) => {
        pts[i][0] = x;
        pts[i][1] = y;
        pts[i][2] = z;
      };

      const isWave = (kind === 'wave' || kind === 'hola');
      const isGracias = (kind === 'gracias');
      const isILY = (kind === 'ily');

      const sway = isWave ? Math.sin(t * 7.2) * 0.045 : 0;
      const wx = (isWave ? 0.59 : 0.53) + sway * 0.45;
      const wy = isWave ? 0.60 : (isGracias ? 0.56 + phase * 0.16 : 0.68);
      const wz = isGracias ? -phase * 0.10 : 0;

      setP(0, wx, wy, wz);
      // Pulgar extendido
      setP(1, wx - 0.025, wy - 0.05, wz - 0.01);
      setP(2, wx - 0.055, wy - 0.10, wz - 0.02);
      setP(3, wx - 0.085, wy - 0.14, wz - 0.03);
      setP(4, wx - 0.115, wy - 0.17, wz - 0.03);

      // Índice extendido
      const tipShift = sway * 0.85;
      setP(5, wx - 0.055, wy - 0.19, wz - 0.01);
      setP(6, wx - 0.065 + tipShift * 0.4, wy - 0.27, wz - 0.01);
      setP(7, wx - 0.072 + tipShift * 0.7, wy - 0.33, wz - 0.01);
      setP(8, wx - 0.078 + tipShift, wy - 0.38, wz - 0.01);

      // Medio (extendido o plegado en ILY)
      setP(9, wx - 0.01, wy - 0.21, wz - 0.01);
      if (isILY) {
        setP(10, wx - 0.01, wy - 0.22, wz - 0.05);
        setP(11, wx - 0.01, wy - 0.17, wz - 0.07);
        setP(12, wx - 0.01, wy - 0.13, wz - 0.05);
      } else {
        setP(10, wx - 0.01 + tipShift * 0.4, wy - 0.29, wz - 0.01);
        setP(11, wx - 0.01 + tipShift * 0.7, wy - 0.35, wz - 0.01);
        setP(12, wx - 0.01 + tipShift, wy - 0.40, wz - 0.01);
      }

      // Anular (extendido o plegado en ILY)
      setP(13, wx + 0.035, wy - 0.20, wz - 0.01);
      if (isILY) {
        setP(14, wx + 0.035, wy - 0.21, wz - 0.05);
        setP(15, wx + 0.035, wy - 0.16, wz - 0.07);
        setP(16, wx + 0.035, wy - 0.12, wz - 0.05);
      } else {
        setP(14, wx + 0.042 + tipShift * 0.4, wy - 0.27, wz - 0.01);
        setP(15, wx + 0.046 + tipShift * 0.7, wy - 0.33, wz - 0.01);
        setP(16, wx + 0.05 + tipShift, wy - 0.38, wz - 0.01);
      }

      // Meñique extendido
      setP(17, wx + 0.08, wy - 0.17, wz - 0.02);
      setP(18, wx + 0.095 + tipShift * 0.4, wy - 0.23, wz - 0.02);
      setP(19, wx + 0.105 + tipShift * 0.7, wy - 0.28, wz - 0.02);
      setP(20, wx + 0.112 + tipShift, wy - 0.32, wz - 0.02);

      return pts;
    }

    _advanceIdleBehavior(dt, t, hasRealHands) {
      if (hasRealHands || this.isAnimatingText) {
        this.idleSeconds = 0;
        this.idleAction = null;
        this.idleActionTimer = 0;
        return null;
      }

      this.idleSeconds += dt;
      if (this.idleAction) {
        this.idleActionTimer += dt;
        if (this.idleActionTimer >= this.idleAction.duration) {
          this.idleAction = null;
          this.idleActionTimer = 0;
          this.idleNextActionAt = 6.5 + Math.random() * 4.5;
          this.idleSeconds = 0;
          return null;
        }
        const phase = Math.min(1, Math.max(0, this.idleActionTimer / this.idleAction.duration));
        return {
          kind: this.idleAction.kind,
          phase,
          pts: this._buildIdleHandPose(this.idleAction.kind, phase, t),
        };
      }

      if (this.idleSeconds >= this.idleNextActionAt) {
        const sequence = [
          { kind: 'wave', duration: 2.8 },
          { kind: 'ily', duration: 3.0 },
          { kind: 'gracias', duration: 2.6 },
          { kind: 'hola', duration: 2.6 },
        ];
        this.idleAction = sequence[this._idleActionIdx % sequence.length];
        this._idleActionIdx += 1;
        this.idleActionTimer = 0;
      }
      return null;
    }

    applyConfig(newCfg) {
      this.config = { ...this.config, ...newCfg };
      this._saveConfig();
      if (this.initialized) {
        this.buildCharacter();
      }
    }

    applyPreset(presetKey) {
      const p = AVATAR_PRESETS[presetKey];
      if (!p) return;
      this.applyConfig(p);
    }

    _resize() {
      if (!this.canvas || !this.renderer || !this.camera) return;
      const parent = this.canvas.parentElement;
      if (!parent) return;
      const w = Math.max(300, parent.clientWidth);
      const h = Math.max(240, parent.clientHeight);
      if (this.canvas.width !== w || this.canvas.height !== h) {
        this.renderer.setSize(w, h, false);
        this.camera.aspect = w / h;
        this.camera.updateProjectionMatrix();
      }
    }

    _animate() {
      this._rafId = requestAnimationFrame(() => this._animate());
      if (!this.canvas || this.canvas.classList.contains('hidden') || !this.initialized) return;

      const now = performance.now();
      const dt = Math.min(0.05, (now - this._lastTime) / 1000);
      this._lastTime = now;
      const t = now / 1000;

      this.primarySmooth = this._lerpPts(this.primarySmooth, this.primaryTarget, 0.45);
      this.secondarySmooth = this._lerpPts(this.secondarySmooth, this.secondaryTarget, 0.45);

      if (this.rootGroup) {
        this.rootGroup.rotation.y += (this.orbitYaw - this.rootGroup.rotation.y) * 0.12;
        this.rootGroup.rotation.x += (this.orbitPitch - this.rootGroup.rotation.x) * 0.12;
      }

      if ((this.config.renderStyle || 'vrm') === 'vrm' && this.currentVrm) {
        const hasRealHands = Boolean(this.primarySmooth || this.secondarySmooth);
        const idleClip = this._advanceIdleBehavior(dt, t, hasRealHands);
        const pointerActive = (performance.now() - this.lastPointerMoveAt) < 7000;

        // 1. Respiración, seguimiento al mouse en reposo y gestos de cabeza alusivos a cada frase
        let spineX = Math.sin(t * 1.8) * 0.012;
        let spineY = 0;
        let neckX = 0;
        let neckY = 0;
        let headX = Math.sin(t * 1.3) * 0.015;
        let headY = Math.sin(t * 0.7) * 0.022;
        let headZ = 0;

        if (!hasRealHands && !this.isAnimatingText) {
          if (pointerActive) {
            const mx = this.mouseNorm.x;
            const my = this.mouseNorm.y;
            neckY += mx * 0.11;
            neckX += my * 0.06;
            headY += mx * 0.22;
            headX += my * 0.12;
            spineY += mx * 0.03;
          }
          if (idleClip) {
            if (idleClip.kind === 'wave' || idleClip.kind === 'hola' || idleClip.kind === 'ily') {
              headZ += 0.07;
              headX -= 0.04;
            } else if (idleClip.kind === 'gracias') {
              headX += Math.sin(idleClip.phase * Math.PI) * 0.12;
            }
          }
        } else if (this.isAnimatingText) {
          // Gestos alusivos de cabeza y torso al deletrear o reproducir frases
          if (this.currentMood === 'happy' || this.currentMood === 'polite' || this.currentMood === 'love') {
            headX += Math.sin(t * 4.2) * 0.055 + 0.03;
            headZ += Math.sin(t * 2.1) * 0.045;
            spineX += Math.sin(t * 2.1) * 0.018;
          } else if (this.currentMood === 'surprised') {
            headZ += 0.085;
            headY += -0.05 + Math.sin(t * 2.5) * 0.03;
            headX -= 0.03;
          } else if (this.currentMood === 'alert') {
            if (/\bno\b/.test(this.animPhrase)) {
              headY += Math.sin(t * 7.5) * 0.10;
            } else {
              headX += Math.sin(t * 5.0) * 0.04;
              spineX += 0.025;
            }
          } else {
            headX += Math.sin(t * 3.6) * 0.035;
            headY += Math.sin(t * 1.8) * 0.035;
          }
        } else if (this.currentMood === 'surprised') {
          headZ += 0.06;
        }

        this._slerpVrmBoneEuler('spine', spineX, spineY, 0, 0.14);
        this._slerpVrmBoneEuler('neck', neckX, neckY, 0, 0.14);
        this._slerpVrmBoneEuler('head', headX, headY, headZ, 0.15);

        if (this.currentVrm.humanoid?.normalizedHumanBonesRoot) {
          this.currentVrm.humanoid.normalizedHumanBonesRoot.updateMatrixWorld(true);
        }

        // 2. Asignar manos derecha/izquierda respetando lateralidad en pantalla y sin cruzar brazos
        let rightPts = null;
        let leftPts = null;
        if (this.primarySmooth && this.secondarySmooth) {
          if ((this.primarySmooth[0]?.[0] ?? 0.5) <= (this.secondarySmooth[0]?.[0] ?? 0.5)) {
            rightPts = this.primarySmooth;
            leftPts = this.secondarySmooth;
          } else {
            rightPts = this.secondarySmooth;
            leftPts = this.primarySmooth;
          }
        } else if (this.primarySmooth) {
          const p = this.primarySmooth;
          const ax = p[5][0] - p[0][0];
          const ay = -(p[5][1] - p[0][1]);
          const bx = p[17][0] - p[0][0];
          const by = -(p[17][1] - p[0][1]);
          const crossZ = ax * by - ay * bx;
          if (p[0][0] < 0.38 && crossZ > 0.004) {
            rightPts = p;
          } else {
            leftPts = p;
          }
        } else if (this.secondarySmooth) {
          rightPts = this.secondarySmooth;
        } else if (idleClip) {
          leftPts = idleClip.pts;
        }

        // 3. IK 2-huesos en frente del pecho + orientación de palma y dedos
        this._poseVrmArmAndHand('Right', rightPts, Boolean(rightPts), 0.26);
        this._poseVrmArmAndHand('Left', leftPts, Boolean(leftPts), idleClip ? 0.18 : 0.26);

        // 4. Parpadeo automático sutil cada 3 a 5 segundos + expresiones y articulación suave
        this.blinkTimer += dt;
        let blinkVal = 0.0;
        if (this.blinkTimer >= this.nextBlinkAt) {
          const blinkPhase = (this.blinkTimer - this.nextBlinkAt) / 0.16;
          if (blinkPhase < 1.0) {
            blinkVal = Math.sin(blinkPhase * Math.PI);
          } else {
            this.blinkTimer = 0;
            this.nextBlinkAt = 3.0 + Math.random() * 2.0;
          }
        }

        let targetHappy = 0.08; // micro-sonrisa natural permanente
        let targetSurprised = 0.0;
        let targetRelaxed = 0.10;
        let targetSad = 0.0;
        let targetAa = 0.0;
        let targetIh = 0.0;
        let targetOu = 0.0;

        if (idleClip) {
          targetHappy = idleClip.kind === 'ily' ? 0.78 : 0.66;
          targetRelaxed = 0.25;
        } else if (this.currentMood === 'love') {
          targetHappy = 0.78;
          targetRelaxed = 0.20;
        } else if (this.currentMood === 'happy') {
          targetHappy = 0.62;
        } else if (this.currentMood === 'polite') {
          targetHappy = 0.42;
          targetRelaxed = 0.30;
        } else if (this.currentMood === 'surprised') {
          targetHappy = 0.0;
          targetSurprised = 0.48;
          targetRelaxed = 0.0;
        } else if (this.currentMood === 'alert') {
          targetHappy = 0.0;
          targetSad = 0.28;
          targetSurprised = 0.22;
          targetRelaxed = 0.0;
        }

        if (this.isAnimatingText) {
          // Articulación labial sutil sincronizada mientras deletrea o firma frases
          const talkWave = Math.max(0, Math.sin(t * 7.5));
          const vowelIdx = Math.floor(t * 3.2) % 3;
          targetAa = vowelIdx === 0 ? talkWave * 0.20 : 0.0;
          targetIh = vowelIdx === 1 ? talkWave * 0.18 : 0.0;
          targetOu = vowelIdx === 2 ? talkWave * 0.16 : 0.0;
        }

        const exprAlpha = Math.min(1.0, dt * 7.5);
        const lerpE = (key, target) => {
          this._exprValues[key] += (target - this._exprValues[key]) * exprAlpha;
          return this._exprValues[key];
        };

        if (this.currentVrm.expressionManager) {
          this.currentVrm.expressionManager.setValue('blink', blinkVal);
          this.currentVrm.expressionManager.setValue('happy', lerpE('happy', targetHappy));
          this.currentVrm.expressionManager.setValue('surprised', lerpE('surprised', targetSurprised));
          this.currentVrm.expressionManager.setValue('relaxed', lerpE('relaxed', targetRelaxed));
          this.currentVrm.expressionManager.setValue('sad', lerpE('sad', targetSad));
          this.currentVrm.expressionManager.setValue('aa', lerpE('aa', targetAa));
          this.currentVrm.expressionManager.setValue('ih', lerpE('ih', targetIh));
          this.currentVrm.expressionManager.setValue('ou', lerpE('ou', targetOu));
        }

        // 5. Actualizar SpringBones (cabello/ropa) y expresiones del VRM
        this.currentVrm.update(dt);
      } else if ((this.config.renderStyle || 'vrm') === 'glb' && this.glbModel) {
        this._updateGlbPose(t);
      }

      this._resize();
      this.renderer.render(this.scene, this.camera);
    }
  }

  window.SignBridgeAvatar3D = new VrmSignAvatar();
  window.SIGNBRIDGE_AVATAR_PRESETS = AVATAR_PRESETS;
})();
