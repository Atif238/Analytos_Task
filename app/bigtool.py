import random
import logging
from typing import List, Dict, Any

POOL_HINTS = {
    "ocr": ["google_vision", "tesseract", "aws_textract"],
    "enrichment": ["clearbit", "people_data_labs", "vendor_db"],
    "erp_connector": ["sap_sandbox", "netsuite", "mock_erp"],
    "db": ["sqlite", "postgres", "dynamodb"],
    "email": ["sendgrid", "smartlead", "ses"],
    "storage": ["s3", "gcs", "local_fs"]
}

def select(capability: str, context: Dict[str, Any] = None) -> str:
    # Deterministic selection for reproducibility in demo: prefer first unless context asks otherwise
    pool = POOL_HINTS.get(capability, [])
    if not pool:
        logging.info(f"BigtoolPicker: no pool for capability {capability}, returning 'mock_{capability}'")
        return f"mock_{capability}"
    # Simple selection: if context contains hint, use it; else choose round-robin / first option
    preferred = None
    if context and context.get("preferred"):
        preferred = context.get("preferred")
        if preferred in pool:
            logging.info(f"BigtoolPicker: selected preferred {preferred} for capability {capability}")
            return preferred
    # For demo, return first for predictability
    choice = pool[0]
    logging.info(f"BigtoolPicker: selected {choice} for capability {capability}")
    return choice