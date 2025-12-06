import sqlite3
import json
from typing import Optional, List, Dict, Any
import os
from datetime import datetime

DB_PATH = os.environ.get("DEMO_DB_PATH", "./demo.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS invoices (
        invoice_id TEXT PRIMARY KEY,
        raw_payload TEXT,
        created_at TEXT
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS checkpoints (
        checkpoint_id TEXT PRIMARY KEY,
        invoice_id TEXT,
        state_blob TEXT,
        paused_reason TEXT,
        review_url TEXT,
        created_at TEXT,
        status TEXT,
        resume_token TEXT
    )
    """)
    conn.commit()
    conn.close()

def _make_serializable(obj, _seen=None):
    """
    Recursively convert an object into JSON-serializable structure.
    Replaces circular references with the string '<circular>' and
    non-serializable leaf objects with their string repr.
    """
    if _seen is None:
        _seen = set()
    oid = id(obj)
    if oid in _seen:
        return "<circular>"
    _seen.add(oid)

    # Primitives
    if obj is None or isinstance(obj, (str, int, float, bool)):
        _seen.remove(oid)
        return obj

    # Dict
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            try:
                key = k if isinstance(k, (str, int, float, bool)) else str(k)
            except Exception:
                key = str(k)
            out[key] = _make_serializable(v, _seen)
        _seen.remove(oid)
        return out

    # List/tuple/set
    if isinstance(obj, (list, tuple, set)):
        out = []
        for v in obj:
            out.append(_make_serializable(v, _seen))
        _seen.remove(oid)
        return out

    # Fallback for objects: try to get dict, else use str()
    try:
        if hasattr(obj, "__dict__"):
            out = {}
            for k, v in vars(obj).items():
                out[str(k)] = _make_serializable(v, _seen)
            _seen.remove(oid)
            return out
    except Exception:
        pass

    # Final fallback
    try:
        rep = str(obj)
    except Exception:
        rep = "<unserializable>"
    _seen.remove(oid)
    return rep

def _to_json_text(obj: Any) -> str:
    """
    Safely produce a JSON text string for storage.
    """
    safe = _make_serializable(obj)
    return json.dumps(safe, ensure_ascii=False)

def persist_invoice(invoice_id: str, payload: Dict[str, Any]):
    """
    Store invoice payload in invoices table. Uses safe serialization to avoid circular refs.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.utcnow().isoformat()
    payload_text = _to_json_text(payload)
    c.execute("INSERT OR REPLACE INTO invoices (invoice_id, raw_payload, created_at) VALUES (?, ?, ?)",
              (invoice_id, payload_text, now))
    conn.commit()
    conn.close()

def create_checkpoint(checkpoint_id: str, invoice_id: str, state_blob: Dict[str, Any], paused_reason: str, review_url: str):
    """
    Store checkpoint with a serialized state_blob.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.utcnow().isoformat()
    state_text = _to_json_text(state_blob)
    c.execute("""
    INSERT OR REPLACE INTO checkpoints
      (checkpoint_id, invoice_id, state_blob, paused_reason, review_url, created_at, status, resume_token)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (checkpoint_id, invoice_id, state_text, paused_reason, review_url, now, "PENDING", ""))
    conn.commit()
    conn.close()

def list_pending_checkpoints() -> List[Dict[str, Any]]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT checkpoint_id, invoice_id, state_blob, paused_reason, review_url, created_at FROM checkpoints WHERE status='PENDING'")
    rows = c.fetchall()
    conn.close()
    out = []
    for r in rows:
        # state_blob stored as JSON text
        try:
            state_blob = json.loads(r[2])
        except Exception:
            # fallback to raw text if something weird stored
            state_blob = {"raw": r[2]}
        out.append({
            "checkpoint_id": r[0],
            "invoice_id": r[1],
            "state_blob": state_blob,
            "paused_reason": r[3],
            "review_url": r[4],
            "created_at": r[5]
        })
    return out

def update_checkpoint_resume(checkpoint_id: str, resume_token: str, status: str = "RESUMED"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE checkpoints SET resume_token=?, status=? WHERE checkpoint_id=?", (resume_token, status, checkpoint_id))
    conn.commit()
    conn.close()

def get_checkpoint_state(checkpoint_id: str) -> Optional[Dict[str, Any]]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT state_blob FROM checkpoints WHERE checkpoint_id=?", (checkpoint_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    try:
        return json.loads(row[0])
    except Exception:
        return {"raw": row[0]}