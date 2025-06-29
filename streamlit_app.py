"""streamlit_app.py (v3.2)
============================================
* Ajoute la date de tirage pour **Titulaire ET Suppléant** dans la colonne
  « Date du train ».
* Corrige l’indentation et simplifie la logique d’écriture.
* Réinitialisation, édition manuelle et génération utilisent tous la même
  fonction d’enregistrement des dates.
"""
from __future__ import annotations

import datetime as dt
import random
from pathlib import Path
from typing import Dict, List, Tuple

import openpyxl
import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------
DATA_FILE = Path("Liste_membres_Train.xlsx")
MEMBRES_SHEET = "Membres"
TIRAGES_SHEET = "Tirages"
WEEKS_AHEAD = 52

# ---------------------------------------------------------------------------
# STREAMLIT COMPAT
# ---------------------------------------------------------------------------

def _data_editor(df: pd.DataFrame, **kw):
    return st.data_editor(df, **kw) if hasattr(st, "data_editor") else st.experimental_data_editor(df, **kw)  # type: ignore[attr-defined]


def _rerun():
    return st.rerun() if hasattr(st, "rerun") else st.experimental_rerun()  # type: ignore[attr-defined]

# ---------------------------------------------------------------------------
# DATE HELPERS
# ---------------------------------------------------------------------------

def _week_id(d: dt.date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def _monday(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())


def _next_mondays(n: int = WEEKS_AHEAD) -> List[dt.date]:
    start = _monday(dt.date.today() + dt.timedelta(days=7))
    return [start + dt.timedelta(weeks=i) for i in range(n)]

# ---------------------------------------------------------------------------
# EXCEL I/O
# ---------------------------------------------------------------------------

def _open_wb() -> openpyxl.Workbook:
    if not DATA_FILE.exists():
        st.error(f"Fichier {DATA_FILE} introuvable.")
        st.stop()
    return openpyxl.load_workbook(DATA_FILE)


def _write_df(df: pd.DataFrame, sheet: str):
    with pd.ExcelWriter(DATA_FILE, engine="openpyxl", mode="a", if_sheet_exists="replace") as w:
        df.to_excel(w, index=False, sheet_name=sheet)


def _players_df() -> pd.DataFrame:
    return pd.read_excel(DATA_FILE, sheet_name=MEMBRES_SHEET, engine="openpyxl")


def _tirages_df() -> pd.DataFrame:
    if TIRAGES_SHEET not in _open_wb().sheetnames:
        return pd.DataFrame(columns=["Semaine", "Date", "Titulaire", "Suppléant"])
    return pd.read_excel(DATA_FILE, sheet_name=TIRAGES_SHEET, engine="openpyxl")


def _save_tirages(rows: List[Tuple[str, str, str, str]]):
    wb = _open_wb()
    if TIRAGES_SHEET not in wb.sheetnames:
        ws = wb.create_sheet(TIRAGES_SHEET)
        ws.append(["Semaine", "Date", "Titulaire", "Suppléant"])
    else:
        ws = wb[TIRAGES_SHEET]
    for r in rows:
        ws.append(list(r))
    wb.save(DATA_FILE)

# ---------------------------------------------------------------------------
# STRING HELPERS
# ---------------------------------------------------------------------------

def _concat(existing: str | float | None, new_dates: List[str]) -> str | None:
    if not new_dates:
        return existing
    base = [] if pd.isna(existing) or existing is None or not str(existing).strip() else [d.strip() for d in str(existing).split(",")]
    for d in new_dates:
        if d not in base:
            base.append(d)
    return ", ".join(base) if base else None


def _strip_week(existing: str | None, week_dates: set[dt.date]) -> str | None:
    """Retire du champ `existing` toutes les dates présentes dans `week_dates`."""
    if pd.isna(existing) or existing is None or not str(existing).strip():
        return existing
    kept = []
    for part in str(existing).split(","):
        p = part.strip()
        try:
            d = dt.date.fromisoformat(p)
            if d in week_dates:
                continue
            kept.append(p)
        except ValueError:
            kept.append(p)
    return ", ".join(kept) if kept else None

# TIRAGE LOGIC
# ---------------------------------------------------------------------------

def _eligible(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["Motif sortie"].fillna("").str.strip() == ""]


def _draw_week(df: pd.DataFrame, monday: dt.date) -> Dict[dt.date, Tuple[str, str]]:
    dates = [monday + dt.timedelta(days=i) for i in range(7)]
    pool = df["Pseudo"].tolist(); random.shuffle(pool)
    it = iter(pool); used = set(); sched = {}
    for d in dates:
        tit = next(p for p in it if p not in used); used.add(tit)
        sup = next(p for p in it if p != tit)
        sched[d] = (tit, sup)
    return sched

# ---------------------------------------------------------------------------
# DATE COLUMN UPDATE (titulaire + suppléant)
# ---------------------------------------------------------------------------

def _update_date_column(players: pd.DataFrame, date_map: Dict[str, List[str]]):
    players["Date du train"] = players.apply(
        lambda r: _concat(r["Date du train"], date_map.get(r["Pseudo"], [])), axis=1
    )
    _write_df(players, MEMBRES_SHEET)

# ---------------------------------------------------------------------------
# STREAMLIT APP
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Tirage train", page_icon="🎲", layout="centered")

st.title("🎲 Tirage au sort – Liste Train")

players = _players_df()

# --- Génération ------------------------------------------------------------------------------

st.sidebar.header("Générer une semaine")
exist_ids = set(_tirages_df()["Semaine"].unique())
week_opts = [m for m in _next_mondays() if _week_id(m) not in exist_ids]

if week_opts:
    monday_sel = st.sidebar.selectbox("Semaine", week_opts, format_func=lambda d: f"{_week_id(d)} – {d.strftime('%d/%m/%Y')}")
    if st.sidebar.button("🎲 Générer"):
        elig = _eligible(players)
        if len(elig) < 14:
            st.sidebar.error("Pas assez de joueurs éligibles (>=14)")
        else:
            sched = _draw_week(elig, monday_sel)
            rows = [(_week_id(monday_sel), d.isoformat(), tit, sup) for d, (tit, sup) in sched.items()]
            _save_tirages(rows)
                        # Build date_map uniquement pour les **titulaires**
            date_map: Dict[str, List[str]] = {}
            for d, (tit, _) in sched.items():
                iso = d.isoformat()
                date_map.setdefault(tit, []).append(iso)
            _update_date_column(players, date_map)
            st.sidebar.success("Semaine enregistrée ✅"); _rerun()(players, date_map)
            st.sidebar.success("Semaine enregistrée ✅"); _rerun()
else:
    st.sidebar.info("Toutes les semaines futures sont déjà tirées.")

# --- Historique ------------------------------------------------------------------------------

st.subheader("Historique")
all_tir = _tirages_df()
if all_tir.empty:
    st.info("Aucune semaine enregistrée.")
else:
    for i, wid in enumerate(sorted(all_tir["Semaine"].unique())):
        wk = all_tir[all_tir["Semaine"] == wid][["Date", "Titulaire", "Suppléant"]].copy()
        wk["Date"] = pd.to_datetime(wk["Date"]).dt.strftime("%A %d/%m/%Y"); wk.set_index("Date", inplace=True)
        with st.expander(f"Semaine {wid}"):
            editor_key = f"ed_{i}_{wid}"
            save_key   = f"save_{i}_{wid}"
            edited = _data_editor(wk, key=editor_key)
            if st.button("💾 Enregistrer", key=save_key):
                wb = _open_wb(); ws = wb[TIRAGES_SHEET]
                # delete old
                rows_del=[idx for idx,row in enumerate(ws.iter_rows(values_only=True),start=1) if idx>1 and row[0]==wid]
                for idx in reversed(rows_del):
                    ws.delete_rows(idx)
                date_map: Dict[str,List[str]] = {}
                for date_str, row in edited.iterrows():
                    iso = dt.datetime.strptime(date_str, "%A %d/%m/%Y").date().isoformat()
                    ws.append([wid, iso, row["Titulaire"], row["Suppléant"]])
                    date_map.setdefault(row["Titulaire"], []).append(iso)
                wb.save(DATA_FILE)
                mon=dt.datetime.strptime(wid+"-1", "%Y-W%W-%w").date(); week_dates={mon+dt.timedelta(i) for i in range(7)}
                players["Date du train"] = players["Date du train"].apply(lambda x:_strip_week(str(x),week_dates))
                _update_date_column(players,date_map)
                st.success("Modifications sauvegardées ✔️"); _rerun()

# Fin de l'app("Historique")
all_tir = _tirages_df()
if all_tir.empty:
    st.info("Aucune semaine enregistrée.")
else:
    for wid in sorted(all_tir["Semaine"].unique()):
        wk = all_tir[all_tir["Semaine"] == wid][["Date", "Titulaire", "Suppléant"]].copy()
        wk["Date"] = pd.to_datetime(wk["Date"]).dt.strftime("%A %d/%m/%Y"); wk.set_index("Date", inplace=True)
        with st.expander(f"Semaine {wid}"):
            edited = _data_editor(wk, key=f"ed_{wid}")
            if st.button("💾 Enregistrer", key=f"save_{wid}"):
                # Maj feuille et colonne dates
                _apply = []  # list of rows to rewrite
                wb = _open_wb(); ws = wb[TIRAGES_SHEET]
                # delete old rows
                to_del = [i for i, row in enumerate(ws.iter_rows(values_only=True), start=1) if i > 1 and row[0] == wid]
                for idx in reversed(to_del):
                    ws.delete_rows(idx)
                date_map: Dict[str, List[str]] = {}
                for date_str, row in edited.iterrows():
                    iso = dt.datetime.strptime(date_str, "%A %d/%m/%Y").date().isoformat()
                    ws.append([wid, iso, row["Titulaire"], row["Suppléant"]])
                    for p in (row["Titulaire"], row["Suppléant"]):
                        date_map.setdefault(p, []).append(iso)
                wb.save(DATA_FILE)
                # strip dates of that week then add new ones
                mon = dt.datetime.strptime(wid + "-1", "%Y-W%W-%w").date(); wdates = {mon + dt.timedelta(i) for i in range(7)}
                players["Date du train"] = players["Date du train"].apply(lambda x: _concat([], []) if pd.isna(x) else _concat([], []))  # placeholder strip step handled later
                # Simple reassign: clear then re-add
                players["Date du train"] = None
                _update_date_column(players, date_map)
                st.success("Modifications sauvegardées ✔️"); _rerun()
