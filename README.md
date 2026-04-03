# Turbota Telegram Webhook

Lightweight FastAPI webhook receiver for TURBOTA's Telegram group "Облік".

## What it does
1. Receives all updates from Telegram
2. Filters: only group -1001866962075, only messages mentioning @turbotaautomationbot
3. Writes filtered messages to Base44 entity (TelegramProcessedMessage)
4. Base44 automation fires → agent builds Dilovod/Finmap draft → replies in Telegram

## Deploy on Railway
1. Push this folder to a GitHub repo
2. Railway → New Project → Deploy from GitHub
3. Set env var: BASE44_JWT=<your_jwt>
4. Copy the Railway URL
5. Set Telegram webhook: https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<railway-url>/webhook

## Env vars required
- BASE44_JWT — service role JWT token for Base44 API
