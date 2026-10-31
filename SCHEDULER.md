# OOPZ daily orders and event scheduler

All event commands use server time. The configured fixed clock is UTC−02:00,
based on leadership's conversion: server midnight = 03:00 German winter time.
Use `/event status` to compare the live server clock before programming events.
German daylight-saving changes do not move the server schedule.

## Automatic messages

- Daily orders: every day at 00:00 in <#1524785999845130321>, without mentions.
- Individual event starts: <#1524785541059448966> with @everyone.
- General's Trial / Gold Zombies: included in daily orders Wednesday–Friday,
  with no separate @everyone post. General's Trial is anchored to 4–6 Nov 2026,
  Gold Zombies to 11–13 Nov 2026, each repeating every 14 days.
- Warzone Duel: Saturday 12:00; called Infinite Octagon during the season.
- Crimson Legion: Tuesday/Friday 12:00 from Season Week 2 through Day 56.
- No automatic Marshall Guard, Zombie Siege, Desert Storm, capture, Sky
  Battlefront or Meteorite War occurrence is invented. Leadership schedules each.

## Leadership commands

Only the exact R4 (1548703579055857774) and R5 (1548703462332694618) roles can
manage the calendar. Responses and previews are private. Changes require the
creator to press **Confirm and save** within three minutes.

- `/season start date:YYYY-MM-DD` sets or changes the 56-day season. Future
  dates activate automatically; after Day 56 the calendar returns out of season.
- `/season status` shows the saved dates, season day/week, and server clock.
- `/season end` returns to out-of-season mode after confirmation.
- `/event add event:Marshall Guard date:YYYY-MM-DD time:HH:MM level:5`
- `/event add event:Zombie Siege date:YYYY-MM-DD time:HH:MM level:5`
- `/event add event:Desert Storm date:YYYY-MM-DD` requires a Friday and creates
  Team A at 09:30 and Team B at 18:30 automatically. Leave time empty.
- `/event add event:Sky Battlefront date:YYYY-MM-DD` activates a Friday at
  12:00, out of season only. Leave time empty.
- `/event add event:Meteorite War date:YYYY-MM-DD` activates a Saturday at
  00:10 and 12:00, out of season only. Leave time empty.
- `/event add event:City Capture date:YYYY-MM-DD time:HH:MM level:3 server:2294`
- `/event add event:Stronghold Capture date:YYYY-MM-DD time:HH:MM level:4 server:2294`
- `/event list` shows the next 14 days and IDs for editable individual events.
- `/event edit id:12 date:YYYY-MM-DD time:HH:MM level:5` replaces that event's
  details. Supply all required fields, including server for a capture. Preset
  events require only the date. Already-started events cannot be edited.
- `/event cancel id:12` cancels both slots for Desert Storm / Meteorite War.
- `/event preview date:YYYY-MM-DD` privately previews the daily announcement.
- `/event status` checks destination permissions, the live clock, and uncertain
  deliveries. It does not publish anything.
- `/event test` previews a full sample run, then sends explicitly labelled TEST
  messages to daily-orders, announcements and r4-chat on confirmation. Everyone,
  role and user mentions are disabled. Samples use fictional 2030 dates and do
  not modify schedules, season settings, VS modes or member data.
- `/schedule` is available to all OOPZ members as a private view of today's agenda.

## LWMA capture plans

- `/plan import file:<LWMA text export>` previews a private import. R0h, ROH,
  and OOPZ are recognised as this alliance. The example calendar dates are
  ignored: Day 1 follows the actual season start. Coordinates are discarded.
- `/plan list` lists unscheduled drafts and their IDs privately.
- `/plan schedule id:1 server:2294 time:18:00` previews a capture using its
  season day, type and level. It creates a normal individual event on confirmation.
- Identical text imports do not duplicate drafts. A revised export is a distinct
  plan; review drafts to avoid scheduling duplicate operations.
- Changing the season start does not silently move already scheduled captures.
  Review `/event list` and edit affected events explicitly.

Public capture messages never include coordinates. They tell members to wait
for leadership before jumping. Live maps are not connected to this version.

## Delivery and recovery

Schedules, season settings, delivery records and change audit are stored in new
SQLite tables alongside the roster; existing tables and environment values are
preserved. Back up the whole database, not just roster CSVs, to retain schedules.

The worker checks every 20 seconds. A daily agenda can catch up until 00:15.
An event can catch up for ten minutes after its start; older messages are skipped
to avoid floods after downtime. There are no early countdown reminders.

Delivery is claimed before sending, preventing duplicate pings after restarts.
If a network failure makes delivery uncertain, it is not retried automatically;
`/event status` flags the record for leadership to check. Missing channel
permissions are logged and rechecked without claiming a delivery.

The bot needs View Channel, Send Messages and Embed Links in both channels,
and Mention Everyone in #announcements. Discord members can suppress @everyone
notifications in their own settings. If a published daily agenda is followed by
schedule changes, the original agenda remains a snapshot; `/schedule` and
`/event list` show the current version.

## VS and Arms Race

Daily orders now include that day's Season-1 VS tasks and the alliance's point
target. Minimum: **3.6 million per player per VS scoring day**. In Save weeks,
the maximum is **7.2 million per player per day**. Push weeks have no alliance
ceiling. Sunday is preparation rather than a VS scoring stage.

Each week starts **Unknown**; no automatic Push/Save alternation is inferred.
At 00:00 server time on Sunday, HR sends one reminder in the R4 channel
(1524482625824231505), mentioning
the R4 role if the following week is still Unknown. No @everyone is used for this
leadership reminder. R4 must be mentionable or the bot must have Mention Everyone
permission in the R4 channel for that role notification to work.

- `/vs week mode:Save` or `/vs week mode:Push`: preview, then confirm. On Sunday,
  this sets the coming Monday; Monday–Saturday it sets the current week.
- Optional `date:YYYY-MM-DD` selects the week containing that date.
- `/vs status`: privately checks this week and next week's modes.
- `/vs preview`: privately shows today's VS instructions; optional date supported.
- Choosing or changing the mode does not send an immediate public message or edit
  an already-posted agenda. Later event alerts read the latest saved mode.

Leadership-supplied recurring Arms Race alerts, sent with @everyone in #announcements:

| Day | Server time | Phase |
|---|---|---|
| Monday | 16:00 | Drone Boost |
| Tuesday | 08:00, 20:00 | Base Building |
| Wednesday | 08:00, 20:00 | Tech Research |
| Thursday | 08:00, 20:00 | Hero Advancement |
| Friday | 08:00, 20:00 | Unit Progression |
| Saturday | 12:00 | Use stamina for Arms Race |

Only these supplied windows are scheduled, not a guessed full rotation.
Matching actions are named explicitly: Thursday's shared actions, for example,
are hero recruitment and hero XP. Saturday stamina is presented separately from
Saturday VS scoring; it is not advertised as earning both types of points.

Task references (alliance rules and server times override generic advice):
- https://www.lastwargame.online/en/game-alliance-duel/
- https://www.lastwargame.online/en/arms-race-complete-guide/

