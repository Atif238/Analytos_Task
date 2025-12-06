import streamlit as st
import requests
import json

API_BASE = st.sidebar.text_input("Human API base URL", value="http://localhost:8000")
st.sidebar.markdown("---")
st.sidebar.markdown("Reviewer details")
reviewer_id = st.sidebar.text_input("Reviewer ID", value="alice")
notes = st.sidebar.text_area("Review notes", value="")
st.sidebar.markdown("---")
refresh_button = st.sidebar.button("Refresh list")

st.title("Invoice Human Review (Streamlit UI)")
st.markdown("Connects to FastAPI human-review endpoints to list pending checkpoints and submit decisions.")

def get_pending():
    try:
        resp = requests.get(f"{API_BASE}/human-review/pending", timeout=5)
        resp.raise_for_status()
        return resp.json().get("items", [])
    except Exception as e:
        st.sidebar.error(f"Error fetching pending: {e}")
        return []

def post_decision(checkpoint_id, decision, notes, reviewer_id):
    payload = {
        "checkpoint_id": checkpoint_id,
        "decision": decision,
        "notes": notes,
        "reviewer_id": reviewer_id
    }
    try:
        resp = requests.post(f"{API_BASE}/human-review/decision", json=payload, timeout=5)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        st.error(f"Error posting decision: {e}")
        return None

# Clicking the button will automatically re-run the script, so explicit rerun is not required.
pending = get_pending()

if not pending:
    st.info("No pending checkpoints found.")
else:
    st.write(f"Found {len(pending)} pending checkpoint(s).")
    for item in pending:
        title = f"{item.get('invoice_id')} — {item.get('vendor_name', 'Unknown')} — {item.get('amount', '')} ({item.get('checkpoint_id')})"
        with st.expander(title, expanded=False):
            st.write("Checkpoint ID:", item.get("checkpoint_id"))
            st.write("Invoice ID:", item.get("invoice_id"))
            st.write("Vendor:", item.get("vendor_name"))
            st.write("Amount:", item.get("amount"))
            st.write("Created at:", item.get("created_at"))
            st.write("Reason:", item.get("reason_for_hold"))
            st.write("Review URL:", item.get("review_url"))
            # Optionally show state blob if present
            if item.get("state_blob"):
                st.markdown("**State snapshot**")
                st.json(item["state_blob"])
            cols = st.columns([1,1,3])
            with cols[0]:
                if st.button(f"ACCEPT {item['checkpoint_id']}", key=f"accept-{item['checkpoint_id']}"):
                    res = post_decision(item["checkpoint_id"], "ACCEPT", notes, reviewer_id)
                    if res:
                        st.success(f"Accepted. resume_token: {res.get('resume_token')}")
            with cols[1]:
                if st.button(f"REJECT {item['checkpoint_id']}", key=f"reject-{item['checkpoint_id']}"):
                    res = post_decision(item["checkpoint_id"], "REJECT", notes, reviewer_id)
                    if res:
                        st.warning(f"Rejected. resume_token: {res.get('resume_token')}")
            with cols[2]:
                st.markdown(f"[Open review URL]({item.get('review_url')})")