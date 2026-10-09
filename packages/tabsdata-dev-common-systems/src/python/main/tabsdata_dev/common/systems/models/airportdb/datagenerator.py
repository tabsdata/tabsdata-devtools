#
# Copyright 2026 Tabsdata Inc.
#

"""Data generator for the ``airportdb`` model.

Builds a deterministic, self-consistent airport ecosystem — airports + geo,
airlines based at those airports, airplane fleets, employees, passengers,
recurring flight schedules, materialized flights, seat bookings and weather
observations — scaled by the requested size (the *bookings* count = the size
bucket; every other table is derived from it). Four entities take deltas:
``airport`` and ``passenger`` (insert / update — inserts mint unique
ICAO / passport values disjoint from the seed data), ``booking`` (delete
only — a leaf table nothing references) and ``weather`` (insert / update —
inserts are readings after the seed's last day; nothing references it).

What ``modify-data`` inserts into ``airport`` and ``passenger`` carries defects, each
at a rate the run draws from its seed (see ``_defect_rate``): a data-quality check
over the changes sees a different share of every defect from one run to the next,
better or worse, and a run stays as repeatable as its seed. What it inserts into
``weather`` is spread around centres the seed sets, with a share of out-of-range
faults (see ``_Weather``): a categorizer's histogram moves from run to run. The
seed data is clean.
"""

from __future__ import annotations

import functools
import random
import string
from datetime import date, datetime, time, timedelta

from tabsdata_dev.common.systems.datagen import (
    FIXED_SEED_INSERT_STRIDE,
    Entity,
    Model,
    OpKind,
    base36,
)
from tabsdata_dev.common.systems.emit import Column, Table

# The *bookings* count is the size bucket; every other table scales from it,
# reproducing v1 airportdb/sizing.json (prolific=--bookings, base=100000).
_PROLIFIC_BASE = 100000
_DEFAULTS = {
    "flights": 5000,
    "passengers": 5000,
    "airports": 200,
    "airlines": 50,
    "airplanes": 1000,
    "airplane_types": 100,
    "employees": 100,
    "weather_days": 30,
}
_MINS = {
    "flights": 20,
    "passengers": 20,
    "airports": 10,
    "airlines": 5,
    "airplanes": 10,
    "airplane_types": 5,
    "employees": 5,
    "weather_days": 1,
}
_CAPS = {
    "airlines": 113,
    "airplane_types": 300,
    "airports": 2000,
}


def _sized(flag: str, n: int) -> int:
    v = max(_DEFAULTS[flag] * n // _PROLIFIC_BASE, _MINS.get(flag, 1))
    if flag in _CAPS:
        v = min(v, _CAPS[flag])
    return v


# ---------- Pools ----------
COUNTRIES_CITIES = [
    (
        "United States",
        "New York",
        "Chicago",
        "Los Angeles",
        "Dallas",
        "Atlanta",
        "Denver",
    ),
    ("United Kingdom", "London", "Manchester", "Edinburgh"),
    ("Germany", "Frankfurt", "Munich", "Berlin", "Hamburg"),
    ("France", "Paris", "Lyon", "Nice"),
    ("Spain", "Madrid", "Barcelona", "Valencia"),
    ("Italy", "Rome", "Milan", "Venice"),
    ("Netherlands", "Amsterdam", "Rotterdam"),
    ("Switzerland", "Zurich", "Geneva"),
    ("Austria", "Vienna", "Salzburg"),
    ("Japan", "Tokyo", "Osaka", "Sapporo"),
    ("China", "Beijing", "Shanghai", "Guangzhou"),
    ("India", "Delhi", "Mumbai", "Bangalore"),
    ("Brazil", "Sao Paulo", "Rio de Janeiro"),
    ("Argentina", "Buenos Aires", "Cordoba"),
    ("Australia", "Sydney", "Melbourne"),
    ("Canada", "Toronto", "Vancouver", "Montreal"),
    ("Mexico", "Mexico City", "Guadalajara"),
    ("Russia", "Moscow", "St. Petersburg"),
    ("Turkey", "Istanbul", "Ankara"),
    ("UAE", "Dubai", "Abu Dhabi"),
]

AIRLINE_NAMES = [
    ("LH", "Lufthansa"),
    ("BA", "British Airways"),
    ("AF", "Air France"),
    ("KL", "KLM"),
    ("IB", "Iberia"),
    ("AZ", "ITA Airways"),
    ("OS", "Austrian Airlines"),
    ("LX", "Swiss"),
    ("SK", "SAS"),
    ("AY", "Finnair"),
    ("TK", "Turkish Airlines"),
    ("EK", "Emirates"),
    ("QR", "Qatar Airways"),
    ("EY", "Etihad"),
    ("SQ", "Singapore Airlines"),
    ("CX", "Cathay Pacific"),
    ("JL", "Japan Airlines"),
    ("NH", "ANA"),
    ("KE", "Korean Air"),
    ("OZ", "Asiana"),
    ("DL", "Delta"),
    ("AA", "American Airlines"),
    ("UA", "United"),
    ("WN", "Southwest"),
    ("B6", "JetBlue"),
    ("AS", "Alaska Airlines"),
    ("AC", "Air Canada"),
    ("WS", "WestJet"),
    ("AM", "Aeromexico"),
    ("LA", "LATAM"),
    ("AR", "Aerolineas Argentinas"),
    ("CM", "Copa"),
    ("VS", "Virgin Atlantic"),
    ("EI", "Aer Lingus"),
    ("FR", "Ryanair"),
    ("U2", "easyJet"),
    ("VY", "Vueling"),
    ("W6", "Wizz Air"),
    ("PC", "Pegasus"),
    ("MS", "EgyptAir"),
    ("ET", "Ethiopian Airlines"),
    ("SA", "South African Airways"),
    ("QF", "Qantas"),
    ("NZ", "Air New Zealand"),
]

AIRPLANE_TYPES = [
    ("A319", "Airbus A319-100, narrow-body twin-engine jet"),
    ("A320", "Airbus A320-200, narrow-body twin-engine jet"),
    ("A321", "Airbus A321-200, stretched A320 narrow-body"),
    ("A330", "Airbus A330-300, wide-body twin-engine jet"),
    ("A350", "Airbus A350-900, wide-body composite jet"),
    ("A380", "Airbus A380-800, double-deck wide-body"),
    ("B737", "Boeing 737-800, narrow-body twin-engine jet"),
    ("B738", "Boeing 737 MAX 8, latest 737 variant"),
    ("B739", "Boeing 737 MAX 9, stretched MAX variant"),
    ("B744", "Boeing 747-400, four-engine wide-body"),
    ("B748", "Boeing 747-8, modernised 747 variant"),
    ("B752", "Boeing 757-200, mid-size narrow-body"),
    ("B763", "Boeing 767-300, mid-size wide-body"),
    ("B772", "Boeing 777-200, long-range wide-body"),
    ("B77W", "Boeing 777-300ER, extended-range wide-body"),
    ("B788", "Boeing 787-8 Dreamliner, composite wide-body"),
    ("B789", "Boeing 787-9 Dreamliner, stretched 787"),
    ("E190", "Embraer E190, regional jet"),
    ("E195", "Embraer E195, stretched E190"),
    ("CRJ9", "Bombardier CRJ-900, regional jet"),
    ("AT72", "ATR 72, twin-engine turboprop"),
    ("DH8D", "Bombardier Dash 8 Q400, regional turboprop"),
]

CAPACITY_BY_TYPE = {
    "A319": 144,
    "A320": 180,
    "A321": 220,
    "A330": 290,
    "A350": 325,
    "A380": 525,
    "B737": 162,
    "B738": 175,
    "B739": 178,
    "B744": 416,
    "B748": 467,
    "B752": 200,
    "B763": 269,
    "B772": 314,
    "B77W": 396,
    "B788": 242,
    "B789": 290,
    "E190": 100,
    "E195": 132,
    "CRJ9": 90,
    "AT72": 70,
    "DH8D": 78,
}

DEPARTMENTS = ["Marketing", "Buchhaltung", "Management", "Logistik", "Flugfeld"]
# The seed's readings end on this day, at every station from 1 and every third hour.
_WEATHER_LAST_DAY = date(2024, 12, 31)

WEATHER_KINDS = [
    "Nebel",
    "Regen",
    "Schneefall",
    "Gewitter",
    "Nebel-Regen",
    "Nebel-Schneefall",
    "Regen-Schneefall",
    "Regen-Gewitter",
    "Nebel-Regen-Gewitter",
]

FIRST_NAMES = [
    "Sophie",
    "Emma",
    "Hannah",
    "Mia",
    "Anna",
    "Lara",
    "Lena",
    "Sarah",
    "Mara",
    "Leonie",
    "Maximilian",
    "Paul",
    "Leon",
    "Felix",
    "Niklas",
    "Tim",
    "Jonas",
    "Lukas",
    "Elias",
    "Liam",
    "Olivia",
    "Ava",
    "Isabella",
    "Charlotte",
    "Amelia",
    "Mila",
    "Aria",
    "Layla",
    "Emily",
    "Harper",
    "Lucas",
    "Mateo",
    "Ethan",
    "Daniel",
    "Carlos",
    "Marco",
    "Diego",
    "Ravi",
    "Aarav",
    "Ahmed",
    "Yuki",
    "Hiro",
    "Mei",
    "Ling",
    "Aiko",
    "Wei",
    "Chen",
    "Priya",
    "Asha",
    "Fatima",
]
LAST_NAMES = [
    "Müller",
    "Schmidt",
    "Schneider",
    "Fischer",
    "Weber",
    "Meyer",
    "Wagner",
    "Becker",
    "Schulz",
    "Hoffmann",
    "Smith",
    "Johnson",
    "Williams",
    "Brown",
    "Jones",
    "Davis",
    "Miller",
    "Wilson",
    "Moore",
    "Taylor",
    "Garcia",
    "Rodriguez",
    "Martinez",
    "Lopez",
    "Gonzalez",
    "Perez",
    "Sanchez",
    "Ramirez",
    "Torres",
    "Flores",
    "Rossi",
    "Russo",
    "Ferrari",
    "Esposito",
    "Bianchi",
    "Romano",
    "Ricci",
    "Conti",
    "Costa",
    "Greco",
    "Sato",
    "Suzuki",
    "Takahashi",
    "Tanaka",
    "Watanabe",
    "Ito",
    "Nakamura",
    "Kobayashi",
    "Yamamoto",
    "Kato",
    "Wang",
    "Li",
    "Zhang",
    "Liu",
    "Chen",
    "Yang",
    "Zhao",
    "Huang",
    "Zhou",
    "Wu",
]
STREETS = [
    "Hauptstr.",
    "Bahnhofstr.",
    "Schillerstr.",
    "Goetheweg",
    "Mozartgasse",
    "Lindenallee",
    "Marktplatz",
    "Kirchstr.",
    "Main St",
    "Park Ave",
    "Oak Rd",
    "Elm St",
    "Maple Dr",
]


# ---------- helpers ----------


def rand_iata(used, length):
    while True:
        c = "".join(random.choices(string.ascii_uppercase, k=length))
        if c not in used:
            used.add(c)
            return c


def rand_icao(used):
    while True:
        c = "".join(random.choices(string.ascii_uppercase, k=4))
        if c not in used:
            used.add(c)
            return c


def rand_phone():
    return (
        f"+{random.randint(1, 99)} {random.randint(10, 999)} "
        f"{random.randint(100000, 9999999)}"
    )


def rand_zip():
    return random.randint(10000, 99999)


def rand_md5():
    return "".join(random.choices("0123456789abcdef", k=32))


def rand_passport():
    return random.choice(string.ascii_uppercase) + "".join(
        random.choices(string.digits, k=8)
    )


# ---------- Generators ----------


def gen_airports(n):
    rows = []
    used_iata, used_icao = set(), set()
    flat = [(c, country) for country, *cities in COUNTRIES_CITIES for c in cities]
    for i in range(n):
        city, country = flat[i % len(flat)]
        suffix = "" if i < len(flat) else f" #{i // len(flat) + 1}"
        rows.append(
            {
                "airport_id": i + 1,
                "iata": rand_iata(used_iata, 3),
                "icao": rand_icao(used_icao),
                "name": f"{city}{suffix} International Airport"[:80],
                "city": city,
                "country": country,
                "latitude": round(random.uniform(-60, 70), 6),
                "longitude": round(random.uniform(-180, 180), 6),
            }
        )
    return rows


def gen_airlines(n, airports):
    rows, used = [], set()
    pool = list(AIRLINE_NAMES)
    random.shuffle(pool)
    for i in range(n):
        if i < len(pool):
            iata, name = pool[i]
        else:
            iata = rand_iata(used, 2)
            name = f"Air {iata}"
        used.add(iata)
        base = random.choice(airports[: max(1, len(airports) // 3)])
        rows.append(
            {
                "airline_id": i + 1,
                "iata": iata,
                "airline_name": name,
                "base_airport": base["airport_id"],
            }
        )
    return rows


def gen_airplane_types(n):
    rows, pool = [], list(AIRPLANE_TYPES)
    for i in range(n):
        if i < len(pool):
            ident, desc = pool[i]
        else:
            ident, desc = pool[i % len(pool)]
            ident = f"{ident}-V{i // len(pool) + 1}"
        rows.append({"type_id": i + 1, "identifier": ident, "description": desc})
    return rows


def gen_airplanes(n, types, airlines):
    rows = []
    for i in range(n):
        t = random.choice(types)
        a = random.choice(airlines)
        cap_base = CAPACITY_BY_TYPE.get(t["identifier"].split("-")[0], 180)
        rows.append(
            {
                "airplane_id": i + 1,
                "capacity": cap_base + random.randint(-10, 10),
                "type_id": t["type_id"],
                "airline_id": a["airline_id"],
            }
        )
    return rows


def gen_employees(n):
    rows, used = [], set()
    for i in range(n):
        sex = random.choice(["m", "f"])
        first = random.choice(FIRST_NAMES)
        last = random.choice(LAST_NAMES)
        username = f"{first[0].lower()}{last.lower()}{i + 1}"[:20]
        if username in used:
            username = f"{username}{i}"[:20]
        used.add(username)
        country, *cities = random.choice(COUNTRIES_CITIES)
        rows.append(
            {
                "employee_id": i + 1,
                "firstname": first,
                "lastname": last,
                "birthdate": date(1965, 1, 1)
                + timedelta(days=random.randint(0, 365 * 35)),
                "sex": sex,
                "street": f"{random.randint(1, 200)} {random.choice(STREETS)}",
                "city": random.choice(cities),
                "zip": rand_zip(),
                "country": country,
                "email": f"{username}@airline.com",
                "phone": rand_phone(),
                "salary": round(random.uniform(28000, 95000), 2),
                "department": random.choice(DEPARTMENTS),
                "username": username,
                "password": rand_md5(),
            }
        )
    return rows


def gen_passengers(n):
    pas, det = [], []
    used = set()
    for i in range(n):
        sex = random.choice(["m", "f"])
        first = random.choice(FIRST_NAMES)
        last = random.choice(LAST_NAMES)
        country, *cities = random.choice(COUNTRIES_CITIES)
        passport = rand_passport()
        while passport in used:
            passport = rand_passport()
        used.add(passport)
        pid = i + 1
        pas.append(
            {
                "passenger_id": pid,
                "passportno": passport,
                "firstname": first,
                "lastname": last,
            }
        )
        det.append(
            {
                "passenger_id": pid,
                "birthdate": date(1940, 1, 1)
                + timedelta(days=random.randint(0, 365 * 78)),
                "sex": sex,
                "street": f"{random.randint(1, 200)} {random.choice(STREETS)}",
                "city": random.choice(cities),
                "zip": rand_zip(),
                "country": country,
                "email": f"{first.lower()}.{last.lower()}{pid}@example.com",
                "phone": rand_phone(),
            }
        )
    return pas, det


def gen_flight_schedules(n, airports, airlines):
    rows, used = [], set()
    for _ in range(n):
        airline = random.choice(airlines)
        while True:
            flightno = f"{airline['iata']}{random.randint(100, 9999):04d}"[:8]
            if flightno not in used:
                used.add(flightno)
                break
        a = random.choice(airports)
        b = random.choice([x for x in airports if x["airport_id"] != a["airport_id"]])
        dep_h = random.randint(0, 22)
        dep_m = random.choice([0, 15, 30, 45])
        flight_minutes = random.choice([55, 75, 90, 120, 180, 240, 360, 480, 600])
        dep = time(dep_h, dep_m)
        arr_dt = datetime.combine(date(2020, 1, 1), dep) + timedelta(
            minutes=flight_minutes
        )
        arr = arr_dt.time()
        days = [random.random() < 0.55 for _ in range(7)]
        if not any(days):
            days[random.randint(0, 6)] = True
        rows.append(
            {
                "flightno": flightno,
                "from_airport": a["airport_id"],
                "to_airport": b["airport_id"],
                "departure": dep,
                "arrival": arr,
                "airline_id": airline["airline_id"],
                "monday": int(days[0]),
                "tuesday": int(days[1]),
                "wednesday": int(days[2]),
                "thursday": int(days[3]),
                "friday": int(days[4]),
                "saturday": int(days[5]),
                "sunday": int(days[6]),
                "_duration": flight_minutes,
                "_days": days,
            }
        )
    return rows


def gen_flights(n, schedules, airplanes):
    rows = []
    today = date(2024, 12, 31)
    for i in range(n):
        s = random.choice(schedules)
        for _ in range(8):
            day = today - timedelta(days=random.randint(0, 365))
            if s["_days"][day.weekday()]:
                break
        dep = datetime.combine(day, s["departure"])
        arr = dep + timedelta(minutes=s["_duration"])
        same = [p for p in airplanes if p["airline_id"] == s["airline_id"]]
        plane = random.choice(same) if same else random.choice(airplanes)
        rows.append(
            {
                "flight_id": i + 1,
                "flightno": s["flightno"],
                "from_airport": s["from_airport"],
                "to_airport": s["to_airport"],
                "departure": dep,
                "arrival": arr,
                "airline_id": s["airline_id"],
                "airplane_id": plane["airplane_id"],
                "_capacity": plane["capacity"],
            }
        )
    return rows


def gen_bookings(n, flights, passengers):
    rows = []
    if not flights:
        return rows
    per = max(1, n // len(flights))
    target = [per] * len(flights)
    extras = n - per * len(flights)
    for _ in range(max(0, extras)):
        target[random.randrange(len(flights))] += 1
    bid = 1
    for f, count in zip(flights, target):
        cap = f["_capacity"]
        count = min(count, cap)
        used = set()
        for _ in range(count):
            for _ in range(20):
                row = random.randint(1, max(2, cap // 6))
                letter = random.choice("ABCDEF")
                seat = f"{row:02d}{letter}"
                if seat not in used:
                    used.add(seat)
                    break
            p = random.choice(passengers)
            rows.append(
                {
                    "booking_id": bid,
                    "flight_id": f["flight_id"],
                    "seat": seat,
                    "passenger_id": p["passenger_id"],
                    "price": round(random.uniform(45.0, 1500.0), 2),
                }
            )
            bid += 1
    return rows


def gen_weather(n_stations, n_days):
    rows = []
    today = _WEATHER_LAST_DAY
    for d_off in range(n_days):
        day = today - timedelta(days=d_off)
        for s in range(1, n_stations + 1):
            for h in range(0, 24, 3):
                rows.append(
                    {
                        "log_date": day,
                        "log_time": time(h, 0),
                        "station": s,
                        "temp": round(random.uniform(-15, 35), 1),
                        "humidity": round(random.uniform(20, 100), 1),
                        "airpressure": round(random.uniform(950, 1050), 2),
                        "wind": round(random.uniform(0, 40), 2),
                        "weather": random.choice(WEATHER_KINDS + [None] * 4),
                        "winddirection": random.randint(0, 359),
                    }
                )
    return rows


# ---------- Column specs ----------

AIRPORT_COLS = [
    Column("airport_id", "int", nullable=False, auto=True),
    Column("iata", "char(3)"),
    Column("icao", "char(4)", nullable=False),
    Column("name", "varchar(80)", nullable=False),
]
GEO_COLS = [
    Column("airport_id", "int", nullable=False),
    Column("name", "varchar(80)", nullable=False),
    Column("city", "varchar(80)"),
    Column("country", "varchar(80)"),
    Column("latitude", "decimal(11,8)", nullable=False),
    Column("longitude", "decimal(11,8)", nullable=False),
]
AIRLINE_COLS = [
    Column("airline_id", "int", nullable=False, auto=True),
    Column("iata", "char(2)", nullable=False),
    Column("airline_name", "varchar(50)"),
    Column("base_airport", "int", nullable=False),
]
APTYPE_COLS = [
    Column("type_id", "int", nullable=False, auto=True),
    Column("identifier", "varchar(50)"),
    Column("description", "text"),
]
AIRPLANE_COLS = [
    Column("airplane_id", "int", nullable=False, auto=True),
    Column("capacity", "int", nullable=False),
    Column("type_id", "int", nullable=False),
    Column("airline_id", "int", nullable=False),
]
EMPLOYEE_COLS = [
    Column("employee_id", "int", nullable=False, auto=True),
    Column("firstname", "varchar(100)", nullable=False),
    Column("lastname", "varchar(100)", nullable=False),
    Column("birthdate", "date", nullable=False),
    Column("sex", "char(1)"),
    Column("street", "varchar(100)", nullable=False),
    Column("city", "varchar(100)", nullable=False),
    Column("zip", "int", nullable=False),
    Column("country", "varchar(100)", nullable=False),
    Column("email", "varchar(120)"),
    Column("phone", "varchar(30)"),
    Column("salary", "decimal(8,2)"),
    Column("department", "varchar(20)"),
    Column("username", "varchar(20)"),
    Column("password", "char(32)"),
]
PASSENGER_COLS = [
    Column("passenger_id", "int", nullable=False, auto=True),
    Column("passportno", "char(9)", nullable=False),
    Column("firstname", "varchar(100)", nullable=False),
    Column("lastname", "varchar(100)", nullable=False),
]
PASSDET_COLS = [
    Column("passenger_id", "int", nullable=False),
    Column("birthdate", "date", nullable=False),
    Column("sex", "char(1)"),
    Column("street", "varchar(100)", nullable=False),
    Column("city", "varchar(100)", nullable=False),
    Column("zip", "int", nullable=False),
    Column("country", "varchar(100)", nullable=False),
    Column("email", "varchar(120)"),
    Column("phone", "varchar(30)"),
]
SCHEDULE_COLS = [
    Column("flightno", "char(8)", nullable=False),
    Column("from_airport", "int", nullable=False),
    Column("to_airport", "int", nullable=False),
    Column("departure", "time", nullable=False),
    Column("arrival", "time", nullable=False),
    Column("airline_id", "int", nullable=False),
    Column("monday", "smallint"),
    Column("tuesday", "smallint"),
    Column("wednesday", "smallint"),
    Column("thursday", "smallint"),
    Column("friday", "smallint"),
    Column("saturday", "smallint"),
    Column("sunday", "smallint"),
]
FLIGHT_COLS = [
    Column("flight_id", "int", nullable=False, auto=True),
    Column("flightno", "char(8)", nullable=False),
    Column("from_airport", "int", nullable=False),
    Column("to_airport", "int", nullable=False),
    Column("departure", "datetime", nullable=False),
    Column("arrival", "datetime", nullable=False),
    Column("airline_id", "int", nullable=False),
    Column("airplane_id", "int", nullable=False),
]
BOOKING_COLS = [
    Column("booking_id", "int", nullable=False, auto=True),
    Column("flight_id", "int", nullable=False),
    Column("seat", "char(4)"),
    Column("passenger_id", "int", nullable=False),
    Column("price", "decimal(10,2)", nullable=False),
]
WEATHER_COLS = [
    Column("log_date", "date", nullable=False),
    Column("log_time", "time", nullable=False),
    Column("station", "int", nullable=False),
    Column("temp", "decimal(4,1)", nullable=False),
    Column("humidity", "decimal(4,1)", nullable=False),
    Column("airpressure", "decimal(10,2)", nullable=False),
    Column("wind", "decimal(5,2)", nullable=False),
    Column("weather", "varchar(30)"),
    Column("winddirection", "smallint", nullable=False),
]


# ---------- Delta entities ----------

# 4-char ICAO space for inserts: a leading digit + 3 base-36 chars. The leading
# digit keeps it disjoint from real (letter) ICAO codes even under a
# case-insensitive collation, and gives 10 * 36**3 unique values.
_ICAO_BODY = 36**3


def _insert_icao(i: int) -> str:
    return f"{(i // _ICAO_BODY) % 10}{base36(i % _ICAO_BODY, 3)}"


def _insert_iata(i: int) -> str:
    """Three upper-case letters from the ordinal. Not unique (``iata`` has no
    unique key on any backend), only well-formed."""
    out = ""
    for _ in range(3):
        i, r = divmod(i, 26)
        out = string.ascii_uppercase[r] + out
    return out


# What a defect does to an inserted row, and the classifier that sees it:
#   iata_missing      airport.iata left NULL            IsNotNull(iata)
#   iata_lowercase    airport.iata in lower case        Matches(iata, ^[A-Z]{3}$)
#   name_lowercase    airport.name in lower case        Matches(name, ^[A-ZÀ-ÖØ-Þ])
#   passport_bad      passportno C<7 digits>X           Matches(passportno, ^[A-Z][0-9]{8}$)
#   firstname_lower   passenger.firstname lower case    Matches(firstname, ^[A-ZÀ-ÖØ-Þ])
#   lastname_lower    passenger.lastname lower case     Matches(lastname, ^[A-ZÀ-ÖØ-Þ])
# No defect is an empty string: Oracle stores '' as NULL, and the names are NOT NULL.
_DEFECT_RATES = (0.05, 0.60)
_GOLDEN = (5**0.5 - 1) / 2


@functools.lru_cache(maxsize=1024)
def _seed_phase(name: str, seed: int) -> float:
    # A golden-ratio step per seed, from a start of the name's own: a few seeds
    # apart, two phases are never close (seeds 4 apart, as the trends suite's
    # passes run, are 0.47 apart around the circle), so a check sees what the
    # phase sets move on every run. A string seed hashes the same in every
    # process, unlike ``hash()``.
    start = random.Random(f"airportdb:{name}").random()
    return (start + seed * _GOLDEN) % 1.0


def _phase(name: str, i: int) -> float:
    """`name`'s phase in [0, 1) for the run inserting ordinal `i`: set by the
    run's seed, the block of ordinals the run owns
    (``i // FIXED_SEED_INSERT_STRIDE``), one sequence per name, so each moves on
    its own from run to run."""
    return _seed_phase(name, i // FIXED_SEED_INSERT_STRIDE)


def _defect_rate(defect: str, i: int) -> float:
    """The share of rows `defect` hits in the run inserting ordinal `i`."""
    low, high = _DEFECT_RATES
    return low + (high - low) * _phase(defect, i)


def _defective(rng: random.Random, defect: str, i: int) -> bool:
    return rng.random() < _defect_rate(defect, i)


class _Airport(Entity):
    table = "airport"
    columns = AIRPORT_COLS
    supports = (OpKind.INSERT, OpKind.UPDATE)
    rows_per_set = 1

    def new_row(self, rng: random.Random, i: int) -> dict:
        row = {"icao": _insert_icao(i), "name": f"Change Airport {i}"[:80]}
        # A missing iata is a column left out of the INSERT, so NULL.
        if not _defective(rng, "iata_missing", i):
            iata = _insert_iata(i)
            row["iata"] = iata.lower() if _defective(rng, "iata_lowercase", i) else iata
        if _defective(rng, "name_lowercase", i):
            row["name"] = row["name"].lower()
        return row

    def target(self, i: int, existing: int) -> dict:
        return {"airport_id": i + 1}

    def mutate(self, rng: random.Random, i: int, existing: int) -> dict:
        return {"name": f"Renamed Airport {i}"[:80]}


class _Passenger(Entity):
    table = "passenger"
    columns = PASSENGER_COLS
    supports = (OpKind.INSERT, OpKind.UPDATE)
    rows_per_set = 1

    def new_row(self, rng: random.Random, i: int) -> dict:
        # A bad passport is still 9 characters and unique: the column has a unique key.
        bad = _defective(rng, "passport_bad", i)
        first, last = f"First{i}"[:100], f"Last{i}"[:100]
        return {
            "passportno": f"C{i:07d}X" if bad else f"C{i:08d}",
            "firstname": first.lower()
            if _defective(rng, "firstname_lower", i)
            else first,
            "lastname": last.lower() if _defective(rng, "lastname_lower", i) else last,
        }

    def target(self, i: int, existing: int) -> dict:
        return {"passenger_id": i + 1}

    def mutate(self, rng: random.Random, i: int, existing: int) -> dict:
        return {"firstname": f"Chg{i}"[:100], "lastname": f"Upd{i}"[:100]}


class _Booking(Entity):
    table = "booking"
    columns = [Column("booking_id", "int", nullable=False, auto=True)]
    # Leaf table (nothing references a booking) — safe to delete from.
    supports = (OpKind.DELETE,)
    rows_per_set = 1

    def target(self, i: int, existing: int) -> dict:
        return {"booking_id": i + 1}


# What modify-data inserts into weather: readings whose spread the run's seed sets,
# for categorizers to bin -- each measure's centre (station: its busiest one) at the
# run's phase of it, so a run's histogram sits elsewhere than the last run's -- and a
# share of sensor faults, 2-10% per measure and run, each a value outside the
# measure's plausible range, below or above it. The ranges are what the
# dataquality/trends suite's scales span, so a fault is an under- or overflow and
# every other reading lands in a bin:
#   station        1..8          an integer per station
#   winddirection  0..360        degrees
#   wind           0..64         knots, exponentially distributed
#   humidity       0..100        percent
#   temp           -30..50       degrees Celsius
_STATIONS = 8
_FAULT_RATES = (0.02, 0.10)
# Inserted readings start the day after the seed's, a minute apart per ordinal, so
# their key never meets the seed's or another insert's whatever the station.
_WEATHER_INSERT_START = datetime.combine(
    _WEATHER_LAST_DAY + timedelta(days=1), time(0, 0)
)


def _faulty(rng: random.Random, measure: str, i: int) -> bool:
    low, high = _FAULT_RATES
    return rng.random() < low + (high - low) * _phase(f"{measure}_fault", i)


def _reading(
    rng: random.Random, measure: str, i: int, low: float, high: float, value: float
) -> float:
    """`value` held to [low, high], or -- a fault -- a value past one end, by 1 or
    more so an integer column truncates it to a value still outside."""
    if _faulty(rng, measure, i):
        past = rng.uniform(1, (high - low) / 4)
        return low - past if rng.random() < 0.5 else high + past
    return min(max(value, low), high)


class _Weather(Entity):
    table = "weather"
    columns = WEATHER_COLS
    supports = (OpKind.INSERT, OpKind.UPDATE)
    rows_per_set = 1

    def new_row(self, rng: random.Random, i: int) -> dict:
        at = _WEATHER_INSERT_START + timedelta(minutes=i)
        hub = 1 + int(_STATIONS * _phase("station", i))
        station = hub if rng.random() < 0.6 else rng.randint(1, _STATIONS)
        if _faulty(rng, "station", i):
            station = rng.choice((0, _STATIONS + 1))
        heading = rng.gauss(360 * _phase("winddirection", i), 45) % 360
        mean_wind = 1 + 24 * _phase("wind", i)
        return {
            "log_date": at.date(),
            "log_time": at.time(),
            "station": station,
            "temp": round(
                _reading(
                    rng, "temp", i, -30, 50, rng.gauss(-20 + 45 * _phase("temp", i), 6)
                ),
                1,
            ),
            "humidity": round(
                _reading(
                    rng,
                    "humidity",
                    i,
                    0,
                    100,
                    rng.gauss(30 + 65 * _phase("humidity", i), 8),
                ),
                1,
            ),
            "airpressure": round(rng.gauss(1013, 12), 2),
            "wind": round(
                _reading(rng, "wind", i, 0, 64, rng.expovariate(1 / mean_wind)), 2
            ),
            "weather": rng.choice(WEATHER_KINDS + [None] * 4),
            "winddirection": int(_reading(rng, "winddirection", i, 0, 360, heading)),
        }

    def target(self, i: int, existing: int) -> dict:
        # The seed's last day at station 1, which every size has: an update
        # rewrites one of those eight readings.
        return {
            "log_date": _WEATHER_LAST_DAY,
            "log_time": time(3 * (i % 8), 0),
            "station": 1,
        }

    def mutate(self, rng: random.Random, i: int, existing: int) -> dict:
        return {
            "airpressure": round(rng.gauss(1013, 12), 2),
            "weather": rng.choice(WEATHER_KINDS),
        }


class _AirportDb(Model):
    entities = [_Airport(), _Passenger(), _Booking(), _Weather()]

    def build_initial(self, rng: random.Random, n: int) -> list[Table]:
        random.seed(42)

        n_bookings = n
        n_flights = _sized("flights", n)
        n_passengers = _sized("passengers", n)
        n_airports = _sized("airports", n)
        n_airlines = _sized("airlines", n)
        n_airplanes = _sized("airplanes", n)
        n_airplane_types = _sized("airplane_types", n)
        n_employees = _sized("employees", n)
        n_weather_days = _sized("weather_days", n)

        airports = gen_airports(n_airports)
        airlines = gen_airlines(n_airlines, airports)
        types = gen_airplane_types(n_airplane_types)
        planes = gen_airplanes(n_airplanes, types, airlines)
        employees = gen_employees(n_employees)
        passengers, pdetails = gen_passengers(n_passengers)
        schedules = gen_flight_schedules(n_flights, airports, airlines)
        flights = gen_flights(n_flights, schedules, planes)
        bookings = gen_bookings(n_bookings, flights, passengers)
        weather = gen_weather(max(1, len(airports) // 5), n_weather_days)

        schedule_clean = [
            {k: v for k, v in s.items() if not k.startswith("_")} for s in schedules
        ]
        flight_clean = [
            {k: v for k, v in f.items() if not k.startswith("_")} for f in flights
        ]

        geo_rows = [
            {
                "airport_id": a["airport_id"],
                "name": a["name"],
                "city": a["city"],
                "country": a["country"],
                "latitude": a["latitude"],
                "longitude": a["longitude"],
            }
            for a in airports
        ]
        airport_rows = [
            {
                "airport_id": a["airport_id"],
                "iata": a["iata"],
                "icao": a["icao"],
                "name": a["name"],
            }
            for a in airports
        ]

        return [
            Table("airport", AIRPORT_COLS, airport_rows),
            Table("airport_geo", GEO_COLS, geo_rows),
            Table("airline", AIRLINE_COLS, airlines),
            Table("airplane_type", APTYPE_COLS, types),
            Table("airplane", AIRPLANE_COLS, planes),
            Table("employee", EMPLOYEE_COLS, employees),
            Table("passenger", PASSENGER_COLS, passengers),
            Table("passenger_details", PASSDET_COLS, pdetails),
            Table("flight_schedule", SCHEDULE_COLS, schedule_clean),
            Table("flight", FLIGHT_COLS, flight_clean),
            Table("booking", BOOKING_COLS, bookings),
            Table("weather", WEATHER_COLS, weather),
        ]


def datagenerator() -> Model:
    return _AirportDb()
