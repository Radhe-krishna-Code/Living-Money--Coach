# 💸 Living Money Coach

An adaptive, AI-powered personal finance and decision engine built with **Python, Streamlit, Plotly, SQLite, and the Google Gemini API (`google-genai` SDK)**.

Most finance apps act as passive trackers. **Living Money Coach** turns raw spending data into smart habits, real-time wealth simulations, and actionable AI guidance—while keeping the human firmly in the loop.

---

## 🔗 Quick Links
- **Live App:** [https://living-money-coach.streamlit.app/]
- **Demo Video:** [https://drive.google.com/file/d/1nErR_rz8mO4PR8Eqs3SzyUpT6PIOluk8/view?usp=drive_link]
- **Repository:** https://github.com/Radhe-krishna-Code/Living-Money--Coach

---

## ✨ Key Features

1. **Dashboard & Subscription Radar**
   - Visualizes total spending, category breakdowns, and recurring subscription leaks using interactive Plotly charts.
2. **Upload & Correction Loop (Self-Learning Engine)**
   - Paste raw SMS alerts, CSV rows, or statement text to extract and categorize transactions via Gemini structured JSON extraction.
   - Backed by multi-model fallback and a deterministic offline regex parser so extraction stays reliable.
   - **Human-in-the-loop learning:** Correcting a merchant's category saves a custom rule in SQLite and automatically applies it to future imports.
3. **Investment Portfolio**
   - Tracks investment distribution and overall wealth allocation in one place.
4. **Foreign Trip Agent**
   - Generates practical travel budget breakdowns and savings plans for any target destination and budget.
5. **What-If Financial Simulator**
   - Interactive sliders to test discretionary spend cuts and extra monthly SIPs, visualizing the 12-month compounding wealth impact.
6. **Profiles & Goals**
   - Manage personal profiles and align daily spending with real financial targets.
7. **Monthly Report & AI Coach**
   - Review monthly spending summaries and chat with a context-aware Gemini Money Coach for tailored budgeting advice.

---

## 🛠️ Tech Stack

- **Frontend & Deployment:** Streamlit, Streamlit Community Cloud
- **AI / LLM:** Google Gemini API (`google-genai` SDK)
- **Data & Visualization:** Pandas, Plotly
- **Database:** SQLite

---

## 🚀 Run Locally

1. **Clone the repository**
   ```bash
   git clone [https://github.com/Radhe-krishna-Code/Living-Money--Coach.git](https://github.com/Radhe-krishna-Code/Living-Money--Coach.git)
   cd Living-Money--Coach

   Install dependencies

