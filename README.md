# DroidPilot

An LLM agent that runs **on** your Android phone and drives it. It reads the
screen as structured data, taps, types and swipes, and can be handed whole
tasks from a laptop over MCP. Unrooted: no root, no Shizuku.

```bash
droidpilot run "What Android version is this phone running?"
# the agent calls device_info, reads "Android 12", answers, and stops:
# one step, recorded to artifacts/runs/ and verifiable with `droidpilot verify`
```

> **This is a full-control agent. Run it on a phone you treat as expendable.**
> It has a shell, your SMS, your camera and your files. See [Safety](#safety).

---

## Why it is interesting

| | |
|---|---|
| **13 ms screen reads** | A custom AccessibilityService ([`android/bridge`](android/bridge)) reads the screen in ~13 ms, against ~220 ms for uiautomator2 and ~2,540 ms for the `uiautomator dump` CLI, and *pushes* an event when the screen changes instead of being polled. [ACCESSIBILITY.md](docs/ACCESSIBILITY.md) |
| **Shell privilege, unrooted** | Termux connects adb to the phone's own adbd over loopback, so the phone drives itself as uid 2000. One Android dialog, once. [ARCHITECTURE.md](docs/ARCHITECTURE.md#the-privilege-trick) |
| **Screens as data, not pixels** | A ~70 KB view hierarchy becomes a 1–3 KB list of typed elements. No vision model in the loop. |
| **Packs keep cheap models cheap** | 102 tools in 6 packs; only `core` (37) loads, about 4,000 schema tokens per turn instead of 9,500. The agent widens its own surface with `use_tools(pack)`. |
| **Taps are judged by target** | "Send", "Pay now", "Log out" and typing into a comment box are refused unless the operator allows that rule for the run, whatever tool the model used. |
| **It notices when it is stuck** | The same call on an unchanged screen gets a warning, then ends the run, instead of burning the step budget. |
| **Delegate, don't proxy** | A laptop sends one goal; a cheap model on the phone runs the 30 steps against localhost. One expensive turn instead of thirty. |

Measured on a realme narzo 50 Pro (Android 14) and a Samsung M21 (Android 12).
Every number has its method in [BENCHMARKS.md](docs/BENCHMARKS.md).

---

## Install

On the phone, in [Termux](https://github.com/termux/termux-app/releases)
(the GitHub build, not the Play Store one: the add-ons need matching signatures):

```bash
curl -sL https://raw.githubusercontent.com/Arnavvs/droidpilot/main/scripts/bootstrap_phone.sh | bash
```

It installs the packages, performs the adb self-connect, waits for you to tap
**Allow**, installs DroidPilot, and runs `doctor` to prove the chain works.
Full walkthrough, including the reboot caveat: [SETUP-PHONE.md](docs/SETUP-PHONE.md).

Optional, for the 13 ms backend (needs a JDK and the Android SDK on a laptop):

```bash
cd android && ./build.sh install
```

### Point it at a model

```bash
export OPENROUTER_API_KEY=sk-or-v1-...
export DROIDPILOT_MODEL=deepseek/deepseek-v4-flash-0731
```

or run offline against `llama.cpp` on the phone (`DROIDPILOT_PROVIDER=local`,
`DROIDPILOT_TOOL_MODE=json`). See [MODELS.md](docs/MODELS.md).

---

## Use

```bash
droidpilot doctor                       # check every link in the chain
droidpilot run "<goal>"                 # give it a task, watch it work
droidpilot run --mode readonly "<goal>" # it cannot change anything
droidpilot tools --pack phone           # browse the tool surface
droidpilot tool ui_dump --args '{"limit":10}'   # call one tool, no model
droidpilot runs                         # every run, with verdicts
droidpilot verify latest --expect '<regex>'     # label a run pass/fail
droidpilot macro make latest --name X   # a verified run becomes a guarded macro
droidpilot macro run X                  # replay it with no model; stops on a mismatch
droidpilot serve --host 0.0.0.0         # accept tasks from a laptop
```

### From a laptop, over MCP

```bash
# phone
droidpilot serve --host 0.0.0.0

# laptop
export DROIDPILOT_URL=http://<phone-ip>:8765
export DROIDPILOT_TOKEN=<token printed by serve>
claude mcp add droidpilot -- python bridge/mcp_bridge.py
```

The laptop gets `phone_task` (delegate a goal), `phone_tool` (one call),
`phone_task_status` / `phone_task_stop` / `phone_reply` for background tasks,
and `phone_run_inspect`. Every tool carries MCP annotations: read-only tools are
marked so a client can auto-approve them, and sends, shell and file writes are
marked destructive.

---

## The tool surface

| Pack | Tools | What |
|---|---|---|
| `core` | 37 | Screen reading, tapping, typing, swipes, app launch, deep links, notes and recall, diagnose, hand-back to a person, tool discovery |
| `phone` | 29 | SMS, calls, camera, GPS, sensors, torch, TTS, notifications, Wi-Fi (via Termux:API) |
| `system` | 14 | Battery, network, storage, clipboard, waiting for a screen |
| `learn` | 10 | Teach the agent an app it has never seen: explore, diff, propose and save selectors |
| `files` | 8 | Read, write, search and move files across both filesystems |
| `shell` | 4 | Arbitrary commands at both privilege levels |

Full catalogue: [TOOLS.md](docs/TOOLS.md). Adding a tool is one decorated
function; adding an app is a selector file plus a module. See
[CONTRIBUTING.md](CONTRIBUTING.md).

---

## How a run stays honest

- **See, act, see again.** Every tap goes by a ref from the last read
  (`ref="<ver>_<i>"`), and the element is found again on a fresh read before the
  tap. If it moved, the tap follows; if it is gone, covered or ambiguous, the tap
  is refused with the reason.
- **Text entry is verified.** Text goes in through the bridge (any Unicode) and
  is read back from the field; plain `adb input text` crashes on Devanagari and is
  only an ASCII fallback.
- **Verification is a program, not a vibe.** A task can declare checks (answer
  regex, text reached, final app) and each run is labelled pass, fail or
  inconclusive automatically.
- **Old results become one-line capsules** that say what was observed, never
  "success", so the model's own history cannot mislead it later.
- **Everything is recorded**, before compaction, as JSONL, with a decision record
  per step (candidates, choice, outcome).

Design and the measurements behind it: [ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Safety

- **Use an expendable phone.**
- `phone_sms_send` and `phone_call` are **denied by default** even in `auto`
  mode, because they reach real people and cost money. Enable them by name.
- **Taps are judged by what they hit** (`policy/writes.json`): sends, payments
  and account-level actions are refused unless allowed for the run, and typing
  into a comment or message box counts as a send.
- **A checkpoint stops the run.** Login, 2FA, CAPTCHA, "unusual activity" and
  "action blocked" screens end the run with `human_required`, whatever the model
  intended.
- The HTTP server binds loopback unless you pass `--host`, and then requires a
  bearer token. The accessibility bridge requires its own token, readable only
  by adb shell, and refuses browser-originated requests.
- `policy/reads.py` holds hook points for rate-limiting reads. The default build
  counts nothing; plug in your own limiter if you automate an app with limits.

Out of scope by design: CAPTCHA solving, device-identity spoofing, root
exploits, consent-dialog bypass, and anything meant to make automation look
human to defeat a platform's enforcement. Automating an app does not change
what its terms allow.

---

## Tests

```bash
pip install -e . pytest
python -m pytest -q          # 238 tests, no phone needed
```

## Credits

The device layer, structured-UI extraction and selector registry come from
[MobileAgentMCP](https://github.com/Arnavvs/MobileAgentMCP). DroidPilot is the
open-source core of a larger private build; app-specific packs are not included.

MIT licensed.
