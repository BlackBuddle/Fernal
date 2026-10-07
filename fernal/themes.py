"""Theme table: colors and switches the scene reads through the Bridge.

Keys per theme: label (Korean UI name), bark, bark_emissive, leaf, leaf_emissive,
leaf_low (leaf color at low vitality), glow, fruit, fruit_color, particles
("motes" or "leaf") and accent (UI accent color).

`leaf` is the middle of a three-stop ramp; the dark crown heart and the light outer shell, and the
autumn colors, live next to it in fernal/qml/Scene.qml (see docs/design/design-plan.md).
"""

THEMES = {
    # Ember in amber: a dark-gold skeleton, amber leaves, luminous tips.
    "erdtree": dict(label="세계수", bark="#6A4A1C", bark_emissive="#FFA640", leaf="#CC8A30",
                    leaf_emissive="#FFB24E", leaf_low="#9A7442", glow=True, fruit=False,
                    fruit_color="#E0672A", particles="motes", accent="#E2B65C"),
    # Layered greens from forest shade to spring.
    "normal": dict(label="일반 나무", bark="#4A372B", bark_emissive="#000000", leaf="#4C7A3A",
                   leaf_emissive="#000000", leaf_low="#C27A36", glow=False, fruit=False,
                   fruit_color="#E0672A", particles="leaf", accent="#8FBF7C"),
    # The same greens with persimmons (감).
    "fruit": dict(label="열매 나무", bark="#4A372B", bark_emissive="#000000", leaf="#4C7A3A",
                  leaf_emissive="#000000", leaf_low="#C27A36", glow=False, fruit=True,
                  fruit_color="#E0672A", particles="leaf", accent="#EC8A4E"),
}


def theme(name: str) -> dict:
    """Theme dict by name; unknown names fall back to "normal"."""
    return THEMES.get(name, THEMES["normal"])
