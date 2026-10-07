"""Theme table: colors and switches the scene reads through the Bridge.

Keys per theme: label (Korean UI name), bark, bark_emissive, leaf, leaf_emissive,
leaf_low (leaf color at low vitality), glow, fruit, fruit_color, particles
("motes" or "leaf") and accent (UI accent color).
"""

THEMES = {
    "erdtree": dict(label="세계수", bark="#8A6A2E", bark_emissive="#FFD27A", leaf="#FFD27A",
                    leaf_emissive="#FFB347", leaf_low="#B8A24A", glow=True, fruit=False,
                    fruit_color="#D9452B", particles="motes", accent="#E8C06A"),
    "normal": dict(label="일반 나무", bark="#5A4030", bark_emissive="#000000", leaf="#4F8A3A",
                   leaf_emissive="#000000", leaf_low="#B8A24A", glow=False, fruit=False,
                   fruit_color="#D9452B", particles="leaf", accent="#5FA85A"),
    "fruit": dict(label="열매 나무", bark="#5A4030", bark_emissive="#000000", leaf="#4F8A3A",
                  leaf_emissive="#000000", leaf_low="#B8A24A", glow=False, fruit=True,
                  fruit_color="#D9452B", particles="leaf", accent="#E2563A"),
}


def theme(name: str) -> dict:
    """Theme dict by name; unknown names fall back to "normal"."""
    return THEMES.get(name, THEMES["normal"])
