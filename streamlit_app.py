
"""streamlit_app.py (v2.1)
Streamlit app – weekly random draws of titular / substitute guild players.

Changelog v2.1
--------------
✅ **Plus de tirages rétroactifs ni de doublons**
   * Dans la barre latérale, on ne peut choisir qu’une **semaine future non encore tirée**.
   * L’option « Écraser » disparaît ; si une semaine existe déjà, elle n’apparaît tout simplement pas dans la liste.

📋 **Historique complet visible**
   * Un volet « Historique des tirages » affiche toutes les semaines déjà générées (expander par semaine).

Les corrections sur les doublons de pseudos restent actives.
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
WEEKS_AHEAD_SHOWN = 52  # combien de semaines futures proposer

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
# Player loading (deduplicate & upsert)
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
# Helper utils
# ---------------------------------------------------------------------------

def week_id_for_date(d: dt.date) -> str:
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def monday_of_week(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())

# ---------------------------------------------------------------------------
# Week lists
# ---------------------------------------------------------------------------

def existing_week_ids() -> List[str]:
    conn = get_conn()
    rows = conn.execute("SELECT DISTINCT week_id FROM draws ORDER BY week_id").fetchall()
    return [r[0] for r in rows]


def upcoming_week_mondays(n_weeks: int = WEEKS_AHEAD_SHOWN) -> List[dt.date]:
    today = dt.date.today()
    next_monday = monday_of_week(today + dt.timedelta(days=7))
    return [next_monday + dt.timedelta(days=7 * i) for i in range(n_weeks)]

# ---------------------------------------------------------------------------
# Draw engine
# ---------------------------------------------------------------------------

def get_player_pool_ids() -> List[int]:
    conn = get_conn()
    return [row[0] for row in conn.execute("SELECT id FROM players ORDER BY RANDOM()")]


def generate_week_dates(week_monday: dt.date) -> List[dt.date]:
    return [week_monday + dt.timedelta(i) for i in range(7)]


def draw_players(dates: List[dt.date]) -> Dict[dt.date, Tuple[int, int]]:
    pool = get_player_pool_ids()
    random.shuffle(pool)
    used_titulars: set[int] = set()
    schedule: Dict[dt.date, Tuple[int, int]] = {}
    pool_iter = iter(pool)

    for day in dates:
        tid = next(pid for pid in pool_iter if pid not in used_titulars)
        used_titulars.add(tid)
        sid = next(pid for pid in pool_iter if pid != tid)
        schedule[day] = (tid, sid)
    return schedule


def save_draw(schedule: Dict[dt.date, Tuple[int, int]]) -> None:
    conn = get_conn()
    conn.executemany(
        """
        INSERT OR REPLACE INTO draws(draw_date, titular_id, substitute_id, week_id)
        VALUES (?, ?, ?, ?)
        """,
        [
            (day.isoformat(), tid, sid, week_id_for_date(day))
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
# Streamlit UI
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Tirage au sort guild", page_icon="🎲", layout="centered")

st.title("🎲 Tirage au sort des joueurs")

init_db()
load_players()

# ---- Sidebar: new week generation ----------------------------------------

st.sidebar.header("Créer une nouvelle semaine")

# Build selectable list: future weeks not yet drawn
existing_ids = set(existing_week_ids())
week_options = [monday for monday in upcoming_week_mondays() if week_id_for_date(monday) not in existing_ids]

if not week_options:
    st.sidebar.success("Toutes les semaines des 12 prochains mois ont déjà été tirées.")
else:
    monday_selected = st.sidebar.selectbox(
        "Choisis la semaine (lundi) :",
        week_options,
        format_func=lambda d: f"Semaine {week_id_for_date(d)} (débute le {d.strftime('%d/%m/%Y')})",
    )

    if st.sidebar.button("Générer cette semaine"):
        dates = generate_week_dates(monday_selected)
        schedule = draw_players(dates)
        save_draw(schedule)
        st.sidebar.success(f"✅ Semaine {week_id_for_date(monday_selected)} créée !")
        st.experimental_rerun()  # refresh to update lists / tables

# ---- Main page: overview --------------------------------------------------

# Current ISO week schedule (if exists)
current_week_id = week_id_for_date(dt.date.today())
st.subheader(f"Planning semaine courante ({current_week_id})")
cur_df = fetch_schedule(current_week_id)
if cur_df.empty:
    st.info("Aucun tirage pour cette semaine.")
else:
    st.table(cur_df)

# Historique
st.subheader("Historique des tirages")
if not existing_ids:
    st.info("Aucun tirage enregistré pour l'instant.")
else:
    for wid in sorted(existing_ids):
        with st.expander(f"Semaine {wid}"):
            hist_df = fetch_schedule(wid)
            st.table(hist_df)
