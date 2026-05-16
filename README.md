# Bank Architecture Diagram Analyzer

Internal tool that ingests cloud-architecture diagram images and returns
structured JSON describing components and flows (north-south vs east-west),
plus compliance findings against a fixed rule set.

## Stack
- **Monorepo**: Turborepo + npm workspaces
- **Backend**: Python 3.12, FastAPI, uv, Pydantic v2
- **LLM**: Azure OpenAI gpt-4o (vision)
- **OCR**: Azure AI Document Intelligence (prebuilt-layout)
- **Storage**: Local JSON files (`./data/analyses/<id>.json`)
- **Frontend**: React 18 + TypeScript + Vite, Tailwind, shadcn/ui, TanStack Query

## Setup

```bash
nvm use            # node 20
npm install
cp .env.example .env
# fill in AZURE_OPENAI_* and DOC_INTEL_* (optional — mocks are used if missing)
```

The Python backend uses [uv](https://docs.astral.sh/uv/):

```bash
brew install uv    # or: pipx install uv
cd apps/api && uv sync
```

## Run

```bash
npm run dev        # api on :8000, web on :5173
```

Then open http://localhost:5173 and drag a diagram onto the upload zone.

## Test

```bash
npm run test
npm run lint
```

## Sample curl

```bash
curl -F "file=@data/samples/azure_3_tier_clean.png" \
     http://localhost:8000/api/analyze | jq
```

## Mock mode

If `AZURE_OPENAI_API_KEY` or `DOC_INTEL_API_KEY` are missing, the backend
falls back to canned mock responses for the committed sample diagrams,
so the UI and pipeline run end-to-end without Azure credentials.

## Layout

```
apps/web      React + Vite frontend
apps/api      FastAPI backend
packages/shared   Zod schema + TS types shared with the frontend
data/         Local persistence (analyses/, uploads/, samples/)
```

## Notes / TODO
- Auth: not implemented for MVP. Add Entra ID / OAuth at the FastAPI
  middleware layer before exposing to non-localhost.
- Storage: JSON files under `./data/analyses`. Swap for a real store
  before production.
