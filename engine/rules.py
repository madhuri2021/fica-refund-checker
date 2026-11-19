"""Eligibility rules for the nonresident student FICA exemption.

Every decision carries a rule ID (R1, R2, ...) so the output can say *why*,
and the README decision table maps 1:1 to this file.

Legal basis (verified Nov 2026):
- IRC 3121(b)(19): F/J/M/Q services exempt while a nonresident alien,
  if performed to carry out the purpose of the visa.
- IRC 7701(b)(5): students are "exempt individuals" (days don't count for
  residency) unless exempt for any part of more than 5 calendar years.
- IRC 7701(b)(3): substantial presence test (31 days and 183 weighted days).
- IRC 7701(b)(2)(A)(iii): residency starts on the first day present that year.
- IRC 3121(c): pay period rule (half or more taxable -> all taxable).
- IRS: FICA applies from the H-1B effective date, regardless of residency.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

STUDENT_VISAS = {"F-1", "J-1"}
DEPENDENT_VISAS = {"F-2", "J-2", "M-2"}
DEFERRED_VISAS = {"M-1"}
QUALIFYING_WORK = {"on_campus", "cpt", "opt", "stem_opt", "cap_gap_with_work_auth"}
UNAUTHORIZED_WORK = {"cap_gap_status_only", "unauthorized"}
DEFERRED_WORK = {"economic_hardship"}

WARN_ON_CAMPUS = (
    "If you work on campus for the school where you are enrolled at least half-time, "
    "a separate student exemption (IRC 3121(b)(10)) may still apply. Not evaluated here."
)
WARN_PAST_5_YEARS = (
    "Rare exception: a student can stay an exempt individual past 5 years by showing "
    "no intent to reside permanently (Form 8843 statement). Not evaluated here."
)


@dataclass
class Profile:
    visa: str                       # "F-1", "J-1", "F-2", "M-1", ...
    tax_year: int
    exempt_years: list[int]         # every calendar year with any day in F/J/M/Q status
    work_type: str                  # see QUALIFYING_WORK etc.
    j1_category: str | None = None  # "student" for J-1 students; anything else is deferred
    h1b_start: date | None = None   # H-1B effective date via change of status
    days_in_us: int | None = None   # only needed past year 5
    days_prior_1: int = 0           # days in US last year (counts only if not an exempt year)
    days_prior_2: int = 0           # days in US two years ago (same)
    first_day_in_us: date | None = None  # first day present this year, only needed past year 5


@dataclass
class Paycheck:
    period_start: date
    period_end: date
    pay_date: date
    gross: float
    ss_withheld: float
    medicare_withheld: float


@dataclass
class ProfileResult:
    ok: bool                        # False = stop, nothing is exempt
    rule: str
    reason: str
    residency_start: date | None = None   # taxable from this date (year 6+ residents)
    warnings: list[str] = field(default_factory=list)


@dataclass
class Verdict:
    status: str                     # "exempt" | "taxable" | "split"
    rule: str
    reason: str
    exempt_share: float             # share of wages claimed as exempt (conservative)
    alt_exempt_share: float | None = None  # other legal reading, shown not claimed
    warnings: list[str] = field(default_factory=list)


def prior_exempt_years(p: Profile) -> int:
    """R5: count distinct calendar years before the tax year (lifetime, any part counts)."""
    return len({y for y in p.exempt_years if y < p.tax_year})


def substantial_presence(p: Profile) -> float:
    """IRC 7701(b)(3): current + 1/3 prior + 1/6 second prior. Exempt years count as 0."""
    exempt = set(p.exempt_years)
    d1 = 0 if (p.tax_year - 1) in exempt else p.days_prior_1
    d2 = 0 if (p.tax_year - 2) in exempt else p.days_prior_2
    return (p.days_in_us or 0) + d1 / 3 + d2 / 6


def check_profile(p: Profile) -> ProfileResult:
    """Person-level rules. Runs once before any paycheck is looked at."""
    if p.visa in DEPENDENT_VISAS:
        return ProfileResult(False, "R1", f"{p.visa} dependents are not covered by the student "
                             "FICA exemption (Treas. Reg. 31.3121(b)(19)-1(a)(2)). FICA was correctly withheld.")
    if p.visa in DEFERRED_VISAS:
        return ProfileResult(False, "D1", f"{p.visa} is out of scope for this prototype. "
                             "The exemption likely applies; check with a tax professional.")
    if p.visa not in STUDENT_VISAS:
        return ProfileResult(False, "R2", f"{p.visa} is not an F/J/M/Q status. FICA applies.")
    if p.visa == "J-1" and (p.j1_category or "").lower() != "student":
        return ProfileResult(False, "D2", "J-1 researchers, scholars and trainees use a different "
                             "rule (2 of 6 years). Out of scope for this prototype.")
    if p.work_type in DEFERRED_WORK:
        return ProfileResult(False, "D3", "Economic-hardship work is exempt under the same rule "
                             "but is out of scope for this prototype.")
    if p.work_type in UNAUTHORIZED_WORK:
        return ProfileResult(False, "R4", "This work was not authorized (for example cap-gap with "
                             "status only, or a grace period). Only authorized work is exempt.")
    if p.work_type not in QUALIFYING_WORK:
        return ProfileResult(False, "R4", f"Unknown work type '{p.work_type}'.")

    used = prior_exempt_years(p)
    if used < 5:
        return ProfileResult(True, "R6", f"Year {used + 1} of 5 as an exempt student: "
                             "nonresident alien, authorized work is exempt.")

    # Past the 5-year window: days now count toward residency (R7).
    if p.days_in_us is None:
        return ProfileResult(False, "E1", "Past 5 exempt years: enter days in the US this year.")
    spt = substantial_presence(p)
    if p.days_in_us < 31 or spt < 183:
        return ProfileResult(True, "R8", f"Past 5 years but substantial presence not met "
                             f"({spt:.0f} weighted days < 183): still a nonresident, exempt.",
                             warnings=[WARN_PAST_5_YEARS])
    if p.first_day_in_us is None:
        return ProfileResult(False, "E1", "Resident this year: enter your first day in the US this year.")
    return ProfileResult(True, "R9", f"Substantial presence met ({spt:.0f} weighted days): resident "
                         f"from {p.first_day_in_us}. Work from that date owes FICA.",
                         residency_start=p.first_day_in_us,
                         warnings=[WARN_ON_CAMPUS, WARN_PAST_5_YEARS])


def classify_paycheck(pc: Paycheck, p: Profile, pr: ProfileResult) -> Verdict:
    """Paycheck-level rules. Classified by the dates the work was done, not the pay date."""
    cutoffs = [d for d in (p.h1b_start, pr.residency_start) if d]
    if not cutoffs:
        return Verdict("exempt", pr.rule, "Work done while exempt.", 1.0)
    cutoff = min(cutoffs)
    why = "H-1B start" if cutoff == p.h1b_start else "residency start"
    rule = "R2" if why == "H-1B start" else "R9"

    if pc.period_end < cutoff:
        return Verdict("exempt", pr.rule, f"Work done before {why} ({cutoff}).", 1.0)
    if pc.period_start >= cutoff:
        return Verdict("taxable", rule, f"Work done on or after {why} ({cutoff}). FICA applies.", 0.0)

    # R10: pay period straddles the cutoff.
    total = (pc.period_end - pc.period_start).days + 1
    exempt_days = (cutoff - pc.period_start).days
    prorated = exempt_days / total
    if total > 31:
        return Verdict("split", "R10", f"Straddles {why}; period over 31 days so the pay-period "
                       "rule does not apply. Split by days.", prorated)
    taxable_days = total - exempt_days
    statute = 0.0 if taxable_days * 2 >= total else 1.0   # IRC 3121(c), tie goes to FICA
    claim, alt = min(statute, prorated), max(statute, prorated)
    return Verdict(
        "split", "R10",
        f"Straddles {why}: {exempt_days} exempt days of {total}. Statute (3121(c)) gives "
        f"{statute:.0%} exempt, day split gives {prorated:.0%}. Claiming the lower amount.",
        claim, alt if alt != claim else None,
        warnings=["Ambiguous: statute vs. IRS employer guidance. Review with a tax professional."],
    )
