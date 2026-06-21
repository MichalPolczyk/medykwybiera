# Dyżur — backend MVP

Dwustronna platforma dopasowania pielęgniarek i pracodawców.
FastAPI + baza danych + frontend serwowany z tego samego serwera (jeden URL).

## Struktura

```
dyzur/
├── main.py            # backend: modele, silnik dopasowania, API, serwowanie frontu
├── static/
│   └── index.html     # frontend (czysty HTML/JS, bez build-stepa)
├── requirements.txt   # zależności Pythona
└── README.md
```

## Uruchomienie lokalne

W terminalu, w folderze `dyzur`:

```
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Otwórz http://127.0.0.1:8000

Dane zapiszą się lokalnie w pliku `dyzur.db` (SQLite). Dokumentacja API jest pod `/docs`.

---

## Wdrożenie na Render (dostępne z internetu)

Render to platforma, która bierze kod z GitHuba i sama go uruchamia.

### 1. Wrzuć kod na GitHub
Załóż konto na github.com, utwórz nowe (puste) repozytorium, wgraj do niego te pliki.
Najprościej przez stronę GitHuba: „Add file" → „Upload files".

### 2. Utwórz bazę PostgreSQL na Render
- Konto na render.com (bez karty kredytowej).
- „New" → „Postgres" → plan Free → „Create Database".
- Po chwili skopiuj **Internal Database URL** (zaczyna się od `postgresql://`).

### 3. Utwórz Web Service
- „New" → „Web Service" → podłącz repozytorium z GitHuba.
- Render wykryje Pythona automatycznie. Ustaw:
  - **Build Command:** `pip install -r requirements.txt`
  - **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
  - Plan: **Free**
- W sekcji **Environment** dodaj zmienną:
  - klucz: `DATABASE_URL`
  - wartość: wklejony Internal Database URL z kroku 2
- „Create Web Service".

Po kilku minutach dostaniesz publiczny adres `https://twojanazwa.onrender.com`.
To jest link, który wysyłasz testerowi.

---

## Trzy ograniczenia darmowego planu (ważne)

1. **Usypianie.** Darmowy serwer zasypia po 15 minutach bezczynności. Pierwsze wejście po
   przerwie ładuje się 30–60 sekund (tzw. zimny start), potem działa normalnie. Uprzedź
   testera, że pierwsze kliknięcie może chwilę potrwać.

2. **Baza wygasa.** Darmowy PostgreSQL na Render jest kasowany 30 dni po utworzeniu.
   Na okno testów w zupełności wystarczy. Gdy projekt przejdzie walidację, przejście na
   plan płatny (od ok. 7 USD/mies.) usuwa wszystkie trzy ograniczenia.

3. **Nie używaj SQLite w chmurze.** Darmowy serwer ma „ulotny" dysk — plik SQLite
   znikałby przy każdym restarcie. Dlatego w chmurze obowiązkowo PostgreSQL przez
   `DATABASE_URL` (krok 2). Lokalnie SQLite jest w porządku.

---

## Co dalej (kolejne kroki, gdy pomysł się obroni)

- **Weryfikacja:** numer PWZ pielęgniarki (rejestr NIPiP) i numer RPWDL pracodawcy
  (rejestr Ministerstwa Zdrowia) — przeciw fałszywym ogłoszeniom.
- **Geocoding:** zamiana nazwy miasta na współrzędne, żeby każda miejscowość (Sieradz,
  Wieluń…) miała realną odległość zamiast przyjętych 150 km.
- **Logowanie i wiadomości** między stronami.
- **Uzasadnienie AI** dopasowania — endpoint w backendzie wołający model językowy
  z Twoim kluczem API (logika z prototypu w przeglądarce).
- **RODO:** polityka prywatności, zgody, minimalizacja danych.
