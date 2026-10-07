// Bark: bark.png (grey, sRGB) tints barkColor, bark_normal.png perturbs the normal through a
// cotangent frame built from screen-space derivatives (the tubes carry no tangents), and the
// emissive color glows only from the cracks (Erdtree), so the trunk reads as a dark-gold
// skeleton threaded with ember light rather than a uniformly lit tube.

SHARED_VARS {
    vec3 albedo;    // final base color, read by the light functions
};

vec3 srgbToLinear(vec3 c) { return pow(max(c, vec3(0.0)), vec3(2.2)); }

void MAIN()
{
    vec2 uv = UV0 * vec2(1.0, 1.0);
    vec3 albedo = srgbToLinear(texture(barkMap, uv).rgb);
    float lum = dot(albedo, vec3(0.299, 0.587, 0.114));
    float crack = clamp(1.0 - lum * 1.35, 0.0, 1.0);

    SHARED.albedo = barkColor.rgb * albedo * 1.6;
    BASE_COLOR = vec4(SHARED.albedo, 1.0);
    ROUGHNESS = 0.82;
    METALNESS = 0.0;
    SPECULAR_AMOUNT = 0.25;

    // Cotangent frame (Schueler) from derivatives of world position and UV.
    vec3 n = normalize(NORMAL);
    vec3 dp1 = dFdx(VAR_WORLD_POSITION);
    vec3 dp2 = dFdy(VAR_WORLD_POSITION);
    vec2 duv1 = dFdx(uv);
    vec2 duv2 = dFdy(uv);
    vec3 dp2perp = cross(dp2, n);
    vec3 dp1perp = cross(n, dp1);
    vec3 t = dp2perp * duv1.x + dp1perp * duv2.x;
    vec3 b = dp2perp * duv1.y + dp1perp * duv2.y;
    float len2 = max(dot(t, t), dot(b, b));
    if (len2 > 1e-12) {
        float inv = inversesqrt(len2);
        vec3 nm = texture(barkNormalMap, uv).xyz * 2.0 - 1.0;
        nm.xy *= normalStrength;
        NORMAL = normalize(mat3(t * inv, b * inv, n) * nm);
    }

    float ember = smoothstep(0.05, 0.6, crack);
    EMISSIVE_COLOR = emissiveColor.rgb * emissiveStrength * (0.1 + 1.4 * ember * ember);
}

void AMBIENT_LIGHT()
{
    // Hemisphere ambient: brighter from the sky, darker from the ground.
    float sky = 0.55 + 0.45 * NORMAL.y;
    DIFFUSE += SHARED.albedo * TOTAL_AMBIENT_COLOR * sky;
}
