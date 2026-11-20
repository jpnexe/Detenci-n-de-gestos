/**
 * SignBridge 3D Anime Avatar ("Mona China") + Volumetric Hands Engine (Three.js)
 * Renderiza un personaje estilo anime/videojuego personalizable con rostro expresivo,
 * parpadeo, cabello configurable, accesorios (audífonos gamer, orejas kitsune/neko, moño)
 * y manos 3D volumétricas conectadas en tiempo real a los 21 landmarks (x, y, z).
 */
(function () {
  const HAND_CONNECTIONS = [
    [0, 1], [1, 2], [2, 3], [3, 4],
    [0, 5], [5, 6], [6, 7], [7, 8],
    [0, 9], [9, 10], [10, 11], [11, 12],
    [0, 13], [13, 14], [14, 15], [15, 16],
    [0, 17], [17, 18], [18, 19], [19, 20],
    [5, 9], [9, 13], [13, 17],
  ];

  const PALM_TRIS = [
    [0, 1, 5], [0, 5, 9], [0, 9, 13], [0, 13, 17],
  ];

  const AVATAR_PRESETS = {
    hasune_glb: {
      name: 'Hasune 3D (GLB Cuerpo Completo)',
      renderStyle: 'glb',
      glbUrl: '/avatares/Hasune%20avatar.glb',
      hairStyle: 'twintails',
      accessory: 'headphones',
      hairColor: '#22D3EE',
      eyeColor: '#00F0FF',
      skinColor: '#FCE0D2',
      outfitColor: '#28303D',
      accentColor: '#22D3EE',
      gloveColor: '#FCE0D2',
      nailColor: '#22D3EE',
      showCharacter: true,
    },
    miku_hd: {
      name: 'Miku HD (Imagen Anime)',
      renderStyle: 'image_bust',
      imageUrl: '/static/models/miku_bust.png',
      hairStyle: 'twintails',
      accessory: 'headphones',
      hairColor: '#22D3EE',
      eyeColor: '#00F0FF',
      skinColor: '#FCE0D2',
      outfitColor: '#28303D',
      accentColor: '#22D3EE',
      gloveColor: '#FCE0D2',
      nailColor: '#22D3EE',
      showCharacter: true,
    },
    cyber_miku: {
      name: 'Cyber-Miku (3D Procedural)',
      renderStyle: 'procedural',
      hairStyle: 'twintails',
      accessory: 'headphones',
      hairColor: '#22D3EE',
      eyeColor: '#00F0FF',
      skinColor: '#FDE2D4',
      outfitColor: '#1E293B',
      accentColor: '#00FF9D',
      gloveColor: '#0F172A',
      nailColor: '#00F0FF',
      showCharacter: true,
    },
    sakura: {
      name: 'Sakura (Anime Clásica)',
      renderStyle: 'procedural',
      hairStyle: 'bob',
      accessory: 'ribbon',
      hairColor: '#F472B6',
      eyeColor: '#8B5CF6',
      skinColor: '#FFE8DC',
      outfitColor: '#F1F5F9',
      accentColor: '#FB7185',
      gloveColor: '#FFE8DC',
      nailColor: '#FB7185',
      showCharacter: true,
    },
    kitsune: {
      name: 'Kitsune (RPG Fantasía)',
      renderStyle: 'procedural',
      hairStyle: 'long',
      accessory: 'ears',
      hairColor: '#E2E8F0',
      eyeColor: '#F59E0B',
      skinColor: '#FFE6D8',
      outfitColor: '#991B1B',
      accentColor: '#FBBF24',
      gloveColor: '#7F1D1D',
      nailColor: '#FBBF24',
      showCharacter: true,
    },
    shadow: {
      name: 'Shadow (Ninja Cyber)',
      renderStyle: 'procedural',
      hairStyle: 'ponytail',
      accessory: 'headphones',
      hairColor: '#312E81',
      eyeColor: '#10B981',
      skinColor: '#F5D5C6',
      outfitColor: '#090D16',
      accentColor: '#A855F7',
      gloveColor: '#1E1B4B',
      nailColor: '#A855F7',
      showCharacter: true,
    },
  };

  class AnimeAvatar3D {
    constructor() {
      this.canvas = null;
      this.renderer = null;
      this.scene = null;
      this.camera = null;
      this.enabled = true;
      this.initialized = false;
      this.config = this._loadConfig();

      this.rootGroup = null;
      this.charGroup = null;
      this.glbGroup = null;
      this.glbModel = null;
      this.glbBones = {};
      this.glbRestQuats = {};
      this.glbRestDirs = {};
      this.glbPrevQuats = {};
      this.glbLoadedUrl = null;
      this.glbLoading = false;
      this.headGroup = null;
      this.leftEye = null;
      this.rightEye = null;
      this.mouthMesh = null;
      this.hairParts = [];

      this.primaryHand = null;
      this.secondaryHand = null;
      this.primaryTarget = null;
      this.secondaryTarget = null;
      this.primarySmooth = null;
      this.secondarySmooth = null;

      this.isAnimatingText = false;
      this.currentMood = 'neutral'; // neutral | happy | surprised | alert
      this.blinkTimer = 0;
      this.nextBlinkAt = 2.8;
      this.orbitYaw = 0;
      this.orbitPitch = 0.04;
      this.isDragging = false;
      this.lastMouse = { x: 0, y: 0 };
      this._rafId = null;
      this._lastTime = performance.now();
    }

    _loadConfig() {
      try {
        const raw = localStorage.getItem('sb_avatar3d_cfg_v3');
        if (raw) {
          return { ...AVATAR_PRESETS.hasune_glb, ...JSON.parse(raw) };
        }
      } catch (e) {}
      return { ...AVATAR_PRESETS.hasune_glb };
    }

    _saveConfig() {
      try {
        localStorage.setItem('sb_avatar3d_cfg_v3', JSON.stringify(this.config));
      } catch (e) {}
    }

    init(canvasEl) {
      if (!canvasEl || typeof window.THREE === 'undefined') return false;
      this.canvas = canvasEl;
      if (this.initialized) return true;

      const THREE = window.THREE;
      this.renderer = new THREE.WebGLRenderer({
        canvas: this.canvas,
        antialias: true,
        alpha: true,
      });
      this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      if ('outputColorSpace' in this.renderer && THREE.SRGBColorSpace) {
        this.renderer.outputColorSpace = THREE.SRGBColorSpace;
      } else if ('outputEncoding' in this.renderer && THREE.sRGBEncoding) {
        this.renderer.outputEncoding = THREE.sRGBEncoding;
      }

      this.scene = new THREE.Scene();
      this.camera = new THREE.PerspectiveCamera(36, 16 / 10, 0.1, 50);
      this.camera.position.set(0, 0.25, 3.6);
      this.camera.lookAt(0, 0.08, 0);

      // Iluminación estilo anime/estudio
      const ambient = new THREE.AmbientLight(0xdbeafe, 0.95);
      this.scene.add(ambient);

      const keyLight = new THREE.DirectionalLight(0xffffff, 1.15);
      keyLight.position.set(2.2, 3.2, 3.5);
      this.scene.add(keyLight);

      const rimCyan = new THREE.PointLight(0x00f0ff, 1.3, 9);
      rimCyan.position.set(-2.4, 1.5, -1.5);
      this.scene.add(rimCyan);

      const rimEmerald = new THREE.PointLight(0x00ff9d, 0.9, 9);
      rimEmerald.position.set(2.4, -0.5, -1.2);
      this.scene.add(rimEmerald);

      // Grid futurista sutil en el fondo
      const grid = new THREE.GridHelper(6, 18, 0x0e7490, 0x162032);
      grid.position.y = -1.35;
      this.scene.add(grid);

      this.rootGroup = new THREE.Group();
      this.scene.add(this.rootGroup);

      this.buildCharacter();
      this.primaryHand = this._createHandRig(false);
      this.secondaryHand = this._createHandRig(true);
      this.rootGroup.add(this.primaryHand.group);
      this.rootGroup.add(this.secondaryHand.group);
      this.secondaryHand.group.visible = false;

      this._bindPointerEvents();
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
        if (!this.isDragging) return;
        const dx = e.clientX - this.lastMouse.x;
        const dy = e.clientY - this.lastMouse.y;
        this.lastMouse = { x: e.clientX, y: e.clientY };
        this.orbitYaw = Math.max(-0.75, Math.min(0.75, this.orbitYaw + dx * 0.006));
        this.orbitPitch = Math.max(-0.25, Math.min(0.45, this.orbitPitch + dy * 0.004));
      });
      c.addEventListener('dblclick', () => {
        this.orbitYaw = 0;
        this.orbitPitch = 0.04;
      });
    }

    _toonMat(hex, opts = {}) {
      const THREE = window.THREE;
      return new THREE.MeshStandardMaterial({
        color: new THREE.Color(hex),
        roughness: opts.roughness ?? 0.55,
        metalness: opts.metalness ?? 0.08,
        emissive: opts.emissive ? new THREE.Color(opts.emissive) : new THREE.Color(0x000000),
        emissiveIntensity: opts.emissiveIntensity ?? 0.0,
      });
    }

    buildCharacter() {
      const THREE = window.THREE;
      if (this.charGroup) {
        this.rootGroup.remove(this.charGroup);
      }
      this.headGroup = null;
      this.leftEye = null;
      this.rightEye = null;
      this.mouthMesh = null;

      this.charGroup = new THREE.Group();
      this.charGroup.visible = this.config.showCharacter !== false;
      this.rootGroup.add(this.charGroup);

      // Modo Modelo 3D Real (.glb) con esqueleto Mixamo
      if (this.config.renderStyle === 'glb') {
        this._loadGlbModel(this.config.glbUrl || '/avatares/Hasune%20avatar.glb');
        return;
      }

      // Modo Busto Anime HD (basado en la imagen del usuario)
      if ((this.config.renderStyle || 'image_bust') === 'image_bust') {
        this.charGroup.position.set(0, -0.02, -0.52);
        const texLoader = new THREE.TextureLoader();
        const tex = texLoader.load(this.config.imageUrl || '/static/models/miku_bust.png');
        if ('colorSpace' in tex && THREE.SRGBColorSpace) {
          tex.colorSpace = THREE.SRGBColorSpace;
        } else if ('encoding' in tex && THREE.sRGBEncoding) {
          tex.encoding = THREE.sRGBEncoding;
        }
        const planeMat = new THREE.MeshBasicMaterial({
          map: tex,
          transparent: true,
          alphaTest: 0.05,
          side: THREE.DoubleSide,
        });
        const bustPlane = new THREE.Mesh(new THREE.PlaneGeometry(3.25, 1.82), planeMat);
        bustPlane.position.set(0, 0.05, 0);
        this.charGroup.add(bustPlane);

        // Halo neón sutil detrás del personaje
        const auraGeo = new THREE.RingGeometry(0.72, 0.76, 48);
        const auraMat = new THREE.MeshBasicMaterial({
          color: new THREE.Color(this.config.accentColor || '#22D3EE'),
          transparent: true,
          opacity: 0.28,
          side: THREE.DoubleSide,
        });
        const aura = new THREE.Mesh(auraGeo, auraMat);
        aura.position.set(0, 0.16, -0.08);
        this.charGroup.add(aura);
        return;
      }

      this.charGroup.position.set(0, -0.05, -0.58);

      const skinMat = this._toonMat(this.config.skinColor, { roughness: 0.65 });
      const hairMat = this._toonMat(this.config.hairColor, { roughness: 0.42 });
      const outfitMat = this._toonMat(this.config.outfitColor, { roughness: 0.6 });
      const accentMat = this._toonMat(this.config.accentColor, {
        roughness: 0.3,
        emissive: this.config.accentColor,
        emissiveIntensity: 0.35,
      });
      const eyeMat = this._toonMat(this.config.eyeColor, {
        roughness: 0.15,
        emissive: this.config.eyeColor,
        emissiveIntensity: 0.25,
      });
      const darkMat = this._toonMat('#0F172A', { roughness: 0.4 });
      const whiteMat = this._toonMat('#FFFFFF', { roughness: 0.2 });
      const blushMat = this._toonMat('#FDA4AF', { roughness: 0.8 });

      // Torso y hombros estilizados
      const torso = new THREE.Mesh(new THREE.CylinderGeometry(0.24, 0.31, 0.72, 20), outfitMat);
      torso.position.set(0, -0.58, 0);
      this.charGroup.add(torso);

      const collar = new THREE.Mesh(new THREE.TorusGeometry(0.18, 0.032, 12, 24), accentMat);
      collar.rotation.x = Math.PI / 2;
      collar.position.set(0, -0.23, 0.01);
      this.charGroup.add(collar);

      // Hombros
      [-1, 1].forEach((side) => {
        const sh = new THREE.Mesh(new THREE.SphereGeometry(0.11, 14, 14), outfitMat);
        sh.position.set(side * 0.29, -0.30, 0);
        this.charGroup.add(sh);
      });

      // Cuello
      const neck = new THREE.Mesh(new THREE.CylinderGeometry(0.085, 0.095, 0.18, 16), skinMat);
      neck.position.set(0, -0.16, 0);
      this.charGroup.add(neck);

      // Cabeza anime
      this.headGroup = new THREE.Group();
      this.headGroup.position.set(0, 0.24, 0);
      this.charGroup.add(this.headGroup);

      const head = new THREE.Mesh(new THREE.SphereGeometry(0.36, 28, 28), skinMat);
      head.scale.set(1.02, 0.98, 0.96);
      this.headGroup.add(head);

      // Mejillas (rubor anime)
      [-1, 1].forEach((side) => {
        const blush = new THREE.Mesh(new THREE.SphereGeometry(0.048, 12, 12), blushMat);
        blush.scale.set(1.3, 0.55, 0.35);
        blush.position.set(side * 0.17, -0.055, 0.305);
        this.headGroup.add(blush);
      });

      // Ojos grandes estilo anime
      const makeEye = (side) => {
        const eg = new THREE.Group();
        eg.position.set(side * 0.135, 0.015, 0.31);
        eg.rotation.y = side * 0.22;

        const sclera = new THREE.Mesh(new THREE.SphereGeometry(0.072, 18, 18), whiteMat);
        sclera.scale.set(0.95, 1.15, 0.45);
        eg.add(sclera);

        const iris = new THREE.Mesh(new THREE.SphereGeometry(0.052, 16, 16), eyeMat);
        iris.scale.set(0.92, 1.12, 0.52);
        iris.position.set(0, -0.004, 0.018);
        eg.add(iris);

        const pupil = new THREE.Mesh(new THREE.SphereGeometry(0.025, 12, 12), darkMat);
        pupil.scale.set(0.9, 1.05, 0.6);
        pupil.position.set(0, -0.004, 0.036);
        eg.add(pupil);

        const sparkle = new THREE.Mesh(new THREE.SphereGeometry(0.015, 10, 10), whiteMat);
        sparkle.position.set(-0.02, 0.025, 0.042);
        eg.add(sparkle);

        // Pestaña superior
        const lash = new THREE.Mesh(new THREE.BoxGeometry(0.13, 0.022, 0.03), darkMat);
        lash.position.set(0, 0.074, 0.024);
        lash.rotation.z = side * -0.08;
        eg.add(lash);

        this.headGroup.add(eg);
        return eg;
      };
      this.leftEye = makeEye(-1);
      this.rightEye = makeEye(1);

      // Boquita expresiva
      this.mouthMesh = new THREE.Mesh(
        new THREE.TorusGeometry(0.036, 0.009, 8, 16, Math.PI),
        this._toonMat('#EC4899', { roughness: 0.4 })
      );
      this.mouthMesh.rotation.z = Math.PI;
      this.mouthMesh.position.set(0, -0.145, 0.335);
      this.headGroup.add(this.mouthMesh);

      // Casquete base de cabello
      const hairCap = new THREE.Mesh(new THREE.SphereGeometry(0.382, 26, 26, 0, Math.PI * 2, 0, Math.PI * 0.62), hairMat);
      hairCap.rotation.x = -0.22;
      this.headGroup.add(hairCap);

      // Flequillo (bangs)
      for (let i = -3; i <= 3; i++) {
        const bang = new THREE.Mesh(new THREE.ConeGeometry(0.068, 0.22, 8), hairMat);
        bang.position.set(i * 0.072, 0.165, 0.315 - Math.abs(i) * 0.022);
        bang.rotation.x = Math.PI + 0.28;
        bang.rotation.z = i * -0.09;
        this.headGroup.add(bang);
      }

      // Mechones laterales
      [-1, 1].forEach((side) => {
        const sideLock = new THREE.Mesh(new THREE.ConeGeometry(0.075, 0.42, 10), hairMat);
        sideLock.position.set(side * 0.33, -0.06, 0.14);
        sideLock.rotation.x = Math.PI;
        sideLock.rotation.z = side * 0.12;
        this.headGroup.add(sideLock);
      });

      // Estilos de peinado
      const style = this.config.hairStyle || 'twintails';
      if (style === 'twintails') {
        [-1, 1].forEach((side) => {
          const tie = new THREE.Mesh(new THREE.TorusGeometry(0.05, 0.018, 8, 16), accentMat);
          tie.position.set(side * 0.39, 0.14, -0.06);
          tie.rotation.y = side * Math.PI / 2.4;
          this.headGroup.add(tie);

          const tail = new THREE.Mesh(new THREE.ConeGeometry(0.11, 0.72, 14), hairMat);
          tail.position.set(side * 0.46, -0.18, -0.12);
          tail.rotation.x = Math.PI;
          tail.rotation.z = side * -0.22;
          this.headGroup.add(tail);
        });
      } else if (style === 'ponytail') {
        const tie = new THREE.Mesh(new THREE.TorusGeometry(0.055, 0.018, 8, 16), accentMat);
        tie.position.set(0, 0.22, -0.35);
        this.headGroup.add(tie);

        const tail = new THREE.Mesh(new THREE.ConeGeometry(0.13, 0.75, 14), hairMat);
        tail.position.set(0, -0.08, -0.44);
        tail.rotation.x = Math.PI - 0.25;
        this.headGroup.add(tail);
      } else if (style === 'long') {
        const backHair = new THREE.Mesh(new THREE.CylinderGeometry(0.35, 0.42, 0.78, 20, 1, false, Math.PI * 0.65, Math.PI * 0.7), hairMat);
        backHair.position.set(0, -0.22, -0.06);
        this.headGroup.add(backHair);
      } else if (style === 'bob') {
        const bob = new THREE.Mesh(new THREE.SphereGeometry(0.395, 22, 22, Math.PI * 0.5, Math.PI, 0, Math.PI * 0.8), hairMat);
        bob.rotation.y = Math.PI / 2;
        bob.position.set(0, -0.03, -0.03);
        this.headGroup.add(bob);
      }

      // Accesorios
      const acc = this.config.accessory || 'headphones';
      if (acc === 'headphones') {
        const band = new THREE.Mesh(new THREE.TorusGeometry(0.41, 0.028, 10, 28, Math.PI), darkMat);
        band.position.set(0, 0.05, 0);
        this.headGroup.add(band);
        [-1, 1].forEach((side) => {
          const cup = new THREE.Mesh(new THREE.CylinderGeometry(0.11, 0.11, 0.07, 18), darkMat);
          cup.rotation.z = Math.PI / 2;
          cup.position.set(side * 0.40, 0.01, 0);
          this.headGroup.add(cup);

          const ring = new THREE.Mesh(new THREE.TorusGeometry(0.085, 0.014, 8, 20), accentMat);
          ring.rotation.y = Math.PI / 2;
          ring.position.set(side * 0.44, 0.01, 0);
          this.headGroup.add(ring);
        });
      } else if (acc === 'ears') {
        [-1, 1].forEach((side) => {
          const ear = new THREE.Mesh(new THREE.ConeGeometry(0.10, 0.24, 4), hairMat);
          ear.position.set(side * 0.23, 0.40, 0.02);
          ear.rotation.z = side * -0.28;
          ear.rotation.y = side * 0.3;
          this.headGroup.add(ear);

          const inner = new THREE.Mesh(new THREE.ConeGeometry(0.055, 0.15, 4), blushMat);
          inner.position.set(side * 0.23, 0.39, 0.045);
          inner.rotation.z = side * -0.28;
          inner.rotation.y = side * 0.3;
          this.headGroup.add(inner);
        });
      } else if (acc === 'ribbon') {
        [-1, 1].forEach((side) => {
          const wing = new THREE.Mesh(new THREE.ConeGeometry(0.075, 0.14, 6), accentMat);
          wing.position.set(side * 0.08 + 0.14, 0.37, 0.12);
          wing.rotation.z = side * Math.PI / 2.2;
          this.headGroup.add(wing);
        });
      }
    }

    _animeToonMat(hex, opts = {}) {
      const THREE = window.THREE;
      if (!this._toonGradTex) {
        // Gradiente cel-shading de 3 tonos suaves estilo anime
        const data = new Uint8Array([
          195, 195, 195, 255,
          232, 232, 232, 255,
          255, 255, 255, 255,
        ]);
        const tex = new THREE.DataTexture(data, 3, 1, THREE.RGBAFormat);
        tex.minFilter = THREE.NearestFilter;
        tex.magFilter = THREE.NearestFilter;
        tex.needsUpdate = true;
        this._toonGradTex = tex;
      }
      return new THREE.MeshToonMaterial({
        color: new THREE.Color(hex),
        gradientMap: this._toonGradTex,
        emissive: opts.emissive ? new THREE.Color(opts.emissive) : new THREE.Color(0x000000),
        emissiveIntensity: opts.emissiveIntensity ?? 0.0,
      });
    }

    _createHandRig(isSecondary) {
      const THREE = window.THREE;
      const group = new THREE.Group();
      const skinHex = this.config.skinColor || '#FCE0D2';
      const gloveHex = this.config.gloveColor || skinHex;
      const useSkin = (this.config.renderStyle || 'image_bust') === 'image_bust' || gloveHex.toLowerCase() === skinHex.toLowerCase();
      const handHex = useSkin ? skinHex : gloveHex;

      const handMat = this._animeToonMat(handHex, { emissive: handHex, emissiveIntensity: 0.14 });
      const nailMat = this._animeToonMat(this.config.nailColor || '#22D3EE', {
        emissive: this.config.nailColor || '#22D3EE',
        emissiveIntensity: 0.25,
      });
      const sleeveMat = this._animeToonMat(this.config.outfitColor || '#2D3542', { emissive: '#111827', emissiveIntensity: 0.1 });
      const cuffMat = this._animeToonMat(this.config.accentColor || '#22D3EE', {
        emissive: this.config.accentColor || '#22D3EE',
        emissiveIntensity: 0.35,
      });

      // Radios anatómicos suaves por articulación (sin bolas robóticas sobresalientes)
      const jointRadii = [
        0.036, // 0 muñeca
        0.028, 0.025, 0.022, 0.018, // 1-4 pulgar
        0.025, 0.021, 0.018, 0.015, // 5-8 índice
        0.025, 0.021, 0.018, 0.015, // 9-12 medio
        0.024, 0.020, 0.017, 0.014, // 13-16 anular
        0.022, 0.018, 0.016, 0.013, // 17-20 meñique
      ];

      const joints = [];
      const nails = [];
      const tipSet = new Set([4, 8, 12, 16, 20]);

      for (let i = 0; i < 21; i++) {
        const r = jointRadii[i];
        const mesh = new THREE.Mesh(new THREE.SphereGeometry(r, 14, 14), handMat);
        group.add(mesh);
        joints.push(mesh);

        // Uñita turquesa delicada en las puntas de los dedos (como en la imagen de Miku)
        if (tipSet.has(i)) {
          const nail = new THREE.Mesh(new THREE.SphereGeometry(r * 0.72, 10, 10), nailMat);
          nail.scale.set(0.85, 1.05, 0.45);
          group.add(nail);
          nails.push({ mesh: nail, tipIdx: i, prevIdx: i - 1, radius: r });
        }
      }

      // Segmentos cónicos continuos que empatan exactamente con el radio de cada articulación
      const bones = [];
      for (let b = 0; b < HAND_CONNECTIONS.length; b++) {
        const [i, j] = HAND_CONNECTIONS[b];
        const rA = jointRadii[i];
        const rB = jointRadii[j];
        const mesh = new THREE.Mesh(new THREE.CylinderGeometry(rB, rA, 1, 14), handMat);
        group.add(mesh);
        bones.push({ mesh, i, j });
      }

      // Palma volumétrica 3D (doble cara con grosor real para que no parezca papel)
      const palmGeo = new THREE.BufferGeometry();
      const palmVerts = new Float32Array(PALM_TRIS.length * 2 * 9);
      palmGeo.setAttribute('position', new THREE.BufferAttribute(palmVerts, 3));
      const palmMat = new THREE.MeshToonMaterial({
        color: new THREE.Color(handHex),
        gradientMap: this._toonGradTex,
        emissive: new THREE.Color(handHex),
        emissiveIntensity: 0.14,
        side: THREE.DoubleSide,
      });
      const palmMesh = new THREE.Mesh(palmGeo, palmMat);
      group.add(palmMesh);

      // Almohadilla central suave de la palma
      const palmCore = new THREE.Mesh(new THREE.SphereGeometry(0.055, 16, 16), handMat);
      palmCore.scale.set(1.25, 1.15, 0.48);
      group.add(palmCore);

      // Antebrazo con manga oscura y aro turquesa en el borde (como en la imagen)
      const forearmMesh = new THREE.Mesh(new THREE.CylinderGeometry(0.040, 0.058, 1, 16), sleeveMat);
      group.add(forearmMesh);

      const cuffRing = new THREE.Mesh(new THREE.TorusGeometry(0.043, 0.008, 10, 22), cuffMat);
      group.add(cuffRing);

      return { group, joints, nails, bones, palmMesh, palmCore, forearmMesh, cuffRing, isSecondary };
    }

    _updateHandRig(rig, pts, isSecondary) {
      if (!pts || pts.length < 21) {
        rig.group.visible = false;
        return;
      }
      rig.group.visible = true;
      const THREE = window.THREE;

      // Mapear coordenadas normalizadas [0..1] a espacio 3D frente al avatar
      const worldPts = pts.map((p) => {
        const x = (p[0] - 0.5) * 2.05;
        const y = -(p[1] - 0.54) * 1.55;
        const z = -(p[2] || 0) * 1.3 + 0.44;
        return new THREE.Vector3(x, y, z);
      });

      for (let i = 0; i < 21; i++) {
        rig.joints[i].position.copy(worldPts[i]);
      }

      // Posicionar uñitas suavemente en la punta dorsal de cada dedo
      for (const n of rig.nails) {
        const tip = worldPts[n.tipIdx];
        const prev = worldPts[n.prevIdx];
        const dir = new THREE.Vector3().subVectors(tip, prev).normalize();
        n.mesh.position.copy(tip).addScaledVector(dir, n.radius * 0.25);
        n.mesh.position.z -= n.radius * 0.42;
      }

      const up = new THREE.Vector3(0, 1, 0);
      for (const bone of rig.bones) {
        const a = worldPts[bone.i];
        const b = worldPts[bone.j];
        const dir = new THREE.Vector3().subVectors(b, a);
        const len = Math.max(0.001, dir.length());
        bone.mesh.position.copy(a).addScaledVector(dir, 0.5);
        bone.mesh.scale.set(1, len, 1);
        bone.mesh.quaternion.setFromUnitVectors(up, dir.normalize());
      }

      // Normal de la palma para darle grosor real en 3D
      const v1 = new THREE.Vector3().subVectors(worldPts[5], worldPts[0]);
      const v2 = new THREE.Vector3().subVectors(worldPts[17], worldPts[0]);
      const palmNormal = new THREE.Vector3().crossVectors(v1, v2).normalize();
      if (palmNormal.lengthSq() < 0.01) palmNormal.set(0, 0, 1);
      const halfThick = 0.022;

      const posAttr = rig.palmMesh.geometry.getAttribute('position');
      let ptr = 0;
      for (const side of [1, -1]) {
        const off = palmNormal.clone().multiplyScalar(side * halfThick);
        for (const [a, b, c] of PALM_TRIS) {
          posAttr.array[ptr++] = worldPts[a].x + off.x;
          posAttr.array[ptr++] = worldPts[a].y + off.y;
          posAttr.array[ptr++] = worldPts[a].z + off.z;
          posAttr.array[ptr++] = worldPts[b].x + off.x;
          posAttr.array[ptr++] = worldPts[b].y + off.y;
          posAttr.array[ptr++] = worldPts[b].z + off.z;
          posAttr.array[ptr++] = worldPts[c].x + off.x;
          posAttr.array[ptr++] = worldPts[c].y + off.y;
          posAttr.array[ptr++] = worldPts[c].z + off.z;
        }
      }
      posAttr.needsUpdate = true;
      rig.palmMesh.geometry.computeVertexNormals();

      // Centro de la palma
      const palmCenter = new THREE.Vector3()
        .add(worldPts[0])
        .add(worldPts[5])
        .add(worldPts[9])
        .add(worldPts[17])
        .multiplyScalar(0.25);
      rig.palmCore.position.copy(palmCenter);
      rig.palmCore.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), palmNormal);

      // Conectar manga oscura + aro turquesa desde la muñeca hacia el brazo del personaje
      if (this.config.showCharacter !== false) {
        rig.forearmMesh.visible = true;
        rig.cuffRing.visible = true;
        const shoulderX = isSecondary ? -0.34 : 0.34;
        const elbow = new THREE.Vector3(shoulderX, -0.52, -0.32);
        const wrist = worldPts[0];
        const fDir = new THREE.Vector3().subVectors(wrist, elbow);
        const fLen = Math.max(0.01, fDir.length());
        const fNorm = fDir.clone().normalize();
        // Dejar un pequeño espacio de muñeca descubierta antes de la manga
        const cuffPos = wrist.clone().addScaledVector(fNorm, -0.055);
        const sleeveDir = new THREE.Vector3().subVectors(cuffPos, elbow);
        const sleeveLen = Math.max(0.01, sleeveDir.length());
        rig.forearmMesh.position.copy(elbow).addScaledVector(sleeveDir, 0.5);
        rig.forearmMesh.scale.set(1, sleeveLen, 1);
        rig.forearmMesh.quaternion.setFromUnitVectors(up, sleeveDir.clone().normalize());

        rig.cuffRing.position.copy(cuffPos);
        rig.cuffRing.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), fNorm);
      } else {
        rig.forearmMesh.visible = false;
        rig.cuffRing.visible = false;
      }
    }

    _lerpPts(cur, target, alpha) {
      if (!target || target.length < 21) return null;
      if (!cur || cur.length < 21) {
        return target.map((p) => [p[0], p[1], p[2] || 0]);
      }
      return target.map((p, i) => [
        cur[i][0] + (p[0] - cur[i][0]) * alpha,
        cur[i][1] + (p[1] - cur[i][1]) * alpha,
        cur[i][2] + ((p[2] || 0) - cur[i][2]) * alpha,
      ]);
    }

    updateFromPacket(data) {
      if (!this.initialized) return;
      this.primaryTarget = data.landmarks && data.landmarks.length >= 21 ? data.landmarks : null;
      this.secondaryTarget = data.secondary_landmarks && data.secondary_landmarks.length >= 21 ? data.secondary_landmarks : null;

      const anim = data.conversation && data.conversation.hand_animation;
      this.isAnimatingText = Boolean(anim && anim.active);

      const sid = String(data.stabilized_id || '').toUpperCase();
      if (sid === 'G4' || sid === 'S_AYUDA') {
        this.currentMood = 'alert';
      } else if (sid === 'S_HOLA' || sid === 'S_GRACIAS' || sid === 'S_FELIZ' || sid === 'S_POR_FAVOR') {
        this.currentMood = 'happy';
      } else if (sid === 'S_COMO_ESTAS' || sid === 'S_QUE') {
        this.currentMood = 'surprised';
      } else {
        this.currentMood = 'neutral';
      }
    }

    applyConfig(newCfg) {
      this.config = { ...this.config, ...newCfg };
      this._saveConfig();
      if (this.initialized) {
        this.buildCharacter();
        // Reconstruir manos con nuevo color de piel/guantes
        this.rootGroup.remove(this.primaryHand.group);
        this.rootGroup.remove(this.secondaryHand.group);
        this.primaryHand = this._createHandRig(false);
        this.secondaryHand = this._createHandRig(true);
        this.rootGroup.add(this.primaryHand.group);
        this.rootGroup.add(this.secondaryHand.group);
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
      this.renderer.setSize(w, h, false);
      this.camera.aspect = w / h;
      this.camera.updateProjectionMatrix();
    }

    _loadGlbModel(url) {
      const THREE = window.THREE;
      if (typeof THREE.GLTFLoader === 'undefined') {
        console.warn('GLTFLoader no disponible, usando busto HD.');
        this.config.renderStyle = 'image_bust';
        this.buildCharacter();
        return;
      }
      if (this.glbModel && this.glbLoadedUrl === url) {
        this.charGroup.add(this.glbModel);
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

          // Auto-escalar y encuadrar de cintura hacia arriba para ver cara y manos claramente
          const box = new THREE.Box3().setFromObject(model);
          const size = new THREE.Vector3();
          const center = new THREE.Vector3();
          box.getSize(size);
          box.getCenter(center);

          const targetHeight = 2.65;
          const scale = targetHeight / Math.max(0.01, size.y);
          model.scale.setScalar(scale);

          // Posicionar torso/cabeza en el centro de la cámara
          model.position.set(
            -center.x * scale,
            -box.min.y * scale - 1.72,
            -center.z * scale + 0.15
          );

          // Mapear huesos Mixamo y guardar pose de descanso
          this.glbBones = {};
          this.glbRestQuats = {};
          this.glbRestDirs = {};
          this.glbPrevQuats = {};
          this.glbRestPalmNormals = {};

          model.updateMatrixWorld(true);
          model.traverse((obj) => {
            if (obj.isMesh) {
              obj.frustumCulled = false;
              if (obj.material) {
                obj.material.side = THREE.DoubleSide;
                // Mejorar definición cel-shading si el modelo viene sin texturas
                if (!obj.material.map) {
                  obj.material = this._animeToonMat('#E2E8F0', {
                    emissive: '#1E293B',
                    emissiveIntensity: 0.18,
                  });
                  obj.material.skinning = true;
                  obj.material.side = THREE.DoubleSide;
                }
              }
            }
            if (obj.isBone && obj.name) {
              this.glbBones[obj.name] = obj;
              this.glbRestQuats[obj.name] = obj.quaternion.clone();
              this.glbPrevQuats[obj.name] = obj.quaternion.clone();
            }
          });

          // Corregir pesos del cabello (coletas) para que NO se deformen al mover los brazos
          this._fixGlbHairWeights(model);

          // Calcular dirección de descanso en mundo para cada hueso respecto a su primer hijo
          const wp = new THREE.Vector3();
          const cp = new THREE.Vector3();
          for (const [bName, bone] of Object.entries(this.glbBones)) {
            const childBone = bone.children.find((c) => c.isBone);
            if (childBone) {
              bone.getWorldPosition(wp);
              childBone.getWorldPosition(cp);
              const d = cp.sub(wp);
              if (d.lengthSq() > 1e-6) {
                const invQ = new THREE.Quaternion();
                bone.getWorldQuaternion(invQ).invert();
                this.glbRestDirs[bName] = d.normalize().applyQuaternion(invQ);
              }
            }
          }

          // Guardar normal de palma en reposo para cada mano (para alinear el giro/roll)
          for (const side of ['Right', 'Left']) {
            const hBone = this.glbBones[`${side}Hand`];
            const idxBone = this.glbBones[`${side}HandIndex1`];
            const pnkBone = this.glbBones[`${side}HandPinky1`];
            if (hBone && idxBone && pnkBone) {
              const hp = new THREE.Vector3();
              const ip = new THREE.Vector3();
              const pp = new THREE.Vector3();
              hBone.getWorldPosition(hp);
              idxBone.getWorldPosition(ip);
              pnkBone.getWorldPosition(pp);
              const v1 = ip.sub(hp);
              const v2 = pp.sub(hp);
              const n = side === 'Right'
                ? new THREE.Vector3().crossVectors(v1, v2)
                : new THREE.Vector3().crossVectors(v2, v1);
              if (n.lengthSq() > 1e-6) {
                const invQ = new THREE.Quaternion();
                hBone.getWorldQuaternion(invQ).invert();
                this.glbRestPalmNormals[side] = n.normalize().applyQuaternion(invQ);
              }
            }
          }

          this.glbModel = model;
          if (this.config.renderStyle === 'glb' && this.charGroup) {
            this.charGroup.add(model);
          }
        },
        undefined,
        (err) => {
          this.glbLoading = false;
          console.error('Error cargando GLB:', err);
        }
      );
    }

    _aimBoneWorld(boneName, targetWorldDir, alpha = 0.45) {
      const THREE = window.THREE;
      const bone = this.glbBones[boneName];
      if (!bone || !bone.parent) return;

      const localAxis = this.glbRestDirs[boneName];
      let curDir = null;
      const wp = new THREE.Vector3();
      const cp = new THREE.Vector3();
      const childBone = bone.children.find((c) => c.isBone);

      if (childBone) {
        bone.getWorldPosition(wp);
        childBone.getWorldPosition(cp);
        curDir = cp.sub(wp);
      } else if (localAxis) {
        const wq = new THREE.Quaternion();
        bone.getWorldQuaternion(wq);
        curDir = localAxis.clone().applyQuaternion(wq);
      }
      if (!curDir || curDir.lengthSq() < 1e-6) return;
      curDir.normalize();

      const tDir = targetWorldDir.clone().normalize();
      const deltaWorld = new THREE.Quaternion().setFromUnitVectors(curDir, tDir);

      const boneWorldQ = new THREE.Quaternion();
      bone.getWorldQuaternion(boneWorldQ);
      const targetWorldQ = deltaWorld.multiply(boneWorldQ);

      const parentWorldQ = new THREE.Quaternion();
      bone.parent.getWorldQuaternion(parentWorldQ);
      const targetLocalQ = parentWorldQ.invert().multiply(targetWorldQ);

      const prevQ = this.glbPrevQuats[boneName] || bone.quaternion.clone();
      prevQ.slerp(targetLocalQ, alpha);
      bone.quaternion.copy(prevQ);
      this.glbPrevQuats[boneName] = prevQ.clone();
      bone.updateMatrixWorld(true);
    }

    _fixGlbHairWeights(model) {
      model.traverse((obj) => {
        if (!obj.isSkinnedMesh || !obj.skeleton || !obj.geometry) return;
        const bones = obj.skeleton.bones;
        const geo = obj.geometry;
        const pos = geo.attributes.position;
        const skinIdx = geo.attributes.skinIndex;
        const skinWgt = geo.attributes.skinWeight;
        if (!pos || !skinIdx || !skinWgt) return;

        const spine2Idx = bones.findIndex((b) => b.name === 'Spine2' || b.name === 'Spine1');
        const headIdx = bones.findIndex((b) => b.name === 'Head');
        const armBoneSet = new Set();
        bones.forEach((b, idx) => {
          if (/^(Left|Right)(Shoulder|Arm|ForeArm|Hand)/.test(b.name)) {
            armBoneSet.add(idx);
          }
        });
        if (spine2Idx < 0 || armBoneSet.size === 0) return;

        const count = pos.count;
        for (let i = 0; i < count; i++) {
          const j0 = skinIdx.getX(i);
          const j1 = skinIdx.getY(i);
          const j2 = skinIdx.getZ(i);
          const j3 = skinIdx.getW(i);
          if (!armBoneSet.has(j0) && !armBoneSet.has(j1) && !armBoneSet.has(j2) && !armBoneSet.has(j3)) {
            continue;
          }

          const vy = pos.getY(i);
          const vz = pos.getZ(i);
          // Coletas largas (debajo de las manos o detrás de los brazos) y parte alta de la cabeza
          const isLowerHair = vy < 0.76;
          const isBackHair = vz < -0.042;
          const isUpperHeadHair = vy > 1.46;

          if (isUpperHeadHair && headIdx >= 0) {
            skinIdx.setXYZW(i, headIdx, 0, 0, 0);
            skinWgt.setXYZW(i, 1, 0, 0, 0);
          } else if (isLowerHair || isBackHair) {
            skinIdx.setXYZW(i, spine2Idx, 0, 0, 0);
            skinWgt.setXYZW(i, 1, 0, 0, 0);
          }
        }
        skinIdx.needsUpdate = true;
        skinWgt.needsUpdate = true;
      });
    }

    _poseGlbArmAndHand(sidePrefix, pts, isActive) {
      const THREE = window.THREE;
      const isRight = sidePrefix === 'Right';
      const sign = isRight ? 1 : -1;

      const armName = `${sidePrefix}Arm`;
      const foreArmName = `${sidePrefix}ForeArm`;
      const handName = `${sidePrefix}Hand`;

      // Resetear a pose de descanso antes de calcular
      const chainNames = [
        `${sidePrefix}Shoulder`, armName, foreArmName, handName,
        `${sidePrefix}HandThumb1`, `${sidePrefix}HandThumb2`, `${sidePrefix}HandThumb3`,
        `${sidePrefix}HandIndex1`, `${sidePrefix}HandIndex2`, `${sidePrefix}HandIndex3`,
        `${sidePrefix}HandMiddle1`, `${sidePrefix}HandMiddle2`, `${sidePrefix}HandMiddle3`,
        `${sidePrefix}HandRing1`, `${sidePrefix}HandRing2`, `${sidePrefix}HandRing3`,
        `${sidePrefix}HandPinky1`, `${sidePrefix}HandPinky2`, `${sidePrefix}HandPinky3`,
      ];
      for (const n of chainNames) {
        if (this.glbBones[n] && this.glbRestQuats[n]) {
          this.glbBones[n].quaternion.copy(this.glbRestQuats[n]);
        }
      }
      this.glbModel.updateMatrixWorld(true);

      if (!isActive || !pts || pts.length < 21) {
        // Dejar el brazo inactivo en su pose natural de descanso (A-pose suave)
        return;
      }

      // Convertir puntos normalizados [0..1] a espacio 3D
      const worldPts = pts.map((p) => new THREE.Vector3(
        (p[0] - 0.5) * 2.0,
        -(p[1] - 0.5) * 1.6,
        -(p[2] || 0) * 1.2
      ));
      const wrist = worldPts[0];

      // Posicionar brazo y antebrazo en pose limpia de intérprete frente al pecho/hombro
      const upperArmTarget = new THREE.Vector3(
        (isRight ? -0.26 : 0.26) + wrist.x * 0.14,
        -0.55 + wrist.y * 0.22,
        0.68
      );
      this._aimBoneWorld(armName, upperArmTarget, 0.30);

      const foreArmTarget = new THREE.Vector3(
        (isRight ? 0.06 : -0.06) + wrist.x * 0.25,
        0.72 + wrist.y * 0.25,
        0.62
      );
      this._aimBoneWorld(foreArmName, foreArmTarget, 0.34);

      // Orientar la mano en 2 ejes: dirección (0->9) + giro de la palma (normal de la palma)
      const handDir = new THREE.Vector3().subVectors(worldPts[9], worldPts[0]);
      if (handDir.lengthSq() > 1e-6) {
        this._aimBoneWorld(handName, handDir, 0.45);

        const restPalmLocal = this.glbRestPalmNormals[sidePrefix];
        const hBone = this.glbBones[handName];
        if (restPalmLocal && hBone && hBone.parent) {
          const vA = new THREE.Vector3().subVectors(worldPts[5], worldPts[0]);
          const vB = new THREE.Vector3().subVectors(worldPts[17], worldPts[0]);
          const targetPalmN = isRight
            ? new THREE.Vector3().crossVectors(vA, vB)
            : new THREE.Vector3().crossVectors(vB, vA);

          if (targetPalmN.lengthSq() > 1e-6) {
            targetPalmN.normalize();
            const axis = handDir.clone().normalize();
            const hWorldQ = new THREE.Quaternion();
            hBone.getWorldQuaternion(hWorldQ);
            const curPalmN = restPalmLocal.clone().applyQuaternion(hWorldQ);

            // Proyectar ambas normales al plano perpendicular a handDir para corregir solo el giro (roll)
            const curProj = curPalmN.sub(axis.clone().multiplyScalar(curPalmN.dot(axis)));
            const tgtProj = targetPalmN.sub(axis.clone().multiplyScalar(targetPalmN.dot(axis)));
            if (curProj.lengthSq() > 1e-4 && tgtProj.lengthSq() > 1e-4) {
              curProj.normalize();
              tgtProj.normalize();
              const rollQ = new THREE.Quaternion().setFromUnitVectors(curProj, tgtProj);
              const newWorldQ = rollQ.multiply(hWorldQ);
              const parentWQ = new THREE.Quaternion();
              hBone.parent.getWorldQuaternion(parentWQ);
              const localQ = parentWQ.invert().multiply(newWorldQ);
              const prevQ = this.glbPrevQuats[handName] || hBone.quaternion.clone();
              prevQ.slerp(localQ, 0.45);
              hBone.quaternion.copy(prevQ);
              this.glbPrevQuats[handName] = prevQ.clone();
              hBone.updateMatrixWorld(true);
            }
          }
        }
      }

      // Retargeting de los 5 dedos (3 falanges cada uno)
      const fingerMap = [
        ['Thumb', 1, 2, 3, 4],
        ['Index', 5, 6, 7, 8],
        ['Middle', 9, 10, 11, 12],
        ['Ring', 13, 14, 15, 16],
        ['Pinky', 17, 18, 19, 20],
      ];
      for (const [fName, i0, i1, i2, i3] of fingerMap) {
        const d1 = new THREE.Vector3().subVectors(worldPts[i1], worldPts[i0]);
        const d2 = new THREE.Vector3().subVectors(worldPts[i2], worldPts[i1]);
        const d3 = new THREE.Vector3().subVectors(worldPts[i3], worldPts[i2]);
        if (d1.lengthSq() > 1e-6) this._aimBoneWorld(`${sidePrefix}Hand${fName}1`, d1, 0.50);
        if (d2.lengthSq() > 1e-6) this._aimBoneWorld(`${sidePrefix}Hand${fName}2`, d2, 0.50);
        if (d3.lengthSq() > 1e-6) this._aimBoneWorld(`${sidePrefix}Hand${fName}3`, d3, 0.50);
      }
    }

    _updateGlbPose(t) {
      if (!this.glbModel) return;
      const THREE = window.THREE;

      // Respiración y movimiento sutil de cabeza/torso
      const spine = this.glbBones['Spine1'] || this.glbBones['Spine'];
      if (spine && this.glbRestQuats[spine.name]) {
        spine.quaternion.copy(this.glbRestQuats[spine.name]);
        spine.rotation.x += Math.sin(t * 2.0) * 0.015;
      }
      const head = this.glbBones['Head'];
      if (head && this.glbRestQuats['Head']) {
        head.quaternion.copy(this.glbRestQuats['Head']);
        head.rotation.x += this.isAnimatingText ? Math.sin(t * 5.0) * 0.04 : Math.sin(t * 1.4) * 0.018;
        head.rotation.y += Math.sin(t * 0.8) * 0.035;
        head.rotation.z += this.currentMood === 'surprised' ? 0.08 : 0;
      }
      this.glbModel.updateMatrixWorld(true);

      this._poseGlbArmAndHand('Right', this.primarySmooth, Boolean(this.primarySmooth));
      this._poseGlbArmAndHand('Left', this.secondarySmooth, Boolean(this.secondarySmooth));
    }

    _animate() {
      this._rafId = requestAnimationFrame(() => this._animate());
      if (!this.canvas || this.canvas.classList.contains('hidden')) return;

      const now = performance.now();
      const dt = Math.min(0.05, (now - this._lastTime) / 1000);
      this._lastTime = now;
      const t = now / 1000;

      const isGlbMode = (this.config.renderStyle === 'glb');

      // Suavizado de manos
      this.primarySmooth = this._lerpPts(this.primarySmooth, this.primaryTarget, 0.42);
      this.secondarySmooth = this._lerpPts(this.secondarySmooth, this.secondaryTarget, 0.42);

      if (isGlbMode) {
        if (this.primaryHand) this.primaryHand.group.visible = false;
        if (this.secondaryHand) this.secondaryHand.group.visible = false;
        this._updateGlbPose(t);
      } else {
        if (this.primaryHand) this._updateHandRig(this.primaryHand, this.primarySmooth, false);
        if (this.secondaryHand) this._updateHandRig(this.secondaryHand, this.secondarySmooth, true);
      }

      // Rotación suave de cámara / personaje
      if (this.rootGroup) {
        this.rootGroup.rotation.y += (this.orbitYaw - this.rootGroup.rotation.y) * 0.12;
        this.rootGroup.rotation.x += (this.orbitPitch - this.rootGroup.rotation.x) * 0.12;
      }

      // Respiración y movimiento expresivo (tanto para busto HD como para cabeza procedural)
      if (this.charGroup && !this.headGroup) {
        this.charGroup.position.y = -0.02 + Math.sin(t * 2.0) * 0.016;
        this.charGroup.rotation.z = this.isAnimatingText ? Math.sin(t * 3.0) * 0.025 : Math.sin(t * 1.1) * 0.012;
      }
      if (this.charGroup && this.headGroup) {
        this.charGroup.position.y = -0.05 + Math.sin(t * 2.0) * 0.014;
        const headNod = this.isAnimatingText ? Math.sin(t * 5.2) * 0.045 : Math.sin(t * 1.4) * 0.02;
        const headTilt = this.currentMood === 'surprised' ? 0.10 : Math.sin(t * 0.9) * 0.03;
        this.headGroup.rotation.x = headNod;
        this.headGroup.rotation.z = headTilt;

        // Parpadeo natural
        this.blinkTimer += dt;
        let eyeScaleY = 1.0;
        if (this.blinkTimer >= this.nextBlinkAt) {
          const blinkPhase = (this.blinkTimer - this.nextBlinkAt) / 0.14;
          if (blinkPhase < 1.0) {
            eyeScaleY = Math.max(0.08, Math.abs(Math.cos(blinkPhase * Math.PI)));
          } else {
            this.blinkTimer = 0;
            this.nextBlinkAt = 2.4 + Math.random() * 2.5;
          }
        }
        if (this.leftEye) this.leftEye.scale.y = eyeScaleY;
        if (this.rightEye) this.rightEye.scale.y = eyeScaleY;

        // Expresión de boca
        if (this.mouthMesh) {
          if (this.isAnimatingText) {
            this.mouthMesh.scale.set(1.05, 0.8 + Math.abs(Math.sin(t * 9.0)) * 0.9, 1);
          } else if (this.currentMood === 'happy') {
            this.mouthMesh.scale.set(1.35, 1.25, 1);
          } else if (this.currentMood === 'alert') {
            this.mouthMesh.scale.set(0.75, 1.5, 1);
          } else {
            this.mouthMesh.scale.set(1.0, 0.85, 1);
          }
        }
      }

      this._resize();
      this.renderer.render(this.scene, this.camera);
    }
  }

  window.SignBridgeAvatar3D = new AnimeAvatar3D();
  window.SIGNBRIDGE_AVATAR_PRESETS = AVATAR_PRESETS;
})();
