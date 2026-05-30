import geopandas as gpd

_CLC_COUT = {
    '111': 2.5, '112': 2.2,
    '121': 2.0, '122': 1.8, '123': 1.8, '124': 1.5,
    '131': 1.2, '132': 1.2, '133': 1.2,
    '141': 1.5, '142': 1.3,
    '211': 0.7, '212': 0.7, '213': 0.7,
    '221': 0.8, '222': 0.8, '223': 0.8,
    '231': 0.7,
    '241': 0.8, '242': 0.8, '243': 0.9, '244': 0.9,
    '311': 0.6, '312': 0.6, '313': 0.6,
    '321': 0.5, '322': 0.5, '323': 0.5, '324': 0.5,
    '331': 0.6, '332': 0.6, '333': 0.6, '334': 0.6, '335': 0.6,
    '411': 1.8, '412': 1.8,
    '421': 1.8, '422': 1.8, '423': 1.8,
    '511': 2.0, '512': 2.0,
    '521': 2.0, '522': 2.0, '523': 2.0,
}
_CLC_COUT_DEFAUT = 1.0

# Coût de pose par km selon le type de réseau (M€/km)
_COUT_BASE = {
    'aerien_bt':      0.5,   # BT aérien  : pose simple sur poteaux
    'souterrain_bt':  1.8,   # BT sout.   : terrassement + remblaiement
    'aerien_hta':     0.8,   # HTA aérien : équipement spécialisé haute tension
    'souterrain_hta': 1.8,   # HTA sout.  : terrassement profond + HTA
}
_COUT_BASE_DEFAUT = 0.5

# Coût minimum de mobilisation par type (M€) — indépendant de la longueur
# Reflète le coût minimum d'une journée d'intervention (équipe + matériel + sécurité)
_COUT_MIN = {
    'aerien_bt':      0.005,  # 5 000 € : petite équipe, travaux simples
    'souterrain_bt':  0.015,  # 15 000 € : engins de terrassement nécessaires
    'aerien_hta':     0.020,  # 20 000 € : équipe HTA spécialisée + consignation
    'souterrain_hta': 0.035,  # 35 000 € : HTA + terrassement profond + balisage
}
_COUT_MIN_DEFAUT = 0.010


def _type_key(t):
    s = str(t).lower()
    if 'souterrain' in s and ('hta' in s or 'moyenne' in s):
        return 'souterrain_hta'
    if 'souterrain' in s:
        return 'souterrain_bt'
    if 'hta' in s or 'moyenne' in s:
        return 'aerien_hta'
    return 'aerien_bt'


def _estimer_cout_clc(gdf_reseau, gdf_clc):
    """Calcule cout_estime (M€) par segment via la jointure CLC.
    Retourne une Series indexée sur gdf_reseau.index, ou None si CLC indisponible."""
    if gdf_clc is None or gdf_clc.empty:
        return None

    col_code = next((c for c in ['CODE_12', 'CODE_18', 'CODE_06', 'CODE_00', 'CODE']
                     if c in gdf_clc.columns), None)
    if col_code is None:
        return None

    print("  Estimation des couts via l'occupation du sol (CLC)...")
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

        code_map    = joined.set_index('index')[col_code].to_dict()
        codes       = gdf_reseau.index.map(code_map).fillna('')
        mult_clc    = codes.map(lambda c: _CLC_COUT.get(str(c)[:3], _CLC_COUT_DEFAUT))
        longueurs   = gdf_reseau.geometry.length / 1000.0  # en km

        if 'type_reseau' in gdf_reseau.columns:
            type_keys   = gdf_reseau['type_reseau'].map(_type_key)
            base        = type_keys.map(lambda k: _COUT_BASE.get(k, _COUT_BASE_DEFAUT))
            cout_min    = type_keys.map(lambda k: _COUT_MIN.get(k, _COUT_MIN_DEFAUT))
        else:
            base     = _COUT_BASE_DEFAUT
            cout_min = _COUT_MIN_DEFAUT

        raw = base * longueurs * mult_clc
        return raw.clip(lower=cout_min)

    except Exception as e:
        print(f"  Jointure CLC couts echouee : {e}")
        return None


def ordonnanceur_budget(df_reseau, budget_max, nuisance_max=None, gdf_clc=None):
    """
    Sélectionne les tronçons à rénover par ordre de priorité SPR décroissant.

    Algorithme glouton vectorisé O(n log n) :
    1. Tri par SPR décroissant — le segment le plus urgent est toujours traité en premier.
    2. Cumsum des coûts → on prend tous les segments jusqu'à épuisement du budget.

    :param budget_max:  Budget annuel disponible (M€)
    :param gdf_clc:     Couche CLC pour estimer les coûts (optionnel si cout_estime absent)
    :return: (df, budget_restant, 0.0, nb_renoves)
    """
    df = df_reseau.copy()

    # ── Calcul des coûts si absents ───────────────────────────────────────────
    if 'cout_estime' not in df.columns:
        couts_clc = _estimer_cout_clc(df, gdf_clc)
        if couts_clc is not None:
            df['cout_estime'] = couts_clc.values
        elif df.geom_type.isin(['LineString', 'MultiLineString']).any():
            if 'type_reseau' in df.columns:
                type_keys = df['type_reseau'].map(_type_key)
                base      = type_keys.map(lambda k: _COUT_BASE.get(k, _COUT_BASE_DEFAUT))
                cout_min  = type_keys.map(lambda k: _COUT_MIN.get(k, _COUT_MIN_DEFAUT))
            else:
                base     = _COUT_BASE_DEFAUT
                cout_min = _COUT_MIN_DEFAUT
            raw = df.geometry.length / 1000.0 * base
            df['cout_estime'] = raw.clip(lower=cout_min)
        else:
            df['cout_estime'] = _COUT_MIN_DEFAUT

    # ── Sélection par SPR décroissant dans la limite du budget ────────────────
    df_sorted = df.sort_values('SPR', ascending=False)
    cum_cout  = df_sorted['cout_estime'].cumsum().values
    mask      = cum_cout <= budget_max

    df['statut_renovation'] = 'En attente'
    df.loc[df_sorted[mask].index, 'statut_renovation'] = 'Renové'

    budget_consomme = float(df_sorted.loc[mask, 'cout_estime'].sum())
    nb_renoves      = int(mask.sum())

    print(f"  Ordonnanceur : {nb_renoves} segments renoves | "
          f"Budget consomme : {budget_consomme:.2f} M€ / {budget_max:.2f} M€")
    return df, budget_max - budget_consomme, 0.0, nb_renoves
