import json
import os
from dotenv import load_dotenv
from google import genai
from google.genai import types
import database as db

load_dotenv()

MODEL_CANDIDATES = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-3-flash-preview",
]

CATEGORIES = [
    "Dining", "Groceries", "Rent & Utilities", "Subscriptions",
    "Transport", "Shopping", "Health", "Entertainment", "Income", "Other"
]

EXTRACTION_PROMPT = f"""
Extract all financial debit/expense transactions from the provided bank statement, CSV, or SMS text.
Ignore account balances, headers, and non-transaction text.
Return ONLY a JSON array of objects with these exact keys:
- "date": "YYYY-MM-DD" (if year is missing, assume 2026)
- "merchant": short clean merchant name (e.g., "ZOMATO", "NETFLIX", "UBER")
- "amount": positive float number (no currency symbols)
- "category": strictly one of {CATEGORIES}
"""


def get_client():
    raw_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
    api_key = raw_key.strip().strip('"').strip("'")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is missing in environment or Streamlit Secrets.")
    return genai.Client(api_key=api_key)


def _clean_json_text(raw_text: str) -> str:
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _normalize_transactions(payload):
    if isinstance(payload, dict):
        for key in ("transactions", "data", "items", "results"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
        else:
            payload = [payload]

    if not isinstance(payload, list):
        return []

    cleaned = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            amount_val = float(str(item.get("amount", 0)).replace(",", "").strip())
        except (ValueError, TypeError):
            continue
        if amount_val <= 0:
            continue

        category = str(item.get("category") or "Other").strip()
        if category not in CATEGORIES:
            category = "Other"

        merchant = str(item.get("merchant") or "UNKNOWN").strip().upper()
        date_str = str(item.get("date") or "2026-11-21").strip()

        cleaned.append({
            "date": date_str,
            "merchant": merchant,
            "amount": amount_val,
            "category": category,
        })
    return cleaned


def _extract_json_with_fallback(contents):
    client = get_client()
    last_error = None

    for model_id in MODEL_CANDIDATES:
        try:
            response = client.models.generate_content(
                model=model_id,
                contents=contents,
                config=types.GenerateContentConfig(response_mime_type="application/json"),
            )
            if response and response.text:
                cleaned_text = _clean_json_text(response.text)
                parsed = json.loads(cleaned_text)
                return _normalize_transactions(parsed)
        except Exception as e:
            last_error = e
            continue

    raise RuntimeError(f"Extraction failed across models: {last_error}")


def apply_learned_rules(transactions, username="default"):
    """Apply logged-in user's saved correction rules BEFORE keeping Gemini's default category."""
    rules = db.get_rules(username=username)
    applied_count = 0
    for tx in transactions:
        merchant_upper = str(tx.get("merchant", "")).upper()
        for keyword, saved_cat in rules.items():
            if keyword in merchant_upper:
                tx["category"] = saved_cat
                applied_count += 1
                break
    return transactions, applied_count


def parse_text_or_csv(raw_text, source="sms/csv", username="default"):
    if not raw_text or not str(raw_text).strip():
        return [], 0
    tx_list = _extract_json_with_fallback([EXTRACTION_PROMPT, f"DATA:\n{raw_text}"])
    for tx in tx_list:
        tx["source"] = source
    return apply_learned_rules(tx_list, username=username)


def parse_pdf(pdf_bytes, source="pdf", username="default"):
    if not pdf_bytes:
        return [], 0
    pdf_part = types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")
    tx_list = _extract_json_with_fallback([EXTRACTION_PROMPT, pdf_part])
    for tx in tx_list:
        tx["source"] = source
    return apply_learned_rules(tx_list, username=username)