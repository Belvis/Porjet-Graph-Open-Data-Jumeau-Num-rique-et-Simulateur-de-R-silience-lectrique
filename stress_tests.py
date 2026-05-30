"""
Module de stress tests climatiques.

Canicule : amplifie l'IFS des segments situés dans des zones à fort indice de chaleur
urbaine (iuhi) selon les données ICU. La jointure se fait par département (code
extrait des 2 premiers chiffres de code_giris).
"""

import numpy as np


def apply_canicule_stress(gdf_reseau, df_icu, col_iuhi='iuhi', amplification=1.25):
    """
    Augmente l'IFS des segments électriques dans les zones de forte chaleur urbaine.

    Méthode : les 2 premiers chiffres de code_giris correspondent au département INSEE.
    On calcule le coefficient de chaleur moyen par département et on l'applique à l'IFS.

    :param gdf_reseau: GeoDataFrame du réseau (doit avoir 'IFS' et 'code_departement').
    :param df_icu: DataFrame des indicateurs ICU (doit avoir 'code_giris' et col_iuhi).
    :param col_iuhi: Nom de la colonne d'indice de chaleur (défaut : 'iuhi').
    :param amplification: Facteur max d'amplification de l'IFS (défaut : 1.25 = +25 %).
    :return: GeoDataFrame avec IFS recalibré.
    """
    print("🌡️ Application du stress test Canicule (ICU)...")

    if col_iuhi not in df_icu.columns:
        print(f"  ⚠️ Colonne '{col_iuhi}' absente du fichier ICU → stress test ignoré.")
        return gdf_reseau

    if 'code_departement' not in gdf_reseau.columns:
        print("  ⚠️ 'code_departement' absent du réseau → stress test ignoré.")
        return gdf_reseau

    # Extraction du département depuis code_giris (2 premiers chiffres, zéro-padded)
    df_icu = df_icu.copy()
    df_icu['code_giris'] = df_icu['code_giris'].astype(str).str.zfill(7)
    df_icu['dept_icu'] = df_icu['code_giris'].str[:2]
    df_icu[col_iuhi] = df_icu[col_iuhi].apply(lambda x: float(x) if str(x).replace('.', '', 1).lstrip('-').isdigit() else np.nan)

    # Score de chaleur normalisé par département (0 → 1)
    iuhi_par_dept = df_icu.groupby('dept_icu')[col_iuhi].mean()
    iuhi_min, iuhi_max = iuhi_par_dept.min(), iuhi_par_dept.max()
    if iuhi_max == iuhi_min:
        print("  ⚠️ Indice ICU uniforme → stress test sans effet.")
        return gdf_reseau

    iuhi_norm = (iuhi_par_dept - iuhi_min) / (iuhi_max - iuhi_min)

    # Coefficient d'amplification : entre 1.0 (froid) et amplification (chaud)
    coeff_par_dept = 1.0 + iuhi_norm * (amplification - 1.0)

    # Application au réseau
    dept_reseau = gdf_reseau['code_departement'].astype(str).str.zfill(2)
    coefficients = dept_reseau.map(coeff_par_dept).fillna(1.0)

    gdf_reseau = gdf_reseau.copy()
    gdf_reseau['IFS'] = (gdf_reseau['IFS'] * coefficients).clip(upper=100)

    nb_touches = int((coefficients > 1.0).sum())
    print(f"  🔥 {nb_touches} segments impactés par la canicule (IFS amplifié jusqu'à ×{amplification}).")
    return gdf_reseau
