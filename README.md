# WoW Ding

Posts your character’s name and new level, for example **“Ding! Élara reached level 42 in WoW.”** The addon briefly draws a marker and asks WoW Forever to save a screenshot. A separate Python watcher decodes the name and level locally. Discord receives a text message with mentions disabled.

## Get started on Windows

1. Download **WoW-Ding.msi** from the [latest release](https://github.com/aelder/wow-ding/releases/latest), or use the installer shared with you. Double-click it on a Windows 10 or 11 x64 PC with WoW Forever installed.
2. **WoW Ding** opens after installation. Check the detected game folder, paste a Discord channel webhook, and click **Install addon and connect**. To make a webhook, open the Discord text channel’s **Edit Channel → Integrations → Webhooks**, choose **New Webhook**, and click **Copy Webhook URL**. Creating one requires the channel’s Manage Webhooks permission.
3. In WoW Forever, enter `/reload` and then `/ding ping`. Look for a labeled test containing your character’s name and current level in Discord. The setup window confirms when Discord accepts it. You can then close setup. Future level-ups post automatically, including after your next Windows sign-in.

The MSI contains the addon, the watcher and Python. Each player supplies a webhook for their intended channel. Share the [installer download](https://github.com/aelder/wow-ding/releases/latest/download/WoW-Ding.msi) with friends.

### Settings and removal

Open **WoW Ding** from Start to change the game folder or webhook. Leave the webhook blank to reuse the saved one. The URL lives in Windows Credential Manager under **WoW Ding/Discord webhook**. Windows may show an unknown-publisher notice for the unsigned installer. Obtain the file from someone you trust.

If the game folder is empty or incorrect, click **Browse** and choose `World of Warcraft` or its `_forever_` folder. If the game is open during setup and the slash command is unknown, restart WoW and enable **Ding** in AddOns. If a test does not appear, check that the UI is visible and WoW can write to `_forever_\Screenshots`. The local-only `/ding test` command is available for capture diagnostics.

Use **Settings → Apps → Installed apps → WoW Ding → Uninstall** to remove the installer-managed app, startup shortcut, saved webhook and unmodified addon files. Local delivery history and screenshots remain on your PC. Discord lets you revoke the webhook by deleting it in the channel settings.

## Privacy and storage

- WoW saves a **full screenshot**, which can include chat, player names and the surrounding scene. Review or delete these files locally as you normally would. An unprocessed capture must still exist for the watcher to read it. Point the watcher at a trusted local directory. The checksum detects damage and accidental matches, and anyone able to write to that directory can construct a marker.
- The addon uses the event payload and standard UI functions. It reads the player’s base character name with `UnitName("player")` and the manual test level with `UnitLevel("player")`. The webhook sends the character name and level as text. Realm, account, screenshots, filenames and timestamps stay local. If the client restricts access to the name, a real event falls back to a level-only post and a manual ping is skipped.
- Live state is under `%LOCALAPPDATA%\WoWDing` on Windows. Setup selects a delivery database for the configured folder and channel. It holds the initial start time, event IDs (which include a capture timestamp), character names, levels, test flags, delivery status and retry state. It contains no screenshot or webhook token. Changing the destination starts a fresh history. To reset the history, stop the watcher and remove its state file. The next live start establishes a fresh cutoff.
- To disable, stop the watcher, remove the optional Startup shortcut, and disable **Ding** in WoW. Delete the webhook in Discord to revoke the URL.

## Compatibility and verification

Target: **WoW Forever 1.60.1, build 70840, interface 16001**. The installed Windows client matched the mirrored Blizzard UI source. Its generated event definition specifies a numeric first argument for `PLAYER_LEVEL_UP`. The client documents global `Screenshot()` and both screenshot result events. Blizzard’s own Edit Mode calls that global. [Build](https://github.com/Gethe/wow-ui-source/blob/5987a8e2304c1331346dc861d5ccacf4c510cf0f/version.txt) · [Level event](https://github.com/Gethe/wow-ui-source/blob/5987a8e2304c1331346dc861d5ccacf4c510cf0f/Interface/AddOns/Blizzard_APIDocumentationGenerated/UnitDocumentation.lua#L3830-L3838) · [Screenshot function](https://github.com/Gethe/wow-ui-source/blob/5987a8e2304c1331346dc861d5ccacf4c510cf0f/Interface/AddOns/Blizzard_APIDocumentationGenerated/ClientDocumentation.lua#L93-L97) · [Result events](https://github.com/Gethe/wow-ui-source/blob/5987a8e2304c1331346dc861d5ccacf4c510cf0f/Interface/AddOns/Blizzard_APIDocumentationGenerated/VideoDocumentation.lua#L164-L181) · [Edit Mode usage](https://github.com/Gethe/wow-ui-source/blob/5987a8e2304c1331346dc861d5ccacf4c510cf0f/Interface/AddOns/Blizzard_EditMode/Shared/EditModeDialogs.lua#L514)

On November 6, 2026, an in-game `/ding test` produced a 3840 × 2160 JPEG on this build. The running watcher reported level 42. The automated tests exercise the real addon event handler with a simulated level-up and check HTTP requests against a local server. A live Discord connection test also returned a confirmed message. A natural level-up remains a separate live acceptance check. Other WoW editions are outside the verified target. This independent project makes no claim of Blizzard approval. [Blizzard UI Add-On Development Policy](https://us.forums.blizzard.com/en/wow/t/ui-add-on-development-policy/24534)

## Development

Use Python 3.12 for Windows x64 and the WiX 4.0.6 CLI (`dotnet tool install wix --version 4.0.6 --tool-path .tools`). From the project folder:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r dev.txt -r win.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\build.ps1 -Wix .\.tools\wix.exe
```

The resulting `dist\WoW-Ding.msi` is the shareable installer. To test the CLI during development, run `.\.venv\Scripts\python.exe watch.py "path-to-Screenshots"` for a local dry run. Add `--send` for live delivery with a hidden webhook prompt. Each packaged release should also exercise an install, upgrade and uninstall, plus the packaged-app test using `WOWDING_EXE` on a Windows account with a saved webhook.

Each tile has side length equal to 1/96 of the UI height. The first tile is one cell inward from the top-left corner. Each eight-bit row encodes one byte. After eleven rows the next block starts immediately to the right. The header carries magic bytes `D6 39`, a type byte, level (1–255), four bytes of server time and two random bytes. Types `20` (named level-up) and `22` (named test ding) append a length byte and up to 48 UTF-8 bytes of character name. Legacy types `10` (level only) and `11` (local diagnostic) omit the name. All types end with CRC-8 (polynomial `07`, initial zero). Values here are hexadecimal for magic, types and polynomial. Integers are big-endian, with the most significant bit on the left. The addon waits two rendered frames before capture. The decoder samples tile interiors, checks contrast, signature, type, level and CRC, and accepts JPEG, PNG and TGA. A per-capture ID lets repeated images of one marker resolve to the same queued notification.

The test harness runs the shipped Lua in LuaJIT, draws the actual texture positions into images, and feeds them through the Python decoder. Tests also exercise capture queuing, failure and timeout cleanup, partial writes, restart recovery, diagnostic suppression and Discord error handling.
