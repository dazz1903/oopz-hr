"""Leadership-reviewed event instructions and persistent image attachments."""
from datetime import timedelta
from pathlib import Path
import uuid

import discord

ROOT = Path(__file__).resolve().parent


def instructions(event):
    title = event.title
    if title == 'Marshall Guard':
        return 'Start rallies with **Loki** and join rallies until both your **personal rewards** and the **alliance rewards** are maxed.'
    if title == 'Zombie Siege':
        return 'Put your **troops on the wall**.' + ('\nReinforce the members targeted by the bus on **waves 4, 8, 12, 16 and 20**.' if event.level is not None and event.level >= 7 else '')
    if title.startswith('General'):
        return 'Choose the **highest level available to you**. Ask for help with rallies when needed, and set your rallies to **1 minute**.'
    if title.startswith('Gold Zombies'):
        return 'Use **1-minute rallies** for zombies you can kill on your own. Use **5-minute rallies** for zombies you cannot kill yourself, so others have time to join. **Let’s maximize rewards!**'
    if title == 'Sky Battlefront':
        return 'Make sure to reach **50 tokens daily!**'
    if title.startswith('Desert Storm'):
        return 'Check your assignment on the team layout and follow R4/R5 instructions.'
    if title == 'Internal Capitol War':
        end = event.start + timedelta(hours=8)
        suffix = f' ({end:%d %b})' if end.date() != event.day else ''
        return f'**No buffs for 8 hours from the start: {event.clock:%H:%M}–{end:%H:%M}{suffix} server time.**\nFollow R4/R5 instructions.'
    if event.server:
        return 'Prepare for the capture and follow R4/R5 instructions.\n🚫 Do not jump until leadership gives the order.'
    return 'Join the operation and follow R4/R5 instructions.'


def event_embed(event, minutes=0):
    stage = f'STARTS IN {minutes // 60} HOURS' if minutes == 120 else ('STARTS IN 5 MINUTES' if minutes else 'STARTING NOW')
    return discord.Embed(title=f'{event.title.upper()} — {stage}',
        description=event.line() + '\n🕒 Server time', color=0xE67E22).add_field(
            name='ORDERS', value=instructions(event), inline=False)


def shield_embed(event):
    saturday = event.day.weekday() == 5
    if saturday:
        text = '**BUSTER DAY IS LIVE — SHIELD UP NOW!** If you’re not actively fighting, protect your base. Check your shield timer before going offline. **No shield = free points for the enemy!**'
    elif event.clock.hour == 22:
        text = '**Buster Day starts in 2 hours!** Shield up before reset. Don’t become someone else’s points.'
    elif event.clock.hour == 16:
        text = 'Don’t leave your shield until the last minute. Check your protection before logging off!'
    else:
        text = 'Buster Day is tomorrow! Prepare your shields and make sure you’re covered while offline.'
    return discord.Embed(title='🚨🛡️ BUSTER DAY IS LIVE' if saturday else '🛡️ SHIELD REMINDER', description=text + '\n🕒 Server time', color=0xE74C3C if saturday else 0xE6B84B)


async def store_images(scheduler, request_id, uploads):
    saved = []
    for team, attachment in uploads.items():
        if attachment is None:
            continue
        ext = Path(attachment.filename).suffix.lower()
        if ext not in {'.png', '.jpg', '.jpeg', '.webp', '.gif'} or attachment.size > 8 * 1024 * 1024:
            raise ValueError('Use a PNG, JPG, WebP or GIF image up to 8 MB per team.')
        folder = Path(scheduler.database).resolve().parent / 'event_images'
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (uuid.uuid4().hex + ext)
        try:
            await attachment.save(path)
        except Exception as exc:
            raise ValueError(f'Event #{request_id} was saved, but Team {team} image could not be downloaded. Use /event edit to attach it again.') from exc
        saved.append((str(request_id), team, str(path)))
    if saved:
        import aiosqlite
        async with aiosqlite.connect(scheduler.database) as db:
            await db.executemany('INSERT OR REPLACE INTO schedule_images(request_id,team,path) VALUES (?,?,?)', saved)
            await db.commit()


async def image_path(scheduler, event):
    if event.category == 'shield':
        path = ROOT / ('shield-saturday.png' if event.day.weekday() == 5 else 'shield-friday.png')
    elif event.request_id and event.title.startswith('Desert Storm'):
        rows = await scheduler.rows('SELECT path FROM schedule_images WHERE request_id=? AND team=?', (str(event.request_id), event.key.rsplit(':', 1)[-1]))
        path = Path(rows[0]['path']) if rows else None
    else:
        path = None
    return path if path and path.is_file() else None


def validate_images(kind, uploads):
    if any(uploads.values()) and kind != 'desert':
        raise ValueError('Team image options are for Desert Storm.')
    for attachment in uploads.values():
        if attachment is not None and (Path(attachment.filename).suffix.lower() not in {'.png','.jpg','.jpeg','.webp','.gif'} or attachment.size > 8*1024*1024):
            raise ValueError('Use a PNG, JPG, WebP or GIF up to 8 MB per team.')

