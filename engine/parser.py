"""Paystub text -> Paycheck lines.

This is the only place AI is used. AI reads messy documents; it never decides tax rules.
- If ANTHROPIC_API_KEY is set and the `anthropic` package is installed, Claude extracts the fields.
- Otherwise a rule-based parser runs instead (labeled MOCK in the output), so no paid
  service is needed to run the prototype.
Either way, every parsed line goes through the same validation in refund.py.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime

from engine.rules import Paycheck

FIELDS = ["period_start", "period_end", "pay_date", "gross", "ss_withheld", "medicare_withheld"]

PROMPT = """Extract every paycheck from the paystub text below.
Return ONLY a JSON array. One object per paycheck with these keys:
period_start, period_end, pay_date (YYYY-MM-DD), gross, ss_withheld, medicare_withheld (numbers).
Use the CURRENT period amounts, not year-to-date. Social Security may be labeled OASDI or Soc Sec.
If a value is missing, use null. Do not guess.

Paystub text:
{text}"""

LABELS = {
    "period": r"(?:pay\s*period|period)\s*:?\s*([\d/.-]+)\s*(?:-|to|–)\s*([\d/.-]+)",
    "pay_date": r"(?:pay\s*date|check\s*date)\s*:?\s*([\d/.-]+)",
    "gross": r"(?:gross\s*pay|gross\s*earnings|total\s*earnings|gross)\s*:?\s*\$?([\d,]+\.?\d*)",
    "ss_withheld": r"(?:social\s*security|soc\s*sec|oasdi)(?:\s*tax)?\s*:?\s*\$?([\d,]+\.?\d*)",
    "medicare_withheld": r"medicare(?:\s*tax)?\s*:?\s*\$?([\d,]+\.?\d*)",
}


def _date(s: str) -> date:
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            pass
    raise ValueError(f"unreadable date '{s}'")


def _money(s) -> float:
    return float(str(s).replace(",", "").replace("$", ""))


def _to_paycheck(d: dict, i: int) -> Paycheck:
    missing = [f for f in FIELDS if d.get(f) in (None, "")]
    if missing:
        raise ValueError(f"Paystub {i}: missing {', '.join(missing)}")
    return Paycheck(_date(d["period_start"]), _date(d["period_end"]), _date(d["pay_date"]),
                    _money(d["gross"]), _money(d["ss_withheld"]), _money(d["medicare_withheld"]))


def parse_mock(text: str) -> list[dict]:
    """Rule-based fallback. Expects one 'Pay Period' block per paycheck."""
    blocks = [b for b in re.split(r"(?i)(?=pay\s*period)", text) if re.search(r"(?i)pay\s*period", b)]
    out = []
    for b in blocks:
        d = {}
        m = re.search(LABELS["period"], b, re.I)
        if m:
            d["period_start"], d["period_end"] = m.group(1), m.group(2)
        for key in ("pay_date", "gross", "ss_withheld", "medicare_withheld"):
            m = re.search(LABELS[key], b, re.I)
            d[key] = m.group(1) if m else None
        out.append(d)
    return out


def parse_ai(text: str) -> list[dict]:
    import anthropic  # only needed in AI mode
    # Ask for gzip only: some Anaconda installs ship an old brotli library that
    # crashes when the API replies brotli-compressed (seen on a Mac, Nov 2026).
    client = anthropic.Anthropic(default_headers={"Accept-Encoding": "gzip"})
    msg = client.messages.create(model="claude-haiku-5-5", max_tokens=2000,
                                 messages=[{"role": "user", "content": PROMPT.format(text=text)}])
    # Join only the text blocks: responses can contain other block types.
    raw = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text").strip()
    if "[" not in raw:
        raise ValueError(f"no JSON array in AI reply: {raw[:80]!r}")
    raw = raw[raw.find("["): raw.rfind("]") + 1]
    return json.loads(raw)


def parse_paystubs(text: str, use_ai: bool | None = None) -> tuple[list[Paycheck], list[str], str]:
    """Returns (paychecks, errors, mode). mode is 'AI' or 'MOCK'."""
    if use_ai is None:
        use_ai = bool(os.environ.get("ANTHROPIC_API_KEY"))
    mode = "AI" if use_ai else "MOCK"
    try:
        rows = parse_ai(text) if use_ai else parse_mock(text)
    except Exception as e:  # AI unavailable or bad response: fall back, say so
        rows, mode = parse_mock(text), f"MOCK (AI failed: {type(e).__name__}: {str(e)[:120]})"
    if not rows:
        return [], ["No paychecks found. Each paystub needs a 'Pay Period' line."], mode
    pcs, errs = [], []
    for i, row in enumerate(rows, 1):
        try:
            pcs.append(_to_paycheck(row, i))
        except ValueError as e:
            errs.append(str(e))
    return pcs, errs, mode
