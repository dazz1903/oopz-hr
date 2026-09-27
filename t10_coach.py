# OOPZ T10 / Special Forces coaching data
#
# Tree order is based on the current in-game Special Forces layout mapped by OOPZ.
# Keep calculations conservative: never invent per-level costs that have not been
# verified against the current game client.

T10_TREE_ROWS = [
    ("HP Boost I", "Attack Boost I", "Defense Boost I"),
    ("Advanced Protection",),
    ("Defense Training VII", "Weapon Training VII", "Advanced Armor VII"),
    ("Focused Training I", "Barracks Expansion I"),
    ("HP Boost II", "Attack Boost II", "Defense Boost II"),
    ("Morale",),
    ("Defense Training VIII", "Weapon Training VIII", "Advanced Armor VIII"),
    ("Rapid Field Dressing I", "Infirmary Expansion I"),
    ("Advanced Protection",),
    ("HP Boost III", "Attack Boost III", "Defense Boost III"),
    ("Unit X",),
]

T10_NODE_MAX_LEVELS = {
    "Unit X": 1,
}

# Verified late-game wall totals supplied/mapped in OOPZ.
T10_RESEARCH = {
    "advanced_protection": {
        "name": "Advanced Protection",
        "gold_total": 1_720_000_000,
        "valor_total": 16_960,
    },
    "hp_boost_iii": {
        "name": "HP Boost III",
        "gold_total": 2_770_000_000,
        "valor_total": 19_040,
    },
    "attack_boost_iii": {
        "name": "Attack Boost III",
        "gold_total": 2_770_000_000,
        "valor_total": 19_040,
    },
    "defense_boost_iii": {
        "name": "Defense Boost III",
        "gold_total": 2_770_000_000,
        "valor_total": 19_040,
    },
    "unit_x": {
        "name": "Unit X (T10)",
        "gold_total": 565_800_000,
        "valor_total": 2_400,
        "iron_total": 188_600_000,
        "food_total": 188_600_000,
    },
}

# Rounded planning totals for the verified final wall.
T10_TOTAL_GOLD = 10_595_800_000
T10_TOTAL_VALOR = 76_480

T10_REQUIREMENTS = {
    "final_nodes": {
        "hq": 30,
        "tech_center": 30,
    },
    "unit_x_research": {
        "tech_center": 30,
        "hp_boost_iii": 10,
    },
    # Barracks 30 is required to train Lv.10 units once Unit X is unlocked.
    "t10_training": {
        "barracks": 30,
    },
}


def tree_name_for_position(row: int, column: str) -> str:
    """Return the mapped research name for a scanned tree position."""
    if row < 1 or row > len(T10_TREE_ROWS):
        return ""
    names = T10_TREE_ROWS[row - 1]
    if len(names) == 1:
        return names[0]
    column_index = {"left": 0, "center": 1, "right": 2}.get(column.lower())
    if column_index is None or column_index >= len(names):
        return ""
    return names[column_index]


def get_hq_advice(hq_level: int) -> str:
    if hq_level < 27:
        return (
            "Your immediate priority is reaching HQ27 for T9 troops. "
            "Keep collecting Valor Badges and Gold for the future T10 push."
        )

    if hq_level < 30:
        return (
            f"You are HQ{hq_level}. Continue progressing Special Forces while "
            "pushing your HQ toward 30. Do NOT wait until HQ30 to work on the "
            "T10 research path. The final research stages will require "
            "HQ30 + Tech Center 30."
        )

    return (
        "HQ30 reached. Prioritize Tech Center 30 for the final Special Forces "
        "research and Barracks 30 so you can train T10 units after Unit X unlocks."
    )
