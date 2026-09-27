# OOPZ T10 / Special Forces coaching data

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
        "gold_total": 560_000_000,
        "valor_total": 2_400,
    },
}

T10_TOTAL_GOLD = 10_590_000_000
T10_TOTAL_VALOR = 76_480

T10_REQUIREMENTS = {
    "final_nodes": {
        "hq": 30,
        "tech_center": 30,
    },
    "unit_x": {
        "hq": 30,
        "tech_center": 30,
        "barracks": 30,
    },
}


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
        "HQ30 reached. Prioritize Tech Center 30 and Barracks 30 if they are "
        "not already complete, then finish the remaining T10 research."
    )
