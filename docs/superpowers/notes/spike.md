1. Corners transparent: yes - all four corner pixels have alpha 0 (the grab is 630x960 because the display DPR is 1.5).
2. Glow halo visible: yes - a golden halo surrounds the emissive sphere, but only with glowBlendMode Additive and glowLevel One|Two|Three (Qt defaults SoftLight/One show no halo); glowBloom 0.5 also saturates the bright lit cube to white.
3. Shadow visible: yes - the sphere casts a clear soft-edged dark ellipse on the cube top, also with glow enabled.
4. Particles visible: yes - dozens of additive golden motes rise around the sphere (needs particleScale ~0.3; the first frame arrives ~1 s after show, so the 1500 ms countdown starts at the first swapped frame).
5. Click-through toggle: yes - WindowTransparentForInput ON sets WS_EX_TRANSPARENT (exstyle 0x000800A8), OFF clears it (0x00080088), no crash, and grabWindow() still returns a full 630x960 image.
RHI backend: Direct3D11 (Qt default on Windows; opengl and d3d11 overrides were not needed).
Fallbacks used: none of the allowed fallbacks (tonemapMode None, backend switch, glow off); the only corrections were scene settings (glow blend/level, particle scale, burst) and a clamping composite (DestinationOut then Plus) because glow writes rgb > alpha in the premultiplied grab and plain SourceOver overflows.
Recommendation: glow path - ExtendedSceneEnvironment glow coexists with the transparent window on D3D11, so no emissive plus billboard fallback is needed; set glowBlendMode Additive with glowLevel One|Two|Three and keep lit surfaces dark or lower glowBloom so they do not blow out.
