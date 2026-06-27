"""
DYŻUR — backend MVP (FastAPI + SQLAlchemy)
Jeden plik: modele, silnik dopasowania, API, serwowanie frontu.

Uruchomienie lokalne:
    pip install -r requirements.txt
    uvicorn main:app --reload
    -> http://127.0.0.1:8000

W chmurze (Render) baza ustawiana jest przez zmienną DATABASE_URL.
Lokalnie domyślnie używany jest plik SQLite (dyzur.db).
"""

import os
import math
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import create_engine, Integer, String, Float, Boolean, DateTime, text
from sqlalchemy.orm import (
    DeclarativeBase, Mapped, mapped_column, Session, sessionmaker,
)

# --------------------------------------------------------------------------
# BAZA DANYCH
# --------------------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./dyzur.db")
# Render bywa zwraca "postgres://", SQLAlchemy potrzebuje "postgresql://"
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


class Nurse(Base):
    __tablename__ = "nurses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    city: Mapped[str] = mapped_column(String)
    spec: Mapped[str] = mapped_column(String)
    years: Mapped[int] = mapped_column(Integer)
    forma: Mapped[str] = mapped_column(String)
    tryb: Mapped[str] = mapped_column(String)
    max_km: Mapped[int] = mapped_column(Integer, default=50)
    expected: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str] = mapped_column(String, default="")


class Offer(Base):
    __tablename__ = "offers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    place: Mapped[str] = mapped_column(String)
    city: Mapped[str] = mapped_column(String)
    spec: Mapped[str] = mapped_column(String)
    min_years: Mapped[int] = mapped_column(Integer)
    forma: Mapped[str] = mapped_column(String)
    tryb: Mapped[str] = mapped_column(String)
    salary: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(String, default="")
    # pola importera Adzuny
    source: Mapped[str] = mapped_column(String, default="direct")
    external_id: Mapped[str] = mapped_column(String, default="", index=True)
    title: Mapped[str] = mapped_column(String, default="")  # oryginalny tytuł — do deduplikacji
    url: Mapped[str] = mapped_column(String, default="")
    salary_predicted: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --------------------------------------------------------------------------
# SILNIK DOPASOWANIA (port 1:1 z prototypu JS)
# --------------------------------------------------------------------------
CITIES = {
    "Warszawa": (52.2297, 21.0122), "Kraków": (50.0647, 19.945),
    "Wrocław": (51.1079, 17.0385), "Poznań": (52.4064, 16.9252),
    "Gdańsk": (54.352, 18.6466), "Katowice": (50.2649, 19.0238),
    "Łódź": (51.7592, 19.456), "Rzeszów": (50.0412, 21.9991),
    "Jasło": (49.7448, 21.4715), "Lublin": (51.2465, 22.5684),
    "Bydgoszcz": (53.1235, 18.0084), "Szczecin": (53.4285, 14.5528),
    # Dolny Śląsk (region startowy)
    "Wałbrzych": (50.7846, 16.2840), "Legnica": (51.2070, 16.1619),
    "Jelenia Góra": (50.9044, 15.7197), "Lubin": (51.4009, 16.2010),
    "Głogów": (51.6640, 16.0858), "Świdnica": (50.8449, 16.4892),
    "Bolesławiec": (51.2640, 15.5694), "Oleśnica": (51.2100, 17.3800),
    "Oława": (50.9450, 17.2920), "Dzierżoniów": (50.7277, 16.6531),
    "Kłodzko": (50.4347, 16.6618), "Zgorzelec": (51.1499, 15.0095),
    "Polkowice": (51.5050, 16.0710), "Trzebnica": (51.3100, 17.0640),
    "Ząbkowice Śląskie": (50.5905, 16.8125), "Lubań": (51.1200, 15.2900),
    "Złotoryja": (51.1260, 15.9100), "Jawor": (51.0510, 16.1930),
    "Bielawa": (50.6900, 16.6200), "Nowa Ruda": (50.5800, 16.5000),
    "Kamienna Góra": (50.7800, 16.0300), "Strzelin": (50.7800, 17.0650),
    "Środa Śląska": (51.1640, 16.5950), "Milicz": (51.5270, 17.2760),
    "Wołów": (51.3390, 16.6440), "Góra": (51.6660, 16.5400),
    "Brzeg Dolny": (51.2730, 16.7300),
}

# zbiór miast regionu startowego — do filtra importu
DOLNOSLASKIE = {
    "Wrocław", "Wałbrzych", "Legnica", "Jelenia Góra", "Lubin", "Głogów",
    "Świdnica", "Bolesławiec", "Oleśnica", "Oława", "Dzierżoniów", "Kłodzko",
    "Zgorzelec", "Polkowice", "Trzebnica", "Ząbkowice Śląskie", "Lubań",
    "Złotoryja", "Jawor", "Bielawa", "Nowa Ruda", "Kamienna Góra", "Strzelin",
    "Środa Śląska", "Milicz", "Wołów", "Góra", "Brzeg Dolny",
}

SPEC_FAMILY = {
    "Anestezjologiczne i intensywna terapia": "krytyczna",
    "Ratunkowe / SOR": "krytyczna",
    "Chirurgiczne / blok operacyjny": "zabiegowa",
    "Internistyczne / zachowawcze": "zachowawcza",
    "Kardiologiczne": "zachowawcza",
    "Onkologiczne": "zachowawcza",
    "Dializoterapia / nefrologiczne": "zachowawcza",
    "POZ / środowiskowo-rodzinne": "podstawowa",
    "Pediatryczne / neonatologiczne": "pediatria",
    "Geriatryczne / opieka długoterminowa": "dlugoterminowa",
}


def distance_km(a: str, b: str) -> int:
    if a == b:
        return 0
    if a not in CITIES or b not in CITIES:
        return 150  # fallback dla miast spoza bazy (do podmiany na geocoding)
    (la1, lo1), (la2, lo2) = CITIES[a], CITIES[b]
    R = 6371
    d_la = math.radians(la2 - la1)
    d_lo = math.radians(lo2 - lo1)
    s = (math.sin(d_la / 2) ** 2
         + math.cos(math.radians(la1)) * math.cos(math.radians(la2))
         * math.sin(d_lo / 2) ** 2)
    return round(2 * R * math.asin(math.sqrt(s)))


def score(nurse: Nurse, offer: Offer) -> dict:
    # specjalizacja (20)
    if nurse.spec == offer.spec:
        spec = 20
    elif SPEC_FAMILY.get(nurse.spec) == SPEC_FAMILY.get(offer.spec):
        spec = 12
    else:
        spec = 4

    # lokalizacja (20)
    d = distance_km(nurse.city, offer.city)
    if d <= nurse.max_km:
        loc = 20
    elif d <= nurse.max_km * 2:
        loc = round(20 - ((d - nurse.max_km) / nurse.max_km) * 14)
    else:
        loc = 3

    # forma (15) — "Nieokreślona" (z importu, brak danych) ma niższą, neutralną wartość
    if "Nieokreślona" in (nurse.forma, offer.forma):
        forma = 9
    elif nurse.forma == offer.forma or "Dowolna" in (nurse.forma, offer.forma):
        forma = 15
    elif all(f in ("Umowa o pracę", "Umowa zlecenie") for f in (nurse.forma, offer.forma)):
        forma = 8
    else:
        forma = 4

    # tryb (10) — "Nieokreślony" (z importu) niżej niż świadomy "Dowolny"
    if "Nieokreślony" in (nurse.tryb, offer.tryb):
        tryb = 6
    elif nurse.tryb == offer.tryb or "Dowolny" in (nurse.tryb, offer.tryb):
        tryb = 10
    else:
        tryb = 3

    # doświadczenie (10)
    if offer.min_years <= 0 or nurse.years >= offer.min_years:
        exp = 10
    else:
        exp = max(3, round((nurse.years / offer.min_years) * 10))

    # wynagrodzenie (25) — neutralne 10 pkt, gdy pensji brak albo jest estymacją Adzuny
    if not nurse.expected:
        sal = 25
    elif (not offer.salary) or getattr(offer, "salary_predicted", False):
        sal = 10  # nie wiemy realnie, nie decydujemy na podstawie zgadywanej kwoty
    elif offer.salary >= nurse.expected:
        sal = 25
    elif offer.salary >= nurse.expected * 0.9:
        sal = 15
    else:
        sal = 5

    return {
        "total": spec + loc + forma + tryb + exp + sal,
        "parts": {"spec": spec, "loc": loc, "forma": forma,
                  "tryb": tryb, "exp": exp, "sal": sal},
        "distance": d,
    }


# --------------------------------------------------------------------------
# SCHEMATY (walidacja wejścia)
# --------------------------------------------------------------------------
class NurseIn(BaseModel):
    name: str = "Nowa pielęgniarka"
    city: str
    spec: str
    years: int = 0
    forma: str
    tryb: str
    max_km: int = 50
    expected: int = 0
    note: str = ""


class OfferIn(BaseModel):
    place: str = "Nowa placówka"
    city: str
    spec: str
    min_years: int = 0
    forma: str
    tryb: str
    salary: int = 0
    note: str = ""


def nurse_dict(n: Nurse) -> dict:
    return {"id": n.id, "name": n.name, "city": n.city, "spec": n.spec,
            "years": n.years, "forma": n.forma, "tryb": n.tryb,
            "max_km": n.max_km, "expected": n.expected, "note": n.note}


def offer_dict(o: Offer) -> dict:
    return {"id": o.id, "place": o.place, "city": o.city, "spec": o.spec,
            "min_years": o.min_years, "forma": o.forma, "tryb": o.tryb,
            "salary": o.salary, "note": o.note,
            "url": getattr(o, "url", "") or "",
            "source": getattr(o, "source", "direct"),
            "salary_predicted": bool(getattr(o, "salary_predicted", False))}


# --------------------------------------------------------------------------
# DANE STARTOWE (wstawiane raz, gdy baza pusta)
# --------------------------------------------------------------------------
SEED_NURSES = [
    dict(name="Anna K.", city="Rzeszów", spec="Anestezjologiczne i intensywna terapia", years=9, forma="Umowa o pracę", tryb="Zmianowy (w tym noce)", max_km=60, expected=7200, note="Szukam stabilnego etatu w OIT bliżej domu, doświadczenie z respiratoroterapią."),
    dict(name="Magdalena P.", city="Jasło", spec="POZ / środowiskowo-rodzinne", years=14, forma="Umowa o pracę", tryb="Jednozmianowy (dzienny)", max_km=40, expected=6000, note="Kurs szczepień i pielęgniarstwa rodzinnego, zależy mi na pracy w dzień."),
    dict(name="Joanna W.", city="Kraków", spec="Pediatryczne / neonatologiczne", years=4, forma="Dowolna", tryb="Dowolny", max_km=50, expected=6500, note="Po specjalizacji neonatologicznej, otwarta na różne formy współpracy."),
    dict(name="Katarzyna Z.", city="Warszawa", spec="Chirurgiczne / blok operacyjny", years=11, forma="Kontrakt B2B", tryb="Zmianowy (w tym noce)", max_km=30, expected=9500, note="Instrumentariuszka, preferuję kontrakt, blok operacyjny."),
    dict(name="Ewa S.", city="Wrocław", spec="Ratunkowe / SOR", years=6, forma="Umowa o pracę", tryb="Zmianowy (w tym noce)", max_km=45, expected=7000, note="SOR, lubię dynamikę, gotowa na dyżury nocne."),
    dict(name="Barbara L.", city="Lublin", spec="Geriatryczne / opieka długoterminowa", years=19, forma="Umowa zlecenie", tryb="Jednozmianowy (dzienny)", max_km=35, expected=5800, note="Wieloletnie doświadczenie w ZOL, szukam spokojniejszego trybu."),
    dict(name="Agnieszka M.", city="Rzeszów", spec="Kardiologiczne", years=7, forma="Umowa o pracę", tryb="Dowolny", max_km=70, expected=7400, note="Oddział kardiologii, kurs EKG, mogę dojeżdżać."),
    dict(name="Monika T.", city="Gdańsk", spec="Onkologiczne", years=8, forma="Dowolna", tryb="Jednozmianowy (dzienny)", max_km=40, expected=7800, note="Koordynacja onkologiczna, edukacja pacjenta, praca w dzień."),
]

SEED_OFFERS = [
    dict(place="Kliniczny Szpital Wojewódzki — OIT", city="Rzeszów", spec="Anestezjologiczne i intensywna terapia", min_years=5, forma="Umowa o pracę", tryb="Zmianowy (w tym noce)", salary=7500, note="Pielęgniarka anestezjologiczna na OIT. Dodatek za pracę w porze nocnej."),
    dict(place="Przychodnia POZ Zdrowie", city="Jasło", spec="POZ / środowiskowo-rodzinne", min_years=2, forma="Umowa o pracę", tryb="Jednozmianowy (dzienny)", salary=6100, note="Praca od poniedziałku do piątku, gabinet zabiegowy i szczepienia."),
    dict(place="Centrum Medyczne Dziecięce", city="Kraków", spec="Pediatryczne / neonatologiczne", min_years=3, forma="Umowa o pracę", tryb="Dowolny", salary=6600, note="Oddział neonatologii, mile widziana specjalizacja, elastyczny grafik."),
    dict(place="Szpital Specjalistyczny — Blok Operacyjny", city="Katowice", spec="Chirurgiczne / blok operacyjny", min_years=8, forma="Kontrakt B2B", tryb="Zmianowy (w tym noce)", salary=9800, note="Instrumentariuszka na blok, kontrakt, atrakcyjne stawki dyżurowe."),
    dict(place="Wojewódzki Szpital — SOR", city="Wrocław", spec="Ratunkowe / SOR", min_years=4, forma="Umowa o pracę", tryb="Zmianowy (w tym noce)", salary=7100, note="Szpitalny oddział ratunkowy, praca zmianowa, zgrany zespół."),
    dict(place="Zakład Opiekuńczo-Leczniczy Senior", city="Lublin", spec="Geriatryczne / opieka długoterminowa", min_years=1, forma="Umowa zlecenie", tryb="Jednozmianowy (dzienny)", salary=5900, note="Opieka długoterminowa nad pacjentem geriatrycznym, stabilny grafik dzienny."),
    dict(place="Centrum Kardiologii", city="Kraków", spec="Kardiologiczne", min_years=5, forma="Umowa o pracę", tryb="Jednozmianowy (dzienny)", salary=7300, note="Oddział kardiologii, wymagany kurs EKG, praca głównie w dzień."),
    dict(place="Centrum Onkologii — Poradnia", city="Gdańsk", spec="Onkologiczne", min_years=6, forma="Umowa o pracę", tryb="Jednozmianowy (dzienny)", salary=7900, note="Koordynacja onkologiczna, edukacja i wsparcie pacjentów onkologicznych."),
]


def seed_if_empty():
    db = SessionLocal()
    try:
        if db.query(Nurse).count() == 0:
            db.add_all(Nurse(**n) for n in SEED_NURSES)
        # ofert już nie seedujemy — pochodzą z importu Adzuny
        db.commit()
    finally:
        db.close()


# --------------------------------------------------------------------------
# APLIKACJA
# --------------------------------------------------------------------------
def migrate_offers():
    """Dodaje nowe kolumny do istniejącej tabeli offers (Postgres/SQLite),
    bez kasowania danych. Idempotentne — bezpieczne przy każdym starcie."""
    alters = [
        "ALTER TABLE offers ADD COLUMN IF NOT EXISTS source VARCHAR DEFAULT 'direct'",
        "ALTER TABLE offers ADD COLUMN IF NOT EXISTS external_id VARCHAR DEFAULT ''",
        "ALTER TABLE offers ADD COLUMN IF NOT EXISTS title VARCHAR DEFAULT ''",
        "ALTER TABLE offers ADD COLUMN IF NOT EXISTS url VARCHAR DEFAULT ''",
        "ALTER TABLE offers ADD COLUMN IF NOT EXISTS salary_predicted BOOLEAN DEFAULT FALSE",
        "ALTER TABLE offers ADD COLUMN IF NOT EXISTS active BOOLEAN DEFAULT TRUE",
        "ALTER TABLE offers ADD COLUMN IF NOT EXISTS created_at TIMESTAMP",
        "ALTER TABLE offers ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMP",
    ]
    with engine.begin() as conn:
        for stmt in alters:
            try:
                conn.execute(text(stmt))
            except Exception:
                pass  # np. SQLite bez IF NOT EXISTS — kolumna już jest


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    migrate_offers()
    seed_if_empty()
    yield


app = FastAPI(title="Dyżur API", lifespan=lifespan)


@app.get("/api/nurses")
def list_nurses(db: Session = Depends(get_db)):
    return [nurse_dict(n) for n in db.query(Nurse).order_by(Nurse.id.desc())]


@app.get("/api/offers")
def list_offers(db: Session = Depends(get_db)):
    q = db.query(Offer).filter(Offer.active == True).order_by(Offer.id.desc()).limit(200)
    return [offer_dict(o) for o in q]


@app.post("/api/nurses")
def add_nurse(data: NurseIn, db: Session = Depends(get_db)):
    n = Nurse(**data.model_dump())
    db.add(n)
    db.commit()
    db.refresh(n)
    return nurse_dict(n)


@app.post("/api/offers")
def add_offer(data: OfferIn, db: Session = Depends(get_db)):
    o = Offer(**data.model_dump())
    db.add(o)
    db.commit()
    db.refresh(o)
    return offer_dict(o)


@app.get("/api/match")
def match(role: str, id: int, db: Session = Depends(get_db)):
    if role == "nurse":
        nurse = db.get(Nurse, id)
        if not nurse:
            raise HTTPException(404, "Nie znaleziono pielęgniarki")
        results = []
        for o in db.query(Offer).filter(Offer.active == True):
            s = score(nurse, o)
            results.append({"item": offer_dict(o), **s})
    elif role == "employer":
        offer = db.get(Offer, id)
        if not offer:
            raise HTTPException(404, "Nie znaleziono oferty")
        results = []
        for n in db.query(Nurse):
            s = score(n, offer)
            results.append({"item": nurse_dict(n), **s})
    else:
        raise HTTPException(400, "role musi być 'nurse' lub 'employer'")
    results.sort(key=lambda r: r["total"], reverse=True)
    return results


# --------------------------------------------------------------------------
# IMPORTER ADZUNY — zaciąga oferty, mapuje na model, robi upsert
# --------------------------------------------------------------------------
IMPORT_STATUS = {"running": False, "last_run": None, "added": 0,
                 "updated": 0, "errors": 0, "fetched": 0, "deactivated": 0}


def _adzuna_city(ad):
    """Wyciąga miasto z pola location Adzuny i dopasowuje do bazy CITIES, jeśli się da."""
    loc = ad.get("location", {}) or {}
    area = loc.get("area") or []
    candidates = list(reversed(area)) + [loc.get("display_name", "")]
    for c in candidates:
        c = (c or "").split(",")[0].strip()
        if c in CITIES:
            return c
    # nie ma w bazie — zwróć najbardziej szczegółowy człon (distance da fallback 150 km)
    return (area[-1] if area else (loc.get("display_name", "") or "")).split(",")[0].strip() or "Polska"


def _adzuna_forma(ad):
    ct = (ad.get("contract_type") or "").lower()
    if ct == "permanent":
        return "Umowa o pracę"
    if ct == "contract":
        return "Kontrakt B2B"
    return "Nieokreślona"  # brak danych — neutralne, nie pełne punkty


def _adzuna_tryb(text_blob):
    t = (text_blob or "").lower()
    if "noc" in t or "zmianow" in t or "dyżur" in t:
        return "Zmianowy (w tym noce)"
    if "jednozmian" in t or "dzienn" in t or "poniedziałek" in t:
        return "Jednozmianowy (dzienny)"
    return "Nieokreślony"  # brak danych — neutralne


def _adzuna_place(ad):
    """Nazwa pracodawcy, ale gdy Adzuna zwróci portal pośredniczący, użyj tytułu oferty."""
    company = ((ad.get("company", {}) or {}).get("display_name") or "").strip()
    title = (ad.get("title", "") or "").strip()
    portal_markers = [".pl", "praca", "jobs", "work", "rekrutacj", "olx", "indeed", "gowork", "pracuj"]
    c = company.lower()
    if not company or any(m in c for m in portal_markers):
        return (title or "Oferta dla pielęgniarki")[:160]
    return company[:160]


def _in_region(ad):
    """Czy oferta jest w województwie dolnośląskim (region startowy)."""
    loc = ad.get("location", {}) or {}
    text = (loc.get("display_name", "") + " " + " ".join(loc.get("area") or [])).lower()
    if "dolnośląsk" in text or "dolnoslask" in text or "lower silesia" in text:
        return True
    return _adzuna_city(ad) in DOLNOSLASKIE


def _classify_llm(title, desc):
    """Klasyfikacja specjalizacji modelem Haiku. Zwraca None, gdy brak klucza lub błąd."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    import json as _json
    import urllib.request
    cats = list(ADZUNA_SPEC_KEYWORDS.keys()) + ["Pielęgniarstwo (ogólne)"]
    prompt = ("Przypisz to ogłoszenie o pracę dla pielęgniarki do JEDNEJ kategorii z listy. "
              "Odpowiedz wyłącznie dokładną nazwą kategorii, bez wyjaśnień.\n\nKategorie:\n- "
              + "\n- ".join(cats) + f"\n\nTytuł: {title}\nOpis: {desc[:600]}")
    body = _json.dumps({
        "model": "claude-haiku-4-5-20251001", "max_tokens": 30,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body,
        headers={"content-type": "application/json", "x-api-key": key,
                 "anthropic-version": "2023-06-01"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = _json.loads(r.read().decode("utf-8"))
        txt = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()
        for c in cats:
            if c.lower() in txt.lower() or txt.lower() in c.lower():
                return c
    except Exception:
        IMPORT_STATUS["errors"] += 1
    return None


def classify_spec(title, desc):
    """Hybryda: słownik na tytule (darmowy) -> model -> słownik na pełnym tekście -> ogólne."""
    s = _adzuna_classify(title)        # pewne trafienie z tytułu
    if s:
        return s
    s = _classify_llm(title, desc)     # model rozstrzyga niejednoznaczne
    if s:
        return s
    s = _adzuna_classify(title + " " + desc)  # awaryjnie pełny tekst
    return s or "Pielęgniarstwo (ogólne)"


def run_import(max_pages_big=4, max_pages_small=1):
    """Pełny przebieg importu. Uruchamiany w tle, więc nie blokuje żądania."""
    import time
    import json as _json
    import urllib.request
    import urllib.parse

    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        IMPORT_STATUS.update(running=False, errors=IMPORT_STATUS["errors"] + 1,
                             last_run="brak kluczy ADZUNA_APP_ID / ADZUNA_APP_KEY")
        return

    IMPORT_STATUS.update(running=True, added=0, updated=0, errors=0, fetched=0, deactivated=0)
    db = SessionLocal()
    base = "https://api.adzuna.com/v1/api/jobs/pl/search"
    try:
        for q in ADZUNA_QUERIES:
            broad = q in ("pielęgniarka", "pielęgniarz", "położna")
            max_pages = max_pages_big if broad else max_pages_small
            for page in range(1, max_pages + 1):
                params = urllib.parse.urlencode({
                    "app_id": app_id, "app_key": app_key,
                    "results_per_page": 50, "max_days_old": 30, "what": q,
                    "where": "Dolnośląskie",
                })
                url = f"{base}/{page}?{params}"
                data = None
                for attempt in range(3):  # ponawianie przy 503/limicie
                    try:
                        with urllib.request.urlopen(url, timeout=25) as r:
                            data = _json.loads(r.read().decode("utf-8"))
                        break
                    except Exception:
                        IMPORT_STATUS["errors"] += 1
                        time.sleep(2 + attempt * 2)
                if not data:
                    break
                results = data.get("results", [])
                if not results:
                    break
                for ad in results:
                    if not _in_region(ad):
                        continue  # tylko Dolny Śląsk
                    _upsert_offer(db, ad)
                    IMPORT_STATUS["fetched"] += 1
                db.commit()
                time.sleep(0.8)
        # dezaktywacja ofert niewidzianych od 30 dni
        cutoff = datetime.utcnow() - timedelta(days=30)
        stale = db.query(Offer).filter(
            Offer.source == "adzuna", Offer.last_seen_at < cutoff, Offer.active == True
        ).all()
        for o in stale:
            o.active = False
        IMPORT_STATUS["deactivated"] = len(stale)
        db.commit()
    except Exception as e:
        IMPORT_STATUS["errors"] += 1
        IMPORT_STATUS["last_run"] = f"przerwane: {e}"
    finally:
        db.close()
        IMPORT_STATUS["running"] = False
        IMPORT_STATUS["last_run"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")


def _upsert_offer(db, ad):
    ext = str(ad.get("id") or "")
    if not ext:
        return
    title = ad.get("title", "") or ""
    desc = ad.get("description", "") or ""
    salary_min = ad.get("salary_min")
    predicted = str(ad.get("salary_is_predicted")) == "1"
    now = datetime.utcnow()

    base_fields = dict(
        place=_adzuna_place(ad), city=_adzuna_city(ad), min_years=0,
        forma=_adzuna_forma(ad), tryb=_adzuna_tryb(desc + " " + title),
        salary=int(salary_min) if salary_min else 0,
        salary_predicted=predicted, note=desc[:300],
        url=ad.get("redirect_url", "") or "", source="adzuna",
        external_id=ext, title=title, active=True, last_seen_at=now,
    )

    existing = db.query(Offer).filter(
        Offer.source == "adzuna", Offer.external_id == ext
    ).first()
    if existing:
        # aktualizacja — zachowujemy raz ustaloną specjalizację (bez ponownej klasyfikacji = bez kosztu)
        for k, v in base_fields.items():
            setattr(existing, k, v)
        IMPORT_STATUS["updated"] += 1
        return

    # deduplikacja: ta sama oferta wystawiona na kilka lokalizacji ma identyczny tytuł
    if title:
        db.flush()  # uwidocznij niezapisane jeszcze oferty z tej samej partii
        dup = db.query(Offer).filter(
            Offer.source == "adzuna", Offer.title == title
        ).first()
        if dup:
            dup.last_seen_at = now  # to ten sam job — odświeżamy, nie dublujemy
            return

    # nowa oferta — tu (i tylko tu) wołamy klasyfikację, więc model płaci tylko za nowe
    spec = classify_spec(title, desc)
    db.add(Offer(created_at=now, spec=spec, **base_fields))
    IMPORT_STATUS["added"] += 1


@app.get("/internal/reset-offers")
def reset_offers(token: str = "", db: Session = Depends(get_db)):
    secret = os.environ.get("SYNC_TOKEN")
    if not secret or token != secret:
        raise HTTPException(403, "Zły lub brakujący token")
    n = db.query(Offer).delete()
    db.commit()
    return {"usunieto_wszystkie_oferty": n, "info": "uruchom teraz /internal/sync, by zaimportować Dolny Śląsk"}


@app.get("/internal/sync")
def internal_sync(token: str = "", background: BackgroundTasks = None):
    secret = os.environ.get("SYNC_TOKEN")
    if not secret:
        raise HTTPException(500, "Ustaw zmienną SYNC_TOKEN na Render, potem wywołaj /internal/sync?token=...")
    if token != secret:
        raise HTTPException(403, "Zły token")
    if IMPORT_STATUS["running"]:
        return {"status": "import już trwa", **IMPORT_STATUS}
    background.add_task(run_import)
    return {"status": "import uruchomiony w tle — sprawdź /internal/sync-status za ~minutę"}


@app.get("/internal/cleanup-seed")
def cleanup_seed(token: str = "", db: Session = Depends(get_db)):
    secret = os.environ.get("SYNC_TOKEN")
    if not secret or token != secret:
        raise HTTPException(403, "Zły lub brakujący token")
    seedy = db.query(Offer).filter(Offer.source != "adzuna").all()
    n = len(seedy)
    for o in seedy:
        db.delete(o)
    db.commit()
    pozostalo = db.query(Offer).filter(Offer.active == True).count()
    return {"usunieto_ofert_seedowych": n, "pozostalo_ofert": pozostalo}


@app.get("/internal/sync-status")
def internal_sync_status(db: Session = Depends(get_db)):
    total = db.query(Offer).filter(Offer.active == True).count()
    adzuna = db.query(Offer).filter(Offer.source == "adzuna", Offer.active == True).count()
    return {"aktywne_oferty": total, "z_adzuny": adzuna, **IMPORT_STATUS}


# --------------------------------------------------------------------------
# DIAGNOSTYKA ADZUNY (jednorazowy test jakości danych — uruchamiany z przeglądarki)
# Wymaga zmiennych środowiskowych ADZUNA_APP_ID i ADZUNA_APP_KEY na Render.
# Wejdź na: https://twojaaplikacja.onrender.com/internal/adzuna-test
# --------------------------------------------------------------------------
ADZUNA_QUERIES = [
    "pielęgniarka", "pielęgniarz",
    "pielęgniarka anestezjologiczna", "pielęgniarka intensywnej opieki",
    "pielęgniarka operacyjna", "pielęgniarka chirurgiczna",
    "pielęgniarka internistyczna", "pielęgniarka kardiologiczna",
    "pielęgniarka onkologiczna", "pielęgniarka pediatryczna",
    "pielęgniarka neonatologiczna", "pielęgniarka geriatryczna",
    "pielęgniarka psychiatryczna", "pielęgniarka ratunkowa",
    "pielęgniarka ratownictwo", "pielęgniarka dializacyjna",
    "pielęgniarka opieki paliatywnej", "pielęgniarka opieki długoterminowej",
    "pielęgniarka POZ", "pielęgniarka środowiskowo-rodzinna",
    "pielęgniarka rodzinna", "położna",
]

ADZUNA_SPEC_KEYWORDS = {
    "Anestezjologiczne i intensywna terapia": ["anestezjolog", "intensywn", "oit", "oiom", "respirator"],
    "Ratunkowe / SOR": ["ratunkow", "sor", "izba przyjęć", "ratownict"],
    "Chirurgiczne / blok operacyjny": ["operacyjn", "blok", "instrumentariusz", "chirurg"],
    "Internistyczne / zachowawcze": ["internistyczn", "interny", "zachowawcz"],
    "Kardiologiczne": ["kardiolog", "ekg"],
    "Onkologiczne": ["onkolog", "chemioterap"],
    "Dializoterapia / nefrologiczne": ["dializ", "nefrolog"],
    "POZ / środowiskowo-rodzinne": ["poz", "środowiskow", "rodzinn", "podstawowej opieki"],
    "Pediatryczne / neonatologiczne": ["pediatr", "neonatolog", "dziecięc", "noworodk"],
    "Geriatryczne / opieka długoterminowa": ["geriatr", "długoterminow", "zol", "opiekuńcz", "paliatywn"],
}


def _adzuna_classify(text):
    t = (text or "").lower()
    for spec, kws in ADZUNA_SPEC_KEYWORDS.items():
        if any(k in t for k in kws):
            return spec
    return None


@app.get("/internal/adzuna-test")
def adzuna_test():
    import time
    import json as _json
    import urllib.request
    import urllib.parse
    from fastapi.responses import HTMLResponse

    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        return HTMLResponse(
            "<h2>Brak kluczy Adzuny</h2><p>Dodaj na Render zmienne środowiskowe "
            "<b>ADZUNA_APP_ID</b> i <b>ADZUNA_APP_KEY</b>, potem odśwież tę stronę.</p>")

    base = "https://api.adzuna.com/v1/api/jobs/pl/search/1"
    seen, counts, errors = {}, {}, 0
    for q in ADZUNA_QUERIES:
        params = urllib.parse.urlencode({
            "app_id": app_id, "app_key": app_key,
            "results_per_page": 50, "max_days_old": 30, "what": q,
        })
        try:
            with urllib.request.urlopen(f"{base}?{params}", timeout=25) as r:
                data = _json.loads(r.read().decode("utf-8"))
            counts[q] = data.get("count", 0)
            for ad in data.get("results", []):
                seen[ad.get("id")] = ad
        except Exception as e:
            errors += 1
            counts[q] = f"błąd: {e}"
        time.sleep(0.5)

    ads = list(seen.values())
    n = len(ads)
    if n == 0:
        return HTMLResponse(f"<h2>Brak ofert w próbce</h2><p>Błędów: {errors}. "
                            "Sprawdź klucze lub limit konta Adzuny.</p>")

    real_sal = sum(1 for a in ads if a.get("salary_min") and str(a.get("salary_is_predicted")) == "0")
    pred_sal = sum(1 for a in ads if a.get("salary_min") and str(a.get("salary_is_predicted")) == "1")
    no_sal = n - real_sal - pred_sal
    contract = sum(1 for a in ads if a.get("contract_type") or a.get("contract_time"))
    classified = sum(1 for a in ads if _adzuna_classify(a.get("title", "") + " " + a.get("description", "")))

    def pct(x):
        return f"{x} ({round(100 * x / n)}%)"

    rows = ""
    for q in ADZUNA_QUERIES:
        rows += f"<tr><td>{q}</td><td style='text-align:right'>{counts.get(q, '-')}</td></tr>"

    samples = ""
    for a in ads[:12]:
        spec = _adzuna_classify(a.get("title", "") + " " + a.get("description", "")) or "—"
        loc = (a.get("location", {}) or {}).get("display_name", "?")
        title = (a.get("title", "") or "")[:70]
        samples += f"<tr><td>{title}</td><td>{loc}</td><td>{spec}</td></tr>"

    html = f"""
    <html><head><meta charset='utf-8'><title>Adzuna — test</title>
    <style>body{{font-family:sans-serif;max-width:900px;margin:30px auto;padding:0 16px;color:#18302B}}
    h2{{color:#3F7A6B}} table{{border-collapse:collapse;width:100%;margin:10px 0;font-size:14px}}
    td,th{{border:1px solid #DCE3E0;padding:6px 10px;text-align:left}}
    .big{{font-size:15px;line-height:1.7}} b{{color:#DD6B4F}}</style></head><body>
    <h2>Adzuna — jakość danych dla ofert pielęgniarskich w PL</h2>
    <p class='big'>Unikalnych ofert w próbce: <b>{n}</b> &nbsp;|&nbsp; błędów zapytań: {errors}<br>
    Realne wynagrodzenie: <b>{pct(real_sal)}</b><br>
    Wynagrodzenie estymowane przez Adzunę: <b>{pct(pred_sal)}</b><br>
    Bez wynagrodzenia: <b>{pct(no_sal)}</b><br>
    Z typem/formą zatrudnienia: <b>{pct(contract)}</b><br>
    Specjalizacja rozpoznana słownikiem: <b>{pct(classified)}</b></p>
    <h3>Liczba ofert na zapytanie (pełny wolumen w PL, do 30 dni)</h3>
    <table><tr><th>Zapytanie</th><th>Liczba ofert</th></tr>{rows}</table>
    <h3>Przykładowe oferty</h3>
    <table><tr><th>Tytuł</th><th>Lokalizacja</th><th>Specjalizacja (słownik)</th></tr>{samples}</table>
    <p style='color:#6B7F79;font-size:13px'>Skopiuj te liczby i wklej w rozmowie — na ich podstawie ustawimy regułę wynagrodzenia i sposób mapowania specjalizacji.</p>
    </body></html>"""
    return HTMLResponse(html)


# frontend (ten sam serwer — jeden URL, zero CORS)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def index():
    return FileResponse("static/index.html")
