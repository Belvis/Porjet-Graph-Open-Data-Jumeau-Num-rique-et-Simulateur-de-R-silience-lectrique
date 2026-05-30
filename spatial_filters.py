import pandas as pd
import geopandas as gpd

# CLC code → sensitivity score (0-100).
# Urban areas have the highest sensitivity (disruption affects most people).
# Natural areas have the lowest.
_CLC_SENSIBILITE = {
    '111': 95, '112': 90,
    '121': 80, '122': 75, '123': 70, '124': 65,
    '141': 70, '142': 65,
    '211': 30, '212': 30, '213': 30,
    '221': 25, '222': 25, '223': 25,
    '231': 25,
    '241': 28, '242': 28, '243': 32, '244': 32,
    '311': 15, '312': 15, '313': 15,
    '321': 10, '322': 10, '323': 10, '324': 10,
    '331': 12, '332': 12, '333': 12, '334': 12, '335': 12,
    '411': 35, '412': 35,
    '421': 35, '422': 35, '423': 35,
    '511': 30, '512': 30,
    '521': 30, '522': 30, '523': 30,
}

# ERP sub-domain → weight (higher = more critical if power fails)
_ERP_POIDS = {
    'D1': 100,   # Santé : hôpitaux, cliniques, urgences
    'D2': 90,    # Santé : centres de soins spécialisés
    'D3': 75,    # Action sociale : EHPAD, personnes âgées, handicap
    'D4': 60,    # Protection de l'enfance
    'C1': 55,    # Enseignement primaire (maternelle, élémentaire)
    'C2': 50,    # Enseignement secondaire
    'C3': 45,    # Enseignement supérieur
    'F': 40,     # Transports (gares, aéroports)
    'A': 20,     # Services aux particuliers
    'B': 15,     # Commerces
}


def apply_dict_risk(gdf_reseau, gdf_dict=None, dict_par_commune=None, buffer_meters=50):
    """
    Calcule le risque externe DICT (0-100).

    Mode 1 (préféré) : jointure spatiale avec buffer de buffer_meters mètres.
    Mode 2 (fallback) : jointure par code_commune, densité de chantiers normalisée.
    """
    print("🔍 Analyse DICT : détection des chantiers à proximité...")
    gdf_reseau = gdf_reseau.copy()
    gdf_reseau['Risk_DICT'] = 0.0

    if gdf_dict is not None and not gdf_dict.empty:
        reseau_buf = gdf_reseau.copy()
        reseau_buf['geometry'] = reseau_buf.geometry.buffer(buffer_meters)
        intersections = gpd.sjoin(gdf_dict, reseau_buf, how='inner', predicate='intersects')
        chantiers = intersections.groupby('index_right').size()
        gdf_reseau['Risk_DICT'] = gdf_reseau.index.map(chantiers).fillna(0)
        gdf_reseau['Risk_DICT'] = (gdf_reseau['Risk_DICT'] * 20).clip(upper=100)
        print(f"  ✅ DICT spatial : {int((gdf_reseau['Risk_DICT'] > 0).sum())} segments à risque.")
        return gdf_reseau

    if dict_par_commune is not None and not dict_par_commune.empty and 'code_commune' in gdf_reseau.columns:
        dict_par_commune = dict_par_commune.copy()
        dict_par_commune['code_commune'] = dict_par_commune['code_commune'].astype(str)
        gdf_reseau['code_commune'] = gdf_reseau['code_commune'].astype(str)

        # Density = chantiers per km of network in the commune → more meaningful than raw count
        longueur_commune = (
            gdf_reseau.groupby('code_commune')['geometry']
            .apply(lambda g: g.length.sum() / 1000.0)
            .reset_index(name='km_reseau')
        )
        dict_enrichi = dict_par_commune.merge(longueur_commune, on='code_commune', how='left')
        dict_enrichi['km_reseau'] = dict_enrichi['km_reseau'].fillna(1.0).clip(lower=0.1)
        dict_enrichi['densite_chantiers'] = dict_enrichi['nb_chantiers'] / dict_enrichi['km_reseau']

        # Normalize density to 0-100
        d_max = dict_enrichi['densite_chantiers'].max()
        if d_max > 0:
            dict_enrichi['Risk_DICT'] = (dict_enrichi['densite_chantiers'] / d_max * 100).clip(0, 100)
        else:
            dict_enrichi['Risk_DICT'] = 0.0

        merged = gdf_reseau.merge(
            dict_enrichi[['code_commune', 'Risk_DICT']],
            on='code_commune', how='left', suffixes=('', '_new')
        )
        gdf_reseau['Risk_DICT'] = merged['Risk_DICT_new'].fillna(0.0).values
        nb_risque = int((gdf_reseau['Risk_DICT'] > 0).sum())
        print(f"  ✅ DICT commune (densité/km) : {nb_risque} segments à risque.")
        return gdf_reseau

    print("  ⚠️ Aucune donnée DICT disponible → Risk_DICT = 0.")
    return gdf_reseau


def apply_population_density(gdf_reseau, df_pop=None):
    """
    Calcule le Pop_Score (0-100) depuis la grille INSEE 200m.

    Agrégation par commune (lcog_geo → code_commune) : rapide et suffisamment précis
    pour prioriser les zones denses vs rurales à l'échelle du réseau IDF.
    """
    print("👥 Calcul de la densité de population...")
    gdf_reseau = gdf_reseau.copy()
    gdf_reseau['Pop_Score'] = 10.0   # base minimale (zone habitée)

    if df_pop is None or df_pop.empty:
        print("  ⚠️ Données INSEE absentes → Pop_Score minimal.")
        return gdf_reseau

    if 'lcog_geo' not in df_pop.columns or 'ind' not in df_pop.columns:
        print("  ⚠️ Colonnes 'lcog_geo'/'ind' absentes du fichier population.")
        return gdf_reseau

    if 'code_commune' not in gdf_reseau.columns:
        print("  ⚠️ 'code_commune' absent du réseau → Pop_Score minimal.")
        return gdf_reseau

    df_pop = df_pop.copy()
    df_pop['ind'] = pd.to_numeric(df_pop['ind'], errors='coerce').fillna(0)
    df_pop['lcog_geo'] = df_pop['lcog_geo'].astype(str).str.zfill(5)

    pop_commune = df_pop.groupby('lcog_geo')['ind'].sum().reset_index()
    pop_commune.columns = ['code_commune', 'pop_totale']

    gdf_reseau['_code_comm_str'] = gdf_reseau['code_commune'].astype(str).str.zfill(5)
    merged = gdf_reseau.merge(pop_commune, left_on='_code_comm_str', right_on='code_commune',
                              how='left', suffixes=('', '_pop'))
    pop_vals = pd.to_numeric(merged['pop_totale'], errors='coerce').fillna(0)

    pop_max = pop_vals.max()
    if pop_max > 0:
        gdf_reseau['Pop_Score'] = (10 + pop_vals / pop_max * 90).clip(0, 100).values
    gdf_reseau = gdf_reseau.drop(columns=['_code_comm_str'], errors='ignore')

    nb_renseignes = int((gdf_reseau['Pop_Score'] > 10.0).sum())
    print(f"  ✅ Pop_Score calculé : {nb_renseignes:,} segments dans des communes renseignées.")
    return gdf_reseau


def apply_social_impact(gdf_reseau, gdf_erp=None, buffer_meters=150):
    """
    Calcule l'ERP_Score (0-100) : pondération par type d'établissement.

    Hôpital (D1) = 100 pts, EHPAD (D3) = 75 pts, École primaire (C1) = 55 pts…
    Un segment peut recevoir le score du ERP le plus critique dans son rayon.
    """
    print(f"🏥 Analyse sociale : ERP dans un rayon de {buffer_meters} m...")
    gdf_reseau = gdf_reseau.copy()
    gdf_reseau['ERP_Score'] = 0.0

    if gdf_erp is None or gdf_erp.empty:
        print("  ⚠️ Données ERP absentes → ERP_Score = 0.")
        return gdf_reseau

    gdf_erp = gdf_erp.copy()

    # Assign weight by Sous-domaine code
    if 'Sous-domaine' in gdf_erp.columns:
        gdf_erp['erp_weight'] = gdf_erp['Sous-domaine'].astype(str).map(
            lambda s: next((v for k, v in _ERP_POIDS.items() if s.startswith(k)), 25)
        )
    elif 'Domaine' in gdf_erp.columns:
        gdf_erp['erp_weight'] = gdf_erp['Domaine'].astype(str).map(
            lambda d: next((v for k, v in _ERP_POIDS.items() if d.startswith(k)), 25)
        )
    else:
        gdf_erp['erp_weight'] = 25

    reseau_buf = gdf_reseau.copy()
    reseau_buf['geometry'] = reseau_buf.geometry.buffer(buffer_meters)

    intersections = gpd.sjoin(gdf_erp[['geometry', 'erp_weight']], reseau_buf[['geometry']],
                              how='inner', predicate='intersects')

    if not intersections.empty:
        erp_score = intersections.groupby('index_right')['erp_weight'].max()
        gdf_reseau['ERP_Score'] = (
            erp_score.reindex(gdf_reseau.index).fillna(0).clip(0, 100)
        )

    nb_avec_erp = int((gdf_reseau['ERP_Score'] > 0).sum())
    print(f"  ✅ {nb_avec_erp:,} segments à proximité d'un ERP.")
    return gdf_reseau


def apply_clc_sensitivity(gdf_reseau, gdf_clc=None):
    """
    Calcule la CLC_Sensibilite (0-100) : sensibilité de l'occupation du sol.

    Une coupure en zone urbaine dense (CLC 111/112) est plus impactante qu'en forêt.
    Utilisé dans le SPR pour prioriser les segments dans les zones à fort impact social.
    """
    print("🗺️ Calcul de la sensibilité CLC (occupation du sol)...")
    gdf_reseau = gdf_reseau.copy()
    gdf_reseau['CLC_Sensibilite'] = 50.0   # default: zone semi-urbaine

    if gdf_clc is None or gdf_clc.empty:
        print("  ⚠️ CLC absent → sensibilité par défaut 50.")
        return gdf_reseau

    col_code = next(
        (c for c in ['CODE_12', 'CODE_18', 'CODE_06', 'CODE_00', 'CODE'] if c in gdf_clc.columns),
        None
    )
    if col_code is None:
        return gdf_reseau

    try:
        if gdf_clc.crs != gdf_reseau.crs:
            gdf_clc = gdf_clc.to_crs(gdf_reseau.crs)

        centroides = gdf_reseau[['geometry']].copy()
        centroides['geometry'] = gdf_reseau.geometry.centroid
        centroides = centroides.reset_index()

        joined = gpd.sjoin(
            centroides, gdf_clc[[col_code, 'geometry']],
            how='left', predicate='within'
        ).drop_duplicates(subset='index')

        code_map = joined.set_index('index')[col_code].to_dict()
        codes = gdf_reseau.index.map(code_map).fillna('')
        gdf_reseau['CLC_Sensibilite'] = codes.map(
            lambda c: _CLC_SENSIBILITE.get(str(c)[:3], 50)
        ).values
        print(f"  ✅ CLC_Sensibilite calculée pour {int((gdf_reseau['CLC_Sensibilite'] != 50).sum()):,} segments.")
    except Exception as e:
        print(f"  ⚠️ Jointure CLC sensibilité échouée : {e}")

    return gdf_reseau


def compute_centralite_proxy(gdf_reseau):
    """
    Proxy de centralité réseau sans construction de graphe complet.

    Logique :
    - Segments HTA/moyenne tension → centralité haute (85) : ils alimentent des quartiers entiers.
    - Segments BT souterrains → centralité intermédiaire haute (65) : plus critiques à remplacer.
    - Segments BT aériens → centralité proportionnelle à la longueur (10-55) :
      un segment plus long dessert plus de foyers.

    Résultat normalisé 0-100.
    """
    print("🕸️ Calcul de la centralité réseau (proxy)...")
    centralite = pd.Series(50.0, index=gdf_reseau.index, dtype=float)

    if 'type_reseau' not in gdf_reseau.columns:
        return centralite

    t = gdf_reseau['type_reseau'].astype(str).str.lower()
    hta_mask = t.str.contains('hta|moyenne', na=False)
    sout_bt_mask = (~hta_mask) & t.str.contains('souterrain', na=False)
    aerien_bt_mask = (~hta_mask) & (~sout_bt_mask)

    centralite[hta_mask] = 85.0
    centralite[sout_bt_mask] = 65.0

    if aerien_bt_mask.any():
        lengths = gdf_reseau.loc[aerien_bt_mask, 'geometry'].length
        len_max = lengths.max()
        if len_max > 0:
            centralite[aerien_bt_mask] = (10 + lengths / len_max * 45).clip(10, 55)

    print(f"  ✅ Centralité : {int(hta_mask.sum())} HTA=85 | {int(sout_bt_mask.sum())} BT sout.=65 | "
          f"{int(aerien_bt_mask.sum())} BT aér.=10-55")
    return centralite
