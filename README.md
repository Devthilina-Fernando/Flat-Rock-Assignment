# Flat Rock Technology — Vendor Onboarding Agent

An AI-powered vendor onboarding system that processes supplier documents (PDF, Word, CSV, images), extracts compliance data using GPT-4o, validates against internal procurement policies, and routes vendors for auto-approval or manual review.

---

## Prerequisites

- Python 3.12+
- Docker & Docker Compose (for the containerised setup)
- An OpenAI API key
- A Google Cloud project with the Gmail API enabled (only needed if you want Gmail polling)

---

## Quick Start

### Option 1 — Docker Compose (recommended)

```bash
# 1. Copy the environment template and fill in your values
cp .env.example .env

# 2. Open .env and set OPENAI_API_KEY (and Gmail settings if needed)

# 3. Build and start the stack
docker-compose up --build
```

The app is available at **http://localhost:8000**.

---

### Option 2 — Local (development)

```bash
# 1. Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS / Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy and configure the environment file
cp .env.example .env
# Edit .env — at minimum set OPENAI_API_KEY

# 4. Start the server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

---

## Environment Variables

Copy `.env.example` to `.env` and set the values below.

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | Yes | Your OpenAI API key (`sk-...`) |
| `DATABASE_URL` | No | SQLite path — default `sqlite:///./vendor_onboarding.db` |
| `CHROMA_PERSIST_PATH` | No | ChromaDB directory — default `./chroma_db` |
| `GMAIL_ENABLED` | No | Set `true` to enable Gmail inbox polling |
| `GMAIL_POLL_INTERVAL` | No | Poll frequency in seconds — default `30` |
| `GMAIL_CREDENTIALS_FILE` | No | Path to `credentials.json` — default `./scripts/credentials.json` |
| `GMAIL_TOKEN_FILE` | No | Path to `token.json` — default `./scripts/token.json` |
| `LOG_LEVEL` | No | `DEBUG` / `INFO` / `WARNING` / `ERROR` — default `INFO` |

---

## Gmail Integration Setup

Gmail polling is optional. Skip this section if you only need the manual document upload feature.

### Step 1 — Enable the Gmail API

1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a project (or select an existing one).
3. Navigate to **APIs & Services → Library** and enable the **Gmail API**.

### Step 2 — Create OAuth 2.0 credentials

1. Go to **APIs & Services → Credentials**.
2. Click **Create Credentials → OAuth client ID**.
3. Set the application type to **Desktop app**.
4. Click **Create**, then download the JSON file.
5. Rename the downloaded file to `credentials.json`.

### Step 3 — Place `credentials.json`

Place the file here:

```
Flat-Rock-Assignment/
└── scripts/
    └── credentials.json   ← put it here
```

### Step 4 — Generate `token.json`

Run the app once with `GMAIL_ENABLED=true`. On first start, a browser window will open asking you to authorise access to the Gmail account you want to poll. After you grant access, the token is saved automatically:

```
Flat-Rock-Assignment/
└── scripts/
    └── token.json         ← created automatically after first auth
```

The token refreshes itself on every subsequent run — you do not need to repeat this step.

### Step 5 — Docker path (if using Docker Compose)

When running via Docker, place both files in the `gmail_creds/` folder at the project root. The `docker-compose.yml` mounts that directory into the container.

```
Flat-Rock-Assignment/
└── gmail_creds/
    ├── credentials.json
    └── token.json
```

Update your `.env` to point to the mounted paths:

```env
GMAIL_CREDENTIALS_FILE=./gmail_creds/credentials.json
GMAIL_TOKEN_FILE=./gmail_creds/token.json
```

> **Security note:** Both files contain sensitive credentials. Do not commit them to version control. They are listed in `.gitignore` by default.

---

## Running the Test Pipeline

Submit 5 sample vendor documents and verify the full pipeline:

```bash
python scripts/test_pipeline.py
```

Make sure the server is running before executing this script.

---

## Project Structure

```
app/               Application code (agents, API, DB, services)
frontend/          Single-page web UI (Tailwind + Alpine.js)
scripts/           Utilities, Gmail scripts, credential files
test_data/         Sample vendor documents
chroma_db/         ChromaDB vector store (auto-created)
.env.example       Environment variable template
docker-compose.yml Docker Compose configuration
Dockerfile         Docker image definition
requirements.txt   Python dependencies
```

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check (DB, ChromaDB, OpenAI) |
| `POST` | `/process/manual` | Upload a vendor document |
| `GET` | `/vendors` | List auto-approved vendors |
| `GET` | `/review` | List review queue |
| `POST` | `/review/{id}/decide` | Approve or reject a vendor |
| `GET` | `/events` | Real-time SSE event stream |
