// Leaves: alpha-masked leaf.png tinted by leafColor (toward a warm yellow-brown as vitality
// drops), per-leaf tone variation from the baked sway phase, both faces lit, and a fake
// translucency that makes leaves glow brighter and yellower when the light is behind them.

SHARED_VARS {
    vec3 albedo;    // final base color, read by the light functions
};

vec3 srgbToLinear(vec3 c) { return pow(max(c, vec3(0.0)), vec3(2.2)); }

void MAIN()
{
    vec4 tex = texture(leafMap, UV0);
    if (tex.a < 0.5)
        discard;

    float v = UV1.x;                                   // per-leaf random 0..1
    vec3 healthy = leafColor.rgb;
    vec3 tired = leafLow.rgb;
    float vit = clamp(vitality, 0.0, 1.0);
    vec3 tint = mix(tired, healthy, smoothstep(0.15, 0.85, vit));
    // Tone variation: some leaves lighter and yellower, some deeper.
    tint *= 0.78 + 0.42 * v;
    tint = mix(tint, tint * vec3(1.12, 1.05, 0.7), 0.2 * fract(v * 7.31));

    vec3 albedo = srgbToLinear(tex.rgb) * 1.35;
    SHARED.albedo = tint * albedo;
    BASE_COLOR = vec4(SHARED.albedo, 1.0);
    ROUGHNESS = 0.55;
    METALNESS = 0.0;
    SPECULAR_AMOUNT = 0.3;
    EMISSIVE_COLOR = leafEmissive.rgb * emissiveStrength * (0.55 + 0.45 * v) * albedo;
}

void DIRECTIONAL_LIGHT()
{
    float ndl = dot(NORMAL, TO_LIGHT_DIR);
    float front = max(ndl, 0.0) * 0.85 + 0.15 * max(ndl + 0.3, 0.0);   // slight wrap
    float back = max(-ndl, 0.0);
    vec3 transColor = SHARED.albedo * vec3(1.0, 1.15, 0.5) * translucency;
    DIFFUSE += LIGHT_COLOR * SHADOW_CONTRIB * (SHARED.albedo * front + transColor * back);
}

void AMBIENT_LIGHT()
{
    float sky = 0.6 + 0.4 * NORMAL.y;
    DIFFUSE += SHARED.albedo * TOTAL_AMBIENT_COLOR * sky;
}
