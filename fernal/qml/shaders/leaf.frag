// Leaves: alpha-masked leaf.png (grey veins, the tint map) colored by a three-stop ramp
// leafDeep -> leafColor -> leafFresh. Where a leaf sits on that ramp depends on its place in the
// crown (dark heart, lighter outer shell and top) plus per-leaf variation hashed from the baked sway
// phase (UV1.x). As vitality drops, leaves turn one by one toward leafLow (gold) or autumnRed (rust).
// Both faces are lit; a fake translucency makes backlit leaves glow a warmer, yellower tone.
// Emissive (Erdtree) is concentrated on the outer shell so the crown keeps its silhouette.

SHARED_VARS {
    vec3 albedo;    // final base color, read by the light functions
    float shade;    // crown self-occlusion, 0.45 in the heart .. 1.0 on the shell
};

vec3 srgbToLinear(vec3 c) { return pow(max(c, vec3(0.0)), vec3(2.2)); }

void MAIN()
{
    vec4 tex = texture(leafMap, UV0);
    if (tex.a < 0.5)
        discard;

    // Three independent per-leaf values from the one baked random phase.
    float h1 = UV1.x;
    float h2 = fract(h1 * 7.31 + 0.13);
    float h3 = fract(h1 * 13.97 + 0.71);

    // Place in the crown: 0 at the heart, 1 on the outer shell; top leaves catch more sky.
    vec3 rel = (VAR_WORLD_POSITION - crownCenter) / max(crownHalf, vec3(1.0));
    float shell = smoothstep(0.2, 1.0, length(rel));
    float top = clamp(rel.y * 0.5 + 0.5, 0.0, 1.0);
    float tone = clamp(0.62 * shell + 0.22 * top + 0.36 * (h1 - 0.5), 0.0, 1.0);

    vec3 col = tone < 0.5 ? mix(leafDeep.rgb, leafColor.rgb, tone * 2.0)
                          : mix(leafColor.rgb, leafFresh.rgb, tone * 2.0 - 1.0);
    // Per-leaf hue drift (some cooler, some warmer) and a little value jitter.
    col *= mix(vec3(0.9, 1.0, 1.1), vec3(1.1, 1.02, 0.84), h2);
    col *= 0.86 + 0.28 * h3;

    // Autumn: each leaf has its own vitality threshold, so the crown turns patchily.
    float vit = clamp(vitality, 0.0, 1.0);
    float threshold = 0.2 + 0.55 * h2;
    float turned = 1.0 - smoothstep(threshold - 0.12, threshold + 0.12, vit);
    vec3 autumn = mix(leafLow.rgb, autumnRed.rgb, h3 * h3) * (0.75 + 0.45 * tone);
    col = mix(col, autumn, turned);

    vec3 veins = srgbToLinear(tex.rgb) * 1.22;
    SHARED.albedo = col * veins;
    SHARED.shade = mix(0.45, 1.0, shell);
    BASE_COLOR = vec4(SHARED.albedo, 1.0);
    ROUGHNESS = 0.6;
    METALNESS = 0.0;
    SPECULAR_AMOUNT = 0.18 * SHARED.shade;

    // Glow lives on the shell and the tips, never in the heart.
    float rim = shell * shell;
    EMISSIVE_COLOR = leafEmissive.rgb * emissiveStrength * (0.06 + 1.5 * rim) * (0.55 + 0.45 * h1) * veins;
}

void DIRECTIONAL_LIGHT()
{
    float ndl = dot(NORMAL, TO_LIGHT_DIR);
    float front = max(ndl, 0.0) * 0.85 + 0.15 * max(ndl + 0.3, 0.0);   // slight wrap
    float back = max(-ndl, 0.0);
    vec3 transColor = SHARED.albedo * vec3(1.05, 1.18, 0.55) * translucency;
    float occl = mix(0.7, 1.0, SHARED.shade);
    DIFFUSE += LIGHT_COLOR * SHADOW_CONTRIB * occl * (SHARED.albedo * front + transColor * back);
}

void AMBIENT_LIGHT()
{
    float sky = 0.55 + 0.45 * NORMAL.y;
    DIFFUSE += SHARED.albedo * TOTAL_AMBIENT_COLOR * sky * SHARED.shade;
}
