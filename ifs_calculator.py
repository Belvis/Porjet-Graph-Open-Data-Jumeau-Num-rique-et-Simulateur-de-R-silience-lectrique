import numpy as np
import pandas as pd

_IDF_DEPTS = {'75', '77', '78', '91', '92', '93', '94', '95'}


def calculate_ifs(df_reseau, df_continuite=None,
                  col_coupures='taux_coupure_5ans', col_age='age_materiel'):
    """
    Calcule l'Indicateur de Fatigue Structurelle (IFS) — score 0 (neuf) à 100 (critique).

    Formule : IFS = 0.55 × score_age + 0.45 × score_coupures

    score_age :
        Si col_age présent dans les données → utilisé directement (données réelles).
        Sinon → estimé depuis le TYPE DE RÉSEAU comme le temps écoulé depuis la
        dernière intervention (cycle de vie = 15 ans), modulé par la longueur (±25 %).

        Hypothèse : une ligne est "vieille" si elle n'a pas été rénovée depuis 15 ans.
        Les bases représentent le temps DEPUIS LA DERNIÈRE RÉNOVATION estimée :
            - BT aérien      : ~11 ans  (rarement touché, faible budget maintenance)
            - HTA aérien     : ~9 ans   (plus critique, reçoit plus d'attention)
            - BT souterrain  : ~7 ans   (durable mais maintenance régulière)
            - HTA souterrain : ~5 ans   (priorité haute, interventions fréquentes)
        Résultat clippé [1, 15] ans → divisé par 15 → score [0, 100].

        Effet : dans un même département, un aerien_bt long (≈92/100) se distingue
        clairement d'un souterrain_hta court (≈25/100) → 4 couleurs visibles partout.

    score_coupures :
        Normalisé par le percentile 90 des départements (SAIFI ou minutes, les deux
        sont gérés). Les 10 % les pires départements → score 100.
        Garantit une diversité de couleurs même si tous les départements IDF
        sont bien notés en absolu.
    """
    df = df_reseau.copy()

    # ── Taux de coupure réel par département ──────────────────────────────────
    if df_continuite is not None and 'code_departement' in df.columns:
        dept_str = df['code_departement'].astype(str).str.zfill(2)
        taux_map = df_continuite.set_index('code_dept_str')['taux_coupure_5ans'].to_dict()
        df[col_coupures] = dept_str.map(taux_map)

        manquants = df[col_coupures].isna().sum()
        if manquants:
            print(f"  IFS : {manquants} segments sans taux de coupure → mediane IDF.")
            idf_median = df_continuite[
                df_continuite['code_dept_str'].isin(_IDF_DEPTS)
            ]['taux_coupure_5ans'].median()
            df[col_coupures] = df[col_coupures].fillna(idf_median)

        # P90 calculé uniquement sur les départements IDF présents dans les données.
        # Normaliser sur la France entière donnerait un score < 20 pour tous les segments
        # IDF car l'IDF est 10× meilleure que la moyenne nationale → vert partout.
        # En normalisant entre les 8 départements IDF, Seine-et-Marne (pires coupures IDF)
        # obtient 100 et Val-de-Marne (quasi zéro) obtient ~12 → diversité de couleurs.
        depts_presents = df_continuite[df_continuite['code_dept_str'].isin(_IDF_DEPTS)]
        p90 = depts_presents['taux_coupure_5ans'].quantile(0.90) if not depts_presents.empty else 0
        if p90 == 0:
            p90 = df_continuite['taux_coupure_5ans'].quantile(0.90)  # fallback national
        if p90 > 0:
            df[col_coupures] = (df[col_coupures] / p90 * 100).clip(0, 100)
        else:
            df[col_coupures] = 0.0

    elif col_coupures not in df.columns:
        print("  IFS : taux de coupure non disponible → valeurs simulees (graine fixe).")
        # Graine fixe : résultats déterministes entre deux lancements de pipeline
        rng = np.random.default_rng(seed=42)
        raw = rng.uniform(0.01, 0.08, len(df))
        max_v = raw.max()
        df[col_coupures] = (raw / max_v * 100) if max_v > 0 else 50.0

    # ── Âge du matériel ───────────────────────────────────────────────────────
    if col_age not in df.columns:
        if df.geom_type.isin(['LineString', 'MultiLineString']).any():
            longueur = df.geometry.length.clip(lower=1)

            # Base d'ancienneté par type de réseau (années)
            # Ancienneté typique du réseau IDF par technologie :
            if 'type_reseau' in df.columns:
                t = df['type_reseau'].astype(str).str.lower()
                # Temps estimé depuis la dernière rénovation (années)
                base_age = pd.Series(8.0, index=df.index)           # défaut générique
                base_age[t.str.contains('aerien_bt',      na=False)] = 11.0
                base_age[t.str.contains('souterrain_bt',  na=False)] = 7.0
                base_age[t.str.contains('aerien_hta',     na=False)] = 9.0
                base_age[t.str.contains('souterrain_hta', na=False)] = 5.0
                mask_hta = t.str.contains('hta|moyenne', na=False) & ~t.str.contains('souterrain', na=False)
                base_age[mask_hta & (base_age == 8.0)] = 9.0
            else:
                base_age = pd.Series(8.0, index=df.index)

            # Modulateur longueur : les segments longs tendent à être plus anciens.
            # Plage : ×0.75 à ×1.25 autour de la base.
            p90_len = longueur.quantile(0.90)
            if p90_len > 0:
                length_factor = (
                    0.75 + 0.50 * np.log1p(longueur) / np.log1p(p90_len)
                ).clip(0.75, 1.25)
            else:
                length_factor = pd.Series(1.0, index=df.index)

            df[col_age] = (base_age * length_factor).clip(1, 15).round(1)
        else:
            df[col_age] = np.random.default_rng(42).integers(10, 40, len(df))

    # ── Calcul IFS ────────────────────────────────────────────────────────────
    duree_vie_max = 15  # cycle de rénovation IDF : ligne "vieille" après 15 ans sans travaux
    score_age      = (df[col_age] / duree_vie_max * 100).clip(0, 100)
    score_coupures = df[col_coupures].clip(0, 100)

    ifs = (score_age * 0.55) + (score_coupures * 0.45)
    ifs = np.clip(ifs, 0, 100)

    print(f"  IFS : age moy={score_age.mean():.1f} | coupures moy={score_coupures.mean():.1f} "
          f"| IFS moy={ifs.mean():.1f} (range {ifs.min():.0f}-{ifs.max():.0f})")
    return ifs
