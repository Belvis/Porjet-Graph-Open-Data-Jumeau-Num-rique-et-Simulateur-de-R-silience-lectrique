def calculate_spr(df_reseau, weights=None):
    """
    Calcule le Score de Priorité de Rénovation (SPR) — formule à 6 critères.

    SPR = (IFS×W_vet + Pop_Score×W_pop + ERP_Score×W_erp
           + Risk_DICT×W_dict + Centralite×W_cent + CLC_Sensibilite×W_clc)
           × facteur_type

    facteur_type : HTA/moyenne tension = 1.3, BT = 1.0 (HTA alimente des quartiers entiers)

    Toutes les composantes sont sur [0, 100].
    SPR résultant ∈ [0, 200] (le ×1.3 peut dépasser 100 pour les segments HTA critiques).
    """
    if weights is None:
        weights = {
            "W_vet":  0.25,   # Vétusté structurelle (IFS)
            "W_pop":  0.20,   # Densité de population desservie
            "W_erp":  0.15,   # Impact ERP (hôpitaux > EHPAD > écoles)
            "W_dict": 0.15,   # Risque chantiers DICT à proximité
            "W_cent": 0.15,   # Centralité réseau / impact en cascade
            "W_clc":  0.10,   # Sensibilité de l'occupation du sol
        }

    defaults = {
        'IFS':            50.0,
        'Pop_Score':      10.0,
        'ERP_Score':       0.0,
        'Risk_DICT':       0.0,
        'Centralite':     50.0,
        'CLC_Sensibilite': 50.0,
    }
    for col, val in defaults.items():
        if col not in df_reseau.columns:
            print(f"  ⚠️ SPR : colonne '{col}' absente → valeur par défaut {val}.")
            df_reseau[col] = val

    spr_brut = (
        df_reseau['IFS']             * weights.get('W_vet',  0.25) +
        df_reseau['Pop_Score']       * weights.get('W_pop',  0.20) +
        df_reseau['ERP_Score']       * weights.get('W_erp',  0.15) +
        df_reseau['Risk_DICT']       * weights.get('W_dict', 0.15) +
        df_reseau['Centralite']      * weights.get('W_cent', 0.15) +
        df_reseau['CLC_Sensibilite'] * weights.get('W_clc',  0.10)
    )

    # HTA segments are priority-multiplied because their failure cascades to entire districts
    if 'type_reseau' in df_reseau.columns:
        facteur = df_reseau['type_reseau'].map(
            lambda t: 1.3 if any(k in str(t).lower() for k in ('hta', 'moyenne', 'souterrain')) else 1.0
        )
    else:
        facteur = 1.0

    df_reseau['SPR'] = (spr_brut * facteur).clip(0, 200)
    df_reseau = df_reseau.sort_values('SPR', ascending=False)
    print("✅ SPR (6 critères + facteur type) calculé et réseau trié par priorité.")
    return df_reseau
