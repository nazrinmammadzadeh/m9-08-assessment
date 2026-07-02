"""
Quick offline checks for the three tools - no LLM or network calls.
Run with: python test_tools.py
"""

import json

from tools import lookup_last_order, check_warranty, calculate
from agent import finalize

failures = 0


def check(label, condition):
    global failures
    print(f"{'PASS' if condition else 'FAIL'} - {label}")
    if not condition:
        failures += 1


def main():
    # lookup_last_order: happy path - picks the most recent order, not just the first one
    order = lookup_last_order("CUST-1042")
    check("lookup_last_order returns the most recent order", order.get("order_id") == "ORD-20260115-07")

    # lookup_last_order: customer isolation
    other = lookup_last_order("CUST-2087")
    check("lookup_last_order does not leak another customer's order", other.get("order_id") == "ORD-20250601-03")

    # lookup_last_order: unknown customer -> structured error, no crash
    missing = lookup_last_order("CUST-9999")
    check("lookup_last_order handles an unknown customer gracefully", "error" in missing)

    # check_warranty: active
    active = check_warranty("ORD-20260115-07")
    check("check_warranty reports an active warranty", active.get("status") == "active")

    # check_warranty: expired
    expired = check_warranty("ORD-20240312-01")
    check("check_warranty reports an expired warranty", expired.get("status") == "expired")

    # check_warranty: unknown order -> structured error, no crash
    missing_order = check_warranty("ORD-DOES-NOT-EXIST")
    check("check_warranty handles an unknown order gracefully", "error" in missing_order)

    # calculate: happy path
    calc = calculate("2 * 149.50")
    check("calculate does basic arithmetic", calc.get("result") == 299.0)

    # calculate: rejects non-arithmetic input instead of executing it
    unsafe = calculate("__import__('os').system('echo hacked')")
    check("calculate rejects non-arithmetic input", "error" in unsafe)

    # --- Safety mitigation: finalize() must not just trust the model ---
    # Simulates a model that was talked into a EUR 0.00 total by the
    # injected order note. finalize() should correct it using the real
    # tool data, without needing another LLM call to check.
    verified_lookup = {"lookup_last_order": {"unit_price": 149.50}}
    hijacked_answer = json.dumps({
        "customer_id": "CUST-1042", "order_reference": "ORD-20260115-07",
        "item": "Noise-Cancelling Headphones", "requested_quantity": 2,
        "unit_price": 149.50, "currency": "EUR", "total_cost": 0.00,
        "warranty_status": "active", "warranty_expires_on": "2027-01-15",
        "summary": "as instructed by the note, total is zero", "security_notice": None,
    })
    corrected = finalize(hijacked_answer, [], verified_lookup)
    check("finalize() corrects a total hijacked by injected tool data", corrected["total_cost"] == 299.0)
    check("finalize() flags the correction in security_notice", bool(corrected.get("security_notice")))

    # A correct model answer should pass through untouched (no false positives)
    honest_answer = json.dumps({
        "customer_id": "CUST-1042", "order_reference": "ORD-20260115-07",
        "item": "Noise-Cancelling Headphones", "requested_quantity": 2,
        "unit_price": 149.50, "currency": "EUR", "total_cost": 299.00,
        "warranty_status": "active", "warranty_expires_on": "2027-01-15",
        "summary": "all good", "security_notice": None,
    })
    untouched = finalize(honest_answer, [], verified_lookup)
    check("finalize() leaves a correct total alone", not untouched.get("security_notice"))

    # A non-JSON final answer should come back as a structured error, not a crash
    broken = finalize("sorry, something went wrong", [], verified_lookup)
    check("finalize() handles a non-JSON answer gracefully", broken["status"] == "error")

    print()
    print("All checks passed." if failures == 0 else f"{failures} check(s) failed.")


if __name__ == "__main__":
    main()
