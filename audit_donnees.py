import os
import glob
import geopandas as gpd
import pandas as pd

def auditer_dossier():
    # On cherche dans "data" et "data/01_raw" au cas où
    dossiers_a_chercher = ["data", os.path.join("data", "01_raw")]
    fichiers_trouves = []
    
    print("📁 Diagnostic : Contenu brut des dossiers...")
    for dossier in dossiers_a_chercher:
        if os.path.exists(dossier):
            fichiers = os.listdir(dossier)
            print(f" - Dans '{dossier}' : {fichiers if fichiers else 'Dossier vide'}")
        else:
            print(f" - Le dossier '{dossier}' n'existe pas.")
    print("-" * 60)

    for dossier in dossiers_a_chercher:
        fichiers_trouves.extend(glob.glob(os.path.join(dossier, "*.geojson")))
        fichiers_trouves.extend(glob.glob(os.path.join(dossier, "*.shp")))
        fichiers_trouves.extend(glob.glob(os.path.join(dossier, "*.zip")))
        fichiers_trouves.extend(glob.glob(os.path.join(dossier, "*.csv")))
        
    # Déduplication au cas où
    fichiers_trouves = list(set(fichiers_trouves))
        
    if not fichiers_trouves:
        print("⚠️ Aucun fichier .geojson, .shp, .zip ou .csv trouvé pour l'audit.")
        return
        
    print(f"🔎 {len(fichiers_trouves)} fichier(s) trouvé(s) ! Voici l'audit :\n" + "="*60)
    
    for fichier in fichiers_trouves:
        print(f"📄 Fichier : {os.path.basename(fichier)}")
        try:
            if fichier.endswith('.csv'):
                # Lecture spéciale pour les CSV (on utilise sep=None pour détecter automatiquement les virgules ou points-virgules)
                df = pd.read_csv(fichier, nrows=5, sep=None, engine='python')
                print(f"   ✅ Statut : Tableau CSV lu avec succès")
                print(f"   📊 Colonnes détectées : {', '.join(df.columns.tolist())}")
            else:
                gdf = gpd.read_file(fichier, rows=5) # On lit 5 lignes pour aller très vite
                print(f"   ✅ Statut : Fichier spatial valide et exploitable")
                print(f"   🌐 Projection (CRS) : {gdf.crs}")
                print(f"   📊 Colonnes détectées : {', '.join(gdf.columns.tolist()[:10])}...")
        except Exception as e:
            print(f"   ❌ Erreur de lecture : {e}")
        print("-" * 60)

if __name__ == "__main__":
    auditer_dossier()