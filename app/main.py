import threading
import time
import uuid
import logging
import json
import uvicorn
from . import db as dbmod
from .bigtool import select as bigtool_select
from . import mcp_clients as mcp
from .human_api import app as human_app, resume_registry, registry_lock
from .models import WorkflowState
from typing import Dict, Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Load workflow config
with open("workflow.json", "r") as f:
    WORKFLOW = json.load(f)

CONFIG = WORKFLOW["config"]

def safe_json(obj: Any) -> str:
    """
    Try a normal json.dumps for pretty printing. If it raises (e.g. circular refs),
    fall back to the safe serializer implemented in db._to_json_text.
    """
    try:
        return json.dumps(obj, indent=2, ensure_ascii=False)
    except Exception:
        try:
            return dbmod._to_json_text(obj)
        except Exception:
            # final fallback: string repr
            return str(obj)

def start_human_api():
    # Start FastAPI/uvicorn server in a background thread using uvicorn.Server
    def run_server():
        config = uvicorn.Config("app.human_api:app", host="127.0.0.1", port=8000, log_level="info", loop="asyncio")
        server = uvicorn.Server(config)
        server.run()

    t = threading.Thread(target=run_server, daemon=True)
    t.start()

    # Wait briefly and check that the server has started (best-effort)
    import socket
    started = False
    for _ in range(10):
        try:
            with socket.create_connection(("127.0.0.1", 8000), timeout=1):
                started = True
                break
        except Exception:
            time.sleep(0.2)
    if started:
        logging.info("Human review API started at http://localhost:8000")
    else:
        logging.warning("Human review API did not respond on http://localhost:8000 (yet). Check logs or start uvicorn manually.")

def run_workflow(invoice_payload: Dict[str, Any]):
    invoice_id = invoice_payload.get("invoice_id", f"inv-{uuid.uuid4()}")
    logging.info(f"Workflow: Starting for invoice_id={invoice_id}")

    # Initialize state
    state = WorkflowState(
        invoice_id=invoice_id,
        stage_history=[],
        current_stage="INTAKE",
        payload=invoice_payload,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )

    # Stage 1: INTAKE
    logging.info("Stage: INTAKE — validate schema and persist raw invoice")
    schema_res = mcp.common_validate_schema(invoice_payload)
    dbmod.persist_invoice(invoice_id, invoice_payload)
    intake_out = {"raw_id": invoice_id, "ingest_ts": state.created_at, "validated": schema_res["validated"]}
    state.stage_history.append({"stage": "INTAKE", "output": intake_out})
    state.current_stage = "UNDERSTAND"

    # Stage 2: UNDERSTAND (OCR -> parsing)
    logging.info("Stage: UNDERSTAND — OCR and parse line items")
    ocr_tool = bigtool_select("ocr", {})
    ocr_res = mcp.atlas_ocr_run(ocr_tool, invoice_payload.get("attachments", []))
    parsed = mcp.common_parse_lines(ocr_res["ocr_text"])
    understand_out = {"parsed_invoice": parsed, "ocr_tool": ocr_tool}
    state.stage_history.append({"stage": "UNDERSTAND", "output": understand_out})
    state.payload.setdefault("parsed", {}).update(parsed)
    state.current_stage = "PREPARE"

    # Stage 3: PREPARE (normalize + enrich + flags)
    logging.info("Stage: PREPARE — normalize vendor and enrich")
    normalized = mcp.common_normalize_vendor(invoice_payload.get("vendor_name", ""))
    enrich_tool = bigtool_select("enrichment", {})
    enrich = mcp.atlas_enrich_vendor(enrich_tool, normalized["normalized_name"])
    flags = mcp.common_compute_flags({"payload": invoice_payload})
    prepare_out = {"vendor_profile": {**normalized, **enrich}, "flags": flags, "enrich_tool": enrich_tool}
    state.stage_history.append({"stage": "PREPARE", "output": prepare_out})
    # merge enrichment into payload
    state.payload.setdefault("vendor_profile", {}).update(prepare_out["vendor_profile"])
    state.payload.setdefault("flags", {}).update(prepare_out["flags"])
    state.current_stage = "RETRIEVE"

    # Stage 4: RETRIEVE (ERP fetch)
    logging.info("Stage: RETRIEVE — fetch PO/GRN/history from ERP")
    erp_tool = bigtool_select("erp_connector", {})
    retrieved = mcp.atlas_fetch_erp(erp_tool, normalized["normalized_name"], invoice_payload)
    retrieve_out = {"retrieved": retrieved, "erp_tool": erp_tool}
    state.stage_history.append({"stage": "RETRIEVE", "output": retrieve_out})
    state.payload.setdefault("retrieved", {}).update(retrieved)
    state.current_stage = "MATCH_TWO_WAY"

    # Stage 5: MATCH_TWO_WAY
    logging.info("Stage: MATCH_TWO_WAY — compute match score")
    match_res = mcp.common_compute_match_score({"payload": invoice_payload, "retrieved": retrieved})
    state.stage_history.append({"stage": "MATCH_TWO_WAY", "output": match_res})
    state.payload.setdefault("match", {}).update(match_res)
    state.current_stage = "CHECKPOINT_HITL" if match_res["match_result"] == "FAILED" else "RECONCILE"

    # Stage 6: CHECKPOINT_HITL (if needed)
    if match_res["match_result"] == "FAILED":
        logging.info("Stage: CHECKPOINT_HITL — creating checkpoint for human review")
        checkpoint_id = f"chkpt-{str(uuid.uuid4())}"
        review_url = f"http://localhost:8000/human-review/pending"
        paused_reason = "Match score below threshold"
        # persist full state blob
        state_blob = {
            "invoice_id": state.invoice_id,
            "payload": state.payload,
            "stage_history": state.stage_history,
            "paused_at_stage": "MATCH_TWO_WAY"
        }
        dbmod.create_checkpoint(checkpoint_id, state.invoice_id, state_blob, paused_reason, review_url)
        state.stage_history.append({"stage": "CHECKPOINT_HITL", "output": {"checkpoint_id": checkpoint_id, "review_url": review_url, "paused_reason": paused_reason}})
        logging.info(f"Checkpoint created: {checkpoint_id}. Pausing workflow until human review.")
        # Register an event to wait for human decision
        ev = threading.Event()
        with registry_lock:
            resume_registry[checkpoint_id] = {"event": ev, "decision": None}
        logging.info(f"Waiting for human decision on checkpoint {checkpoint_id}. Check the Human Review API.")
        ev.wait()  # block until human posts decision
        # After resume
        with registry_lock:
            info = resume_registry.pop(checkpoint_id, {})
        decision = info.get("decision")
        resume_token = info.get("resume_token")
        reviewer = info.get("reviewer_id")
        notes = info.get("notes")
        state.stage_history.append({"stage": "HITL_DECISION", "output": {"decision": decision, "resume_token": resume_token, "reviewer_id": reviewer, "notes": notes}})
        if decision == "REJECT":
            logging.info("Human rejected the invoice. Finalizing with MANUAL_HANDOFF")
            state.current_stage = "COMPLETE"
            state.stage_history.append({"stage": "COMPLETE", "output": {"status": "REQUIRES_MANUAL_HANDLING"}})
            final_payload = {"status": "REQUIRES_MANUAL_HANDLING", "invoice_id": state.invoice_id}
            logging.info(f"Workflow ended: {safe_json(final_payload)}")
            return final_payload
        else:
            logging.info("Human accepted — resuming to RECONCILE")
            state.current_stage = "RECONCILE"

    # Stage 7: RECONCILE
    logging.info("Stage: RECONCILE — build accounting entries")
    recon_out = mcp.common_build_accounting_entries({"payload": invoice_payload})
    state.stage_history.append({"stage": "RECONCILE", "output": recon_out})
    state.payload.setdefault("accounting_entries", []).extend(recon_out["accounting_entries"])
    state.current_stage = "APPROVE"

    # Stage 8: APPROVE
    logging.info("Stage: APPROVE — apply approval policy")
    amount = invoice_payload.get("amount", 0.0)
    approval_status = "APPROVED" if amount <= 5000 else "ESCALATED"
    approver_id = None if approval_status == "APPROVED" else "approver-team"
    state.stage_history.append({"stage": "APPROVE", "output": {"approval_status": approval_status, "approver_id": approver_id}})
    state.current_stage = "POSTING" if approval_status == "APPROVED" else "COMPLETE"

    # Stage 9: POSTING
    if approval_status == "APPROVED":
        erp_tool_post = bigtool_select("erp_connector", {})
        post_res = mcp.atlas_post_to_erp(erp_tool_post, state.payload.get("accounting_entries", []))
        sched = mcp.atlas_schedule_payment(erp_tool_post, invoice_payload)
        post_out = {**post_res, **sched}
        state.stage_history.append({"stage": "POSTING", "output": post_out})
        state.current_stage = "NOTIFY"
    else:
        logging.info("Approval required — skipping posting and marking workflow for escalation.")
        state.stage_history.append({"stage": "POSTING", "output": {"posted": False}})
        state.current_stage = "NOTIFY"

    # Stage 10: NOTIFY
    logging.info("Stage: NOTIFY — notify vendor and finance team")
    email_tool = bigtool_select("email", {})
    notify_status = {"vendor_email": "sent", "finance_slack": "sent", "via": email_tool}
    state.stage_history.append({"stage": "NOTIFY", "output": notify_status})
    state.current_stage = "COMPLETE"

    # Stage 11: COMPLETE
    logging.info("Stage: COMPLETE — final payload and audit")
    final_payload = {
        "invoice_id": state.invoice_id,
        "status": "COMPLETED",
        "accounting_entries": state.payload.get("accounting_entries"),
        "approval_status": approval_status,
        "history": state.stage_history
    }
    state.stage_history.append({"stage": "COMPLETE", "output": {"final_payload": final_payload}})
    # Persist audit to DB (append into invoices table as example)
    dbmod.persist_invoice(state.invoice_id + "-final", {"audit": state.stage_history})
    logging.info(f"Workflow completed for invoice {state.invoice_id}. Final payload:\n{safe_json(final_payload)}")
    return final_payload

def demo_run():
    start_human_api()
    dbmod.init_db()
    # Load sample invoice that will trigger HITL (low matching)
    with open("sample_invoice.json", "r") as f:
        sample = json.load(f)
    # Run workflow in separate thread (so main thread can continue)
    def runner():
        out = run_workflow(sample)
        logging.info("Demo run finished. Summary output:")
        logging.info(safe_json(out))
    t = threading.Thread(target=runner, daemon=True)
    t.start()
    # Keep main thread alive while the runner and uvicorn keep working
    while t.is_alive():
        time.sleep(1)

if __name__ == "__main__":
    demo_run()