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


# Verified prerequisite rules from OOPZ in-game research popups.
# Keys use row/column so duplicate names such as Advanced Protection stay unambiguous.
T10_PREREQUISITES = {
    (6, "center"): [((5, "left"), 5), ((5, "right"), 5)],  # Morale
    (7, "left"): [((6, "center"), 4)],
    (7, "center"): [((6, "center"), 4)],
    (7, "right"): [((6, "center"), 4)],
    (10, "left"): [((9, "center"), 2)],
    (10, "center"): [((9, "center"), 2)],
    (10, "right"): [((9, "center"), 1)],
    (11, "center"): [((10, "left"), 10)],  # Unit X
}


def scan_levels_by_position(scan: dict) -> dict[tuple[int, str], int]:
    """Normalize Gemini scan output into {(row, column): current_level}."""
    levels = {}
    for node in scan.get("nodes") or []:
        try:
            row = int(node.get("row"))
            column = str(node.get("column") or "").lower()
            current = int(node.get("current_level"))
        except (TypeError, ValueError):
            continue
        levels[(row, column)] = current
    return levels


def get_t10_next_moves(scan: dict, hq_level: int) -> list[str]:
    """Return only coaching steps supported by verified prerequisite data."""
    levels = scan_levels_by_position(scan)
    moves = []

    # Immediate blocker visible in the mapped mid-tree.
    morale = levels.get((6, "center"))
    hp2 = levels.get((5, "left"))
    defense2 = levels.get((5, "right"))
    if morale is not None and morale < 10:
        blockers = []
        if hp2 is not None and hp2 < 5:
            blockers.append(f"HP Boost II {hp2} → 5")
        if defense2 is not None and defense2 < 5:
            blockers.append(f"Defense Boost II {defense2} → 5")
        if blockers:
            moves.extend(blockers)
            moves.append("Then continue Morale — its next research is blocked until both reach Lv.5.")
            return moves

    # Final T10 wall. Unit X explicitly depends on HP Boost III 10.
    unit_x = levels.get((11, "center"))
    hp3 = levels.get((10, "left"))
    ap_final = levels.get((9, "center"))
    if unit_x == 0:
        if hp3 is not None and hp3 < 10:
            if ap_final is not None and ap_final < 2:
                moves.append(f"Advanced Protection {ap_final} → 2 to open HP Boost III progression.")
            moves.append(f"Push HP Boost III {hp3} → 10 — Unit X explicitly requires Lv.10.")
        if hq_level < 30:
            moves.append(f"Push HQ{hq_level} → HQ30; Unit X requires Tech Center 30.")
        else:
            moves.append("Make sure Tech Center is Lv.30 for Unit X.")
        moves.append("After Unit X unlocks, Barracks 30 is required to train T10 units.")
        return moves

    if unit_x == 1:
        moves.append("Unit X is unlocked. Get Barracks 30 if needed, then train T10 units.")
        return moves

    return moves
