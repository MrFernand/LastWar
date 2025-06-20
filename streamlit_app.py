
"""streamlit_app.py
Streamlit app to organize weekly random draws of titular and substitute players
based on an Excel file of guild members.

How it works
=============
1. Upload/update your Excel list (`guild_players_complete.xlsx`) in the repo folder.
2. Deploy the app on *Streamlit Community Cloud* (free) so anyone with the link can use it.
3. Every Friday (or any day) click **Generate draw** to create the next schedule:
   - First time: it will add the remaining days of the current week (Fri-Sun) + full next week.
   - After that: it will always create a 7-day schedule (Mon-Sun) for the next week.
4. The result is stored in a SQLite database so all users see the same schedule.
5. No `R1` players are ever selected. A player cannot be titular twice in the
   same schedule. Substitutes are chosen from the remaining pool and can
   become titular in future weeks.

Tables
-------
players(id, pseudo, rank)
draws(id, draw_date, titular_id, substitute_id, week_id)

Feel free to extend the schema (e.g. add user accounts, audit log, etc.).
"""

import datetime as dt
import os
import random
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

# --- Configuration ----------------------------------------------------------

DATA_FILE = Path("guild_players_complete.xlsx")
DB_FILE = Path("draws.db")

# --- Database helpers -------------------------------------------------------


def get_conn() -> sqlite3.Connection:
    """Return a SQLite connection (singleton per session)."""
    return sqlite3.connect(DB_FILE, check_same_thread=False)


def init_db():
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


def load_players():
    """(Re)load players from the Excel sheet into the DB, skipping R1."""
    if not DATA_FILE.exists():
        st.error(f"Cannot find {DATA_FILE}. Upload it to the repo.")
        st.stop()
    df = pd.read_excel(DATA_FILE)
    df = df[df["Rang"] != "R1"][["Pseudo", "Rang"]].rename(
        columns={"Pseudo": "pseudo", "Rang": "rank"}
    )

    conn = get_conn()
    df.to_sql("players", conn, if_exists="append", index=False)
    conn.commit()

    # Remove potential duplicates while keeping the first occurrence
    conn.execute(
        "DELETE FROM players WHERE id NOT IN (SELECT MIN(id) FROM players GROUP BY pseudo)"
    )
    conn.commit()


def get_player_pool():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, pseudo FROM players ORDER BY RANDOM()")
    return cur.fetchall()


def save_draw(schedule):
    """Persist a dict{date:(titular_id, sub_id)} into the draws table."""
    conn = get_conn()
    cur = conn.cursor()
    for day, (tid, sid) in schedule.items():
        cur.execute(
            "INSERT OR REPLACE INTO draws(draw_date,titular_id,substitute_id,week_id) VALUES(?,?,?,?)",
            (day.isoformat(), tid, sid, week_identifier(day)),
        )
    conn.commit()


def fetch_schedule(week_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT draw_date,pseudo_t,pseudo_s FROM (\
            SELECT d.draw_date,\
                   p1.pseudo AS pseudo_t,\
                   p2.pseudo AS pseudo_s\
            FROM draws d\
            JOIN players p1 ON p1.id = d.titular_id\
            JOIN players p2 ON p2.id = d.substitute_id\
            WHERE d.week_id = ?\
            ORDER BY d.draw_date)\
        ",
        (week_id,),
    )
    rows = cur.fetchall()
    return pd.DataFrame(
        rows, columns=["Date", "Titulaire", "Suppléant"]
    ).set_index("Date")


# --- Logic helpers ----------------------------------------------------------


def week_identifier(date: dt.date) -> str:
    week = date.isocalendar()
    return f"{week[0]}-W{week[1]:02d}"


def generate_dates(initial=False):
    """Return list of dates to draw.
    * initial=True  -> today..Sunday (if today<=Thursday, start next Fri) + full next week
    * initial=False -> upcoming Monday..Sunday
    """
    today = dt.date.today()
    if initial:
        # Remaining days of current week starting Friday
        fri = today + dt.timedelta((4 - today.weekday()) % 7)
        current_week_extra = [
            fri + dt.timedelta(i) for i in range(0, 3)  # Fri,Sat,Sun
        ]
        next_monday = fri + dt.timedelta(days=(7 - fri.weekday()))
        next_week = [next_monday + dt.timedelta(i) for i in range(7)]
        return current_week_extra + next_week
    else:
        # Next Monday to Sunday
        next_monday = today + dt.timedelta(days=((7 - today.weekday()) % 7 or 7))
        return [next_monday + dt.timedelta(i) for i in range(7)]


def draw_players(dates):
    """Return dict(date -> (titular_id, substitute_id))"""
    pool = get_player_pool()
    pool_ids = [p[0] for p in pool]
    random.shuffle(pool_ids)

    schedule = {}
    used_titulars = set()
    pool_iter = iter(pool_ids)

    for d in dates:
        # Titular
        tid = next(p for p in pool_iter if p not in used_titulars)
        used_titulars.add(tid)
        # Substitute (can be any remaining different player)
        sid = next(p for p in pool_iter if p != tid)
        schedule[d] = (tid, sid)
    return schedule


# --- UI ---------------------------------------------------------------------

st.set_page_config(page_title="Tirage au sort guild", page_icon="🎲", layout="centered")

st.title("🎲 Tirage au sort joueurs")

init_db()
load_players()

st.sidebar.header("Paramètres du tirage")

if "generated" not in st.session_state:
    st.session_state.generated = False

initial = st.sidebar.checkbox(
    "Premier tirage (ajouter Vendredi-Dimanche)?", value=not st.session_state.generated
)

if st.sidebar.button("Générer le tirage", type="primary"):
    dates = generate_dates(initial)
    schedule = draw_players(dates)
    save_draw(schedule)
    st.session_state.generated = True
    st.success("Tirage enregistré !")

# Show current / next schedule
today = dt.date.today()
current_week = week_identifier(today)
df = fetch_schedule(current_week)

if not df.empty:
    st.subheader(f"Planning semaine {current_week}")
    st.table(df)
else:
    st.info(
        "Aucun tirage trouvé pour la semaine en cours. Générez-en un depuis la barre latérale."
    )
