import QtQuick
import QtQuick3D
import QtQuick3D.Helpers
import QtQuick3D.Particles3D
import QtQuick3D.AssetUtils

// Fernal plant scene. Bound only to the context properties created by the window:
// bridge, branchGeometry, leafGeometry, fruitGeometry, assetsUrl.
// Axes: x = east, y = up, z = south (north is -z). Units are centimeters.
Item {
    id: root
    width: 420
    height: 640

    // ---- Shared state -------------------------------------------------------------------
    readonly property real dayF: Math.max(0, Math.min(1, bridge.dayFactor))
    readonly property bool sunUp: bridge.sunElevation > 0
    // The visible body: the sun while above the horizon, else the moon opposite the sun.
    readonly property real bodyEl: sunUp ? bridge.sunElevation : -bridge.sunElevation
    readonly property real bodyAz: sunUp ? bridge.sunAzimuth : (bridge.sunAzimuth + 180) % 360
    // Key light fades out around the horizon crossing, where it swaps from sun to moon.
    readonly property real keyFade: smoothstep(-1, 8, bodyEl)

    // Wind clock in seconds; wraps once an hour.
    property real time: 0
    NumberAnimation on time {
        from: 0
        to: 3600
        duration: 3600 * 1000
        loops: Animation.Infinite
    }

    // Camera framing: bridge distance 650 is the default framing of a mature ~300-340 cm tree
    // plus pot in a 420x640 window. The tree fills the lower ~75 % of the window and the top
    // band stays free for the sun or moon arc.
    readonly property real distScale: 1.24
    readonly property real focusY: 200

    // Crown box from the leaf mesh bounds, so particles follow the tree as it grows.
    readonly property vector3d crownMin: leaves.bounds.minimum
    readonly property vector3d crownMax: leaves.bounds.maximum
    readonly property bool hasCrown: crownMax.y - crownMin.y > 1
    readonly property vector3d crownCenter: Qt.vector3d((crownMin.x + crownMax.x) / 2,
                                                        (crownMin.y + crownMax.y) / 2,
                                                        (crownMin.z + crownMax.z) / 2)
    // Emitter scale: a unit ParticleShape3D sphere is 100 cm across.
    readonly property real crownW: Math.max(20, Math.max(crownMax.x - crownMin.x, crownMax.z - crownMin.z))
    readonly property real crownH: Math.max(20, crownMax.y - crownMin.y)
    readonly property real crownShare: Math.max(0.15, Math.min(1, crownW / 260))

    // Palette
    readonly property color keyDay: "#FFF1DC"
    readonly property color keyLow: "#FFB46E"
    readonly property color keyNight: "#8EA8F0"
    readonly property color fillDay: "#DDE7FF"
    readonly property color fillNight: "#7A88B8"
    readonly property color ambDay: "#4A5058"
    readonly property color ambNight: "#465478"
    readonly property color rimDay: "#FFF6E6"
    readonly property color rimNight: "#8FB0FF"
    readonly property color sunColor: "#FFC872"
    readonly property color moonColor: "#CFE0FF"
    readonly property bool golden: bridge.theme === "erdtree"
    // Leaf ramp around bridge.leafColor: a dark crown heart and a light outer shell.
    readonly property color leafDeep: golden ? "#7A4512" : "#1C3520"
    readonly property color leafFresh: golden ? "#FFD27E" : "#86AE58"
    // Autumn (low vitality): leaves turn one by one toward gold or rust.
    readonly property color leafLowColor: golden ? "#9A7442" : "#C27A36"
    readonly property color autumnRed: golden ? "#6E4526" : "#A8462A"
    readonly property color loam: "#3B2A1E"

    function smoothstep(e0, e1, x) {
        var t = Math.max(0, Math.min(1, (x - e0) / (e1 - e0)));
        return t * t * (3 - 2 * t);
    }
    // "#RRGGBB" -> linear RGBA, for vertex colors (which bypass the sRGB conversion of color properties).
    function linearHex(h) {
        function ch(i) { return Math.pow(parseInt(h.substr(i, 2), 16) / 255, 2.2); }
        return Qt.vector4d(ch(1), ch(3), ch(5), 1.0);
    }
    function samePoint(a, b) { return Math.abs(a[0] - b[0]) < 1e-4 && Math.abs(a[1] - b[1]) < 1e-4; }
    // Surface of revolution around +y from a profile of [radius, y, "#color"] points, walked from the
    // axis outward and up, or from the rim inward for a top surface (normals face the walker's left). A repeated point makes a crease (or a color edge).
    // uvScale > 0 maps uv0 to the xz plane in units of uvScale cm (for the soil); otherwise uv0 wraps.
    function lathe(prof, seg, uvScale) {
        var pos = [], nrm = [], uv = [], col = [], idx = [];
        var n = prof.length, ring = seg + 1, i, j;
        var arc = [0];
        for (i = 1; i < n; ++i)
            arc.push(arc[i - 1] + Math.sqrt(Math.pow(prof[i][0] - prof[i - 1][0], 2)
                                            + Math.pow(prof[i][1] - prof[i - 1][1], 2)));
        var total = Math.max(arc[n - 1], 1e-3);
        for (i = 0; i < n; ++i) {
            var a = (i > 0 && !samePoint(prof[i - 1], prof[i])) ? prof[i - 1] : prof[i];
            var b = (i < n - 1 && !samePoint(prof[i + 1], prof[i])) ? prof[i + 1] : prof[i];
            var dr = b[0] - a[0], dy = b[1] - a[1];
            var len = Math.sqrt(dr * dr + dy * dy) || 1;
            var nr = dy / len, ny = -dr / len;
            var c = linearHex(prof[i][2]);
            for (j = 0; j <= seg; ++j) {
                var t = j / seg * 2 * Math.PI, cs = Math.cos(t), sn = Math.sin(t);
                var x = prof[i][0] * cs, z = prof[i][0] * sn;
                pos.push(Qt.vector3d(x, prof[i][1], z));
                nrm.push(Qt.vector3d(nr * cs, ny, nr * sn));
                uv.push(uvScale > 0 ? Qt.vector2d(x / uvScale, z / uvScale)
                                    : Qt.vector2d(j / seg * 4, arc[i] / total));
                col.push(c);
            }
        }
        for (i = 0; i < n - 1; ++i) {
            for (j = 0; j < seg; ++j) {
                var p = i * ring + j;
                idx.push(p, p + ring, p + 1, p + 1, p + ring, p + ring + 1);
            }
        }
        return { positions: pos, normals: nrm, uv0s: uv, colors: col, indexes: idx };
    }

    function mixColor(a, b, t) {
        return Qt.rgba(a.r + (b.r - a.r) * t, a.g + (b.g - a.g) * t,
                       a.b + (b.b - a.b) * t, 1.0);
    }

    View3D {
        id: view3d
        anchors.fill: parent
        camera: camera

        environment: ExtendedSceneEnvironment {
            backgroundMode: SceneEnvironment.Transparent
            tonemapMode: SceneEnvironment.TonemapModeFilmic
            // Glowing themes already add light through bloom, so they keep a neutral exposure.
            exposure: (bridge.glowEnabled ? 0.9 : 1.2) * (0.8 + 0.2 * root.dayF)
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.High
            glowEnabled: bridge.glowEnabled
            // Spike findings: the defaults (SoftLight, level One) show no halo over a
            // transparent window; a high bloom whites out lit surfaces.
            glowBlendMode: ExtendedSceneEnvironment.GlowBlendMode.Additive
            glowLevel: ExtendedSceneEnvironment.GlowLevel.One | ExtendedSceneEnvironment.GlowLevel.Two
                       | ExtendedSceneEnvironment.GlowLevel.Three
            // Restrained: only the luminous tips and bark cracks pass the threshold, so the crown
            // keeps its shape instead of whiting out.
            glowStrength: 1.0
            glowIntensity: 0.32 + 0.25 * (1.0 - root.dayF)   // stronger halo at night
            glowBloom: 0.02
            glowHDRMinimumValue: 0.7 + 0.4 * root.dayF
            glowQualityHigh: true
            glowUseBicubicUpscale: true
        }

        // ---- Orbit camera ---------------------------------------------------------------
        // Yaw 0 puts the camera on the north side looking south, so east is on the left.
        Node {
            id: orbit
            y: root.focusY
            eulerRotation: Qt.vector3d(-bridge.cameraPitch, 180 + bridge.cameraYaw, 0)

            PerspectiveCamera {
                id: camera
                z: bridge.cameraDistance * root.distScale
                fieldOfView: 35
                clipNear: 20
                clipFar: 8000

                // ---- Celestial body (screen-anchored, additive) ---------------------------
                Model {
                    id: celestial
                    readonly property real depth: 4000
                    readonly property real halfH: depth * Math.tan(17.5 * Math.PI / 180)
                    readonly property real halfW: halfH * view3d.width / Math.max(1, view3d.height)
                    // Azimuth relative to the view direction: positive = west = right.
                    readonly property real viewAz: 180 - bridge.cameraYaw
                    readonly property real relAz: (root.bodyAz - viewAz) * Math.PI / 180
                    readonly property real xFrac: 0.5 + 0.40 * Math.sin(relAz)
                    readonly property real yFrac: 0.29 - 0.21 * Math.sin(Math.max(0, root.bodyEl) * Math.PI / 180)
                    readonly property real sizeFrac: root.sunUp ? 0.30 : 0.24   // quad width / view width
                    position: Qt.vector3d((xFrac * 2 - 1) * halfW, (1 - yFrac * 2) * halfH, -depth)
                    scale: Qt.vector3d(sizeFrac * halfW * 2 / 100, sizeFrac * halfW * 2 / 100, 1)
                    source: "#Rectangle"
                    castsShadows: false
                    receivesShadows: false
                    visible: material.opacity > 0.001
                    materials: CustomMaterial {
                        id: material
                        shadingMode: CustomMaterial.Unshaded
                        vertexShader: "shaders/celestial.vert"
                        fragmentShader: "shaders/celestial.frag"
                        sourceBlend: CustomMaterial.One
                        destinationBlend: CustomMaterial.One
                        depthDrawMode: Material.NeverDepthDraw
                        property color bodyColor: root.sunUp ? root.sunColor : root.moonColor
                        property real coreRadius: root.sunUp ? 0.17 : 0.15
                        property real coreStrength: root.sunUp ? 1.5 : 1.05
                        property real haloFalloff: root.sunUp ? 9.0 : 14.0
                        property real haloStrength: root.sunUp ? 0.55 : 0.32
                        property real opacity: root.smoothstep(-1, 7, root.bodyEl)
                    }
                }
            }

            // Cool fill from the camera side (upper left) and the scene's ambient term.
            DirectionalLight {
                eulerRotation: Qt.vector3d(-32, -28, 0)
                color: root.mixColor(root.fillNight, root.fillDay, root.dayF)
                brightness: 0.75 - 0.13 * root.dayF
                ambientColor: root.mixColor(root.ambNight, root.ambDay, root.dayF)
                castsShadow: false
            }

            // Rim light from behind the plant, high, picks out silhouettes and backlit leaves.
            DirectionalLight {
                eulerRotation: Qt.vector3d(-38, 160, 0)
                color: root.mixColor(root.rimNight, root.rimDay, root.dayF)
                brightness: 0.35 + 0.35 * root.dayF
                castsShadow: false
            }
        }

        // ---- Key light: sun by day, moon by night -----------------------------------------
        // Pointing along -s for s = (cos(el) sin(az), sin(el), -cos(el) cos(az)) needs
        // eulerRotation (-el, 180 - az, 0). Elevation is kept above 12 deg for usable shadows.
        DirectionalLight {
            id: keyLight
            readonly property real lightEl: Math.max(root.bodyEl, 12)
            eulerRotation: Qt.vector3d(-lightEl, 180 - root.bodyAz, 0)
            color: root.mixColor(root.keyNight,
                                 root.mixColor(root.keyLow, root.keyDay, root.smoothstep(4, 35, root.bodyEl)),
                                 root.dayF)
            brightness: root.keyFade * (2.0 + 0.2 * root.dayF)
            castsShadow: true
            shadowMapQuality: Light.ShadowMapQualityVeryHigh
            softShadowQuality: Light.PCF16
            pcfFactor: 3.0
            shadowFactor: 72
            shadowBias: 2
            shadowMapFar: 2600
        }

        // ---- Plant ------------------------------------------------------------------------
        Model {
            id: branches
            geometry: branchGeometry
            castsShadows: true
            receivesShadows: true
            materials: CustomMaterial {
                shadingMode: CustomMaterial.Shaded
                vertexShader: "shaders/wind.vert"
                fragmentShader: "shaders/bark.frag"
                property real time: root.time
                property real windStrength: bridge.windStrength
                property real flutter: 0.0
                property color barkColor: bridge.barkColor
                property color emissiveColor: bridge.emissiveColor
                property real emissiveStrength: 0.3 * (1.0 + 1.5 * (1.0 - root.dayF))   // glows more at night
                property real normalStrength: 1.1
                property TextureInput barkMap: TextureInput {
                    texture: Texture {
                        source: assetsUrl + "bark.png"
                        tilingModeHorizontal: Texture.Repeat
                        tilingModeVertical: Texture.Repeat
                        generateMipmaps: true
                        mipFilter: Texture.Linear
                    }
                }
                property TextureInput barkNormalMap: TextureInput {
                    texture: Texture {
                        source: assetsUrl + "bark_normal.png"
                        tilingModeHorizontal: Texture.Repeat
                        tilingModeVertical: Texture.Repeat
                        generateMipmaps: true
                        mipFilter: Texture.Linear
                    }
                }
            }
        }

        Model {
            id: leaves
            geometry: leafGeometry
            castsShadows: true
            receivesShadows: true
            materials: CustomMaterial {
                shadingMode: CustomMaterial.Shaded
                cullMode: Material.NoCulling
                vertexShader: "shaders/wind.vert"
                fragmentShader: "shaders/leaf.frag"
                property real time: root.time
                property real windStrength: bridge.windStrength
                property real flutter: 1.0
                property color leafColor: bridge.leafColor
                property color leafDeep: root.leafDeep
                property color leafFresh: root.leafFresh
                property color leafLow: root.leafLowColor
                property color autumnRed: root.autumnRed
                property real vitality: bridge.vitality
                property color leafEmissive: bridge.leafEmissive
                property real emissiveStrength: 0.3 * (1.0 + 0.8 * (1.0 - root.dayF))
                property real translucency: 0.6
                property vector3d crownCenter: root.crownCenter
                property vector3d crownHalf: Qt.vector3d(root.crownW / 2, root.crownH / 2, root.crownW / 2)
                property TextureInput leafMap: TextureInput {
                    texture: Texture {
                        source: assetsUrl + "leaf.png"
                        tilingModeHorizontal: Texture.ClampToEdge
                        tilingModeVertical: Texture.ClampToEdge
                        generateMipmaps: true
                        mipFilter: Texture.Linear
                    }
                }
            }
        }

        Model {
            id: fruits
            geometry: fruitGeometry
            visible: bridge.theme === "fruit"
            castsShadows: true
            receivesShadows: true
            // Fruits hang from leaves, so they sway with the same wind (no leaf flap).
            materials: CustomMaterial {
                shadingMode: CustomMaterial.Shaded
                vertexShader: "shaders/wind.vert"
                fragmentShader: "shaders/fruit.frag"
                property real time: root.time
                property real windStrength: bridge.windStrength
                property real flutter: 0.0
                property color fruitColor: bridge.fruitColor
                property real glow: 0.07 + 0.08 * (1.0 - root.dayF)   // a faint warmth, more at night
            }
        }

        // ---- Pot --------------------------------------------------------------------------
        // Default: a celadon planter turned on a lathe (ProceduralMesh), 55 cm across the rolled rim,
        // a raw clay foot, a shallow saucer, and a mulched soil mound. The soil
        // top is at y = 0 where the trunk emerges. Glaze shading comes from vertex colors: darker
        // where it pools toward the foot, paler where it breaks over the rim.
        Node {
            id: defaultPot
            visible: !(potLoader.item && potLoader.item.status === RuntimeLoader.Success)
            readonly property real bottomY: -42.8

            PrincipledMaterial {
                id: glazeMat
                baseColor: "white"
                vertexColorsEnabled: true
                roughness: 0.5
                specularAmount: 0.45
                metalness: 0.0
                cullMode: Material.NoCulling
            }
            PrincipledMaterial {
                id: soilMat
                baseColor: root.loam
                baseColorMap: Texture {
                    source: assetsUrl + "bark.png"
                    tilingModeHorizontal: Texture.Repeat
                    tilingModeVertical: Texture.Repeat
                    generateMipmaps: true
                    mipFilter: Texture.Linear
                }
                normalMap: Texture {
                    source: assetsUrl + "bark_normal.png"
                    tilingModeHorizontal: Texture.Repeat
                    tilingModeVertical: Texture.Repeat
                    generateMipmaps: true
                    mipFilter: Texture.Linear
                }
                normalStrength: 0.8
                roughness: 0.95
                specularAmount: 0.1
            }
            Model {   // planter
                castsShadows: true
                receivesShadows: true
                materials: glazeMat
                geometry: ProceduralMesh {
                    readonly property var m: root.lathe([
                        [0, -40, "#8A6A52"], [17.5, -40, "#8A6A52"], [17.5, -40, "#8A6A52"],
                        [18.6, -39.5, "#8A6A52"], [19.1, -38.4, "#8A6A52"], [19.3, -37.2, "#8A6A52"],
                        [19.3, -37.2, "#5A5F4B"], [19.75, -36.7, "#5A5F4B"], [21.4, -33, "#666A56"],
                        [23.3, -27, "#707561"], [24.8, -20, "#787D6A"], [25.8, -13, "#7E8370"],
                        [26.3, -7, "#828674"], [26.4, -3, "#838676"], [26.3, -0.6, "#838676"],
                        [26.8, 0.3, "#868A79"], [27.4, 1.1, "#8C907E"], [27.7, 2.0, "#969986"],
                        [27.5, 2.8, "#A2A491"], [27.0, 3.3, "#A2A491"], [26.3, 3.4, "#A2A491"],
                        [25.6, 3.1, "#969986"], [25.3, 2.4, "#838676"], [25.2, 1.0, "#707561"],
                        [25.05, -1.6, "#5A5F4B"]
                    ], 56, 0)
                    positions: m.positions
                    normals: m.normals
                    uv0s: m.uv0s
                    colors: m.colors
                    indexes: m.indexes
                }
            }
            Model {   // saucer
                castsShadows: true
                receivesShadows: true
                materials: glazeMat
                geometry: ProceduralMesh {
                    readonly property var m: root.lathe([
                        [0, -42.8, "#8A6A52"], [23, -42.8, "#8A6A52"], [23, -42.8, "#8A6A52"],
                        [24.6, -42.5, "#8A6A52"], [24.6, -42.5, "#565B47"], [27.2, -41.5, "#5E634F"],
                        [29.6, -40.0, "#666A56"], [30.6, -38.9, "#707561"], [30.7, -38.4, "#8C907E"],
                        [30.3, -38.1, "#8C907E"], [29.8, -38.3, "#666A56"], [29.2, -38.9, "#5A5F4B"],
                        [27.4, -39.8, "#505441"], [25, -40.1, "#4B4F3C"], [0, -40.1, "#4B4F3C"]
                    ], 56, 0)
                    positions: m.positions
                    normals: m.normals
                    uv0s: m.uv0s
                    colors: m.colors
                    indexes: m.indexes
                }
            }
            Model {   // soil mound, mulch texture mapped flat from above
                receivesShadows: true
                castsShadows: false
                materials: soilMat
                geometry: ProceduralMesh {
                    readonly property var m: root.lathe([
                        [25.15, -1.5, "#FFFFFF"], [22, -0.7, "#FFFFFF"], [18, -0.1, "#FFFFFF"],
                        [12, 0.4, "#FFFFFF"], [6, 0.7, "#FFFFFF"], [0, 0.8, "#FFFFFF"]
                    ], 40, 16)
                    positions: m.positions
                    normals: m.normals
                    uv0s: m.uv0s
                    indexes: m.indexes
                }
            }
        }

        // Soft contact shadow below whichever pot is shown.
        Model {
            source: "#Rectangle"
            y: defaultPot.visible ? defaultPot.bottomY - 0.2 : potLoader.item.bottomY - 0.2
            eulerRotation.x: -90
            scale: Qt.vector3d(1.12, 1.12, 1)
            castsShadows: false
            receivesShadows: false
            materials: CustomMaterial {
                shadingMode: CustomMaterial.Unshaded
                vertexShader: "shaders/celestial.vert"
                fragmentShader: "shaders/contact.frag"
                sourceBlend: CustomMaterial.One
                destinationBlend: CustomMaterial.OneMinusSrcAlpha
                depthDrawMode: Material.NeverDepthDraw
                property color shadowColor: "#000000"
                property real strength: 0.42
            }
        }

        // User pot (.glb/.gltf): fitted to ~54 cm wide with its top at the soil line.
        Loader3D {
            id: potLoader
            active: bridge.potSource !== ""
            sourceComponent: Component {
                RuntimeLoader {
                    id: userPot
                    source: bridge.potSource
                    readonly property vector3d bmin: bounds.minimum
                    readonly property vector3d bmax: bounds.maximum
                    readonly property real fit: 54 / Math.max(1e-3, Math.max(bmax.x - bmin.x, bmax.z - bmin.z))
                    readonly property real bottomY: -fit * (bmax.y - bmin.y)
                    scale: Qt.vector3d(fit, fit, fit)
                    position: Qt.vector3d(-fit * (bmin.x + bmax.x) / 2, -fit * bmax.y,
                                          -fit * (bmin.z + bmax.z) / 2)
                }
            }
        }

        // ---- Particles --------------------------------------------------------------------
        // Erdtree: drifting embers, small and warm, rising slowly (screen-blended, about 50 alive).
        ParticleSystem3D {
            id: moteSystem
            visible: bridge.particlesEnabled && bridge.theme === "erdtree"
            running: visible

            SpriteParticle3D {
                id: mote
                sprite: Texture {
                    textureData: ProceduralTextureData {
                        width: 64
                        height: 64
                        format: TextureData.RGBA8
                        hasTransparency: true
                        textureData: {
                            var n = 64;
                            var buf = new ArrayBuffer(n * n * 4);
                            var a = new Uint8Array(buf);
                            for (var y = 0; y < n; ++y) {
                                for (var x = 0; x < n; ++x) {
                                    var dx = (x + 0.5) / n * 2 - 1;
                                    var dy = (y + 0.5) / n * 2 - 1;
                                    var r2 = dx * dx + dy * dy;
                                    var f = Math.exp(-r2 * 5.0) * Math.max(0, 1 - r2);
                                    var v = Math.round(255 * f);
                                    var i = (y * n + x) * 4;
                                    a[i] = v; a[i + 1] = v; a[i + 2] = v; a[i + 3] = v;
                                }
                            }
                            return buf;
                        }
                    }
                }
                maxAmount: 100
                color: "#FFB04A"
                colorVariation: Qt.vector4d(0.06, 0.16, 0.12, 0.4)
                blendMode: SpriteParticle3D.Screen
                billboard: true
                fadeInDuration: 900
                fadeOutDuration: 1400
            }

            ParticleEmitter3D {
                particle: mote
                enabled: root.hasCrown
                position: root.crownCenter
                scale: Qt.vector3d(root.crownW / 100, root.crownH / 160, root.crownW / 100)
                shape: ParticleShape3D {
                    type: ParticleShape3D.Sphere
                }
                emitRate: 10 * root.crownShare
                emitBursts: [
                    EmitBurst3D {
                        time: 0
                        amount: Math.round(40 * root.crownShare)
                    }
                ]
                lifeSpan: 5000
                lifeSpanVariation: 1500
                particleScale: 2.3
                particleScaleVariation: 1.1
                velocity: VectorDirection3D {
                    direction: Qt.vector3d(0, 13, 0)
                    directionVariation: Qt.vector3d(5, 5, 5)
                }
            }

            Wander3D {
                globalAmount: Qt.vector3d(8, 3, 8)
                globalPace: Qt.vector3d(0.25, 0.15, 0.25)
                uniqueAmount: Qt.vector3d(6, 4, 6)
                uniquePace: Qt.vector3d(0.3, 0.2, 0.3)
            }
        }

        // Other themes: an occasional falling leaf that drifts as it drops.
        ParticleSystem3D {
            id: leafFallSystem
            visible: bridge.particlesEnabled && bridge.theme !== "erdtree"
            running: visible

            // A real lit leaf quad (same shaders as the canopy), tinted toward autumn.
            ModelParticle3D {
                id: fallingLeaf
                maxAmount: 8
                fadeInEffect: ModelParticle3D.FadeScale
                fadeOutEffect: ModelParticle3D.FadeScale
                fadeInDuration: 600
                fadeOutDuration: 1500
                delegate: Component {
                    Model {
                        source: "#Rectangle"
                        castsShadows: false
                        materials: CustomMaterial {
                            shadingMode: CustomMaterial.Shaded
                            cullMode: Material.NoCulling
                            vertexShader: "shaders/wind.vert"
                            fragmentShader: "shaders/leaf.frag"
                            property real time: 0
                            property real windStrength: 0
                            property real flutter: 0
                            property color leafColor: bridge.leafColor
                            property color leafDeep: root.leafDeep
                            property color leafFresh: root.leafFresh
                            property color leafLow: root.leafLowColor
                            property color autumnRed: root.autumnRed
                            property real vitality: Math.min(bridge.vitality, 0.3)
                            property color leafEmissive: bridge.leafEmissive
                            property real emissiveStrength: 0.3
                            property real translucency: 0.6
                            // Far from any crown: a falling leaf is always an outer, lit leaf.
                            property vector3d crownCenter: Qt.vector3d(0, -1e5, 0)
                            property vector3d crownHalf: Qt.vector3d(1, 1, 1)
                            property TextureInput leafMap: TextureInput {
                                texture: Texture {
                                    source: assetsUrl + "leaf.png"
                                    generateMipmaps: true
                                    mipFilter: Texture.Linear
                                }
                            }
                        }
                    }
                }
            }

            ParticleEmitter3D {
                particle: fallingLeaf
                enabled: root.hasCrown
                position: Qt.vector3d(root.crownCenter.x, root.crownCenter.y + 0.15 * root.crownH, root.crownCenter.z)
                scale: Qt.vector3d(root.crownW / 115, root.crownH / 250, root.crownW / 115)
                shape: ParticleShape3D {
                    type: ParticleShape3D.Sphere
                }
                emitRate: 0.22 * root.crownShare
                emitBursts: [
                    EmitBurst3D {
                        time: 0
                        amount: 1
                    }
                ]
                lifeSpan: 9000
                lifeSpanVariation: 1500
                particleScale: 0.11
                particleScaleVariation: 0.025
                particleRotationVariation: Qt.vector3d(180, 180, 180)
                particleRotationVelocityVariation: Qt.vector3d(50, 80, 50)
                velocity: VectorDirection3D {
                    direction: Qt.vector3d(5, -22, 2)
                    directionVariation: Qt.vector3d(6, 4, 6)
                }
            }

            Wander3D {
                uniqueAmount: Qt.vector3d(22, 4, 22)
                uniquePace: Qt.vector3d(0.35, 0.2, 0.35)
            }
        }
    }
}
