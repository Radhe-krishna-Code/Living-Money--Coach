import os
import re
import json
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

MODEL_CANDIDATES = [
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
    "gemini-3-flash-preview",
]


def get_client():
    raw_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
    api_key = raw_key.strip().strip('"').strip("'")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is missing in .env file.")
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=12000),
    )


def _call_gemini_fast(contents, system_instruction=None, json_mode=False):
    client = get_client()
    last_error = None

    for model_id in MODEL_CANDIDATES:
        try:
            config = types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json" if json_mode else "text/plain",
                temperature=0.35,
            )
            response = client.models.generate_content(
                model=model_id,
                contents=contents,
                config=config,
            )
            if response and response.text and response.text.strip():
                return response.text.strip()
        except Exception as e:
            last_error = e
            continue

    raise RuntimeError(f"Gemini unavailable: {last_error}")


def _quick_what_if_fallback(query: str, available_categories: list[str]) -> dict:
    q = (query or "").lower()
    pct_changes = {}

    pct_matches = re.findall(r"(?:cut|reduce|trim|lower|less)\s+([a-zA-Z\s&]+?)\s+(?:by\s+)?(\d+)\s*%", q)
    for raw_cat, pct_str in pct_matches:
        pct = float(pct_str) / 100.0
        cat_clean = raw_cat.strip().lower()
        matched_cat = None
        for c in available_categories:
            if c.lower() in cat_clean or cat_clean in c.lower():
                matched_cat = c
                break
        if not matched_cat and ("food" in cat_clean or "dining" in cat_clean or "eat" in cat_clean):
            matched_cat = "Dining"
        if matched_cat:
            pct_changes[matched_cat] = -pct

    if not pct_changes and ("dining" in q or "food" in q or "zomato" in q or "swiggy" in q):
        pct_changes["Dining"] = -0.25

    fixed_delta = 0.0
    rent_up = re.search(r"(?:rent|fixed|cost)[^\d]*(?:up|increase|add|plus|\+)[^\d]*(\d+(?:,\d+)*)", q)
    if rent_up:
        fixed_delta += float(rent_up.group(1).replace(",", ""))
    rent_down = re.search(r"(?:rent|fixed|cost)[^\d]*(?:down|decrease|cut|reduce|save|-)[^\d]*(\d+(?:,\d+)*)", q)
    if rent_down:
        fixed_delta -= float(rent_down.group(1).replace(",", ""))

    income_delta = 0.0
    inc_up = re.search(r"(?:salary|income|side\s*hustle|earn|bonus)[^\d]*(?:up|increase|add|plus|\+|by)[^\d]*(\d+(?:,\d+)*)", q)
    if inc_up:
        income_delta += float(inc_up.group(1).replace(",", ""))

    return {
        "category_pct_change": pct_changes,
        "fixed_cost_delta": fixed_delta,
        "income_delta": income_delta,
        "summary": f"Simulated scenario: {query}",
    }


def _local_fallback_reply(user_message: str, profile: dict, goals_df, tx_df) -> str:
    msg = (user_message or "").lower()
    blocked_phrases = [
        "which stock", "buy stock", "best crypto", "should i buy", "which mutual fund",
        "recommend a stock", "kaunsa stock", "konsa stock", "share kharidu", "stock lu", "crypto lu"
    ]
    if any(p in msg for p in blocked_phrases):
        return (
            "🛡️ **Guardrail Active:** I cannot recommend specific stocks, mutual funds, or cryptocurrencies. "
            f"I can help you structure a savings plan, build your ₹{float(profile.get('emergency_target', 150000)):,.0f} "
            "emergency fund, or model budget scenarios."
        )

    salary = float(profile.get("monthly_income") or 80000)
    fixed = float(profile.get("fixed_costs") or 25000)
    spent = float(tx_df[tx_df["category"] != "Income"]["amount"].sum()) if (tx_df is not None and not tx_df.empty) else 0.0
    surplus = max(salary - fixed - spent, salary * 0.20)
    needs = salary * 0.50
    wants = salary * 0.25
    invest = salary * 0.25

    goals_line = ""
    if goals_df is not None and not goals_df.empty:
        g_names = ", ".join([str(x) for x in goals_df["name"].tolist()[:3]])
        goals_line = f"\n- **Active Goals:** {g_names}"

    return (
        f"**Living Money Plan (Monthly Income: ₹{salary:,.0f} | Estimated Surplus: ₹{surplus:,.0f}):**\n"
        f"- **Needs (~50%):** ₹{needs:,.0f} (Rent/Fixed: ₹{fixed:,.0f}, essentials)\n"
        f"- **Lifestyle & Wants (~25%):** ₹{wants:,.0f} (Tracked spend: ₹{spent:,.0f})\n"
        f"- **Savings & Goal Investments (~25%):** ₹{invest:,.0f}/month{goals_line}\n\n"
        "**Next Steps:** Keep 3–6 months of core expenses in a liquid emergency buffer first, automate monthly goal contributions, and trim high-drift categories."
    )


def _fallback_trip_plan(destination: str, budget: float, days: int, travelers: int, notes: str) -> dict:
    dest = (destination or "Vietnam").strip()
    b = max(float(budget or 100000), 10000.0)
    d = max(int(days or 5), 1)
    t = max(int(travelers or 1), 1)

    flights = round(b * 0.32)
    hotel = round(b * 0.28)
    food = round(b * 0.18)
    transport_activities = round(b * 0.14)
    contingency = max(round(b - (flights + hotel + food + transport_activities)), 0)

    breakdown = [
        {"Category": "Flights (Round-Trip)", "Allocated (₹)": flights, "Share (%)": round(flights / b * 100, 1), "Notes": f"Est. airfare to {dest} for {t} traveler(s)"},
        {"Category": "Hotel / Stay", "Allocated (₹)": hotel, "Share (%)": round(hotel / b * 100, 1), "Notes": f"{d} nights budget/mid-range stay"},
        {"Category": "Food & Dining", "Allocated (₹)": food, "Share (%)": round(food / b * 100, 1), "Notes": f"~₹{round(food / max(d * t, 1)):,} per person/day"},
        {"Category": "Local Transport & Activities", "Allocated (₹)": transport_activities, "Share (%)": round(transport_activities / b * 100, 1), "Notes": "Cabs, passes, entry tickets & tours"},
        {"Category": "Buffer / SIM / Forex", "Allocated (₹)": contingency, "Share (%)": round(contingency / b * 100, 1), "Notes": "Emergency buffer, roaming/SIM, tips"},
    ]

    itinerary = (
        f"### ✈️ {dest} ({d} Days, {t} Traveler{'s' if t > 1 else ''}) — Budget Plan: ₹{b:,.0f}\n"
        f"- **Flights & Arrival:** Book round-trip flights early and keep ~₹{flights:,.0f} allocated.\n"
        f"- **Stay Strategy:** Target ~₹{round(hotel / d):,}/night total across {d} nights near central transit hubs.\n"
        f"- **Daily Food & Sightseeing:** Keep food around ₹{round(food / max(d * t, 1)):,}/day per person by mixing local spots with occasional restaurants.\n"
        f"- **Smart Tip:** {notes.strip() if notes else 'Carry a zero-forex card plus small cash buffer for local transit and emergencies.'}"
    )

    return {
        "destination": dest,
        "budget": b,
        "breakdown": breakdown,
        "itinerary": itinerary,
    }


def plan_foreign_trip(destination: str, budget: float, days: int, travelers: int, notes: str = "") -> dict:
    fallback = _fallback_trip_plan(destination, budget, days, travelers, notes)
    try:
        prompt = f"""
        You are a Foreign Trip Planner AI Agent. Create a realistic travel budget breakdown and concise itinerary for a traveler from India.
        Destination: {destination}
        Total Budget (INR): ₹{budget:,.0f}
        Duration: {days} days
        Travelers: {travelers}
        Extra preferences: {notes or "Balanced value trip"}

        Return ONLY valid JSON with keys:
        - "breakdown": array of 5 objects, each with:
          * "Category": one of ["Flights (Round-Trip)", "Hotel / Stay", "Food & Dining", "Local Transport & Activities", "Buffer / SIM / Forex"]
          * "Allocated (₹)": integer INR amount (sum of all 5 should stay close to {int(budget)})
          * "Share (%)": number (percentage of total budget)
          * "Notes": concise practical note
        - "itinerary": concise markdown guide covering day-wise flow, booking/forex tips, and staying within ₹{budget:,.0f}.
        """
        raw = _call_gemini_fast(contents=prompt, json_mode=True)
        data = json.loads(raw)
        if isinstance(data, dict) and isinstance(data.get("breakdown"), list) and len(data["breakdown"]) > 0:
            return {
                "destination": destination,
                "budget": float(budget),
                "breakdown": data["breakdown"],
                "itinerary": str(data.get("itinerary") or fallback["itinerary"]),
            }
    except Exception:
        pass
    return fallback


BASE_SYSTEM_RULES = """
You are a professional Personal Finance AI Agent connected to the user's Living Money Model.

LANGUAGE HANDLING:
- Understand both English and Hindi (including Hindi written in A-Z letters).
- Reply in clean, professional English by default. If the user writes in Hindi/Hinglish, reply politely in their language.

STRICT GUARDRAILS:
1. NEVER recommend specific stocks, mutual funds, ETFs, crypto coins, or securities to buy or sell.
2. If asked which stock, fund, or crypto to buy, politely decline and explain that you only provide financial education and scenario modeling.
3. Ground all advice in the user's actual numbers provided in the context.
4. Keep responses structured, concise, and actionable.
"""

SPECIALIST_PROMPTS = {
    "BUDGET_SAVINGS": (
        BASE_SYSTEM_RULES
        + "\nROLE: Budget & Savings Specialist Agent. Create structured monthly allocation plans based on income and expenses."
    ),
    "GOAL_PLANNER": (
        BASE_SYSTEM_RULES
        + "\nROLE: Goal Strategy Agent. Focus on helping the user hit their target dates faster by optimizing monthly surplus."
    ),
    "FINANCE_EDUCATOR": (
        BASE_SYSTEM_RULES
        + "\nROLE: Financial Educator Agent. Explain personal finance concepts clearly without recommending specific securities."
    ),
}


def _guardrail_agent(user_message, profile):
    msg = (user_message or "").lower()
    blocked_phrases = [
        "which stock", "buy stock", "best crypto", "should i buy", "which mutual fund",
        "recommend a stock", "kaunsa stock", "konsa stock", "share kharidu", "stock lu", "crypto lu"
    ]
    if any(p in msg for p in blocked_phrases):
        return (
            "🛡️ **Guardrail Active:** I cannot recommend specific stocks, mutual funds, or cryptocurrencies. "
            f"I can help you structure a savings plan, build your ₹{float(profile.get('emergency_target', 150000)):,.0f} "
            "emergency fund, or explain asset allocation principles."
        )
    return None


def _router_agent(user_message):
    msg = (user_message or "").lower()
    if any(w in msg for w in ["goal", "target", "trip", "laptop", "car", "house", "faster"]):
        return "GOAL_PLANNER"
    if any(w in msg for w in ["salary", "income", "budget", "save", "saving", "invest", "plan", "spend", "expense", "kharcha"]):
        return "BUDGET_SAVINGS"
    return "FINANCE_EDUCATOR"


def parse_what_if_query(query, available_categories):
    try:
        prompt = f"""
        Convert the user's financial "What-If" scenario into JSON adjustments.
        Available spending categories: {available_categories}
        Return ONLY JSON with these exact keys:
        - "category_pct_change": object mapping category name to decimal change (e.g., cut Dining by 30% -> {{"Dining": -0.30}})
        - "fixed_cost_delta": float change in monthly fixed costs/rent (e.g., rent goes up by 2000 -> 2000)
        - "income_delta": float change in monthly income (e.g., side hustle +10000 -> 10000)
        - "summary": 1-sentence plain English summary of the scenario

        User scenario: "{query}"
        """
        raw_json = _call_gemini_fast(contents=prompt, json_mode=True)
        parsed = json.loads(raw_json)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    return _quick_what_if_fallback(query, available_categories)


def ask_coach(user_message, profile, goals_df, tx_df, chat_history=None):
    blocked_reply = _guardrail_agent(user_message, profile)
    if blocked_reply:
        return blocked_reply

    route = _router_agent(user_message)
    system_instruction = SPECIALIST_PROMPTS[route]

    try:
        top_cats = tx_df.groupby("category")["amount"].sum().to_dict() if (tx_df is not None and not tx_df.empty) else {}
        total_spent = tx_df[tx_df["category"] != "Income"]["amount"].sum() if (tx_df is not None and not tx_df.empty) else 0

        history_text = ""
        if chat_history:
            recent = chat_history[-4:]
            history_text = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in recent])

        context = f"""
        User Living Money Model:
        - Monthly Income: ₹{float(profile.get('monthly_income', 60000)):,.0f}
        - Fixed Costs: ₹{float(profile.get('fixed_costs', 25000)):,.0f}
        - Total Tracked Spending: ₹{float(total_spent):,.0f}
        - Emergency Fund: ₹{float(profile.get('emergency_fund', 50000)):,.0f} / ₹{float(profile.get('emergency_target', 150000)):,.0f}
        - Spending by Category: {top_cats}
        - Active Goals: {goals_df.to_dict(orient='records') if (goals_df is not None and not goals_df.empty) else 'None'}

        Recent Conversation:
        {history_text}
        """

        return _call_gemini_fast(
            contents=f"CONTEXT:\n{context}\n\nUSER QUESTION:\n{user_message}",
            system_instruction=system_instruction,
            json_mode=False,
        )
    except Exception:
        return _local_fallback_reply(user_message, profile, goals_df, tx_df)


def generate_monthly_report(profile, goals_df, tx_df, subs):
    if tx_df is None or tx_df.empty:
        return "Please upload transactions (or click **⚡ Load 2-Month Sample Data**) first to generate your Monthly Review Report."

    try:
        cat_summary = tx_df.groupby("category")["amount"].sum().to_dict()
        total_spent = float(tx_df[tx_df["category"] != "Income"]["amount"].sum())
        income = float(profile.get("monthly_income") or 60000)
        fixed = float(profile.get("fixed_costs") or 25000)

        prompt = f"""
        Write a crisp, executive Monthly Financial Review Report in Markdown using these real numbers:
        - Monthly Income: ₹{income:,.0f}
        - Fixed Costs: ₹{fixed:,.0f}
        - Tracked Variable Spend: ₹{total_spent:,.0f}
        - Spending by Category: {cat_summary}
        - Subscriptions Detected: {subs}
        - Active Goals: {goals_df.to_dict(orient='records') if (goals_df is not None and not goals_df.empty) else 'None'}

        Include:
        1. Financial Health Snapshot (Savings Rate & Cash Flow)
        2. Top 3 Insights (including subscription leaks if any)
        3. 3 Concrete Action Steps for Next Month
        """
        return _call_gemini_fast(
            contents=prompt,
            system_instruction=BASE_SYSTEM_RULES,
            json_mode=False,
        )
    except Exception:
        return _local_fallback_reply("monthly financial review report", profile, goals_df, tx_df)