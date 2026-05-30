import streamlit as st
import os
import sqlite3
import json
import numpy as np
import geopandas as gpd
import pandas as pd

try:
    import pydeck as pdk
    PYDECK_OK = True
except ImportError:
    PYDECK_OK = False

try:
    import plotly.graph_objects as go
    PLOTLY_OK = True
except ImportError:
    PLOTLY_OK = False

st.set_page_config(
    page_title="Jumeau Numérique IDF",
    layout="wide",
    initial_sidebar_state="expanded",
)

try:
    from run_pipeline import executer_pipeline_complet
    PIPELINE_OK = True
except ImportError as e:
    PIPELINE_OK = False
    st.error(f"Impossible d'importer le pipeline : {e}")

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
_DIR_PROC     = os.path.join(BASE_DIR, "data", "03_processed")
CHEMIN_OPT    = os.path.join(_DIR_PROC, "reseau_optimise.geojson")
CHEMIN_PDK    = os.path.join(_DIR_PROC, "reseau_pydeck.parquet")
CHEMIN_PDK_SL = os.path.join(_DIR_PROC, "reseau_pydeck_slim.parquet")
CHEMIN_NOEUDS = os.path.join(_DIR_PROC, "noeuds_pydeck.parquet")
CHEMIN_DB     = os.path.join(_DIR_PROC, "reseau.db")

_COLS_PDK = [
    'path', 'type_reseau', 'code_departement', 'code_commune',
    'SPR', 'Pop_Score', 'ERP_Score', 'Risk_DICT', 'Centralite', 'CLC_Sensibilite',
    'cout_estime', 'annee_renovation', 'IFS_base', 'IFS',
]
# 150 000 segments → ~25 Mo de GeoJSON minimal → bien sous la limite de 200 Mo
_MAX_SEG = 150_000


# ════════════════════════════════════════════════════════════════════════
#  SIDEBAR
# ════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.title("Simulateur IDF")
    st.markdown("---")
    with st.form("sim_form"):
        budget = st.slider("Budget annuel (M€)", 0, 4000, 300, 50)
        timeline = st.slider("Projection (années)", 0, 20, 0, 1)
        st.markdown("---")
        canicule_active = st.toggle("Stress Canicule", value=False)
        st.markdown("---")
        lancer = st.form_submit_button("Lancer la Simulation", type="primary", use_container_width=True)
    crisis_type = "Canicule (Stress Thermique)" if canicule_active else "Aucune"


# ════════════════════════════════════════════════════════════════════════
#  PIPELINE
# ════════════════════════════════════════════════════════════════════════
@st.cache_data(show_spinner="Simulation en cours…", ttl=3600)
def run_pipeline_cached(budget, crisis_type):
    if not PIPELINE_OK:
        return None
    return executer_pipeline_complet(budget=float(budget), crisis_type=crisis_type)


if lancer and PIPELINE_OK:
    last_budget = st.session_state.get('_last_budget')
    last_crisis = st.session_state.get('_last_crisis')
    params_changed = (budget != last_budget) or (crisis_type != last_crisis)
    if params_changed:
        run_pipeline_cached.clear()
    with st.spinner("Pipeline en cours…"):
        res = run_pipeline_cached(budget, crisis_type)
    if res:
        st.session_state['_last_budget'] = budget
        st.session_state['_last_crisis'] = crisis_type
        if params_changed:
            st.cache_data.clear()
            for f in [CHEMIN_PDK_SL, CHEMIN_DB]:
                if os.path.exists(f):
                    os.remove(f)
        st.rerun()
    else:
        st.sidebar.error("Echec du pipeline")


# ════════════════════════════════════════════════════════════════════════
#  BASE DE DONNÉES SQLITE
# ════════════════════════════════════════════════════════════════════════
def _init_db(df: pd.DataFrame, nodes):
    """Crée reseau.db depuis le DataFrame slim (s'exécute une seule fois)."""
    if os.path.exists(CHEMIN_DB):
        return
    os.makedirs(_DIR_PROC, exist_ok=True)

    df_db = df.reset_index(drop=True).copy()

    def _p2s(p):
        try:
            return json.dumps([[float(c[0]), float(c[1])] for c in p])
        except Exception:
            return '[]'

    df_db['path'] = df_db['path'].apply(_p2s)

    conn = sqlite3.connect(CHEMIN_DB)
    df_db.to_sql('segments', conn, if_exists='replace', index=True, index_label='id')
    conn.execute("CREATE INDEX IF NOT EXISTS idx_seg ON segments(id)")
    if nodes is not None and not nodes.empty:
        nodes.reset_index(drop=True).to_sql('noeuds', conn, if_exists='replace', index=True)
    conn.commit()
    conn.close()


@st.cache_data(show_spinner=False)
def _get_segment(seg_id: int) -> dict:
    """Retourne les détails complets d'un segment depuis SQLite."""
    if not os.path.exists(CHEMIN_DB):
        return {}
    try:
        conn = sqlite3.connect(CHEMIN_DB)
        row  = pd.read_sql("SELECT * FROM segments WHERE id = ?", conn, params=[int(seg_id)])
        conn.close()
        return {} if row.empty else row.iloc[0].to_dict()
    except Exception:
        return {}


# ════════════════════════════════════════════════════════════════════════
#  CHARGEMENT RÉSEAU
# ════════════════════════════════════════════════════════════════════════
def _sous_echantillon(df):
    """Échantillon stratifié par département — tous les 8 depts IDF sont représentés.
    Chaque département reçoit un minimum de MIN_PAR_DEPT segments, puis le budget
    restant est distribué proportionnellement. Garantit l'affichage des segments
    critiques (rouge) de Seine-et-Marne et Yvelines, souvent exclus si on favorise
    uniquement Paris/92/93/94."""
    if len(df) <= _MAX_SEG:
        return df
    if 'code_departement' not in df.columns:
        return df.sample(_MAX_SEG, random_state=42)

    MIN_PAR_DEPT = 8_000   # minimum garanti par département
    parts, pool_indices = [], []

    for _, grp in df.groupby('code_departement'):
        take    = min(MIN_PAR_DEPT, len(grp))
        sampled = grp.sample(take, random_state=42)
        parts.append(sampled)
        reste   = grp.index.difference(sampled.index)
        pool_indices.extend(reste.tolist())

    budget_restant = _MAX_SEG - sum(len(p) for p in parts)
    if budget_restant > 0 and pool_indices:
        pool  = df.loc[pool_indices]
        extra = pool.sample(min(budget_restant, len(pool)), random_state=42)
        parts.append(extra)

    return pd.concat(parts)


def _noeuds_depuis_paths(df):
    """Calcule les nœuds de jonction depuis les chemins déjà affichés.
    Garantit que chaque point visible a ses lignes correspondantes sur la carte."""
    from collections import Counter
    pts = []
    for path in df['path']:
        try:
            coords = [[float(c[0]), float(c[1])] for c in path]
            if len(coords) >= 2:
                pts.append((round(coords[0][0], 5), round(coords[0][1], 5)))
                pts.append((round(coords[-1][0], 5), round(coords[-1][1], 5)))
        except Exception:
            pass
    cnt  = Counter(pts)
    junc = [(lng, lat, deg) for (lng, lat), deg in cnt.items() if deg >= 3]
    return pd.DataFrame(junc, columns=['lng', 'lat', 'degree']) if junc else None


@st.cache_data(show_spinner="Chargement du réseau électrique…")
def _charger_reseau():
    def _slim(p):
        if not isinstance(p, list) or len(p) < 2:
            return p
        return [p[0], p[-1]] if len(p) <= 4 else [p[0], p[len(p) // 2], p[-1]]

    def _load_nodes(df_sampled):
        # Priorité : nœuds du réseau complet (pipeline) → degrés réels non biaisés
        # Fallback : nœuds calculés depuis les segments affichés (sampling biaise les degrés)
        if os.path.exists(CHEMIN_NOEUDS):
            return pd.read_parquet(CHEMIN_NOEUDS)
        return _noeuds_depuis_paths(df_sampled)

    if os.path.exists(CHEMIN_PDK_SL):
        df    = pd.read_parquet(CHEMIN_PDK_SL)
        df    = _sous_echantillon(df)
        nodes = _load_nodes(df)
        _init_db(df, nodes)
        return df, nodes

    if os.path.exists(CHEMIN_PDK):
        df = pd.read_parquet(CHEMIN_PDK)
        df['path'] = df['path'].apply(_slim)
        df = df[[c for c in _COLS_PDK if c in df.columns]]
        df = _sous_echantillon(df)
        df.to_parquet(CHEMIN_PDK_SL, index=False)
        nodes = _load_nodes(df)
        _init_db(df, nodes)
        return df, nodes

    if not os.path.exists(CHEMIN_OPT):
        return None, None

    gdf = gpd.read_file(CHEMIN_OPT)

    def _path(geom):
        try:
            c = (list(geom.coords) if geom.geom_type == 'LineString'
                 else list(geom.geoms[0].coords))
            if len(c) < 2:
                return []
            pts = [c[0], c[-1]] if len(c) <= 4 else [c[0], c[len(c) // 2], c[-1]]
            return [[round(x, 5), round(y, 5)] for x, y in pts]
        except Exception:
            return []

    gdf['path'] = gdf.geometry.apply(_path)
    valid = gdf['path'].apply(len) >= 2
    df    = pd.DataFrame(gdf[valid][[c for c in _COLS_PDK if c in gdf.columns]])
    df    = _sous_echantillon(df)
    df.to_parquet(CHEMIN_PDK_SL, index=False)
    nodes = _load_nodes(df)
    _init_db(df, nodes)
    return df, nodes


df_reseau, df_noeuds = _charger_reseau() if PYDECK_OK else (None, None)
nb_total = len(df_reseau) if df_reseau is not None else 0


# ════════════════════════════════════════════════════════════════════════
#  CALCUL COULEURS (vectorisé numpy)
# ════════════════════════════════════════════════════════════════════════
def _appliquer_couleurs(df, year_n):
    annee_r = (df['annee_renovation'].fillna(0).to_numpy().astype(np.int32)
               if 'annee_renovation' in df.columns else np.zeros(len(df), np.int32))
    if 'IFS_base' in df.columns:
        ifs_b = df['IFS_base'].fillna(50).to_numpy().astype(np.float32)
    elif 'IFS' in df.columns:
        ifs_b = df['IFS'].fillna(50).to_numpy().astype(np.float32)
    else:
        ifs_b = np.full(len(df), 50.0, np.float32)

    years   = np.where(annee_r > 0, np.minimum(year_n, annee_r - 1), year_n)
    ifs_eff = np.minimum(100.0, ifs_b * (1.03 ** years))
    ifs_eff[(annee_r > 0) & (annee_r <= year_n)] = 10.0

    niveaux = np.where(ifs_eff >= 75, 'CRITIQUE',
              np.where(ifs_eff >= 50, 'ELEVE',
              np.where(ifs_eff >= 30, 'MODERE', 'FAIBLE')))
    ncolors = np.where(ifs_eff >= 75, '#FF2D00',
              np.where(ifs_eff >= 50, '#FF8C00',
              np.where(ifs_eff >= 30, '#c8a200', '#00a040')))
    nc_code = np.where(ifs_eff >= 75, 3,
              np.where(ifs_eff >= 50, 2,
              np.where(ifs_eff >= 30, 1, 0))).astype(int)

    # Seulement path + champs tooltip + id implicite (index)
    out = pd.DataFrame({
        'path':    df['path'].tolist(),
        '_nc':     nc_code.tolist(),
        '_ifs':    [round(float(v), 1) for v in ifs_eff],
        '_niv':    niveaux.tolist(),
        '_ncol':   ncolors.tolist(),
        '_tr':     df['type_reseau'].fillna('').tolist() if 'type_reseau' in df.columns else [''] * len(df),
    })
    return out


# ════════════════════════════════════════════════════════════════════════
#  CONSTRUCTION DE LA CARTE (plotly Scattermapbox — couleurs garanties)
# ════════════════════════════════════════════════════════════════════════
_NC_COLOR = {0: '#00A040', 1: '#C8A200', 2: '#FF8C00', 3: '#FF2D00'}
_NC_NAME  = {0: 'Sain',    1: 'Vieillissant', 2: 'Degrade', 3: 'Critique'}


def _construire_carte(df_col, df_noeuds=None):
    paths  = df_col['path'].tolist()
    nc_arr = df_col['_nc'].tolist()
    ifs_a  = df_col['_ifs'].tolist()
    niv_a  = df_col['_niv'].tolist()
    tr_a   = df_col['_tr'].tolist()

    # Grouper lon/lat par niveau avec None comme séparateur entre segments
    lons = {k: [] for k in range(4)}
    lats = {k: [] for k in range(4)}
    # Midpoints pour les clics (un point par segment)
    mid_lons, mid_lats, mid_ids, mid_tr, mid_ifs, mid_niv = [], [], [], [], [], []

    for i, (path, nc) in enumerate(zip(paths, nc_arr)):
        try:
            coords = [[float(c[0]), float(c[1])] for c in path]
        except Exception:
            continue
        nc = int(nc)
        for lon, lat in coords:
            lons[nc].append(lon)
            lats[nc].append(lat)
        lons[nc].append(None)
        lats[nc].append(None)
        # Midpoint pour détection de clic
        mid = coords[len(coords) // 2]
        mid_lons.append(mid[0]);  mid_lats.append(mid[1])
        mid_ids.append(i);        mid_tr.append(tr_a[i] or '')
        mid_ifs.append(ifs_a[i]); mid_niv.append(niv_a[i])

    fig = go.Figure()

    # 1. Lignes colorées par niveau
    for nc in range(4):
        if not lons[nc]:
            continue
        fig.add_trace(go.Scattermapbox(
            lon=lons[nc], lat=lats[nc],
            mode='lines',
            line=dict(color=_NC_COLOR[nc], width=2),
            name=_NC_NAME[nc],
            hoverinfo='skip',
            showlegend=False,
        ))

    # 2. Points aux midpoints — capturent les clics (grande zone, quasi-invisible)
    fig.add_trace(go.Scattermapbox(
        lon=mid_lons, lat=mid_lats,
        mode='markers',
        marker=dict(size=22, color='rgba(0,0,0,0)', opacity=0.01),
        customdata=list(zip(mid_ids, mid_tr, mid_ifs, mid_niv)),
        hovertemplate=(
            "<b>%{customdata[1]}</b><br>"
            "IFS %{customdata[2]}<br>"
            "Niveau %{customdata[3]}<extra></extra>"
        ),
        name='segments',
        showlegend=False,
    ))

    # 3. Nœuds réseau (postes et intersections)
    if df_noeuds is not None and not df_noeuds.empty:
        # Postes sources / sous-stations : degré ≥ 6 (réseau complet → vrais nœuds structurels)
        postes = df_noeuds[df_noeuds['degree'] >= 6]
        if not postes.empty:
            fig.add_trace(go.Scattermapbox(
                lon=postes['lng'].tolist(), lat=postes['lat'].tolist(),
                mode='markers',
                marker=dict(size=11, color='#1565C0', opacity=0.90),
                name='Poste / Sous-station',
                hovertemplate="<b>Poste / Sous-station</b><br>Degré : %{customdata}<extra></extra>",
                customdata=postes['degree'].tolist(),
                showlegend=False,
            ))

        # Intersections de câbles : degré 3 (T-junctions), limité à 8 000 pts
        junc = df_noeuds[df_noeuds['degree'] == 3]
        if not junc.empty:
            if len(junc) > 8000:
                junc = junc.sample(8000, random_state=42)
            fig.add_trace(go.Scattermapbox(
                lon=junc['lng'].tolist(), lat=junc['lat'].tolist(),
                mode='markers',
                marker=dict(size=6, color='#777777', opacity=0.65),
                name='Intersection câbles',
                hovertemplate="<b>Intersection câbles</b><br>Degré : %{customdata}<extra></extra>",
                customdata=junc['degree'].tolist(),
                showlegend=False,
            ))


    fig.update_layout(
        mapbox=dict(
            style='carto-positron',
            center=dict(lat=48.72, lon=2.53),
            zoom=9,
        ),
        margin=dict(l=0, r=0, t=0, b=0),
        height=780,
        uirevision='carte',
    )
    return fig


# ════════════════════════════════════════════════════════════════════════
#  PANNEAU D'INFORMATION
# ════════════════════════════════════════════════════════════════════════
def _barre(label, valeur, max_val, couleur):
    pct = min(100, max(0, valeur / max_val * 100)) if max_val else 0
    st.markdown(
        f"<div style='margin:6px 0'>"
        f"<div style='font-size:12px;margin-bottom:3px;color:#333'>{label}</div>"
        f"<div style='background:#e8e8e8;border-radius:4px;height:10px'>"
        f"<div style='width:{pct:.0f}%;height:100%;background:{couleur};"
        f"border-radius:4px'></div></div>"
        f"</div>",
        unsafe_allow_html=True,
    )


def _panel_legende(avec_noeuds=False):
    st.markdown("**Legende**")
    noeuds_html = (
        "<br/><b>Nœuds réseau</b><br/>"
        "<span style='color:#1565C0'>⬤</span> Poste / Sous-station (deg ≥ 6)<br/>"
        "<span style='color:#777777'>●</span> Intersection câbles (deg 3)"
    ) if avec_noeuds else ""
    st.markdown(
        "<div style='font-size:13px;line-height:2.2'>"
        "<b>Tronçons</b><br/>"
        "<span style='color:#00A040'>━</span> Sain &nbsp;(IFS &lt; 30)<br/>"
        "<span style='color:#C8A200'>━</span> Vieillissant &nbsp;(30–50)<br/>"
        "<span style='color:#FF8C00'>━</span> Dégradé &nbsp;(50–75)<br/>"
        "<span style='color:#FF2D00'>━</span> Critique &nbsp;(&gt;75)"
        f"{noeuds_html}"
        "</div>",
        unsafe_allow_html=True,
    )


def _panel_segment(obj, year_n):
    # Lecture depuis SQLite via l'id du segment cliqué
    seg_id = None
    props  = obj.get('properties', obj) if isinstance(obj, dict) else {}

    if 'id' in props:
        seg_id  = int(props['id'])
        db_data = _get_segment(seg_id)
    else:
        db_data = props  # fallback si pas d'id

    # IFS ajusté selon la timeline
    ifs_b   = float(db_data.get('IFS_base', db_data.get('IFS', 50)) or 50)
    ann_r   = int(db_data.get('annee_renovation', 0) or 0)
    yrs     = min(year_n, ann_r - 1) if ann_r > 0 else year_n
    ifs_eff = min(100.0, ifs_b * (1.03 ** yrs))
    if ann_r > 0 and ann_r <= year_n:
        ifs_eff = 10.0

    type_r  = str(db_data.get('type_reseau', props.get('t', 'Inconnu')) or 'Inconnu')
    dept    = str(db_data.get('code_departement', '') or '')
    commune = str(db_data.get('code_commune', '') or '')
    spr     = float(db_data.get('SPR', 0) or 0)
    pop     = float(db_data.get('Pop_Score', 0) or 0)
    erp     = float(db_data.get('ERP_Score', 0) or 0)
    dict_r  = float(db_data.get('Risk_DICT', 0) or 0)
    clc     = float(db_data.get('CLC_Sensibilite', 0) or 0)
    cout    = float(db_data.get('cout_estime', 0) or 0)

    if ifs_eff >= 75:   niveau, ncolor = "CRITIQUE", "#FF2D00"
    elif ifs_eff >= 50: niveau, ncolor = "ELEVE",    "#FF8C00"
    elif ifs_eff >= 30: niveau, ncolor = "MODERE",   "#c8a200"
    else:               niveau, ncolor = "FAIBLE",   "#00a040"

    st.markdown(
        f"<div style='font-size:15px;font-weight:bold'>{type_r}</div>"
        f"<div style='color:{ncolor};font-size:14px;font-weight:bold'>Niveau : {niveau}</div>"
        f"<div style='color:#888;font-size:12px'>Dept. {dept} | Commune {commune}</div>",
        unsafe_allow_html=True,
    )
    st.markdown("---")
    _barre(f"Vétusté IFS ({ifs_eff:.0f}/100)",     ifs_eff, 100, ncolor)
    _barre(f"Priorité SPR ({spr:.0f}/150)",         spr,     150, "#7b2d8b")
    _barre(f"Population desservie ({pop:.0f}/100)", pop,     100, "#2196F3")
    _barre(f"ERP à proximité ({erp:.0f}/100)",      erp,     100, "#e74c3c")
    _barre(f"Risque chantier DICT ({dict_r:.0f}/100)", dict_r, 100, "#f39c12")
    _barre(f"Sensibilité CLC ({clc:.0f}/100)",      clc,     100, "#27ae60")
    st.markdown("---")

    # Coût : affichage adapté à l'ordre de grandeur (k€ ou M€)
    if cout < 0.1:
        cout_str = f"{cout * 1000:.0f} k€"
    elif cout < 1:
        cout_str = f"{cout:.3f} M€  ({cout * 1000:.0f} k€)"
    else:
        cout_str = f"{cout:.2f} M€"

    if ann_r > 0 and ann_r <= year_n:
        renov_str  = f"An {ann_r}"
        renov_note = "✅ Réalisée"
        renov_col  = "#00a040"
    elif ann_r > 0:
        renov_str  = f"An {ann_r}"
        renov_note = "Planifiée"
        renov_col  = "#2196F3"
    else:
        renov_str  = "—"
        renov_note = "Non planifiée"
        renov_col  = "#aaa"

    st.markdown(
        f"<div style='display:flex;gap:12px;margin-top:4px'>"
        f"  <div style='flex:1;background:#f5f5f5;border-radius:8px;padding:10px 12px'>"
        f"    <div style='font-size:11px;color:#888;margin-bottom:3px'>Coût estimé</div>"
        f"    <div style='font-size:16px;font-weight:bold'>{cout_str}</div>"
        f"  </div>"
        f"  <div style='flex:1;background:#f5f5f5;border-radius:8px;padding:10px 12px'>"
        f"    <div style='font-size:11px;color:#888;margin-bottom:3px'>Rénovation</div>"
        f"    <div style='font-size:16px;font-weight:bold'>{renov_str}</div>"
        f"    <div style='font-size:11px;color:{renov_col}'>{renov_note}</div>"
        f"  </div>"
        f"</div>",
        unsafe_allow_html=True,
    )


# ════════════════════════════════════════════════════════════════════════
#  LAYOUT PRINCIPAL
# ════════════════════════════════════════════════════════════════════════
st.markdown(
    f"<h2 style='margin-bottom:0'>Jumeau Numerique — Reseau Electrique IDF 2026</h2>"
    f"<p style='color:#888;margin-top:2px'>{nb_total:,} troncons affichés · "
    "🟢 Sain &nbsp; 🟡 Vieillissant &nbsp; 🟠 Degrade &nbsp; 🔴 Critique</p>",
    unsafe_allow_html=True,
)

@st.fragment
def _section_carte(df_reseau, df_noeuds, timeline):
    """Fragment isolé : seuls les clics carte relancent ce bloc."""
    col_carte, col_info = st.columns([3, 1], gap="medium")
    selected_obj = None

    with col_carte:
        if not PLOTLY_OK:
            st.error("plotly requis : pip install plotly")
        elif df_reseau is not None:
            df_col = _appliquer_couleurs(df_reseau, timeline)
            fig    = _construire_carte(df_col, df_noeuds)
            event  = st.plotly_chart(
                fig,
                use_container_width=True,
                on_select="rerun",
                selection_mode="points",
                config={"scrollZoom": True, "displayModeBar": False},
            )
            if event and hasattr(event, 'selection'):
                sel = event.selection
                try:
                    pts = sel.get('points', []) if isinstance(sel, dict) else getattr(sel, 'points', [])
                except Exception:
                    pts = []
                for pt in pts:
                    try:
                        cd = pt.get('customdata') if isinstance(pt, dict) else getattr(pt, 'customdata', None)
                        if cd and len(cd) >= 4:
                            selected_obj = {'properties': {
                                'id': cd[0], 't': cd[1], 'i': cd[2], 'n': cd[3]
                            }}
                            break
                    except Exception:
                        continue
        else:
            st.info("Lancez une simulation pour afficher la carte.")

    with col_info:
        if selected_obj:
            _panel_segment(selected_obj, timeline)
        else:
            _panel_legende(avec_noeuds=df_noeuds is not None and not df_noeuds.empty)


_section_carte(df_reseau, df_noeuds, timeline)
