import os
import base64
import datetime
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import database as db
import ingestion as ing
import analyzer as an
import coach as ai

st.set_page_config(
    page_title="Living Money Coach",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="collapsed"
)
db.init_db()


def _init_investments_table():
    conn = db.get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS investments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL DEFAULT 'default',
            bucket TEXT NOT NULL,
            label TEXT NOT NULL,
            amount REAL NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


_init_investments_table()


def get_user_investments(username: str) -> pd.DataFrame:
    conn = db.get_conn()
    df = pd.read_sql(
        "SELECT * FROM investments WHERE username = ? ORDER BY id DESC",
        conn,
        params=(db._norm_user(username),),
    )
    conn.close()
    return df


def add_user_investment(username: str, bucket: str, label: str, amount: float, updated_at: str):
    conn = db.get_conn()
    conn.execute(
        "INSERT INTO investments (username, bucket, label, amount, updated_at) VALUES (?, ?, ?, ?, ?)",
        (db._norm_user(username), bucket, label.strip() or bucket, float(amount), updated_at),
    )
    conn.commit()
    conn.close()


def delete_user_investment(inv_id: int, username: str):
    conn = db.get_conn()
    conn.execute(
        "DELETE FROM investments WHERE id = ? AND username = ?",
        (inv_id, db._norm_user(username)),
    )
    conn.commit()
    conn.close()


def compute_proportional_allocation(risk: str, market_condition: str) -> tuple[dict, float, str]:
    """Returns (bucket_weights_pct, blended_annual_return, strategy_note)."""
    base = {
        "Conservative": {"Equity / Index Bucket": 25, "Debt / Fixed Income Bucket": 45, "Gold & Commodities Bucket": 15, "Liquid Emergency Reserve": 15},
        "Balanced": {"Equity / Index Bucket": 50, "Debt / Fixed Income Bucket": 25, "Gold & Commodities Bucket": 15, "Liquid Emergency Reserve": 10},
        "Growth": {"Equity / Index Bucket": 70, "Debt / Fixed Income Bucket": 15, "Gold & Commodities Bucket": 10, "Liquid Emergency Reserve": 5},
    }[risk].copy()

    if market_condition == "🟢 Bullish / Uptrend":
        base["Equity / Index Bucket"] = max(base["Equity / Index Bucket"] - 5, 10)
        base["Liquid Emergency Reserve"] += 5
        note = "Market is running hot—stay disciplined with SIPs and keep a slightly higher liquid buffer to avoid chasing peaks."
    elif market_condition == "🟡 Volatile / Sideways":
        base["Equity / Index Bucket"] = max(base["Equity / Index Bucket"] - 5, 10)
        base["Gold & Commodities Bucket"] += 5
        note = "Market is choppy—extra Gold & Debt cushion smooths volatility while SIPs average out costs."
    else:
        shift = min(5, base["Liquid Emergency Reserve"])
        base["Equity / Index Bucket"] += shift
        base["Liquid Emergency Reserve"] -= shift
        note = "Market is in a dip—gradually tilting surplus toward broad Equity/Index improves long-term compounding."

    rates = {
        "Equity / Index Bucket": 0.12,
        "Debt / Fixed Income Bucket": 0.07,
        "Gold & Commodities Bucket": 0.085,
        "Liquid Emergency Reserve": 0.05,
    }
    blended = sum((pct / 100.0) * rates[b] for b, pct in base.items())
    return base, blended, note


def project_sip_growth(monthly_amount: float, annual_rate: float, years: int) -> list[float]:
    """Returns year-end corpus values for years 1..N."""
    r = annual_rate / 12.0
    values = []
    for y in range(1, years + 1):
        n = y * 12
        if r == 0:
            val = monthly_amount * n
        else:
            val = monthly_amount * (((1 + r) ** n - 1) / r) * (1 + r)
        values.append(round(val))
    return values


# --- SESSION STATE ---
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.username = ""

if "chat_open" not in st.session_state:
    st.session_state.chat_open = False

if "theme_mode" not in st.session_state:
    st.session_state.theme_mode = "Light"

if "trip_result" not in st.session_state:
    st.session_state.trip_result = None

if "assistant_messages" not in st.session_state:
    st.session_state.assistant_messages = [
        {
            "role": "assistant",
            "content": "Hello sir, I am your AI Finance Agent. How can I help you with your savings, budget, or financial goals today?"
        }
    ]


def get_palette(mode: str) -> dict:
    if mode == "Dark":
        return {
            "app_bg": "#0b1120",
            "card_bg": "#111827",
            "card_border": "#1f2937",
            "text_primary": "#f8fafc",
            "text_muted": "#cbd5e1",
            "tab_bg": "#111827",
            "tab_text": "#cbd5e1",
            "active_grad": "linear-gradient(135deg, #4f46e5 0%, #7c3aed 55%, #06b6d4 100%)",
            "btn_grad": "linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)",
            "btn_shadow": "rgba(99, 102, 241, 0.35)",
            "header_grad": "linear-gradient(135deg, #1e1b4b 0%, #312e81 45%, #0f172a 100%)",
            "accent_gold": "#fbbf24",
            "accent_cyan": "#38bdf8",
            "chart_bg": "#111827",
            "chart_text": "#f8fafc",
            "plot_template": "plotly_dark",
        }
    return {
        "app_bg": "#f4f6fb",
        "card_bg": "#ffffff",
        "card_border": "#e2e8f0",
        "text_primary": "#0f172a",
        "text_muted": "#475569",
        "tab_bg": "#ffffff",
        "tab_text": "#334155",
        "active_grad": "linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%)",
        "btn_grad": "linear-gradient(135deg, #4f46e5 0%, #6366f1 100%)",
        "btn_shadow": "rgba(79, 70, 229, 0.25)",
        "header_grad": "linear-gradient(135deg, #1e1b4b 0%, #4338ca 55%, #0284c7 100%)",
        "accent_gold": "#f59e0b",
        "accent_cyan": "#bae6fd",
        "chart_bg": "#ffffff",
        "chart_text": "#0f172a",
        "plot_template": "plotly_white",
    }


pal = get_palette(st.session_state.theme_mode)

st.markdown(f"""
<style>
    .stApp {{
        background-color: {pal["app_bg"]};
        color: {pal["text_primary"]};
    }}
    .block-container {{
        padding-top: 1.3rem !important;
        padding-bottom: 6rem !important;
    }}

    /* High-contrast alerts */
    div[data-testid="stAlert"] p, div[data-testid="stAlert"] span, div[data-testid="stAlert"] strong {{
        color: #1e293b !important;
    }}

    /* Metric Cards */
    div[data-testid="stMetric"] {{
        background-color: {pal["card_bg"]};
        border: 1px solid {pal["card_border"]};
        border-top: 3px solid #6366f1;
        border-radius: 14px;
        padding: 16px 20px;
        box-shadow: 0 4px 14px rgba(15, 23, 42, 0.06);
    }}
    div[data-testid="stMetricLabel"] {{
        color: {pal["text_muted"]};
        font-weight: 600;
        font-size: 13px;
    }}
    div[data-testid="stMetricValue"] {{
        color: {pal["text_primary"]};
        font-weight: 700;
    }}

    /* Modern Multi-Color Pill Tabs */
    .stTabs [data-baseweb="tab-list"] {{
        gap: 6px;
        background-color: {pal["tab_bg"]};
        padding: 6px;
        border-radius: 14px;
        border: 1px solid {pal["card_border"]};
        box-shadow: 0 2px 8px rgba(15, 23, 42, 0.05);
        flex-wrap: wrap;
    }}
    .stTabs [data-baseweb="tab"] {{
        border-radius: 10px;
        padding: 7px 13px;
        font-weight: 600;
        font-size: 13px;
        color: {pal["tab_text"]};
    }}
    .stTabs [aria-selected="true"] {{
        background: {pal["active_grad"]} !important;
        color: #ffffff !important;
    }}

    /* Sleek Buttons */
    .stButton > button, .stFormSubmitButton > button {{
        background: {pal["btn_grad"]};
        color: #ffffff;
        border: none;
        border-radius: 10px;
        font-weight: 600;
        padding: 0.45rem 1.1rem;
        transition: all 0.2s ease;
        box-shadow: 0 3px 10px {pal["btn_shadow"]};
    }}
    .stButton > button:hover, .stFormSubmitButton > button:hover {{
        transform: translateY(-1px);
        filter: brightness(1.06);
        color: #ffffff;
    }}

    /* Cards for Forms & Containers */
    div[data-testid="stForm"] {{
        background-color: {pal["card_bg"]};
        border: 1px solid {pal["card_border"]};
        border-radius: 14px;
        padding: 16px;
        box-shadow: 0 4px 14px rgba(15, 23, 42, 0.06);
    }}

    /* Floating Bottom-Right Launcher Button */
    .st-key-floating_ai_btn {{
        position: fixed;
        bottom: 24px;
        right: 24px;
        z-index: 9999;
        width: auto !important;
    }}
    .st-key-floating_ai_btn button {{
        background: {pal["active_grad"]} !important;
        color: #ffffff !important;
        border: 2px solid #fbbf24 !important;
        border-radius: 999px !important;
        padding: 12px 20px !important;
        font-weight: 600 !important;
        box-shadow: 0 8px 24px rgba(79, 70, 229, 0.35) !important;
    }}

    /* Floating Bottom-Right Open Chat Window */
    .st-key-floating_ai_window {{
        position: fixed;
        bottom: 20px;
        right: 20px;
        width: 390px;
        max-width: 92vw;
        background-color: {pal["card_bg"]};
        color: {pal["text_primary"]};
        border: 2px solid #7c3aed;
        border-radius: 16px;
        padding: 14px;
        box-shadow: 0 14px 36px rgba(15, 23, 42, 0.32);
        z-index: 9999;
    }}
</style>
""", unsafe_allow_html=True)

AVATAR_DIR = "avatars"
os.makedirs(AVATAR_DIR, exist_ok=True)

DEMO_TRANSACTIONS = [
    {"date": "2026-10-02", "merchant": "NETFLIX", "amount": 499.0, "category": "Subscriptions", "source": "demo"},
    {"date": "2026-10-05", "merchant": "ZOMATO", "amount": 4200.0, "category": "Dining", "source": "demo"},
    {"date": "2026-10-07", "merchant": "SPOTIFY INDIA", "amount": 119.0, "category": "Subscriptions", "source": "demo"},
    {"date": "2026-10-10", "merchant": "SWIGGY INSTAMART", "amount": 3500.0, "category": "Groceries", "source": "demo"},
    {"date": "2026-10-14", "merchant": "CHAI POINT BLR", "amount": 1800.0, "category": "Dining", "source": "demo"},
    {"date": "2026-10-18", "merchant": "UBER INDIA", "amount": 1450.0, "category": "Transport", "source": "demo"},
    {"date": "2026-11-02", "merchant": "NETFLIX", "amount": 649.0, "category": "Subscriptions", "source": "demo"},
    {"date": "2026-11-07", "merchant": "SPOTIFY INDIA", "amount": 119.0, "category": "Subscriptions", "source": "demo"},
    {"date": "2026-11-11", "merchant": "CHAI POINT BLR", "amount": 2200.0, "category": "Dining", "source": "demo"},
    {"date": "2026-11-15", "merchant": "ZOMATO", "amount": 5500.0, "category": "Dining", "source": "demo"},
    {"date": "2026-11-18", "merchant": "AMAZON PAY", "amount": 3200.0, "category": "Shopping", "source": "demo"},
]

MULTI_COLOR_PALETTE = ["#6366f1", "#ec4899", "#f59e0b", "#06b6d4", "#8b5cf6", "#10b981", "#f97316", "#3b82f6"]

INVESTMENT_BUCKETS = [
    "Equity / Index Bucket",
    "Debt / Fixed Income Bucket",
    "Gold & Commodities Bucket",
    "Liquid Emergency Reserve",
]

MARKET_PULSE_DATA = pd.DataFrame([
    {"Asset Class": "Equity / Broad Index", "Trend Signal": "📈 Volatile / Up-Down", "Volatility": "High", "Est. Role": "Long-Term Growth (5+ yrs)"},
    {"Asset Class": "Debt / Fixed Income", "Trend Signal": "⚖️ Steady Yield", "Volatility": "Low", "Est. Role": "Stability & Cushion"},
    {"Asset Class": "Gold / Commodities", "Trend Signal": "🪙 Hedge Active", "Volatility": "Medium", "Est. Role": "Inflation & Dip Hedge"},
    {"Asset Class": "Liquid / Money Market", "Trend Signal": "💧 High Liquidity", "Volatility": "Very Low", "Est. Role": "Emergency & Cash Buffer"},
])


def get_avatar_path(username):
    return os.path.join(AVATAR_DIR, f"{username}.png")


def get_avatar_html(username):
    path = get_avatar_path(username)
    if os.path.exists(path):
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        return f'<img src="data:image/png;base64,{b64}" style="width:44px;height:44px;border-radius:50%;object-fit:cover;border:2px solid #8b5cf6;box-shadow:0 2px 8px rgba(139,92,246,0.35);" />'
    return (
        '<div style="width:44px;height:44px;border-radius:50%;'
        'background:linear-gradient(135deg,#eef2ff,#fae8ff);color:#4f46e5;'
        'border:2px dashed #6366f1;display:flex;align-items:center;'
        'justify-content:center;font-weight:700;font-size:22px;'
        'box-shadow:0 2px 6px rgba(0,0,0,0.08);">+</div>'
    )


def clear_user_transactions(username):
    conn = db.get_conn()
    conn.execute("DELETE FROM transactions WHERE username = ?", (db._norm_user(username),))
    conn.commit()
    conn.close()


def style_plotly_fig(fig, palette: dict):
    fig.update_layout(
        paper_bgcolor=palette["chart_bg"],
        plot_bgcolor=palette["chart_bg"],
        font=dict(color=palette["chart_text"], size=13),
        title=dict(font=dict(color=palette["chart_text"], size=16)),
        legend=dict(
            font=dict(color=palette["chart_text"], size=13),
            bgcolor=palette["chart_bg"],
            bordercolor=palette["card_border"],
        ),
        margin=dict(t=50, b=25, l=20, r=20),
    )
    return fig


def build_header_html(palette: dict) -> str:
    return f"""
    <div style="
        background: {palette["header_grad"]};
        padding: 14px 22px;
        border-radius: 16px;
        border: 1px solid rgba(255,255,255,0.12);
        box-shadow: 0 8px 22px rgba(30, 27, 75, 0.22);
        color: #ffffff;
    ">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:4px;">
            <span style="font-size:17px;" title="Prosperity">🪷</span>
            <span style="font-size:17px;" title="Smart Banking">🏛️</span>
            <span style="font-size:17px;" title="Wealth">🪙</span>
            <span style="font-size:17px;" title="Growth">📈</span>
            <span style="font-size:17px;" title="AI Coach">🤖</span>
            <span style="font-size:11px;font-weight:700;color:{palette["accent_gold"]};letter-spacing:1.1px;margin-left:4px;">
                SMART WEALTH • LIVING MONEY MODEL
            </span>
        </div>
        <div style="
            font-size: 24px;
            font-weight: 700;
            letter-spacing: -0.3px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            color: #ffffff;
        ">
            💰 Personal Finance Coach — Living Money Model
        </div>
    </div>
    """


HEADER_HTML = build_header_html(pal)

# --- LOGIN / REGISTER SCREEN ---
if not st.session_state.logged_in:
    top_theme_l, top_theme_r = st.columns([6.5, 1.5], vertical_alignment="center")
    with top_theme_r:
        chosen_mode = st.selectbox(
            "Theme",
            ["Light", "Dark"],
            index=0 if st.session_state.theme_mode == "Light" else 1,
            key="login_theme_select",
            label_visibility="collapsed"
        )
        if chosen_mode != st.session_state.theme_mode:
            st.session_state.theme_mode = chosen_mode
            st.rerun()

    st.markdown(HEADER_HTML, unsafe_allow_html=True)
    st.write("")
    col_auth, col_story = st.columns([1.1, 1.9], gap="large")
    with col_auth:
        st.caption("Sign in or create an account to open your dashboard.")
        auth_tab1, auth_tab2 = st.tabs(["🔐 Login", "📝 Register"])

        with auth_tab1:
            with st.form("login_form"):
                l_user = st.text_input("Username")
                l_pass = st.text_input("Password", type="password")
                if st.form_submit_button("Login", use_container_width=True):
                    if db.authenticate_user(l_user, l_pass):
                        st.session_state.logged_in = True
                        st.session_state.username = l_user.strip().lower()
                        st.rerun()
                    else:
                        st.error("Invalid username or password.")

        with auth_tab2:
            with st.form("register_form"):
                r_user = st.text_input("Choose a Username")
                r_pass = st.text_input("Choose a Password", type="password")
                r_pass2 = st.text_input("Confirm Password", type="password")
                if st.form_submit_button("Create Account", use_container_width=True):
                    if r_pass != r_pass2:
                        st.error("Passwords do not match.")
                    else:
                        ok, msg = db.register_user(r_user, r_pass)
                        if ok:
                            st.success(msg)
                        else:
                            st.error(msg)

    with col_story:
        anim_html = """
        <div style="font-family:'Segoe UI',sans-serif;height:330px;border-radius:20px;padding:24px;color:#ffffff;
                    background:linear-gradient(135deg,#1e1b4b 0%,#4338ca 52%,#0284c7 100%);
                    display:flex;flex-direction:column;justify-content:space-between;
                    box-shadow:0 14px 32px rgba(30,27,75,0.28);border:1px solid rgba(255,255,255,0.2);
                    perspective:900px;">
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <span style="font-size:12px;font-weight:700;letter-spacing:1.2px;color:#fbbf24;">
                    LIVING MONEY STORY • 3D STAGE
                </span>
                <span id="stage_badge" style="font-size:11px;background:rgba(255,255,255,0.16);
                      padding:4px 10px;border-radius:999px;">Scene 1 / 3</span>
            </div>

            <div id="stage_box" style="text-align:center;transition:all 0.35s ease;transform:rotateY(0deg);">
                <div id="a_emoji" style="font-size:56px;line-height:1.15;">👫 💵 🤔</div>
                <div id="a_head" style="font-size:21px;font-weight:700;margin-top:10px;">
                    ₹4,00,000 in Hand — Par Kya Karein?
                </div>
                <div id="a_sub" style="font-size:13.5px;color:#e0e7ff;margin-top:6px;">
                    Couple confused hai: smartly invest karein, goals banayein, ya foreign trip plan karein?
                </div>
                <div id="a_pills" style="margin-top:14px;display:flex;justify-content:center;gap:8px;flex-wrap:wrap;">
                    <span style="background:rgba(251,191,36,0.22);border:1px solid #fbbf24;padding:4px 10px;border-radius:8px;font-size:12px;">❓ Where to Invest?</span>
                    <span style="background:rgba(255,255,255,0.14);border:1px solid rgba(255,255,255,0.3);padding:4px 10px;border-radius:8px;font-size:12px;">✈️ Trip Budget?</span>
                </div>
            </div>

            <div style="display:flex;justify-content:center;gap:8px;">
                <span id="d0" style="width:10px;height:10px;border-radius:50%;background:#fbbf24;"></span>
                <span id="d1" style="width:10px;height:10px;border-radius:50%;background:rgba(255,255,255,0.35);"></span>
                <span id="d2" style="width:10px;height:10px;border-radius:50%;background:rgba(255,255,255,0.35);"></span>
            </div>
        </div>
        <script>
            const scenes = [
                {
                    badge: "Scene 1 / 3 • Confusion",
                    emoji: "👫 💵 🤔",
                    head: "₹4,00,000 in Hand — Par Kya Karein?",
                    sub: "Couple confused hai: smartly invest karein, goals banayein, ya foreign trip plan karein?",
                    pills: ["❓ Where to Invest?", "✈️ Trip Budget?"]
                },
                {
                    badge: "Scene 2 / 3 • Bulb Idea",
                    emoji: "💡 📱 🚀",
                    head: "Idea Aaya — Living Money Coach Open!",
                    sub: "Dono ne app khola: Proportional Investment, Foreign Trip Agent & AI Guardrails explore kiye.",
                    pills: ["📈 Smart Wealth", "🧭 Foreign Trip Agent", "🛡️ AI Coach"]
                },
                {
                    badge: "Scene 3 / 3 • Happy & Sorted",
                    emoji: "🎉 👫 📈",
                    head: "Dono Happy — Wealth & Trip Sorted!",
                    sub: "Money ka right proportion grow ho raha hai aur trip ka complete budget chart ready hai!",
                    pills: ["✨ Compounding Active", "🌍 Budget Locked"]
                }
            ];
            let idx = 0;
            setInterval(() => {
                idx = (idx + 1) % scenes.length;
                const box = document.getElementById("stage_box");
                box.style.opacity = "0.2";
                box.style.transform = "rotateY(10deg) scale(0.97)";
                setTimeout(() => {
                    const s = scenes[idx];
                    document.getElementById("stage_badge").innerText = s.badge;
                    document.getElementById("a_emoji").innerText = s.emoji;
                    document.getElementById("a_head").innerText = s.head;
                    document.getElementById("a_sub").innerText = s.sub;
                    document.getElementById("a_pills").innerHTML = s.pills
                        .map(p => `<span style="background:rgba(255,255,255,0.16);border:1px solid rgba(255,255,255,0.35);padding:4px 10px;border-radius:8px;font-size:12px;">${p}</span>`)
                        .join("");
                    for (let j = 0; j < 3; j++) {
                        document.getElementById("d" + j).style.background = j === idx ? "#fbbf24" : "rgba(255,255,255,0.35)";
                    }
                    box.style.opacity = "1";
                    box.style.transform = "rotateY(0deg) scale(1)";
                }, 220);
            }, 3200);
        </script>
        """
        components.html(anim_html, height=345)
    st.stop()

current_user = st.session_state.username

# --- TOP BAR: LEFT PROFILE + THEME SWITCHER + RIGHT HEADER ---
top_left, top_right = st.columns([1.5, 4.5], vertical_alignment="center")

with top_left:
    av_col, menu_col, mode_col = st.columns([0.9, 1.9, 1.3], vertical_alignment="center")
    with av_col:
        st.markdown(get_avatar_html(current_user), unsafe_allow_html=True)
    with menu_col:
        with st.popover(f"**{current_user}**", use_container_width=True):
            uploaded_pic = st.file_uploader(
                "Add / Change Profile Photo",
                type=["png", "jpg", "jpeg"],
                key="avatar_uploader"
            )
            if uploaded_pic is not None:
                with open(get_avatar_path(current_user), "wb") as f:
                    f.write(uploaded_pic.getvalue())
                st.rerun()

            st.divider()
            if st.button("➕ Add Person / Switch Account", use_container_width=True):
                st.session_state.logged_in = False
                st.session_state.username = ""
                st.session_state.chat_open = False
                st.rerun()

            if st.button("🚪 Logout", use_container_width=True):
                st.session_state.logged_in = False
                st.session_state.username = ""
                st.session_state.chat_open = False
                st.rerun()
    with mode_col:
        mode_label = "🌙 Dark" if st.session_state.theme_mode == "Light" else "☀️ Light"
        if st.button(mode_label, key="toggle_theme_btn", use_container_width=True):
            st.session_state.theme_mode = "Dark" if st.session_state.theme_mode == "Light" else "Light"
            st.rerun()

with top_right:
    st.markdown(HEADER_HTML, unsafe_allow_html=True)

st.write("")

# --- LOAD PER-USER DATA ---
profile = db.get_profile(username=current_user)
tx_df = db.get_transactions(username=current_user)
goals_df = db.get_goals(username=current_user)
inv_df = get_user_investments(current_user)

tabs = st.tabs([
    "📊 Dashboard & Subscriptions",
    "📥 Upload & Correction Loop",
    "📈 Investment & Portfolio",
    "✈️ Foreign Trip Agent",
    "🔮 What-If Simulator",
    "👤 Profile & Goals",
    "📝 Monthly Report & Coach"
])

# --- TAB 1: DASHBOARD & SUBSCRIPTIONS ---
with tabs[0]:
    nudges = an.get_drift_nudges(tx_df, profile)
    for n in nudges:
        st.warning(n)

    col1, col2, col3, col4 = st.columns(4)
    total_spent = tx_df[tx_df["category"] != "Income"]["amount"].sum() if not tx_df.empty else 0
    total_invested = float(inv_df["amount"].sum()) if not inv_df.empty else 0.0
    col1.metric("Monthly Income", f"₹{profile['monthly_income']:,.0f}")
    col2.metric("Fixed Costs", f"₹{profile['fixed_costs']:,.0f}")
    col3.metric("Tracked Spending", f"₹{total_spent:,.0f}")
    col4.metric("Invested Portfolio", f"₹{total_invested:,.0f}")

    st.write("")
    if not tx_df.empty:
        fig = px.pie(
            tx_df[tx_df["category"] != "Income"],
            values="amount", names="category",
            title="Spending Breakdown by Category", hole=0.45,
            color_discrete_sequence=MULTI_COLOR_PALETTE,
            template=pal["plot_template"]
        )
        fig.update_traces(
            textfont=dict(color="#ffffff", size=13),
            hoverinfo="label+percent+value"
        )
        style_plotly_fig(fig, pal)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No transactions yet. Go to the **Upload & Correction Loop** tab to add CSV, PDF, SMS, or 1-Click Demo data.")

    st.subheader("🔄 Recurring Payments & Subscriptions")
    subs = an.detect_subscriptions(tx_df)
    if subs:
        alert_items = [
            s for s in subs
            if "Price Hike" in s.get("Price Alert", "")
            or "Price Drop" in s.get("Price Alert", "")
            or "Unused" in s.get("Usage Alert", "")
        ]
        if alert_items:
            for item in alert_items:
                st.info(
                    f"**{item['Merchant']}** ({item['Latest Amount']}) — "
                    f"{item['Price Alert']}  |  {item['Usage Alert']}"
                )
        st.dataframe(pd.DataFrame(subs), use_container_width=True, hide_index=True)
    else:
        st.caption("Upload transactions spanning 2+ months to automatically detect recurring subscriptions and price hikes.")

# --- TAB 2: UPLOAD & CORRECTION LOOP ---
with tabs[1]:
    st.subheader("⚡ Quick Demo Sandbox")
    d_col1, d_col2 = st.columns([2, 1], vertical_alignment="center")
    with d_col1:
        if st.button("⚡ Load 2-Month Sample Data", use_container_width=True):
            applied, _ = ing.apply_learned_rules(
                [dict(t) for t in DEMO_TRANSACTIONS],
                username=current_user
            )
            db.add_transactions(applied, username=current_user)
            st.success(f"Loaded {len(applied)} sample transactions across Oct & Nov 2026!")
            st.rerun()
    with d_col2:
        if st.button("🧹 Clear Transactions", use_container_width=True):
            clear_user_transactions(current_user)
            st.info("Cleared your transactions.")
            st.rerun()

    st.divider()
    st.subheader("Ingest Messy Bank Statements (PDF, CSV, or SMS)")
    input_type = st.radio("Choose input format:", ["Paste SMS / Raw Text", "Upload CSV", "Upload PDF"], horizontal=True)

    if input_type == "Paste SMS / Raw Text":
        sms_text = st.text_area(
            "Paste messy bank SMS alerts or raw text:",
            height=120,
            placeholder="Rs. 450 debited at ZOMATO on 2026-10-12 via UPI..."
        )
        if st.button("Extract & Categorize"):
            with st.spinner("Parsing with Gemini + applying your learned rules..."):
                txs, rules_hit = ing.parse_text_or_csv(sms_text, source="sms", username=current_user)
                db.add_transactions(txs, username=current_user)
                st.success(f"Added {len(txs)} transactions! (Auto-applied {rules_hit} learned rules)")
                st.rerun()

    elif input_type == "Upload CSV":
        csv_file = st.file_uploader("Upload bank CSV", type=["csv"])
        if csv_file and st.button("Extract CSV"):
            with st.spinner("Parsing CSV + applying learned rules..."):
                raw_csv = csv_file.getvalue().decode("utf-8", errors="ignore")
                txs, rules_hit = ing.parse_text_or_csv(raw_csv, source="csv", username=current_user)
                db.add_transactions(txs, username=current_user)
                st.success(f"Added {len(txs)} transactions! (Auto-applied {rules_hit} learned rules)")
                st.rerun()

    elif input_type == "Upload PDF":
        pdf_file = st.file_uploader("Upload bank statement PDF", type=["pdf"])
        if pdf_file and st.button("Extract PDF"):
            with st.spinner("Reading PDF with Gemini + applying learned rules..."):
                txs, rules_hit = ing.parse_pdf(pdf_file.getvalue(), source="pdf", username=current_user)
                db.add_transactions(txs, username=current_user)
                st.success(f"Added {len(txs)} transactions! (Auto-applied {rules_hit} learned rules)")
                st.rerun()

    st.divider()
    st.subheader("🧠 Correction Loop (Edit any category to teach the agent)")
    if not tx_df.empty:
        edited_df = st.data_editor(
            tx_df[["id", "date", "merchant", "amount", "category"]],
            column_config={
                "category": st.column_config.SelectboxColumn("Category", options=ing.CATEGORIES)
            },
            disabled=["id", "date", "merchant", "amount"],
            hide_index=True,
            use_container_width=True
        )
        if st.button("Save Corrections & Learn Rules"):
            changes = 0
            for idx, row in edited_df.iterrows():
                orig_cat = tx_df.loc[tx_df["id"] == row["id"], "category"].values[0]
                if row["category"] != orig_cat:
                    db.update_transaction_category(row["id"], row["category"], username=current_user)
                    db.save_rule(row["merchant"], row["category"], username=current_user)
                    changes += 1
            if changes > 0:
                st.success(f"Saved {changes} correction(s)! Future uploads for these merchants will auto-categorize.")
                st.rerun()
            else:
                st.info("No category changes detected.")

    with st.expander("View Learned Memory Rules"):
        st.json(db.get_rules(username=current_user))

# --- TAB 3: INVESTMENT & PROPORTIONAL WEALTH ENGINE ---
with tabs[2]:
    st.subheader("📈 Smart Wealth & Proportional Investment Engine")
    st.caption("Combine your investable money, risk appetite, and current market mood to get a dynamic proportional split & compounding projection. (Educational allocation framework—no individual stock tips.)")

    est_surplus = max(float(profile["monthly_income"]) - float(profile["fixed_costs"]) - float(total_spent) * 0.5, 10000.0)
    ctrl1, ctrl2, ctrl3, ctrl4 = st.columns([1.3, 1.2, 1.4, 1.1])
    with ctrl1:
        monthly_invest = st.number_input("Monthly Investable Money (₹)", min_value=1000.0, value=float(round(est_surplus / 1000) * 1000), step=1000.0)
    with ctrl2:
        risk_mode = st.selectbox("Risk Appetite", ["Conservative", "Balanced", "Growth"], index=1)
    with ctrl3:
        market_mood = st.selectbox("Current Market Condition", ["🟢 Bullish / Uptrend", "🟡 Volatile / Sideways", "🔴 Correction / Dip"], index=1)
    with ctrl4:
        horizon_yrs = st.slider("Horizon (Years)", min_value=1, max_value=20, value=10)

    weights, blended_rate, strategy_note = compute_proportional_allocation(risk_mode, market_mood)
    st.info(f"**Market Strategy ({market_mood} • {risk_mode}):** {strategy_note}")

    b_cols = st.columns(4)
    alloc_rows = []
    for idx, (b_name, pct) in enumerate(weights.items()):
        amt = round(monthly_invest * (pct / 100.0))
        alloc_rows.append({"Bucket": b_name, "Share (%)": pct, "Monthly (₹)": amt})
        b_cols[idx].metric(b_name.replace(" Bucket", ""), f"₹{amt:,.0f}/mo", f"{pct}% Share")

    st.write("")
    ch_l, ch_r = st.columns([1, 1.4])
    alloc_df = pd.DataFrame(alloc_rows)

    with ch_l:
        fig_alloc = px.pie(
            alloc_df,
            values="Monthly (₹)",
            names="Bucket",
            title="Recommended Proportional Split",
            hole=0.45,
            color_discrete_sequence=MULTI_COLOR_PALETTE,
            template=pal["plot_template"],
        )
        fig_alloc.update_traces(textfont=dict(color="#ffffff", size=12))
        style_plotly_fig(fig_alloc, pal)
        st.plotly_chart(fig_alloc, use_container_width=True)

    with ch_r:
        years_axis = list(range(1, horizon_yrs + 1))
        portfolio_curve = project_sip_growth(monthly_invest, blended_rate, horizon_yrs)
        savings_curve = project_sip_growth(monthly_invest, 0.04, horizon_yrs)
        invested_curve = [round(monthly_invest * 12 * y) for y in years_axis]

        fig_growth = go.Figure()
        fig_growth.add_trace(go.Scatter(
            x=years_axis, y=portfolio_curve, mode="lines+markers",
            name=f"Smart Portfolio (~{blended_rate*100:.1f}% est.)",
            line=dict(color="#6366f1", width=3)
        ))
        fig_growth.add_trace(go.Scatter(
            x=years_axis, y=savings_curve, mode="lines",
            name="Bank Savings (~4.0%)",
            line=dict(color="#f59e0b", width=2, dash="dash")
        ))
        fig_growth.add_trace(go.Scatter(
            x=years_axis, y=invested_curve, mode="lines",
            name="Total Money Invested",
            line=dict(color="#94a3b8", width=2, dash="dot")
        ))
        fig_growth.update_layout(
            title=f"{horizon_yrs}-Year Wealth Projection (₹{monthly_invest:,.0f}/mo)",
            xaxis_title="Years",
            yaxis_title="Estimated Value (₹)",
        )
        style_plotly_fig(fig_growth, pal)
        st.plotly_chart(fig_growth, use_container_width=True)

    tot_invested_h = invested_curve[-1]
    est_corpus_h = portfolio_curve[-1]
    extra_vs_bank = est_corpus_h - savings_curve[-1]

    m1, m2, m3, m4 = st.columns([1.2, 1.2, 1.2, 1.4], vertical_alignment="center")
    m1.metric(f"Total Invested ({horizon_yrs}y)", f"₹{tot_invested_h:,.0f}")
    m2.metric("Projected Corpus", f"₹{est_corpus_h:,.0f}", f"+₹{est_corpus_h - tot_invested_h:,.0f} gain")
    m3.metric("Extra vs. Bank Savings", f"+₹{extra_vs_bank:,.0f}")
    with m4:
        if st.button("⚡ Apply This Plan to My Portfolio", use_container_width=True):
            today_str = str(datetime.date.today())
            for row in alloc_rows:
                if row["Monthly (₹)"] > 0:
                    add_user_investment(
                        current_user,
                        row["Bucket"],
                        f"Auto Plan ({risk_mode})",
                        row["Monthly (₹)"],
                        today_str,
                    )
            st.success("Applied proportional plan to your portfolio!")
            st.rerun()

    st.divider()
    inv_left, inv_right = st.columns([1.1, 1.9])
    with inv_left:
        st.markdown("#### ➕ Add Custom Investment")
        with st.form("investment_form"):
            inv_bucket = st.selectbox("Investment Bucket", INVESTMENT_BUCKETS)
            inv_label = st.text_input("Label / Note", placeholder="e.g., Monthly SIP / FD / Gold ETF")
            inv_amt = st.number_input("Amount (₹)", min_value=100.0, value=10000.0, step=500.0)
            inv_date = st.date_input("Date")
            if st.form_submit_button("Add Entry", use_container_width=True):
                add_user_investment(current_user, inv_bucket, inv_label, inv_amt, str(inv_date))
                st.success("Investment entry added!")
                st.rerun()

    with inv_right:
        st.markdown("#### 🌐 Market Pulse & Your Saved Portfolio")
        st.dataframe(MARKET_PULSE_DATA, use_container_width=True, hide_index=True)

        if not inv_df.empty:
            st.metric("Total Saved Portfolio Capital", f"₹{inv_df['amount'].sum():,.0f}")
            for _, item in inv_df.iterrows():
                i_id = int(item["id"])
                with st.container(border=True):
                    c_info, c_del = st.columns([5, 1], vertical_alignment="center")
                    with c_info:
                        st.markdown(f"**{item['bucket']}** — {item['label']} • **₹{float(item['amount']):,.0f}** (`{item['updated_at']}`)")
                    with c_del:
                        if st.button("🗑️", key=f"del_inv_{i_id}", use_container_width=True):
                            delete_user_investment(i_id, current_user)
                            st.rerun()
        else:
            st.info("No saved investments yet. Click **⚡ Apply This Plan to My Portfolio** above or add a custom entry.")

# --- TAB 4: FOREIGN TRIP AGENT ---
with tabs[3]:
    st.subheader("✈️ Foreign Trip Planner Agent")
    st.caption("Enter your budget (like ₹1,00,000) and foreign country—the agent builds a complete budget chart & trip plan.")

    with st.form("foreign_trip_form"):
        t_col1, t_col2, t_col3 = st.columns([2, 1.5, 1])
        with t_col1:
            trip_dest = st.text_input("Foreign Country / Destination", value="Vietnam", placeholder="e.g., Vietnam, Thailand, Bali, Dubai")
        with t_col2:
            trip_budget = st.number_input("Total Trip Budget (₹)", min_value=10000.0, value=100000.0, step=5000.0)
        with t_col3:
            trip_days = st.number_input("Days", min_value=1, max_value=30, value=5, step=1)

        t_col4, t_col5 = st.columns([1, 3])
        with t_col4:
            trip_people = st.number_input("Travelers", min_value=1, max_value=10, value=1, step=1)
        with t_col5:
            trip_notes = st.text_input("Preferences (optional)", placeholder="e.g., budget-friendly food, beaches, city tour")

        if st.form_submit_button("🧭 Plan My Foreign Trip", use_container_width=True):
            with st.spinner("Trip Agent is calculating flights, stay, food & itinerary..."):
                st.session_state.trip_result = ai.plan_foreign_trip(
                    destination=trip_dest,
                    budget=trip_budget,
                    days=int(trip_days),
                    travelers=int(trip_people),
                    notes=trip_notes,
                )

    if st.session_state.trip_result:
        res_t = st.session_state.trip_result
        b_df = pd.DataFrame(res_t["breakdown"])
        st.markdown(f"### 🌍 Budget Chart for **{res_t['destination']}** (Total: ₹{float(res_t['budget']):,.0f})")

        ch_col, tbl_col = st.columns([1.2, 1.8])
        with ch_col:
            fig_trip = px.pie(
                b_df,
                values="Allocated (₹)",
                names="Category",
                title="Trip Budget Split",
                hole=0.42,
                color_discrete_sequence=MULTI_COLOR_PALETTE,
                template=pal["plot_template"],
            )
            fig_trip.update_traces(textfont=dict(color="#ffffff", size=12))
            style_plotly_fig(fig_trip, pal)
            st.plotly_chart(fig_trip, use_container_width=True)

        with tbl_col:
            st.dataframe(b_df, use_container_width=True, hide_index=True)

        st.markdown(res_t["itinerary"])

# --- TAB 5: WHAT-IF SIMULATOR ---
with tabs[4]:
    st.subheader("🔮 What-If Goal Simulator")
    if goals_df.empty:
        st.info("Add at least one goal in the **Profile & Goals** tab first.")
    else:
        selected_goal_name = st.selectbox("Select Goal to Simulate:", goals_df["name"].tolist())
        goal_row = goals_df[goals_df["name"] == selected_goal_name].iloc[0]

        scenario = st.text_input(
            "Ask a What-If scenario:",
            placeholder="e.g., What if I cut dining out by 30% and my rent goes up by 2000?"
        )
        if st.button("Run Simulation") and scenario:
            with st.spinner("Modeling scenario..."):
                adj = ai.parse_what_if_query(scenario, ing.CATEGORIES)
                res = an.run_what_if_simulation(tx_df, profile, goal_row, adj)

                st.info(f"**Scenario Modeled:** {adj.get('summary', scenario)}")
                c1, c2, c3 = st.columns(3)
                c1.metric("Current Monthly Surplus", f"₹{res['baseline_surplus']:,.0f}")
                c2.metric(
                    "Simulated Monthly Surplus",
                    f"₹{res['sim_surplus']:,.0f}",
                    delta=f"₹{res['sim_surplus'] - res['baseline_surplus']:,.0f}"
                )
                c3.metric(
                    "Months to Goal",
                    f"{res['sim_months']} mos",
                    delta=f"{res['months_diff']} mos faster" if res['months_diff'] >= 0 else f"{abs(res['months_diff'])} mos slower"
                )

                chart_df = pd.DataFrame({
                    "Path": ["Current Path", "Simulated Path"],
                    "Months to Reach Goal": [res["baseline_months"], res["sim_months"]]
                })
                fig_bar = px.bar(
                    chart_df, x="Path", y="Months to Reach Goal", color="Path",
                    color_discrete_sequence=["#ec4899", "#6366f1"],
                    template=pal["plot_template"]
                )
                style_plotly_fig(fig_bar, pal)
                st.plotly_chart(fig_bar, use_container_width=True)

# --- TAB 6: PROFILE & GOALS ---
with tabs[5]:
    st.subheader("Persistent Financial Profile")
    with st.form("profile_form"):
        inc = st.number_input("Monthly Income (₹)", value=float(profile["monthly_income"]), step=1000.0)
        fix = st.number_input("Monthly Fixed Costs / Rent (₹)", value=float(profile["fixed_costs"]), step=1000.0)
        em_cur = st.number_input("Current Emergency Fund (₹)", value=float(profile["emergency_fund"]), step=1000.0)
        em_tgt = st.number_input("Emergency Fund Target (₹)", value=float(profile["emergency_target"]), step=5000.0)
        if st.form_submit_button("Save Profile"):
            db.update_profile(current_user, inc, fix, em_cur, em_tgt)
            st.success("Financial profile updated!")
            st.rerun()

    st.divider()
    st.subheader("Financial Goals")
    with st.form("goal_form"):
        g_name = st.text_input("Goal Name", placeholder="e.g., Goa Trip / New Laptop")
        g_target = st.number_input("Target Amount (₹)", min_value=1000.0, value=50000.0, step=1000.0)
        g_saved = st.number_input("Already Saved (₹)", min_value=0.0, value=5000.0, step=1000.0)
        g_date = st.date_input("Target Date")
        if st.form_submit_button("Add Goal") and g_name:
            db.add_goal(current_user, g_name, g_target, g_saved, str(g_date))
            st.success(f"Added goal: {g_name}")
            st.rerun()

    if not goals_df.empty:
        st.write("### Active Goal Progress")
        for _, g in goals_df.iterrows():
            g_id = int(g["id"])
            target = max(float(g["target_amount"]), 1.0)
            saved = float(g["saved_amount"])
            pct = min(max(saved / target, 0.0), 1.0)
            remaining = max(target - saved, 0.0)

            with st.container(border=True):
                top_c, del_c = st.columns([5, 1], vertical_alignment="center")
                with top_c:
                    st.markdown(f"**🎯 {g['name']}** — Target Date: `{g['target_date']}`")
                with del_c:
                    if st.button("🗑️ Delete", key=f"del_goal_{g_id}", use_container_width=True):
                        db.delete_goal(g_id, username=current_user)
                        st.rerun()

                st.progress(pct, text=f"₹{saved:,.0f} / ₹{target:,.0f} ({pct*100:.1f}%) • Remaining: ₹{remaining:,.0f}")

                add_col, set_col = st.columns([1.5, 1.5], vertical_alignment="bottom")
                with add_col:
                    quick_add = st.number_input(
                        "Add amount (₹)",
                        min_value=0.0,
                        value=2000.0,
                        step=500.0,
                        key=f"add_amt_{g_id}"
                    )
                    if st.button("➕ Add to Saved", key=f"btn_add_{g_id}", use_container_width=True):
                        db.update_goal_saved(g_id, saved + quick_add, username=current_user)
                        st.rerun()
                with set_col:
                    exact_val = st.number_input(
                        "Set total saved (₹)",
                        min_value=0.0,
                        value=float(saved),
                        step=1000.0,
                        key=f"set_amt_{g_id}"
                    )
                    if st.button("💾 Update Saved", key=f"btn_set_{g_id}", use_container_width=True):
                        db.update_goal_saved(g_id, exact_val, username=current_user)
                        st.rerun()

# --- TAB 7: MONTHLY REPORT & GUARDRAILED COACH ---
with tabs[6]:
    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("📝 Monthly Review Report")
        if st.button("Generate Monthly Report"):
            with st.spinner("Compiling your Living Money Model report..."):
                subs = an.detect_subscriptions(tx_df)
                report = ai.generate_monthly_report(profile, goals_df, tx_df, subs)
                st.markdown(report)

    with col_right:
        st.subheader("💬 Guardrailed Finance Coach")
        user_q = st.text_input(
            "Ask your coach anything:",
            placeholder="Try: 'How can I reach my goal faster?' or 'Which stock should I buy?'"
        )
        if st.button("Ask Coach") and user_q:
            with st.spinner("Thinking..."):
                reply = ai.ask_coach(user_q, profile, goals_df, tx_df)
                st.markdown(reply)

# --- FLOATING BOTTOM-RIGHT AI AGENT (ALWAYS AVAILABLE AFTER LOGIN) ---
if not st.session_state.chat_open:
    with st.container(key="floating_ai_btn"):
        if st.button("🤖 If you have any doubt, ask me", key="open_ai_agent"):
            st.session_state.chat_open = True
            st.rerun()
else:
    with st.container(key="floating_ai_window"):
        hdr_col, close_col = st.columns([4.5, 1], vertical_alignment="center")
        with hdr_col:
            st.markdown("**🤖 AI Finance Agent** *(Hindi / English)*")
        with close_col:
            if st.button("✖", key="close_ai_agent", use_container_width=True):
                st.session_state.chat_open = False
                st.rerun()

        chat_box = st.container(height=270)
        with chat_box:
            for msg in st.session_state.assistant_messages:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

        with st.form("floating_chat_form", clear_on_submit=True):
            q_col, btn_col = st.columns([3.3, 1.2])
            with q_col:
                doubt = st.text_input(
                    "Ask a question",
                    placeholder="Type your question...",
                    label_visibility="collapsed"
                )
            with btn_col:
                send = st.form_submit_button("Send", use_container_width=True)

            if send and doubt.strip():
                st.session_state.assistant_messages.append({"role": "user", "content": doubt})
                with st.spinner("Thinking..."):
                    ans = ai.ask_coach(
                        doubt,
                        profile,
                        goals_df,
                        tx_df,
                        chat_history=st.session_state.assistant_messages
                    )
                st.session_state.assistant_messages.append({"role": "assistant", "content": ans})
                st.rerun()