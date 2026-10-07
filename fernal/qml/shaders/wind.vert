// Wind sway shared by the branch and leaf materials.
// UV1 = (sway phase 0..1, sway weight 0..1) is baked per vertex by fernal/mesh.py.
// Uniforms (declared as properties on each CustomMaterial):
//   time         seconds, driven by a looping NumberAnimation in Scene.qml
//   windStrength 0..1 from the bridge
//   flutter      0 for branches, 1 for leaves (adds a fast per-leaf flap)

void MAIN()
{
    float phase = UV1.x * 6.2831853;
    float weight = UV1.y;
    float s = clamp(windStrength, 0.0, 1.0);

    // Spatially coherent gust: neighbouring twigs and their leaves move together,
    // so leaves stay attached; the per-segment phase only adds a small wobble.
    float wave = dot(VERTEX.xz, vec2(0.006, 0.004));
    float gust = 0.65 * sin(time * 0.9 + wave)
               + 0.25 * sin(time * 2.3 + wave * 1.7 + phase * 0.35)
               + 0.10 * sin(time * 4.1 + phase);
    float amp = (0.6 + 4.4 * s) * weight;          // cm at the tips: ~2.4 at the default 0.4
    vec3 dir = normalize(vec3(1.0, 0.0, 0.35));     // prevailing wind toward east-south-east
    vec3 offs = dir * gust * amp;
    offs.y -= abs(gust) * amp * 0.18;               // tips dip slightly as they bend

    // Leaf flap: the quad end with v = 1 swings along the leaf normal around its v = 0 end.
    float flap = sin(time * (5.0 + 3.0 * UV1.x) + phase * 7.0) * (0.25 + 0.75 * s);
    offs += NORMAL * flutter * flap * 0.9 * UV0.y;

    VERTEX += offs;
}
