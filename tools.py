"""
Tool implementations for the order assistant agent.

Three tools:
  - lookup_last_order(customer_id)
  - check_warranty(order_id)
  - calculate(expression)

Design rule: a tool never raises for "expected" failures (unknown
customer, unknown order, bad expression). It returns {"error": ...}
instead, so the agent loop can keep going and the model gets a
chance to react sensibly instead of the whole run crashing.
"""

import ast
import json
import operator
from datetime import date, datetime
from pathlib import Path

DATA_FILE = Path(__file__).parent / "orders.json"


def _load_orders() -> dict:
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def lookup_last_order(customer_id: str) -> dict:
    """Return the most recent order on file for a customer."""
    if not isinstance(customer_id, str) or not customer_id.strip():
        return {"error": "invalid_customer_id", "detail": "customer_id must be a non-empty string"}

    orders_by_customer = _load_orders()
    customer_orders = orders_by_customer.get(customer_id)
    if not customer_orders:
        return {"error": "customer_not_found", "detail": f"No orders on file for {customer_id}"}

    last_order = max(customer_orders, key=lambda o: o["purchase_date"])
    return {
        "order_id": last_order["order_id"],
        "item": last_order["item"],
        "unit_price": last_order["unit_price"],
        "currency": last_order["currency"],
        "quantity": last_order["quantity"],
        "purchase_date": last_order["purchase_date"],
        "notes": last_order.get("notes", ""),
    }


def check_warranty(order_id: str) -> dict:
    """Check whether an order is still inside its warranty window."""
    if not isinstance(order_id, str) or not order_id.strip():
        return {"error": "invalid_order_id", "detail": "order_id must be a non-empty string"}

    orders_by_customer = _load_orders()
    for customer_orders in orders_by_customer.values():
        for order in customer_orders:
            if order["order_id"] != order_id:
                continue
            purchase = datetime.strptime(order["purchase_date"], "%Y-%m-%d").date()
            months = order["warranty_months"]
            total_month = purchase.month - 1 + months
            year = purchase.year + total_month // 12
            month = total_month % 12 + 1
            day = min(purchase.day, 28)  # keeps this simple, avoids month-length edge cases
            expires = date(year, month, day)
            status = "active" if date.today() <= expires else "expired"
            return {
                "order_id": order_id,
                "purchase_date": order["purchase_date"],
                "warranty_months": months,
                "expires_on": expires.isoformat(),
                "status": status,
            }

    return {"error": "order_not_found", "detail": f"No order on file with id {order_id}"}


# calculate() only ever evaluates arithmetic: numbers, + - * / **, and
# parentheses. Anything else (names, calls, attribute access, ...) is
# rejected before it can run. This also means calculate() can't be
# used to execute arbitrary code even if a tool result upstream tried
# to steer the model into passing something malicious as "expression".
_ALLOWED_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_OPERATORS:
        return _ALLOWED_OPERATORS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_OPERATORS:
        return _ALLOWED_OPERATORS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("disallowed syntax")


def calculate(expression: str) -> dict:
    """Safely evaluate a basic arithmetic expression, e.g. '2 * 149.50'."""
    if not isinstance(expression, str) or not expression.strip():
        return {"error": "invalid_expression", "detail": "expression must be a non-empty string"}
    try:
        tree = ast.parse(expression, mode="eval")
        result = _safe_eval(tree.body)
        return {"expression": expression, "result": result}
    except Exception:
        return {"error": "invalid_expression", "detail": "could not safely evaluate that expression"}
