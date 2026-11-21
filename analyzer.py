import pandas as pd


def detect_subscriptions(tx_df: pd.DataFrame) -> list[dict]:
    """
    Detects recurring subscriptions/payments and flags:
    1. Price hikes or price changes across occurrences/months
    2. Subscriptions that appear inactive/unused in the latest month
    """
    if tx_df is None or tx_df.empty:
        return []

    df = tx_df.copy()
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    df["parsed_date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["parsed_date"]).sort_values("parsed_date")
    if df.empty:
        return []

    df["month_period"] = df["parsed_date"].dt.to_period("M")
    latest_period = df["month_period"].max()

    known_sub_merchants = [
        "NETFLIX", "SPOTIFY", "AMAZON PRIME", "YOUTUBE", "HOTSTAR",
        "JIOCINEMA", "APPLE", "ICLOUD", "ADOBE", "CHATGPT", "OPENAI",
        "CURSOR", "CANVA", "GYM", "CULT", "PLAYSTATION", "XBOX"
    ]

    sub_rows = []
    for merchant, grp in df.groupby("merchant"):
        m_upper = str(merchant).upper()
        cat_match = grp["category"].astype(str).str.lower().eq("subscriptions").any()
        keyword_match = any(k in m_upper for k in known_sub_merchants)
        months_count = grp["month_period"].nunique()

        # Treat as recurring if categorized as Subscriptions, matches known subscription brand, or repeats across 2+ months
        if not (cat_match or keyword_match or months_count >= 2):
            continue

        amounts = grp["amount"].tolist()
        first_amt = float(amounts[0])
        latest_amt = float(amounts[-1])
        last_date = grp["parsed_date"].max()
        days_since_last = int((df["parsed_date"].max() - last_date).days)
        in_latest_month = bool((grp["month_period"] == latest_period).any())

        # Determine Price Alert
        if len(amounts) >= 2 and latest_amt > first_amt:
            diff = latest_amt - first_amt
            pct = (diff / first_amt * 100.0) if first_amt > 0 else 0.0
            price_alert = f"⚠️ Price Hike (₹{first_amt:,.0f} → ₹{latest_amt:,.0f}, +₹{diff:,.0f} / +{pct:.1f}%)"
        elif len(amounts) >= 2 and latest_amt < first_amt:
            diff = first_amt - latest_amt
            price_alert = f"📉 Price Drop (₹{first_amt:,.0f} → ₹{latest_amt:,.0f}, -₹{diff:,.0f})"
        else:
            price_alert = "✅ Stable Price"

        # Determine Usage / Activity Alert
        if not in_latest_month or days_since_last >= 35:
            usage_alert = f"⚠️ Unused / Inactive (Last seen {last_date.strftime('%Y-%m-%d')}, {days_since_last}d ago)"
        else:
            usage_alert = "🟢 Active"

        sub_rows.append({
            "Merchant": merchant,
            "Category": grp["category"].iloc[-1],
            "Occurrences": len(amounts),
            "Latest Amount": f"₹{latest_amt:,.0f}",
            "Price Alert": price_alert,
            "Usage Alert": usage_alert,
            "Last Charged": last_date.strftime("%Y-%m-%d"),
        })

    return sub_rows


def get_drift_nudges(tx_df: pd.DataFrame, profile: dict) -> list[str]:
    """Generates actionable spending drift & savings nudges."""
    nudges = []
    if tx_df is None or tx_df.empty:
        return nudges

    expense_df = tx_df[tx_df["category"] != "Income"].copy()
    if expense_df.empty:
        return nudges

    expense_df["amount"] = pd.to_numeric(expense_df["amount"], errors="coerce").fillna(0.0)
    total_tracked = float(expense_df["amount"].sum())
    income = float(profile.get("monthly_income") or 0.0)
    fixed = float(profile.get("fixed_costs") or 0.0)

    if income > 0 and (fixed + total_tracked) > income:
        overshoot = (fixed + total_tracked) - income
        nudges.append(
            f"🚨 **Budget Drift Alert:** Fixed costs (₹{fixed:,.0f}) + tracked spending (₹{total_tracked:,.0f}) "
            f"exceed your monthly income (₹{income:,.0f}) by **₹{overshoot:,.0f}**."
        )

    cat_totals = expense_df.groupby("category")["amount"].sum().to_dict()
    dining_spend = float(cat_totals.get("Dining", 0.0))
    if income > 0 and dining_spend > income * 0.15:
        nudges.append(
            f"🍽️ **Dining Drift Nudge:** Dining spend is **₹{dining_spend:,.0f}** "
            f"({dining_spend / income * 100:.1f}% of monthly income). Trimming 20% frees **₹{dining_spend * 0.20:,.0f}**."
        )

    subs = detect_subscriptions(tx_df)
    hike_subs = [s["Merchant"] for s in subs if "Price Hike" in s.get("Price Alert", "")]
    unused_subs = [s["Merchant"] for s in subs if "Unused" in s.get("Usage Alert", "")]

    if hike_subs:
        nudges.append(f"💸 **Subscription Price Hike Detected:** Review **{', '.join(hike_subs)}** for unexpected renewal increases.")
    if unused_subs:
        nudges.append(f"💤 **Unused Subscription Alert:** **{', '.join(unused_subs)}** looks inactive—consider pausing or cancelling.")

    return nudges


def run_what_if_simulation(tx_df: pd.DataFrame, profile: dict, goal_row, adjustments: dict) -> dict:
    """Simulates baseline vs. adjusted monthly surplus and months needed to reach a goal."""
    income = float(profile.get("monthly_income") or 60000.0)
    fixed = float(profile.get("fixed_costs") or 25000.0)

    cat_totals = {}
    if tx_df is not None and not tx_df.empty:
        exp = tx_df[tx_df["category"] != "Income"].copy()
        exp["amount"] = pd.to_numeric(exp["amount"], errors="coerce").fillna(0.0)
        cat_totals = exp.groupby("category")["amount"].sum().to_dict()

    # Normalize variable spend across distinct months if multi-month data exists
    months_span = 1
    if tx_df is not None and not tx_df.empty and "date" in tx_df.columns:
        dt = pd.to_datetime(tx_df["date"], errors="coerce").dropna()
        if not dt.empty:
            months_span = max(int(dt.dt.to_period("M").nunique()), 1)

    baseline_var_monthly = sum(cat_totals.values()) / months_span
    baseline_surplus = max(income - fixed - baseline_var_monthly, 1000.0)

    pct_changes = adjustments.get("category_pct_change") or {}
    fixed_delta = float(adjustments.get("fixed_cost_delta") or 0.0)
    income_delta = float(adjustments.get("income_delta") or 0.0)

    sim_income = max(income + income_delta, 0.0)
    sim_fixed = max(fixed + fixed_delta, 0.0)

    sim_var_monthly = 0.0
    all_cats = set(cat_totals.keys()) | set(pct_changes.keys())
    for c in all_cats:
        base_c = float(cat_totals.get(c, 0.0)) / months_span
        chg = float(pct_changes.get(c, 0.0))
        sim_var_monthly += max(base_c * (1.0 + chg), 0.0)

    sim_surplus = max(sim_income - sim_fixed - sim_var_monthly, 1000.0)

    target_amt = float(goal_row["target_amount"])
    saved_amt = float(goal_row["saved_amount"])
    remaining = max(target_amt - saved_amt, 0.0)

    # Assume 50% of monthly surplus is directed toward the goal
    base_contrib = max(baseline_surplus * 0.5, 500.0)
    sim_contrib = max(sim_surplus * 0.5, 500.0)

    baseline_months = max(int(round(remaining / base_contrib)), 1) if remaining > 0 else 0
    sim_months = max(int(round(remaining / sim_contrib)), 1) if remaining > 0 else 0
    months_diff = baseline_months - sim_months

    return {
        "baseline_surplus": baseline_surplus,
        "sim_surplus": sim_surplus,
        "baseline_months": baseline_months,
        "sim_months": sim_months,
        "months_diff": months_diff,
    }