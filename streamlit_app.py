
"""streamlit_app.py (v1.1)
Streamlit app to organize weekly random draws of titular and substitute players
based on an Excel file of guild members.

Changelog v1.1
==============
* **Fix IntegrityError UNIQUE constraint failed: players.pseudo**
  The original `load_players()` tried to bulk-insert the DataFrame via
  `df.to_sql(..., if_exists="append")`; if the same file was loaded twice or if
  the Excel already contained duplicates, the UNIQUE constraint on `pseudo`
  triggered an error before we could deduplicate.  We now:
  1. drop duplicates in the DataFrame itself, and
  2. insert each row with **INSERT OR IGNORE** (SQLite upsert) so rerunning the
     app is safe.

How it works
============
1. Upload/update your Excel list (`guild_players_complete.xlsx`) in the repo
   folder.
2. Deploy the app on *Streamlit Community Cloud* (free) so anyone with the link
   can use it.
3. Every Friday (or any day) click **Generate draw** to create the next
   schedule:
   - First time: it will add the remaining days of the current week (Fri-Sun)
     plus the full next week.
   - After that: it will always create a 7-day schedule (Mon-Sun) for the next
     week.
4. The result is stored in a SQLite database so all users see the same
   schedule.
5. No `R1` players are ever selected. A player cannot be titular twice in the
   same schedule. Substitutes are chosen from the remaining pool and can
   become titular in future weeks.

Tables
-------
players(id, pseudo **UNIQUE**, rank)
draws(id, draw_date **UNIQUE**, titular_id, substitute_id, week_id)

Feel free to extend the schema (e.g. add user accounts, audit log, etc.).
"""

from __future__ import annotations

import datetime as dt
import os
import random
import sqlite3
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATA_FILE = Path("guild_players_complete.xlsx")
DB_FILE = Path("draws.db")
WEEKDAYS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_conn() -> sqlite3.Connection:
    """Return a SQLite connection (singleton per session)."""
    return sqlite3.connect(DB_FILE, check_same_thread=False)


def init_db() -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS players(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pseudo TEXT UNIQUE,
            rank  TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS draws(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            draw_date TEXT UNIQUE,
            titular_id INTEGER,
            substitute_id INTEGER,
            week_id TEXT,
            FOREIGN KEY(titular_id) REFERENCES players(id),
            FOREIGN KEY(substitute_id) REFERENCES players(id)
        )
        """
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Player loading (fixes UNIQUE constraint error)
# ---------------------------------------------------------------------------

def load_players() -> None:
    """Load / update the `players` table from the Excel sheet.

    * Skips rank `R1`.
    * Drops duplicate pseudos inside the sheet.
    * Upserts with INSERT OR IGNORE so rerunning the app never crashes.
    """
    if not DATA_FILE.exists():
        st.error(f"Fichier introuvable : {DATA_FILE}. Téléverse-le d'abord.")
        st.stop()

    # Read Excel & basic cleanup
    df = (
        pd.read_excel(DATA_FILE)
        .loc[lambda d: d["Rang"] != "R1", ["Pseudo", "Rang"]]
        .rename(columns={"Pseudo": "pseudo", "Rang": "rank"})
        .drop_duplicates(subset="pseudo")
    )

    # Upsert (INSERT OR IGNORE) to avoid UNIQUE constraint errors
    conn = get_conn()
    cur = conn.cursor()
    cur.executemany(
        "INSERT OR IGNORE INTO players(pseudo, rank) VALUES (?, ?)",
        df.itertuples(index=False, name=None),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_player_pool() -> List[Tuple[int, str]]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, pseudo FROM players ORDER BY RANDOM()")
    return cur.fetchall()


def save_draw(schedule: Dict[dt.date, Tuple[int, int]]) -> None:
    """Persist schedule {date: (titular_id, substitute_id)} into DB."""
    conn = get_conn()
    cur = conn.cursor()
    for day, (tid, sid) in schedule.items():
        cur.execute(
            "INSERT OR REPLACE INTO draws(draw_date, titular_id, substitute_id, week_id)\n             VALUES (?, ?, ?, ?)",
            (day.isoformat(), tid, sid, week_identifier(day)),
        )
    conn.commit()


def fetch_schedule(week_id: str) -> pd.DataFrame:
    conn = get_conn()
    query = (
        "SELECT draw_date,\n                p1.pseudo  AS Titulaire,\n                p2.pseudo  AS Suppléant\n         FROM draws d\n         JOIN players p1 ON p1.id = d.titular_id\n         JOIN players p2 ON p2.id = d.substitute_id\n         WHERE d.week_id = ?\n         ORDER BY draw_date"
    )
    df = pd.read_sql_query(query, conn, params=(week_id,))
    if not df.empty:
        df["draw_date"] = pd.to_datetime(df["draw_date"]).dt.strftime("%A %d/%m/%Y")
        df = df.set_index("draw_date")
    return df


# ---------------------------------------------------------------------------
# Draw logic
# ---------------------------------------------------------------------------

def week_identifier(date: dt.date) -> str:
    year, week, _ = date.isocalendar()
    return f"{year}-W{week:02d}"


def generate_dates(initial: bool = False) -> List[dt.date]:
    """Return list of dates to draw.

    * initial=True  -> current Friday–Sunday + full next week (7 days)
    * initial=False -> upcoming Monday–Sunday
    """
    today = dt.date.today()

    if initial:
        # Find the Friday of the current ISO week (weekday(): 0=Mon … 4=Fri)
        friday = today + dt.timedelta((4 - today.weekday()) % 7)
        extra_days = [friday + dt.timedelta(i) for i in range(0, 3)]  # Fri, Sat, Sun
        next_monday = friday + dt.timedelta(days=(7 - friday.weekday()))
        next_week = [next_monday + dt.timedelta(i) for i in range(7)]
        return extra_days + next_week

    else:
        next_monday = today + dt.timedelta(days=((7 - today.weekday()) % 7 or 7))
        return [next_monday + dt.timedelta(i) for i in range(7)]


def draw_players(dates: List[dt.date]) -> Dict[dt.date, Tuple[int, int]]:
    """Return mapping {date: (titular_id, substitute_id)} following the rules."""

    pool_ids = [pid for pid, _ in get_player_pool()]
    random.shuffle(pool_ids)
    used_titulars: set[int] = set()
    schedule: Dict[dt.date, Tuple[int, int]] = {}

    pool_iter = iter(pool_ids)
    for day in dates:
        # Titular: first id not yet used
        tid = next(pid for pid in pool_iter if pid not in used_titulars)
        used_titulars.add(tid)
        # Substitute: next different id (can be re-used later as titular)
        sid = next(pid for pid in pool_iter if pid != tid)
        schedule[day] = (tid, sid)
    return schedule


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Tirage au sort guild", page_icon="🎲", layout="centered")

st.title("🎲 Tirage au sort des joueurs")

init_db()
load_players()

st.sidebar.header("Paramètres du tirage")
	
# Remember if at least one draw has been generated this session
if "generated" not in st.session_state:
    st.session_state.generated = False

initial_draw = st.sidebar.checkbox(
    "Premier tirage (ajout Vendredi-Dimanche)", value=not st.session_state.generated
)

if st.sidebar.button("Générer le tirage", type="primary"):
    dates = generate_dates(initial_draw)
    schedule = draw_players(dates)
    save_draw(schedule)
    st.session_state.generated = True
    st.success("✅ Tirage enregistré !")

# Display current week schedule (ISO week of today)
week_id = week_identifier(dt.date.today())
df_sched = fetch_schedule(week_id)

if df_sched.empty:
    st.info("Aucun tirage pour la semaine en cours. Utilise le bouton à gauche.")
else:
    st.subheader(f"Planning semaine {week_id}")
    st.table(df_sched)
