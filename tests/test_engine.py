"""Run with: python -m pytest -q   (from the project folder)"""
from datetime import date as d

from engine.parser import parse_paystubs
from engine.refund import compute
from engine.rules import Paycheck, Profile

TODAY = d(2026, 11, 17)


def pc(start, end, pay, gross=3000, ss=186, med=43.5):
    return Paycheck(start, end, pay, gross, ss, med)


def test_opt_year3_full_refund():
    r = compute(Profile("F-1", 2026, [2024, 2025, 2026], "opt"),
                [pc(d(2026, 1, 1), d(2026, 1, 14), d(2026, 1, 17))], today=TODAY)
    assert r.ok and r.refund_total == 229.50


def test_h1b_switch_refund_straddle_and_under_withholding():
    p = Profile("F-1", 2026, [2023, 2024, 2025, 2026], "opt", h1b_start=d(2026, 10, 1))
    r = compute(p, [pc(d(2026, 5, 1), d(2026, 5, 14), d(2026, 5, 17)),
                    pc(d(2026, 9, 24), d(2026, 10, 7), d(2026, 10, 10)),       # 7/7 tie -> taxable
                    pc(d(2026, 10, 8), d(2026, 10, 21), d(2026, 10, 24), ss=0, med=0)], today=TODAY)
    assert [l.status for l in r.lines] == ["exempt", "split", "taxable"]
    assert r.refund_total == 229.50          # conservative reading claimed
    assert r.alt_refund_total == 344.25      # day-split reading shown, not claimed
    assert r.under_withheld_total == 229.50  # flagged, not subtracted


def test_paid_after_h1b_for_f1_work_is_exempt():
    p = Profile("F-1", 2026, [2024, 2025, 2026], "opt", h1b_start=d(2026, 10, 1))
    r = compute(p, [pc(d(2026, 9, 16), d(2026, 9, 30), d(2026, 10, 5))], today=TODAY)
    assert r.lines[0].status == "exempt"     # classified by work dates, not pay date


def test_year6_over_183_days_is_taxable():
    p = Profile("F-1", 2026, [2020, 2021, 2022, 2023, 2024], "opt", days_in_us=200, first_day_in_us=d(2026, 1, 1))
    r = compute(p, [pc(d(2026, 3, 1), d(2026, 3, 14), d(2026, 3, 17))], today=TODAY)
    assert r.profile_rule == "R9" and r.refund_total == 0


def test_year6_under_183_days_still_exempt():
    p = Profile("F-1", 2026, [2020, 2021, 2022, 2023, 2024], "opt", days_in_us=120)
    r = compute(p, [pc(d(2026, 3, 1), d(2026, 3, 14), d(2026, 3, 17))], today=TODAY)
    assert r.profile_rule == "R8" and r.refund_total == 229.50


def test_prior_visit_counts_toward_five_years():
    p = Profile("F-1", 2026, [2015, 2022, 2023, 2024, 2025], "opt", days_in_us=300, first_day_in_us=d(2026, 1, 1))
    assert compute(p, [pc(d(2026, 3, 1), d(2026, 3, 14), d(2026, 3, 17))], today=TODAY).profile_rule == "R9"


def test_dependent_rejected():
    r = compute(Profile("F-2", 2026, [2026], "opt"), [pc(d(2026, 3, 1), d(2026, 3, 14), d(2026, 3, 17))])
    assert not r.ok and r.profile_rule == "R1"


def test_j1_researcher_deferred():
    r = compute(Profile("J-1", 2026, [2026], "on_campus", j1_category="researcher"),
                [pc(d(2026, 3, 1), d(2026, 3, 14), d(2026, 3, 17))])
    assert not r.ok and r.profile_rule == "D2"


def test_cap_gap_without_work_auth_not_exempt():
    r = compute(Profile("F-1", 2026, [2025, 2026], "cap_gap_status_only"),
                [pc(d(2026, 3, 1), d(2026, 3, 14), d(2026, 3, 17))])
    assert not r.ok and r.profile_rule == "R4"


def test_bad_input_caught():
    r = compute(Profile("F-1", 2026, [2026], "opt"), [pc(d(2026, 5, 14), d(2026, 5, 1), d(2026, 5, 17), 100, 90, 20)])
    assert len(r.errors) == 2 and not r.lines


def test_deadline_passed():
    r = compute(Profile("F-1", 2021, [2020, 2021], "opt"), [pc(d(2021, 3, 1), d(2021, 3, 14), d(2021, 3, 17))], today=TODAY)
    assert r.deadline == d(2025, 4, 15) and r.deadline_passed


def test_wage_base_caps_social_security():
    # $190k already taxable this year at H-1B; SS only owed up to the $184,500 base
    p = Profile("F-1", 2026, [2024, 2025, 2026], "opt", h1b_start=d(2026, 1, 1))
    big = [pc(d(2026, 1, 1), d(2026, 1, 14), d(2026, 1, 17), 190_000, 184_500 * 0.062, 190_000 * 0.0145)]
    r = compute(p, big, today=TODAY)
    assert r.refund_total == 0 and r.under_withheld_total == 0


def test_mock_parser_reads_sample():
    pcs, errs, mode = parse_paystubs(open("samples/paystubs_h1b_switch.txt").read(), use_ai=False)
    assert mode == "MOCK" and not errs and len(pcs) == 3


def test_parser_reports_missing_fields():
    _, errs, _ = parse_paystubs("Pay Period: 05/01/2026 - 05/14/2026\nGross Pay: 3000", use_ai=False)
    assert "missing" in errs[0]
