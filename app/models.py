from dataclasses import dataclass
from typing import Any, Dict, List
import datetime
import json

@dataclass
class InvoicePayload:
    data: Dict[str, Any]

@dataclass
class WorkflowState:
    invoice_id: str
    stage_history: List[Dict[str, Any]]
    current_stage: str
    payload: Dict[str, Any]
    created_at: str

    def to_json(self):
        return json.dumps({
            "invoice_id": self.invoice_id,
            "stage_history": self.stage_history,
            "current_stage": self.current_stage,
            "payload": self.payload,
            "created_at": self.created_at
        })

    @staticmethod
    def from_json(s: str):
        d = json.loads(s)
        return WorkflowState(
            invoice_id=d["invoice_id"],
            stage_history=d["stage_history"],
            current_stage=d["current_stage"],
            payload=d["payload"],
            created_at=d["created_at"]
        )