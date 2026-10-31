"""OOPZ's persistent, server-time event calendar. No network calls at import."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

import aiosqlite
import discord
from discord import app_commands
from discord.ext import tasks

log = logging.getLogger('oopz-scheduler')
# Explicitly supplied by the alliance: midnight server = 03:00 German winter time.
SERVER_TIME = timezone(timedelta(hours=-2), name='Server time (UTC-02:00)')
DAILY_CHANNEL = 1524785999845130321
ANNOUNCEMENTS_CHANNEL = 1524785541059448966
LEADERSHIP_ROLES = {1548703462332694618, 1548703579055857774}
TRIAL_ANCHOR = date(2026, 11, 4)
KINDS = {
    'marshall': 'Marshall Guard', 'zombie': 'Zombie Siege',
    'desert': 'Desert Storm', 'stronghold': 'Stronghold Capture',
    'city': 'City Capture', 'sky': 'Sky Battlefront', 'meteorite': 'Meteorite War',
}
CHOICES = [app_commands.Choice(name=v, value=k) for k, v in KINDS.items()]
SEASON_ONLY = {'stronghold', 'city'}
OUTSIDE_ONLY = {'sky', 'meteorite'}


def parse_date(value: str) -> date:
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('Use a date like 2026-11-23 (YYYY-MM-DD).')
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError('That calendar date does not exist.') from None


def parse_time(value: str) -> time:
    if not re.fullmatch(r'\d{2}:\d{2}', value):
        raise ValueError('Use a server time like 18:30 (HH:MM).')
    try:
        return time.fromisoformat(value)
    except ValueError:
        raise ValueError('Use a valid 24-hour server time.') from None


def season_day(day: date, start: date | None) -> int | None:
    n = (day - start).days + 1 if start else 0
    return n if 1 <= n <= 56 else None


@dataclass(frozen=True)
class Event:
    key: str
    title: str
    day: date
    clock: time | None = None
    level: int | None = None
    server: int | None = None
    request_id: int | None = None

    @property
    def start(self):
        return datetime.combine(self.day, self.clock or time(), SERVER_TIME)

    def line(self):
        details = [self.title]
        if self.level is not None:
            details.append(f'Level {self.level}')
        if self.server is not None:
            details.append(f'Server {self.server}')
        prefix = self.clock.strftime('%H:%M') if self.clock else 'ALL DAY'
        return f'**{prefix}** — ' + ' · '.join(details)


def fixed_events(day: date, start: date | None) -> list[Event]:
    events = []
    n = season_day(day, start)
    if day.weekday() == 5:
        name = 'Infinite Octagon' if n else 'Warzone Duel'
        events.append(Event(f'fixed:duel:{day}', name, day, time(12)))
    if day.weekday() in (2, 3, 4):
        wednesday = day - timedelta(days=day.weekday() - 2)
        trial = ((wednesday - TRIAL_ANCHOR).days // 7) % 2 == 0
        name = "General’s Trial" if trial else 'Gold Zombies'
        events.append(Event(f'fixed:all-day:{day}', name + ' (Wednesday–Friday)', day))
    if n and n >= 8 and day.weekday() in (1, 4):
        events.append(Event(f'fixed:crimson:{day}', 'Crimson Legion Attack', day, time(12)))
    return events


def request_events(row, start: date | None) -> list[Event]:
    day = parse_date(row['event_date'])
    kind = row['kind']
    active = bool(season_day(day, start))
    if (kind in SEASON_ONLY and not active) or (kind in OUTSIDE_ONLY and active):
        return []
    slots = [('A', time(9, 30)), ('B', time(18, 30))] if kind == 'desert' else (
        [('early', time(0, 10)), ('noon', time(12))] if kind == 'meteorite' else
        [('', time(12) if kind == 'sky' else parse_time(row['event_time']))]
    )
    return [Event(f"manual:{row['id']}:{label}", KINDS[kind] + (f' · Team {label}' if kind == 'desert' else ''),
                  day, clock, row['level'], row['server'], row['id']) for label, clock in slots]


def agenda_embed(day: date, events: list[Event], start: date | None):
    n = season_day(day, start)
    label = f'Season 1 · Week {(n - 1) // 7 + 1} · Day {n}' if n else 'Out of season'
    embed = discord.Embed(title='📋 OOPZ DAILY ORDERS', color=0xE6B84B,
                          description=f'**{day:%A, %d %B %Y}**\n{label}\n🕒 All times are server time.')
    for title, subset in [('ALL DAY', [e for e in events if e.clock is None]),
                          ("TODAY’S OPERATIONS", [e for e in events if e.clock is not None])]:
        if subset:
            lines = [e.line() for e in subset]
            chunks, current = [], ''
            for line in lines:
                if len(current) + len(line) + 1 > 1000:
                    chunks.append(current)
                    current = ''
                current += line + '\n'
            chunks.append(current)
            for i, chunk in enumerate(chunks):
                embed.add_field(name=title if i == 0 else title + ' (continued)', value=chunk, inline=False)
    if not events:
        embed.add_field(name='TODAY', value='No events are scheduled yet. Follow R4/R5 for updates.', inline=False)
    if any(e.server for e in events):
        embed.add_field(name='LEADERSHIP ORDERS', value='🚫 Do not jump early. Wait for R4/R5 to give target and movement instructions.', inline=False)
    embed.set_footer(text='Schedule changes after this post appear through /event list. Event starts are posted in #announcements.')
    return embed


def start_embed(event: Event):
    embed = discord.Embed(title=event.title.upper() + ' — STARTING NOW', color=0xE67E22,
                          description=event.line() + '\n🕒 Server time')
    if event.server:
        embed.add_field(name='ORDERS', value='Prepare for the capture and follow R4/R5 instructions.\n🚫 Do not jump until leadership gives the order.', inline=False)
    else:
        embed.add_field(name='ORDERS', value='Join the operation and follow R4/R5 instructions.', inline=False)
    return embed


class Confirm(discord.ui.View):
    def __init__(self, owner: int, action):
        super().__init__(timeout=180)
        self.owner, self.action = owner, action
        self.lock = asyncio.Lock()

    async def interaction_check(self, interaction):
        return interaction.user.id == self.owner and bool({r.id for r in getattr(interaction.user, 'roles', [])} & LEADERSHIP_ROLES)

    @discord.ui.button(label='Confirm and save', style=discord.ButtonStyle.success)
    async def confirm(self, interaction, button):
        async with self.lock:
            if self.is_finished():
                await interaction.response.send_message('This preview has already been used.', ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True)
            try:
                message = await self.action()
            except (ValueError, aiosqlite.IntegrityError) as exc:
                await interaction.edit_original_response(content=f'Could not save: {exc}', embed=None, view=None)
            else:
                await interaction.edit_original_response(content=message, embed=None, view=None)
            self.stop()

    @discord.ui.button(label='Discard', style=discord.ButtonStyle.secondary)
    async def discard(self, interaction, button):
        self.stop()
        await interaction.response.edit_message(content='Discarded. Nothing was changed.', embed=None, view=None)


class Scheduler:
    def __init__(self, bot, database: str, guild_id: int):
        self.bot, self.database, self.guild_id = bot, database, guild_id
        self.lock = asyncio.Lock()

    async def init(self):
        async with aiosqlite.connect(self.database) as db:
            await db.executescript('''
                CREATE TABLE IF NOT EXISTS schedule_settings (key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE IF NOT EXISTS schedule_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
                    event_date TEXT NOT NULL, event_time TEXT, level INTEGER, server INTEGER,
                    active INTEGER NOT NULL DEFAULT 1, created_by TEXT NOT NULL,
                    updated_by TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS schedule_deliveries (
                    key TEXT PRIMARY KEY, status TEXT NOT NULL, claimed_at TEXT NOT NULL,
                    message_id TEXT, error TEXT);
                CREATE TABLE IF NOT EXISTS schedule_audit (
                    id INTEGER PRIMARY KEY, actor TEXT, action TEXT, detail TEXT, at TEXT);
                CREATE TABLE IF NOT EXISTS schedule_plan (
                    id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL, entry_no INTEGER NOT NULL,
                    season_day INTEGER NOT NULL, kind TEXT NOT NULL, level INTEGER NOT NULL,
                    request_id INTEGER, UNIQUE(fingerprint, entry_no));
            ''')

    async def rows(self, sql, values=()):
        async with aiosqlite.connect(self.database) as db:
            db.row_factory = aiosqlite.Row
            return await (await db.execute(sql, values)).fetchall()

    async def season(self):
        rows = await self.rows("SELECT value FROM schedule_settings WHERE key='season_start'")
        return parse_date(rows[0]['value']) if rows and rows[0]['value'] else None

    async def set_season(self, start, actor):
        async with self.lock, aiosqlite.connect(self.database) as db:
            await db.execute("INSERT OR REPLACE INTO schedule_settings VALUES ('season_start', ?)", (str(start) if start else '',))
            await db.execute('INSERT INTO schedule_audit(actor,action,detail,at) VALUES (?,?,?,?)',
                             (str(actor), 'season', str(start), datetime.now(timezone.utc).isoformat()))
            await db.commit()

    async def events(self, day):
        start = await self.season()
        events = fixed_events(day, start)
        for row in await self.rows('SELECT * FROM schedule_requests WHERE active=1 AND event_date=?', (str(day),)):
            events.extend(request_events(row, start))
        return sorted(events, key=lambda e: (e.clock is not None, e.clock or time(), e.title))

    def validate(self, kind, day, clock, level, server, start):
        if kind not in KINDS:
            raise ValueError('Select a known event.')
        if day < datetime.now(SERVER_TIME).date():
            raise ValueError('Choose today or a future date.')
        if kind in SEASON_ONLY and not season_day(day, start):
            raise ValueError('Set the season start first, and choose a date within its 56 days.')
        if kind in OUTSIDE_ONLY and season_day(day, start):
            raise ValueError('That event is out-of-season only.')
        if kind in {'desert', 'sky'} and day.weekday() != 4:
            raise ValueError('This event must be on a Friday.')
        if kind == 'meteorite' and day.weekday() != 5:
            raise ValueError('Meteorite War must be on a Saturday.')
        if kind in {'marshall', 'zombie', 'city', 'stronghold'} and (level is None or not 1 <= level <= 100):
            raise ValueError('Enter a level from 1 to 100.')
        if kind in {'city', 'stronghold'} and (server is None or not 1 <= server <= 99999):
            raise ValueError('Enter the target server number.')
        fixed = kind in {'desert', 'sky', 'meteorite'}
        if fixed and clock:
            raise ValueError('Leave time empty: this event already has preset times.')
        if not fixed and clock is None:
            raise ValueError('Enter a server time in HH:MM.')
        row = dict(id=0, kind=kind, event_date=str(day), event_time=clock.strftime('%H:%M') if clock else None,
                   level=level, server=server)
        slots = request_events(row, start)
        if any(e.start <= datetime.now(SERVER_TIME) for e in slots):
            raise ValueError('Every occurrence must be in the future. Choose a later date/time.')
        return slots

    async def save_request(self, actor, kind, day, clock, level, server, request_id=None):
        start = await self.season()
        self.validate(kind, day, clock, level, server, start)
        clock_text = clock.strftime('%H:%M') if clock else None
        async with self.lock, aiosqlite.connect(self.database) as db:
            duplicate = await (await db.execute('''SELECT id FROM schedule_requests WHERE active=1 AND kind=?
                AND event_date=? AND COALESCE(event_time,'')=COALESCE(?,'')
                AND COALESCE(server,0)=COALESCE(?,0) AND id<>?''',
                (kind, str(day), clock_text, server, request_id or 0))).fetchone()
            if duplicate:
                raise ValueError('That event is already scheduled.')
            stamp = datetime.now(timezone.utc).isoformat()
            if request_id:
                original = await (await db.execute('SELECT * FROM schedule_requests WHERE id=? AND active=1', (request_id,))).fetchone()
                if not original:
                    raise ValueError('Event no longer exists or is cancelled.')
                sent = await (await db.execute("SELECT 1 FROM schedule_deliveries WHERE key LIKE ?", (f'manual:{request_id}:%',))).fetchone()
                if sent:
                    raise ValueError('An occurrence has already started. Cancel it and create a new event instead.')
                await db.execute('UPDATE schedule_requests SET event_date=?,event_time=?,level=?,server=?,updated_by=?,updated_at=? WHERE id=?',
                                 (str(day), clock_text, level, server, str(actor), stamp, request_id))
            else:
                cur = await db.execute('''INSERT INTO schedule_requests
                    (kind,event_date,event_time,level,server,created_by,updated_by,updated_at) VALUES (?,?,?,?,?,?,?,?)''',
                    (kind, str(day), clock_text, level, server, str(actor), str(actor), stamp))
                request_id = cur.lastrowid
            await db.execute('INSERT INTO schedule_audit(actor,action,detail,at) VALUES (?,?,?,?)',
                             (str(actor), 'save event', str(request_id), stamp))
            await db.commit()
        return request_id

    async def cancel(self, request_id, actor):
        async with self.lock, aiosqlite.connect(self.database) as db:
            cur = await db.execute('UPDATE schedule_requests SET active=0,updated_by=? WHERE id=? AND active=1', (str(actor), request_id))
            if not cur.rowcount:
                raise ValueError('No active event has that ID.')
            await db.execute('INSERT INTO schedule_audit(actor,action,detail,at) VALUES (?,?,?,?)',
                             (str(actor), 'cancel event', str(request_id), datetime.now(timezone.utc).isoformat()))
            await db.commit()

    async def deliver(self, key, channel_id, embed, ping=False):
        channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
        if getattr(getattr(channel, 'guild', None), 'id', None) != self.guild_id:
            raise RuntimeError('Schedule destination is not in the configured guild.')
        permissions = channel.permissions_for(channel.guild.me)
        if not permissions.send_messages or not permissions.embed_links or (ping and not permissions.mention_everyone):
            raise RuntimeError('Missing Send Messages / Embed Links / Mention Everyone permissions.')
        # Claim before sending: uncertain sends are never replayed after restart.
        # This favors avoiding duplicate @everyone notifications over late catch-up.
        async with aiosqlite.connect(self.database) as db:
            cur = await db.execute('INSERT OR IGNORE INTO schedule_deliveries(key,status,claimed_at) VALUES (?,?,?)',
                                   (key, 'claimed', datetime.now(timezone.utc).isoformat()))
            await db.commit()
            if not cur.rowcount:
                return
        try:
            message = await channel.send(content='@everyone' if ping else None, embed=embed,
                allowed_mentions=discord.AllowedMentions(everyone=ping, users=False, roles=False, replied_user=False))
        except Exception:
            log.exception('Schedule delivery %s failed; left claimed to prevent a duplicate notification', key)
            return
        async with aiosqlite.connect(self.database) as db:
            await db.execute("UPDATE schedule_deliveries SET status='sent',message_id=? WHERE key=?", (str(message.id), key))
            await db.commit()
        log.info('Schedule delivery sent: %s', key)

    async def tick(self, now=None):
        now = now or datetime.now(SERVER_TIME)
        day = now.date()
        events = await self.events(day)
        start = await self.season()
        if now.time().replace(tzinfo=None) < time(0, 15):
            try:
                await self.deliver(f'agenda:{day}', DAILY_CHANNEL, agenda_embed(day, events, start))
            except Exception:
                log.exception('Cannot deliver daily agenda for %s', day)
        for event in events:
            if event.clock and timedelta(0) <= now - event.start < timedelta(minutes=10):
                try:
                    await self.deliver(event.key, ANNOUNCEMENTS_CHANNEL, start_embed(event), ping=True)
                except Exception:
                    log.exception('Cannot deliver scheduled event %s', event.key)

    @tasks.loop(seconds=20)
    async def worker(self):
        try:
            await self.tick()
        except Exception:
            log.exception('Scheduler tick failed')

    @worker.before_loop
    async def before_worker(self):
        await self.bot.wait_until_ready()

    async def start(self):
        await self.init()
        if not self.worker.is_running():
            self.worker.start()
            log.info('Scheduler active: server UTC-02:00, daily orders 00:00, R4/R5 controls enabled')


def install(bot, database, guild_id):
    scheduler = Scheduler(bot, database, guild_id)
    guild = discord.Object(id=guild_id)
    events = app_commands.Group(name='event', description='OOPZ event schedule — server time')
    seasons = app_commands.Group(name='season', description='Set the eight-week OOPZ season')
    plans = app_commands.Group(name='plan', description='Private LWMA capture planning for R4/R5')

    async def leader(interaction):
        if interaction.guild_id != guild_id or not ({r.id for r in getattr(interaction.user, 'roles', [])} & LEADERSHIP_ROLES):
            await interaction.response.send_message('Only members with the OOPZ R4 or R5 role can do that.', ephemeral=True)
            return False
        return True

    async def error(interaction, exc):
        await interaction.followup.send(str(exc), ephemeral=True)

    @seasons.command(name='start', description='Preview and set Season 1 start date (YYYY-MM-DD); lasts 56 days')
    async def season_start(interaction: discord.Interaction, date: str):
        if not await leader(interaction): return
        try:
            start = parse_date(date)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        async def save():
            await scheduler.set_season(start, interaction.user.id)
            return f'Season 1 saved: {start} through {start + timedelta(days=55)}. Existing individually dated captures are unchanged; review /event list.'
        await interaction.response.send_message(
            f'**Season 1 preview**\nDay 1: {start}\nWeek 2: {start + timedelta(days=7)}\nFinal day: {start + timedelta(days=55)}\n'
            'Crimson Legion: Tuesday/Friday 12:00 from Week 2. Warzone Duel becomes Infinite Octagon.\n'
            'Sky Battlefront/Meteorite War are suppressed during these 56 days. Previously scheduled captures keep their dates; review them after a change.\n'
            'This does not send a public announcement.', ephemeral=True, view=Confirm(interaction.user.id, save))

    @seasons.command(name='status', description='Show season dates, week, day and server time')
    async def season_status(interaction: discord.Interaction):
        if not await leader(interaction): return
        start = await scheduler.season()
        now = datetime.now(SERVER_TIME)
        n = season_day(now.date(), start)
        text = f'Server clock: {now:%Y-%m-%d %H:%M} (UTC−02:00).\n'
        text += f'Season: {start} through {start + timedelta(days=55)}.\n' if start else 'Season start has not been set.\n'
        text += f'Week {(n-1)//7+1}, Day {n}.' if n else 'Currently out of season.'
        await interaction.response.send_message(text, ephemeral=True)

    @seasons.command(name='end', description='Preview returning the calendar to out-of-season mode')
    async def season_end(interaction: discord.Interaction):
        if not await leader(interaction): return
        async def save():
            await scheduler.set_season(None, interaction.user.id)
            return 'Out-of-season mode saved. Capture drafts and existing event records were preserved.'
        await interaction.response.send_message('End season mode? Crimson Legion and captures will be suppressed; out-of-season events become available.',
                                                ephemeral=True, view=Confirm(interaction.user.id, save))

    @events.command(name='add', description='Preview an individual event; preset events fill their own times')
    @app_commands.choices(event=CHOICES)
    async def event_add(interaction: discord.Interaction, event: str, date: str,
                        time: str | None = None, level: app_commands.Range[int, 1, 100] | None = None,
                        server: app_commands.Range[int, 1, 99999] | None = None):
        if not await leader(interaction): return
        try:
            day, clock = parse_date(date), parse_time(time) if time else None
            slots = scheduler.validate(event, day, clock, level, server, await scheduler.season())
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        async def save():
            rid = await scheduler.save_request(interaction.user.id, event, day, clock, level, server)
            return f'Saved event #{rid}. It will appear in daily orders and post with @everyone in #announcements at its start time.'
        await interaction.response.send_message('**Preview — ' + str(day) + '**\n' + '\n'.join(e.line() for e in slots) +
            '\nDaily orders: <#1524785999845130321> · Event starts: <#1524785541059448966> with @everyone.\nNo coordinates will be posted.',
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none(), view=Confirm(interaction.user.id, save))

    @events.command(name='edit', description='Preview changing an individual event; provide all its required fields')
    async def event_edit(interaction: discord.Interaction, id: int, date: str, time: str | None = None,
                         level: app_commands.Range[int, 1, 100] | None = None,
                         server: app_commands.Range[int, 1, 99999] | None = None):
        if not await leader(interaction): return
        rows = await scheduler.rows('SELECT * FROM schedule_requests WHERE id=? AND active=1', (id,))
        try:
            if not rows: raise ValueError('No active event has that ID.')
            row = rows[0]
            day, clock = parse_date(date), parse_time(time) if time else None
            slots = scheduler.validate(row['kind'], day, clock, level, server, await scheduler.season())
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        async def save():
            await scheduler.save_request(interaction.user.id, row['kind'], day, clock, level, server, id)
            return f'Event #{id} updated. Already-posted daily orders are unchanged; /event list shows the latest schedule.'
        await interaction.response.send_message(f'**Updated event #{id} — {day}**\n' + '\n'.join(e.line() for e in slots),
                                                ephemeral=True, view=Confirm(interaction.user.id, save))

    @events.command(name='cancel', description='Cancel an individual event; Desert Storm cancels both teams')
    async def event_cancel(interaction: discord.Interaction, id: int):
        if not await leader(interaction): return
        async def save():
            await scheduler.cancel(id, interaction.user.id)
            return f'Event #{id} cancelled. No further start messages will be sent for it.'
        await interaction.response.send_message(f'Cancel event #{id}? This applies to both slots if it is Desert Storm or Meteorite War.',
                                                ephemeral=True, view=Confirm(interaction.user.id, save))

    @events.command(name='list', description='Show the next 14 days of scheduled and fixed events')
    async def event_list(interaction: discord.Interaction):
        if not await leader(interaction): return
        await interaction.response.defer(ephemeral=True)
        lines = []
        today = datetime.now(SERVER_TIME).date()
        for offset in range(14):
            day = today + timedelta(days=offset)
            for e in await scheduler.events(day):
                lines.append(f'{day} · {e.line()}' + (f' · ID #{e.request_id}' if e.request_id else ' · fixed'))
        content = '\n'.join(lines) or 'No events.'
        # A text attachment keeps a large calendar readable without truncation.
        if len(content) > 1800:
            import io
            await interaction.followup.send('Next 14 days (server time):', file=discord.File(io.BytesIO(content.encode()), filename='oopz-events.txt'), ephemeral=True)
        else:
            await interaction.followup.send(content, ephemeral=True)

    @events.command(name='preview', description='Privately preview daily orders; does not send or ping anyone')
    async def event_preview(interaction: discord.Interaction, date: str | None = None):
        if not await leader(interaction): return
        try:
            day = parse_date(date) if date else datetime.now(SERVER_TIME).date()
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message(embed=agenda_embed(day, await scheduler.events(day), await scheduler.season()),
                                                ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @events.command(name='status', description='Check scheduler clock, channels, permissions and delivery health')
    async def event_status(interaction: discord.Interaction):
        if not await leader(interaction): return
        await interaction.response.defer(ephemeral=True)
        lines = [f'Server time: {datetime.now(SERVER_TIME):%Y-%m-%d %H:%M} · UTC−02:00',
                 'Daily orders: 00:00 · no ping. Event starts: @everyone. Multi-day events: daily orders only.',
                 f'Scheduler running: {scheduler.worker.is_running()}']
        for cid, ping in [(DAILY_CHANNEL, False), (ANNOUNCEMENTS_CHANNEL, True)]:
            try:
                channel = bot.get_channel(cid) or await bot.fetch_channel(cid)
                p = channel.permissions_for(channel.guild.me)
                ok = channel.guild.id == guild_id and p.send_messages and p.embed_links and (not ping or p.mention_everyone)
                lines.append(f'<#{cid}>: ' + ('ready' if ok else 'check Send Messages / Embed Links / Mention Everyone'))
            except discord.HTTPException:
                lines.append(f'<#{cid}>: inaccessible')
        uncertain = await scheduler.rows("SELECT key FROM schedule_deliveries WHERE status='claimed' ORDER BY claimed_at DESC LIMIT 5")
        if uncertain:
            lines.append('Check these uncertain deliveries manually (not resent): ' + ', '.join(r['key'] for r in uncertain))
        await interaction.followup.send('\n'.join(lines), ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @plans.command(name='import', description='Import LWMA text as private drafts; no coordinates are announced')
    async def plan_import(interaction: discord.Interaction, file: discord.Attachment):
        if not await leader(interaction): return
        if file.size > 200000 or not file.filename.lower().endswith('.txt'):
            await interaction.response.send_message('Attach an LWMA text export (.txt), under 200 KB.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            text = (await file.read()).decode('utf-8-sig')
            day, entries = None, []
            for line in text.splitlines():
                match = re.match(r'Day\s+(\d+)\b', line)
                if match:
                    day = int(match[1])
                capture = re.match(r'\s*(R0h|ROH|OOPZ)\s+takes\s+\d+,\d+\s+(SH|CITY)\s+L(\d+)\s*$', line, re.I)
                if capture:
                    if day is None or not 1 <= day <= 56: raise ValueError('Plan day must be between 1 and 56.')
                    entries.append((day, 'stronghold' if capture[2].upper() == 'SH' else 'city', int(capture[3])))
            if not entries: raise ValueError('No OOPZ/R0h captures found in this LWMA text export.')
            fingerprint = hashlib.sha256(text.encode()).hexdigest()
        except (ValueError, UnicodeError) as exc:
            await error(interaction, exc)
            return
        async def save():
            async with aiosqlite.connect(database) as db:
                for number, (day, kind, level) in enumerate(entries):
                    await db.execute('INSERT OR IGNORE INTO schedule_plan(fingerprint,entry_no,season_day,kind,level) VALUES (?,?,?,?,?)',
                                     (fingerprint, number, day, kind, level))
                await db.commit()
            return f'Imported {len(entries)} private capture drafts (identical imports are deduplicated). Use /plan list, then /plan schedule for each capture. No dates, times or coordinates were published.'
        await interaction.followup.send(f'Found {len(entries)} captures across {len(set(x[0] for x in entries))} days. Dates will follow your actual /season start date; example dates are ignored. Coordinates are discarded. Confirm private import?',
                                         ephemeral=True, view=Confirm(interaction.user.id, save))

    @plans.command(name='list', description='List unscheduled capture drafts for leadership only')
    async def plan_list(interaction: discord.Interaction):
        if not await leader(interaction): return
        rows = await scheduler.rows('SELECT * FROM schedule_plan WHERE request_id IS NULL ORDER BY season_day,id')
        lines = [f"#{r['id']} · Season Day {r['season_day']} · {KINDS[r['kind']]} · Level {r['level']}" for r in rows]
        content = '\n'.join(lines) or 'No unscheduled drafts. Import an LWMA .txt plan first.'
        import io
        await interaction.response.send_message('Private capture drafts:', ephemeral=True,
            file=discord.File(io.BytesIO(content.encode()), filename='private-capture-drafts.txt'))

    @plans.command(name='schedule', description='Choose server and time for a private capture draft')
    async def plan_schedule(interaction: discord.Interaction, id: int, server: app_commands.Range[int, 1, 99999], time: str):
        if not await leader(interaction): return
        rows = await scheduler.rows('SELECT * FROM schedule_plan WHERE id=? AND request_id IS NULL', (id,))
        try:
            start = await scheduler.season()
            if not rows: raise ValueError('No unscheduled draft has that ID.')
            if not start: raise ValueError('Set /season start first.')
            row = rows[0]
            day, clock = start + timedelta(days=row['season_day']-1), parse_time(time)
            slots = scheduler.validate(row['kind'], day, clock, row['level'], server, start)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        async def save():
            current_start = await scheduler.season()
            if current_start != start: raise ValueError('Season start changed. Preview this draft again.')
            rid = await scheduler.save_request(interaction.user.id, row['kind'], day, clock, row['level'], server)
            async with aiosqlite.connect(database) as db:
                await db.execute('UPDATE schedule_plan SET request_id=? WHERE id=?', (rid, id))
                await db.commit()
            return f'Capture scheduled as event #{rid}. Public messages contain no coordinates.'
        await interaction.response.send_message(f'**Capture preview — {day}**\n{slots[0].line()}\nNo coordinates will be posted.',
                                                ephemeral=True, view=Confirm(interaction.user.id, save))

    for group in (events, seasons, plans):
        bot.tree.add_command(group, guild=guild)

    @bot.tree.command(name='schedule', description='Show today’s OOPZ events in server time', guild=guild)
    async def schedule_today(interaction: discord.Interaction):
        if interaction.guild_id != guild_id:
            await interaction.response.send_message('Use this command in the OOPZ server.', ephemeral=True)
            return
        day = datetime.now(SERVER_TIME).date()
        await interaction.response.send_message(embed=agenda_embed(day, await scheduler.events(day), await scheduler.season()),
                                                ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
    return scheduler

