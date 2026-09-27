import csv
import asyncio
import json
import io
import logging
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv
from google import genai
from google.genai import types
from t10_coach import T10_RESEARCH, T10_TOTAL_GOLD, T10_TOTAL_VALOR, T10_REQUIREMENTS, T10_TREE_ROWS, tree_name_for_position, get_hq_advice

load_dotenv()

TOKEN = os.environ["DISCORD_TOKEN"]
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_VISION_MODEL = os.getenv("GEMINI_VISION_MODEL", "gemini-3.8-flash").strip()
GEMINI_FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.1-flash-lite").strip()
GUILD_ID = int(os.environ["GUILD_ID"])
ROSTER_CHANNEL_ID = int(os.environ["ROSTER_CHANNEL_ID"])
LOG_CHANNEL_ID = int(os.environ["LOG_CHANNEL_ID"])
WELCOME_CHANNEL_ID = int(os.getenv("WELCOME_CHANNEL_ID", "0") or 0)
SUMMARY_CHANNEL_ID = int(os.getenv("SUMMARY_CHANNEL_ID", "0") or 0)
ACHIEVEMENTS_CHANNEL_ID = int(os.getenv("ACHIEVEMENTS_CHANNEL_ID", "0") or 0)
GRACE_HOURS = int(os.getenv("GRACE_HOURS", "24"))
GRACE_CHECK_MINUTES = int(os.getenv("GRACE_CHECK_MINUTES", "10"))
DATABASE_PATH = os.getenv("DATABASE_PATH", "oopz_roster.db")
AUTO_CREATE_ROLES = os.getenv("AUTO_CREATE_ROLES", "true").lower() in {"1", "true", "yes", "on"}
DECORATE_NICKNAMES = os.getenv("DECORATE_NICKNAMES", "true").lower() in {"1", "true", "yes", "on"}
NICKNAME_SHOW_HQ = os.getenv("NICKNAME_SHOW_HQ", "true").lower() in {"1", "true", "yes", "on"}
NICKNAME_SHOW_PRESTIGE = os.getenv("NICKNAME_SHOW_PRESTIGE", "true").lower() in {"1", "true", "yes", "on"}
NICKNAME_SHOW_POWER_TIER = os.getenv("NICKNAME_SHOW_POWER_TIER", "false").lower() in {"1", "true", "yes", "on"}

VERIFIED_ROLE_ID = int(os.getenv("VERIFIED_ROLE_ID", "0") or 0)
LEADERSHIP_ROLE_ID = int(os.getenv("LEADERSHIP_ROLE_ID", "0") or 0)
TOP10_ROLE_ID = int(os.getenv("TOP10_ROLE_ID", "0") or 0)
TOP25_ROLE_ID = int(os.getenv("TOP25_ROLE_ID", "0") or 0)


def parse_role_map(value: str) -> dict[int, int]:
    result: dict[int, int] = {}
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        key, role_id = part.split(":", 1)
        result[int(key.strip())] = int(role_id.strip())
    return result


def parse_id_set(value: str) -> set[int]:
    result: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if part:
            result.add(int(part))
    return result


def parse_thresholds(value: str) -> list[int]:
    values = []
    for part in value.split(","):
        part = part.strip()
        if part:
            values.append(int(part))
    return sorted(set(values), reverse=True)


RANK_ROLE_IDS = parse_role_map(os.getenv("RANK_ROLE_IDS", ""))
HQ_ROLE_IDS = parse_role_map(os.getenv("HQ_ROLE_IDS", ""))
POWER_TIER_ROLE_IDS = parse_role_map(os.getenv("POWER_TIER_ROLE_IDS", ""))
POWER_TIER_MILLIONS = parse_thresholds(os.getenv("POWER_TIER_MILLIONS", "60,50,40,30,20"))
EXEMPT_USER_IDS = parse_id_set(os.getenv("EXEMPT_USER_IDS", ""))
EXEMPT_ROLE_IDS = parse_id_set(os.getenv("EXEMPT_ROLE_IDS", ""))

RANK_ROLE_NAMES = {
    5: "👑 R5",
    4: "⚔️ R4",
    3: "🛡️ R3",
    2: "🔷 R2",
    1: "▫️ R1",
}
HQ_ROLE_PREFIX = "🏰 HQ"
POWER_ROLE_SUFFIX = "M+ Power"
VERIFIED_ROLE_NAME = "✅ OOPZ Member"
LEADERSHIP_ROLE_NAME = "🔐 OOPZ Leadership"
TOP10_ROLE_NAME = "🔥 Top 10 Power"
TOP25_ROLE_NAME = "⚡ Top 25 Power"

PLAYER_COLUMN_CANDIDATES = [
    "player name", "player", "name", "username", "commander", "governor",
    "playername", "player_name",
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("oopz-roster-bot")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


@dataclass
class SyncStats:
    roster_count: int = 0
    matched: int = 0
    warnings_started: int = 0
    warnings_cleared: int = 0
    kicked_left: int = 0
    exempt: int = 0
    bots_skipped: int = 0
    failed_kicks: int = 0
    roles_updated: int = 0
    nicknames_updated: int = 0


@dataclass
class RosterDiff:
    joins: list[str]
    departures: list[str]
    renames: list[tuple[str, str]]
    rank_changes: list[tuple[str, int, int]]
    hq_changes: list[tuple[str, int, int]]
    power_gains: list[tuple[str, int]]


async def db_execute(sql: str, params: tuple = ()):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(sql, params)
        await db.commit()


async def db_fetchone(sql: str, params: tuple = ()):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(sql, params) as cursor:
            return await cursor.fetchone()


async def db_fetchall(sql: str, params: tuple = ()):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(sql, params) as cursor:
            return await cursor.fetchall()


async def init_db():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS members (
                discord_id INTEGER PRIMARY KEY,
                last_name TEXT,
                last_verified_name TEXT,
                last_verified_uid TEXT,
                ever_verified INTEGER NOT NULL DEFAULT 0,
                warning_started_at TEXT,
                manually_exempt INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS roster (
                player_name TEXT PRIMARY KEY,
                player_uid TEXT,
                rank INTEGER,
                level INTEGER,
                power INTEGER,
                snapshot_date TEXT,
                imported_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )
        member_cols = [row[1] for row in await db.execute_fetchall("PRAGMA table_info(members)")]
        if "last_verified_name" not in member_cols:
            await db.execute("ALTER TABLE members ADD COLUMN last_verified_name TEXT")
        if "last_verified_uid" not in member_cols:
            await db.execute("ALTER TABLE members ADD COLUMN last_verified_uid TEXT")

        roster_cols = [row[1] for row in await db.execute_fetchall("PRAGMA table_info(roster)")]
        for col, sql_type in (("player_uid", "TEXT"), ("rank", "INTEGER"), ("level", "INTEGER"),
                              ("power", "INTEGER"), ("snapshot_date", "TEXT")):
            if col not in roster_cols:
                await db.execute(f"ALTER TABLE roster ADD COLUMN {col} {sql_type}")
        await db.commit()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: Optional[datetime] = None) -> str:
    return (dt or now_utc()).isoformat()


def parse_iso(value: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(value) if value else None


def member_name(member: discord.Member) -> str:
    return member.display_name.strip()


def strip_bot_decorations(name: str) -> str:
    """Remove only decorations created by this bot, never arbitrary user suffixes/emojis."""
    # Examples: "Player • HQ28", "Player • HQ28 • 🔥T10", "Player • HQ28 • 60M+"
    return re.sub(r"(?:\s*•\s*(?:HQ\d+|🔥T10|⚡T25|\d+M\+))+$", "", name).strip()


def canonical_name(name: str) -> str:
    """Relaxed comparison form for Discord ↔ LWMA names.

    We intentionally ignore bot decorations, capitalization, whitespace, punctuation,
    emoji/symbol decoration, and Unicode presentation differences. The actual LWMA
    name is still preserved separately for display and UID tracking.
    """
    name = strip_bot_decorations(name)
    name = unicodedata.normalize("NFKC", name).casefold()
    # Keep letters/numbers only. This makes e.g. `Auntie depressant 💅` match
    # `Auntie depressant`, while preserving meaningful letters/digits.
    return "".join(ch for ch in name if ch.isalnum())


def levenshtein(a: str, b: str) -> int:
    """Small dependency-free edit distance used for typo-tolerant name matching."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    if len(a) > len(b):
        a, b = b, a
    previous = list(range(len(a) + 1))
    for i, cb in enumerate(b, start=1):
        current = [i]
        for j, ca in enumerate(a, start=1):
            current.append(min(
                current[j - 1] + 1,      # insertion
                previous[j] + 1,         # deletion
                previous[j - 1] + (ca != cb),  # substitution
            ))
        previous = current
    return previous[-1]


def roster_name_index(roster: dict[str, dict]) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for game_name in roster:
        index.setdefault(canonical_name(game_name), []).append(game_name)
    return index


def relaxed_roster_name_match(visible_name: str, roster: dict[str, dict]) -> Optional[str]:
    """Return one safe fuzzy LWMA match, or None when ambiguous.

    Policy requested for OOPZ:
      * emoji/punctuation/spacing/case differences are ignored completely;
      * one character difference is tolerated even on short names;
      * up to two character edits are tolerated on names of 5+ characters;
      * harmless Discord suffix/prefix decoration is tolerated when the roster name
        is a unique 5+ character prefix/suffix (e.g. `Shelly26 of 2294`);
      * ambiguous near-matches are NEVER guessed.
    """
    visible = canonical_name(visible_name)
    if not visible:
        return None

    exact = roster_name_index(roster).get(visible, [])
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return None

    scored: list[tuple[int, str, str]] = []
    affix_candidates: list[str] = []
    for game_name in roster:
        candidate = canonical_name(game_name)
        if not candidate:
            continue
        shorter, longer = (candidate, visible) if len(candidate) <= len(visible) else (visible, candidate)
        # Extra words / clan flair around an otherwise unique substantial name.
        if len(shorter) >= 5 and (longer.startswith(shorter) or longer.endswith(shorter)):
            if len(longer) - len(shorter) <= 8:
                affix_candidates.append(game_name)
        scored.append((levenshtein(visible, candidate), game_name, candidate))

    if len(affix_candidates) == 1:
        return affix_candidates[0]

    scored.sort(key=lambda x: (x[0], x[1].casefold()))
    if not scored:
        return None

    best_distance, best_name, best_canonical = scored[0]
    max_distance = 2 if min(len(visible), len(best_canonical)) >= 5 else 1
    if best_distance > max_distance:
        return None

    # Don't auto-match when two roster names are equally plausible.
    if len(scored) > 1 and scored[1][0] == best_distance:
        return None

    return best_name


def find_role_by_name(guild: discord.Guild, role_name: str) -> Optional[discord.Role]:
    target = role_name.casefold().strip()
    return next((r for r in guild.roles if r.name.casefold().strip() == target), None)


def best_roster_candidates(visible_name: str, roster: dict[str, dict], limit: int = 3) -> list[tuple[int, str]]:
    visible = canonical_name(visible_name)
    if not visible:
        return []
    scored = []
    for game_name in roster:
        candidate = canonical_name(game_name)
        if candidate:
            scored.append((levenshtein(visible, candidate), game_name))
    scored.sort(key=lambda x: (x[0], x[1].casefold()))
    return scored[:limit]


def fmt_power(power: Optional[int]) -> str:
    if power is None:
        return "?"
    if power >= 1_000_000:
        return f"{power / 1_000_000:.1f}M"
    return f"{power:,}"


async def get_channel(channel_id: int) -> Optional[discord.TextChannel]:
    if not channel_id:
        return None
    channel = bot.get_channel(channel_id)
    return channel if isinstance(channel, discord.TextChannel) else None


async def log_action(message: str):
    log.info(message)
    channel = await get_channel(LOG_CHANNEL_ID)
    if channel:
        try:
            await channel.send(message)
        except discord.HTTPException:
            log.exception("Could not post to log channel")


async def is_exempt(member: discord.Member) -> bool:
    """Full roster-enforcement exemption. The server owner is NOT fully exempt:
    they should still match the roster and receive managed roles, but are protected
    from warnings/kicks and nickname edits separately.
    """
    if member.bot:
        return True
    if member.id in EXEMPT_USER_IDS:
        return True
    if any(role.id in EXEMPT_ROLE_IDS for role in member.roles):
        return True
    row = await db_fetchone("SELECT manually_exempt FROM members WHERE discord_id = ?", (member.id,))
    return bool(row and row["manually_exempt"])


def is_owner(member: discord.Member) -> bool:
    return member.id == member.guild.owner_id


async def is_protected_from_enforcement(member: discord.Member) -> bool:
    return is_owner(member) or await is_exempt(member)


async def upsert_member(member: discord.Member):
    await db_execute(
        """
        INSERT INTO members(discord_id, last_name, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(discord_id) DO UPDATE SET
            last_name = excluded.last_name,
            updated_at = excluded.updated_at
        """,
        (member.id, member_name(member), iso()),
    )


async def mark_verified(member: discord.Member, info: dict, game_name: str) -> bool:
    row = await db_fetchone("SELECT warning_started_at FROM members WHERE discord_id = ?", (member.id,))
    warning_was_active = bool(row and row["warning_started_at"])
    await db_execute(
        """
        INSERT INTO members(discord_id, last_name, last_verified_name, last_verified_uid,
                            ever_verified, warning_started_at, updated_at)
        VALUES (?, ?, ?, ?, 1, NULL, ?)
        ON CONFLICT(discord_id) DO UPDATE SET
            last_name = excluded.last_name,
            last_verified_name = excluded.last_verified_name,
            last_verified_uid = excluded.last_verified_uid,
            ever_verified = 1,
            warning_started_at = NULL,
            updated_at = excluded.updated_at
        """,
        (member.id, member_name(member), game_name, info.get("uid"), iso()),
    )
    return warning_was_active


async def start_warning(member: discord.Member, expected_name: Optional[str] = None) -> bool:
    # The server owner is roster-synced but never warned or kicked.
    if is_owner(member) or member.bot:
        return False

    await upsert_member(member)
    row = await db_fetchone("SELECT warning_started_at FROM members WHERE discord_id = ?", (member.id,))
    if row and row["warning_started_at"]:
        return False

    started = now_utc()
    deadline = started + timedelta(hours=GRACE_HOURS)
    await db_execute(
        "UPDATE members SET warning_started_at = ?, updated_at = ? WHERE discord_id = ?",
        (iso(started), iso(), member.id),
    )

    expected_line = (
        f"\nHR thinks your current Last War name is **{expected_name}**."
        if expected_name else ""
    )
    dm = (
        "👑 **OOPZ HR HAS OPENED A FILE ON YOU**\n\n"
        "Good news: this is probably just a nickname problem. 💀\n\n"
        "Your Discord nickname only needs to be **recognisable as your current Last War name**. "
        "Emojis, weird fonts, capitals, spaces and small differences are fine — HR is annoying, not blind."
        f"{expected_line}\n\n"
        f"You have **{GRACE_HOURS} hours** to make your Discord name recognisable. "
        f"Deadline: {discord.utils.format_dt(deadline, style='F')}.\n\n"
        "If you completely renamed yourself in Last War, contact **Queen/R4** so we can manually link your account. "
        "Once HR recognises you, your OOPZ, rank, HQ, power and prestige roles are handled automatically.\n\n"
        "If we still cannot identify you when the timer expires, the bot will remove you from the server. "
        "So, respectfully: please do not ghost HR. ❤️"
    )
    try:
        await member.send(dm)
        dm_status = "DM sent"
    except discord.HTTPException:
        dm_status = "DM could not be delivered"

    await log_action(
        f"⚠️ **Identity check opened** — {member.mention} (`{member_name(member)}`) — "
        f"{GRACE_HOURS}h grace started; {dm_status}."
    )
    return True


async def _get_or_create_role(guild: discord.Guild, *, role_id: int = 0, name: str) -> Optional[discord.Role]:
    if role_id:
        role = guild.get_role(role_id)
        if role:
            return role
    role = discord.utils.get(guild.roles, name=name)
    if role or not AUTO_CREATE_ROLES:
        return role
    try:
        role = await guild.create_role(name=name, reason="OOPZ automated roster hierarchy")
        await log_action(f"✨ **Created managed role** — `{name}`")
        return role
    except discord.Forbidden:
        await log_action(f"🚫 **Could not create role** `{name}` — bot needs Manage Roles.")
    except discord.HTTPException as exc:
        await log_action(f"🚫 **Could not create role** `{name}` — Discord error: {exc}")
    return None


def power_tier(power: Optional[int]) -> Optional[int]:
    if power is None:
        return None
    millions = power / 1_000_000
    for threshold in POWER_TIER_MILLIONS:
        if millions >= threshold:
            return threshold
    return None


def power_role_name(threshold: int) -> str:
    return f"💥 {threshold}{POWER_ROLE_SUFFIX}"


def _looks_managed(role: discord.Role) -> bool:
    return (
        role.id in {VERIFIED_ROLE_ID, LEADERSHIP_ROLE_ID, TOP10_ROLE_ID, TOP25_ROLE_ID}
        or role.id in RANK_ROLE_IDS.values()
        or role.id in HQ_ROLE_IDS.values()
        or role.id in POWER_TIER_ROLE_IDS.values()
        or role.name in {VERIFIED_ROLE_NAME, LEADERSHIP_ROLE_NAME, TOP10_ROLE_NAME, TOP25_ROLE_NAME}
        or role.name in RANK_ROLE_NAMES.values()
        or role.name.startswith(HQ_ROLE_PREFIX)
        or (role.name.startswith("💥 ") and role.name.endswith(POWER_ROLE_SUFFIX))
    )


async def sync_member_roles(member: discord.Member, info: dict, power_position: Optional[int]) -> bool:
    desired_roles: list[discord.Role] = []

    verified = await _get_or_create_role(member.guild, role_id=VERIFIED_ROLE_ID, name=VERIFIED_ROLE_NAME)
    if verified:
        desired_roles.append(verified)

    rank = info.get("rank")
    if rank in RANK_ROLE_NAMES:
        role = await _get_or_create_role(member.guild, role_id=RANK_ROLE_IDS.get(rank, 0), name=RANK_ROLE_NAMES[rank])
        if role:
            desired_roles.append(role)

    if rank is not None and rank >= 4:
        role = await _get_or_create_role(member.guild, role_id=LEADERSHIP_ROLE_ID, name=LEADERSHIP_ROLE_NAME)
        if role:
            desired_roles.append(role)

    level = info.get("level")
    if level is not None:
        role = await _get_or_create_role(member.guild, role_id=HQ_ROLE_IDS.get(level, 0), name=f"{HQ_ROLE_PREFIX}{level}")
        if role:
            desired_roles.append(role)

    tier = power_tier(info.get("power"))
    if tier is not None:
        role = await _get_or_create_role(member.guild, role_id=POWER_TIER_ROLE_IDS.get(tier, 0), name=power_role_name(tier))
        if role:
            desired_roles.append(role)

    # Prestige badges are exclusive: Top 10 gets Top 10, positions 11-25 get Top 25.
    if power_position is not None and power_position <= 10:
        role = await _get_or_create_role(member.guild, role_id=TOP10_ROLE_ID, name=TOP10_ROLE_NAME)
        if role:
            desired_roles.append(role)
    elif power_position is not None and power_position <= 25:
        role = await _get_or_create_role(member.guild, role_id=TOP25_ROLE_ID, name=TOP25_ROLE_NAME)
        if role:
            desired_roles.append(role)

    desired_ids = {r.id for r in desired_roles}
    current_managed = [r for r in member.roles if _looks_managed(r)]
    to_remove = [r for r in current_managed if r.id not in desired_ids]
    current_ids = {r.id for r in member.roles}
    to_add = [r for r in desired_roles if r.id not in current_ids]

    if not to_add and not to_remove:
        return False
    try:
        if to_remove:
            await member.remove_roles(*to_remove, reason="LWMA roster hierarchy sync")
        if to_add:
            await member.add_roles(*to_add, reason="LWMA roster hierarchy sync")
        return True
    except discord.Forbidden:
        await log_action(f"🚫 **Role sync failed** — {member.mention} — bot needs Manage Roles and must sit above managed roles.")
    except discord.HTTPException as exc:
        await log_action(f"🚫 **Role sync failed** — {member.mention} — Discord error: {exc}")
    return False


async def kick_member(member: discord.Member, reason: str) -> bool:
    if is_owner(member):
        await log_action(f"🛡️ **Removal blocked** — {member.mention} is the server owner. HR is powerful, not suicidal.")
        return False
    try:
        await member.kick(reason=reason)
        await log_action(f"❌ **Kicked** — `{member}` / `{member_name(member)}` — {reason}")
        return True
    except discord.Forbidden:
        await log_action(f"🚫 **Kick failed** — {member.mention} (`{member_name(member)}`) — bot lacks permission or role hierarchy is too low. Reason: {reason}")
    except discord.HTTPException as exc:
        await log_action(f"🚫 **Kick failed** — {member.mention} (`{member_name(member)}`) — Discord error: {exc}")
    return False


def decode_csv(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Could not decode CSV text")


def detect_dialect(text: str):
    try:
        return csv.Sniffer().sniff(text[:10000], delimiters=",;\t|")
    except csv.Error:
        return csv.excel


def _find_column(fieldnames: list[str], candidates: list[str]) -> Optional[str]:
    normalized = {f.strip().lower(): f for f in fieldnames if f}
    for candidate in candidates:
        if candidate in normalized:
            return normalized[candidate]
    return None


def find_player_column(fieldnames: list[str]) -> Optional[str]:
    col = _find_column(fieldnames, PLAYER_COLUMN_CANDIDATES)
    if col:
        return col
    normalized = {f.strip().lower(): f for f in fieldnames if f}
    for normalized_name, original in normalized.items():
        if "player" in normalized_name and "name" in normalized_name:
            return original
    return None


def parse_roster_csv(data: bytes) -> tuple[dict[str, dict], str]:
    text = decode_csv(data)
    reader = csv.DictReader(io.StringIO(text), dialect=detect_dialect(text))
    if not reader.fieldnames:
        raise ValueError("CSV has no header row")

    player_col = find_player_column(reader.fieldnames)
    if not player_col:
        raise ValueError("Could not identify player-name column. Found columns: " + ", ".join(reader.fieldnames))

    rank_col = _find_column(reader.fieldnames, ["rank", "alliance rank", "alliance_rank"])
    level_col = _find_column(reader.fieldnames, ["level", "hq", "hq level", "hq_level"])
    uid_col = _find_column(reader.fieldnames, ["playeruid", "player uid", "uid", "player_id"])
    power_col = _find_column(reader.fieldnames, ["power", "total power", "total_power"])
    snapshot_col = _find_column(reader.fieldnames, ["snapshotdate", "snapshot date", "date"])

    def as_int(row: dict, col: Optional[str]) -> Optional[int]:
        try:
            raw = (row.get(col) or "").replace(",", "").strip() if col else ""
            return int(float(raw)) if raw else None
        except (ValueError, AttributeError):
            return None

    players: dict[str, dict] = {}
    seen_uids: set[str] = set()
    for row in reader:
        name = (row.get(player_col) or "").strip()
        if not name:
            continue
        uid = (row.get(uid_col) or "").strip() if uid_col else None
        if uid and uid in seen_uids:
            raise ValueError(f"Duplicate PlayerUID detected: {uid}")
        if uid:
            seen_uids.add(uid)
        players[name] = {
            "uid": uid,
            "rank": as_int(row, rank_col),
            "level": as_int(row, level_col),
            "power": as_int(row, power_col),
            "snapshot_date": (row.get(snapshot_col) or "").strip() if snapshot_col else None,
        }

    if not players:
        raise ValueError("Roster contains zero player names")
    if len(players) < 5:
        raise ValueError(f"Roster contains only {len(players)} unique players. Refusing to sync as a safety check.")
    return players, player_col


async def get_roster() -> dict[str, dict]:
    rows = await db_fetchall("SELECT player_name, player_uid, rank, level, power, snapshot_date FROM roster")
    return {
        row["player_name"]: {
            "uid": row["player_uid"], "rank": row["rank"], "level": row["level"],
            "power": row["power"], "snapshot_date": row["snapshot_date"],
        }
        for row in rows
    }


def roster_by_uid(roster: dict[str, dict]) -> dict[str, tuple[str, dict]]:
    return {info["uid"]: (name, info) for name, info in roster.items() if info.get("uid")}


def power_positions(roster: dict[str, dict]) -> dict[str, int]:
    ordered = sorted(roster.items(), key=lambda item: (item[1].get("power") or -1, item[0]), reverse=True)
    return {name: pos for pos, (name, _) in enumerate(ordered, start=1)}


def diff_rosters(old: dict[str, dict], new: dict[str, dict]) -> RosterDiff:
    old_uids = roster_by_uid(old)
    new_uids = roster_by_uid(new)
    joins: list[str] = []
    departures: list[str] = []
    renames: list[tuple[str, str]] = []
    rank_changes: list[tuple[str, int, int]] = []
    hq_changes: list[tuple[str, int, int]] = []
    power_gains: list[tuple[str, int]] = []

    if old_uids and new_uids:
        for uid, (name, info) in new_uids.items():
            if uid not in old_uids:
                joins.append(name)
                continue
            old_name, old_info = old_uids[uid]
            if old_name != name:
                renames.append((old_name, name))
            if old_info.get("rank") is not None and info.get("rank") is not None and old_info["rank"] != info["rank"]:
                rank_changes.append((name, old_info["rank"], info["rank"]))
            if old_info.get("level") is not None and info.get("level") is not None and old_info["level"] != info["level"]:
                hq_changes.append((name, old_info["level"], info["level"]))
            if old_info.get("power") is not None and info.get("power") is not None:
                gain = info["power"] - old_info["power"]
                if gain:
                    power_gains.append((name, gain))
        for uid, (name, _) in old_uids.items():
            if uid not in new_uids:
                departures.append(name)
    else:
        # Fallback for legacy data with no UIDs.
        joins = sorted(set(new) - set(old))
        departures = sorted(set(old) - set(new))
        for name in set(old) & set(new):
            old_info, info = old[name], new[name]
            if old_info.get("rank") is not None and info.get("rank") is not None and old_info["rank"] != info["rank"]:
                rank_changes.append((name, old_info["rank"], info["rank"]))
            if old_info.get("level") is not None and info.get("level") is not None and old_info["level"] != info["level"]:
                hq_changes.append((name, old_info["level"], info["level"]))
            if old_info.get("power") is not None and info.get("power") is not None:
                gain = info["power"] - old_info["power"]
                if gain:
                    power_gains.append((name, gain))

    power_gains.sort(key=lambda x: x[1], reverse=True)
    return RosterDiff(sorted(joins), sorted(departures), renames, rank_changes, hq_changes, power_gains)


async def replace_roster(players: dict[str, dict]):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("BEGIN")
        await db.execute("DELETE FROM roster")
        imported_at = iso()
        await db.executemany(
            "INSERT INTO roster(player_name, player_uid, rank, level, power, snapshot_date, imported_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(name, info.get("uid"), info.get("rank"), info.get("level"), info.get("power"), info.get("snapshot_date"), imported_at)
             for name, info in sorted(players.items())],
        )
        await db.execute(
            "INSERT INTO meta(key, value) VALUES('last_import_at', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (imported_at,),
        )
        await db.commit()


async def find_expected_name(row, roster: dict[str, dict]) -> Optional[str]:
    if not row:
        return None
    uid = row["last_verified_uid"] if "last_verified_uid" in row.keys() else None
    if uid:
        entry = roster_by_uid(roster).get(uid)
        if entry:
            return entry[0]
    return None


async def resolve_roster_identity(member: discord.Member, roster: dict[str, dict], row=None) -> Optional[tuple[str, dict]]:
    """Resolve a Discord member to one LWMA identity.

    PlayerUID is authoritative once a Discord account has ever been linked to a
    UID. A rename must never break that link, and a missing linked UID must
    never be silently reassigned by nickname matching.
    """
    if row is None:
        row = await db_fetchone(
            "SELECT last_verified_name, last_verified_uid, ever_verified FROM members WHERE discord_id = ?",
            (member.id,),
        )

    # Existing UID links always win over names. If that UID disappeared from
    # the current roster, return no identity: sync_guild will classify the
    # member as departed and remove them immediately.
    if row:
        uid = row["last_verified_uid"] if "last_verified_uid" in row.keys() else None
        if uid:
            entry = roster_by_uid(roster).get(uid)
            if entry:
                return entry
            return None

    # Name/fuzzy matching is ONLY for Discord users who do not yet have a
    # durable UID link (new members / legacy migration).
    visible = member_name(member)
    if visible in roster:
        return visible, roster[visible]

    game_name = relaxed_roster_name_match(visible, roster)
    if game_name:
        return game_name, roster[game_name]

    # Legacy pre-UID records may still have a previously verified name.
    if row:
        old_name = row["last_verified_name"] if "last_verified_name" in row.keys() else None
        if old_name:
            game_name = relaxed_roster_name_match(old_name, roster)
            if game_name:
                return game_name, roster[game_name]
    return None


def build_decorated_nickname(game_name: str, info: dict, power_position: Optional[int]) -> str:
    if not DECORATE_NICKNAMES:
        return game_name

    decorations: list[str] = []
    level = info.get("level")
    if NICKNAME_SHOW_HQ and level is not None:
        decorations.append(f"HQ{level}")

    if NICKNAME_SHOW_PRESTIGE and power_position is not None:
        if power_position <= 10:
            decorations.append("🔥T10")
        elif power_position <= 25:
            decorations.append("⚡T25")

    if NICKNAME_SHOW_POWER_TIER:
        tier = power_tier(info.get("power"))
        if tier is not None:
            decorations.append(f"{tier}M+")

    if not decorations:
        return game_name[:32]

    candidate = f"{game_name} • " + " • ".join(decorations)
    if len(candidate) <= 32:
        return candidate

    # Compact fallback while preserving the actual Last War name in full whenever possible.
    compact: list[str] = []
    if NICKNAME_SHOW_HQ and level is not None:
        compact.append(f"H{level}")
    if NICKNAME_SHOW_PRESTIGE and power_position is not None:
        if power_position <= 10:
            compact.append("T10")
        elif power_position <= 25:
            compact.append("T25")
    candidate = f"{game_name} • " + " • ".join(compact) if compact else game_name
    if len(candidate) <= 32:
        return candidate

    # Never mutilate a player's game name just to fit a badge.
    return game_name[:32]


async def sync_member_nickname(member: discord.Member, game_name: str, info: dict, power_position: Optional[int]) -> bool:
    # Discord does not allow bots to manage the server owner's nickname.
    if is_owner(member):
        return False
    desired = build_decorated_nickname(game_name, info, power_position)
    if member.nick == desired:
        return False
    try:
        await member.edit(nick=desired, reason="OOPZ roster hierarchy nickname sync")
        return True
    except discord.Forbidden:
        await log_action(
            f"🚫 **Nickname sync failed** — {member.mention} — bot needs Manage Nicknames and must sit above this member's highest role."
        )
    except discord.HTTPException as exc:
        await log_action(f"🚫 **Nickname sync failed** — {member.mention} — Discord error: {exc}")
    return False


async def sync_guild(guild: discord.Guild, roster: dict[str, dict]) -> SyncStats:
    stats = SyncStats(roster_count=len(roster))
    positions = power_positions(roster)
    uid_index = roster_by_uid(roster)
    members = [m async for m in guild.fetch_members(limit=None)]

    for member in members:
        if member.bot:
            stats.bots_skipped += 1
            continue
        if await is_exempt(member):
            stats.exempt += 1
            continue

        name = member_name(member)
        row = await db_fetchone(
            "SELECT ever_verified, warning_started_at, last_name, last_verified_name, last_verified_uid FROM members WHERE discord_id = ?",
            (member.id,),
        )
        ever_verified = bool(row and row["ever_verified"])
        verified_name = row["last_verified_name"] if row else None
        verified_uid = row["last_verified_uid"] if row else None

        identity = await resolve_roster_identity(member, roster, row)
        if identity:
            game_name, info = identity
            cleared = await mark_verified(member, info, game_name)
            if await sync_member_roles(member, info, positions.get(game_name)):
                stats.roles_updated += 1
            if await sync_member_nickname(member, game_name, info, positions.get(game_name)):
                stats.nicknames_updated += 1
            stats.matched += 1
            if cleared:
                stats.warnings_cleared += 1
                await log_action(f"✅ **Match restored** — {member.mention} verified as `{game_name}`; warning cleared.")
            continue

        # Stable UID is the safest indicator of whether the player actually left the alliance.
        if ever_verified and verified_uid:
            uid_entry = uid_index.get(verified_uid)
            if uid_entry is None:
                if await kick_member(member, f"Previously verified OOPZ UID `{verified_uid}` is absent from latest LWMA roster"):
                    stats.kicked_left += 1
                else:
                    stats.failed_kicks += 1
                continue
            expected_name = uid_entry[0]
            if await start_warning(member, expected_name=expected_name):
                stats.warnings_started += 1
            continue

        # Legacy fallback for members verified before UID tracking existed.
        if ever_verified and verified_name and verified_name not in roster:
            if await kick_member(member, f"Previously verified OOPZ player `{verified_name}` is absent from latest LWMA roster"):
                stats.kicked_left += 1
            else:
                stats.failed_kicks += 1
            continue

        if await start_warning(member):
            stats.warnings_started += 1

    return stats


async def send_welcome(member: discord.Member, *, verified: bool, info: Optional[dict] = None) -> bool:
    channel = await get_channel(WELCOME_CHANNEL_ID)
    if not channel:
        await log_action("🚫 **Welcome failed** — configured welcome channel could not be found.")
        return False

    if verified and info:
        rank = info.get("rank")
        level = info.get("level")
        power = info.get("power")
        embed = discord.Embed(
            title="👑 OOPZ HAS A NEW ARRIVAL",
            description=(
                f"Welcome {member.mention} to **OOPZ**. You have been identified, processed and released into the asylum. 💀🔥\n\n"
                "HR found you on the current LWMA roster and **verified you automatically**. "
                "Your roles are being handled by the bureaucracy from here."
            ),
            timestamp=now_utc(),
        )
        embed.add_field(name="⚔️ Rank", value=f"R{rank}" if rank else "—", inline=True)
        embed.add_field(name="🏰 HQ", value=f"HQ{level}" if level else "—", inline=True)
        embed.add_field(name="💥 Power", value=fmt_power(power), inline=True)
        embed.set_footer(text="OOPZ HR Department • File approved. Chaos authorised.")
    else:
        embed = discord.Embed(
            title="👋 Welcome to OOPZ",
            description=(
                f"Welcome {member.mention}! You have officially entered the asylum. 💀\n\n"
                "Before we unleash the rest of the server, **HR needs to figure out who the hell you are.**\n\n"
                "Your Discord nickname should be **recognisable as your current Last War name**. "
                "Emojis, weird fonts, extra decoration and minor differences are fine — **HR is annoying, not blind.**\n\n"
                f"You have **{GRACE_HOURS} hours** to match the current OOPZ roster. "
                "If HR still can't recognise you, check your DMs. If you completely changed your Last War name, "
                "contact **Queen/R4** so we can manually link you before the bureaucracy decides you no longer exist.\n\n"
                "Once verified, HR automatically sorts your **OOPZ Member • R-rank • HQ • Power • Top 25/10** roles.\n\n"
                "Welcome to OOPZ. Please enjoy your stay and try not to make HR open a second case file on day one. 👑🔥"
            ),
            timestamp=now_utc(),
        )
        embed.set_footer(text="OOPZ HR Department • Automatic verification")
    try:
        await channel.send(embed=embed)
        return True
    except discord.HTTPException as exc:
        log.exception("Could not send welcome message")
        await log_action(f"🚫 **Welcome failed** — {member.mention} — Discord error: {exc}")
        return False


async def send_sync_summary(channel: discord.abc.Messageable, stats: SyncStats, filename: str, column: str):
    embed = discord.Embed(title="👑 OOPZ HR — Roster Processing Complete", timestamp=now_utc())
    embed.description = "The spreadsheet has been consumed. HR has opinions."
    embed.add_field(name="📄 CSV", value=filename, inline=False)
    embed.add_field(name="LWMA roster", value=str(stats.roster_count), inline=True)
    embed.add_field(name="✅ Matched", value=str(stats.matched), inline=True)
    embed.add_field(name="🏷️ Role updates", value=str(stats.roles_updated), inline=True)
    embed.add_field(name="✏️ Nickname updates", value=str(stats.nicknames_updated), inline=True)
    embed.add_field(name="⚠️ New identity checks", value=str(stats.warnings_started), inline=True)
    embed.add_field(name="❤️ Cases resolved", value=str(stats.warnings_cleared), inline=True)
    embed.add_field(name="🚪 Left OOPZ / removed", value=str(stats.kicked_left), inline=True)
    embed.add_field(name="🌍 Guests / exempt", value=str(stats.exempt), inline=True)
    embed.add_field(name="🤖 Bots skipped", value=str(stats.bots_skipped), inline=True)
    if stats.failed_kicks:
        embed.add_field(name="🚫 Failed removals", value=str(stats.failed_kicks), inline=True)
    embed.set_footer(text=f"Identity matching source: CSV column {column} • HR survives another day")
    await channel.send(embed=embed)


def clipped_lines(lines: list[str], limit: int = 950) -> str:
    if not lines:
        return "—"
    out = ""
    for line in lines:
        candidate = out + ("\n" if out else "") + line
        if len(candidate) > limit:
            remaining = len(lines) - len(out.splitlines())
            out += f"\n…and {remaining} more"
            break
        out = candidate
    return out


def hq_upgrade_celebration(who: str, old_hq: int, new_hq: int) -> tuple[str, str]:
    """Return an OOPZ-style title/body for an HQ upgrade. Message is based on the destination HQ."""
    messages = {
        21: (
            "🏗️ HQ21: THE CONSTRUCTION CREW SURVIVED",
            f"{who} just hauled themselves from **HQ{old_hq} → HQ21**.\n\n"
            "The tutorial is over. The bills are not. Someone tell the builders they are absolutely not getting a day off.\n\n"
            "**CONGRATULATIONS ON HQ21!** 🥳🏰"
        ),
        22: (
            "🧱 HQ22: MORE CONCRETE, LESS COMMON SENSE",
            f"{who} just upgraded **HQ{old_hq} → HQ22**.\n\n"
            "More walls. More timers. More staring at a construction icon like it personally offended you.\n\n"
            "**HQ22 SECURED.** HR approves of this deeply questionable life choice. 📋🔥"
        ),
        23: (
            "🔨 HQ23: THE SPEEDUPS HAVE BEEN SUMMONED",
            f"{who} has forced the base from **HQ{old_hq} → HQ23**.\n\n"
            "A suspicious number of speedups disappeared during the process. OOPZ Accounting has declined to investigate.\n\n"
            "**CONGRATULATIONS ON HQ23!** 🏰✨"
        ),
        24: (
            "🏰 HQ24: THIS IS GETTING EXPENSIVE",
            f"{who} just climbed **HQ{old_hq} → HQ24**.\n\n"
            "The base is bigger, the queues are longer, and your resource tiles have begun avoiding eye contact.\n\n"
            "**WELCOME TO HQ24.** Financial restraint was never part of the OOPZ strategy. 💸🔥"
        ),
        25: (
            "💀 HQ25: RESOURCES, WE HARDLY KNEW YE",
            f"{who} just marched from **HQ{old_hq} → HQ25**.\n\n"
            "Please observe one minute of silence for the resources sacrificed to make this possible. The speedups will be remembered too.\n\n"
            "**CONGRATULATIONS ON HQ25!** 🏰🔥 The expensive part has officially started."
        ),
        26: (
            "🏰🔥 HQ26: CONSTRUCTION ADDICTION CONFIRMED",
            f"{who} just upgraded **HQ{old_hq} → HQ26**.\n\n"
            "Resources: gone. Speedups: presumed dead. Construction workers: requesting union representation.\n\n"
            "**CONGRATULATIONS ON HQ26!** OOPZ grows stronger and financially less responsible by the day. 👑"
        ),
        27: (
            "🚧 HQ27: DANGEROUSLY CLOSE TO THE DEEP END",
            f"{who} has dragged the base from **HQ{old_hq} → HQ27**.\n\n"
            "At this point the construction crew lives here, the resource bill requires its own spreadsheet, and there is absolutely no turning back.\n\n"
            "**HQ27 ACHIEVED.** One step closer to becoming completely unreasonable. 🔥🏰"
        ),
        28: (
            "🚨🏰 HQ28: THE BASE HAS BECOME A PROBLEM",
            f"{who} just smashed through **HQ{old_hq} → HQ28**.\n\n"
            "HQ27 has been placed in the bin. The builders have stopped asking questions. OOPZ HR has classified this account as a developing threat.\n\n"
            "**CONGRATULATIONS ON HQ28!** 👑🔥 This is where things start looking properly dangerous."
        ),
        29: (
            "⚠️👑 HQ29: ONE. MORE. LEVEL.",
            f"{who} just went **HQ{old_hq} → HQ29**.\n\n"
            "ONE MORE. That is all. One tiny, harmless, definitely-not-ruinously-expensive HQ level standing between you and HQ30.\n\n"
            "**CONGRATULATIONS ON HQ29!** The entire alliance is now legally required to stare at the progress bar with you. 🏰🔥"
        ),
        30: (
            "👑💥 HQ30: RELEASE THE PARADE",
            f"{who} HAS DONE IT: **HQ{old_hq} → HQ30**.\n\n"
            "🚨 THE CASTLE HAS EVOLVED. 🚨\n"
            "Resources are missing. Speedups are extinct. The construction crew has not seen their families in weeks. HR has shredded the budget and fled the building.\n\n"
            "**HQ30. ABSOLUTE MENACE STATUS ACHIEVED.** 👑🏰🔥\n"
            "Congratulations from all of OOPZ — now please pretend this was financially sensible."
        ),
    }
    if new_hq in messages:
        return messages[new_hq]
    return (
        "🏰 HQ UPGRADE CHAOS",
        f"{who} just upgraded **HQ{old_hq} → HQ{new_hq}**.\n\n"
        "Construction addiction remains undefeated. Resources have mysteriously vanished. Speedups are presumed dead.\n\n"
        f"**CONGRATULATIONS ON HQ{new_hq}!** 🔥👑"
    )


def rank_promotion_celebration(who: str, old_rank: int, new_rank: int) -> str:
    messages = {
        2: (
            f"📎 {who} has escaped **R{old_rank}** and been promoted to **R2**.\n\n"
            "HR has reluctantly acknowledged your existence. A slightly nicer imaginary chair has been assigned.\n\n"
            "**CONGRATULATIONS ON R2!** Please misuse this enormous amount of prestige responsibly. 🫡"
        ),
        3: (
            f"🛡️ {who} has been promoted **R{old_rank} → R3**.\n\n"
            "Apparently showing up, contributing and causing the correct amount of chaos has consequences. HR has stamped the paperwork.\n\n"
            "**WELCOME TO R3!** You are now officially one of the functioning adults. Allegedly. 🔥"
        ),
        4: (
            f"🚨⚔️ {who} has been promoted **R{old_rank} → R4**.\n\n"
            "**MANAGEMENT HAS MADE A TERRIBLE DECISION.** Responsibilities have been issued. Authority has been unlocked. Free time has been revoked.\n\n"
            "Congratulations and welcome to OOPZ management. There is no salary and the complaint box is on fire. 👑"
        ),
        5: (
            f"👑🚨 {who} has ascended **R{old_rank} → R5**.\n\n"
            "This is no longer a promotion. This is a constitutional crisis. HR has evacuated the building and somebody has handed you the crown.\n\n"
            "**ALL HAIL THE NEW R5.** May your reign be glorious, chaotic and only moderately concerning to the server. 👑🔥"
        ),
    }
    return messages.get(new_rank, f"⚔️ {who} has been promoted **R{old_rank} → R{new_rank}**. HR approves this suspicious display of competence. Congratulations! 🔥")


def power_milestone_celebration(who: str, milestone: int, new_power: int) -> str:
    messages = {
        20: f"💥 {who} just broke **20M POWER** and is now sitting at **{fmt_power(new_power)}**.\n\nThe account has developed muscles. HR recommends continued exposure to violence. **Welcome to 20M!** 🔥",
        40: f"🚀 {who} just smashed through **40M POWER** and reached **{fmt_power(new_power)}**.\n\nThis is becoming less of a base and more of a public safety concern. **CONGRATULATIONS ON 40M!** 💥",
        60: f"⚠️💥 {who} has crossed **60M POWER** and now stands at **{fmt_power(new_power)}**.\n\nOOPZ HR has upgraded your file from ‘concerning’ to **‘please point this at the enemy.’** Congratulations! 🔥",
        80: f"🚨🔥 {who} HAS BROKEN **80M POWER** and reached **{fmt_power(new_power)}**.\n\nAt this stage we are no longer tracking growth. We are documenting an arms race. The server has been advised to remain calm. **80M. ABSOLUTE MENACE.** 👑",
        100: f"💯👑🚨 {who} HAS ENTERED THE **100 MILLION POWER CLUB** at **{fmt_power(new_power)}**.\n\nNine digits. NINE. HR attempted to calculate the resources involved and Excel simply closed itself.\n\n**100M POWER ACHIEVED.** This account is now legally classified as heavy machinery. OOPZ salutes you. 🔥💥👑",
    }
    return messages.get(milestone, f"💥📈 {who} smashed through **{milestone}M POWER** and is now sitting at **{fmt_power(new_power)}**. The spreadsheet is impressed. HR is frightened. Congratulations! 🔥")


def prestige_celebration(who: str, old_pos: int, new_pos: int) -> str:
    if new_pos <= 10 and old_pos > 10:
        return (
            f"🚨👑 **SERVER MENACE DETECTED.** {who} just broke into the **OOPZ TOP 10 POWER** at **#{new_pos}**.\n\n"
            "The leaderboard has been disturbed. The peasants are whispering. HR would like to know who authorized this level of violence.\n\n"
            "**WELCOME TO THE TOP 10.** Please enjoy the view while everyone below you plots accordingly. 🔥💥"
        )
    return (
        f"⚡📈 {who} has crashed into the **OOPZ TOP 25 POWER** at **#{new_pos}**.\n\n"
        "The leaderboard has received a formal notice of disturbance. HR confirms this was not an administrative error.\n\n"
        "**WELCOME TO THE TOP 25!** Keep climbing. The Top 10 is beginning to look nervous. 👀🔥"
    )


async def send_achievements(diff: RosterDiff, old_roster: dict[str, dict], new_roster: dict[str, dict]):
    """Public, positive-only OOPZ celebrations. Never announces rank drops or other negative changes."""
    channel = await get_channel(ACHIEVEMENTS_CHANNEL_ID)
    if not channel:
        await log_action("🚨 **Achievement delivery failed** — HR detected roster changes but cannot resolve the configured achievements channel.")
        return

    guild = bot.get_guild(GUILD_ID)
    member_by_name = {}
    if guild:
        stored = await db_fetchall("SELECT discord_id, last_verified_name FROM members WHERE ever_verified = 1")
        for row in stored:
            m = guild.get_member(row["discord_id"])
            if m and row["last_verified_name"]:
                member_by_name[row["last_verified_name"]] = m
    old_pos = power_positions(old_roster)
    new_pos = power_positions(new_roster)

    def who(name: str) -> str:
        member = member_by_name.get(name)
        return member.mention if member else f"**{name}**"

    hq_lines = []
    for name, old, new in diff.hq_changes:
        if new > old:
            _, body = hq_upgrade_celebration(who(name), old, new)
            hq_lines.append(body)

    promo_lines = []
    for name, old, new in diff.rank_changes:
        if new > old:
            promo_lines.append(rank_promotion_celebration(who(name), old, new))

    milestone_lines = []
    for name, info in new_roster.items():
        if name not in old_roster:
            continue
        old_power = old_roster[name].get("power")
        new_power = info.get("power")
        if old_power is None or new_power is None or new_power <= old_power:
            continue
        crossed = [m for m in POWER_TIER_MILLIONS if old_power < m * 1_000_000 <= new_power]
        # If one upload crosses several configured thresholds, celebrate only the highest one.
        if crossed:
            milestone = max(crossed)
            milestone_lines.append(power_milestone_celebration(who(name), milestone, new_power))

    prestige_lines = []
    for name, pos in new_pos.items():
        old = old_pos.get(name)
        if old is None:
            continue
        if pos <= 10 and old > 10:
            prestige_lines.append(prestige_celebration(who(name), old, pos))
        elif pos <= 25 and old > 25:
            prestige_lines.append(prestige_celebration(who(name), old, pos))

    sections = [
        ("🏰 HQ UPGRADE CHAOS", hq_lines),
        ("⚔️ HR PROMOTION DEPARTMENT", promo_lines),
        ("💥 POWER LEVEL: QUESTIONABLE", milestone_lines),
        ("🔥 LEADERBOARD DISTURBANCE", prestige_lines),
    ]
    for title, lines in sections:
        if not lines:
            continue
        embed = discord.Embed(title=title, description="\n\n".join(lines), timestamp=now_utc())
        embed.set_footer(text="OOPZ Achievements Department • HR was not consulted")
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            log.exception("Could not send OOPZ achievement celebration: missing channel permission")
            await log_action("🚨 **Achievement delivery failed** — HR found the achievements channel but cannot post there. Check View Channel / Send Messages / Embed Links.")
        except discord.HTTPException:
            log.exception("Could not send OOPZ achievement celebration")
            await log_action("🚨 **Achievement delivery failed** — Discord rejected a celebration post. Check the bot console for details.")


async def send_change_report(diff: RosterDiff, roster: dict[str, dict]):
    channel = await get_channel(SUMMARY_CHANNEL_ID) or await get_channel(ROSTER_CHANNEL_ID)
    if not channel:
        return
    embed = discord.Embed(title="📈 OOPZ Daily Roster Report — HR Has Numbers", timestamp=now_utc())
    if diff.joins:
        embed.add_field(name=f"🟢 Joined OOPZ ({len(diff.joins)})", value=clipped_lines([f"• {n}" for n in diff.joins]), inline=False)
    if diff.departures:
        embed.add_field(name=f"🔴 Left OOPZ ({len(diff.departures)})", value=clipped_lines([f"• {n}" for n in diff.departures]), inline=False)
    if diff.renames:
        embed.add_field(name="✏️ Renames", value=clipped_lines([f"• {a} → **{b}**" for a, b in diff.renames]), inline=False)
    if diff.rank_changes:
        embed.add_field(name="⚔️ Rank changes", value=clipped_lines([f"• **{n}**: R{a} → R{b}" for n, a, b in diff.rank_changes]), inline=False)
    if diff.hq_changes:
        embed.add_field(name="🏰 HQ changes", value=clipped_lines([f"• **{n}**: HQ{a} → HQ{b}" for n, a, b in diff.hq_changes]), inline=False)

    positive = [(n, g) for n, g in diff.power_gains if g > 0][:10]
    if positive:
        embed.add_field(name="🚀 Top power gains", value=clipped_lines([f"• **{n}** +{fmt_power(g)}" for n, g in positive]), inline=False)

    top = sorted(roster.items(), key=lambda x: x[1].get("power") or -1, reverse=True)[:10]
    if top:
        embed.add_field(name="🔥 Current Top 10 Power", value=clipped_lines([f"**{i}.** {n} — {fmt_power(info.get('power'))}" for i, (n, info) in enumerate(top, 1)]), inline=False)

    if len(embed.fields) == 1 and not diff.joins and not diff.departures and not diff.renames and not diff.rank_changes and not diff.hq_changes and not positive:
        embed.description = "Nothing dramatic happened since the last upload. Suspiciously peaceful. HR will continue monitoring. 👀"
    embed.set_footer(text="OOPZ HR Department • Powered by spreadsheets and poor decisions")
    await channel.send(embed=embed)


@bot.event
async def on_ready():
    await init_db()
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        log.error("Configured GUILD_ID is not available to the bot")
        return
    try:
        bot.tree.copy_global_to(guild=discord.Object(id=GUILD_ID))
        await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
    except discord.HTTPException:
        log.exception("Slash command sync failed")
    if not grace_period_check.is_running():
        grace_period_check.change_interval(minutes=GRACE_CHECK_MINUTES)
        grace_period_check.start()
    log.info("Logged in as %s (%s)", bot.user, bot.user.id if bot.user else "?")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or message.guild is None:
        return
    if message.guild.id != GUILD_ID or message.channel.id != ROSTER_CHANNEL_ID:
        return
    csv_attachments = [a for a in message.attachments if a.filename.lower().endswith(".csv")]
    if not csv_attachments:
        return
    attachment = csv_attachments[-1]
    try:
        data = await attachment.read()
        roster, column = parse_roster_csv(data)
    except Exception as exc:
        await message.reply(f"❌ **HR rejected this spreadsheet.** Nothing was changed.\nReason: `{exc}`")
        await log_action(f"❌ **Roster import rejected** — `{attachment.filename}` — {exc}")
        return

    old_roster = await get_roster()
    diff = diff_rosters(old_roster, roster) if old_roster else None
    await replace_roster(roster)
    stats = await sync_guild(message.guild, roster)
    await send_sync_summary(message.channel, stats, attachment.filename, column)
    if diff:
        await send_change_report(diff, roster)
        await send_achievements(diff, old_roster, roster)


@bot.event
async def on_member_join(member: discord.Member):
    if member.guild.id != GUILD_ID or await is_exempt(member):
        return
    roster = await get_roster()
    if not roster:
        await send_welcome(member, verified=False)
        return
    identity = await resolve_roster_identity(member, roster)
    if identity:
        name, info = identity
        pos = power_positions(roster).get(name)
        await mark_verified(member, info, name)
        await sync_member_roles(member, info, pos)
        await sync_member_nickname(member, name, info, pos)
        await log_action(f"✅ **Joined + verified** — {member.mention} matches `{name}`.")
        await send_welcome(member, verified=True, info=info)
    else:
        await start_warning(member)
        await send_welcome(member, verified=False)


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    if after.guild.id != GUILD_ID or before.display_name == after.display_name or await is_exempt(after):
        return
    roster = await get_roster()
    if not roster:
        return
    row = await db_fetchone("SELECT * FROM members WHERE discord_id = ?", (after.id,))
    identity = await resolve_roster_identity(after, roster, row)
    if identity:
        game_name, info = identity
        pos = power_positions(roster).get(game_name)
        cleared = await mark_verified(after, info, game_name)
        await sync_member_roles(after, info, pos)
        await sync_member_nickname(after, game_name, info, pos)
        if cleared:
            await log_action(f"✅ **Match restored** — {after.mention} verified as `{game_name}`; warning cleared.")
        return

    expected_name = await find_expected_name(row, roster)
    await start_warning(after, expected_name=expected_name)


@tasks.loop(minutes=10)
async def grace_period_check():
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    roster = await get_roster()
    if not roster:
        return
    positions = power_positions(roster)
    rows = await db_fetchall("SELECT discord_id, warning_started_at FROM members WHERE warning_started_at IS NOT NULL")
    cutoff = now_utc() - timedelta(hours=GRACE_HOURS)

    for row in rows:
        started = parse_iso(row["warning_started_at"])
        if not started or started > cutoff:
            continue
        member = guild.get_member(row["discord_id"])
        if member is None:
            try:
                member = await guild.fetch_member(row["discord_id"])
            except discord.NotFound:
                await db_execute("UPDATE members SET warning_started_at = NULL, updated_at = ? WHERE discord_id = ?", (iso(), row["discord_id"]))
                continue
            except discord.HTTPException:
                continue
        if is_owner(member):
            await db_execute("UPDATE members SET warning_started_at = NULL, updated_at = ? WHERE discord_id = ?", (iso(), member.id))
            continue
        if await is_exempt(member):
            continue
        member_row = await db_fetchone("SELECT * FROM members WHERE discord_id = ?", (member.id,))
        identity = await resolve_roster_identity(member, roster, member_row)
        if identity:
            game_name, info = identity
            await mark_verified(member, info, game_name)
            await sync_member_roles(member, info, positions.get(game_name))
            await sync_member_nickname(member, game_name, info, positions.get(game_name))
            await log_action(f"✅ **Match restored** — {member.mention} verified as `{game_name}` before grace expiry.")
            continue
        await kick_member(member, f"Nickname did not match OOPZ roster after {GRACE_HOURS}h grace period")
        await db_execute("UPDATE members SET warning_started_at = NULL, updated_at = ? WHERE discord_id = ?", (iso(), member.id))


@grace_period_check.before_loop
async def before_grace_period_check():
    await bot.wait_until_ready()


def admin_only(interaction: discord.Interaction) -> bool:
    return bool(interaction.user.guild_permissions.manage_guild)



async def analyze_special_forces_screenshots(screenshots: list[discord.Attachment]) -> dict:
    """Read overlapping Special Forces screenshots with Gemini and return merged progress JSON."""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    parts = []
    for index, screenshot in enumerate(screenshots, start=1):
        image_bytes = await screenshot.read()
        mime_type = (screenshot.content_type or "image/png").split(";", 1)[0]
        if mime_type == "image/jpg":
            mime_type = "image/jpeg"
        parts.append(types.Part.from_text(text=f"Screenshot {index} of {len(screenshots)}. Screenshots are ordered top-to-bottom and may overlap."))
        parts.append(types.Part.from_bytes(data=image_bytes, mime_type=mime_type))

    tree_legend = "\n".join(
        f"Row {index}: " + " | ".join(names)
        for index, names in enumerate(T10_TREE_ROWS, start=1)
    )
    prompt = f"""You are reading screenshots of the Special Forces technology tree from Last War: Survival.
Treat all supplied screenshots as overlapping sections of ONE continuous tree, ordered top to bottom.
Your job is precise visual transcription. Read every visible node progress label such as MAX, 8/10, 5/10, 1/10 or 0/1 and reconcile duplicates in overlaps.

The OOPZ-verified tree layout, top to bottom, is:
{tree_legend}

Use this fixed layout to assign row, column and node name. For three-node rows use left, center, right. For one-node rows use center. For two-node rows use left, right.
Return JSON only: {{"nodes":[{{"order":1,"row":1,"column":"left|center|right|other","name":"HP Boost I","progress_text":"8/10","current_level":8,"max_level":10,"seen_in_screens":[1],"confidence":0.95}}],"notes":[]}}
For MAX, use current_level=10 and max_level=10 unless the screenshot clearly shows another maximum. Unit X is 0/1 or 1/1.
If a value is unreadable, omit that node rather than guessing. Do not fabricate a level."""
    parts.insert(0, types.Part.from_text(text=prompt))

    def run_gemini():
        client = genai.Client(api_key=GEMINI_API_KEY)
        config = types.GenerateContentConfig(response_mime_type="application/json", temperature=0)
        try:
            response = client.models.generate_content(
                model=GEMINI_VISION_MODEL,
                contents=parts,
                config=config,
            )
        except Exception as exc:
            error_text = str(exc)
            if ("503" not in error_text and "UNAVAILABLE" not in error_text):
                raise
            # A 503 means temporary capacity pressure. Use Google's documented
            # free-tier Flash-Lite model for this simple screenshot transcription.
            if GEMINI_FALLBACK_MODEL:
                logging.warning("Gemini primary overloaded; trying fallback model %s", GEMINI_FALLBACK_MODEL)
                response = client.models.generate_content(
                    model=GEMINI_FALLBACK_MODEL,
                    contents=parts,
                    config=config,
                )
            else:
                raise
        return json.loads(response.text)

    return await asyncio.to_thread(run_gemini)


def summarize_special_forces_scan(scan: dict) -> tuple[str, str]:
    nodes = scan.get("nodes") or []
    if not nodes:
        return "I couldn't confidently read any research levels from these screenshots.", "Progress unavailable"
    lines, earned, possible, complete_nodes = [], 0, 0, 0
    for node in nodes[:30]:
        row = node.get("row", "?")
        column = str(node.get("column", "other")).title()
        progress = str(node.get("progress_text", "?"))
        current, maximum = node.get("current_level"), node.get("max_level")
        if isinstance(current, int) and isinstance(maximum, int) and maximum > 0:
            earned += max(0, min(current, maximum))
            possible += maximum
            if current >= maximum:
                complete_nodes += 1
        confidence = node.get("confidence")
        suffix = " ⚠️" if isinstance(confidence, (int, float)) and confidence < 0.8 else ""
        mapped_name = tree_name_for_position(int(row), str(node.get("column", "other"))) if str(row).isdigit() else ""
        detected_name = str(node.get("name") or "").strip()
        node_name = mapped_name or detected_name or f"Row {row} {column}"
        lines.append(f"• **{node_name}** — {progress}{suffix}")
    if len(nodes) > 30:
        lines.append(f"• …and {len(nodes) - 30} more nodes")
    percent = round((earned / possible) * 100, 1) if possible else 0
    summary = (
        f"**Visible tree progress:** {percent}%\n"
        f"**Research levels complete:** {earned}/{possible}\n"
        f"**Levels remaining:** {max(0, possible - earned)}\n"
        f"**Fully completed nodes:** {complete_nodes}/{len(nodes)}"
    )
    return "\n".join(lines), summary


@bot.tree.command(name="t10", description="Get your personal OOPZ T10 / Special Forces roadmap")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def t10(
    interaction: discord.Interaction,
    screenshot_1: discord.Attachment | None = None,
    screenshot_2: discord.Attachment | None = None,
    screenshot_3: discord.Attachment | None = None,
    screenshot_4: discord.Attachment | None = None,
):
    """Give a T10 roadmap and accept up to four overlapping Special Forces screenshots."""
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("🚫 This command only works inside the OOPZ server.", ephemeral=True)
        return

    roster = await get_roster()
    if not roster:
        await interaction.response.send_message("📭 I don't have an OOPZ roster loaded yet. Ask leadership to upload the latest LWMA CSV.", ephemeral=True)
        return

    row = await db_fetchone("SELECT * FROM members WHERE discord_id = ?", (interaction.user.id,))
    identity = await resolve_roster_identity(interaction.user, roster, row)
    if not identity:
        await interaction.response.send_message(
            "🕵️ I can't connect your Discord account to the current OOPZ roster yet. "
            "Ask Queen/R4 to use `/link_member` for you, then try `/t10` again.",
            ephemeral=True,
        )
        return

    game_name, info = identity
    hq = info.get("level")
    if hq is None:
        await interaction.response.send_message(
            f"🧮 I found you as **{game_name}**, but your HQ level is missing from the current roster.",
            ephemeral=True,
        )
        return

    research_lines = [
        f"• **{item['name']}** — {item['gold_total'] / 1_000_000_000:.2f}B Gold • {item['valor_total']:,} Valor"
        for item in T10_RESEARCH.values()
    ]

    if hq < 27:
        milestone = "**First milestone:** HQ27 → unlock T9. Keep building your Gold and Valor stockpile while you push HQ."
    elif hq < 30:
        milestone = (
            f"**Current milestone:** HQ{hq} → HQ30. Keep advancing Special Forces now; "
            "the final two research rows (levels 9–10) require **HQ30 + Tech Center 30**."
        )
    else:
        milestone = (
            "**HQ30 reached.** Finish **Tech Center 30** for the final research rows. "
            "**Unit X / T10 also requires Barracks 30**."
        )

    embed = discord.Embed(
        title="🔥 OOPZ T10 Coach",
        description=f"**{game_name} • HQ{hq}**\n\n{get_hq_advice(hq)}",
        timestamp=now_utc(),
    )
    embed.add_field(name="🎯 Your next milestone", value=milestone, inline=False)
    embed.add_field(name="🧪 Full T10 research path", value="\n".join(research_lines), inline=False)
    embed.add_field(
        name="💰 Full path cost",
        value=f"**Gold:** {T10_TOTAL_GOLD / 1_000_000_000:.2f}B\n**Valor Badges:** {T10_TOTAL_VALOR:,}",
        inline=False,
    )
    embed.add_field(
        name="🔒 Final requirements",
        value=(
            f"Research levels 9–10: **HQ{T10_REQUIREMENTS['final_nodes']['hq']} + "
            f"Tech Center {T10_REQUIREMENTS['final_nodes']['tech_center']}**\n"
            f"Unit X research: **Tech Center {T10_REQUIREMENTS['unit_x_research']['tech_center']} + "
            f"HP Boost III {T10_REQUIREMENTS['unit_x_research']['hp_boost_iii']}**\n"
            f"Training T10 after unlock: **Barracks {T10_REQUIREMENTS['t10_training']['barracks']}**"
        ),
        inline=False,
    )
    screenshots = [s for s in (screenshot_1, screenshot_2, screenshot_3, screenshot_4) if s is not None]
    if screenshots:
        image_extensions = (".png", ".jpg", ".jpeg", ".webp", ".gif")
        for screenshot in screenshots:
            content_type = (screenshot.content_type or "").lower()
            filename = screenshot.filename.lower()
            if not (content_type.startswith("image/") or filename.endswith(image_extensions)):
                await interaction.response.send_message(
                    f"📸 **{screenshot.filename}** is not an image. Please use PNG, JPG, JPEG, WEBP or GIF.",
                    ephemeral=True,
                )
                return

        filenames = "\n".join(f"• {s.filename}" for s in screenshots)
        embed.add_field(
            name=f"📸 {len(screenshots)} Special Forces screenshot{'s' if len(screenshots) != 1 else ''} received",
            value=(
                f"{filenames}\n\n"
                "I will treat these as **overlapping sections of one continuous Special Forces tree**. "
                "The upload pipeline is ready for the image-analysis step."
            ),
            inline=False,
        )
        # Discord embeds can preview one image; Gemini receives every supplied image.
        embed.set_image(url=screenshots[0].url)

        if not GEMINI_API_KEY:
            embed.add_field(
                name="🧠 Screenshot reader not connected yet",
                value="Add **GEMINI_API_KEY** to Railway Variables, then run `/t10` again.",
                inline=False,
            )
        else:
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                scan = await analyze_special_forces_screenshots(screenshots)
                scan_text, progress_summary = summarize_special_forces_scan(scan)
                if len(scan_text) > 1024:
                    scan_text = scan_text[:1018] + "…"
                embed.add_field(name="📊 Your scanned progress", value=progress_summary, inline=False)
                embed.add_field(name="🧠 Detected research levels", value=scan_text, inline=False)
                embed.add_field(
                    name="🗺️ Tree mapping",
                    value="All 23 Special Forces nodes are mapped. HR matches the scanned row/position to the verified research name and will not invent unreadable levels.",
                    inline=False,
                )
                notes = scan.get("notes") or []
                if notes:
                    note_text = "\n".join(f"• {n}" for n in notes[:4])
                    embed.add_field(name="🔎 Scan notes", value=note_text[:1024], inline=False)
            except Exception as exc:
                logging.exception("Gemini Special Forces screenshot analysis failed")
                error_text = str(exc).replace(GEMINI_API_KEY, "[redacted]") if GEMINI_API_KEY else str(exc)
                embed.add_field(
                    name="⚠️ Screenshot analysis failed",
                    value=(
                        "I received the screenshots, but the vision scan failed.\n"
                        f"**Diagnostic:** `{error_text[:700]}`"
                    ),
                    inline=False,
                )
            embed.set_footer(text="OOPZ Growth Department • based on your latest roster HQ")
            await interaction.edit_original_response(embed=embed)
            return
    else:
        embed.add_field(
            name="📸 Want a more exact plan?",
            value=(
                "Run **/t10** again and attach your Special Forces tree using "
                "**screenshot_1** through **screenshot_4**. Use overlapping screenshots "
                "from top to bottom so I can reconstruct the full tree."
            ),
            inline=False,
        )

    embed.set_footer(text="OOPZ Growth Department • based on your latest roster HQ")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="roster_status", description="Show current OOPZ roster bot status")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def roster_status(interaction: discord.Interaction):
    if not admin_only(interaction):
        await interaction.response.send_message("🚫 HR says no. You need **Manage Server** permission for that command.", ephemeral=True)
        return
    roster_count = (await db_fetchone("SELECT COUNT(*) AS c FROM roster"))["c"]
    warning_count = (await db_fetchone("SELECT COUNT(*) AS c FROM members WHERE warning_started_at IS NOT NULL"))["c"]
    verified_count = (await db_fetchone("SELECT COUNT(*) AS c FROM members WHERE ever_verified = 1"))["c"]
    last_import = await db_fetchone("SELECT value FROM meta WHERE key='last_import_at'")
    imported = last_import["value"] if last_import else "Never"
    await interaction.response.send_message(
        f"**Roster players:** {roster_count}\n**Ever-verified Discord users:** {verified_count}\n"
        f"**Active identity checks:** {warning_count}\n**Last CSV import:** {imported}", ephemeral=True)


@bot.tree.command(name="member_status", description="Show one member's OOPZ verification state")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def member_status(interaction: discord.Interaction, member: discord.Member):
    if not admin_only(interaction):
        await interaction.response.send_message("🚫 HR says no. You need **Manage Server** permission for that command.", ephemeral=True)
        return
    row = await db_fetchone("SELECT * FROM members WHERE discord_id = ?", (member.id,))
    roster = await get_roster()
    identity = await resolve_roster_identity(member, roster, row) if row else None
    if not row:
        text = "No stored verification history."
    else:
        text = (
            f"**Current display name:** `{member_name(member)}`\n"
            f"**Currently resolves to roster:** {'Yes' if identity else 'No'}\n"
            f"**Ever verified:** {'Yes' if row['ever_verified'] else 'No'}\n"
            f"**Last verified game name:** `{row['last_verified_name'] or 'None'}`\n"
            f"**Last verified UID:** `{row['last_verified_uid'] or 'None'}`\n"
            f"**Identity check started:** `{row['warning_started_at'] or 'None'}`\n"
            f"**Manual whitelist:** {'Yes' if row['manually_exempt'] else 'No'}"
        )
    await interaction.response.send_message(text, ephemeral=True)


@bot.tree.command(name="whitelist", description="Exempt a Discord member from automatic roster enforcement")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def whitelist(interaction: discord.Interaction, member: discord.Member):
    if not admin_only(interaction):
        await interaction.response.send_message("🚫 HR says no. You need **Manage Server** permission for that command.", ephemeral=True)
        return
    await upsert_member(member)
    await db_execute("UPDATE members SET manually_exempt = 1, warning_started_at = NULL, updated_at = ? WHERE discord_id = ?", (iso(), member.id))
    await interaction.response.send_message(f"🛡️ {member.mention} is now exempt from roster enforcement. HR will pretend they don't exist.", ephemeral=True)
    await log_action(f"🛡️ **Whitelisted** — {member.mention} by {interaction.user.mention}")


@bot.tree.command(name="unwhitelist", description="Remove a member's manual roster exemption")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def unwhitelist(interaction: discord.Interaction, member: discord.Member):
    if not admin_only(interaction):
        await interaction.response.send_message("🚫 HR says no. You need **Manage Server** permission for that command.", ephemeral=True)
        return
    await upsert_member(member)
    await db_execute("UPDATE members SET manually_exempt = 0, updated_at = ? WHERE discord_id = ?", (iso(), member.id))
    await interaction.response.send_message(f"🔓 Exemption removed for {member.mention}. HR can see them again. Unfortunate for them.", ephemeral=True)
    await log_action(f"🔓 **Whitelist removed** — {member.mention} by {interaction.user.mention}")


@bot.tree.command(name="clear_warnings", description="Clear all active nickname grace warnings (leadership safety tool)")
@app_commands.checks.has_permissions(manage_guild=True)
async def clear_warnings(interaction: discord.Interaction):
    await db_execute("UPDATE members SET warning_started_at = NULL, updated_at = ? WHERE warning_started_at IS NOT NULL", (iso(),))
    await interaction.response.send_message("✅ All active identity-check timers were cleared. Nobody will be removed because of an old warning. HR has shredded the paperwork.", ephemeral=True)


@bot.tree.command(name="force_sync", description="Re-run enforcement and all managed roles against the stored roster")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def force_sync(interaction: discord.Interaction):
    if not admin_only(interaction):
        await interaction.response.send_message("🚫 HR says no. You need **Manage Server** permission for that command.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    roster = await get_roster()
    if not roster:
        await interaction.followup.send("📭 HR has no roster yet. Upload the latest LWMA CSV first.", ephemeral=True)
        return
    if not interaction.guild:
        return
    stats = await sync_guild(interaction.guild, roster)
    await interaction.followup.send(
        f"✅ **HR sync complete.** {stats.matched} matched • {stats.warnings_started} new identity checks • "
        f"{stats.warnings_cleared} resolved • {stats.kicked_left} departures removed • {stats.roles_updated} role updates • {stats.nicknames_updated} nickname updates. "
        "The spreadsheet has spoken.",
        ephemeral=True,
    )


@bot.tree.command(name="migration_report", description="Audit old Verified members against the current LWMA roster")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def migration_report(interaction: discord.Interaction):
    if not admin_only(interaction):
        await interaction.response.send_message("🚫 HR says no. You need **Manage Server** permission for that command.", ephemeral=True)
        return
    if not interaction.guild:
        return
    await interaction.response.defer(ephemeral=True)
    roster = await get_roster()
    if not roster:
        await interaction.followup.send("📭 HR has no roster yet. Upload the latest LWMA CSV first.", ephemeral=True)
        return
    legacy = find_role_by_name(interaction.guild, "Verified")
    if not legacy:
        await interaction.followup.send("I couldn't find the old `Verified` role. Either migration is already clean, or someone moved the furniture again.", ephemeral=True)
        return
    matched, unmatched, exempt = [], [], []
    for member in legacy.members:
        if await is_exempt(member):
            exempt.append(member)
            continue
        identity = await resolve_roster_identity(member, roster)
        if identity:
            matched.append((member, identity[0]))
        else:
            unmatched.append((member, best_roster_candidates(member_name(member), roster)))
    lines = [
        "OOPZ LEGACY VERIFIED MIGRATION AUDIT",
        f"Old Verified role: {len(legacy.members)} members",
        f"Matched current LWMA: {len(matched)}",
        f"Unmatched: {len(unmatched)}",
        f"Exempt: {len(exempt)}",
        "",
        "UNMATCHED LEGACY VERIFIED MEMBERS",
    ]
    for member, candidates in unmatched:
        cand = "; ".join(f"{name} (distance {dist})" for dist, name in candidates) or "none"
        lines.append(f"- {member.display_name} | Discord ID {member.id} | closest: {cand}")
    if exempt:
        lines += ["", "EXEMPT LEGACY VERIFIED MEMBERS"]
        lines += [f"- {m.display_name} | Discord ID {m.id}" for m in exempt]
    payload = "\n".join(lines).encode("utf-8")
    await interaction.followup.send(
        f"🧾 **Migration audit complete:** **{len(matched)} matched**, **{len(unmatched)} unresolved**, **{len(exempt)} exempt** out of **{len(legacy.members)}** old Verified members.\nThe unresolved list is attached. HR brought receipts.",
        file=discord.File(io.BytesIO(payload), filename="oopz-migration-report.txt"),
        ephemeral=True,
    )


@bot.tree.command(name="link_member", description="Manually link one Discord member to a current LWMA player")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def link_member(interaction: discord.Interaction, member: discord.Member, player_name: str):
    if not admin_only(interaction):
        await interaction.response.send_message("🚫 HR says no. You need **Manage Server** permission for that command.", ephemeral=True)
        return
    roster = await get_roster()
    if not roster:
        await interaction.response.send_message("📭 HR has no roster yet. Upload the latest LWMA CSV first.", ephemeral=True)
        return
    # Manual linking must still resolve to exactly one current roster player.
    exact = roster.get(player_name)
    resolved_name = player_name if exact else relaxed_roster_name_match(player_name, roster)
    if not resolved_name or resolved_name not in roster:
        await interaction.response.send_message(f"🕵️ HR couldn't uniquely identify `{player_name}` in the current LWMA roster. Try the current in-game name more exactly.", ephemeral=True)
        return
    info = roster[resolved_name]
    # Prevent accidentally linking the same stable LWMA UID to two Discord accounts.
    uid = info.get("uid")
    if uid:
        existing = await db_fetchone("SELECT discord_id FROM members WHERE last_verified_uid = ? AND discord_id != ?", (uid, member.id))
        if existing:
            other = interaction.guild.get_member(int(existing["discord_id"])) if interaction.guild else None
            label = other.mention if other else str(existing["discord_id"] )
            await interaction.response.send_message(f"🚫 That LWMA account is already linked to {label}. HR refuses to create an identity crisis.", ephemeral=True)
            return
    await mark_verified(member, info, resolved_name)
    positions = power_positions(roster)
    await sync_member_roles(member, info, positions.get(resolved_name))
    await sync_member_nickname(member, resolved_name, info, positions.get(resolved_name))
    await interaction.response.send_message(f"✅ Case closed: {member.mention} is linked to `{resolved_name}`. Any warning was cleared and HR synced the managed roles/nickname it is allowed to touch.", ephemeral=True)
    await log_action(f"🔗 **Manual identity link** — {member.mention} → `{resolved_name}` by {interaction.user.mention}")


@bot.tree.command(name="celebrate_hq", description="Manually celebrate a missed HQ upgrade in the achievements channel")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def celebrate_hq(interaction: discord.Interaction, member: discord.Member, old_hq: int, new_hq: int):
    if not admin_only(interaction):
        await interaction.response.send_message("🚫 HR says no. You need **Manage Server** permission for that command.", ephemeral=True)
        return
    if new_hq <= old_hq:
        await interaction.response.send_message("🧮 HR checked the paperwork. `new_hq` must be higher than `old_hq` or this is not an upgrade.", ephemeral=True)
        return
    if old_hq < 1 or new_hq > 99:
        await interaction.response.send_message("🧮 Those HQ numbers look suspicious. Please use sensible HQ levels.", ephemeral=True)
        return

    channel = await get_channel(ACHIEVEMENTS_CHANNEL_ID)
    if not channel:
        await interaction.response.send_message(
            "🚫 HR cannot find the configured achievements channel. Check `ACHIEVEMENTS_CHANNEL_ID` in `.env`.",
            ephemeral=True,
        )
        await log_action("🚨 **Achievement replay failed** — configured achievements channel could not be resolved.")
        return

    title, body = hq_upgrade_celebration(member.mention, old_hq, new_hq)

    embed = discord.Embed(title=title, description=body, timestamp=now_utc())
    embed.set_footer(text="OOPZ Achievements Department • HR was not consulted")
    try:
        await channel.send(embed=embed)
    except discord.Forbidden:
        await interaction.response.send_message(
            "🚫 HR found the achievements channel but cannot post there. Give the bot **View Channel, Send Messages and Embed Links**.",
            ephemeral=True,
        )
        await log_action(f"🚨 **Achievement replay failed** — missing channel permissions while celebrating {member.mention} HQ{old_hq} → HQ{new_hq}.")
        return
    except discord.HTTPException as exc:
        await interaction.response.send_message(f"🚫 Discord rejected the achievement post: `{exc}`", ephemeral=True)
        await log_action(f"🚨 **Achievement replay failed** — {member.mention} HQ{old_hq} → HQ{new_hq} — Discord error: {exc}")
        return

    await interaction.response.send_message(
        f"🏰 Celebration posted for {member.mention}: **HQ{old_hq} → HQ{new_hq}**. HR has retroactively approved the parade.",
        ephemeral=True,
    )
    await log_action(f"🏰 **Manual HQ celebration** — {member.mention} HQ{old_hq} → HQ{new_hq} by {interaction.user.mention}")


@bot.tree.command(name="celebrate_rank", description="Manually celebrate an R3 promotion to R4 or R5")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def celebrate_rank(interaction: discord.Interaction, member: discord.Member, new_rank: int):
    if not admin_only(interaction):
        await interaction.response.send_message("🚫 HR says no. You need **Manage Server** permission for that command.", ephemeral=True)
        return
    if new_rank not in (4, 5):
        await interaction.response.send_message(
            "🧮 Manual rank celebrations are reserved for **R3 → R4** or **R3 → R5**. Use `new_rank` 4 or 5.",
            ephemeral=True,
        )
        return

    channel = await get_channel(ACHIEVEMENTS_CHANNEL_ID)
    if not channel:
        await interaction.response.send_message(
            "🚫 HR cannot find the configured achievements channel. Check `ACHIEVEMENTS_CHANNEL_ID` in `.env`.",
            ephemeral=True,
        )
        await log_action("🚨 **Manual rank celebration failed** — configured achievements channel could not be resolved.")
        return

    body = rank_promotion_celebration(member.mention, 3, new_rank)
    title = "🚨⚔️ MANAGEMENT INCIDENT" if new_rank == 4 else "👑🚨 CONSTITUTIONAL CRISIS"
    embed = discord.Embed(title=title, description=body, timestamp=now_utc())
    embed.set_footer(text="OOPZ Achievements Department • HR was not consulted")
    try:
        await channel.send(embed=embed)
    except discord.Forbidden:
        await interaction.response.send_message(
            "🚫 HR found the achievements channel but cannot post there. Give the bot **View Channel, Send Messages and Embed Links**.",
            ephemeral=True,
        )
        await log_action(f"🚨 **Manual rank celebration failed** — missing channel permissions while celebrating {member.mention} R3 → R{new_rank}.")
        return
    except discord.HTTPException as exc:
        await interaction.response.send_message(f"🚫 Discord rejected the achievement post: `{exc}`", ephemeral=True)
        await log_action(f"🚨 **Manual rank celebration failed** — {member.mention} R3 → R{new_rank} — Discord error: {exc}")
        return

    await interaction.response.send_message(
        f"⚔️ Celebration posted for {member.mention}: **R3 → R{new_rank}**. HR has approved the management incident.",
        ephemeral=True,
    )
    await log_action(f"⚔️ **Manual rank celebration** — {member.mention} R3 → R{new_rank} by {interaction.user.mention}")


@bot.tree.command(name="welcome", description="Re-send the OOPZ welcome for a member")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def welcome(interaction: discord.Interaction, member: discord.Member):
    if not admin_only(interaction):
        await interaction.response.send_message("🚫 HR says no. You need **Manage Server** permission for that command.", ephemeral=True)
        return
    roster = await get_roster()
    identity = await resolve_roster_identity(member, roster)
    info = identity[1] if identity else None
    sent = await send_welcome(member, verified=bool(info), info=info)
    if sent:
        await interaction.response.send_message(f"👋 Public welcome posted for {member.mention}. HR has acknowledged their existence.", ephemeral=True)
    else:
        await interaction.response.send_message(
            f"🚫 I could **not** post the public welcome for {member.mention}. Check the configured welcome channel and the bot's **View Channel / Send Messages / Embed Links** permissions.",
            ephemeral=True,
        )


if __name__ == "__main__":
    bot.run(TOKEN)