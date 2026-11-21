import os
import json
from datetime import datetime
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv
from google import genai
import database as db
import ingestion as ing

load_dotenv()

st.set_page_config(
    page_title="Living Money Coach",
    page_icon="💸",
    layout="wide",
)

CATEGORIES = [
    "Dining", "Groceries", "Rent & Utilities", "Subscriptions",
    "Transport", "Shopping", "Health", "Entertainment", "Income", "Other"
]

SAMPLE_TRANSACTIONS = [
    {"date": "2026-10-04", "merchant": "ZOMATO", "amount": 480.0, "category": "Dining", "source": "sample"},
    {"date": "2026-10-06", "merchant": "BIGBASKET", "amount": 2150.0, "category": "Groceries", "source": "sample"},
    {"date": "2026-10-08", "merchant": "UBER", "amount": 340.0, "category": "Transport", "source": "sample"},
    {"date": "2026-10-10", "merchant": "NETFLIX", "amount": 649.0, "category": "Subscriptions", "source": "sample"},
    {"date": "2026-10-14", "merchant": "AMAZON", "amount": 1890.0, "category": "Shopping", "source": "sample"},
    {"date": "2026-10-20", "merchant": "SWIGGY", "amount": 560.0, "category": "Dining", "source": "sample"},
    {"date": "2026-11-02", "merchant": "SPOTIFY", "amount": 119.0, "category": "Subscriptions", "source": "sample"},
    {"date": "2026-11-05", "merchant": "ELECTRICITY BOARD", "amount": 1620.0, "category": "Rent & Utilities", "source": "sample"},
    {"date": "2026-11-11", "merchant": "APOLLO PHARMACY", "amount": 720.0, "category": "Health", "source": "sample"},
    {"date": "2026-11-16", "merchant": "MYNTRA", "amount": 2400.0, "category": "Shopping", "source": "sample"},
]


def _get_api_key() -> str:
    raw_key = ""
    try:
        if "GEMINI_API_KEY" in st.secrets:
            raw_key = str(st.secrets["GEMINI_API_KEY"])
    except Exception:
        raw_key = ""
    if not raw_key:
        raw_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
    return raw_key.strip().strip('"').strip("'")


def _ask_gemini(prompt: str) -> str:
    api_key = _get_api_key()
    if not api_key:
        return "⚠️ GEMINI_API_KEY not configured yet. Add it in Streamlit Secrets to get live Gemini responses."

    client = genai.Client(api_key=api_key)
    models_to_try = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3-flash-preview"]
    last_err = None

    for model_id in models_to_try:
        try:
            resp = client.models.generate_content(model=model_id, contents=prompt)
            if resp and resp.text:
                return resp.text.strip()
        except Exception as e:
            last_err = e
            continue

    return f"⚠️ Gemini request fallback: {last_err}"


def _init_state():
    if "current_user" not in st.session_state:
        st.session_state.current_user = "ayushman_demo"
    if "tx_rows" not in st.session_state:
        st.session_state.tx_rows = list(SAMPLE_TRANSACTIONS)
    if "last_extracted" not in st.session_state:
        st.session_state.last_extracted = []
    if "rules_applied_count" not in st.session_state:
        st.session_state.rules_applied_count = 0
    if "coach_reply" not in st.session_state:
        st.session_state.coach_reply = ""
    if "trip_reply" not in st.session_state:
        st.session_state.trip_reply = ""


def _load_db_transactions(username: str):
    try:
        if hasattr(db, "get_transactions"):
            rows = db.get_transactions(username)
            if isinstance(rows, list) and len(rows) > 0:
                return rows
    except Exception:
        pass
    return None


def _save_transaction_safe(username: str, tx: dict):
    try:
        if hasattr(db, "add_transaction"):
            db.add_transaction(username, tx)
            return
        if hasattr(db, "insert_transaction"):
            db.insert_transaction(username, tx)
            return
    except Exception:
        pass


def _save_rule_safe(username: str, merchant: str, category: str):
    keyword = str(merchant).strip().upper()
    if not keyword:
        return
    try:
        if hasattr(db, "save_rule"):
            db.save_rule(username, keyword, category)
            return
        if hasattr(db, "add_rule"):
            db.add_rule(username, keyword, category)
            return
    except Exception:
        pass

    rules_store = st.session_state.setdefault("local_rules", {})
    rules_store[keyword] = category


def _get_rules_safe(username: str) -> dict:
    merged = dict(st.session_state.get("local_rules", {}))
    try:
        if hasattr(db, "get_rules"):
            db_rules = db.get_rules(username=username)
            if isinstance(db_rules, dict):
                merged.update(db_rules)
    except Exception:
        pass
    return merged


def _tx_dataframe() -> pd.DataFrame:
    rows = st.session_state.get("tx_rows") or []
    if not rows:
        return pd.DataFrame(columns=["date", "merchant", "amount", "category", "source"])
    df = pd.DataFrame(rows)
    if "amount" in df.columns:
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    if "category" not in df.columns:
        df["category"] = "Other"
    if "merchant" not in df.columns:
        df["merchant"] = "UNKNOWN"
    if "date" not in df.columns:
        df["date"] = datetime.now().strftime("%Y-%m-%d")
    return df


def render_sidebar():
    with st.sidebar:
        st.title("💸 Living Money Coach")
        st.caption("Adaptive Personal Finance & Decision Engine")

        username = st.text_input("Profile / Username", value=st.session_state.current_user)
        st.session_state.current_user = username.strip() or "default"

        if st.button("⚡ Load 2-Month Sample Data", use_container_width=True):
            st.session_state.tx_rows = list(SAMPLE_TRANSACTIONS)
            for tx in SAMPLE_TRANSACTIONS:
                _save_transaction_safe(st.session_state.current_user, tx)
            st.success("Loaded 2-month sample transactions!")
            st.rerun()

        db_rows = _load_db_transactions(st.session_state.current_user)
        if db_rows is not None and st.button("🔄 Sync From Database", use_container_width=True):
            st.session_state.tx_rows = db_rows
            st.rerun()

        active_rules = _get_rules_safe(st.session_state.current_user)
        st.markdown("---")
        st.markdown(f"**🧠 Active Correction Rules:** `{len(active_rules)}`")
        if active_rules:
            for k, v in list(active_rules.items())[:6]:
                st.caption(f"• `{k}` → **{v}**")


def render_overview(df: pd.DataFrame):
    total_spend = float(df["amount"].sum()) if not df.empty else 0.0
    tx_count = len(df)
    top_cat = df.groupby("category")["amount"].sum().idxmax() if not df.empty and total_spend > 0 else "N/A"
    sub_spend = float(df[df["category"] == "Subscriptions"]["amount"].sum()) if not df.empty else 0.0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Tracked Spend", f"₹{total_spend:,.0f}")
    c2.metric("Transactions", f"{tx_count}")
    c3.metric("Top Spend Category", top_cat)
    c4.metric("Subscriptions Leak", f"₹{sub_spend:,.0f}")

    if not df.empty and total_spend > 0:
        cat_summary = df.groupby("category", as_index=False)["amount"].sum().sort_values("amount", ascending=False)
        left, right = st.columns([1.2, 1])
        with left:
            fig_bar = px.bar(
                cat_summary,
                x="category",
                y="amount",
                title="Spend by Category (₹)",
                text_auto=".0f",
            )
            fig_bar.update_layout(height=320, margin=dict(l=15, r=15, t=40, b=20))
            st.plotly_chart(fig_bar, use_container_width=True)
        with right:
            fig_pie = px.pie(
                cat_summary,
                names="category",
                values="amount",
                title="Category Share",
                hole=0.42,
            )
            fig_pie.update_layout(height=320, margin=dict(l=15, r=15, t=40, b=20))
            st.plotly_chart(fig_pie, use_container_width=True)


def render_upload_and_correction_loop():
    st.markdown("---")
    st.subheader("📥 Upload & Correction Loop")
    st.caption("Paste SMS alerts, CSV rows, or bank text—extract, auto-apply learned rules, and save corrections.")

    default_sample_input = (
        "2026-11-18 Zomato order 420\n"
        "2026-11-19 Uber trip 265\n"
        "2026-11-20 Netflix monthly 649"
    )
    sms_text = st.text_area(
        "Paste SMS / Statement / CSV Lines",
        value=st.session_state.get("sms_input_box", default_sample_input),
        height=110,
        key="sms_input_box",
    )

    col_btn1, col_btn2 = st.columns([1, 2])
    with col_btn1:
        extract_clicked = st.button("🚀 Extract and Categorize", type="primary", use_container_width=True)

    if extract_clicked:
        try:
            txs, rules_hit = ing.parse_text_or_csv(
                sms_text,
                source="sms",
                username=st.session_state.current_user,
            )
            st.session_state.last_extracted = txs or []
            st.session_state.rules_applied_count = rules_hit or 0

            if txs:
                st.session_state.tx_rows = list(txs) + list(st.session_state.tx_rows)
                for item in txs:
                    _save_transaction_safe(st.session_state.current_user, item)

            st.success(
                f"Extracted {len(txs)} transaction(s) • {rules_hit} learned rule(s) applied!"
            )
        except Exception as e:
            st.error(f"Could not extract transactions cleanly: {e}")

    extracted = st.session_state.get("last_extracted") or []
    if extracted:
        st.markdown("**Extracted Preview & Live Correction Loop**")
        ext_df = pd.DataFrame(extracted)
        st.dataframe(ext_df, use_container_width=True, hide_index=True)

        c_m, c_c, c_b = st.columns([2, 2, 1.2])
        merchants_list = [str(x.get("merchant", "")).upper() for x in extracted if x.get("merchant")]
        with c_m:
            selected_merchant = st.selectbox("Merchant to Teach Rule", options=merchants_list or ["ZOMATO"])
        with c_c:
            corrected_cat = st.selectbox("Correct Category", options=CATEGORIES)
        with c_b:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("💾 Save Rule", use_container_width=True):
                _save_rule_safe(st.session_state.current_user, selected_merchant, corrected_cat)
                for r in st.session_state.tx_rows:
                    if selected_merchant in str(r.get("merchant", "")).upper():
                        r["category"] = corrected_cat
                for r in st.session_state.last_extracted:
                    if selected_merchant in str(r.get("merchant", "")).upper():
                        r["category"] = corrected_cat
                st.success(f"Saved rule: `{selected_merchant}` → **{corrected_cat}**")
                st.rerun()


def render_what_if_simulator(df: pd.DataFrame):
    st.markdown("---")
    st.subheader("🎯 What-If Financial Simulator (12-Month Impact)")
    st.caption("Test discretionary spend cuts and extra monthly investments to see 1-year compounding impact.")

    col1, col2, col3 = st.columns(3)
    with col1:
        discretionary_cut_pct = st.slider("Cut Dining & Shopping (%)", 0, 60, 20, step=5)
    with col2:
        extra_monthly_invest = st.slider("Extra Monthly SIP / Savings (₹)", 0, 25000, 3000, step=500)
    with col3:
        expected_return_pct = st.slider("Expected Annual Return (%)", 6, 18, 12, step=1)

    current_spend = float(df["amount"].sum()) if not df.empty and float(df["amount"].sum()) > 0 else 25000.0
    disc_df = df[df["category"].astype(str).str.lower().isin(["dining", "shopping", "entertainment"])] if not df.empty else pd.DataFrame()
    discretionary_spend = float(disc_df["amount"].sum()) if not disc_df.empty and float(disc_df["amount"].sum()) > 0 else 8000.0

    monthly_saved_from_cut = discretionary_spend * (discretionary_cut_pct / 100.0)
    total_monthly_boost = monthly_saved_from_cut + extra_monthly_invest

    r_monthly = (expected_return_pct / 100.0) / 12.0
    base_corpus = 0.0
    sim_corpus = 0.0
    months = list(range(1, 13))
    base_series = []
    sim_series = []

    for _ in months:
        base_corpus = (base_corpus + extra_monthly_invest * 0.3) * (1 + r_monthly)
        sim_corpus = (sim_corpus + total_monthly_boost) * (1 + r_monthly)
        base_series.append(round(base_corpus, 0))
        sim_series.append(round(sim_corpus, 0))

    extra_12m_wealth = max(0.0, sim_corpus - base_corpus)
    new_monthly_spend = max(0.0, current_spend - monthly_saved_from_cut)

    m1, m2, m3 = st.columns(3)
    m1.metric("Monthly Spend Cut Saved", f"₹{monthly_saved_from_cut:,.0f}", f"-{discretionary_cut_pct}% discretionary")
    m2.metric("Total Monthly Boost", f"₹{total_monthly_boost:,.0f}/mo", "Cut + Extra SIP")
    m3.metric("12-Month Extra Wealth", f"₹{extra_12m_wealth:,.0f}", f"at {expected_return_pct}% p.a.")

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=months, y=sim_series, mode="lines+markers", name="With What-If Plan (₹)"))
    fig.add_trace(go.Scatter(x=months, y=base_series, mode="lines+markers", name="Baseline (₹)"))
    fig.update_layout(
        xaxis_title="Month",
        yaxis_title="Projected Value (₹)",
        height=300,
        margin=dict(l=20, r=20, t=30, b=20),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.info(
        f"**Coach Verdict:** Cutting **{discretionary_cut_pct}%** on discretionary spends saves **₹{monthly_saved_from_cut:,.0f}/mo**. "
        f"Combined with **₹{extra_monthly_invest:,.0f}/mo** extra investment, your adjusted spend is **₹{new_monthly_spend:,.0f}** "
        f"and builds **~₹{extra_12m_wealth:,.0f}** extra over 12 months."
    )


def render_coach_and_trip_agent(df: pd.DataFrame):
    st.markdown("---")
    st.subheader("🤖 AI Money Coach & Trip Planner")

    tab1, tab2 = st.tabs(["💬 Living Money Coach", "✈️ Foreign Trip Agent"])

    with tab1:
        summary_json = df.groupby("category")["amount"].sum().to_dict() if not df.empty else {}
        user_q = st.text_input(
            "Ask your money coach",
            value="How can I optimize my monthly spending and subscriptions?",
            key="coach_q",
        )
        if st.button("Ask Coach", key="btn_coach"):
            prompt = (
                f"You are Living Money Coach. Category spend summary (INR): {json.dumps(summary_json)}. "
                f"User question: {user_q}. Give concise, practical, actionable advice."
            )
            st.session_state.coach_reply = _ask_gemini(prompt)

        if st.session_state.coach_reply:
            st.markdown(st.session_state.coach_reply)

    with tab2:
        t_col1, t_col2 = st.columns(2)
        with t_col1:
            dest = st.text_input("Destination", value="Japan", key="trip_dest")
        with t_col2:
            budget_inr = st.number_input("Total Budget (₹)", min_value=10000, value=120000, step=5000, key="trip_budget")

        if st.button("Plan Trip Budget", key="btn_trip"):
            prompt = (
                f"Create a concise budget breakdown and daily saving plan for a trip to {dest} "
                f"with a total budget of ₹{budget_inr:,.0f}."
            )
            st.session_state.trip_reply = _ask_gemini(prompt)

        if st.session_state.trip_reply:
            st.markdown(st.session_state.trip_reply)


def main():
    _init_state()
    render_sidebar()

    st.title("💸 Living Money Coach")
    st.caption("Real-time expense extraction, adaptive category rules, what-if simulation, and AI coaching.")

    df = _tx_dataframe()
    render_overview(df)
    render_upload_and_correction_loop()
    render_what_if_simulator(df)
    render_coach_and_trip_agent(df)


if __name__ == "__main__":
    main()