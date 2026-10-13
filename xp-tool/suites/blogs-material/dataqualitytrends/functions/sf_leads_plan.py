#
# Copyright 2026 Tabsdata Inc.
#

"""sf_leads_plan -- a Salesforce *Lead Lifetime* report, ten runs of it, and the
data-quality every run should show.

Standard library only: the publisher builds its rows from here and the check
reads the same plan, so the check knows every run's tallies exactly. The
functions spell their data quality out literally -- patterns, picklists, ranges,
scales -- so they read on their own; the constants here are the same values, for
making the data and checking it, and a drift between the two fails the check.

The report is 1000 leads, 100 a trigger -- a weekly run of the report, the run
of trigger ``t`` as of ``report_date(t)``. Columns are named as the report API's
``columnName`` (``SalesforceReportSrc``'s default), with ``DAYS_IN_STATUS`` for
the org's days-in-current-status formula field.

Every run, at most ``POOL`` (30) of its 100 rows carry an issue: per column the
defects of the run are drawn from those rows, the counts set by ``DEFECTS`` --
the classifier the defect fails and how its count moves over the ten runs:

- improving -- missing emails, placeholder companies, missing lead sources: the
  web form making the fields required, the backlog cleaned;
- stable -- out-of-range employee counts, phones without a country code, legacy
  statuses, one-letter last names: a steady trickle;
- up and down -- malformed emails, ratings off the picklist, revenue zero or
  negative: list imports landing some weeks and not others.

That is the report's own quality, checked as it is published. The business's
is the transformer's, on ``PIPELINE`` -- the leads plus two columns -- with two
categorizers: ``OPEN_DAYS``, the days of the leads still open (``OPEN``;
null for the rest) in 30-day buckets over a year -- the open backlog building up,
then worked off (``OPEN_MEAN_DAYS``), ``STALE`` open leads past a year and ``SKEWED``
ones dated after the report landing over and under -- and ``RATINGS``, Cold 1,
Warm 2, Hot 3, anything else 0, no rating (a categorizer bins numbers only), its
Hot share moving with the campaigns (``HOT``).

    python sf_leads_plan.py --csv FILE    writes the 1000 rows as a report export
"""

from __future__ import annotations

import csv
import math
import random
import re
import sys
from dataclasses import dataclass
from datetime import date, timedelta

TRIGGERS = 10
ROWS = 100
POOL = 30
COLLECTION = "sf_leads"
TABLE = "leads"
FUNCTION = "leads_report"
PIPELINE = "leads_pipeline"
PIPELINE_COLLECTION = "sf_pipeline"
FIRST_REPORT = date(2026, 8, 10)

EMAIL_PATTERN = r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$"
PHONE_PATTERN = r"^\+[1-9][0-9]{0,2}( [0-9]{2,4}){2,4}$"
VALID_RATINGS = ("Hot", "Warm", "Cold")
RATING_CODES = {"Cold": 1, "Warm": 2, "Hot": 3}
STATUSES = ("Open - Not Contacted", "Working - Contacted", "Closed - Converted", "Closed - Not Converted")
SOURCES = ("Web", "Phone Inquiry", "Partner Referral", "Purchased List", "Trade Show", "Webinar", "Other")
PLACEHOLDERS = ("[not provided]", "N/A", "Unknown", "-", "none")
OPEN = "Open - Not Contacted"
EMPLOYEES = (1, 10_000)
DAYS_BUCKET = 30
DAYS_MAX = 360

# The counts of every run, t = 0..9.
_IMPROVING = {
    "email_missing": (12, 10, 9, 7, 6, 5, 4, 3, 2, 1),
    "company_placeholder": (10, 9, 8, 6, 5, 4, 3, 3, 2, 1),
    "source_missing": (9, 8, 6, 5, 4, 4, 3, 2, 1, 1),
}
_STABLE = {
    "employees_out_of_range": (3, 3, 4, 3, 3, 2, 3, 3, 4, 3),
    "phone_malformed": (5, 4, 5, 5, 4, 5, 5, 4, 5, 5),
    "status_off_picklist": (2, 2, 1, 2, 2, 2, 1, 2, 2, 2),
    "last_name_short": (2, 3, 2, 2, 2, 3, 2, 2, 2, 3),
}
_UPS_AND_DOWNS = {
    "email_malformed": (3, 11, 2, 9, 4, 12, 1, 8, 3, 10),
    "rating_off_picklist": (6, 1, 9, 2, 11, 3, 8, 1, 10, 4),
    "revenue_not_positive": (2, 8, 1, 6, 2, 9, 3, 7, 1, 5),
}
DEFECTS = {**_IMPROVING, **_STABLE, **_UPS_AND_DOWNS}
TRENDS = {
    **dict.fromkeys(_IMPROVING, "improving"),
    **dict.fromkeys(_STABLE, "stable"),
    **dict.fromkeys(_UPS_AND_DOWNS, "up and down"),
}

OPEN_MEAN_DAYS = (20, 35, 55, 80, 95, 70, 45, 30, 25, 40)  # mean days an open lead waits
STALE = (1, 0, 2, 3, 5, 4, 2, 1, 0, 1)  # open leads untouched over a year
SKEWED = (0, 1, 0, 0, 2, 0, 1, 0, 0, 1)  # open leads dated after the report
HOT = (0.15, 0.20, 0.30, 0.45, 0.35, 0.20, 0.15, 0.25, 0.40, 0.30)


@dataclass(frozen=True)
class Check:
    """A boolean classifier: the column, the verdict column it names, and the
    defects it fails -- and, its column's nulls left as ``none``, the defects it
    cannot see."""

    column: str
    verdict: str
    fails: str
    blind: str | None = None

    @property
    def name(self) -> str:
        return f"@td.dq.{self.verdict}"


CHECKS = (
    Check("EMAIL", "email_present", "email_missing"),
    Check("EMAIL", "email_valid", "email_malformed", blind="email_missing"),
    Check("LEAD_SOURCE", "lead_source_present", "source_missing"),
    Check("COMPANY", "company_provided", "company_placeholder"),
    Check("RATING", "rating_valid", "rating_off_picklist"),
    Check("STATUS", "status_valid", "status_off_picklist"),
    Check("EMPLOYEES", "employees_in_range", "employees_out_of_range"),
    Check("PHONE", "phone_valid", "phone_malformed"),
    Check("LAST_NAME", "last_name_valid", "last_name_short"),
    Check("ANNUAL_REVENUE", "revenue_positive", "revenue_not_positive"),
)
CATEGORIZERS = ("@td.dq.open_days_bucket", "@td.dq.rating_bucket")

COLUMNS = (
    "LEAD_ID", "OWNER", "FIRST_NAME", "LAST_NAME", "TITLE", "COMPANY", "EMAIL", "PHONE",
    "COUNTRY", "INDUSTRY", "EMPLOYEES", "ANNUAL_REVENUE", "LEAD_SOURCE", "STATUS", "RATING",
    "DAYS_IN_STATUS", "CREATED_DATE", "LAST_UPDATE", "CONVERTED_DATE", "OPPORTUNITY_NAME",
    "OPPORTUNITY_AMOUNT", "CLOSE_DATE",
)  # fmt: skip

_OWNERS = ("Alex Rivera", "Priya Shah", "Sam Okafor", "Lena Fischer", "Diego Martin")
_FIRST = (
    "James", "Mary", "Wei", "Fatima", "Carlos", "Anna", "Kenji", "Olivia", "Rahul", "Sofia",
    "Liam", "Chloe", "Mateo", "Hannah", "Yusuf", "Grace", "Lucas", "Mia", "Noah", "Aisha",
    "Ethan", "Ines", "Omar", "Julia", "Leo", "Nora", "Ivan", "Zara", "Hugo", "Emma",
)  # fmt: skip
_LAST = (
    "Smith", "Garcia", "Chen", "Khan", "Muller", "Rossi", "Tanaka", "Brown", "Patel", "Lopez",
    "Martin", "Novak", "Silva", "Dubois", "Kowalski", "Nguyen", "Ahmed", "Larsen", "Costa",
    "Becker", "Moreau", "Jensen", "Romero", "Walsh", "Ito", "Fischer", "Hughes", "Ortiz",
)  # fmt: skip
_TITLES = ("VP Engineering", "Data Engineer", "CTO", "Head of Analytics", "IT Director", "Data Architect", "CFO")
_COMPANIES = (
    ("Northwind Traders", "northwind.com"), ("Globex", "globex.com"), ("Initech", "initech.io"),
    ("Umbrella Health", "umbrellahealth.com"), ("Stark Industries", "stark.com"),
    ("Wayne Logistics", "waynelogistics.com"), ("Acme Retail", "acmeretail.com"),
    ("Hooli", "hooli.com"), ("Pied Piper", "piedpiper.com"), ("Soylent Foods", "soylent.co"),
    ("Tyrell Energy", "tyrell.energy"), ("Cyberdyne", "cyberdyne.ai"), ("Vandelay Import", "vandelay.com"),
    ("Oscorp", "oscorp.com"), ("Massive Dynamic", "massivedynamic.com"), ("Aperture Labs", "aperture.io"),
    ("Blue Sun", "bluesun.com"), ("Gringotts Bank", "gringotts.bank"), ("Monarch Media", "monarch.media"),
    ("Dunder Paper", "dunderpaper.com"),
)  # fmt: skip
_COUNTRIES = (
    ("United States", "+1", (3, 3, 4)), ("Canada", "+1", (3, 3, 4)), ("United Kingdom", "+44", (2, 4, 4)),
    ("Germany", "+49", (2, 4, 4)), ("Spain", "+34", (2, 3, 4)), ("France", "+33", (3, 3, 3)),
)  # fmt: skip
_INDUSTRIES = ("Technology", "Finance", "Healthcare", "Manufacturing", "Retail", "Education", "Media", "Energy")

_BAD_PHONES = ("415-555-0123", "(212) 555 0199", "N/A", "TBD", "555-CALL-NOW", "0")
_BAD_RATINGS = ("hot", "WARM", "N/A", "--None--", "Lukewarm", "Very Hot")
_BAD_STATUSES = ("Qualified", "Nurturing", "Contacted", "open")
_BAD_LAST = ("X", "-", ".", "A")
_BAD_EMPLOYEES = (0, -5, 9_999_999, 1_000_000_000)
_BAD_REVENUE = (0.0, -1.0, -250_000.0)


def report_date(t: int) -> date:
    return FIRST_REPORT + timedelta(weeks=t)


def lead_id(t: int, row: int) -> str:
    return f"00Q5e0000{t * ROWS + row:06d}EAA"


def _bad_email(good: str, k: int) -> str:
    local, domain = good.split("@")
    return (
        f"{local}{domain}",  # no @
        f"{local}@",  # no domain
        f"{local}@@{domain}",
        f"{local.replace('.', ' ')}@{domain}",
        f"{local}@{domain.rsplit('.', 1)[0]}",  # no TLD
        f"{local}@{domain.replace('.', '..')}",
        "n/a",
    )[k % 7]


def _phone(rng: random.Random, country: tuple) -> str:
    _, prefix, groups = country
    return " ".join([prefix] + ["".join(str(rng.randrange(10)) for _ in range(n)) for n in groups])


def defect_rows(t: int) -> dict[str, list[int]]:
    """Per defect, the rows of trigger `t` that carry it; a column's defects never
    share a row, and every one is in the trigger's pool."""
    rng = random.Random(f"pool:{t}")
    pool = rng.sample(range(ROWS), POOL)
    out = {}
    for pair in (("email_missing", "email_malformed"),) + tuple(
        (d,) for d in DEFECTS if d not in ("email_missing", "email_malformed")
    ):
        drawn = rng.sample(pool, sum(DEFECTS[d][t] for d in pair))
        for d in pair:
            n = DEFECTS[d][t]
            out[d], drawn = drawn[:n], drawn[n:]
    # Days out of the scale: a stale or skewed lead is open, in the pool, and of a
    # valid status -- or it would fall out of the open leads' histogram.
    drawn = rng.sample([r for r in pool if r not in out["status_off_picklist"]], STALE[t] + SKEWED[t])
    out["stale"], out["skewed"] = drawn[: STALE[t]], drawn[STALE[t] :]
    return out


def rows(t: int) -> list[dict]:
    """The 100 rows of trigger `t`'s report, in report order."""
    at = report_date(t)
    marks: dict[int, set[str]] = {}
    for d, found in defect_rows(t).items():
        for row in found:
            marks.setdefault(row, set()).add(d)
    hot = HOT[t]
    out = []
    for row in range(ROWS):
        rng = random.Random(f"lead:{t}:{row}")
        has = marks.get(row, set())
        first, last = rng.choice(_FIRST), rng.choice(_LAST)
        company, domain = rng.choice(_COMPANIES)
        country = rng.choice(_COUNTRIES)
        email = f"{first.lower()}.{last.lower()}@{domain}"
        status = rng.choices(STATUSES, weights=(35, 30, 15, 20))[0]
        rating = rng.choices(VALID_RATINGS, weights=(hot, 0.35, 0.65 - hot))[0]
        employees = int(min(EMPLOYEES[1], max(EMPLOYEES[0], round(rng.lognormvariate(4.5, 1.6)))))
        revenue = float(round(employees * rng.uniform(80_000, 300_000), -3))
        match status:
            case "Open - Not Contacted":
                days = DAYS_MAX + 1  # redrawn rather than clamped: no pile-up in the last bucket
                while days > DAYS_MAX:
                    days = int(rng.expovariate(1 / OPEN_MEAN_DAYS[t]))
            case "Working - Contacted":
                days = rng.randint(1, 60)
            case _:
                days = rng.randint(0, 180)
        if "stale" in has:
            status, days = OPEN, rng.randint(DAYS_MAX + 1, 900)
        if "skewed" in has:
            status, days = OPEN, -rng.randint(1, 15)
        k = rng.randrange(1000)
        if "email_missing" in has:
            email = None
        if "email_malformed" in has:
            email = _bad_email(email, k)
        if "last_name_short" in has:
            last = _BAD_LAST[k % len(_BAD_LAST)]
        if "status_off_picklist" in has:
            status = _BAD_STATUSES[k % len(_BAD_STATUSES)]
        if "rating_off_picklist" in has:
            rating = _BAD_RATINGS[k % len(_BAD_RATINGS)]
        if "employees_out_of_range" in has:
            employees = _BAD_EMPLOYEES[k % len(_BAD_EMPLOYEES)]
        if "revenue_not_positive" in has:
            revenue = _BAD_REVENUE[k % len(_BAD_REVENUE)]
        changed = at - timedelta(days=days)
        created = min(changed, at) - timedelta(days=rng.randint(0, 90))
        converted = status == "Closed - Converted"
        out.append(
            {
                "LEAD_ID": lead_id(t, row),
                "OWNER": rng.choice(_OWNERS),
                "FIRST_NAME": first,
                "LAST_NAME": last,
                "TITLE": rng.choice(_TITLES),
                "COMPANY": PLACEHOLDERS[k % len(PLACEHOLDERS)] if "company_placeholder" in has else company,
                "EMAIL": email,
                "PHONE": _BAD_PHONES[k % len(_BAD_PHONES)] if "phone_malformed" in has else _phone(rng, country),
                "COUNTRY": country[0],
                "INDUSTRY": rng.choice(_INDUSTRIES),
                "EMPLOYEES": employees,
                "ANNUAL_REVENUE": revenue,
                "LEAD_SOURCE": None if "source_missing" in has else rng.choice(SOURCES),
                "STATUS": status,
                "RATING": rating,
                "DAYS_IN_STATUS": days,
                "CREATED_DATE": created,
                "LAST_UPDATE": changed,
                "CONVERTED_DATE": changed if converted else None,
                "OPPORTUNITY_NAME": f"{company} - New Business" if converted else None,
                "OPPORTUNITY_AMOUNT": float(rng.randrange(10, 400) * 500) if converted else None,
                "CLOSE_DATE": changed + timedelta(days=rng.randint(30, 120)) if converted else None,
            }
        )
    return out


def rows_with_issues(t: int) -> int:
    return len({row for found in defect_rows(t).values() for row in found})


def expected_booleans(t: int) -> dict[str, dict[str, int]]:
    """Per boolean classifier, trigger `t`'s dq.true, dq.false, dq.none and dq.nan."""
    out = {}
    for c in CHECKS:
        failed = DEFECTS[c.fails][t]
        none = DEFECTS[c.blind][t] if c.blind else 0
        out[c.name] = {"dq.true": ROWS - failed - none, "dq.false": failed, "dq.none": none, "dq.nan": 0}
    return out


def days_bin(days: int) -> str:
    """The summary column a day count lands in: [0, 30] is the first bucket."""
    if days < 0:
        return "dq.under"
    if days > DAYS_MAX:
        return "dq.over"
    return f"dq.p{max(1, math.ceil(days / DAYS_BUCKET)):03d}"


def rating_bin(rating: str) -> str:
    """IdentityScale(0, 3, use_bin_zero=True): no rating p000, Cold p001, Warm p002,
    Hot p003."""
    return f"dq.p{RATING_CODES.get(rating, 0):03d}"


def expected_categories(t: int) -> dict[str, dict[str, int]]:
    """Per categorizer, trigger `t`'s count in every column the plan fills."""
    days: dict[str, int] = {}
    ratings: dict[str, int] = {}
    for r in rows(t):
        d = days_bin(r["DAYS_IN_STATUS"]) if r["STATUS"] == OPEN else "dq.none"
        days[d] = days.get(d, 0) + 1
        ratings[rating_bin(r["RATING"])] = ratings.get(rating_bin(r["RATING"]), 0) + 1
    return {CATEGORIZERS[0]: days, CATEGORIZERS[1]: ratings}


def self_check() -> list[str]:
    """The plan against itself: every defect really fails, nothing else does."""
    problems = []
    email, phone = re.compile(EMAIL_PATTERN), re.compile(PHONE_PATTERN)
    for t in range(TRIGGERS):
        marks = defect_rows(t)
        if rows_with_issues(t) > POOL:
            problems.append(f"t={t}: {rows_with_issues(t)} rows with issues")
        for row, r in enumerate(rows(t)):
            got = {
                "email_missing": r["EMAIL"] is None,
                "email_malformed": r["EMAIL"] is not None and not email.match(r["EMAIL"]),
                "source_missing": r["LEAD_SOURCE"] is None,
                "company_placeholder": r["COMPANY"] in PLACEHOLDERS,
                "rating_off_picklist": r["RATING"] not in VALID_RATINGS,
                "employees_out_of_range": not EMPLOYEES[0] <= r["EMPLOYEES"] <= EMPLOYEES[1],
                "phone_malformed": not phone.match(r["PHONE"]),
                "status_off_picklist": r["STATUS"] not in STATUSES,
                "last_name_short": len(r["LAST_NAME"]) < 2,
                "revenue_not_positive": r["ANNUAL_REVENUE"] <= 0,
            }
            for d, bad in got.items():
                if bad != (row in marks[d]):
                    problems.append(f"t={t} row {row}: {d} is {bad}, the plan says {not bad}")
    return problems


def main(argv: list[str]) -> int:
    if argv[:1] != ["--csv"] or len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 1
    with open(argv[1], "w", newline="") as f:
        out = csv.DictWriter(f, fieldnames=COLUMNS)
        out.writeheader()
        for t in range(TRIGGERS):
            out.writerows(rows(t))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
