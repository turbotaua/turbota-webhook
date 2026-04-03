# Turbota Telegram Webhook

Lightweight webhook relay: Telegram → Base44 Agent API.

## How it works
- Receives Telegram updates via webhook
- **Group** (Облік): only processes messages with @turbotaautomationbot tag
- **Private**: forwards all messages to the agent
- Sends to Base44 agent via REST API with permanent `api_key`

## Deploy on Railway
1. Connect this repo to Railway
2. Set env vars: `BASE44_API_KEY`, `BASE44_CONV_ID` (optional)
3. Set Telegram webhook: `https://api.telegram.org/bot{TOKEN}/setWebhook?url=https://{RAILWAY_URL}/webhook`
