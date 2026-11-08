# Marking alt accounts

Only R4/R5 or Manage Server staff can use these commands. Replies and lists are private.

1. Type `/alt add`.
2. In **player_name**, choose the alt's in-game name from the latest uploaded roster.
3. In **owner**, choose the Discord member who owns it. Send the command.

Repeat for each alt. One person can own several alts. Their main account link,
nickname and roles stay unchanged.

`/missing_discord` now counts those alts as covered by their owner and lists them
separately. An alt only counts while its human owner is currently in this server.
If the owner leaves Discord, the alt appears missing again.

- `/alt list`: view saved alts, owners and current coverage.
- `/alt remove`: remove a marker. Choose its saved name, current name or player key.
- To change an owner: remove the old marker, then add it with the correct owner.

Links use the roster player UID when available, so renames survive daily imports.
Accounts absent from the current roster do not count. A name-only link requires
review if a later import introduces a UID; it is never silently transferred.
Keep the existing SQLite database to preserve all links.

This records in-game accounts represented by a real Discord owner. It does not
create extra Discord members or exempt the owner from normal roster enforcement.

