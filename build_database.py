"""
build_database.py — Ingestion unique des données brutes IDF.

Exécutez ce script UNE SEULE FOIS avant de lancer le pipeline :
    python build_database.py

Produit :
    data/02_interim/idf_data.db     — SQLite (continuité, population, DICT)
    data/02_interim/reseau_idf.gpkg — GeoPackage (réseau électrique + ERP)

Le pipeline détecte automatiquement ces fichiers et les utilise à la place
des CSV bruts → chargement 10× plus rapide lors des simulations suivantes.
"""
import os
import glob
import json
import sqlite3
import pandas as pd
import geopandas as gpd
from shapely import wkt
from shapely.geometry import shape

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
DIR_RAW     = os.path.join(BASE_DIR, "data", "01_raw")
DIR_INTERIM = os.path.join(BASE_DIR, "data", "02_interim")
DB_PATH     = os.path.join(DIR_INTERIM, "idf_data.db")
GPKG_PATH   = os.path.join(DIR_INTERIM, "reseau_idf.gpkg")

IDF_DEPTS = {'75', '77', '78', '91', '92', '93', '94', '95'}


def _parse_geom(g):
    if pd.isna(g):
        return None
    try:
        return wkt.loads(str(g))
    except Exception:
        try:
            return shape(json.loads(str(g)))
        except Exception:
            return None


# ── Table 1 : continuité d'alimentation ─────────────────────────────────────

def build_continuite(conn):
    print("\n[1/5] Indicateurs de continuité d'alimentation...")
    fichiers = (glob.glob(os.path.join(DIR_RAW, "*continuite*.csv")) +
                glob.glob(os.path.join(DIR_RAW, "*continuité*.csv")) +
                glob.glob(os.path.join(DIR_RAW, "*continuit*.csv")))
    if not fichiers:
        print("  ⚠️  Fichier non trouvé — ignoré.")
        return

    df = pd.read_csv(fichiers[0], dtype=str)
    df.columns = df.columns.str.strip()
    annee_cols = [c for c in df.columns if c.startswith('aaa')]

    if len(annee_cols) >= 5:
        for c in annee_cols[-5:]:
            df[c] = pd.to_numeric(df[c], errors='coerce')
        df['taux_coupure_5ans'] = df[annee_cols[-5:]].mean(axis=1)
    elif annee_cols:
        df[annee_cols[0]] = pd.to_numeric(df[annee_cols[0]], errors='coerce')
        df['taux_coupure_5ans'] = df[annee_cols[0]]
    else:
        print("  ⚠️  Aucune colonne 'aaa*' trouvée.")
        return

    df['code_dept_str'] = df['N° Département'].str.strip().str.zfill(2)
    result = df[['code_dept_str', 'taux_coupure_5ans']].dropna()

    result.to_sql('continuite', conn, if_exists='replace', index=False)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cont ON continuite(code_dept_str)")
    conn.commit()
    print(f"  ✅ {len(result)} départements → table 'continuite'")


# ── Table 2 : densité de population (agrégée par commune) ───────────────────

def build_population(conn):
    print("\n[2/5] Densité de population INSEE (grille 200m)...")
    fichiers = (glob.glob(os.path.join(DIR_RAW, "*ensit*population*.csv")) +
                glob.glob(os.path.join(DIR_RAW, "*population*.csv")))
    if not fichiers:
        print("  ⚠️  Fichier non trouvé — ignoré.")
        return

    print(f"  Lecture de {os.path.basename(fichiers[0])} (peut être long)...")
    df = pd.read_csv(fichiers[0], sep=',', usecols=['lcog_geo', 'ind'], dtype=str)

    idf_prefixes = tuple(IDF_DEPTS)
    mask = df['lcog_geo'].astype(str).str.startswith(idf_prefixes, na=False)
    df_idf = df[mask].copy()
    df_idf['ind'] = pd.to_numeric(df_idf['ind'], errors='coerce').fillna(0)
    df_idf['lcog_geo'] = df_idf['lcog_geo'].astype(str).str.zfill(5)

    # Agrégation par commune (lcog_geo = code commune pour ce fichier)
    pop_idf = df_idf.groupby('lcog_geo')['ind'].sum().reset_index()

    pop_idf.to_sql('population_idf', conn, if_exists='replace', index=False)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pop ON population_idf(lcog_geo)")
    conn.commit()
    print(f"  ✅ {len(pop_idf)} communes IDF → table 'population_idf'")


# ── Table 3 : chantiers DT/DICT ──────────────────────────────────────────────

def build_dict(conn):
    print("\n[3/5] Chantiers DT/DICT...")
    fichiers = (glob.glob(os.path.join(DIR_RAW, "*DICT*.csv")) +
                glob.glob(os.path.join(DIR_RAW, "*DT et DICT*.csv")))
    if not fichiers:
        print("  ⚠️  Fichier non trouvé — ignoré.")
        return

    df = pd.read_csv(fichiers[0], sep=';', dtype=str, low_memory=False)
    col = 'C04_Code INSEE Chantier'
    if col not in df.columns:
        candidates = [c for c in df.columns if 'insee' in c.lower() or 'commune' in c.lower()]
        if candidates:
            col = candidates[0]
            print(f"  Colonne utilisée : {col}")
        else:
            print(f"  ⚠️  Colonne code commune introuvable. Colonnes : {list(df.columns[:6])}")
            return

    counts = df.groupby(col).size().reset_index(name='nb_chantiers')
    counts.rename(columns={col: 'code_commune'}, inplace=True)

    counts.to_sql('dict_chantiers', conn, if_exists='replace', index=False)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dict ON dict_chantiers(code_commune)")
    conn.commit()
    print(f"  ✅ {len(counts)} communes avec chantiers → table 'dict_chantiers'")


# ── Couche 1 : réseau électrique IDF ─────────────────────────────────────────

def build_reseau():
    print("\n[4/5] Réseau électrique IDF (4 fichiers CSV → GeoPackage)...")

    def _type_reseau(nom):
        n = nom.lower()
        if 'souterrain' in n:
            return 'souterrain_bt' if 'basse' in n else 'souterrain_hta'
        if 'moyenne' in n or 'hta' in n:
            return 'aerien_hta'
        return 'aerien_bt'

    fichiers = sorted(
        glob.glob(os.path.join(DIR_RAW, "*Basse Tension*.csv")) +
        glob.glob(os.path.join(DIR_RAW, "*moyenne tension*.csv"))
    )
    if not fichiers:
        print(f"  ⚠️  Aucun fichier réseau trouvé dans {DIR_RAW}")
        return

    gdfs = []
    for f in fichiers:
        nom   = os.path.basename(f)
        label = _type_reseau(nom)
        print(f"\n  Traitement : {nom}")
        print(f"  Type détecté : {label}")

        # Passe 1 : identifier les lignes IDF uniquement
        df_depts = pd.read_csv(f, usecols=['code_departement'], dtype=str)
        idx_idf  = df_depts.index[df_depts['code_departement'].isin(IDF_DEPTS)].tolist()
        if not idx_idf:
            print(f"  ⚠️  Aucun segment IDF dans ce fichier — ignoré.")
            continue
        print(f"  {len(idx_idf):,} segments IDF sur {len(df_depts):,} total")

        # Passe 2 : charger seulement les lignes IDF
        all_rows = set(range(1, len(df_depts) + 1))
        skip     = all_rows - {i + 1 for i in idx_idf}
        df_raw   = pd.read_csv(f, skiprows=skip, header=0, dtype=str)

        if df_raw.columns[0] != 'geometry':
            cols = pd.read_csv(f, nrows=0).columns.tolist()
            df_raw.columns = cols[:len(df_raw.columns)]

        print(f"  Parsing géométries...")
        df_raw['geometry'] = df_raw['geometry'].apply(_parse_geom)

        gdf = gpd.GeoDataFrame(df_raw, geometry='geometry', crs="EPSG:4326")
        gdf = gdf.to_crs("EPSG:2154")
        gdf = gdf[~gdf.geometry.isna() & gdf.geometry.is_valid]

        # Supprimer les micro-segments (< 1 cm)
        if gdf.geom_type.isin(['LineString', 'MultiLineString']).any():
            gdf = gdf[gdf.geometry.length >= 0.01]

        gdf['type_reseau'] = label
        cols_keep = [c for c in ['geometry', 'type_reseau', 'code_departement',
                                  'code_commune', 'code_iris'] if c in gdf.columns]
        gdfs.append(gdf[cols_keep])
        print(f"  ✅ {len(gdf):,} segments valides")

    if not gdfs:
        print("  ⚠️  Aucun segment IDF — GeoPackage réseau non créé.")
        return

    gdf_all = gpd.GeoDataFrame(pd.concat(gdfs, ignore_index=True), crs="EPSG:2154")
    print(f"\n  Réseau IDF total : {len(gdf_all):,} segments")
    print(f"  Répartition par type :")
    for t, n in gdf_all['type_reseau'].value_counts().items():
        print(f"    {t:25s} : {n:>8,}")

    print(f"\n  Sauvegarde GeoPackage (peut être long)...")
    gdf_all.to_file(GPKG_PATH, layer='reseau', driver="GPKG")
    print(f"  ✅ Réseau → {GPKG_PATH} (layer='reseau')")


# ── Couche 2 : ERP ────────────────────────────────────────────────────────────

def build_erp():
    print("\n[5/5] Établissements Recevant du Public (ERP)...")
    fichiers = glob.glob(os.path.join(DIR_RAW, "*Zone sensible ERP*.csv"))
    if not fichiers:
        print("  ⚠️  Fichier ERP non trouvé — ignoré.")
        return

    try:
        df = pd.read_csv(fichiers[0], sep=';', dtype=str, low_memory=False)
        df.columns = df.columns.str.strip()

        # Utiliser Lambert X/Y (déjà en EPSG:2154) — plus précis que Lon/Lat
        if 'Lambert X' in df.columns and 'Lambert Y' in df.columns:
            df['Lambert X'] = pd.to_numeric(df['Lambert X'], errors='coerce')
            df['Lambert Y'] = pd.to_numeric(df['Lambert Y'], errors='coerce')
            df = df.dropna(subset=['Lambert X', 'Lambert Y'])
            gdf = gpd.GeoDataFrame(
                df,
                geometry=gpd.points_from_xy(df['Lambert X'], df['Lambert Y']),
                crs="EPSG:2154"
            )
        elif 'Longitude' in df.columns and 'Latitude' in df.columns:
            df['Longitude'] = pd.to_numeric(df['Longitude'], errors='coerce')
            df['Latitude']  = pd.to_numeric(df['Latitude'],  errors='coerce')
            df = df.dropna(subset=['Longitude', 'Latitude'])
            gdf = gpd.GeoDataFrame(
                df,
                geometry=gpd.points_from_xy(df['Longitude'], df['Latitude']),
                crs="EPSG:4326"
            ).to_crs("EPSG:2154")
        else:
            print(f"  ⚠️  Colonnes géométriques introuvables.")
            print(f"       Colonnes disponibles : {list(df.columns[:10])}")
            return

        gdf = gdf[~gdf.geometry.isna() & gdf.geometry.is_valid]

        # Garder uniquement les colonnes utiles pour le scoring ERP
        cols_utiles = [c for c in ['geometry', 'Domaine', 'Sous-domaine'] if c in gdf.columns]
        gdf = gdf[cols_utiles]

        gdf.to_file(GPKG_PATH, layer='erp', driver="GPKG")
        print(f"  ✅ {len(gdf):,} ERP → {GPKG_PATH} (layer='erp')")

    except Exception as e:
        print(f"  ⚠️  ERP non chargé : {e}")
        import traceback
        traceback.print_exc()


# ── Point d'entrée ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("CONSTRUCTION DE LA BASE DE DONNÉES IDF")
    print("=" * 60)

    os.makedirs(DIR_INTERIM, exist_ok=True)

    # Supprimer l'ancienne DB pour forcer une reconstruction complète
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"Ancien fichier supprimé : {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    try:
        build_continuite(conn)
        build_population(conn)
        build_dict(conn)
    finally:
        conn.close()

    build_reseau()
    build_erp()

    print("\n" + "=" * 60)
    print("BASE DE DONNÉES CONSTRUITE AVEC SUCCÈS")
    print(f"  SQLite     : {DB_PATH}")
    print(f"  GeoPackage : {GPKG_PATH}")
    print("  → Lancez maintenant : streamlit run app.py")
    print("=" * 60)
