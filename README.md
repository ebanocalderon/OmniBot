# Chatwoot AI Agent Bot (Universal LLM Integration)

A production-ready Python service that acts as an **Agent Bot** for [Chatwoot](https://www.chatwoot.com/). 
It automatically replies to customer messages across **any inbox** using any LLM (Ollama, OpenAI, Anthropic, etc.) via LiteLLM.

```
Customer Message ──► Chatwoot Webhook ──► AI Agent Server (10.0.0.41:8000)
AI Agent Server  ──► Queries LLM (e.g., local Ollama Qwen) ──► Chatwoot Agent Reply
```

---

## Features

- ✅ Works across **any** Chatwoot inbox (Facebook, IG, WhatsApp, Web Widget, etc.)
- ✅ Universal LLM support via LiteLLM (Ollama, OpenAI GPT-4, Anthropic Claude, etc.)
- ✅ Context-aware: maintains conversation history in memory for follow-up questions
- ✅ Optional HMAC-SHA256 webhook signature verification
- ✅ Health check endpoint at `/health`
- ✅ Runs as a systemd service on Ubuntu (auto-restart on crash / reboot)

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.11+ | |
| A running Chatwoot instance | Self-hosted or cloud |
| A Chatwoot Agent Bot | Configured via Rails console or API |
| LLM API Access | Local Ollama, OpenAI API Key, Anthropic API Key, etc. |

---

## Quick Start — Ubuntu Server (10.0.0.41)

### 1. SSH into the server

```bash
ssh user@10.0.0.41
```

### 2. Clone the repository

```bash
git clone https://github.com/ebanocalderon/OmniBot.git
cd OmniBot
```

### 3. Run the automated deployment script

```bash
sudo bash deploy/deploy.sh
```

This will:
- Install system dependencies (git, python3, python3-venv)
- Create a dedicated `bridge` system user
- Clone/update the repo to `/opt/chatwoot-bridge`
- Create a Python virtual environment and install all packages
- Copy `.env.example` → `/opt/chatwoot-bridge/.env` (if not already present)
- Install and enable the `chatwoot-bridge` systemd service
- Start the service immediately

### 4. Edit the configuration

```bash
sudo nano /opt/chatwoot-bridge/.env
```

Fill in all the required values:

```env
CHATWOOT_BASE_URL=http://localhost:3000
CHATWOOT_API_TOKEN=your_agent_bot_access_token
CHATWOOT_ACCOUNT_ID=1

LLM_MODEL=ollama/qwen:3.50.8b
LLM_API_BASE=http://localhost:11434
LLM_API_KEY=

SERVER_HOST=0.0.0.0
SERVER_PORT=8000
```

### 5. Restart and verify

```bash
sudo systemctl restart chatwoot-bridge
curl http://10.0.0.41:8000/health
# Expected: {"status":"ok"}
```

### 6. Add the Bot to Chatwoot

In Chatwoot, an Agent Bot is an entity that listens to conversations and can reply. 
You can create an Agent Bot using the Chatwoot Rails console:

```ruby
# On your Chatwoot Server
RAILS_ENV=production bundle exec rails c

# Create the bot
bot = AgentBot.create!(
  name: "AI Assistant",
  description: "Helpful AI",
  outgoing_url: "http://10.0.0.41:8000/chatwoot/webhook"
)

# Generate an Access Token for the bot
bot_access_token = bot.access_token.token
puts "Your bot token is: #{bot_access_token}"

# Add the bot to an Inbox (replace 1 with your inbox_id)
AgentBotInbox.create!(inbox_id: 1, agent_bot_id: bot.id)
```

Use the `bot_access_token` as your `CHATWOOT_API_TOKEN` in the `.env` file.

---

## Manual Local Development Setup

### 1. Clone & create virtual environment

```bash
git clone https://github.com/ebanocalderon/OmniBot.git
cd OmniBot

python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env  # Linux/macOS
# copy .env.example .env  # Windows
```

Edit `.env` and fill in all values.

### 4. Run the server

```bash
python run.py
```

---

## Useful Service Commands

```bash
# Check status
sudo systemctl status chatwoot-bridge

# View live logs
sudo journalctl -u chatwoot-bridge -f

# View recent logs (last 100 lines)
sudo journalctl -u chatwoot-bridge -n 100 --no-pager

# Restart
sudo systemctl restart chatwoot-bridge

# Stop
sudo systemctl stop chatwoot-bridge

# Disable auto-start on boot
sudo systemctl disable chatwoot-bridge
```
