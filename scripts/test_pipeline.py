"""
End-to-end pipeline test — submits all 5 vendor documents and reports outcomes.
Run: python scripts/test_pipeline.py
"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

BASE_URL   = os.environ.get("API_BASE_URL")
VENDOR_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "test_data", "vendor_submissions")

if not BASE_URL:
    print("[ERROR] API_BASE_URL not set. Add it to your .env file.")
    sys.exit(1)

TESTS = [
    ("acme_software_onboarding.txt",      "j.hargreaves@acmesoftware.co.uk",        "AUTO_APPROVE",    "HIGH"),
    ("buildtech_facilities_onboarding.txt","g.tomlin@buildtechfacilities.co.uk",     "FLAG_FOR_REVIEW", "HIGH"),
    ("globaldata_onboarding.txt",          "f.drummond@globaldataanalytics.co.uk",   "FLAG_FOR_REVIEW", "HIGH"),
    ("premier_consulting_messy.txt",       "r.chalm@premierconsulting.co.uk",        "FLAG_FOR_REVIEW", "HIGH"),
    ("enterprise_cloud_highvalue.txt",     "t.ashbridge@enterprisecloudsolutions.co.uk","FLAG_FOR_REVIEW","HIGH"),
]

def run_test(filename, sender_email, expected_decision, expected_priority):
    filepath = os.path.join(VENDOR_DIR, filename)
    print(f"\n{'='*60}")
    print(f"FILE:     {filename}")
    print(f"EXPECTED: {expected_decision} | Priority: {expected_priority}")

    with open(filepath, "rb") as f:
        files = {"file": (filename, f, "text/plain")}
        data = {"sender_email": sender_email}
        resp = httpx.post(f"{BASE_URL}/process/manual", files=files, data=data, timeout=180)

    if resp.status_code != 200:
        print(f"ERROR: HTTP {resp.status_code} — {resp.text[:300]}")
        return False

    r = resp.json()
    company     = (r.get("company") or {}).get("company_name", "N/A")
    confidence  = r.get("overall_confidence_score", 0)
    decision    = r.get("routing_decision", "N/A")
    priority    = r.get("review_priority", "N/A")
    flags       = r.get("routing_flags", [])
    rag_flags   = r.get("rag_validation_flags", [])
    tier        = r.get("category_tier", "N/A")
    sort_code   = (r.get("banking") or {}).get("sort_code", "N/A")
    contract    = (r.get("services") or {}).get("contract_value_gbp", "N/A")

    print(f"RESULT:")
    print(f"  Company:         {company}")
    print(f"  Category Tier:   {tier}")
    print(f"  Contract Value:  £{contract}")
    print(f"  Sort Code:       {sort_code}")
    print(f"  Confidence:      {confidence:.4f}")
    print(f"  Decision:        {decision}  (expected: {expected_decision})")
    print(f"  Priority:        {priority}  (expected: {expected_priority})")
    print(f"  RAG Flags:       {rag_flags}")
    print(f"  Routing Flags:   {flags}")

    ok_decision = decision == expected_decision
    ok_priority = (priority == expected_priority) or (expected_decision == "AUTO_APPROVE" and priority in (None, "None", "N/A"))
    status = "PASS" if (ok_decision and ok_priority) else "FAIL"
    print(f"  STATUS: {status}")
    return ok_decision and ok_priority


if __name__ == "__main__":
    # Quick health check first
    try:
        health = httpx.get(f"{BASE_URL}/health", timeout=5).json()
        print(f"Health: {health}")
    except Exception as e:
        print(f"Server not reachable: {e}")
        sys.exit(1)

    results = []
    for args in TESTS:
        results.append(run_test(*args))
        time.sleep(1)  # avoid hammering

    print(f"\n{'='*60}")
    print(f"SUMMARY: {sum(results)}/{len(results)} tests passed")

    # Show review queue and vendor records
    print("\n--- Vendor Records (AUTO_APPROVED) ---")
    vendors = httpx.get(f"{BASE_URL}/vendors", timeout=10).json()
    print(f"  Total: {vendors['total']}")
    for v in vendors["items"]:
        print(f"  - {v['company_name']} | {v['service_category']} | confidence={v['overall_confidence_score']}")

    print("\n--- Review Queue ---")
    stats = httpx.get(f"{BASE_URL}/review/stats", timeout=10).json()
    print(f"  Pending: {stats['pending']} | Approved: {stats['approved']} | Rejected: {stats['rejected']}")
    print(f"  By Priority: {stats['pending_by_priority']}")
