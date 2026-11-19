"""Refund math, input validation, filing deadline and under-withholding flag.

Rates: Social Security 6.2% (up to the yearly wage base), Medicare 1.45% (no cap).
Additional Medicare Tax (0.9% over $200k from one employer) is excluded on purpose:
it is not refundable on Form 843 (recover it via Form 8959 on the tax return).
Deadline: IRC 6511 + 6513(c) -> April 15 of the 4th year after wages were paid.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from engine.rules import Paycheck, Profile, check_profile, classify_paycheck

SS_RATE = 0.062
MEDICARE_RATE = 0.0145
ADDL_MEDICARE_THRESHOLD = 200_000
WAGE_BASE = {  # SSA Social Security wage base by year
    2021: 142_800, 2022: 147_000, 2023: 160_200, 2024: 168_600,
    2025: 176_100, 2026: 184_500, 2027: 192_300,
}


@dataclass
class Line:
    paycheck: Paycheck
    status: str
    rule: str
    reason: str
    refund_ss: float = 0.0
    refund_medicare: float = 0.0
    under_withheld: float = 0.0
    alt_refund: float | None = None


@dataclass
class Result:
    ok: bool
    profile_rule: str
    profile_reason: str
    lines: list[Line] = field(default_factory=list)
    refund_ss: float = 0.0
    refund_medicare: float = 0.0
    employer_already_refunded: float = 0.0
    refund_total: float = 0.0
    alt_refund_total: float | None = None
    under_withheld_total: float = 0.0
    deadline: date | None = None
    deadline_passed: bool = False
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def validate(p: Profile, paychecks: list[Paycheck]) -> list[str]:
    """Catch bad input before any math runs."""
    errs = []
    if not paychecks:
        errs.append("No paychecks entered.")
    if p.tax_year not in WAGE_BASE:
        errs.append(f"Tax year {p.tax_year} not supported (supported: {min(WAGE_BASE)}-{max(WAGE_BASE)}).")
    for i, pc in enumerate(paychecks, 1):
        tag = f"Paycheck {i}:"
        if pc.period_end < pc.period_start:
            errs.append(f"{tag} period ends before it starts.")
        if pc.pay_date.year != p.tax_year:
            errs.append(f"{tag} paid in {pc.pay_date.year}, not {p.tax_year}. Run one year at a time.")
        if pc.gross <= 0:
            errs.append(f"{tag} gross wages must be more than 0.")
        if pc.ss_withheld < 0 or pc.medicare_withheld < 0:
            errs.append(f"{tag} withheld amounts cannot be negative.")
        if pc.ss_withheld + pc.medicare_withheld > pc.gross:
            errs.append(f"{tag} FICA withheld is more than gross wages. Check the numbers.")
    return errs


def _expected(taxable_wages: float, ytd_taxable: float, wage_base: int) -> tuple[float, float]:
    """FICA that *should* have been withheld on the taxable part of one paycheck."""
    ss_wages = max(0.0, min(taxable_wages, wage_base - ytd_taxable))
    return ss_wages * SS_RATE, taxable_wages * MEDICARE_RATE


def compute(p: Profile, paychecks: list[Paycheck], employer_refunded: float = 0.0,
            today: date | None = None) -> Result:
    today = today or date.today()
    errors = validate(p, paychecks)
    if errors:
        return Result(False, "E1", "Input errors. Nothing calculated.", errors=errors)

    pr = check_profile(p)
    res = Result(pr.ok, pr.rule, pr.reason, warnings=list(pr.warnings))
    if not pr.ok:
        return res

    base = WAGE_BASE[p.tax_year]
    ytd_taxable = ytd_gross = 0.0
    alt_total, has_alt = 0.0, False
    for pc in sorted(paychecks, key=lambda x: x.pay_date):
        v = classify_paycheck(pc, p, pr)
        taxable = pc.gross * (1 - v.exempt_share)
        exp_ss, exp_med = _expected(taxable, ytd_taxable, base)
        ytd_taxable += taxable
        ytd_gross += pc.gross

        diff_ss = pc.ss_withheld - exp_ss
        diff_med = pc.medicare_withheld - exp_med
        line = Line(pc, v.status, v.rule, v.reason,
                    refund_ss=max(diff_ss, 0), refund_medicare=max(diff_med, 0),
                    under_withheld=max(0.0, -diff_ss) + max(0.0, -diff_med))
        if v.alt_exempt_share is not None:
            alt_taxable = pc.gross * (1 - v.alt_exempt_share)
            a_ss, a_med = alt_taxable * SS_RATE, alt_taxable * MEDICARE_RATE
            line.alt_refund = max(pc.ss_withheld - a_ss, 0) + max(pc.medicare_withheld - a_med, 0)
            has_alt = True
        alt_total += line.alt_refund if line.alt_refund is not None else line.refund_ss + line.refund_medicare
        res.warnings += [w for w in v.warnings if w not in res.warnings]
        res.lines.append(line)

    res.refund_ss = round(sum(l.refund_ss for l in res.lines), 2)
    res.refund_medicare = round(sum(l.refund_medicare for l in res.lines), 2)
    res.employer_already_refunded = employer_refunded
    res.refund_total = round(max(res.refund_ss + res.refund_medicare - employer_refunded, 0), 2)
    if has_alt:
        res.alt_refund_total = round(max(alt_total - employer_refunded, 0), 2)
    res.under_withheld_total = round(sum(l.under_withheld for l in res.lines), 2)

    if res.under_withheld_total > 0.5:
        res.warnings.append(f"Payroll under-withheld ${res.under_withheld_total:,.2f} on taxable pay. "
                            "Your employer is responsible for correcting this and may deduct it from "
                            "future pay. Not subtracted from your refund.")
    if ytd_gross > ADDL_MEDICARE_THRESHOLD:
        res.warnings.append("Wages from this employer passed $200,000. Some Medicare withheld may be "
                            "Additional Medicare Tax: recover it via Form 8959 on your tax return, not Form 843.")

    res.deadline = date(p.tax_year + 4, 4, 15)
    res.deadline_passed = today > res.deadline
    if res.deadline_passed:
        res.warnings.append(f"Refund deadline passed on {res.deadline}. The IRS will likely deny the claim.")
    return res
