import os
import glob
import sqlite3
import pandas as pd
import geopandas as gpd

try:
    from src.data_prep.cleaning import load_and_reproject, clean_geometry
    from src.scoring.spatial_filters import (
        apply_dict_risk, apply_population_density,
        apply_social_impact, apply_clc_sensitivity,
        compute_centralite_proxy,
    )
    from src.scoring.ifs_calculator import calculate_ifs
    from src.scoring.spr_calculator import calculate_spr
    from src.optimization.scheduler import ordonnanceur_budget
except ModuleNotFoundError:
    from cleaning import load_and_reproject, clean_geometry
    from spatial_filters import (
        apply_dict_risk, apply_population_density,
        apply_social_impact, apply_clc_sensitivity,
        compute_centralite_proxy,
    )
    from ifs_calculator import calculate_ifs
    from spr_calculator import calculate_spr
    from scheduler import ordonnanceur_budget

IDF_DEPTS = {'75', '77', '78', '91', '92', '93', '94', '95'}

_DIR_INTERIM = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "02_interim")
_DB_PATH     = os.path.join(_DIR_INTERIM, "idf_data.db")
_GPKG_PATH   = os.path.join(_DIR_INTERIM, "reseau_idf.gpkg")

# Always precompute this many years for the slider (even if user selects 0)
TIMELINE_MAX_ANNEES = 20
# Maximum segments in the display file
MAX_DISPLAY = 5000


def _from_db(table):
    """Charge une table depuis idf_data.db. Retourne None si indisponible."""
    if not os.path.exists(_DB_PATH):
        return None
    try:
        conn = sqlite3.connect(_DB_PATH)
        df   = pd.read_sql(f"SELECT * FROM {table}", conn)
        conn.close()
        return df if not df.empty else None
    except Exception as e:
        print(f"  ⚠️ DB table '{table}' indisponible : {e}")
        return None


# ── Data loaders ──────────────────────────────────────────────────────────────

def _charger_dict(dossier_raw):
    fichiers = (glob.glob(os.path.join(dossier_raw, "*DICT*.csv")) +
                glob.glob(os.path.join(dossier_raw, "*DT et DICT*.csv")))
    if not fichiers:
        return None
    print("📂 Chargement des données DICT (chantiers)...")
    try:
        df = pd.read_csv(fichiers[0], sep=';', dtype=str, low_memory=False)
        col = 'C04_Code INSEE Chantier'
        if col in df.columns:
            counts = df.groupby(col).size().reset_index(name='nb_chantiers')
            counts.rename(columns={col: 'code_commune'}, inplace=True)
            return counts
    except Exception as e:
        print(f"  ⚠️ Erreur DICT : {e}")
    return None


def _charger_continuite(dossier_raw):
    fichiers = (glob.glob(os.path.join(dossier_raw, "*continuite*.csv")) +
                glob.glob(os.path.join(dossier_raw, "*continuité*.csv")) +
                glob.glob(os.path.join(dossier_raw, "*continuit*.csv")))
    if not fichiers:
        return None
    print("📂 Chargement des indicateurs de continuité d'alimentation...")
    try:
        df = pd.read_csv(fichiers[0], dtype=str)
        df.columns = df.columns.str.strip()
        annee_cols = [c for c in df.columns if c.startswith('aaa')]
        if len(annee_cols) >= 5:
            cols_5ans = annee_cols[-5:]
            for c in cols_5ans:
                df[c] = pd.to_numeric(df[c], errors='coerce')
            df['taux_coupure_5ans'] = df[cols_5ans].mean(axis=1)
        elif annee_cols:
            df[annee_cols[0]] = pd.to_numeric(df[annee_cols[0]], errors='coerce')
            df['taux_coupure_5ans'] = df[annee_cols[0]]
        if 'N° Département' in df.columns and 'taux_coupure_5ans' in df.columns:
            df['code_dept_str'] = df['N° Département'].str.strip().str.zfill(2)
            return df[['code_dept_str', 'taux_coupure_5ans']].dropna()
    except Exception as e:
        print(f"  ⚠️ Erreur continuité : {e}")
    return None


def _charger_icu(dossier_raw):
    fichiers = (glob.glob(os.path.join(dossier_raw, "*icu*.csv")) +
                glob.glob(os.path.join(dossier_raw, "*ICU*.csv")))
    if not fichiers:
        return None
    print("📂 Chargement des indicateurs ICU (chaleur urbaine)...")
    try:
        return pd.read_csv(fichiers[0], dtype={'code_giris': str})
    except Exception as e:
        print(f"  ⚠️ Erreur ICU : {e}")
    return None


def _charger_clc(dossier_raw):
    candidats = [
        os.path.join(dossier_raw, "CLC_RIDF_RGF_SHP", "CLC12", "CLC12_RIDF_RGF.shp"),
        os.path.join(dossier_raw, "CLC_RIDF_RGF_SHP", "CLC06", "CLC06R_RIDF_RGF.shp"),
        os.path.join(dossier_raw, "CLC_RIDF_RGF_SHP", "CLC00", "CLC00R_RIDF_RGF.shp"),
    ]
    for shp in candidats:
        if os.path.exists(shp):
            print(f"📂 Chargement CLC : {os.path.basename(shp)}...")
            try:
                return gpd.read_file(shp)
            except Exception as e:
                print(f"  ⚠️ Erreur CLC : {e}")
    return None


def _charger_population(dossier_raw):
    """Charge la grille INSEE 200m (colonnes lcog_geo + ind uniquement — évite les 2 Go)."""
    fichiers = (glob.glob(os.path.join(dossier_raw, "*ensit*population*.csv")) +
                glob.glob(os.path.join(dossier_raw, "*population*.csv")))
    if not fichiers:
        return None
    print("📂 Chargement densité population (grille INSEE 200m)...")
    try:
        df = pd.read_csv(fichiers[0], sep=',', usecols=['lcog_geo', 'ind'], dtype=str)
        IDF_PREFIXES = ('75', '77', '78', '91', '92', '93', '94', '95')
        mask = df['lcog_geo'].astype(str).str.startswith(IDF_PREFIXES, na=False)
        df_idf = df[mask].copy()
        df_idf['ind'] = pd.to_numeric(df_idf['ind'], errors='coerce').fillna(0)
        print(f"  ✅ {len(df_idf):,} cellules de population IDF chargées.")
        return df_idf
    except Exception as e:
        print(f"  ⚠️ Erreur population : {e}")
    return None


def _charger_reseau_idf(fichier, type_reseau_label):
    """
    Charge un fichier réseau CSV en filtrant sur l'IDF AVANT de parser les géométries.
    Méthode deux passes : d'abord code_departement, puis seulement les lignes IDF.
    """
    from shapely.geometry import shape
    from shapely import wkt
    import json

    print(f"    Lecture rapide de {os.path.basename(fichier)}...")
    df_depts = pd.read_csv(fichier, sep=',', usecols=['code_departement'], dtype=str)
    if 'code_departement' not in df_depts.columns:
        print("    ⚠️ Colonne 'code_departement' absente — fichier ignoré.")
        return None

    idx_idf = df_depts.index[df_depts['code_departement'].isin(IDF_DEPTS)].tolist()
    if not idx_idf:
        print("    ⚠️ Aucun segment IDF trouvé.")
        return None

    print(f"    {len(idx_idf):,} segments IDF détectés — chargement...")
    all_rows = set(range(1, len(df_depts) + 1))
    rows_to_skip = all_rows - {i + 1 for i in idx_idf}
    df_raw = pd.read_csv(fichier, sep=',', skiprows=rows_to_skip, header=0, dtype=str)

    # Restore column names when skiprows drops the original header row
    if df_raw.columns[0] != 'geometry':
        cols = pd.read_csv(fichier, sep=',', nrows=0).columns.tolist()
        df_raw.columns = cols[:len(df_raw.columns)]

    if df_raw.empty:
        print("    ⚠️ DataFrame IDF vide après filtrage.")
        return None

    print(f"    Parsing géométrie de {len(df_raw):,} segments IDF...")

    def _parse(g):
        if pd.isna(g):
            return None
        try:
            return wkt.loads(str(g))
        except Exception:
            try:
                return shape(json.loads(str(g)))
            except Exception:
                return None

    df_raw['geometry'] = df_raw['geometry'].apply(_parse)
    gdf = gpd.GeoDataFrame(df_raw, geometry='geometry', crs="EPSG:4326")
    gdf = gdf.to_crs("EPSG:2154")   # Lambert 93 AVANT clean_geometry (filtre en mètres)
    gdf = clean_geometry(gdf)
    gdf['type_reseau'] = type_reseau_label

    cols_utiles = [c for c in ['geometry', 'type_reseau', 'code_departement',
                                'code_commune', 'code_iris', 'nom_commune'] if c in gdf.columns]
    print(f"    ✅ {len(gdf):,} segments IDF retenus.")
    return gdf[cols_utiles]


def _charger_noeuds(dossier_raw, pattern, label):
    fichiers = (glob.glob(os.path.join(dossier_raw, f"*{pattern}*.csv")) +
                glob.glob(os.path.join(dossier_raw, f"*{pattern}*.geojson")))
    if not fichiers:
        return None
    print(f"📂 Chargement {label}...")
    try:
        gdf = load_and_reproject(fichiers[0])
        return clean_geometry(gdf)
    except Exception as e:
        print(f"  ⚠️ Erreur {label} : {e}")
    return None


# ── Timeline precomputation ───────────────────────────────────────────────────

def _precomputer_timeline(gdf_base, budget_annuel, weights):
    """
    Simule TIMELINE_MAX_ANNEES années de rénovation et tague chaque segment avec
    l'année où il sera rénové (annee_renovation = 0 si jamais rénové dans la fenêtre).

    Retourne (df_avec_annees, chart_data).
    Optimisation : la géométrie est exclue de la boucle (SPR + ordonnanceur ne l'utilisent
    pas quand cout_estime est déjà calculé) → copies ~10× plus rapides.
    """
    print(f"  ⏳ Pré-calcul de {TIMELINE_MAX_ANNEES} années de simulation...")

    # Travailler sur un DataFrame plat (sans géométrie) — beaucoup plus rapide à copier
    geom_col = gdf_base.geometry.name if hasattr(gdf_base, 'geometry') else 'geometry'
    df = pd.DataFrame(gdf_base.drop(columns=[geom_col], errors='ignore'))
    df['annee_renovation'] = 0
    df['IFS_base']         = df['IFS'].copy()

    risque_opti  = [round(float(df['IFS'].mean()), 1)]
    risque_inact = [round(float(df['IFS'].mean()), 1)]

    for annee in range(1, TIMELINE_MAX_ANNEES + 1):
        en_attente_mask = df['annee_renovation'] == 0
        df_pending = df[en_attente_mask].copy()
        if df_pending.empty:
            risque_opti.append(risque_opti[-1])
            risque_inact.append(round(min(100.0, risque_inact[-1] * 1.03), 1))
            continue

        df_pending = calculate_spr(df_pending, weights=weights)
        df_pending, _, _, _ = ordonnanceur_budget(
            df_pending, budget_max=budget_annuel,
            nuisance_max=len(df_pending), gdf_clc=None  # cout_estime déjà présent
        )
        nouveaux = df_pending[df_pending['statut_renovation'] == 'Renové'].index
        df.loc[nouveaux, 'annee_renovation'] = annee

        still_pending = df['annee_renovation'] == 0
        df.loc[still_pending, 'IFS'] = (df.loc[still_pending, 'IFS'] * 1.03).clip(upper=100)

        risque_opti.append(round(float(df.loc[still_pending, 'IFS'].mean()), 1)
                           if still_pending.any() else 10.0)
        risque_inact.append(round(min(100.0, risque_inact[-1] * 1.03), 1))
        print(f"    An {annee:2d} : {int(nouveaux.size):,} renovations | "
              f"IFS moy restant = {risque_opti[-1]:.1f}")

    chart_data = {
        'annees':          list(range(TIMELINE_MAX_ANNEES + 1)),
        'risque_optimise': risque_opti,
        'risque_inaction': risque_inact,
    }
    print(f"  ✅ Timeline : {int((df['annee_renovation'] > 0).sum()):,} segments planifiés.")
    return df, chart_data


# ── Main pipeline ─────────────────────────────────────────────────────────────

def executer_pipeline_complet(budget=50.0, crisis_type="Aucune", weights=None):
    """
    Exécute le pipeline complet du jumeau numérique.

    La simulation temporelle est toujours pré-calculée sur 15 ans (TIMELINE_MAX_ANNEES).
    Le slider du dashboard pilote l'affichage sans relancer le pipeline.

    :param budget:      Budget annuel en M€
    :param crisis_type: "Aucune" | "Canicule (Stress Thermique)" | "Crue (Inondation)"
    :param weights:     Dict des pondérations SPR {W_vet, W_pop, W_erp, W_dict, W_cent, W_clc}
    :return: Dict {gdf_reseau, graphe, kpis, chart_data}
    """
    print("\n" + "=" * 60)
    print("DEMARRAGE DU JUMEAU NUMERIQUE - PIPELINE COMPLET")
    print("=" * 60 + "\n")

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    dossier_raw       = os.path.join(BASE_DIR, "data", "01_raw")
    dossier_interim   = os.path.join(BASE_DIR, "data", "02_interim")
    dossier_processed = os.path.join(BASE_DIR, "data", "03_processed")
    os.makedirs(dossier_interim,   exist_ok=True)
    os.makedirs(dossier_processed, exist_ok=True)

    # ── Données contextuelles ────────────────────────────────────────────────
    # ERP : GeoPackage (base de données) en priorité, CSV en fallback
    gdf_erp = None
    if os.path.exists(_GPKG_PATH):
        try:
            gdf_erp = gpd.read_file(_GPKG_PATH, layer='erp')
            print(f"\n--- ERP chargé depuis la base de données ({len(gdf_erp):,} points) ---")
        except Exception as e:
            print(f"  ⚠️ ERP DB indisponible ({e}) — lecture CSV...")
    if gdf_erp is None:
        fichiers_erp = glob.glob(os.path.join(dossier_raw, "*Zone sensible ERP*.csv"))
        if fichiers_erp:
            print("\n--- Chargement ERP (CSV) ---")
            try:
                gdf_erp = load_and_reproject(fichiers_erp[0])
                gdf_erp = clean_geometry(gdf_erp)
            except Exception as e:
                print(f"  ⚠️ ERP non chargé : {e}")

    # Données tabulaires : base de données en priorité, fichiers CSV en fallback
    _d = _from_db('dict_chantiers')
    dict_par_commune = _d if _d is not None else _charger_dict(dossier_raw)
    _c = _from_db('continuite')
    df_continuite    = _c if _c is not None else _charger_continuite(dossier_raw)
    df_icu           = _charger_icu(dossier_raw)
    gdf_clc          = _charger_clc(dossier_raw)
    _p = _from_db('population_idf')
    df_pop           = _p if _p is not None else _charger_population(dossier_raw)

    # Poteaux/postes : non utilisés (graphe NetworkX désactivé)

    # ── PHASE 1 : Réseau ─────────────────────────────────────────────────────
    gdf_reseau = None

    # Priorité : GeoPackage pré-construit (build_database.py)
    if os.path.exists(_GPKG_PATH):
        print(f"\nPHASE 1 : Chargement du réseau depuis la base de données...")
        try:
            gdf_reseau = gpd.read_file(_GPKG_PATH, layer='reseau')
            print(f"  ✅ {len(gdf_reseau):,} segments chargés depuis DB")
            print(f"  Types : {gdf_reseau['type_reseau'].value_counts().to_dict()}")
        except Exception as e:
            print(f"  ⚠️ Réseau DB indisponible ({e}) — lecture CSV...")
            gdf_reseau = None

    # Fallback : lecture directe des 4 CSV (lent)
    if gdf_reseau is None:
        print("\nPHASE 1 : Chargement du reseau complet (4 fichiers CSV)...")
        fichiers_reseau = sorted(
            glob.glob(os.path.join(dossier_raw, "*Basse Tension*.csv")) +
            glob.glob(os.path.join(dossier_raw, "*moyenne tension*.csv"))
        )
        if not fichiers_reseau:
            print(f"ERREUR : Aucun fichier reseau et aucune DB dans {dossier_raw}.")
            return None

        def _type_reseau(nom):
            n = nom.lower()
            if 'souterrain' in n:
                return 'souterrain_bt' if 'basse' in n else 'souterrain_hta'
            if 'moyenne' in n or 'hta' in n:
                return 'aerien_hta'
            return 'aerien_bt'

        gdfs_idf = []
        for fichier in fichiers_reseau:
            nom = os.path.basename(fichier)
            print(f"\n  Fichier : {nom}")
            try:
                gdf_idf = _charger_reseau_idf(fichier, _type_reseau(nom))
                if gdf_idf is not None and not gdf_idf.empty:
                    gdfs_idf.append(gdf_idf)
            except Exception as e:
                print(f"  ERREUR : {e}")

        if not gdfs_idf:
            print("ERREUR : Aucun segment IDF trouve.")
            return None

        gdf_reseau = gpd.GeoDataFrame(pd.concat(gdfs_idf, ignore_index=True), crs=gdfs_idf[0].crs)
        del gdfs_idf
        print(f"\n  Reseau IDF total : {len(gdf_reseau):,} troncons")
        print(f"  Types : {gdf_reseau['type_reseau'].value_counts().to_dict()}")

    # Export intermédiaire supprimé — non utilisé par le dashboard (gain de temps)

    # ── PHASE 2 : Analyse spatiale ───────────────────────────────────────────
    print("\nPHASE 2 : Analyse spatiale et scoring...")

    gdf_reseau = apply_dict_risk(gdf_reseau, dict_par_commune=dict_par_commune)
    gdf_reseau = apply_population_density(gdf_reseau, df_pop)
    gdf_reseau = apply_social_impact(gdf_reseau, gdf_erp)
    gdf_reseau = apply_clc_sensitivity(gdf_reseau, gdf_clc)
    gdf_reseau['Centralite'] = compute_centralite_proxy(gdf_reseau)

    # ── PHASE 3 : IFS + stress tests ─────────────────────────────────────────
    print("\nPHASE 3 : Calcul IFS et stress tests...")
    gdf_reseau['IFS'] = calculate_ifs(gdf_reseau, df_continuite=df_continuite)

    if crisis_type == "Canicule (Stress Thermique)" and df_icu is not None:
        try:
            from stress_tests import apply_canicule_stress
            gdf_reseau = apply_canicule_stress(gdf_reseau, df_icu)
        except Exception as e:
            print(f"  ⚠️ Stress canicule non applique : {e}")

    # ── PHASE 4 : SPR ────────────────────────────────────────────────────────
    print("\nPHASE 4 : Calcul du score SPR (6 criteres)...")

    # Remap old weight keys to new ones (backward compat with sidebar sliders)
    if weights:
        weights = {
            'W_vet':  weights.get('W_vet',  0.25),
            'W_pop':  weights.get('W_pop',  weights.get('W_soc', 0.20)),
            'W_erp':  weights.get('W_erp',  0.15),
            'W_dict': weights.get('W_dict', weights.get('W_ext', 0.15)),
            'W_cent': weights.get('W_cent', 0.15),
            'W_clc':  weights.get('W_clc',  0.10),
        }

    gdf_reseau = calculate_spr(gdf_reseau, weights=weights)

    # ── PHASE 5 : Graphe NetworkX (optionnel — non utilisé par le dashboard) ───
    # Désactivé par défaut : itère sur 4.3M nœuds/arêtes et ralentit le pipeline.
    # Réactiver si on veut les métriques de graphe (composantes connexes, etc.).
    graphe = None
    # graphe = build_graph_from_lines(gdf_reseau, gdf_poteaux=gdf_poteaux, gdf_postes=gdf_postes)

    # ── PHASE 6 : Ordonnancement budgetaire (année 0) ────────────────────────
    print("\nPHASE 6 : Ordonnanceur budgetaire (annee 0)...")
    gdf_optimise, budget_restant, _, nb_renoves = ordonnanceur_budget(
        gdf_reseau.copy(), budget_max=budget,
        nuisance_max=len(gdf_reseau), gdf_clc=gdf_clc
    )
    print(f"  {nb_renoves} renovations | Reste : {budget_restant:.2f} M€")

    # Propager cout_estime calculé en Phase 6 vers gdf_reseau
    # → la timeline ne relancera pas la jointure CLC 15 fois
    if 'cout_estime' in gdf_optimise.columns:
        gdf_reseau['cout_estime'] = gdf_optimise['cout_estime'].reindex(
            gdf_reseau.index
        ).values

    # ── PHASE 7 : Timeline pré-calculée ─────────────────────────────────────
    print("\nPHASE 7 : Pre-calcul de la simulation 15 ans...")
    gdf_timeline, chart_data = _precomputer_timeline(gdf_reseau.copy(), budget, weights)

    # Merge annee_renovation back into gdf_optimise
    if 'annee_renovation' in gdf_timeline.columns:
        gdf_optimise['annee_renovation'] = gdf_timeline['annee_renovation'].reindex(
            gdf_optimise.index
        ).fillna(0).astype(int).values
        gdf_optimise['IFS_base'] = gdf_timeline['IFS_base'].reindex(
            gdf_optimise.index
        ).fillna(gdf_optimise['IFS']).values

    # ── PHASE 8 : KPIs ───────────────────────────────────────────────────────
    print("\nPHASE 8 : Calcul des KPIs et export...")

    budget_consomme    = round(budget - budget_restant, 2)
    ifs_non_renoves    = gdf_optimise[gdf_optimise['statut_renovation'] != 'Renové']['IFS'].mean()
    resilience         = round(float(max(0, min(100, 100 - ifs_non_renoves))), 1)

    nb_erp_securises = 0
    if gdf_erp is not None and not gdf_erp.empty:
        gdf_renoves = gdf_optimise[gdf_optimise['statut_renovation'] == 'Renové']
        if not gdf_renoves.empty:
            try:
                buf = gdf_renoves.geometry.buffer(150).union_all()
                nb_erp_securises = int(gdf_erp[gdf_erp.geometry.intersects(buf)].shape[0])
            except Exception:
                nb_erp_securises = 0

    # ── Export complet ───────────────────────────────────────────────────────
    cols_export = [c for c in [
        'geometry', 'SPR', 'IFS', 'IFS_base', 'Pop_Score', 'ERP_Score',
        'Risk_DICT', 'Centralite', 'CLC_Sensibilite',
        'statut_renovation', 'annee_renovation',
        'cout_estime', 'code_commune', 'code_departement', 'type_reseau',
    ] if c in gdf_optimise.columns]

    # GeoJSON supprimés (non lus par le dashboard, coût ~3 min chacun)

    # ── Export pydeck (réseau complet — coordonnées pré-extraites) ────────────
    print("  Export pydeck (réseau complet + nœuds)...")
    try:
        gdf_pdk = gdf_optimise[cols_export].to_crs("EPSG:4326").copy()

        def _extract_path(geom):
            # Garde uniquement début + fin (+ point médian si > 4 pts)
            # → réduit la taille JSON de 20-50× sans perte visuelle à zoom 9-12
            try:
                if geom.geom_type == 'LineString':
                    c = list(geom.coords)
                elif geom.geom_type == 'MultiLineString':
                    c = list(geom.geoms[0].coords)
                else:
                    return []
                if len(c) < 2:
                    return []
                pts = [c[0], c[-1]] if len(c) <= 4 else [c[0], c[len(c)//2], c[-1]]
                return [[round(x, 5), round(y, 5)] for x, y in pts]
            except Exception:
                return []

        gdf_pdk['path'] = gdf_pdk.geometry.apply(_extract_path)
        valid_mask = gdf_pdk['path'].apply(len) >= 2
        cols_pdk = [c for c in cols_export if c != 'geometry'] + ['path']
        df_pdk = pd.DataFrame(gdf_pdk[valid_mask][cols_pdk])
        df_pdk.to_parquet(os.path.join(dossier_processed, "reseau_pydeck.parquet"), index=False)
        print(f"  ✅ {len(df_pdk):,} tronçons → reseau_pydeck.parquet")

        # Nœuds : extraire les extrémités de chaque segment, compter le degré
        from collections import Counter
        pts = []
        for geom in gdf_pdk[valid_mask].geometry:
            try:
                lines = [geom] if geom.geom_type == 'LineString' else list(geom.geoms)
                for line in lines:
                    c = list(line.coords)
                    if len(c) >= 2:
                        pts.append((round(c[0][0], 5), round(c[0][1], 5)))
                        pts.append((round(c[-1][0], 5), round(c[-1][1], 5)))
            except Exception:
                pass
        cnt = Counter(pts)
        junctions = [(lng, lat, deg) for (lng, lat), deg in cnt.items() if deg >= 3]
        if junctions:
            df_nodes = pd.DataFrame(junctions, columns=['lng', 'lat', 'degree'])
            df_nodes.to_parquet(
                os.path.join(dossier_processed, "noeuds_pydeck.parquet"), index=False
            )
            print(f"  ✅ {len(df_nodes):,} nœuds (jonctions/postes) → noeuds_pydeck.parquet")
    except Exception as _pdk_err:
        print(f"  ⚠️ Export pydeck échoué : {_pdk_err}")
    print("\nPIPELINE TERMINE AVEC SUCCES !\n")

    return {
        'gdf_reseau':  gdf_optimise.to_crs("EPSG:4326"),
        'graphe':      graphe,
        'kpis': {
            'resilience':       resilience,
            'nb_renoves':       nb_renoves,
            'nb_erp_securises': nb_erp_securises,
            'budget_consomme':  budget_consomme,
            'budget_total':     budget,
        },
        'chart_data': chart_data,
    }


if __name__ == "__main__":
    executer_pipeline_complet()
