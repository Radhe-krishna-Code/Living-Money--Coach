import os
import json
from dotenv import load_dotenv
from google import genai
from google.genai import types
import database as db

load_dotenv()

MODEL_CANDIDATES = [
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
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
        raise ValueError("GEMINI_API_KEY is missing in .env file.")
    return genai.Client(api_key=api_key)


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
                return json.loads(response.text)
        except Exception as e:
            last_error = e
            err_str = str(e)
            if "404" in err_str or "NOT_FOUND" in err_str or "not found" in err_str.lower():
                continue
            raise e
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
    tx_list = _extract_json_with_fallback([EXTRACTION_PROMPT, f"DATA:\n{raw_text}"])
    for tx in tx_list:
        tx["source"] = source
    return apply_learned_rules(tx_list, username=username)


def parse_pdf(pdf_bytes, source="pdf", username="default"):
    pdf_part = types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")
    tx_list = _extract_json_with_fallback([EXTRACTION_PROMPT, pdf_part])
    for tx in tx_list:
        tx["source"] = source
    return apply_learned_rules(tx_list, username=username)