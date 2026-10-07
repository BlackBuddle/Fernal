// Pass-through vertex shader for the unshaded screen quads (celestial body, contact shadow).
VARYING vec2 vUV;

void MAIN()
{
    vUV = UV0;
    POSITION = MODELVIEWPROJECTION_MATRIX * vec4(VERTEX, 1.0);
}
