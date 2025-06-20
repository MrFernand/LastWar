
"""streamlit_app.py (v1.2)
Streamlit app to organise weekly random draws of titular and substitute players
based on an Excel file of guild members.

Changelog v1.2
==============
* **Initial draw now excludes Friday** → only **Saturday + Sunday** of the current
  week are added before the full next week (7 days).  Requested by user.
* Docstrings & comments updated accordingly.

Previous fixes (v1.1) remain:
* Duplicate `pseudo` handling via INSERT OR IGNORE (no more UNIQUE constraint).

"""
from __future__ import annotations

import datetime as dt
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

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_conn() -> sqlite3.Connection:
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
# Player loader (dedup / upsert)
# ---------------------------------------------------------------------------

def load_players() -> None:
    if not DATA_FILE.exists():
        st.error(f"Fichier introuvable : {DATA_FILE}")
        st.stop()

    df = (
        pd.read_excel(DATA_FILE)
        .loc[lambda d: d["Rang"] != "R1", ["Pseudo", "Rang"]]
        .rename(columns={"Pseudo": "pseudo", "Rang": "rank"})
        .drop_duplicates(subset="pseudo")
    )

    conn = get_conn()
    conn.executemany(
        "INSERT OR IGNORE INTO players(pseudo, rank) VALUES (?, ?)",
        df.itertuples(index=False, name=None),
    )
    conn.commit()

# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_player_pool() -> List[Tuple[int, str]]:
    conn = get_conn()
    return conn.execute("SELECT id, pseudo FROM players ORDER BY RANDOM()").fetchall()


def save_draw(schedule: Dict[dt.date, Tuple[int, int]]) -> None:
    conn = get_conn()
    conn.executemany(
        "INSERT OR REPLACE INTO draws(draw_date, titular_id, substitute_id, week_id)\n         VALUES (?, ?, ?, ?)",
        [
            (day.isoformat(), tid, sid, week_identifier(day))
            for day, (tid, sid) in schedule.items()
        ],
    )
    conn.commit()


def fetch_schedule(week_id: str) -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query(
        """
        SELECT draw_date, p1.pseudo AS Titulaire, p2.pseudo AS Suppléant
        FROM draws d
        JOIN players p1 ON p1.id = d.titular_id
        JOIN players p2 ON p2.id = d.substitute_id
        WHERE d.week_id = ?
        ORDER BY draw_date
        """,
        conn,
        params=(week_id,),
    )
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
    """Return list of dates that need a draw.

    * **Initial draw** (`initial=True`) → **Saturday & Sunday** of the current
      ISO week, **plus full next week (Mon–Sun)**.
    * Subsequent draws (`initial=False`) → **upcoming Monday–Sunday** only.
    """
    today = dt.date.today()

    if initial:
        # Saturday of current ISO week (weekday 5)
        saturday = today + dt.timedelta((5 - today.weekday()) % 7)
        extra_days = [saturday, saturday + dt.timedelta(1)]  # Sat & Sun

        # Next Monday (weekday 0) relative to that Saturday
        next_monday = saturday + dt.timedelta(days=2)  # always Monday
        next_week = [next_monday + dt.timedelta(i) for i in range(7)]
        return extra_days + next_week

    # Not initial → next Monday to Sunday
    next_monday = today + dt.timedelta(days=((7 - today.weekday()) % 7 or 7))
    return [next_monday + dt.timedelta(i) for i in range(7)]


def draw_players(dates: List[dt.date]) -> Dict[dt.date, Tuple[int, int]]:
    pool_ids = [pid for pid, _ in get_player_pool()]
    random.shuffle(pool_ids)
    used_titulars: set[int] = set()
    schedule: Dict[dt.date, Tuple[int, int]] = {}
    pool_iter = iter(pool_ids)

    for date in dates:
        # Titular: first id not already used this draw
        tid = next(pid for pid in pool_iter if pid not in used_titulars)
        used_titulars.add(tid)
        # Substitute: next different id
        sid = next(pid for pid in pool_iter if pid != tid)
        schedule[date] = (tid, sid)
    return schedule

# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Tirage au sort guild", page_icon="🎲", layout="centered")

st.title("🎲 Tirage au sort des joueurs")

init_db()
load_players()

st.sidebar.header("Paramètres du tirage")

if "generated" not in st.session_state:
    st.session_state.generated = False

initial_draw = st.sidebar.checkbox(
    "Premier tirage (ajout Samedi-Dimanche)", value=not st.session_state.generated
)

if st.sidebar.button("Générer le tirage", type="primary"):
    dates = generate_dates(initial_draw)
    schedule = draw_players(dates)
    save_draw(schedule)
    st.session_state.generated = True
    st.success("✅ Tirage enregistré !")

# Display current week schedule
week_id = week_identifier(dt.date.today())
df_sched = fetch_schedule(week_id)

if df_sched.empty:
    st.info("Aucun tirage pour la semaine en cours. Utilise le bouton à gauche.")
else:
    st.subheader(f"Planning semaine {week_id}")
    st.table(df_sched)
