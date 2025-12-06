from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Any, Dict
from . import db as dbmod
import uuid
import threading
import logging

app = FastAPI()

# In-memory resume event registry used by orchestrator to wait/resume per checkpoint
# orchestrator will register an Event object for expected checkpoint_id.
resume_registry = {}
registry_lock = threading.Lock()

class DecisionRequest(BaseModel):
    checkpoint_id: str
    decision: str  # ACCEPT or REJECT
    notes: str = ""
    reviewer_id: str

class DecisionResponse(BaseModel):
    resume_token: str
    next_stage: str

@app.get("/human-review/pending")
def list_pending():
    pending = dbmod.list_pending_checkpoints()
    # Return shaped items according to workflow.json human_review_api_contract
    items = []
    for p in pending:
        state = p["state_blob"]
        invoice_id = p["invoice_id"]
        payload = state.get("payload", {})
        items.append({
            "checkpoint_id": p["checkpoint_id"],
            "invoice_id": invoice_id,
            "vendor_name": payload.get("vendor_name"),
            "amount": payload.get("amount"),
            "created_at": p["created_at"],
            "reason_for_hold": p["paused_reason"],
            "review_url": p["review_url"],
            # include state_blob for richer UI (safe JSON already stored)
            "state_blob": state
        })
    return {"items": items}

@app.post("/human-review/decision", response_model=DecisionResponse)
def decision(req: DecisionRequest):
    # Validate checkpoint
    pending = dbmod.get_checkpoint_state(req.checkpoint_id)
    if not pending:
        raise HTTPException(status_code=404, detail="Checkpoint not found")
    decision = req.decision.upper()
    if decision not in ("ACCEPT", "REJECT"):
        raise HTTPException(status_code=400, detail="decision must be ACCEPT or REJECT")
    resume_token = str(uuid.uuid4())
    next_stage = "RECONCILE" if decision == "ACCEPT" else "MANUAL_HANDOFF"
    # update checkpoint
    dbmod.update_checkpoint_resume(req.checkpoint_id, resume_token, status=("RESUMED" if decision=="ACCEPT" else "REJECTED"))
    # Signal orchestrator if waiting
    with registry_lock:
        ev = resume_registry.get(req.checkpoint_id)
        if ev:
            logging.info(f"Human API: signaling orchestrator for checkpoint {req.checkpoint_id} with decision {decision}")
            ev["decision"] = decision
            ev["resume_token"] = resume_token
            ev["reviewer_id"] = req.reviewer_id
            ev["notes"] = req.notes
            ev["event"].set()
        else:
            logging.info(f"Human API: no orchestrator waiting for checkpoint {req.checkpoint_id}")
    return {"resume_token": resume_token, "next_stage": next_stage}