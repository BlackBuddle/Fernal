// Fruit (persimmon): per-fruit ripeness from the baked sway phase (UV1.x), a deeper tone on the
// shadowed underside, waxy skin, wrapped diffuse and a faint warm rim so the fruit reads as lit
// flesh under the canopy instead of a flat sticker.

SHARED_VARS {
    vec3 albedo;
};

void MAIN()
{
    float h = UV1.x;
    vec3 base = fruitColor.rgb;
    vec3 ripe = base * vec3(0.86, 0.5, 0.42);       // deep, reddish
    vec3 young = base * vec3(1.05, 1.32, 0.8);      // lighter, more golden
    vec3 col = mix(ripe, young, 0.15 + 0.6 * h);
    float up = clamp(NORMAL.y * 0.5 + 0.5, 0.0, 1.0);
    col *= 0.72 + 0.4 * up;                          // shoulders catch light, the base stays deep

    SHARED.albedo = col;
    BASE_COLOR = vec4(col, 1.0);
    ROUGHNESS = 0.36;
    METALNESS = 0.0;
    SPECULAR_AMOUNT = 0.55;

    float facing = clamp(dot(NORMAL, normalize(VIEW_VECTOR)), 0.0, 1.0);
    float rim = pow(1.0 - facing, 2.5);
    EMISSIVE_COLOR = col * glow * (0.35 + 1.4 * rim);
}

void DIRECTIONAL_LIGHT()
{
    float ndl = dot(NORMAL, TO_LIGHT_DIR);
    float wrap = max((ndl + 0.35) / 1.35, 0.0);
    DIFFUSE += LIGHT_COLOR * SHADOW_CONTRIB * SHARED.albedo * wrap;
}

void AMBIENT_LIGHT()
{
    float sky = 0.5 + 0.5 * NORMAL.y;
    DIFFUSE += SHARED.albedo * TOTAL_AMBIENT_COLOR * sky;
}
