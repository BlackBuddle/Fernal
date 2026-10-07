// Sun or moon disc: a soft core plus a gaussian halo, drawn additively (no texture).
// bodyColor is the tint, opacity fades the body near the horizon.

VARYING vec2 vUV;

void MAIN()
{
    vec2 p = vUV * 2.0 - 1.0;
    float r = length(p);
    float core = 1.0 - smoothstep(coreRadius * 0.82, coreRadius, r);
    float halo = exp(-r * r * haloFalloff) * haloStrength;
    float edge = 1.0 - smoothstep(0.85, 1.0, r);       // keep the quad border invisible
    vec3 c = bodyColor.rgb * (core * coreStrength + halo) * edge * opacity;
    float a = clamp(core * 0.85 + halo * 0.35, 0.0, 1.0) * edge * opacity;
    FRAGCOLOR = vec4(c, a);
}
