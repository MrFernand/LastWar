"""streamlit_app.py (v3.0.2)
=================================
Application complète Streamlit pour gérer les tirages au sort hebdomadaires à
partir du classeur **Liste_membres_Train.xlsx**.

Principales fonctionnalités
---------------------------
* **Filtre "Motif sortie"** : les joueurs ayant un motif sont exclus.
* **Inscription automatique** de la date tirée dans "Date du train".
* **Historique dans la feuille "Tirages"** (une ligne par jour).
* **Édition manuelle** d’un planning (tableau éditable → Sauvegarder).
* **Réinitialisation sécurisée** (bouton + confirmation « CONFIRMER »).
* **Compatibilité Streamlit ≥ 1.18** (gestion `st.data_editor` / `experimental_*` et `st.rerun`).

Pour déployer : requirements.txt minimal
```
streamlit>=1.35
pandas
openpyxl
```
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
WEEKS_AHEAD_SHOWN = 52  # 1 an

# ---------------------------------------------------------------------------
# Compatibilité Streamlit
# ---------------------------------------------------------------------------

def _data_editor(df: pd.DataFrame, **kwargs):
    """Wrapper compatible pour l’éditeur de tableau."""
    if hasattr(st, "data_editor"):
        return st.data_editor(df, **kwargs)
    return st.experimental_data_editor(df, **kwargs)  # type: ignore[attr-defined]


def _rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()  # type: ignore[attr-defined]

# ---------------------------------------------------------------------------
# Fonctions utilitaires (dates concat / suppression)
# ---------------------------------------------------------------------------

def _concat_date(existing: str | float | None, new_date: str | None) -> str | None:
    """Ajoute `new_date` à la chaîne de dates (séparées par virgules)."""
    if new_date is None:
        return existing
    if pd.isna(existing) or existing is None or str(existing).strip() == "":
        return new_date
    dates = [d.strip() for d in str(existing).split(",")]
    if new_date in dates:
        return str(existing)
    return str(existing) + ", " + new_date


def _remove_week_dates(existing: str | None, week_dates: set[dt.date]) -> str | None:
    """Supprime les dates appartenant à la semaine `week_dates`.

    * Ignore les sous-chaînes vides ou mal formées au format ISO.
    * Évite ValueError en utilisant un try/except.
    """
    if pd.isna(existing) or existing is None or str(existing).strip() == "":
        return existing

    kept_parts: List[str] = []
    for part in str(existing).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            date_obj = dt.date.fromisoformat(part)
        except ValueError:
            # entrée non ISO 8601, on la conserve telle quelle
            kept_parts.append(part)
            continue
        if date_obj not in week_dates:
            kept_parts.append(part)

    return ", ".join(kept_parts) if kept_parts else None
    kept = [d for d in str(existing).split(",") if dt.date.fromisoformat(d.strip()) not in week_dates]
    return ", ".join(kept) if kept else None

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
        st.error(f"Feuille '{MEMBRES_SHEET}' manquante dans le classeur.")
        st.stop()
    df = pd.read_excel(DATA_FILE, sheet_name=MEMBRES_SHEET, engine="openpyxl")
    required = {"Pseudo", "Motif sortie", "Date du train"}
    if not required.issubset(df.columns):
        st.error("Colonnes manquantes : " + ", ".join(required))
        st.stop()
    return df


def _save_players_df(df: pd.DataFrame, wb: openpyxl.Workbook) -> None:
    with pd.ExcelWriter(DATA_FILE, engine="openpyxl", mode="a", if_sheet_exists="replace") as writer:
        df.to_excel(writer, index=False, sheet_name=MEMBRES_SHEET)


def _append_tirages_rows(rows: List[Tuple[str, str, str, str]], wb: openpyxl.Workbook) -> None:
    """Ajoute les lignes à la feuille Tirages (création si besoin)."""
    if TIRAGES_SHEET not in wb.sheetnames:
        ws = wb.create_sheet(TIRAGES_SHEET)
        ws.append(["Semaine", "Date", "Titulaire", "Suppléant"])
    else:
        ws = wb[TIRAGES_SHEET]
    for r in rows:
        ws.append(list(r))
    wb.save(DATA_FILE)


def _tirages_df(wb: openpyxl.Workbook) -> pd.DataFrame:
    if TIRAGES_SHEET not in wb.sheetnames:
        return pd.DataFrame(columns=["Semaine", "Date", "Titulaire", "Suppléant"])
    return pd.read_excel(DATA_FILE, sheet_name=TIRAGES_SHEET, engine="openpyxl")


def _clear_tirages_and_dates(wb: openpyxl.Workbook, players_df: pd.DataFrame) -> None:
    """Supprime toutes les lignes de la feuille Tirages (en conservant l'en‑tête)
    et remet à blanc la colonne « Date du train ».
    La feuille est recréée au besoin pour garantir qu’elle existe après reset.
    """
    if TIRAGES_SHEET in wb.sheetnames:
        ws = wb[TIRAGES_SHEET]
        # Supprime tout sauf la première ligne (header)
        if ws.max_row > 1:
            ws.delete_rows(2, ws.max_row)
    else:
        ws = wb.create_sheet(TIRAGES_SHEET)
        ws.append(["Semaine", "Date", "Titulaire", "Suppléant"])

    # Réinitialiser la colonne Date du train
    if "Date du train" in players_df.columns:
        players_df["Date du train"] = pd.NA
        _save_players_df(players_df, wb)

    wb.save(DATA_FILE)

# ---------------------------------------------------------------------------
# Semaine / tirage helpers
# ---------------------------------------------------------------------------

def _week_id_for_date(d: dt.date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def _monday_of_week(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())


def _upcoming_week_mondays(n: int = WEEKS_AHEAD_SHOWN) -> List[dt.date]:
    next_mon = _monday_of_week(dt.date.today() + dt.timedelta(days=7))
    return [next_mon + dt.timedelta(days=7 * i) for i in range(n)]


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

# ---------------------------------------------------------------------------
# Appliquer modifications après édition manuelle
# ---------------------------------------------------------------------------

def _apply_edits_and_save(
    edited_df: pd.DataFrame,
    week_id: str,
    wb: openpyxl.Workbook,
    players_df: pd.DataFrame,
) -> None:
    if TIRAGES_SHEET not in wb.sheetnames:
        st.error("Feuille Tirages absente.")
        return
    ws = wb[TIRAGES_SHEET]
    # Supprimer lignes existantes pour la semaine
    rows_to_del = [i for i, row in enumerate(ws.iter_rows(values_only=True), start=1) if i > 1 and row[0] == week_id]
    for idx in reversed(rows_to_del):
        ws.delete_rows(idx)
    # Ajouter lignes éditées
    for date_str, row in edited_df.iterrows():
        iso = dt.datetime.strptime(date_str, "%A %d/%m/%Y").date().isoformat()
        ws.append([week_id, iso, row["Titulaire"], row["Suppléant"]])
    wb.save(DATA_FILE)

    # Mettre à jour Date du train
    monday = dt.datetime.strptime(week_id + "-1", "%Y-W%W-%w").date()
    week_dates = {monday + dt.timedelta(i) for i in range(7)}
    players_df["Date du train"] = players_df["Date du train"].apply(lambda x: _remove_week_dates(str(x), week_dates))
    date_map = {row["Titulaire"]: dt.datetime.strptime(date_str, "%A %d/%m/%Y").date().isoformat() for date_str, row in edited_df.iterrows()}
    players_df["Date du train"] = players_df.apply(
        lambda r: _concat_date(r["Date du train"], date_map.get(r["Pseudo"])) if r["Pseudo"] in date_map else r["Date du train"],
        axis=1,
    )
    _save_players_df(players_df, wb)

# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Tirage au sort train", page_icon="🎲", layout="centered")

st.title("🎲 Tirages au sort – Liste Train")

wb = _load_workbook()
players_df = _load_players_df(wb)

# ---- Barre latérale : Génération --------------------------------------------------------------

st.sidebar.header("Générer une semaine")
existing_wids = set(_tirages_df(wb)["Semaine"].unique())
week_opts = [m for m in _upcoming_week_mondays() if _week_id_for_date(m) not in existing_wids]

if week_opts:
    monday_sel = st.sidebar.selectbox(
        "Nouvelle semaine (lundi)",
        week_opts,
        format_func=lambda d: f"{_week_id_for_date(d)} – {d.strftime('%d/%m/%Y')}",
    )
    if st.sidebar.button("🎲 Générer"):
        elig = _eligible(players_df)
        if len(elig) < 14:
            st.sidebar.error("Pas assez de joueurs éligibles (min 14)")
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
            st.sidebar.success("Semaine enregistrée ✅")
            _rerun()
else:
    st.sidebar.info("Toutes les semaines futures sont déjà tirées.")

# ---- Barre latérale : Réinitialisation --------------------------------------------------------

st.sidebar.header("Réinitialiser")
if st.sidebar.button("🗑️ Réinitialiser les tirages"):
    txt = st.sidebar.text_input("Tape CONFIRMER pour valider", key="reset_confirm")
    if txt == "CONFIRMER":
        _clear_tirages_and_dates(wb, players_df)
        st.sidebar.success("Réinitialisation effectuée.")
        _rerun()
    elif txt != "":
        st.sidebar.warning("Saisie incorrecte, opération annulée.")

# ---- Historique ----------------------------------------------------------------------------

st.subheader("Historique des semaines tirées")

tdf = _tirages_df(wb)
if tdf.empty:
    st.info("Aucun tirage enregistré pour l'instant.")
else:
    for wid in sorted(tdf["Semaine"].unique()):
        with st.expander(f"Semaine {wid}"):
            wdf = tdf[tdf["Semaine"] == wid][["Date", "Titulaire", "Suppléant"]].copy()
            wdf["Date"] = pd.to_datetime(wdf["Date"]).dt.strftime("%A %d/%m/%Y")
            wdf.set_index("Date", inplace=True)
            edited = _data_editor(wdf, key=f"ed_{wid}")
            if st.button("💾 Enregistrer", key=f"save_{wid}"):
                _apply_edits_and_save(edited, wid, wb, players_df)
                st.success("Modifications sauvegardées ✔️")
                _rerun()
