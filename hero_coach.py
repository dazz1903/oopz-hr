# OOPZ Hero / Squad Coach v1 knowledge base
#
# Scope: composition, formation, stars, skills and shard-source coaching.
# Deliberately excluded for now: gear and Exclusive Weapons.

SQUAD_GUIDES = {
    "tank": {
        "optimal": ["Kimberly", "Stetmann", "Williams", "Murphy", "Marshall"],
        "front": ["Williams", "Murphy"],
        "back": ["Kimberly", "Stetmann", "Marshall"],
        "star_priority": ["Kimberly", "Stetmann", "Williams", "Murphy", "Marshall"],
        "star_rule": "5-star Kimberly first; then get everyone to 4-star before the next 5-star push.",
        "skill_rule": "Get every skill to Lv.20 ASAP, except the top-left skill for Williams and Murphy.",
        "skill_priority": [
            "Kimberly: Barrage Strike",
            "Stetmann: Lightning Rush",
            "Williams: Iron Will, then All-Around Armor",
            "Murphy: Ironclad Barrier",
            "Marshall: Command Strategy",
        ],
    },
    "air": {
        "optimal": ["DVA", "Morrison", "Lucius", "Carlie", "Schuyler"],
        "front": ["Lucius", "Carlie"],
        "back": ["DVA", "Morrison", "Schuyler"],
        "star_priority": ["DVA", "Morrison", "Lucius", "Carlie", "Schuyler"],
        "star_rule": "Get everyone to at least 3-star before pushing 5-star heroes; then follow the listed priority.",
        "skill_rule": "Get every skill to Lv.20 ASAP, except the top-left skill for Carlie and Lucius.",
        "skill_priority": [
            "DVA: Steel Barrage",
            "Morrison: Knight's Spirit, then Silver Armor",
            "Lucius: Inferno Blaze",
            "Carlie: Armor-Piercing Shot",
            "Schuyler: Vortex Missile",
        ],
    },
    "missile": {
        "optimal": ["Swift", "Tesla", "Adam", "Fiona", "McGregor"],
        "front": ["Adam", "McGregor"],
        "back": ["Swift", "Tesla", "Fiona"],
        "star_priority": ["Swift", "Tesla", "Adam", "Fiona", "McGregor"],
        "star_rule": "Follow the supplied Missile Squad 5-star/level priority in this order.",
        "skill_rule": "Get every skill to Lv.20 ASAP in priority order, then max in priority order.",
    },
}

TYPE_COUNTERS = {
    "tank": {"beats": "missile", "bonus": 20},
    "air": {"beats": "tank", "bonus": 20},
    "missile": {"beats": "air", "bonus": 20},
}

# Current-server Tavern rule from Queen's recruitment screen.
# These are the currently available UR hero portraits/shards shown in Tavern.
# Future Season 2 additions are intentionally NOT considered currently farmable.
CURRENT_TAVERN_UR = {
    "Carlie", "DVA", "Swift", "Tesla", "Kimberly", "Murphy", "Marshall",
}

SEASON2_TAVERN_LATER = {
    "Williams", "Schuyler",
}

UNIVERSAL_SHARD_RULE = (
    "Default: protect Universal UR shards for important non-Tavern heroes. "
    "Do not prioritize universals on a currently Tavern-farmable hero when a "
    "non-Tavern priority hero needs them. A small spend to hit an immediate "
    "major breakpoint can be an exception."
)


def hero_prompt_knowledge() -> str:
    lines = [
        "OOPZ verified squad targets:",
        "Tank: Kimberly, Stetmann, Williams, Murphy, Marshall. Front Williams + Murphy; back Kimberly + Stetmann + Marshall.",
        "Air: DVA, Morrison, Lucius, Carlie, Schuyler. Front Lucius + Carlie; back DVA + Morrison + Schuyler.",
        "Missile: Swift, Tesla, Adam, Fiona, McGregor. Front Adam + McGregor; back Swift + Tesla + Fiona.",
        "Counters: Tank +20% vs Missile; Air +20% vs Tank; Missile +20% vs Air.",
        "Current Tavern UR source list: " + ", ".join(sorted(CURRENT_TAVERN_UR)) + ".",
        "Season 2 Tavern later, NOT currently Tavern-farmable: " + ", ".join(sorted(SEASON2_TAVERN_LATER)) + ".",
        "Universal shard policy: " + UNIVERSAL_SHARD_RULE,
        "Do not discuss gear or Exclusive Weapons.",
    ]
    return "\n".join(lines)
