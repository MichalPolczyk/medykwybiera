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

from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import create_engine, Integer, String, Float
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

    # forma (15)
    if nurse.forma == offer.forma or "Dowolna" in (nurse.forma, offer.forma):
        forma = 15
    elif all(f in ("Umowa o pracę", "Umowa zlecenie") for f in (nurse.forma, offer.forma)):
        forma = 8
    else:
        forma = 4

    # tryb (10)
    tryb = 10 if (nurse.tryb == offer.tryb or "Dowolny" in (nurse.tryb, offer.tryb)) else 3

    # doświadczenie (10)
    if offer.min_years <= 0 or nurse.years >= offer.min_years:
        exp = 10
    else:
        exp = max(3, round((nurse.years / offer.min_years) * 10))

    # wynagrodzenie (25)
    if not nurse.expected:
        sal = 25
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
            "salary": o.salary, "note": o.note}


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
        if db.query(Offer).count() == 0:
            db.add_all(Offer(**o) for o in SEED_OFFERS)
        db.commit()
    finally:
        db.close()


# --------------------------------------------------------------------------
# APLIKACJA
# --------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    seed_if_empty()
    yield


app = FastAPI(title="Dyżur API", lifespan=lifespan)


@app.get("/api/nurses")
def list_nurses(db: Session = Depends(get_db)):
    return [nurse_dict(n) for n in db.query(Nurse).order_by(Nurse.id.desc())]


@app.get("/api/offers")
def list_offers(db: Session = Depends(get_db)):
    return [offer_dict(o) for o in db.query(Offer).order_by(Offer.id.desc())]


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
        for o in db.query(Offer):
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


# frontend (ten sam serwer — jeden URL, zero CORS)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def index():
    return FileResponse("static/index.html")
