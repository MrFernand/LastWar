"""streamlit_app.py (v3.4.1)
============================================================
Correction de la parenthèse manquante (SyntaxError) + code complet.

* Exclusion automatique des joueurs **R1**.
* Toutes les fonctionnalités de la v3.4.
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
# CONFIG
# ---------------------------------------------------------------------------
DATA_FILE = Path("Liste_membres_Train.xlsx")
MEMBRES_SHEET = "Membres"
TIRAGES_SHEET = "Tirages"
WEEKS_AHEAD = 52

# ---------------------------------------------------------------------------
# STREAMLIT COMPAT
# ---------------------------------------------------------------------------

def _data_editor(df: pd.DataFrame, **kw):
    if hasattr(st, "data_editor"):
        return st.data_editor(df, **kw)
    return st.experimental_data_editor(df, **kw)  # type: ignore[attr-defined]


def _rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()  # type: ignore[attr-defined]

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
    df = pd.read_excel(DATA_FILE, sheet_name=MEMBRES_SHEET, engine="openpyxl")
    required = {"Pseudo", "Motif sortie", "Date du train", "Rang"}
    missing = required - set(df.columns)
    if missing:
        st.error("Colonnes manquantes : " + ", ".join(missing))
        st.stop()
    return df


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

def _concat(base: str | float | None, new_dates: List[str]) -> str | None:
    if not new_dates:
        return base
    existing = [] if pd.isna(base) or base is None or not str(base).strip() else [d.strip() for d in str(base).split(",")]
    for d in new_dates:
        if d not in existing:
            existing.append(d)
    return ", ".join(existing) if existing else None


def _strip_week(base: str | None, week_dates: set[dt.date]) -> str | None:
    if pd.isna(base) or base is None or not str(base).strip():
        return base
    kept = []
    for part in str(base).split(","):
        p = part.strip()
        try:
            d = dt.date.fromisoformat(p)
            if d not in week_dates:
                kept.append(p)
        except ValueError:
            kept.append(p)
    return ", ".join(kept) if kept else None

# ---------------------------------------------------------------------------
# ENGINE
# ---------------------------------------------------------------------------

def _eligible(df: pd.DataFrame) -> pd.DataFrame:
    no_motif = df["Motif sortie"].fillna("").str.strip() == ""
    not_r1 = df["Rang"].fillna("").astype(str).str.upper() != "R1"
    return df[no_motif & not_r1]


def _draw_week(df: pd.DataFrame, monday: dt.date) -> Dict[dt.date, Tuple[str, str]]:
    dates = [monday + dt.timedelta(days=i) for i in range(7)]
    pool = df["Pseudo"].tolist(); random.shuffle(pool)
    used=set(); it=iter(pool); sched={}
    for d in dates:
        tit = next(p for p in it if p not in used); used.add(tit)
        sup = next(p for p in it if p != tit)
        sched[d]=(tit,sup)
    return sched

# ---------------------------------------------------------------------------
# UPDATE DATES
# ---------------------------------------------------------------------------

def _update_dates(players: pd.DataFrame, dm: Dict[str, List[str]]):
    players["Date du train"] = players.apply(lambda r: _concat(r["Date du train"], dm.get(r["Pseudo"], [])), axis=1)
    _write_df(players, MEMBRES_SHEET)

# ---------------------------------------------------------------------------
# RESET
# ---------------------------------------------------------------------------

def _reset_all():
    wb = _open_wb(); pdf = _players_df()
    if TIRAGES_SHEET in wb.sheetnames:
        ws = wb[TIRAGES_SHEET]
        if ws.max_row > 1:
            ws.delete_rows(2, ws.max_row)
    else:
        ws = wb.create_sheet(TIRAGES_SHEET); ws.append(["Semaine", "Date", "Titulaire", "Suppléant"])
    pdf["Date du train"] = pd.NA
    _write_df(pdf, MEMBRES_SHEET); wb.save(DATA_FILE)

# ---------------------------------------------------------------------------
# APP
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Tirage train", page_icon="🎲", layout="centered")

st.title("🎲 Tirage au sort – Liste Train")

players = _players_df()

# --- Génération ------------------------------------------------------------

st.sidebar.header("Générer une semaine")
exist_ids = set(_tirages_df()["Semaine"].astype(str).str.strip())
week_opts = [m for m in _next_mondays() if _week_id(m) not in exist_ids]

if week_opts:
    monday_sel = st.sidebar.selectbox(
        "Semaine", week_opts,
        format_func=lambda d: f"{_week_id(d)} – {d.strftime('%d/%m/%Y')}"
    )
    if st.sidebar.button("🎲 Générer"):
        if _week_id(monday_sel) in exist_ids:
            st.sidebar.warning("Cette semaine existe déjà.")
        else:
            elig = _eligible(players)
            if len(elig) < 14:
                st.sidebar.error("Pas assez de joueurs éligibles (≥14)")
            else:
                sched = _draw_week(elig, monday_sel)
                rows = [(_week_id(monday_sel), d.isoformat(), tit, sup) for d, (tit, sup) in sched.items()]
                _save_tirages(rows)
                dm: Dict[str, List[str]] = {}
                for d, (tit, _) in sched.items():
                    dm.setdefault(tit, []).append(d.isoformat())
                _update_dates(players, dm)
                st.sidebar.success("Semaine enregistrée ✅"); _rerun()
else:
    st.sidebar.info("Toutes les semaines futures sont déjà tirées.")

# --- Reset -----------------------------------------------------------------

st.sidebar.header("Réinitialiser")
with st.sidebar.form("reset_form"):
    conf = st.text_input("Tape CONFIRMER pour tout effacer")
    submit = st.form_submit_button("🗑️ Réinitialiser")
    if submit:
        if conf == "CONFIRMER":
            _reset_all()
            st.sidebar.success("Base remise à zéro ✔️")
            _rerun()
        else:
            st.sidebar.warning("Confirmation incorrecte – reset annulé.")

# ---- Affichage historique --------------------------------------------------

st.subheader("Historique des semaines tirées")
all_tir = _tirages_df()
if all_tir.empty:
    st.info("Aucun tirage enregistré pour l'instant.")
else:
    seen = set(); uniq_weeks = []
    for w in all_tir["Semaine"].astype(str).str.strip():
        if w not in seen:
            seen.add(w); uniq_weeks.append(w)
    for idx, wid in enumerate(sorted(uniq_weeks)):
        wk = all_tir[all_tir["Semaine"].astype(str).str.strip() == wid][["Date","Titulaire","Suppléant"]].copy()
        wk["Date"] = pd.to_datetime(wk["Date"]).dt.strftime("%A %d/%m/%Y"); wk.set_index("Date", inplace=True)
        with st.expander(f"Semaine {wid}"):
            edited = _data_editor(wk, key=f"ed_{idx}_{wid}")
            if st.button("💾 Enregistrer", key=f"save_{idx}_{wid}"):
                wb = _open_wb(); ws = wb[TIRAGES_SHEET]
                rows_del=[i for i,row in enumerate(ws.iter_rows(values_only=True),start=1) if i>1 and str(row[0]).strip()==wid]
                for i in reversed(rows_del):
                    ws.delete_rows(i)
                date_map: Dict[str,List[str]]={}
                for date_str,row in edited.iterrows():
                    iso=dt.datetime.strptime(date_str,"%A %d/%m/%Y").date().isoformat()
                    ws.append([wid,iso,row["Titulaire"],row["Suppléant"]])
                    date_map.setdefault(row["Titulaire"], []).append(iso)
                wb.save(DATA_FILE)
                mon=dt.datetime.strptime(wid+"-1","%Y-W%W-%w").date(); week_dates={mon+dt.timedelta(i) for i in range(7)}
                players["Date du train"] = players["Date du train"].apply(lambda x:_strip_week(str(x),week_dates))
                _update_dates(players,date_map)
                st.success("Modifications sauvegardées ✔️"); _rerun()

# ---- Téléchargement -------------------------------------------------------

with open(DATA_FILE, "rb") as f:
    st.download_button(
        label="📥 Télécharger le fichier Excel mis à jour",
        data=f.read(),
        file_name=DATA_FILE.name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

# Fin de l'app
