# Honcho Memory — Install Guide for LLM Agents

This document is written for an LLM or coding agent to follow. Read it top to
bottom, ask the user for any missing information, then execute each step. When
a step fails, **pause and ask before continuing**. Every step includes a
verification so you know it worked before moving on.

---

## 1. Gather required inputs

Ask the user for each of these. Do not proceed until every required item is known.

| Input | Required | How the user obtains it |
|---|---|---|
| Open WebUI base URL | Yes | The URL they open in a browser, e.g. `http://localhost:3000` |
| Open WebUI admin API key | Yes | **Settings → Account → API Keys → Create API Key** |
| Honcho API key | Yes | From [honcho.dev](https://honcho.dev) — create a workspace, copy the key |
| Honcho base URL | No | Defaults to `https://api.honcho.dev` |
| Honcho workspace ID | No | Defaults to `openwebui` |
| Identity salt | No | Auto-generated if not provided (≥32 random characters) |

### Prompt template

> I need a few things to install the Honcho Memory plugin:
>
> 1. Your **Open WebUI URL** (e.g. `http://localhost:3000`)
> 2. An **admin API key** from Open WebUI (Settings → Account → API Keys)
> 3. Your **Honcho API key** (from honcho.dev)
>
> Optionally: a custom Honcho base URL or workspace ID. I'll use defaults if
> you skip those.

---

## 2. Pre-flight: check the dist files exist

These must be present — they're the plugin files the install script uploads.

```bash
ls -1 dist/honcho_memory.py dist/honcho_memory_actions.py dist/honcho_memory_tools.py
```

Expected: three paths printed, no errors. If any are missing, stop and run:

```bash
python scripts/generate_plugins.py
```

Then verify again.

---

## 3. Verify Open WebUI is reachable

```bash
curl -s -o /dev/null -w "%{http_code}" "<BASE_URL>/api/v1/auths/"
```

| Response | Meaning | Action |
|---|---|---|
| `200` | Open WebUI is up | Continue |
| `000` | Connection refused | Wrong URL or Open WebUI is down. Ask the user to confirm. |
| `3xx` | Redirect | Follow it: `curl -sL -o /dev/null -w "%{http_code}" "<BASE_URL>/api/v1/auths/"` |
| `5xx` | Server error | Open WebUI is starting up. Wait 10s and retry. |

---

## 4. Verify the admin API key works

```bash
curl -s -w "\n%{http_code}" -H "Authorization: Bearer <ADMIN_API_KEY>" \
  "<BASE_URL>/api/v1/functions/" | tail -1
```

| Response | Meaning | Action |
|---|---|---|
| `200` | Key is valid, user is admin | Continue |
| `401` | Invalid key | Ask the user to re-copy it from Settings → Account → API Keys |
| `403` | Valid key but not admin | The user needs an admin account. Cannot proceed. |

---

## 5. Set environment variables on the Open WebUI server

Generate a salt if the user didn't provide one:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

The user must add these to the Open WebUI server's environment:

```
ENABLE_PIP_INSTALL_FRONTMATTER_REQUIREMENTS=true
HONCHO_API_KEY=<honcho-api-key>
HONCHO_BASE_URL=<honcho-base-url-or-default>
HONCHO_WORKSPACE_ID=<workspace-id-or-default>
OPENWEBUI_HONCHO_IDENTITY_SALT=<salt>
```

Ask the user: **"How do you run Open WebUI — Docker, docker-compose, systemd, or something else?"**

Then give the exact instructions:

- **Docker run**: Add each variable as `-e VAR=value` to the `docker run` command.
- **docker-compose**: Add each under the `environment:` key in `docker-compose.yml`.
- **Systemd**: Add `Environment=VAR=value` lines under `[Service]` in the unit file.
- **Manual / shell**: Export each in the shell before starting Open WebUI.

After setting the variables, tell the user to **restart Open WebUI**. Then verify
it came back up by repeating step 3.

---

## 6. Run the install script

```bash
python scripts/install.py \
  --base-url <BASE_URL> \
  --api-key <ADMIN_API_KEY>
```

If the Honcho workspace isn't the default `openwebui`, add `--workspace-id`.

### Expected success output

```
✓ Created function honcho_memory
✓ Created function honcho_memory_actions
✓ Created tool honcho_memory_tools

Done. The Honcho Filter should now appear in chat settings and Tools in Workspace.
```

If components already exist you'll see `✓ Updated ...` instead — that's also
success.

### Failure modes

| Output | Meaning | Action |
|---|---|---|
| `✗ Missing dist/...` | Dist files not generated | Run `python scripts/generate_plugins.py` and retry |
| `ConnectionError` / `Connection refused` | Open WebUI unreachable | Retry step 3 |
| `401` / `403` | Admin key invalid | Retry step 4 |
| `ReadTimeout` after >30s | `honcho-ai` pip install in progress | Wait 60s and retry — Open WebUI is pulling the package |
| `✗ Failed to install ...` with HTTP error | Server-side problem | Check Open WebUI server logs; the `requirements:` field triggers pip |

### Dry run (safe preview)

```bash
python scripts/install.py --base-url <BASE_URL> --api-key <ADMIN_API_KEY> --dry-run
```

Expected:
```
[DRY RUN] Would CREATE or UPDATE function honcho_memory from honcho_memory.py
[DRY RUN] Would CREATE or UPDATE function honcho_memory_actions from honcho_memory_actions.py
[DRY RUN] Would CREATE or UPDATE tool honcho_memory_tools from honcho_memory_tools.py
```

---

## 7. Verify each component was installed

### 7a. Filter function

```bash
curl -s -H "Authorization: Bearer <ADMIN_API_KEY>" \
  "<BASE_URL>/api/v1/functions/id/honcho_memory" | python3 -c "
import json, sys
f = json.load(sys.stdin)
print(f['id'], f.get('type','?'), '—', 'OK' if f.get('content') else 'EMPTY')
"
```

Expected: `honcho_memory filter — OK`

If `EMPTY`: the function was created but content wasn't uploaded. Re-run step 6.

### 7b. Actions function

```bash
curl -s -H "Authorization: Bearer <ADMIN_API_KEY>" \
  "<BASE_URL>/api/v1/functions/id/honcho_memory_actions" | python3 -c "
import json, sys
f = json.load(sys.stdin)
print(f['id'], f.get('type','?'), '—', 'OK' if f.get('content') else 'EMPTY')
"
```

Expected: `honcho_memory_actions action — OK`

### 7c. Tools

```bash
curl -s -H "Authorization: Bearer <ADMIN_API_KEY>" \
  "<BASE_URL>/api/v1/tools/id/honcho_memory_tools" | python3 -c "
import json, sys
t = json.load(sys.stdin)
print(t['id'], '—', 'OK' if t.get('content') else 'EMPTY')
"
```

Expected: `honcho_memory_tools — OK`

### 7d. Memory UI route replacement (confirms env vars took effect)

The Honcho filter replaces Open WebUI's built-in `/api/v1/memories` routes at
load time. If `HONCHO_API_KEY` is set, the memories endpoint returns Honcho
data. If it's missing, it falls back to ChromaDB.

```bash
curl -s -H "Authorization: Bearer <ADMIN_API_KEY>" \
  "<BASE_URL>/api/v1/memories/" | python3 -c "
import json, sys
data = json.load(sys.stdin)
# Honcho-backed memories have ids like 'honcho_0', 'honcho_1'.
# ChromaDB-backed memories have UUID-style ids.
honcho_style = all(
    isinstance(m, dict) and m.get('id', '').startswith('honcho_')
    for m in data
) if isinstance(data, list) and data else None
if honcho_style is True:
    print('OK: memories endpoint is Honcho-backed')
elif honcho_style is False:
    print('WARNING: memories endpoint returned non-Honcho data — HONCHO_API_KEY may not be set')
else:
    print('OK: memories endpoint responded (no data yet, expected for new install)')
"
```

Expected: `OK` in the output.

If you get `WARNING`: the `HONCHO_API_KEY` env var may not be set or the
filter may not have loaded. Check:
- The variable is spelled exactly `HONCHO_API_KEY` (not `HONCHO_KEY`, etc.)
- Open WebUI was restarted after setting it
- Open WebUI server logs for "Honcho: replaced all 7" or "Honcho: failed to replace"

---

## 8. Attach the filter to models

Ask the user: **"Which models should have memory? Give me their model IDs, or
say 'all' and I'll list them for you."**

If they want to list models:

```bash
curl -s -H "Authorization: Bearer <ADMIN_API_KEY>" \
  "<BASE_URL>/api/v1/models/" | python3 -c "
import json, sys
models = json.load(sys.stdin)
for m in models.get('data', models if isinstance(models, list) else []):
    print(f\"{m['id']:40s} {m.get('name', '')}\")
"
```

For each model the user picks, add the filter:

```bash
MODEL_ID="<model-id>"

# Fetch current config, add honcho_memory to filter_ids and default_filter_ids
curl -s -H "Authorization: Bearer <ADMIN_API_KEY>" \
  "<BASE_URL>/api/v1/models/$MODEL_ID" | python3 -c "
import json, sys
m = json.load(sys.stdin)
info = m.get('info', m) if isinstance(m, dict) else {}
filters = list(set(info.get('filter_ids') or []))
defaults = list(set(info.get('default_filter_ids') or []))
if 'honcho_memory' not in filters:
    filters.append('honcho_memory')
if 'honcho_memory' not in defaults:
    defaults.append('honcho_memory')
info['filter_ids'] = filters
info['default_filter_ids'] = defaults
# Wrap back into the model update shape
if 'info' in m:
    m['info'] = info
else:
    m.update(info)
print(json.dumps(m))
" > /tmp/model_update.json

# Apply
curl -s -X POST -H "Authorization: Bearer <ADMIN_API_KEY>" \
  -H "Content-Type: application/json" \
  -d @/tmp/model_update.json \
  "<BASE_URL>/api/v1/models/$MODEL_ID/update" | python3 -c "
import json, sys
m = json.load(sys.stdin)
info = m.get('info', m)
filters = info.get('filter_ids', [])
print('OK: filter_ids =', filters) if 'honcho_memory' in filters else print('FAILED')
"
```

Also tell the user to attach **Honcho Memory Tools** in the model's Tools
section in the admin panel. There's no REST endpoint for tool-to-model
attachment in Open WebUI 0.9.6, so this must be done in the UI.

---

## 9. End-to-end smoke test

Tell the user:

> 1. Open a **new chat** with a model that has Honcho enabled
> 2. Click the `[Honcho Memory]` chip near the chat input to toggle it on
>    (it appears at the bottom of the input area)
> 3. Send: *"My name is Alice and I live in Toronto"*
> 4. Send a follow-up: *"What's my name and where do I live?"*
> 5. The model should recall Alice and Toronto

If the model doesn't recall:

1. Check the `[Honcho Memory]` chip was active (it highlights when on)
2. Go to **Settings → Personalization → Memory** — toggle it on if off
3. Check the server logs for Honcho errors (`openwebui_honcho` or `honcho`)

---

## 10. Troubleshooting

### Common failures

| Symptom | Likely cause | How to check |
|---|---|---|
| `[Honcho Memory]` chip not visible in chat | Filter not attached to the model | Admin Panel → Models → model → Filter IDs must include `honcho_memory` |
| Chip visible but model doesn't recall | Per-chat toggle is off | Click the chip in the chat input area |
| Model recalls nothing across all chats | Global memory toggle is off | Settings → Personalization → Memory → toggle ON |
| "Honcho memory is disabled for this chat" | Filter ID mismatch | Verify `OPENWEBUI_HONCHO_FILTER_ID` matches the function ID in Admin Panel → Functions |
| "Honcho memory is temporarily unavailable" | Honcho API unreachable | Check `HONCHO_API_KEY` is set, Honcho is up, network egress from Open WebUI server |
| "Honcho memory is not configured" in settings | `HONCHO_API_KEY` env var missing | Check server environment, restart Open WebUI |
| Memory UI (Settings → Personalization) shows old ChromaDB data | Route replacement didn't run | Server logs should say "replaced all 7 /api/v1/memories route handlers"; if not, check `HONCHO_API_KEY` |
| Install script prints `✗ Missing dist/...` | Dist files not generated | Run `python scripts/generate_plugins.py` first |
| Install script timeout (>30s) | `honcho-ai==2.1.2` pip install on server | Wait and retry; check server has internet access to PyPI |

### Docker-specific

**Checking server logs:**

```bash
docker logs <container-name> 2>&1 | grep -i honcho
```

Look for:
- `Honcho: replaced all 7 /api/v1/memories route handlers` — good
- `Honcho: replaced only X of 7` — some routes missing, may still work
- `Honcho: failed to replace` or tracebacks — misconfiguration

**Verifying env vars inside the container:**

```bash
docker exec <container-name> env | grep HONCHO
```

Expected: `HONCHO_API_KEY`, `HONCHO_BASE_URL`, `HONCHO_WORKSPACE_ID` all present.

**Restarting:**

```bash
docker restart <container-name>
```

Then wait for the health check. Confirm with step 3.

### If `honcho-ai` pip install fails

Open WebUI runs `pip install honcho-ai==2.1.2` when it first loads the plugin
(triggered by the `requirements:` frontmatter field). If this fails:

1. Check the server has internet access: `docker exec <container> pip install honcho-ai==2.1.2`
2. If the server is air-gapped, pre-install `honcho-ai==2.1.2` in the image/venv
3. Check `ENABLE_PIP_INSTALL_FRONTMATTER_REQUIREMENTS=true` is set

### If everything looks correct but memory still doesn't work

Run a debug verification — call the memory tool directly:

```bash
curl -s -H "Authorization: Bearer <ADMIN_API_KEY>" \
  "<BASE_URL>/api/v1/memories/" | python3 -m json.tool | head -20
```

If you see UUID-style IDs, Honcho isn't backing the memory endpoint. If you see
`honcho_0`-style IDs, Honcho is working but the model config or toggles are off.

---

## Quick reference: all env vars

```
ENABLE_PIP_INSTALL_FRONTMATTER_REQUIREMENTS=true  # required
HONCHO_API_KEY=                                    # required
HONCHO_BASE_URL=https://api.honcho.dev             # default
HONCHO_WORKSPACE_ID=openwebui                      # default
OPENWEBUI_HONCHO_IDENTITY_SALT=                    # required, ≥32 chars
OPENWEBUI_HONCHO_FILTER_ID=honcho_memory           # default
OPENWEBUI_HONCHO_TIMEOUT_SECONDS=30                # default
OPENWEBUI_HONCHO_MAX_RETRIES=2                     # default
OPENWEBUI_HONCHO_VERBOSE=false                     # default
```
