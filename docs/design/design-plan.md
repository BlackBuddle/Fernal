# Fernal design plan (T11)

## Subject and audience

A living plant that keeps someone company on their desktop while they work: it grows for days, turns
toward the sun, droops when neglected. The audience is one person at a PC who wants a calm, beautiful
presence and three-second care actions (water, feed, climate, spray), never a dashboard.

## Palette

Scene colors are the theme table (`fernal/themes.py`) plus derived shades in the shaders.

### Erdtree (세계수): ember in amber, not lemon

| name | hex | role |
|---|---|---|
| heartwood amber | `#7A4512` | crown interior, shadowed leaves (derived in leaf.frag) |
| leaf gold | `#CC8A30` | `leaf`: the mid tone of the canopy |
| lit tip | `#FFD27E` | outer leaves and tips; the only part allowed to bloom |
| bark umber-gold | `#6A4A1C` | `bark`: a dark-gold skeleton that reads against the crown |
| ember | `#FFA640` / `#FFB04A` | crack glow in the bark / drifting motes |

### Normal and fruit trees: layered greens, persimmon fruit

| name | hex | role |
|---|---|---|
| forest shade | `#1C3520` | crown interior (derived) |
| leaf | `#4C7A3A` | `leaf`: mid green |
| spring | `#86AE58` | outer, sunlit leaves (derived) |
| backlit | `#C9DC78` | translucency when the light is behind a leaf |
| autumn | `#C27A36` / `#A8462A` | low vitality: leaves turn one by one, gold and rust |
| persimmon (감) | `#E0672A` | `fruit_color`: warm, per-fruit ripeness variation |
| bark | `#4A372B` | `bark` |

### Default pot: celadon (청자)

| name | hex | role |
|---|---|---|
| celadon glaze | `#838675` | matte sage-grey celadon; cool against warm gold, lighter than any leaf green |
| glaze pool | `#5A5F4B` | darker glaze toward the foot (vertex color) |
| glaze break | `#A2A491` | paler where the glaze thins over the rolled rim |
| raw clay | `#8A6A52` | unglazed foot ring and saucer underside |
| loam | `#3B2A1E` | soil mound, mulch texture (bark map, planar) |

### UI glass

| name | hex | role |
|---|---|---|
| glass | `#121615` at 80 % mixed 7 % toward the theme accent | panel body: moss glass for normal, umber glass for Erdtree, clay glass for fruit |
| text | `#ECEEE8` | readings and values |
| text dim | `#ECEEE8` at 60 % | titles, field names |
| text faint | `#ECEEE8` at 40 % | captions, hints |
| sage | `#8FBF7C` | accent, normal theme |
| gold | `#E2B65C` | accent, Erdtree |
| persimmon | `#EC8A4E` | accent, fruit theme |

### Light

| name | hex |
|---|---|
| sun key (high) | `#FFF1DC` |
| sun key (low, golden hour) | `#FFB46E` |
| sky fill | `#DDE7FF` |
| moon key | `#8EA8F0` |
| night fill | `#7A88B8` |
| night ambient | `#465478` |

## Type

Installed families only (QFontDatabase on this machine), both with full Hangul:

- **Noto Serif KR** (Regular / Medium): the reading line, the plant's voice. A field-journal serif
  that no other desktop widget uses. 20 px (steps down to 17 px rather than wrap).
- **Noto Sans KR** (Regular / Medium): everything else. 14 px for controls and buttons, 12 px for field
  names, readouts and captions, 13 px Medium for the window title.
- Fallback chain: Malgun Gothic, then the system UI font.

Scale: 12 / 14 / 20 px (roughly a 1.2 and 1.4 step from the 14 px base, after the classic scale
12, 14, 18, 21, rounded to the panel width). Weights: Regular for content, Medium only for the title and the action. Left aligned
everywhere; the only centered text is the action label.

## Layout

A tool panel reads top to bottom as "what is happening, the evidence, what you can do":

```
╭──────────────────────────────────╮  radius 16
│ 물 주기                        ✕ │  13 px sans, dim; drag handle
│                                  │
│ 흙이 말라 가요                    │  20 px serif: the reading (signature)
│                                  │
│ ──────▕████████████▏──│───────── │  hairline track, comfort band, needle
│ 토양 수분 35%        알맞은 범위 40–80% │  12 px readout
│ 마지막 물 주기 2시간 전            │  caption (optional)
├──────────────────────────────────┤  hairline
│             물 주기               │  the action is the card's foot
╰──────────────────────────────────╯  → "물을 줬어요" for 1.6 s
```

Climate replaces the gauge with a cool-to-warm slider and says what the device is doing:

```
╭──────────────────────────────────╮
│ 온도 조절                      ✕ │
│ 난방으로 3°C 올리는 중              │  serif reading
│ ────────────┃██●──────────────── │  fill grows from the center notch
│ 냉방                         난방 │
│ 현재 24.5°C        알맞은 온도 17–27°C │
╰──────────────────────────────────╯
```

Settings: quiet field groups separated by space, not boxes; the tree choice is a segmented row because
three options fit and should be visible at once.

```
╭──────────────────────────────────╮
│ 설정                           ✕ │
│ 도시                              │
│ [ 서울                  ] [ 찾기 ] │  fields radius 8, buttons radius 10
│ 위치: 서울특별시                   │
│ 테마                              │
│ [ 세계수 | 일반 나무 | 열매 나무 ]  │  segmented, the chosen one lit
│ 화분                              │
│ terracotta_pot_v2.glb             │
│ [ 화분 바꾸기…    ] [ 기본 화분 ]   │
│ 창 크기                           │
│ [ 가로 420 ] [ 세로 640 ] [ 적용 ]  │  → "적용됨"
╰──────────────────────────────────╯
```

## Principles

- **One memorable element: the reading.** Each care panel opens with one serif sentence that says
  how the plant is ("흙이 말라 가요", "공기가 알맞게 촉촉해요"), computed from the same comfort ranges the
  simulation uses (`sim.OPTIMUM`). The number is still there, small, as evidence. Nothing else in the
  panel competes with it.
- **The gauge shows the plant's comfort, not just a level.** A hairline track, the healthy range as a
  soft band that lights up in the accent while the needle is inside it, and a thin needle. No gradient
  sheen, no fat progress bar.
- **The action is the foot of the card.** One full-width footer under a hairline, like a saucer under
  a pot; it confirms in words ("물을 줬어요") and goes back.
- **Radius follows size**: window 16, action 10, fields 8, band fully round. Not one radius everywhere.
- **Quiet everywhere else**: no accent rule under titles, no accent wash in the corner, no glow under
  handles; the accent appears only in the band, the action and focus rings.
- **Keyboard**: Tab reaches every control; focus is a 1.5 px accent ring shown only when focus came
  from the keyboard; Esc closes; Space/Enter acts.
- **Scene**: depth before brightness. Dark interiors, lit edges, a visible skeleton. Bloom is a
  privilege of the Erdtree's tips, never a white-out.

## Genericness review

What the first draft of this plan contained, and what changed:

1. **Big number, small unit as the gauge hero** (the "big number with a small label" default). The
   first sketch kept "35 %" at 20 px as the panel's focal point. Changed: the focal point is now a
   sentence about the plant in a serif; the number dropped to the 12 px readout. Reason: the person
   wants to know whether to water, not to read a meter.
2. **SaaS card kit**: one 14 px radius on the card, pill buttons, the same bar in every panel.
   Changed: radius hierarchy, the action became the card's footer instead of a floating pill, the bar
   became a comfort-band gauge that differs per tool by its range.
3. **Gradient wash as decoration**: accent glow in the top-left corner and an accent rule fading under
   each title. Removed both; hierarchy now comes from type size, weight and space.
4. **Near-black glass with one bright green accent** (default 2). Changed: the glass is tinted 7 %
   toward the theme (moss, umber, clay) and the accents are softened to sage, gold and persimmon.
5. **Meta joined with middle dots** ("서울특별시 · 37.57°N 126.98°E" in the preview). Changed to a plain
   sentence-like status ("위치: 서울특별시"), the same form the app already writes.
6. **System UI type** (Segoe UI + Malgun Gothic, the default for any Windows tool). Changed to Noto
   Serif KR for the voice and Noto Sans KR for the controls, both installed.
7. **Terracotta pot**. The first instinct for "a plant pot" is terracotta, which is also the warm-clay
   accent that reads as a generated look. Changed to a matte celadon glaze with a raw clay foot: it is
   cool against the gold tree, lighter than the greens, and specific to a Korean-language companion.
8. **"More bloom = more magic" for the Erdtree.** Changed to the opposite: lower bloom, a higher bloom
   threshold, emissive only on outer leaves and bark cracks, so the glow has a shape.
9. **Copy**: "적용" on the city field described the system, not the action; it searches. Renamed
   "찾기", matching the app's "찾는 중…" status. "에어컨" vs "난방" were not a pair; now "냉방" and "난방".

## Build notes and self-critique (six rounds of renders)

- Round 1: the soil mound was invisible (its profile was walked outward, so its faces pointed down);
  the first jade celadon was too light and pulled the eye away from the tree; edge-on leaves flashed
  white (specular 0.32, now 0.18).
- Round 2: the pot turned saturated blue under moonlight. The glaze became a greyer, warmer sage
  celadon and the night fill and ambient lost some blue (`#7C92D2` to `#7A88B8`, `#4E62A0` to
  `#465478`); the crown greens are unaffected because they carry their own saturation.
- Round 3: the Erdtree trunk was a plain brown pole. Crack emission now uses a soft threshold so the
  bark reads as gold threaded with ember; round 4 showed it too orange by day, so the bark emissive
  dropped to 0.3 (x2.5 at night).
- Panels round 1: the "px" suffix clipped inside the size fields (moved to the section name), and the
  keyboard focus ring only shows in the active window (the preview now activates the focused panel).
- **Accessory removed: the river pebbles on the soil.** They were built to give the soil character,
  but at overlay scale they read as six white rivets and competed with the tree. The mulch texture on
  a domed mound carries the soil alone.
- Earlier cuts made during the plan review: the accent rule under every title, the accent corner wash,
  the gradient sheen on gauge bars and the glow halo under slider handles.
