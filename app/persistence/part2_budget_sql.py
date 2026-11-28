"""Budget membership shared by the reservation gate and its read-only report."""

UTC_DAY = "date_trunc('day', now(), 'UTC')"
UTC_MONTH = "date_trunc('month', now(), 'UTC')"
MONTHLY_CHARGE = f"(created_at >= {UTC_MONTH} OR dispatched_at >= {UTC_MONTH})"
BUDGET_TOTALS = f"""
  coalesce(sum(cost_usd) FILTER (WHERE {MONTHLY_CHARGE}), 0) AS spent,
  coalesce(sum(reserved_usd) FILTER (WHERE cost_usd IS NULL), 0) AS held
"""
BUDGET_ROWS = f"(cost_usd IS NULL OR {MONTHLY_CHARGE})"
