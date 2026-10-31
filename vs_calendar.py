"""Season-1 VS instructions; Arms Race slots supplied by OOPZ leadership.

Task reference: https://www.lastwargame.online/en/game-alliance-duel/
Overlap reference: https://www.lastwargame.online/en/arms-race-complete-guide/
Points and week policy are OOPZ rules, not game reward thresholds.
"""
from datetime import time
import discord

# (daily VS theme, tasks, what to hold)
VS_DAYS = {
    0: ('Radar & Drone', 'Claim radar rewards; use stamina, drone parts and battle data.',
        'Keep hero recruitment, shards and skill medals for Thursday.'),
    1: ('Base Expansion', 'Finish buildings; recruit survivors; send UR trucks and legendary secret tasks.',
        'Keep research resources for Wednesday and hero resources for Thursday.'),
    2: ('Age of Science', 'Complete research; use research speedups and Valor Badges; claim radar; open drone component chests.',
        'Keep hero resources for Thursday and training speedups for Friday.'),
    3: ('Train Heroes', 'Recruit heroes; use hero XP, shards and skill medals.',
        'Keep troop training and training speedups for Friday.'),
    4: ('Total Mobilization', 'Train or promote troops; use training speedups; claim radar.',
        'Follow leadership’s shield instructions before Saturday.'),
    5: ('Enemy Buster', 'Use UR trucks, legendary secret tasks and speedups; fight only as leadership directs.',
        'Protect your troops and follow leadership’s combat orders.'),
    6: ('Prepare for Monday', 'Save completed radar rewards within storage limits; prepare gathering returns after reset.',
        'Hold drone resources for Monday. There is no VS scoring stage on Sunday.'),
}

# Only these overlap windows have been supplied; do not infer a full rotation.
ARMS = {
    0: ('Drone Boost', (time(16),), 'Use stamina and battle data now.'),
    1: ('Base Building', (time(8), time(20)), 'Finish buildings and use construction speedups now.'),
    2: ('Tech Research', (time(8), time(20)), 'Complete research and use research speedups now.'),
    3: ('Hero Advancement', (time(8), time(20)), 'Use hero recruitment tickets and hero XP now.'),
    4: ('Unit Progression', (time(8), time(20)), 'Train or promote troops and use training speedups now.'),
    5: ('Stamina', (time(12),), 'Use stamina for Arms Race now. This is separate from Saturday’s VS scoring tasks.'),
}


def target_text(mode, day):
    if day.weekday() == 6:
        return 'Sunday preparation — next VS scoring day: Monday. Minimum on each scoring day: **3.6 million per player**.'
    if mode == 'save':
        return '**SAVE WEEK:** each player must score **at least 3.6 million** today and **no more than 7.2 million**. Stop spending for VS when you reach the cap.'
    if mode == 'push':
        return '**PUSH WEEK:** each player must score **at least 3.6 million** today. Score as many points as possible; there is no alliance ceiling.'
    return '**WEEK MODE: UNKNOWN.** Each player must score **at least 3.6 million** today. R4/R5 has not selected Push or Save yet—follow leadership for further instructions.'


def add_daily_vs(embed, day, mode):
    theme, tasks, save = VS_DAYS[day.weekday()]
    embed.add_field(name='⚔️ VS — ' + theme, value=target_text(mode, day) + '\n\n**DO TODAY:** ' + tasks + '\n**SAVE / PREPARE:** ' + save, inline=False)
    if day.weekday() in ARMS:
        phase, clocks, action = ARMS[day.weekday()]
        timing = ' and '.join(t.strftime('%H:%M') for t in clocks)
        label = 'ARMS RACE — STAMINA' if day.weekday() == 5 else 'VS + ARMS RACE — SCORE TOGETHER'
        embed.add_field(name='⏰ ' + label, value=f'**{timing} server time · {phase}**\n{action}', inline=False)
    else:
        embed.add_field(name='R4/R5 — NEXT WEEK', value='Use `/vs week` to choose Push or Save for the coming Monday. HR never guesses the mode.', inline=False)
    return embed


def arms_embed(day, clock, mode):
    phase, _, action = ARMS[day.weekday()]
    combined = day.weekday() != 5
    embed = discord.Embed(title=('⚔️ VS + ARMS RACE — SCORE BOTH NOW!' if combined else '⚡ ARMS RACE — USE STAMINA NOW'),
                          description=f'**{phase} · {clock:%H:%M} server time**\n\n{action}', color=0x9B59B6)
    embed.add_field(name='YOUR DAILY VS TARGET', value=target_text(mode, day), inline=False)
    if not combined:
        embed.add_field(name='SATURDAY VS', value=VS_DAYS[5][1], inline=False)
    embed.set_footer(text='Check the active phase in-game before spending. HR posts at the times supplied by leadership.')
    return embed

