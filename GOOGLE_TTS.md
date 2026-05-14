# Google Cloud TTS Setup

Google Cloud Text-to-Speech requires a **Service Account** (not a simple API key). Here's how to get through the Google jungle.

## Step by step

### 1. Open Cloud Console

Go to [console.cloud.google.com](https://console.cloud.google.com) — **not** AI Studio, not Vertex AI.

### 2. Select or create a project

Top-left project dropdown. Use an existing one or create new (e.g. "JUGO").

**Important:** AI Studio and Cloud Console can use different default projects. Make sure you do everything in the **same** project.

### 3. Enable the Text-to-Speech API

- **APIs & Services → Library**
- Search for **"Cloud Text-to-Speech API"**
- Click **Enable**

### 4. Create a Service Account

- **IAM & Admin → Service Accounts**
- **+ CREATE SERVICE ACCOUNT**
- Name: anything (e.g. "jugo-tts")
- No role needed
- Click **Done**

### 5. Download the JSON key

- Click on the service account you just created
- Tab **Keys**
- **ADD KEY → Create new key → JSON**
- A `.json` file downloads

### 6. Add to .env

Base64-encode the JSON and add it to `.env`:

```bash
echo "GOOGLE_TTS_CREDENTIALS=$(base64 -w0 /path/to/downloaded-key.json)" >> .env
```

The app decodes this at runtime and uses it to authenticate with Google Cloud TTS.

## Why not a simple API key?

Google Cloud TTS **does not support API keys** for the SynthesizeSpeech endpoint. Only the voices.list endpoint works with API keys. Synthesis requires OAuth2 credentials (= Service Account).

## Common pitfalls

- **Wrong project**: API enabled in project A, key created in project B → 403. Everything must be in the same project.
- **AI Studio vs Cloud Console**: They look similar but are different sites with different default projects. AI Studio keys (`AQ.Ab8...`) don't work for Cloud TTS.
- **API key vs Service Account**: API keys (`AIzaSy...`) are blocked for TTS synthesis. You need a Service Account JSON.

## Verify

```bash
# Quick test from command line
python3 -c "
import os, base64, json
from google.oauth2 import service_account
from google.cloud import texttospeech

creds = service_account.Credentials.from_service_account_info(
    json.loads(base64.b64decode(os.environ['GOOGLE_TTS_CREDENTIALS']))
)
client = texttospeech.TextToSpeechClient(credentials=creds)
resp = client.synthesize_speech(
    input=texttospeech.SynthesisInput(text='test'),
    voice=texttospeech.VoiceSelectionParams(language_code='en'),
    audio_config=texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3),
)
print(f'OK, {len(resp.audio_content)} bytes')
"
```
