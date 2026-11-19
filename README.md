# FICA Refund Checker (prototype)

Nonresident F-1 and J-1 students working on OPT, STEM OPT, CPT or on campus are exempt from Social Security and Medicare tax (IRC 3121(b)(19)). Payroll systems often withhold it anyway, and most people never get it back because the rules and the refund process are confusing.

This prototype takes paystubs and a few facts about the person, decides paycheck by paycheck whether FICA was owed, calculates the refund, and produces the two documents needed to claim it: a refund request to the employer and, if the employer refuses, an IRS packet checklist (Form 843 + Form 8316).

**Not tax advice.** All sample data is synthetic.

## Quick start

Requires Python 3.10+.

```bash
cd fica-refund-checker
pip install -r requirements.txt
python -m pytest -q          # expect: 14 passed
jupyter notebook demo.ipynb  # then Kernel > Restart & Run All
```

When the notebook asks for a Claude API key, **press Enter to skip**. Everything runs without a key in MOCK mode. With a key, AI mode reads paystubs (see below).

## Design

```
paystub text --> parser.py --> Paycheck lines --> rules.py --> refund.py --> outputs.py
                 (AI or MOCK)                     (eligibility)  (math,        (summary, employer
                                                                  checks)       letter, IRS checklist)
```

**One rule: AI reads documents, code decides tax.** Paystub layouts vary across payroll providers, which is where AI helps. Tax rules must be exact and explainable, so they are plain Python with a rule ID and a legal citation on every decision. Anything AI extracts goes through the same input validation as typed data.

| File | What it does |
|---|---|
| `engine/rules.py` | Eligibility rules R1 to R10, with legal citations in the docstring |
| `engine/refund.py` | Refund math, input validation, wage base, filing deadline, under-withholding flag |
| `engine/parser.py` | Paystub text to paycheck lines. AI mode (Claude) or MOCK mode (pattern matching) |
| `engine/outputs.py` | Plain-English summary, employer letter, IRS checklist |
| `demo.ipynb` | Six demo cases plus the generated documents |
| `tests/test_engine.py` | 14 automated tests |
| `samples/` | Synthetic paystubs: one clean, one messy table layout |

## Decision rules

| ID | Condition | Outcome | Source |
|---|---|---|---|
| R1 | F-2 / J-2 / M-2 dependent | Not exempt | Treas. Reg. 31.3121(b)(19)-1(a)(2) |
| R2 | Work on or after H-1B effective date | Taxable | IRS: FICA applies from H-1B effective date |
| D2 | J-1 researcher, scholar, trainee | Deferred (2-of-6-year rule) | Treas. Reg. 301.7701(b)-3 |
| R4 | Work not authorized (e.g. cap-gap status only) | Not exempt | IRC 3121(b)(19): must carry out visa purpose |
| R5 | Count every calendar year in F/J/M/Q status, lifetime, any part counts | Input to R6/R7 | IRC 7701(b)(5)(E) |
| R6 | 5 or fewer years | Nonresident, authorized work exempt | IRC 3121(b)(19) |
| R7/R8 | Past 5 years, under 183 weighted days | Still nonresident, exempt | IRC 7701(b)(3) |
| R9 | Past 5 years, 183+ weighted days | Resident from first day present; taxable | IRC 7701(b)(2)(A)(iii) |
| R10 | Pay period straddles the cutoff | Statute (all-or-nothing) vs. day split: claim the lower, show both | IRC 3121(c) |

Refund = 6.2% Social Security (capped at the yearly wage base) + 1.45% Medicare, on exempt wages only. Deadline = April 15 of the 4th year after wages were paid (IRC 6511, 6513(c)).

## Demo cases (in `demo.ipynb`)

| # | Case | Input | Expected output |
|---|---|---|---|
| 1 | Typical | F-1 OPT, year 3, three paychecks of $3,000 with FICA withheld | Refund $688.50 |
| 2 | **Hard** | F-1 to H-1B on Oct 1, read from `samples/paystubs_h1b_switch.txt` | Refund $229.50; straddling paycheck shows alternative $344.25; under-withheld $229.50 flagged separately |
| 2b | AI vs MOCK | `samples/paystub_messy.txt` (table layout, "OASDI", "Med EE") | MOCK finds nothing; AI extracts one paycheck |
| 3 | Past 5 years | Year 6, 200 days in US | Refund $0, two warnings |
| 4 | **Invalid person** | F-2 dependent | Rejected, rule R1 |
| 5 | **Invalid input** | Period ends before it starts; FICA more than wages | Two clear errors, nothing calculated |
| 6 | Too late | 2021 wages | Refund calculated, deadline passed warning |

## AI mode

- Set a key in the notebook prompt, or `export ANTHROPIC_API_KEY=...` before starting Jupyter.
- Model: Claude Haiku 5.5 (cheapest; extraction is a simple task).
- If the AI call fails for any reason, the tool falls back to MOCK and says so in the mode label.
- **Privacy:** in AI mode, paystub text is sent to an outside service. A production version would tell the user first and strip names and IDs.

## What is implemented, mocked, deferred

**Implemented:** eligibility rules R1 to R10, refund math with wage base, filing deadline, under-withholding flag, Additional Medicare Tax warning, input validation, AI paystub extraction, employer letter, IRS checklist, 14 tests.

**Mocked / synthetic:** all paystubs and people; MOCK parser when no API key. No real employer or IRS integration.

**Deferred (out of scope, flagged by the tool):** J-1 researchers and scholars, M-1, economic-hardship work, H-1B obtained abroad, totalization agreements, income and state tax, the IRC 3121(b)(10) on-campus student exemption after year 5, the past-5-years student exception, the 10-day de minimis residency rule.

**Excluded by design:** Additional Medicare Tax (0.9%). Not refundable on Form 843; recovered via Form 8959 on the tax return. The tool warns when wages pass $200,000.

## Known limitations

- One tax year and one employer per run.
- Straddling pay periods: the IRS has not reconciled IRC 3121(c) with its "withhold from the effective date" guidance. The tool claims the lower amount and shows both.
- Rules verified against IRS and Treasury sources in Nov 2026. A tax professional should review before real use.

## How AI was used to build this

- Claude helped research the IRS rules, draft code and tests, and debug a library conflict.
- I checked its output by: verifying each rule against primary sources (IRC, Treasury regulations, IRS pages, Pub 519), running every demo case against a written expected result, and 14 automated tests.
- Example of a fix found by testing: an API connection error turned out to be an old compression library in Anaconda. Fixed by requesting gzip responses instead of downgrading packages.

## Time spent

About 3 hours 25 minutes in total, within the 2 to 4 hour limit:

- Research and scoping (problem choice, IRS rule verification, scope decisions): about 1 hour (Nov 17)
- Build (engine, AI parser, demo notebook, tests, README): about 1 hour 10 minutes (1:30 to 2:40 PM CST, Nov 17)
- Written explanation and video walkthrough: about 1 hour 15 minutes (Nov 18)

## What I would investigate next

1. Talk to 5 to 10 international students and 2 university payroll offices: how often does this happen, and why?
2. Review the rules with a CPA who handles nonresident returns.
3. Read a W-2 or a full year of paystub PDFs directly.
4. Add J-1 researchers and multiple employers.
5. Flip the user: a payroll-side check that catches this before the money is withheld.
