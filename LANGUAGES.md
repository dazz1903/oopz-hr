# Choose my language

HR publishes a persistent language picker in **#choose-your-language**. It is
available to existing members as well as new arrivals. The button opens a private
five-page menu. Members can change their choice at any time, or use
`/language choose` with a searchable language option.

The language catalogue contains 110 options from iTranslator's published list.
Translation is not enabled by choosing a role. iTranslator's free plan supports
30 of the listed languages; the catalogue marks the others as Premium/Pro.
https://docs.itranslator.app/fundamentals/languages-list.md

## For members

1. Open #choose-your-language.
2. Press **Choose my language**.
3. Use **Next** if needed and select your language.
4. Your choice is saved. Repeat these steps to change it.

HR gives you one language role. Once leadership has linked that role to the
matching translated channels, those channels become available. Existing English
guides are unchanged; guide translation will be handled separately.

## For R4/R5

- `/language report` lists languages already chosen, member counts and role IDs.
  It downloads a private Markdown report. This tells you which channels are needed.
- `/language catalogue` downloads all 110 choices, with role IDs where available
  and free-versus-paid iTranslator support.
- `/language role language:Portuguese` prepares the language role if you need to
  create its channels before anyone chooses it. Otherwise roles are created only
  when selected. Existing unrelated roles are never adopted automatically.
- `/language setup` creates or refreshes the picker message.
- `/language status` checks setup and HR's permissions.

To set up translated channels, use the role ID from the report. Add that language
role to the relevant language category/channel access rules, keeping staff-only
areas restricted to R4/R5. Do not use self-selected language roles as a substitute
for roster verification. iTranslator's channel-pair configurations are separate
from this picker; they are not changed by HR.

## Permissions and persistence

HR needs **Manage Roles**, with its highest role above the language roles.
Language roles start with zero server-wide permissions, no special color, no
separate member list and no role mentions. Selecting a language only adds/removes
HR-created language roles; it does not touch staff, rank or verification roles.
If a language role gains global permissions or is renamed, self-assignment of
that role stops until leadership reviews it.

HR can create #choose-your-language when it has Manage Channels. Otherwise,
create that channel manually, let everyone view it and read its history, and give
HR View Channel, Send Messages and Embed Links. Then run `/language setup`.

Choices, role IDs and the picker message ID are saved in new SQLite tables
alongside the roster. Buttons are re-registered after a restart. Re-running setup
edits the existing message rather than posting another. Reports contain aggregate
counts and role IDs, without member names or member IDs.

## English defaults and owner notifications

Existing and new human members receive English unless they already saved another
language. Choosing another language replaces their language role and sends the
server owner a private message with the member, language and assigned role ID.
Choosing the same language again does not repeat the message. Bot accounts are
excluded. Failed DMs are recorded in `/language report`; there is no public fallback.

English, Portuguese and French roles are prepared automatically. On first rollout,
the owner receives a private list of current choices and role IDs for manual setup.
No translation links or channel permissions are configured by this feature.

