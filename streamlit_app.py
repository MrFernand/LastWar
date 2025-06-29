
"""streamlit_app.py (v3.0.1 – bug-fix NameError)
=================================================
*Corrige l’exception `NameError` due à l’appel de fonctions définies plus loin.*

Modifications principales
-------------------------
1. **Les helpers `_concat_date`, `_remove_week_dates` et `_apply_edits_and_save`**
   sont désormais définis *avant* toute utilisation dans le flux Streamlit.
2. Aucun changement fonctionnel ; l’interface reste identique.
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
# Configuration
# ---------------------------------------------------------------------------

DATA_FILE = Path("Liste_membres_Train.xlsx")
MEMBRES_SHEET = "Membres"
TIRAGES_SHEET = "Tirages"
WEEKS_AHEAD_SHOWN = 52

# ---------------------------------------------------------------------------
# Helper functions that will be used throughout the app
# ---------------------------------------------------------------------------

def _concat_date(existing: str | float | None, new_date: str | None) -> str | None:
    """Concatène `new_date` à la chaîne existante (séparée par virgules)."""
    if new_date is None:
        return existing
    if pd.isna(existing) or existing is None or str(existing).strip() == "":
        return new_date
    existing_str = str(existing)
    dates = [d.strip() for d in existing_str.split(",")]
    if new_date in dates:
        return existing_str
    return existing_str + ", " + new_date


def _remove_week_dates(existing: str | None, week_dates: set[dt.date]) -> str | None:
    if pd.isna(existing) or existing is None or str(existing).strip() == "":
        return existing
    kept = [d for d in str(existing).split(",") if dt.date.fromisoformat(d.strip()) not in week_dates]
    return ", ".join(kept) if kept else None


def _apply_edits_and_save(
    edited_df: pd.DataFrame,
    week_id: str,
    wb: "openpyxl.Workbook",
    players_df: pd.DataFrame,
) -> None:
    """Met à jour la feuille Tirages + colonne Date du train après édition."""
    # 1. Mettre à jour la feuille Tirages
    if TIRAGES_SHEET not in wb.sheetnames:
        st.error("Feuille Tirages manquante – impossible de sauvegarder.")
        return
    ws = wb[TIRAGES_SHEET]
    # Supprime les anciennes lignes de la semaine
    rows_to_del = [idx for idx, row in enumerate(ws.iter_rows(values_only=True), start=1) if idx > 1 and row[0] == week_id]
    for ridx in reversed(rows_to_del):
        ws.delete_rows(ridx)
    # Ajoute les nouvelles
    for date_str, row in edited_df.iterrows():
        iso_date = dt.datetime.strptime(date_str, "%A %d/%m/%Y").date().isoformat()
        ws.append([week_id, iso_date, row["Titulaire"], row["Suppléant"]])
    wb.save(DATA_FILE)

    # 2. Mettre à jour la colonne Date du train
    monday = dt.datetime.strptime(week_id + "-1", "%Y-W%W-%w").date()
    week_dates = {monday + dt.timedelta(i) for i in range(7)}
    players_df["Date du train"] = players_df["Date du train"].apply(lambda x: _remove_week_dates(str(x), week_dates))

    date_map = {row["Titulaire"]: dt.datetime.strptime(date, "%A %d/%m/%Y").date().isoformat() for date, row in edited_df.iterrows()}
    players_df["Date du train"] = players_df.apply(
        lambda r: _concat_date(r["Date du train"], date_map.get(r["Pseudo"])) if r["Pseudo"] in date_map else r["Date du train"],
        axis=1,
    )
    _save_players_df(players_df, wb)

# ---------------------------------------------------------------------------
# Excel helpers
# ---------------------------------------------------------------------------

def _load_workbook() -> openpyxl.Workbook:
    if not DATA_FILE.exists():
        st.error(f"Fichier {DATA_FILE} introuvable.")
        st.stop()
    return openpyxl.load_workbook(DATA_FILE)


def _load_players_df(wb: openpyxl.Workbook) -> pd.DataFrame:
    if MEMBRES_SHEET not in wb.sheetnames:
        st.error(f"La feuille '{MEMBRES_SHEET}' est absente dans le classeur.")
        st.stop()
    df = pd.read_excel(DATA_FILE, sheet_name=MEMBRES_SHEET, engine="openpyxl")
    required = {"Pseudo", "Motif sortie", "Date du train"}
    if not required.issubset(df.columns):
        st.error("Colonnes manquantes dans la feuille Membres : " + ", ".join(required))
        st.stop()
    return df


def _save_players_df(df: pd.DataFrame, wb: openpyxl.Workbook) -> None:
    with pd.ExcelWriter(DATA_FILE, engine="openpyxl", mode="a", if_sheet_exists="replace") as writer:
        df.to_excel(writer, index=False, sheet_name=MEMBRES_SHEET)


def _append_tirages_rows(rows: List[Tuple[str, str, str, str]], wb: openpyxl.Workbook) -> None:
    if TIRAGES_SHEET not in wb.sheetnames:
        ws = wb.create_sheet(TIRAGES_SHEET)
        ws.append(["Semaine", "Date", "Titulaire", "Suppléant"])
    else:
        ws = wb[TIRAGES_SHEET]
    for r in rows:
        ws.append(list(r))
    wb.save(DATA_FILE)


def _clear_tirages_and_dates(wb: openpyxl.Workbook, players_df: pd.DataFrame) -> None:
    if TIRAGES_SHEET in wb.sheetnames:
        wb.remove(wb[TIRAGES_SHEET])
    players_df["Date du train"] = pd.NA
    _save_players_df(players_df, wb)
    wb.save(DATA_FILE)

# ---------------------------------------------------------------------------
# Utils weeks & eligibility
# ---------------------------------------------------------------------------

def _week_id_for_date(d: dt.date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def _monday_of_week(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())


def _upcoming_week_mondays(n: int = WEEKS_AHEAD_SHOWN) -> List[dt.date]:
    today = dt.date.today()
    nxt = _monday_of_week(today + dt.timedelta(days=7))
    return [nxt + dt.timedelta(days=7 * i) for i in range(n)]


def _eligible(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["Motif sortie"].fillna("").str.strip() == ""]


def _draw_week(df: pd.DataFrame, monday: dt.date) -> Dict[dt.date, Tuple[str, str]]:
    dates = [monday + dt.timedelta(i) for i in range(7)]
    pseudos = df["Pseudo"].tolist()
    random.shuffle(pseudos)
    used: set[str] = set()
    it = iter(pseudos)
    sched: Dict[dt.date, Tuple[str, str]] = {}
    for d in dates:
        tit = next(p for p in it if p not in used)
        used.add(tit)
        sup = next(p for p in it if p != tit)
        sched[d] = (tit, sup)
    return sched


def _tirages_df(wb: openpyxl.Workbook) -> pd.DataFrame:
    if TIRAGES_SHEET not in wb.sheetnames:
        return pd.DataFrame(columns=["Semaine", "Date", "Titulaire", "Suppléant"])
    return pd.read_excel(DATA_FILE, sheet_name=TIRAGES_SHEET, engine="openpyxl")

# ---------------------------------------------------------------------------
# Streamlit App
# ---------------------------------------------------------------------------

st.set_page_config("Tirage au sort train", "🎲", layout="centered")

st.title("🎲 Tirages au sort – Liste Train")

wb = _load_workbook()
players_df = _load_players_df(wb)

# --- Sidebar: Génération ---------------------------------------------------

st.sidebar.header("Générer une nouvelle semaine")

existing_wids = set(_tirages_df(wb)["Semaine"].unique())
week_opts = [m for m in _upcoming_week_mondays() if _week_id_for_date(m) not in existing_wids]

if week_opts:
    monday_sel = st.sidebar.selectbox(
        "Semaine à créer (lundi)",
        week_opts,
        format_func=lambda d: f"{_week_id_for_date(d)} – {d.strftime('%d/%m/%Y')}",
    )
    if st.sidebar.button("🎲 Générer"):
        elig = _eligible(players_df)
        if len(elig) < 14:
            st.sidebar.error("Pas assez de joueurs éligibles (min 14) !")
        else:
            sched = _draw_week(elig, monday_sel)
            rows = [(_week_id_for_date(monday_sel), d.isoformat(), tit, sup) for d, (tit, sup) in sched.items()]
            _append_tirages_rows(rows, wb)
            date_map = {tit: d.isoformat() for d, (tit, _) in sched.items()}
            players_df["Date du train"] = players_df.apply(
                lambda r: _concat_date(r["Date du train"], date_map.get(r["Pseudo"])) if r["Pseudo"] in date_map else r["Date du train"],
                axis=1,
            )
            _save_players_df(players_df, wb)
            st.sidebar.success("✅ Semaine enregistrée !")
            st.rerun()
else:
    st.sidebar.info("Toutes les semaines futures sont déjà générées.")

# --- Sidebar: Reset --------------------------------------------------------

st.sidebar.header("Réinitialiser")
if st.sidebar.button("🗑️ Réinitialiser les tirages"):
    conf = st.sidebar.text_input("Tape CONFIRMER", key="reset_confirm")
    if conf == "CONFIRMER":
        _clear_tirages_and_dates(wb, players_df)
        st.sidebar.success("Réinitialisation terminée.")
        st.rerun()
    else:
        st.sidebar.warning("Annulé : texte incorrect.")

# --- Historique ------------------------------------------------------------

st.subheader("Historique des semaines tirées")
mdat = _tirages_df(wb)
if mdat.empty:
    st.info("Aucun tirage enregistré.")
else:
    for wid in sorted(mdat["Semaine"].unique()):
        with st.expander(f"Semaine {wid}"):
            wdf = mdat[mdat["Semaine"] == wid][["Date", "Titulaire", "Suppléant"]].copy()
            wdf["Date"] = pd.to_datetime(wdf["Date"]).dt.strftime("%A %d/%m/%Y")
            wdf.set_index("Date", inplace=True)
            edited = st.experimental_data_editor(wdf, key=f"ed_{wid}")
            if st.button("💾 Enregistrer", key=f"save_{wid}"):
                _apply_edits_and_save(edited, wid, wb, players_df)
                st.success("Modifications sauvegardées.")
                st.rerun()
