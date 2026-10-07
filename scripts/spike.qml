import QtQuick
import QtQuick3D
import QtQuick3D.Helpers
import QtQuick3D.Particles3D

// Transparency spike: glow + shadow + additive particles over a transparent window.
Item {
    width: 420
    height: 640

    View3D {
        anchors.fill: parent

        environment: ExtendedSceneEnvironment {
            backgroundMode: SceneEnvironment.Transparent
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.High
            glowEnabled: true
            glowBloom: 0.5
            // Qt defaults (SoftLight blend, level One) give no visible halo over a transparent background.
            glowBlendMode: ExtendedSceneEnvironment.GlowBlendMode.Additive
            glowLevel: ExtendedSceneEnvironment.GlowLevel.One | ExtendedSceneEnvironment.GlowLevel.Two | ExtendedSceneEnvironment.GlowLevel.Three
        }

        PerspectiveCamera {
            id: camera
            fieldOfView: 35
            position: Qt.vector3d(0, 110, 270)
            eulerRotation.x: -17
            clipNear: 10
            clipFar: 2000
        }

        DirectionalLight {
            eulerRotation: Qt.vector3d(-50, -30, 0)
            brightness: 1.2
            castsShadow: true
            shadowMapQuality: Light.ShadowMapQualityHigh
        }

        // Cool fill light from the opposite side, no shadow.
        DirectionalLight {
            eulerRotation: Qt.vector3d(-20, 150, 0)
            brightness: 0.35
            color: "#9FB8FF"
        }

        // Emissive golden sphere (radius 50 * 0.3 = 15 cm).
        Model {
            source: "#Sphere"
            position: Qt.vector3d(0, 45, 0)
            scale: Qt.vector3d(0.3, 0.3, 0.3)
            materials: PrincipledMaterial {
                baseColor: "#E8B84A"
                metalness: 0.2
                roughness: 0.4
                emissiveFactor: Qt.vector3d(1.8, 1.2, 0.3)
            }
        }

        // Cube slab below the sphere, top face at y = 0, receives the shadow.
        Model {
            source: "#Cube"
            position: Qt.vector3d(0, -15, 0)
            scale: Qt.vector3d(1.0, 0.3, 1.0)
            materials: PrincipledMaterial {
                baseColor: "#9A9AA4"
                roughness: 0.8
            }
        }

        ParticleSystem3D {
            id: psystem

            SpriteParticle3D {
                id: mote
                sprite: Texture {
                    sourceItem: Rectangle {
                        width: 32
                        height: 32
                        radius: 16
                        color: "white"
                    }
                }
                maxAmount: 80
                color: "#FFD27A"
                colorVariation: Qt.vector4d(0.1, 0.1, 0.0, 0.0)
                blendMode: SpriteParticle3D.Additive
                billboard: true
                fadeInDuration: 400
                fadeOutDuration: 700
            }

            ParticleEmitter3D {
                particle: mote
                position: Qt.vector3d(0, 50, 0)
                scale: Qt.vector3d(0.9, 0.8, 0.9)
                shape: ParticleShape3D {
                    type: ParticleShape3D.Sphere
                }
                emitRate: 20
                // Initial burst so a few dozen motes are already in the volume at the first frames.
                emitBursts: [
                    EmitBurst3D {
                        time: 0
                        amount: 40
                    }
                ]
                lifeSpan: 3000
                lifeSpanVariation: 600
                particleScale: 0.3
                particleScaleVariation: 0.15
                velocity: VectorDirection3D {
                    direction: Qt.vector3d(0, 28, 0)
                    directionVariation: Qt.vector3d(6, 5, 6)
                }
            }
        }
    }
}
