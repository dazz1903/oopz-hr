"""Self-service language labels. Does not translate messages or grant staff roles."""
from __future__ import annotations

import asyncio
import io
import logging
import json
from datetime import datetime, timezone

import aiosqlite
import discord
from discord import app_commands

log = logging.getLogger('oopz-languages')
LEADERS = {1548703462332694618, 1548703579055857774}
CHANNEL_NAME = 'choose-your-language'
READY_LANGUAGES = ('EN','PT','FR','DE','PL','ID')
CAMPAIGN_KEY = 'language_confirmation_20261108'

# Factual language names/codes from iTranslator's published catalogue:
# https://docs.itranslator.app/fundamentals/languages-list.md
_CATALOGUE = '''AF|Afrikaans
SQ|Albanian
AM|Amharic
AR|Arabic
HY|Armenian
AZ|Azerbaijani
EU|Basque
BE|Belarusian
BN|Bengali
BS|Bosnian
BG|Bulgarian
CA|Catalan
CEB|Cebuano
NY|Chichewa
ZH_HANS|Chinese (Simplified)
ZH_HANT|Chinese (Traditional)
CO|Corsican
HT|Haitian Creole
HR|Croatian
CS|Czech
DA|Danish
NL|Dutch
EN|English
EO|Esperanto
ET|Estonian
FI|Finnish
FR|French
FY|Frisian
GL|Galician
KA|Georgian
DE|German
EL|Greek
GU|Gujarati
HA|Hausa
HAW|Hawaiian
HE|Hebrew
HI|Hindi
HMN|Hmong
HU|Hungarian
IS|Icelandic
IG|Igbo
ID|Indonesian
GA|Irish
IT|Italian
JA|Japanese
JV|Javanese
KN|Kannada
KK|Kazakh
KM|Khmer
RW|Kinyarwanda
KO|Korean
KU|Kurdish (Kurmanji)
KY|Kyrgyz
LO|Lao
LA|Latin
LV|Latvian
LT|Lithuanian
LB|Luxembourgish
MK|Macedonian
MG|Malagasy
MS|Malay
ML|Malayalam
MT|Maltese
MI|Maori
MR|Marathi
MN|Mongolian
MY|Myanmar (Burmese)
NE|Nepali
NO|Norwegian
OR|Odia
PS|Pashto
FA|Persian
PL|Polish
PT|Portuguese
PT_BR|Brazilian Portuguese
PA|Punjabi
RO|Romanian
RU|Russian
SM|Samoan
GD|Scots Gaelic
SR_CYRL|Serbian (Cyrillic)
ST|Sesotho
SN|Shona
SD|Sindhi
SI|Sinhala
SK|Slovak
SL|Slovenian
SO|Somali
ES|Spanish
SU|Sundanese
SW|Swahili
SV|Swedish
TL|Filipino (Tagalog)
TG|Tajik
TA|Tamil
TT|Tatar
TE|Telugu
TH|Thai
TR|Turkish
TK|Turkmen
UK|Ukrainian
UR|Urdu
UG|Uyghur
UZ|Uzbek
VI|Vietnamese
CY|Welsh
XH|Xhosa
YI|Yiddish
YO|Yoruba
ZU|Zulu'''
LANGUAGES = dict(row.split('|') for row in _CATALOGUE.splitlines())
FREE = set('EN AR AZ CA ZH_HANS CS DA NL EO FI FR DE EL HE HI HU ID GA IT JA KO FA PL PT RU SK ES SV TR UK'.split())
NATIVE = {
    'SQ':'Shqip','AR':'العربية','HY':'Հայերեն','AZ':'Azərbaycanca','EU':'Euskara',
    'BE':'Беларуская','BN':'বাংলা','BS':'Bosanski','BG':'Български','CA':'Català',
    'ZH_HANS':'简体中文','ZH_HANT':'繁體中文','HR':'Hrvatski','CS':'Čeština','DA':'Dansk',
    'NL':'Nederlands','EN':'English','EO':'Esperanto','ET':'Eesti','FI':'Suomi',
    'FR':'Français','GL':'Galego','KA':'ქართული','DE':'Deutsch','EL':'Ελληνικά',
    'HE':'עברית','HI':'हिन्दी','HU':'Magyar','IS':'Íslenska','ID':'Bahasa Indonesia',
    'GA':'Gaeilge','IT':'Italiano','JA':'日本語','KO':'한국어','LV':'Latviešu',
    'LT':'Lietuvių','MS':'Bahasa Melayu','NO':'Norsk','FA':'فارسی','PL':'Polski',
    'PT':'Português','PT_BR':'Português (Brasil)','RO':'Română','RU':'Русский',
    'SR_CYRL':'Српски','SK':'Slovenčina','SL':'Slovenščina','ES':'Español',
    'SW':'Kiswahili','SV':'Svenska','TL':'Filipino','TH':'ไทย','TR':'Türkçe',
    'UK':'Українська','UR':'اردو','UZ':'O‘zbek','VI':'Tiếng Việt','CY':'Cymraeg',
}


def staff_target(target):
    permissions=getattr(target,'guild_permissions',None) or getattr(target,'permissions',None)
    return (target.id in LEADERS or getattr(target,'name','')=='🔐 OOPZ Leadership' or
        bool({r.id for r in getattr(target,'roles',[])} & LEADERS) or
        bool(permissions and (getattr(permissions,'administrator',False) or getattr(permissions,'manage_guild',False))))


def channel_language(name):
    names={'announcements':'EN','daily-orders':'EN','🇺🇸-english-chat':'EN','🇧🇷-chat':'PT','🇫🇷-chat':'FR','🇩🇪-chat':'DE','🇵🇱-chat':'PL','🇮🇩-chat':'ID',
        'english-chat':'EN','brazilian-chat':'PT','french-chat':'FR','german-chat':'DE','polish-chat':'PL','indonesian-chat':'ID'}
    if name in names:return names[name]
    for prefix in ('announcements-','daily-orders-'):
        if name.startswith(prefix):
            suffix=name[len(prefix):].upper()
            if suffix=='IN':suffix='ID'
            return suffix if suffix in READY_LANGUAGES else None
    return None


def role_name(code):
    return f'🌐 {code} · {NATIVE.get(code, LANGUAGES[code])}'


def choices(query):
    query = query.casefold().strip()
    return [app_commands.Choice(name=f'{NATIVE.get(code,name)} — {name} ({code})'[:100],value=code)
            for code,name in sorted(LANGUAGES.items(), key=lambda item:item[1])
            if not query or query in f'{code} {name} {NATIVE.get(code,"")}'.casefold()][:25]


class LanguageSelect(discord.ui.Select):
    def __init__(self, service, owner, page):
        ordered = sorted(LANGUAGES,key=lambda code:LANGUAGES[code])
        items = ordered[page*25:(page+1)*25]
        super().__init__(placeholder='Choose / Sprache / Idioma / Langue…', options=[
            discord.SelectOption(label=NATIVE.get(code,LANGUAGES[code])[:100],value=code,
                description=f'{LANGUAGES[code]} · {code}'[:100]) for code in items])
        self.service,self.owner=service,owner

    async def callback(self, interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            await self.service.select(interaction.user,self.values[0])
        except (ValueError,discord.HTTPException) as exc:
            log.warning('Language selection failed: %s', type(exc).__name__)
            await interaction.edit_original_response(content='Could not assign the language role. Ask R4/R5 to run `/language status` and check HR’s role permissions.',view=None)
            return
        await interaction.edit_original_response(content=f'✅ **{NATIVE.get(self.values[0],LANGUAGES[self.values[0]])}** saved.\n'
            'You can change your language here anytime. Matching language channels will appear when leadership finishes setting them up. Existing guides were not changed.',view=None)


class Picker(discord.ui.View):
    def __init__(self,service,owner,page=0):
        super().__init__(timeout=180)
        self.service,self.owner,self.page=service,owner,page
        self.pages=(len(LANGUAGES)+24)//25
        self.add_item(LanguageSelect(service,owner,page))
        self.previous.disabled=page==0
        self.next.disabled=page==self.pages-1

    async def interaction_check(self,interaction):
        return interaction.guild_id==self.service.guild_id and interaction.user.id==self.owner

    async def change(self,interaction,page):
        await interaction.response.edit_message(content=f'🌐 Choose your language — page {page+1}/{self.pages}.\n'
            'Use Previous/Next if you do not see it. / Wähle deine Sprache. / Escolha seu idioma. / Choisissez votre langue.',
            view=Picker(self.service,self.owner,page))

    @discord.ui.button(label='← Previous',style=discord.ButtonStyle.secondary,row=1)
    async def previous(self,interaction,button):
        await self.change(interaction,self.page-1)

    @discord.ui.button(label='Next →',style=discord.ButtonStyle.secondary,row=1)
    async def next(self,interaction,button):
        await self.change(interaction,self.page+1)


class PublicPicker(discord.ui.View):
    def __init__(self,service):
        super().__init__(timeout=None)
        self.service=service

    @discord.ui.button(label='🌐 Choose my language',style=discord.ButtonStyle.primary,custom_id='oopz:language:choose:v1')
    async def choose(self,interaction,button):
        if interaction.guild_id!=self.service.guild_id:
            await interaction.response.send_message('Use this in OOPZ.',ephemeral=True)
            return
        await interaction.response.send_message('🌐 Choose your language — page 1/5.\n'
            'Use Previous/Next if you do not see it. / Wähle deine Sprache. / Escolha seu idioma. / Choisissez votre langue.',
            ephemeral=True,view=Picker(self.service,interaction.user.id))


class Languages:
    def __init__(self,bot,database,guild_id):
        self.bot,self.database,self.guild_id=bot,database,guild_id
        self.lock=asyncio.Lock()
        self.registered=False

    async def init(self):
        async with aiosqlite.connect(self.database) as db:
            await db.executescript('''
                CREATE TABLE IF NOT EXISTS language_access_backup(campaign TEXT NOT NULL,channel_id TEXT NOT NULL,overwrites TEXT NOT NULL,PRIMARY KEY(campaign,channel_id));
                CREATE TABLE IF NOT EXISTS language_confirmed(member_id TEXT PRIMARY KEY,confirmed_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS language_roles(code TEXT PRIMARY KEY,role_id TEXT UNIQUE NOT NULL);
                CREATE TABLE IF NOT EXISTS language_preferences(member_id TEXT PRIMARY KEY,code TEXT NOT NULL,updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS language_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS language_notifications(
                    id INTEGER PRIMARY KEY,member_id TEXT NOT NULL,code TEXT NOT NULL,role_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending');
            ''')

    async def rows(self,query,values=()):
        async with aiosqlite.connect(self.database) as db:
            db.row_factory=aiosqlite.Row
            return await (await db.execute(query,values)).fetchall()

    async def get_role(self,guild,code):
        code='PT' if code=='PT_BR' else code
        if code not in LANGUAGES or guild.id!=self.guild_id:
            raise ValueError('Unknown language or server.')
        mappings=await self.rows('SELECT role_id FROM language_roles WHERE code=?',(code,))
        role=guild.get_role(int(mappings[0]['role_id'])) if mappings else None
        if role:
            if role.permissions.value!=0 or role.managed or role.is_default() or role.name!=role_name(code):
                raise ValueError('Language role was modified. Leadership must review it before self-assignment.')
            if role>=guild.me.top_role:
                raise ValueError('HR’s role must be above the language role.')
            return role
        if not guild.me.guild_permissions.manage_roles:
            raise ValueError('HR needs Manage Roles.')
        # Never adopt an unrelated existing role just because its name looks right.
        role=await guild.create_role(name=role_name(code),permissions=discord.Permissions.none(),
            hoist=False,mentionable=False,reason='OOPZ self-service language label')
        async with aiosqlite.connect(self.database) as db:
            await db.execute('INSERT OR REPLACE INTO language_roles VALUES (?,?)',(code,str(role.id)))
            await db.commit()
        return role

    async def select(self,member,code,*,notify=True,default=False):
        code='PT' if code=='PT_BR' else code
        if member.guild.id!=self.guild_id or member.bot or code not in LANGUAGES:
            raise ValueError('Invalid language selection.')
        async with self.lock:
            previous=await self.rows('SELECT code FROM language_preferences WHERE member_id=?',(str(member.id),))
            previous_code=previous[0]['code'] if previous else None
            if previous_code=='PT_BR':previous_code='PT'
            if default and previous_code:
                code=previous_code
            role=await self.get_role(member.guild,code)
            known={int(row['role_id']) for row in await self.rows('SELECT role_id FROM language_roles')}
            old=[r for r in member.roles if r.id in known and r.id!=role.id]
            had_new=any(r.id==role.id for r in member.roles)
            if not had_new:
                await member.add_roles(role,reason='Member chose preferred language')
            try:
                if old:
                    await member.remove_roles(*old,reason='Member changed preferred language')
            except discord.HTTPException:
                if not had_new:
                    await member.remove_roles(role,reason='Restore previous language after failed change')
                raise
            async with aiosqlite.connect(self.database) as db:
                stamp=datetime.now(timezone.utc).isoformat()
                await db.execute('INSERT OR REPLACE INTO language_preferences VALUES (?,?,?)',
                    (str(member.id),code,stamp))
                if not default:
                    await db.execute('INSERT OR REPLACE INTO language_confirmed VALUES (?,?)',(str(member.id),stamp))
                note_id=None
                if notify and not default and code!='EN' and code!=previous_code:
                    cur=await db.execute('INSERT INTO language_notifications(member_id,code,role_id,created_at) VALUES (?,?,?,?)',
                        (str(member.id),code,str(role.id),stamp))
                    note_id=cur.lastrowid
                await db.commit()
            log.info('Language choice saved: %s',code)
        if note_id:
            await self.notify_owner(member,code,role,note_id)

    async def notify_owner(self,member,code,role,note_id):
        # Only the server owner receives this notification. No public fallback.
        async with aiosqlite.connect(self.database) as db:
            cur=await db.execute("UPDATE language_notifications SET status='sending' WHERE id=? AND status='pending'",(note_id,))
            await db.commit()
            if not cur.rowcount:return
        try:
            owner=self.bot.get_user(member.guild.owner_id) or await self.bot.fetch_user(member.guild.owner_id)
            embed=discord.Embed(title='🌐 MEMBER CHOSE A LANGUAGE',color=0x3498DB,
                description=f'**{discord.utils.escape_markdown(member.display_name)}** chose **{LANGUAGES[code]}** '
                    f'({NATIVE.get(code,LANGUAGES[code])}).\n\n'
                    f'**Assigned role:** {role.name}\n**Role ID:** `{role.id}`\n\n'
                    'If this language is not ready yet, set up its channels and iTranslator links manually. '
                    'HR uses saved language roles for configured language-channel access. Use /language audit to check access.')
            embed.set_footer(text=f'Member ID: {member.id} · Language: {code}')
            await owner.send(embed=embed,allowed_mentions=discord.AllowedMentions.none())
            status='sent'
            log.info('Owner language notification sent: %s',code)
        except Exception as exc:
            status='failed'
            log.warning('Owner language DM failed (%s); recorded for /language report',type(exc).__name__)
        async with aiosqlite.connect(self.database) as db:
            await db.execute('UPDATE language_notifications SET status=? WHERE id=?',(status,note_id))
            await db.commit()

    async def assign_defaults(self,guild):
        try:
            if not guild.chunked:
                await guild.chunk(cache=True)
            # Prepare the three requested roles without granting channel access.
            async with self.lock:
                for code in READY_LANGUAGES:
                    await self.get_role(guild,code)
            done,failed=0,0
            for member in list(guild.members):
                if member.bot:continue
                try:
                    await self.select(member,'EN',notify=False,default=True)
                    done+=1
                except (ValueError,discord.HTTPException):
                    failed+=1
                    log.warning('Could not apply a default language role; check role hierarchy')
            log.info('Default language assignment complete: %s members, %s failures; previous choices preserved',done,failed)
            await self.apply_channel_access(guild)
            await self.prompt_members(guild)
            await self.send_rollout_audit(guild)
            # One initial private report helps the owner configure existing choices.
            sent=await self.rows("SELECT value FROM language_settings WHERE key='owner_report_defaults_v1'")
            if not sent:
                try:
                    text,counts=await self.report(guild)
                    owner=self.bot.get_user(guild.owner_id) or await self.bot.fetch_user(guild.owner_id)
                    await owner.send('🌐 English is now the default language. Existing other-language choices were preserved.\n'
                        'Here is your current language/role list for manual channel and translation setup. No translation rules or channel permissions were changed.',
                        file=discord.File(io.BytesIO(text.encode()),filename='oopz-languages-to-set-up.md'),
                        allowed_mentions=discord.AllowedMentions.none())
                    async with aiosqlite.connect(self.database) as db:
                        await db.execute("INSERT OR REPLACE INTO language_settings VALUES ('owner_report_defaults_v1','sent')")
                        await db.commit()
                except Exception as exc:
                    log.warning('Initial owner language report could not be DMed: %s',type(exc).__name__)
        except Exception as exc:
            log.warning('Default language assignment needs attention: %s',exc)

    async def publish(self):
        guild=self.bot.get_guild(self.guild_id)
        if not guild:raise ValueError('OOPZ guild unavailable.')
        settings={r['key']:r['value'] for r in await self.rows('SELECT * FROM language_settings')}
        channel=guild.get_channel(int(settings['channel'])) if settings.get('channel') else None
        if channel is None:
            channel=discord.utils.get(guild.text_channels,name=CHANNEL_NAME)
        if channel is None:
            if not guild.me.guild_permissions.manage_channels:
                raise ValueError('Create #choose-your-language, then give HR View Channel, Send Messages and Embed Links. Run /language setup afterward.')
            channel=await guild.create_text_channel(CHANNEL_NAME,
                topic='Choose or change your preferred language. Available to new and existing OOPZ members.',
                overwrites={guild.default_role:discord.PermissionOverwrite(view_channel=True,read_message_history=True,send_messages=False),
                    guild.me:discord.PermissionOverwrite(view_channel=True,read_message_history=True,send_messages=True,embed_links=True)},
                reason='Leadership requested a language picker for everyone')
        permissions=channel.permissions_for(guild.me)
        if not (permissions.view_channel and permissions.send_messages and permissions.embed_links):
            raise ValueError('HR needs View Channel, Send Messages and Embed Links in the language picker channel.')
        embed=discord.Embed(title='🌐 CHOOSE MY LANGUAGE',color=0x3498DB,
            description='**New here or already a member? Everyone can choose.**\n\n'
            '**Please confirm your language — including English speakers.** English stays your default until you choose.\n\n'
            'Press the button, find your language and select it. You can change your choice anytime.\n\n'
            '**Deutsch:** Wähle deine Sprache.\n**Português:** Escolha seu idioma.\n'
            '**Français:** Choisissez votre langue.\n**Español:** Elige tu idioma.\n'
            '**Polski:** Wybierz swój język.\n**Bahasa Indonesia:** Pilih bahasa Anda.\n**Русский:** Выберите свой язык.\n\n'
            'Choose English, Português, Français, Deutsch, Polski, Bahasa Indonesia or another language. Your selection gives you one language role; it can be changed anytime. Guides will be handled later.')
        embed.set_footer(text='Your selected role controls access where channel permissions are configured. Other-language choices notify the server owner privately.')
        message=None
        if settings.get('message') and settings.get('channel')==str(channel.id):
            try:
                message=await channel.fetch_message(int(settings['message']))
            except discord.NotFound:
                pass
        if message and message.author.id==self.bot.user.id:
            await message.edit(embed=embed,view=PublicPicker(self),allowed_mentions=discord.AllowedMentions.none())
        else:
            message=await channel.send(embed=embed,view=PublicPicker(self),allowed_mentions=discord.AllowedMentions.none())
        async with aiosqlite.connect(self.database) as db:
            await db.executemany('INSERT OR REPLACE INTO language_settings VALUES (?,?)',
                [('channel',str(channel.id)),('message',str(message.id))])
            await db.commit()
        log.info('Language picker ready: channel=%s message=%s ManageRoles=%s',channel.id,message.id,guild.me.guild_permissions.manage_roles)
        return channel,message

    async def report(self,guild,all_languages=False):
        mappings={r['code']:r['role_id'] for r in await self.rows('SELECT * FROM language_roles')}
        counts={}
        for row in await self.rows('SELECT member_id,code FROM language_preferences'):
            if guild.get_member(int(row['member_id'])):
                counts[row['code']]=counts.get(row['code'],0)+1
        codes=list(LANGUAGES) if all_languages else sorted(set(counts)|set(mappings),key=lambda c:(-counts.get(c,0),LANGUAGES.get(c,c)))
        lines=['# OOPZ languages', '', '| Language | Code | Members | Discord role ID | iTranslator plan |',
            '|---|---|---:|---|---|']
        for code in codes:
            lines.append(f'| {LANGUAGES[code]} — {NATIVE.get(code,LANGUAGES[code])} | {code} | {counts.get(code,0)} | {mappings.get(code,"Not created yet")} | {"Free" if code in FREE else "Premium/Pro"} |')
        if not codes:
            lines.append('| Nobody has chosen a language yet | — | 0 | — | — |')
        lines.extend(['','Use the matching language role when setting up its translated channels. English, Portuguese, French, German, Polish and Indonesian roles are prepared automatically.',
            'Use /language role to create a role before anyone selects it. Language roles have no server-wide permissions.',
            'Keep leadership channels restricted to leadership roles. Language selection does not replace roster verification.',
            'HR reconciles one saved language role and matching language-channel visibility. iTranslator routes are configured separately. Existing guides are unchanged.',
            'Catalogue reference: https://docs.itranslator.app/fundamentals/languages-list.md'])
        missed=await self.rows("SELECT code,COUNT(*) AS n FROM language_notifications WHERE status IN ('failed','sending') GROUP BY code")
        if missed:
            lines.extend(['','## Owner notifications needing review']+[f'- {LANGUAGES[r["code"]]}: {r["n"]} notifications could not be confirmed.' for r in missed])
        return '\n'.join(lines),counts

    async def apply_channel_access(self,guild):
        if not guild.me.guild_permissions.manage_roles:
            log.warning('Language channel access needs Manage Roles');return
        mappings={r['code']:int(r['role_id']) for r in await self.rows('SELECT * FROM language_roles')}
        managed=set(mappings.values())
        bots=[m for m in guild.members if m.bot and ('itranslator' in getattr(m,'name','').casefold() or (getattr(guild.me,'id',None) is not None and m.id==guild.me.id))]
        done,failed=0,0
        for channel in getattr(guild,'text_channels',[]):
            code=channel_language(channel.name)
            if not code:continue
            try:
                role=await self.get_role(guild,code)
                backup=[{'id':t.id,'type':'role' if isinstance(t,discord.Role) else 'member','allow':ow.pair()[0].value,'deny':ow.pair()[1].value} for t,ow in channel.overwrites.items()]
                async with aiosqlite.connect(self.database) as db:
                    await db.execute('INSERT OR IGNORE INTO language_access_backup VALUES (?,?,?)',(CAMPAIGN_KEY,str(channel.id),json.dumps(backup)));await db.commit()
                async def set_view(target,value,history=None):
                    ow=channel.overwrites_for(target)
                    if ow.view_channel==value and (history is None or ow.read_message_history==history):return
                    ow.view_channel=value
                    if history is not None:ow.read_message_history=history
                    await channel.set_permissions(target,overwrite=ow,reason='OOPZ owner requested one language channel set per member; previous settings backed up')
                # Keep the bots reachable before restricting broad channel grants.
                for member in bots:await set_view(member,True,True)
                await set_view(role,True,True)
                for target,ow in list(channel.overwrites.items()):
                    if target.id in {role.id,guild.default_role.id}:continue
                    if isinstance(target,discord.Role):
                        if target.id in managed:await set_view(target,False)
                        elif ow.view_channel is True and not target.managed and not staff_target(target):await set_view(target,None)
                    elif not target.bot and target.id!=guild.owner_id and not staff_target(target) and ow.view_channel is True:
                        await set_view(target,None)
                await set_view(guild.default_role,False)
                done+=1
            except (ValueError,discord.HTTPException) as exc:
                failed+=1;log.warning('Language access needs attention: #%s (%s)',channel.name,type(exc).__name__)
        log.info('Language channel access checked: %s channels, %s failures; backups saved',done,failed)

    async def prompt_members(self,guild):
        settings={r['key']:r['value'] for r in await self.rows('SELECT * FROM language_settings')}
        if settings.get(CAMPAIGN_KEY):return
        channel=guild.get_channel(int(settings['channel'])) if settings.get('channel') else None
        if channel is None:return
        p=channel.permissions_for(guild.me)
        async with aiosqlite.connect(self.database) as db:
            cur=await db.execute('INSERT OR IGNORE INTO language_settings VALUES (?,?)',(CAMPAIGN_KEY,'claimed'))
            await db.commit()
            if not cur.rowcount:return
        try:
            message=await channel.send(content=('@everyone ' if p.mention_everyone else '')+
                '🌐 **EVERYONE: PLEASE CONFIRM YOUR LANGUAGE**\n'
                'Already a member? Please choose too — even if you want English.\n'
                '**English · Português · Français · Deutsch · Polski · Bahasa Indonesia**\n'
                'Press **Choose my language** below. Your existing language stays until you choose. '
                'HR assigns one language role; you can change your choice anytime.\n'
                '**Polski:** Wybierz swój język. **Bahasa Indonesia:** Pilih bahasa Anda.',
                view=PublicPicker(self),allowed_mentions=discord.AllowedMentions(everyone=p.mention_everyone,users=False,roles=False))
            async with aiosqlite.connect(self.database) as db:
                await db.execute('UPDATE language_settings SET value=? WHERE key=?',(f'sent:{message.id}',CAMPAIGN_KEY));await db.commit()
            log.info('Language confirmation prompt published: everyone_ping=%s',p.mention_everyone)
        except Exception as exc:
            log.warning('Language prompt delivery needs review: %s',type(exc).__name__)

    async def member_audit(self,guild):
        if not guild.chunked:await guild.chunk(cache=True)
        if not guild.chunked:raise ValueError('Full Discord member list unavailable; try again shortly.')
        prefs={int(r['member_id']):r['code'] for r in await self.rows('SELECT * FROM language_preferences')}
        confirmed={int(r['member_id']) for r in await self.rows('SELECT member_id FROM language_confirmed')}
        mappings={r['code']:int(r['role_id']) for r in await self.rows('SELECT * FROM language_roles')}
        channels=[(c,channel_language(c.name)) for c in guild.text_channels if channel_language(c.name)]
        managed=set(mappings.values())
        lines=['# OOPZ language confirmations and access audit','',
            'Only members can confirm their own language; English defaults are not confirmations.',
            'Staff (R4/R5) and administrator visibility is excluded from member-channel warnings. The server owner always sees all channels.',
            '', '| Member | Saved language | Confirmed | Language roles | Channel access issues |','|---|---|---|---|---|']
        counts={'members':0,'unconfirmed':0,'role_issues':0,'access_issues':0}
        for member in guild.members:
            if member.bot:continue
            counts['members']+=1
            code=prefs.get(member.id,'EN')
            actual={r.id for r in member.roles if r.id in managed}
            role_bad=actual!={mappings.get(code)}
            if role_bad:counts['role_issues']+=1
            if member.id not in confirmed:counts['unconfirmed']+=1
            staff=staff_target(member)
            issues=[]
            if not staff:
                if not any(language==code for _,language in channels):issues.append('No channels configured for '+code)
                for c,language in channels:
                    visible=c.permissions_for(member).view_channel
                    if visible and language!=code:issues.append('Can see #'+c.name)
                    elif not visible and language==code:issues.append('Cannot see #'+c.name)
            if issues:counts['access_issues']+=1
            name=discord.utils.escape_markdown(member.display_name).replace('|','/').replace('\n',' ')
            actual_names=', '.join(r.name for r in member.roles if r.id in managed) or 'MISSING'
            lines.append(f'| {name} | {code} | {"Yes" if member.id in confirmed else "PLEASE CHOOSE"} | {actual_names}{" — FIX NEEDED" if role_bad else ""} | {"; ".join(issues) or "OK"} |')
        lines+=['','## Channel setup checklist']
        for c,code in channels:
            broad=[getattr(target,'name',str(target.id)) for target,ow in c.overwrites.items() if isinstance(target,discord.Role) and ow.view_channel is True and target.id not in managed and target.id not in LEADERS and not target.managed and not staff_target(target)]
            lines.append(f'- #{c.name}: use {role_name(code)} (role ID {mappings.get(code,"not created")}).'+(' Review broad View Channel grants: '+', '.join(broad) if broad else ''))
        lines+=['','Counts: '+', '.join(f'{k}: {v}' for k,v in counts.items()),
            'For each language channel: @everyone View Channel denied; matching language role allowed. Broad member/rank grants can expose other languages. Keep iTranslator and HR access. Keep leadership channels private.']
        return '\n'.join(lines),counts

    async def send_rollout_audit(self,guild):
        key='language_access_audit_20261108'
        if await self.rows('SELECT value FROM language_settings WHERE key=?',(key,)):return
        try:
            report,counts=await self.member_audit(guild)
            owner=self.bot.get_user(guild.owner_id) or await self.bot.fetch_user(guild.owner_id)
            await owner.send('🌐 **Language setup check**\nEnglish, Portuguese, French, German, Polish and Indonesian roles are ready. '
                f'{counts["unconfirmed"]} members still need to confirm a language. '
                f'{counts["role_issues"]} role issues; {counts["access_issues"]} members with channel-access issues. '
                'The attached private report lists exactly what needs checking. Use /language audit for a fresh copy.',
                file=discord.File(io.BytesIO(report.encode()),filename='oopz-language-access-audit.md'),allowed_mentions=discord.AllowedMentions.none())
            async with aiosqlite.connect(self.database) as db:
                await db.execute('INSERT OR REPLACE INTO language_settings VALUES (?,?)',(key,'sent'));await db.commit()
        except Exception as exc:
            log.warning('Language audit DM needs attention: %s',type(exc).__name__)

    async def start(self):
        await self.init()
        if not self.registered:
            self.bot.add_view(PublicPicker(self))
            self.registered=True
        try:
            await self.publish()
        except Exception as exc:
            log.warning('Language picker setup needs attention: %s',exc)
        guild=self.bot.get_guild(self.guild_id)
        if guild and (not hasattr(self,'default_task') or self.default_task.done()):
            self.default_task=asyncio.create_task(self.assign_defaults(guild))


def install(bot,database,guild_id):
    service=Languages(bot,database,guild_id)
    group=app_commands.Group(name='language',description='Choose your language or view the OOPZ language report')

    async def leader(interaction):
        if interaction.guild_id!=guild_id or not ({r.id for r in getattr(interaction.user,'roles',[])}&LEADERS):
            await interaction.response.send_message('Only OOPZ R4/R5 can manage language setup and reports.',ephemeral=True)
            return False
        return True

    async def autocomplete(interaction,current):
        return choices(current)

    @bot.listen('on_member_join')
    async def assign_join_language(member):
        if member.guild.id==guild_id and not member.bot:
            try:
                await service.select(member,'EN',notify=False,default=True)
                settings={r['key']:r['value'] for r in await service.rows('SELECT * FROM language_settings')}
                if settings.get('channel'):
                    try:await member.send(f'🌐 Welcome to OOPZ! Please confirm your language here: https://discord.com/channels/{guild_id}/{settings["channel"]}. English stays your default until you choose. Polski and Bahasa Indonesia are available too.',allowed_mentions=discord.AllowedMentions.none())
                    except discord.HTTPException:pass
            except (ValueError,discord.HTTPException):
                log.warning('New member default language could not be assigned')

    @bot.listen('on_member_update')
    async def reconcile_language_roles(before,after):
        if after.guild.id!=guild_id or after.bot:return
        if {r.id for r in before.roles}=={r.id for r in after.roles}:return
        managed={int(r['role_id']) for r in await service.rows('SELECT role_id FROM language_roles')}
        if ({r.id for r in before.roles} ^ {r.id for r in after.roles}) & managed:
            try:await service.select(after,'EN',notify=False,default=True)
            except (ValueError,discord.HTTPException):log.warning('Language role repair needs leadership attention')

    @group.command(name='choose',description='Choose or change your preferred language; everyone can use this')
    @app_commands.autocomplete(language=autocomplete)
    async def choose(interaction:discord.Interaction,language:str|None=None):
        if interaction.guild_id!=guild_id:
            await interaction.response.send_message('Use this in OOPZ.',ephemeral=True)
            return
        if language is None:
            await interaction.response.send_message('🌐 Choose your language — page 1/5.',ephemeral=True,view=Picker(service,interaction.user.id))
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await service.select(interaction.user,language.upper())
        except (ValueError,discord.HTTPException):
            await interaction.followup.send('Could not assign that language. Select a listed option; ask R4/R5 to check /language status if it still fails.',ephemeral=True)
            return
        await interaction.followup.send(f'✅ Saved **{NATIVE.get(language.upper(),LANGUAGES[language.upper()])}**. You can change it anytime.',ephemeral=True)

    @group.command(name='setup',description='Create or refresh the public choose-your-language message')
    async def setup(interaction:discord.Interaction):
        if not await leader(interaction):return
        await interaction.response.defer(ephemeral=True)
        try:
            channel,message=await service.publish()
        except (ValueError,discord.HTTPException) as exc:
            await interaction.followup.send(f'Could not publish the picker: {exc}',ephemeral=True)
            return
        await interaction.followup.send(f'Language picker ready: {message.jump_url}',ephemeral=True)

    @group.command(name='report',description='List selected languages, counts and role IDs for channel setup')
    async def report(interaction:discord.Interaction):
        if not await leader(interaction):return
        await interaction.response.defer(ephemeral=True)
        text,counts=await service.report(interaction.guild)
        summary=', '.join(f'{LANGUAGES[c]}: {n}' for c,n in sorted(counts.items(),key=lambda x:-x[1])) or 'No language choices yet.'
        await interaction.followup.send(summary[:1800],file=discord.File(io.BytesIO(text.encode()),filename='oopz-language-report.md'),
            ephemeral=True,allowed_mentions=discord.AllowedMentions.none())

    @group.command(name='catalogue',description='Download the complete language list, including translation plan requirements')
    async def catalogue(interaction:discord.Interaction):
        if not await leader(interaction):return
        text,_=await service.report(interaction.guild,all_languages=True)
        await interaction.response.send_message(file=discord.File(io.BytesIO(text.encode()),filename='oopz-language-catalogue.md'),ephemeral=True)

    @group.command(name='role',description='Prepare a language role for matching channels before members choose it')
    @app_commands.autocomplete(language=autocomplete)
    async def role(interaction:discord.Interaction,language:str):
        if not await leader(interaction):return
        await interaction.response.defer(ephemeral=True)
        try:
            async with service.lock:
                created=await service.get_role(interaction.guild,language.upper())
        except (ValueError,discord.HTTPException) as exc:
            await interaction.followup.send(str(exc),ephemeral=True)
            return
        await interaction.followup.send(f'Language role ready: **{created.name}**\nRole ID: `{created.id}`. Use this role for its matching translated channels.',ephemeral=True)

    @group.command(name='audit',description='Privately list unconfirmed languages, incorrect roles and channel visibility issues')
    async def audit(interaction:discord.Interaction):
        if not await leader(interaction):return
        await interaction.response.defer(ephemeral=True)
        try:report,counts=await service.member_audit(interaction.guild)
        except (ValueError,discord.HTTPException) as exc:
            await interaction.followup.send(str(exc),ephemeral=True);return
        await interaction.followup.send(f'**{counts["unconfirmed"]} need to choose**, **{counts["role_issues"]} role issues**, **{counts["access_issues"]} members with channel-access issues**. Private details attached.',
            file=discord.File(io.BytesIO(report.encode()),filename='oopz-language-access-audit.md'),ephemeral=True,allowed_mentions=discord.AllowedMentions.none())

    @group.command(name='repair',description='Restore saved language roles and matching language-channel access')
    async def repair(interaction:discord.Interaction):
        if not await leader(interaction):return
        await interaction.response.defer(ephemeral=True)
        await service.assign_defaults(interaction.guild)
        await interaction.followup.send('Saved language roles and language-channel access reconciled. Use /language audit to check any remaining role or channel-access issues.',ephemeral=True)

    @group.command(name='status',description='Check HR language permissions, picker and saved choices')
    async def status(interaction:discord.Interaction):
        if not await leader(interaction):return
        settings={r['key']:r['value'] for r in await service.rows('SELECT * FROM language_settings')}
        prefs=await service.rows('SELECT COUNT(*) AS n FROM language_preferences')
        perms=interaction.guild.me.guild_permissions
        await interaction.response.send_message(f'Picker channel: {settings.get("channel","not created")}\n'
            f'Manage Roles: {perms.manage_roles}\nManage Channels: {perms.manage_channels}\n'
            f'Saved language choices: {prefs[0]["n"]}\n'
            'English is the default. Other-language choices are DMed privately to the server owner.\n'
            'HR’s role must sit above its language roles. Existing members can use the button or /language choose.',ephemeral=True)

    bot.tree.add_command(group,guild=discord.Object(id=guild_id))
    return service

