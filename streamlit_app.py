"""streamlit_app.py (v3.1)
=========================================
Refonte stabilité : réinitialisation fiable + écriture Excel garantie.

Correctifs majeurs
------------------
1. **Réinitialisation fiable** :
   * interface sous `st.sidebar.form()` : champ « CONFIRMER » **puis** bouton *Valider* ;
   * la feuille *Tirages* est vidée (l'en-tête est conservé/créé) ;
   * la colonne « Date du train » est effacée ;
   * le classeur est sauvegardé ⇒ les semaines redeviennent disponibles.
2. **Écriture Excel solide** :
   * après chaque modification (tirage, édition, reset) **double sauvegarde** :
     `wb.save(...)` **et** ré-écriture DataFrame via `pandas.ExcelWriter`.
   * évite les “workbook not saved” ou « stale data ».
3. **UX** : messages clairs côté barre latérale et historique.

Dépendances : `streamlit>=1.35`, `pandas`, `openpyxl>=3.1`.
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
WEEKS_AHEAD = 52  # semaines futures proposées

# ---------------------------------------------------------------------------
# COMPAT WRAPPERS
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
    """Écrit la DataFrame dans `sheet` (remplacement)."""
    with pd.ExcelWriter(DATA_FILE, engine="openpyxl", mode="a", if_sheet_exists="replace") as w:
        df.to_excel(w, index=False, sheet_name=sheet)


def _players_df(wb: openpyxl.Workbook) -> pd.DataFrame:
    if MEMBRES_SHEET not in wb.sheetnames:
        st.error(f"Feuille {MEMBRES_SHEET} manquante.")
        st.stop()
    df = pd.read_excel(DATA_FILE, sheet_name=MEMBRES_SHEET, engine="openpyxl")
    missing = {"Pseudo", "Motif sortie", "Date du train"} - set(df.columns)
    if missing:
        st.error("Colonnes manquantes : " + ", ".join(missing))
        st.stop()
    return df


def _tirages_df(wb: openpyxl.Workbook) -> pd.DataFrame:
    if TIRAGES_SHEET not in wb.sheetnames:
        return pd.DataFrame(columns=["Semaine", "Date", "Titulaire", "Suppléant"])
    return pd.read_excel(DATA_FILE, sheet_name=TIRAGES_SHEET, engine="openpyxl")


def _save_tirages(rows: List[Tuple[str, str, str, str]], wb: openpyxl.Workbook):
    if TIRAGES_SHEET not in wb.sheetnames:
        ws = wb.create_sheet(TIRAGES_SHEET)
        ws.append(["Semaine", "Date", "Titulaire", "Suppléant"])
    else:
        ws = wb[TIRAGES_SHEET]
    for r in rows:
        ws.append(list(r))
    wb.save(DATA_FILE)

# ---------------------------------------------------------------------------
# STRING HELPERS (dates concat)
# ---------------------------------------------------------------------------

def _concat_date(existing: str | float | None, new_iso: str | None) -> str | None:
    if new_iso is None:
        return existing
    if pd.isna(existing) or not str(existing).strip():
        return new_iso
    items = [d.strip() for d in str(existing).split(",")]
    if new_iso in items:
        return str(existing)
    items.append(new_iso)
    return ", ".join(items)


def _strip_week(existing: str | None, week_dates: set[dt.date]) -> str | None:
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
            kept.append(p)  # chaîne non ISO, on conserve
    return ", ".join(kept) if kept else None

# ---------------------------------------------------------------------------
# Tirage
# ---------------------------------------------------------------------------

def _eligible(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["Motif sortie"].fillna("").str.strip() == ""]


def _draw_week(df: pd.DataFrame, monday: dt.date) -> Dict[dt.date, Tuple[str, str]]:
    dates = [monday + dt.timedelta(days=i) for i in range(7)]
    pool = df["Pseudo"].tolist(); random.shuffle(pool)
    it = iter(pool); used: set[str] = set(); sched = {}
    for d in dates:
        tit = next(p for p in it if p not in used); used.add(tit)
        sup = next(p for p in it if p != tit)
        sched[d] = (tit, sup)
    return sched

# ---------------------------------------------------------------------------
# APPLY EDITS
# ---------------------------------------------------------------------------

def _apply_edits(edt: pd.DataFrame, week_id: str, wb: openpyxl.Workbook, pdf: pd.DataFrame):
    # Maj feuille Tirages
    if TIRAGES_SHEET not in wb.sheetnames:
        st.error("Feuille Tirages absente."); return
    ws = wb[TIRAGES_SHEET]
    del_rows = [i for i,row in enumerate(ws.iter_rows(values_only=True), start=1) if i>1 and row[0]==week_id]
    for idx in reversed(del_rows):
        ws.delete_rows(idx)
    for date_str, row in edt.iterrows():
        iso = dt.datetime.strptime(date_str, "%A %d/%m/%Y").date().isoformat()
        ws.append([week_id, iso, row["Titulaire"], row["Suppléant"]])
    wb.save(DATA_FILE)

    # Maj Date du train
    mon = dt.datetime.strptime(week_id+"-1", "%Y-W%W-%w").date(); wdates={mon+dt.timedelta(i) for i in range(7)}
    pdf["Date du train"] = pdf["Date du train"].apply(lambda x:_strip_week(str(x),wdates))
    date_map={row["Titulaire"]:dt.datetime.strptime(date_str,"%A %d/%m/%Y").date().isoformat() for date_str,row in edt.iterrows()}
    pdf["Date du train"] = pdf.apply(lambda r:_concat_date(r["Date du train"],date_map.get(r["Pseudo"])) if r["Pseudo"] in date_map else r["Date du train"],axis=1)
    _write_df(pdf, MEMBRES_SHEET)
    wb.save(DATA_FILE)

# ---------------------------------------------------------------------------
# RESET LOGIC
# ---------------------------------------------------------------------------

def _reset_all(wb: openpyxl.Workbook, pdf: pd.DataFrame):
    # vider Tirages (laisser header)
    if TIRAGES_SHEET in wb.sheetnames:
        ws = wb[TIRAGES_SHEET]
        if ws.max_row>1:
            ws.delete_rows(2, ws.max_row)
    else:
        ws = wb.create_sheet(TIRAGES_SHEET); ws.append(["Semaine","Date","Titulaire","Suppléant"])
    # clear dates
    pdf["Date du train"] = pd.NA
    _write_df(pdf, MEMBRES_SHEET)
    wb.save(DATA_FILE)

# ---------------------------------------------------------------------------
# STREAMLIT APP
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Tirage train", page_icon="🎲", layout="centered")

st.title("🎲 Tirage au sort – Liste Train")

wb = _open_wb()
players = _players_df(wb)

# ----- SIDEBAR GENERATION --------------------------------------------------

st.sidebar.header("Générer une semaine")
exist_ids=set(_tirages_df(wb)["Semaine"].unique()); opt=[m for m in _next_mondays() if _week_id(m) not in exist_ids]
if opt:
    monday_sel = st.sidebar.selectbox("Semaine", opt, format_func=lambda d:f"{_week_id(d)} – {d.strftime('%d/%m/%Y')}")
    if st.sidebar.button("🎲 Générer"):
        elig=_eligible(players)
        if len(elig)<14:
            st.sidebar.error("Pas assez de joueurs éligibles (>=14)")
        else:
            sched=_draw_week(elig, monday_sel)
            rows=[(_week_id(monday_sel), d.isoformat(),tit,sup) for d,(tit,sup) in sched.items()]
            _save_tirages(rows, wb)
            date_map={tit:d.isoformat() for d,(tit,_) in sched.items()}
            players["Date du train"] = players.apply(lambda r:_concat_date(r["Date du train"],date_map.get(r["Pseudo"])) if r["Pseudo"] in date_map else r["Date du train"],axis=1)
            _write_df(players, MEMBRES_SHEET); wb.save(DATA_FILE)
            st.sidebar.success("Semaine enregistrée ✅"); _rerun()
else:
    st.sidebar.info("Toutes les semaines futures sont déjà tirées.")

# ----- SIDEBAR RESET -------------------------------------------------------

st.sidebar.header("Réinitialiser")
with st.sidebar.form(key="reset_form"):
    confirm=st.text_input("Tape CONFIRMER pour tout effacer")
    submitted=st.form_submit_button("Valider la réinitialisation 🗑️")
    if submitted:
        if confirm=="CONFIRMER":
            _reset_all(wb, players)
            st.sidebar.success("Base remise à zéro ✔️"); _rerun()
        else:
            st.sidebar.warning("Confirmation incorrecte – reset annulé.")

# ----- HISTORIQUE ----------------------------------------------------------

st.subheader("Historique")
all_tir=_tirages_df(wb)
if all_tir.empty:
    st.info("Aucune semaine enregistrée.")
else:
    for wid in sorted(all_tir["Semaine"].unique()):
        with st.expander(f"Semaine {wid}"):
            wk=all_tir[all_tir["Semaine"]==wid][["Date","Titulaire","Suppléant"]].copy()
            wk["Date"] = pd.to_datetime(wk["Date"]).dt.strftime("%A %d/%m/%Y"); wk.set_index("Date", inplace=True)
            edited=_data_editor(wk, key=f"ed_{wid}")
            if st.button("💾 Enregistrer", key=f"save_{wid}"):
                _apply_edits(edited, wid, wb, players)
                st.success("Modifications sauvegardées ✔️"); _rerun()
# --- Téléchargement du classeur -------------------------------------------
with open(DATA_FILE, "rb") as f:
    st.download_button(
        label="📥 Télécharger le fichier Excel mis à jour",
        data=f.read(),
        file_name=DATA_FILE.name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
