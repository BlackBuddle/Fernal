// Soft contact shadow under the pot: a dark radial falloff, alpha-blended so the desktop
// below the window darkens a little and the pot looks grounded (there is no ground plane).
VARYING vec2 vUV;

void MAIN()
{
    float r = length(vUV * 2.0 - 1.0);
    float a = strength * (1.0 - smoothstep(0.25, 1.0, r)) * (0.6 + 0.4 * (1.0 - smoothstep(0.0, 0.45, r)));
    FRAGCOLOR = vec4(shadowColor.rgb * a, a);
}
