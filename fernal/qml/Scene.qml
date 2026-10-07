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
    readonly property color fillNight: "#7C92D2"
    readonly property color ambDay: "#4A5058"
    readonly property color ambNight: "#4E62A0"
    readonly property color rimDay: "#FFF6E6"
    readonly property color rimNight: "#8FB0FF"
    readonly property color sunColor: "#FFC872"
    readonly property color moonColor: "#CFE0FF"
    readonly property color leafLowColor: "#B08A3E"
    readonly property color fruitCol: bridge.fruitColor

    function smoothstep(e0, e1, x) {
        var t = Math.max(0, Math.min(1, (x - e0) / (e1 - e0)));
        return t * t * (3 - 2 * t);
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
            exposure: (bridge.glowEnabled ? 0.95 : 1.35) * (0.8 + 0.2 * root.dayF)
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.High
            glowEnabled: bridge.glowEnabled
            // Spike findings: the defaults (SoftLight, level One) show no halo over a
            // transparent window; a high bloom whites out lit surfaces.
            glowBlendMode: ExtendedSceneEnvironment.GlowBlendMode.Additive
            glowLevel: ExtendedSceneEnvironment.GlowLevel.One | ExtendedSceneEnvironment.GlowLevel.Two
                       | ExtendedSceneEnvironment.GlowLevel.Three
            glowStrength: 1.1
            glowIntensity: 0.45 + 0.3 * (1.0 - root.dayF)   // stronger halo at night
            glowBloom: 0.05
            glowHDRMinimumValue: 0.45 + 0.4 * root.dayF
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
                property real emissiveStrength: 0.28 * (1.0 + 1.8 * (1.0 - root.dayF))   // glows more at night
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
                property color leafLow: root.leafLowColor
                property real vitality: bridge.vitality
                property color leafEmissive: bridge.leafEmissive
                property real emissiveStrength: 0.2 * (1.0 + 1.0 * (1.0 - root.dayF))   // a dense crown blooms a lot
                property real translucency: 0.6
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
            materials: PrincipledMaterial {
                baseColor: bridge.fruitColor
                // A faint self-glow keeps the fruit vivid when the sun is behind the tree.
                emissiveFactor: Qt.vector3d(root.fruitCol.r * 0.16, root.fruitCol.g * 0.16, root.fruitCol.b * 0.16)
                roughness: 0.32
                metalness: 0.0
                clearcoatAmount: 0.6
                clearcoatRoughnessAmount: 0.15
            }
        }

        // ---- Pot --------------------------------------------------------------------------
        // Default: dark ceramic built from #Cylinder (100 tall, 100 wide at scale 1), 54 cm at
        // the lip, 43 cm tall, soil top at y = 0 where the trunk emerges.
        Node {
            id: defaultPot
            visible: !(potLoader.item && potLoader.item.status === RuntimeLoader.Success)

            PrincipledMaterial {
                id: glaze
                baseColor: "#2B2926"
                roughness: 0.28
                metalness: 0.0
                clearcoatAmount: 0.7
                clearcoatRoughnessAmount: 0.12
            }
            PrincipledMaterial {
                id: lipGlaze
                baseColor: "#3D3A36"
                roughness: 0.22
                clearcoatAmount: 0.8
                clearcoatRoughnessAmount: 0.08
            }
            PrincipledMaterial {
                id: footGlaze
                baseColor: "#15161A"
                roughness: 0.6
            }
            PrincipledMaterial {
                id: soilMat
                baseColor: "#2A1E16"
                roughness: 0.95
            }

            Model {   // foot ring, slightly recessed
                source: "#Cylinder"
                position: Qt.vector3d(0, -41.5, 0)
                scale: Qt.vector3d(0.40, 0.03, 0.40)
                materials: footGlaze
            }
            Model {   // body
                source: "#Cylinder"
                position: Qt.vector3d(0, -22.25, 0)
                scale: Qt.vector3d(0.50, 0.355, 0.50)
                materials: glaze
            }
            Model {   // lower waist band, a hint of taper
                source: "#Cylinder"
                position: Qt.vector3d(0, -37.5, 0)
                scale: Qt.vector3d(0.465, 0.05, 0.465)
                materials: glaze
            }
            Model {   // lip
                source: "#Cylinder"
                position: Qt.vector3d(0, -2.5, 0)
                scale: Qt.vector3d(0.54, 0.04, 0.54)
                materials: lipGlaze
            }
            Model {   // soil, top at y = 0
                source: "#Cylinder"
                position: Qt.vector3d(0, -0.75, 0)
                scale: Qt.vector3d(0.495, 0.015, 0.495)
                materials: soilMat
            }
        }

        // Soft contact shadow below whichever pot is shown.
        Model {
            source: "#Rectangle"
            y: defaultPot.visible ? -43.2 : potLoader.item.bottomY - 0.2
            eulerRotation.x: -90
            scale: Qt.vector3d(1.05, 1.05, 1)
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
        // Erdtree: slowly rising golden motes (screen-blended, about 60 alive).
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
                color: "#FFD27A"
                colorVariation: Qt.vector4d(0.08, 0.12, 0.1, 0.3)
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
                emitRate: 12 * root.crownShare
                emitBursts: [
                    EmitBurst3D {
                        time: 0
                        amount: Math.round(50 * root.crownShare)
                    }
                ]
                lifeSpan: 5000
                lifeSpanVariation: 1200
                particleScale: 3.5
                particleScaleVariation: 1.5
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
                            property color leafLow: root.leafLowColor
                            property real vitality: Math.min(bridge.vitality, 0.45)
                            property color leafEmissive: bridge.leafEmissive
                            property real emissiveStrength: 0.3
                            property real translucency: 0.6
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
