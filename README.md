# WoW Ding

Posts **“Ding! Reached level 42 in WoW.”** when your character gains level 42. The addon briefly draws a marker and asks WoW Forever to save a screenshot. A separate Python watcher decodes the level locally. Discord receives a text message with mentions disabled.

## Install on Windows

1. Clone or download this repository. Open PowerShell in the project folder.
2. In Battle.net, select **World of Warcraft: Forever → Show in Explorer**. Find the folder named `_forever_`. Copy this repository's entire `Ding` folder into its `Interface\AddOns` folder. The result must include `_forever_\Interface\AddOns\Ding\Ding.toc`.
3. Enable **Ding** in the AddOns list. If WoW was open, enter `/reload`. Restart the client if Ding does not appear. Take an ordinary in-game screenshot once if the `Screenshots` folder is missing.
4. Use Python 3.12 with a virtual environment. These commands use the Windows Python launcher. If Python 3.12 is already available as `python`, use `python -m venv .venv` for the first command.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Check the capture locally

Set the folder to your own Forever installation and start the watcher. Keep its terminal open.

```powershell
$shots = 'C:\Program Files (x86)\World of Warcraft\_forever_\Screenshots'
.\.venv\Scripts\python.exe watch.py "$shots"
```

In WoW, show the UI and enter `/ding test`. Within a few seconds the terminal should show **Test marker decoded: level 42.** For a real level-up, dry run prints **Dry run: level N.** Diagnostic captures stay local in both modes. Press **Ctrl+C** to stop a foreground watcher.

If the slash command works but nothing decodes, confirm that a new image appears in the watched directory and that the black-and-white tiles are visible at its upper left. Use original screenshots from WoW with the UI visible. Cropping, UI-hiding tools, third-party overlays or extremely low screenshot resolution can obscure the marker. WoW reports capture failures in chat.

## Enable Discord

In the destination Discord text channel, open **Edit Channel → Integrations → Webhooks**, create or select an incoming webhook, and copy its URL. You need permission to manage webhooks in that channel. Stop the foreground dry run, then run:

```powershell
.\.venv\Scripts\python.exe watch.py "$shots" --send
```

Paste the URL at the hidden prompt and press Enter. A secret supplied as `DISCORD_WEBHOOK` in the process environment also works. Keep the URL out of source code, command arguments and chat. The watcher accepts the standard HTTPS channel webhook URL on `discord.com`. A real level-up triggers delivery. Discord clients apply each member’s channel notification settings. [Discord webhook reference](https://docs.discord.com/developers/resources/webhook#execute-webhook)

The first live run starts at the current time. Subsequent live runs pick up eligible files saved since that first start and recover queued events. The watcher waits for file size and modification time to settle, suppresses repeated event IDs, and persists Discord rate-limit and retry delays. A rejected webhook stops the live watcher with a status code. Correct the webhook and restart with the same state file. A lost response or a crash between Discord accepting a message and the local receipt being saved can produce a duplicate.

## Privacy and storage

- WoW saves a **full screenshot**, which can include chat, player names and the surrounding scene. Review or delete these files locally as you normally would. An unprocessed capture must still exist for the watcher to read it. Point the watcher at a trusted local directory. The checksum detects damage and accidental matches, and anyone able to write to that directory can construct a marker.
- The addon uses the event payload and standard UI functions. It issues no character controls, reads no process memory, and stores no character or account identifiers. The watcher reads local image files. Image pixels, filenames, timestamps and character names are excluded from the webhook payload.
- Live state is under `%LOCALAPPDATA%\WoWDing\events.db` on Windows. It holds the initial start time, event IDs (which include a capture timestamp), levels, receipts and retry state. It contains no screenshot or webhook token. Use `--state "path\to\events.db"` for a separate folder or destination. To reset the history, stop the watcher and remove its state file. The next live start establishes a fresh cutoff.
- To disable, stop the watcher and disable **Ding** in WoW. Delete the webhook in Discord to revoke the URL. The project installs no system service or startup task.

## Compatibility and verification

Target: **WoW Forever 1.60.1, build 70840, interface 16001**. The installed Windows client matched the mirrored Blizzard UI source. Its generated event definition specifies a numeric first argument for `PLAYER_LEVEL_UP`. The client documents global `Screenshot()` and both screenshot result events. Blizzard’s own Edit Mode calls that global. [Build](https://github.com/Gethe/wow-ui-source/blob/5987a8e2304c1331346dc861d5ccacf4c510cf0f/version.txt) · [Level event](https://github.com/Gethe/wow-ui-source/blob/5987a8e2304c1331346dc861d5ccacf4c510cf0f/Interface/AddOns/Blizzard_APIDocumentationGenerated/UnitDocumentation.lua#L3830-L3838) · [Screenshot function](https://github.com/Gethe/wow-ui-source/blob/5987a8e2304c1331346dc861d5ccacf4c510cf0f/Interface/AddOns/Blizzard_APIDocumentationGenerated/ClientDocumentation.lua#L93-L97) · [Result events](https://github.com/Gethe/wow-ui-source/blob/5987a8e2304c1331346dc861d5ccacf4c510cf0f/Interface/AddOns/Blizzard_APIDocumentationGenerated/VideoDocumentation.lua#L164-L181) · [Edit Mode usage](https://github.com/Gethe/wow-ui-source/blob/5987a8e2304c1331346dc861d5ccacf4c510cf0f/Interface/AddOns/Blizzard_EditMode/Shared/EditModeDialogs.lua#L514)

On November 6, 2026, an in-game `/ding test` produced a 3840 × 2160 JPEG on this build. The running watcher reported level 42. The automated tests exercise the real addon event handler with a simulated level-up and check HTTP requests against a local server. A natural level-up and delivery to an actual Discord channel remain live acceptance checks. Other WoW editions are outside the verified target. This independent project makes no claim of Blizzard approval. [Blizzard UI Add-On Development Policy](https://us.forums.blizzard.com/en/wow/t/ui-add-on-development-policy/24534)

## Development

```powershell
.\.venv\Scripts\python.exe -m pip install -r dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Each tile has side length equal to 1/96 of the UI height. The first tile is one cell inward from the top-left corner. Eleven rows of eight bits each carry two magic bytes (`D6 39`), a version/type byte (`10` for a level, `11` for a test, both hex), the level (1–255), four bytes of server time, two random bytes and CRC-8 (polynomial `07`, initial zero). Integers are big-endian, with the most significant bit on the left. The addon waits two rendered frames before capture. The decoder samples tile interiors, checks contrast, signature, type, level and CRC, and accepts JPEG, PNG and TGA. A per-capture ID lets repeated images of one marker resolve to the same queued notification.

The test harness runs the shipped Lua in LuaJIT, draws the actual texture positions into images, and feeds them through the Python decoder. Tests also exercise capture queuing, failure and timeout cleanup, partial writes, restart recovery, diagnostic suppression and Discord error handling.
