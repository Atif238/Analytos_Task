```markdown
# LangGraph Invoice Processing Agent (Demo)

This repository contains a self-contained, simulated LangGraph-style invoice processing agent that demonstrates:

- Deterministic & non-deterministic stages
- Bigtool-based tool selection (OCR / Enrichment / ERP / DB / Email)
- MCP client routing between COMMON and ATLAS
- Checkpoint creation (HITL) and persistent checkpoint storage in SQLite
- Human Review API to list pending checkpoints and accept/reject decisions
- Resume execution after human decision
- Streamlit-based human review UI

This is a demo implementation (Python) that simulates external services (OCR, ERP, enrichment) and focuses on workflow orchestration, state persistence, and HITL flow.

What you'll find:
- workflow.json — LangGraph Agent configuration
- app/ — Python implementation
  - main.py — Orchestrator that runs the workflow end-to-end and waits at HITL checkpoint
  - bigtool.py — BigtoolPicker: chooses a tool from a pool based on capability/context
  - mcp_clients.py — Simulated COMMON and ATLAS client abilities
  - db.py — SQLite persistence for invoices and checkpoints
  - models.py — Dataclasses/models for state blobs
  - human_api.py — FastAPI app exposing human-review endpoints (list pending, decision)
  - streamlit_ui.py — Streamlit human-review UI
- sample_invoice.json — Example invoice payload that triggers a HITL path (low match score)
- requirements.txt — Python dependencies

Quick start (local):
1. Create a virtualenv and install deps:
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt

2. Run the orchestrator (this starts the human-review API and runs the workflow):
   python app/main.py

3. In another terminal, run the Streamlit UI:
   streamlit run app/streamlit_ui.py

The orchestrator will:
- Execute the stages up to MATCH_TWO_WAY
- If match fails, create checkpoint, persist state, and pause
- The human reviewer can inspect pending checkpoints and ACCEPT/REJECT via the Streamlit UI or direct API
- After ACCEPT, the orchestrator resumes and completes the workflow

Notes:
- This demo uses simulated abilities and simple heuristics for match score so it can run offline.
- The DB used is SQLite (demo.db) stored next to the repository.
```