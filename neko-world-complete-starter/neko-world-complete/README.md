# Neko World — complete starter project

A runnable Flask + vanilla JavaScript AI companion starter. Mochi is the visual avatar; chat is her voice; Soul presets control her speaking style.

## Quick start (Python 3.10+)

```bash
cd backend
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
# Copy .env.example to .env (Windows: copy .env.example .env)
python run.py
```

Open http://127.0.0.1:5000. The default `AI_PROVIDER=mock` works without an API key, so you can test the full UI and avatar protocol immediately.

## Connect an LLM

Set these in `backend/.env`:

```env
AI_PROVIDER=openai_compatible
AI_BASE_URL=https://api.openai.com/v1
AI_API_KEY=your-secret-key
AI_MODEL=your-model-name
```

The adapter uses the OpenAI-compatible Chat Completions API and requests JSON output. It can be configured for OpenAI-compatible services such as DeepSeek or gateways; use the exact base URL/model required by your provider. API credentials stay on the server, never in browser code.

## MySQL

Create a MySQL database and user, then configure:

```env
DATABASE_URL=mysql+pymysql://neko_user:URL_ENCODED_PASSWORD@127.0.0.1:3306/neko_world?charset=utf8mb4
```

SQLite is the default for local testing. Tables are created on startup for this starter; use Alembic migrations before production schema changes.

## API

`POST /api/chat` accepts:

```json
{"conversation_id":null,"message":"I missed you!","mode":"normal","soul_id":"gentle"}
```

The response contains `message`, `conversation_id`, and optional `avatar` action. Supported expressions: neutral, happy, shy, sad, surprised, curious, sleepy, pout. Gestures: none, wave, nod, tilt_head, look_away, heart_gesture. Effects: none, floating_hearts, sparkles, sweat_drop.

## Architecture

- `soul/catalog.py`: selectable personality presets.
- `chat/service.py`: conversation orchestration and provider-independent response shape.
- `providers/`: mock and OpenAI-compatible adapters.
- `avatar/actions.py`: server-side action whitelist and validation.
- `models.py`: persistent conversations, messages, and settings.
- `frontend/app.js`: chat UI and local animation runtime.

Normal mode keeps idle animation local (CSS) and only animates meaningful AI reactions. It does not call the model for every blink or tail movement.

## Before public deployment

This is a functional starter, not a production-secure multi-user product. Add authentication and per-user data isolation, rate limiting, HTTPS, CSRF/origin protections appropriate to your deployment, secret management, database backups, logging/monitoring, and database migrations. The included CSS Mochi is a placeholder character illustration, not the final layered anime artwork or skeletal animation rig. Replace it with properly prepared character layers and an animation runtime when those assets are ready.
