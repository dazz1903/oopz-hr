"""Self-service language labels. Does not translate messages or grant staff roles."""
from __future__ import annotations

import asyncio
import io
import logging
from datetime import datetime, timezone

import aiosqlite
import discord
from discord import app_commands

log = logging.getLogger('oopz-languages')
LEADERS = {1548703462332694618, 1548703579055857774}
CHANNEL_NAME = 'choose-your-language'

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
        if member.guild.id!=self.guild_id or member.bot or code not in LANGUAGES:
            raise ValueError('Invalid language selection.')
        async with self.lock:
            previous=await self.rows('SELECT code FROM language_preferences WHERE member_id=?',(str(member.id),))
            previous_code=previous[0]['code'] if previous else None
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
                    'HR has not changed channel permissions or translation settings.')
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
                for code in ('EN','PT','FR'):
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
            '**English is your default.** Pick another language below if you prefer.\n\n'
            'Press the button, find your language and select it. You can change your choice anytime.\n\n'
            '**Deutsch:** Wähle deine Sprache.\n**Português:** Escolha seu idioma.\n'
            '**Français:** Choisissez votre langue.\n**Español:** Elige tu idioma.\n'
            '**Polski:** Wybierz swój język.\n**Русский:** Выберите свой язык.\n\n'
            'Leadership will use your choices to set up the matching language channels. Guides will be handled later.')
        embed.set_footer(text='Your role is visible on your profile. Other-language choices notify the server owner privately. Translation setup is manual.')
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
        lines.extend(['','Use the matching language role when setting up its translated channels. Roles are created only as needed.',
            'Use /language role to create a role before anyone selects it. Language roles have no server-wide permissions.',
            'Keep leadership channels restricted to leadership roles. Language selection does not replace roster verification.',
            'This picker does not configure iTranslator or alter existing guides.',
            'Catalogue reference: https://docs.itranslator.app/fundamentals/languages-list.md'])
        missed=await self.rows("SELECT code,COUNT(*) AS n FROM language_notifications WHERE status IN ('failed','sending') GROUP BY code")
        if missed:
            lines.extend(['','## Owner notifications needing review']+[f'- {LANGUAGES[r["code"]]}: {r["n"]} notifications could not be confirmed.' for r in missed])
        return '\n'.join(lines),counts

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
            except (ValueError,discord.HTTPException):
                log.warning('New member default language could not be assigned')

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

