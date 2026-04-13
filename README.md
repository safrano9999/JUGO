# JUGO! 🇭🇷🇷🇸🇪🇸

LLMs have a personality — and it's shaped by language.

The same model answering in German tends to be formal, cautious, stiff.
In Croatian or Spanish it's looser, more direct, more chill.
Not because it's a different AI — but because language sets the tone,
just like it does for humans.

JUGO is a browser wrapper for Codex CLI (or any other LLM running in a terminal).
You type in German (or English), JUGO translates via DeepL into the target language,
sends it into the tmux pane, captures the response, and translates it back.
The detour through another language shifts the vibe of the model —
without you having to actually speak it. 😄

## Why does this work? 🧠

Language models are trained on massive text corpora.
The German portion of that data skews academic, bureaucratic, technical.
The Croatian or Spanish portion has a different composition —
more everyday language, less formal register.
The model doesn't "think" in languages, but it follows the statistical patterns of the input.
More relaxed language in → more relaxed answer out.

Croatian and Spanish both work great for this.
Croatian tends to get you a pragmatic, no-nonsense vibe. 🇭🇷
Spanish gets you something warmer and more conversational. 🇪🇸
Try both and see what fits your workflow.

## Setup ⚙️

```bash
# Install dependencies
pip install -r requirements.txt

# Create local env file
cp .env_example .env

# Set your DeepL API key (Free tier: 500k chars/month — deepl.com/pro-api)
# DEEPL_KEY=xxxx-xxxx:fx
# JUGO_PORT=840

# Start the server
python3 server.py
```

The server always binds to `0.0.0.0`. Change `JUGO_PORT` in `.env` if needed.

Open `http://localhost:840` in your browser, tmux with Codex on the side. Done.

## Requirements

- tmux running with Codex (or any LLM CLI) open in a pane
- DeepL Free API key (ends in `:fx`)

## Workflow 🔄

1. Select your tmux pane from the dropdown
2. Choose target language — Croatian or Spanish recommended
3. Type your message → **Ctrl+Enter** to translate
4. Hit **Deploy** — text goes straight into the terminal, Enter is sent automatically
5. Response comes back in the target language → **Translate ↓** brings it back to you
