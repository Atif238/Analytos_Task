import logging
from typing import Dict, Any, List
import random
import uuid

# Simulated COMMON abilities
def common_validate_schema(payload: Dict[str, Any]) -> Dict[str, Any]:
    logging.info("COMMON: validate_schema called")
    required = ["invoice_id", "vendor_name", "amount", "currency"]
    missing = [k for k in required if k not in payload]
    return {"validated": len(missing) == 0, "missing": missing}

def common_parse_lines(ocr_text: str) -> Dict[str, Any]:
    logging.info("COMMON: parse_line_items called")
    # Simulated parser: detect a single line item if 'ITEM' present, else return payload's lines
    lines = []
    if "Item:" in ocr_text:
        lines.append({"desc": "Parsed item from OCR", "qty": 1, "unit_price": 100.0, "total": 100.0})
    return {"invoice_text": ocr_text, "parsed_line_items": lines, "currency": "USD", "parsed_dates": {"invoice_date": "2025-11-01", "due_date": "2025-11-30"}}

def common_normalize_vendor(name: str) -> Dict[str, Any]:
    logging.info("COMMON: normalize_vendor called")
    normalized = name.strip().title()
    return {"normalized_name": normalized}

def common_compute_flags(state: Dict[str, Any]) -> Dict[str, Any]:
    logging.info("COMMON: compute_flags called")
    flags = []
    risk_score = 0.1
    if not state.get("payload", {}).get("vendor_tax_id"):
        flags.append("missing_tax_id")
        risk_score = 0.5
    return {"missing_info": flags, "risk_score": risk_score}

def common_build_accounting_entries(state: Dict[str, Any]) -> Dict[str, Any]:
    logging.info("COMMON: build_accounting_entries called")
    invoice = state["payload"]
    entries = [
        {"account": "Expenses", "debit": invoice.get("amount", 0.0)},
        {"account": "Accounts Payable", "credit": invoice.get("amount", 0.0)}
    ]
    return {"accounting_entries": entries, "reconciliation_report": {"status": "OK"}}

# Simulated ATLAS abilities (external systems)
def atlas_ocr_run(tool_name: str, attachments: List[str]) -> Dict[str, Any]:
    logging.info(f"ATLAS: OCR run via {tool_name} on attachments {attachments}")
    # For demo, return a predictable OCR text
    return {"ocr_text": "Vendor: Example Co\nItem: Demo Service\nTotal: 100.00\nPO: PO-12345"}

def atlas_enrich_vendor(tool_name: str, vendor_name: str) -> Dict[str, Any]:
    logging.info(f"ATLAS: enrich_vendor via {tool_name} for {vendor_name}")
    # Return mock enrichment
    return {"tax_id": "TAX-123", "credit_score": 720, "vendor_id": str(uuid.uuid4())}

# in app/mcp_clients.py — replace atlas_fetch_erp with this
def atlas_fetch_erp(tool_name: str, vendor_name: str, invoice: Dict[str, Any]) -> Dict[str, Any]:
    logging.info(f"ATLAS: fetch_erp via {tool_name} for vendor {vendor_name}, invoice {invoice.get('invoice_id')}")
    # For testing, return a fixed PO amount (so invoice and PO can deliberately mismatch)
    # Change po_amount here to control whether match succeeds or fails.
    po_amount = 100.0  # <-- set different value to force mismatch (e.g., invoice amount is 500)
    return {
        "pos": [{"po_id": "PO-12345", "amount": po_amount}],
        "grns": [{"grn_id": "GRN-1", "items_received": True}],
        "history": [{"invoice_id": "INV-0001", "amount": 90.0}]
    }

def atlas_post_to_erp(tool_name: str, accounting_entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    logging.info(f"ATLAS: post_to_erp via {tool_name}")
    return {"posted": True, "erp_txn_id": f"TXN-{random.randint(1000,9999)}"}

def atlas_schedule_payment(tool_name: str, invoice: Dict[str, Any]) -> Dict[str, Any]:
    logging.info(f"ATLAS: schedule_payment via {tool_name}")
    return {"scheduled_payment_id": f"PAY-{random.randint(10000,99999)}", "status": "scheduled"}

# Match engine (COMMON)
def common_compute_match_score(state: Dict[str, Any]) -> Dict[str, Any]:
    logging.info("COMMON: compute_match_score called")
    # Very simple matching logic:
    invoice_amount = state["payload"].get("amount", 0.0)
    pos = state.get("retrieved", {}).get("pos", [])
    if not pos:
        return {"match_score": 0.0, "match_result": "FAILED", "tolerance_pct": 0.0, "match_evidence": {}}
    po_amount = pos[0].get("amount", 0.0)
    # match score based on closeness
    if po_amount == 0:
        score = 0.0
    else:
        diff = abs(po_amount - invoice_amount)
        pct = diff / po_amount
        score = max(0.0, 1.0 - pct)
    result = "MATCHED" if score >= 0.9 else "FAILED"
    return {"match_score": round(score, 3), "match_result": result, "tolerance_pct": pct * 100.0 if 'pct' in locals() else 100.0, "match_evidence": {"po_amount": po_amount}}