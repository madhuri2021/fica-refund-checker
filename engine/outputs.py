"""Turn a Result into things a person can act on:
1. a plain-English summary
2. a refund request letter to the employer (step 1 required by the IRS)
3. an IRS packet checklist (Form 843 + Form 8316), used only if the employer refuses
"""
from __future__ import annotations

from datetime import date

from engine.refund import Result


def summary(r: Result) -> str:
    out = []
    if r.errors:
        out.append("Could not check this. Fix these first:")
        out += [f"  - {e}" for e in r.errors]
        return "\n".join(out)
    if not r.ok:
        out.append(f"Result: no refund. [{r.profile_rule}] {r.profile_reason}")
        return "\n".join(out)

    out.append(f"Status: [{r.profile_rule}] {r.profile_reason}")
    out.append("")
    out.append(f"{'Work period':<25}{'Verdict':<9}{'Rule':<6}{'Refund':>10}{'Under':>10}")
    for l in r.lines:
        pc = l.paycheck
        out.append(f"{str(pc.period_start) + ' to ' + str(pc.period_end):<25}{l.status:<9}{l.rule:<6}"
                   f"{l.refund_ss + l.refund_medicare:>10,.2f}{l.under_withheld:>10,.2f}")
    out.append("")
    out.append(f"Social Security refund: ${r.refund_ss:,.2f}")
    out.append(f"Medicare refund:        ${r.refund_medicare:,.2f}")
    if r.employer_already_refunded:
        out.append(f"Already refunded:      -${r.employer_already_refunded:,.2f}")
    out.append(f"REFUND TO CLAIM:        ${r.refund_total:,.2f}")
    if r.alt_refund_total is not None:
        out.append(f"(Alternative reading:   ${r.alt_refund_total:,.2f}, not claimed)")
    out.append(f"Claim deadline:         {r.deadline}")
    if r.warnings:
        out.append("")
        out += [f"! {w}" for w in r.warnings]
    return "\n".join(out)


def employer_letter(r: Result, name: str, employer: str, visa: str, tax_year: int,
                    today: date | None = None) -> str:
    if not r.ok or r.refund_total <= 0:
        return "No letter: there is nothing to claim."
    today = today or date.today()
    exempt = [l for l in r.lines if l.refund_ss + l.refund_medicare > 0]
    first, last = exempt[0].paycheck.period_start, exempt[-1].paycheck.period_end
    return f"""{today:%B %d, %Y}

To: Payroll Department, {employer}
From: {name}
Subject: Refund of Social Security and Medicare tax withheld in error ({tax_year})

Hello,

Social Security and Medicare tax was withheld from my wages for work performed from {first:%B %d, %Y} to {last:%B %d, %Y}. During that period I was in {visa} status, a nonresident alien for tax purposes, doing work authorized under my status.

Under Internal Revenue Code section 3121(b)(19), these wages are not subject to Social Security or Medicare tax. IRS guidance asks employees to request repayment from the employer first.

Amounts withheld in error:
  Social Security: ${r.refund_ss:,.2f}
  Medicare:        ${r.refund_medicare:,.2f}
  Total:           ${r.refund_total:,.2f}

Please refund this amount and, if it was reported for a prior year, issue a corrected Form W-2c. If you file Form 941-X to recover it, I am happy to sign the written consent you need.

If you are unable to refund it, please send me a short written statement saying so and listing any amount you have refunded or claimed. I will need it for my claim to the IRS.

I can provide my I-20 or DS-2019, I-94 and work authorization on request.

Thank you,
{name}
"""


def irs_checklist(r: Result, tax_year: int) -> str:
    if not r.ok or r.refund_total <= 0:
        return "No IRS claim needed."
    return f"""IRS packet: use ONLY if your employer refuses or does not respond.
File one packet per tax year. Do not attach it to your tax return.

[ ] Form 843 (Claim for Refund and Request for Abatement)
      Tax period: Jan 1 - Dec 31, {tax_year}
      Amount to be refunded: ${r.refund_total:,.2f}
      Type of tax: Employment (Social Security and Medicare)
      Explanation: nonresident alien student, wages exempt under IRC 3121(b)(19)
[ ] Form 8316 (refund of Social Security tax withheld on F, J or M visa wages)
[ ] Copy of Form W-2 for {tax_year}
[ ] Copy of visa page from passport
[ ] Form I-94 (arrival and departure record)
[ ] I-20 or DS-2019, and EAD card if you were on OPT or STEM OPT
[ ] Employer's statement of refusal, OR your own signed statement explaining why you
    could not get one (include the date you asked)
[ ] Mail to: Department of the Treasury, Internal Revenue Service Center,
             Ogden, UT 84201-0038 (check IRS Publication 519 for the current address)

Deadline: postmarked by {r.deadline:%B %d, %Y}.
This tool is not tax advice. Rules verified against IRS sources, Nov 2026.
"""
