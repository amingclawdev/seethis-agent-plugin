# SeeThis + Codex — install and try the hackathon demo

**Mark a page, hand the reference to Codex, and revisit the pictures, conversation and changing instructions together.** This is the single setup and testing guide for the SeeThis app and its local Codex plugin.

[Download everything](https://github.com/amingclawdev/seethis-agent-plugin/releases/tag/v0.4.1-hackathon.1) · [SeeThis app source](https://github.com/amingclawdev/seethis/tree/codex/hackathon-demo-016-20261025) · [Report a problem](https://github.com/amingclawdev/seethis-agent-plugin/issues)

## Downloads

| Component | Version | Download |
| --- | --- | --- |
| SeeThis for Apple Silicon | 0.1.6 hackathon, source `8b39106` | **[macOS DMG](https://github.com/amingclawdev/seethis-agent-plugin/releases/download/v0.4.1-hackathon.1/SeeThis-0.1.6-Hackathon-8b39106-macos-arm64.dmg)** · [App ZIP](https://github.com/amingclawdev/seethis-agent-plugin/releases/download/v0.4.1-hackathon.1/SeeThis-0.1.6-Hackathon-8b39106-macos-arm64.zip) |
| Codex plugin + MCP + skill + hooks | 0.4.1 | **[Plugin source ZIP](https://github.com/amingclawdev/seethis-agent-plugin/releases/download/v0.4.1-hackathon.1/seethis-runs-0.4.1-source.zip)** · [Browse source](https://github.com/amingclawdev/seethis-agent-plugin) |
| Checksums and provenance | This release | [SHA256SUMS](https://github.com/amingclawdev/seethis-agent-plugin/releases/download/v0.4.1-hackathon.1/SHA256SUMS) · [RELEASE-MANIFEST.json](https://github.com/amingclawdev/seethis-agent-plugin/releases/download/v0.4.1-hackathon.1/RELEASE-MANIFEST.json) |

The app and DMG are Developer ID signed, Apple notarized and stapled. This is a **hackathon prerelease**, separate from the App Store 0.1.5 release. The plugin is installed locally; it has not been submitted to the universal plugin directory. The plugin source uses the [MIT license](LICENSE), matching SeeThis.

**Setup order:** install SeeThis → install plugin → review four hooks → connect the installed helper → open Reference runs → test two runs.

[Requirements](#requirements) · [1. App](#1-install-seethis) · [2. Plugin](#2-install-the-plugin) · [3. Hooks](#3-review-the-four-hooks) · [4. Connection](#4-connect-seethis-to-the-installed-plugin) · [5. Checks](#5-check-the-installation) · [6. Full demo](#6-test-the-complete-workflow) · [Troubleshooting](#troubleshooting) · [Data and limits](#data-and-limits) · [Uninstall](#uninstall)

## Requirements

- An **Apple Silicon Mac running macOS 14.2 or later**. This release does not include an Intel or Windows app.
- Codex in the macOS desktop app, signed in, with native local plugin and hook support. The checked CLI was **0.163.0-alpha.11.2**. Use a client that exposes `plugin marketplace`, `plugin add`, `plugin remove` and `/hooks`.
- **Python 3.10+**, available as `python3` to the Codex process, and a writable home directory. No `pip install`, API key or third-party Python dependency is needed.
- Git only if you choose to clone the source; the ZIP installation works without Git.

Check `python3 --version` and `codex --version` in Terminal. If `codex` is not on PATH, use your desktop app's bundled CLI path in every command below. The tested host used `/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex`; other installations can differ. Check `codex plugin --help` before continuing. Do not assume an older CLI supports these commands.

## 1. Install SeeThis

1. Download the DMG and `SHA256SUMS` above. In the download directory, run:

   ```sh
   shasum -a 256 SeeThis-0.1.6-Hackathon-8b39106-macos-arm64.dmg
   ```

   Expected SHA-256: `5e03987f4ddb38fd354b35b52d3dbb29b3d04eaf00702e879e1ccedc6aff9d81`.
   Compare the ZIP/plugin download against the same release's checksum file if using those files.
2. Quit any running SeeThis copy. Open the DMG and drag **SeeThis.app** to **Applications**. If macOS asks to replace an existing copy, keep a backup first if you need that version for another test. Open the installed `/Applications/SeeThis.app`, rather than another copy inside an old disk image.
3. In **System Settings → Privacy & Security**, grant **Screen Recording** (called **Screen & System Audio Recording** on some versions) and **Input Monitoring** to that installed app. Complete any macOS restart/reopen prompt yourself.
4. Open SeeThis from its menu bar icon. **Show SeeThis** must report both capture permissions ready. **Show Inspector** opens the reference controls. Review the displayed Capture shortcut; hold that configured shortcut while drawing and release it to finish the round.
5. Chrome Automation is optional for Chrome-specific page identity. It is separate from the two capture permissions. Other applications can be marked without it.

If a permission row launches an old copy, quit it and select the exact installed app when granting permission. Do not reset the permissions database or disable Gatekeeper to work around a wrong path. This integration build shares SeeThis's application identity with other copies, so avoid running several versions at once.

## 2. Install the plugin

**ZIP option:** download and extract `seethis-runs-0.4.1-source.zip`, then change into its `seethis-runs-0.4.1` directory in Terminal.

**Git option:** clone the pinned hackathon release:

```sh
git clone --branch v0.4.1-hackathon.1 --depth 1 https://github.com/amingclawdev/seethis-agent-plugin.git
cd seethis-agent-plugin
```

The source is the MCP/plugin project, not the macOS application. Its entry point is [`seethis_runs/mcp_server.py`](seethis_runs/mcp_server.py). The plugin also contains a skill and four lifecycle hooks.

Run the following from the project root (the directory containing `.mcp.json`):

```sh
python3 - <<'PY'
import json, shutil
from pathlib import Path
root = Path.cwd()
market = root / 'build/marketplace'
plugin = market / 'plugins/seethis-runs'
plugin.mkdir(parents=True, exist_ok=True)
for name in ('.codex-plugin', 'seethis_runs', 'skills'):
    shutil.copytree(root / name, plugin / name, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
shutil.copy2(root / '.mcp.json', plugin / '.mcp.json')
catalog = market / '.agents/plugins/marketplace.json'
catalog.parent.mkdir(parents=True, exist_ok=True)
catalog.write_text(json.dumps({
    'name': 'seethis-agent-demo-local',
    'plugins': [{'name': 'seethis-runs',
                 'source': {'source': 'local', 'path': './plugins/seethis-runs'},
                 'policy': {'installation': 'AVAILABLE', 'authentication': 'ON_INSTALL'},
                 'category': 'Productivity'}]
}, indent=2))
print(market)
PY
codex plugin marketplace add "$PWD/build/marketplace" --json
codex plugin add seethis-runs@seethis-agent-demo-local --json
```

Keep the extracted source and marketplace directory available. Confirm native
installation reports version `0.4.1` and save its returned `installedPath`.
The observed demo path is
`~/.codex/plugins/cache/seethis-agent-demo-local/seethis-runs/0.4.1`;
use your returned path if it differs. Do not edit installed cache files.

For an existing installation, stage the new source first, then use native
`codex plugin remove seethis-runs@seethis-agent-demo-local --json` followed by the
`plugin add` command above. This preserves the independent run store. It may
remove the old helper path, so reconnect the bridge after every reinstall.

## 3. Review the four hooks

Start `codex` in the source project directory. Open `/hooks`, or choose
**Review hooks** when Codex reports changed definitions. Open each of these event
entries and review only the hook whose source is
`seethis-runs@seethis-agent-demo-local`:

| Event | Purpose |
| --- | --- |
| UserPromptSubmit | Open a run when a reference is handed in |
| Stop | Infer stopped-without-end for a matching unfinished run |
| Interrupt | Record interruption of a matching unfinished run |
| SessionEnd | Infer interruption for remaining unfinished session runs |

Each event has one synchronous command with timeout **1 second**. Its unexpanded
source definition is:

```sh
{ [ -n "${PLUGIN_ROOT:-}" ] && python3 "${PLUGIN_ROOT}/seethis_runs/hooks.py"; } >/dev/null 2>&1 || :
```

Codex expands the helper path to the installed plugin root. Review that path and
use the native trust action for each event separately. The current CLI offers
`t` while viewing an event needing review. Confirm each becomes **Trusted** and
active. Installing or enabling a plugin does not establish trust; changed
commands require another review. Do not use a skip-trust option or edit trust
records. Leave unrelated hooks unchanged.

The shell wrapper handles missing Python or target failures before the handler
starts. The handler begins its own 0.8-second deadline before loading the store.
An error stops that invocation without a subsequent callback, state write or
retry, and silently exits zero so Codex can continue. Exit zero is fail-open
behavior, not a successful run report. Missing hook data stays missing.


Installation and hook trust are separate steps in [OpenAI’s plugin documentation](https://developers.openai.com/plugins/build/plugins). The commands above and the native review flow were also checked against the bundled CLI on the demo host. This guide retains that tested local format; it does not promise compatibility with every client version.

## 4. Connect SeeThis to the installed plugin

Keep SeeThis open after completing step 1.
Use the helper from the native installation, not from the extracted source:

```sh
python3 "$HOME/.codex/plugins/cache/seethis-agent-demo-local/seethis-runs/0.4.1/seethis_runs/bridge.py" --connect
```

Substitute your actual installed path if needed. This creates an owner-only
`bridge.json` next to `runs.json`. It binds the exact Python executable, helper
path and Python source digests. The app checks this binding before invoking a
bounded helper process per request. Reconnect after installation changes; no
listener needs to be started. A `connected:true` response verifies descriptor
creation, not an end-to-end reference or log rendering result.

**To reach the page: menu bar SeeThis → Show Inspector → select a reference → Reference runs…**. Use **All references** to see the list, then **View details** to open its pictures and conversation. Keep the existing app running
while using its page. The app chooses its local port: use the URL it opens,
rather than copying a demo port. The page receives a separate ephemeral local
view capability. Closing/restarting SeeThis invalidates that URL; open it again
from Inspector. Do not publish this private URL or reference capabilities.

## 5. Check the installation

1. Check `plugin add` reported manifest version **0.4.1**. `/hooks` must show all
   four plugin definitions active and trusted, with a one-second timeout and the
   installed helper path. The native `hooks/list` app-server API provides the
   same metadata for an operator using that API; there is no public trust-update
   API in the checked CLI schema.
2. Check `--connect` reports `connected:true` and the 0.4.1 installed helper. To
   check the local descriptor without opening any run or log:

   ```sh
   python3 - <<'PY'
   import hashlib, json
   from pathlib import Path
   p = Path.home() / '.local/share/seethis-agent-demo/bridge.json'
   d = json.loads(p.read_text())
   print('helper:', d['helper'])
   print('sources_match:', all(Path(k).is_file() and
       hashlib.sha256(Path(k).read_bytes()).hexdigest() == v
       for k, v in d['files'].items()))
   PY
   ```

3. Start a **fresh Codex conversation** after installation. Confirm the plugin's
   MCP tools are available: `get_progress`, `run_end`, `confirm_takeover`, and
   `commit_handoff`. The server's MCP initialize compatibility version remains
   **0.4.0**; package 0.4.1 changes hook startup protection. Do not interpret that
   existing MCP version field as an installation failure.
4. Open **Reference runs…** from Inspector. Confirm the plugin connection is shown, then select a harmless test reference. A connection badge verifies availability; a run needs its own recorded start/end and the browser needs a readable log interval.
5. Run the existing source tests from the extracted project:

   ```sh
   python3 -m unittest discover -s tests -v
   ```

   The suite has **55 tests** using synthetic temporary state. It does not use your real conversation history.

## 6. Test the complete workflow

Use a disposable event website with a homepage and a signup form, in a local project Codex can edit. Do not use a production form or real personal data. This story starts with normal registration and then changes the event to a waitlist. It can be performed in one conversation or two; use a new conversation for the continuation check below.

### A. Create one reference across two pages

1. Open the homepage. Hold your configured Capture shortcut and draw two marks. Release the shortcut.
2. **Click a numbered button to open its note.** Paste the following instructions and explicitly close each note to save it:
   - **Note 1:** `Move the event date and location below the homepage heading so they are easy to find.`
   - **Note 2:** `Change the button label to Reserve my seat and link it to the signup page.`
3. In Inspector, select that reference and turn on **Append screenshots**. Open the signup page and start another round with the Capture shortcut. Add two marks:
   - **Note 3:** `Explain that the email address will only be used for event-related updates.`
   - **Note 4:** `After a successful submission, display Registration confirmed.`
4. Close the notes. Check that the carousel has two screenshots in **one reference**. The Marks list follows the selected screenshot; mark numbers do not restart. Turn Append off when you want the next capture to create a different reference.

### B. Hand it to Codex and review run 1

Use **Copy JSON URL** for the selected reference and paste it into a fresh Codex conversation with this prompt:

> Update this event project using the four notes in the reference. Then check the full flow from the homepage to the signup result. Briefly tell me what you changed. Keep your replies and the website copy in English.

The installed skill instructs Codex to read the current notes and prior runs, retain the exact note revision, and report its ending. When the response finishes:

- Verify the homepage button and signup confirmation on the actual website.
- **Open Inspector → Reference runs… → View details.** Use All references to return to the list.
- Click a picture to enlarge it; use the carousel to inspect both screenshots.
- Scroll the conversation on the right. **You** and **Codex** must be distinguished. Run 1 must show its actual state and report, not an assumed completion.
- Record the displayed note version. Do not expect a fixed number: captures and edits use the existing counter.

### C. Change notes, then continue with run 2

The event is now full. Edit only these two notes and **close each note to save**:

- **Note 2:** `The event is full. Change the button label to Join the waitlist. Keep it linked to the signup page.`
- **Note 4:** `After submission, display You are on the waitlist. Do not promise a confirmed place anywhere on the page.`

Refresh Reference runs. It should show the saved changes at their recorded times. Keystrokes while the editor is open are not separate note-history entries. Run 1 and its report stay intact.

Hand the **same reference link** to a new Codex conversation:

> Continue from the previous run. Read the latest instructions and tell me which notes changed before editing the project. Keep everything else unchanged, and check that the button and submission result reflect that the event is full. Keep your replies and the website copy in English.

Before editing, Codex should identify notes 2 and 4 as changed relative to the prior reported revision. After it finishes, check the website's button and form result, then refresh Reference runs:

| Check | Expected observation |
| --- | --- |
| Run order | Run 1 remains, the saved note changes remain, and run 2 is recorded separately. |
| Note version | The reported version is corroborated only when SeeThis delivered that version strictly after this run started and before it ended. Otherwise it stays unverified/unknown. |
| Timeline position | Saved changes are labelled before hand-in, during run or after run relative to the selected run. |
| Editing during a run | The change is highlighted with a reminder that Codex will not see it automatically; tell Codex or hand in the reference again. |
| Current JSON | It contains current notes and per-mark `note_revision`, not note history. |
| History | Older run records and saved note changes remain available on the page. |

A matching version/time is **not proof of which reader fetched the reference**. “Agent reported (unverified)” and “Unknown” are valid outcomes when evidence is absent; do not change them to completion for a recording.

### D. Optional interruption and takeover check

Start a small test run, pause/interrupt its old conversation, and hand the reference to another conversation with **“Take over the previous run.”** If the old run still appears in progress, confirm that you have paused it when asked. The agent should find the recent unfinished run and complete the existing two-step handoff without asking you to type IDs. The page must retain the old log segment and show the new segment. The plugin records the switch; it does not stop the old process for you.

A completed run being continued (part C) is different from an unfinished run being handed over (part D). A stop without an explicit report is **stopped-without-end**; an interruption is **interrupted**. Neither means the work passed acceptance.

## What has been verified

- The exported plugin runtime, manifest, MCP configuration, skill and tests match the documented source snapshot. The public source suite passes **55 tests**.
- The original demo host had native plugin 0.4.1 installed, its four hooks reviewed/trusted with timeout 1 second, and an exact helper binding. These are historical checks, not a claim about a new user's installation.
- The downloadable app and DMG have accepted Apple notarization, stapled tickets and passing signature/Gatekeeper checks. The app binaries here are identical to the SeeThis hackathon release, not rebuilt for this repository.
- A clean install on another Mac, fresh live hook delivery, and a complete post-fix two-run recording still require the manual checks above. Unit tests, a green connection badge and the edited demo video do not replace that acceptance.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| `codex` is missing or has no `plugin` command | Use the desktop installation's supported CLI and verify its help/version. |
| No MCP tools in an existing conversation | Start a fresh conversation after native installation. Check Python availability and native plugin enable state. |
| Hooks show Modified or Untrusted | Review the four exact new definitions in native `/hooks`; old trust is not proof of new trust. |
| A run is missing after a hook error | Restore the correct installed target/Python and check trust. Fail-open intentionally does not retry or reconstruct old prompts. |
| `plugin_not_connected` or `plugin_source_changed` | Run the installed 0.4.1 helper with `--connect` again. Do not edit the descriptor or cache manually. |
| `plugin_bridge_unavailable_in_sandbox_build` | Use the separately delivered 0.1.6 local demo build, not the Store build. |
| Page link no longer works | Reopen Reference runs from the running app's Inspector. |
| Missing/truncated/unavailable log interval | Keep it unavailable; do not substitute another conversation file or claim completion. |

## Data and limits

- **SeeThis** owns reference pictures, current notes, saved note history and bounded delivery observations. **The plugin** owns run metadata, short agent summaries and log locations in local JSON. The SeeThis app serves the local page and invokes a short-lived helper; no extra plugin server or background watcher is started.
- Plugin state is under `~/.local/share/seethis-agent-demo/`. It stores reference IDs and bounded log positions, not reference capabilities, prompt copies or conversation-log copies. Original Codex logs are read-only.
- The page reads registered log intervals under `~/.codex/sessions` on demand, within a 4 MiB bound. It displays the text transiently, with no-store responses and no browser storage. Missing, truncated or unreadable intervals stay unavailable. Reference capability URLs in the displayed messages are redacted.
- Shareable reference JSON does not grant access to the local run viewer. The viewer uses a separate ephemeral capability created by Inspector, with loopback host/origin validation. Do not publish either private URL.
- At **256 delivery observations per reference**, SeeThis stops adding observations and shows **Delivery records full**; `/r/` delivery still succeeds and old observations are kept. This differs from the **512 saved note-change** limit, which can reject another note save. A missing delivery observation cannot verify a run's note version.
- Hook failure stops that hook invocation without another callback or retry; Codex continues. No history is reconstructed from old prompts to hide a missed callback.

## Uninstall

```sh
codex plugin remove seethis-runs@seethis-agent-demo-local --json
codex plugin marketplace remove seethis-agent-demo-local --json
```

This removes the native plugin/marketplace registration without deleting
`~/.local/share/seethis-agent-demo/` or original Codex sessions. The retained
bridge descriptor may then point to a removed helper; reconnect after a later
installation. Removing the plugin does not uninstall SeeThis. No `notify`, other
plugin, App Store 0.1.5 or original-log edits are part of this workflow.

## Source and release provenance

This public repository is a clean, allowlisted source export. It excludes private development history, local sessions, reference data and recordings. [`SOURCE-PROVENANCE.json`](SOURCE-PROVENANCE.json) maps the unchanged plugin implementation to source commit `53c640dbb518ab7dca88d7cac0f5df1d4a09c5c2`. Public installation documentation and licensing were added for this distribution.

The SeeThis app was built from `8b3910667622840b46d77c0e55ec70f17767c98f`. Its [public source mapping](https://github.com/amingclawdev/seethis/releases/download/v0.1.6-hackathon-demo.1/PUBLIC-SOURCE-MAPPING.json) and release manifest describe the byte-matching export. The original [SeeThis prerelease](https://github.com/amingclawdev/seethis/releases/tag/v0.1.6-hackathon-demo.1) remains available.
