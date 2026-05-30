import os
import glob
from src.data_prep.cleaning import load_and_reproject, clean_geometry

def tester_donnees():
    dossier_raw = os.path.join("data", "01_raw")
    
    # Cherche tous les fichiers geojson ou shapefile dans le dossier
    fichiers = glob.glob(os.path.join(dossier_raw, "*.geojson")) + \
               glob.glob(os.path.join(dossier_raw, "*.shp"))
               
    if not fichiers:
        print(f"⚠️ Aucun fichier .geojson ou .shp trouvé dans {dossier_raw}.")
        print("Veuillez y glisser vos fichiers de données Enedis ou autres.")
        return
        
    # On prend le premier fichier trouvé pour le test
    fichier_test = fichiers[0]
    print(f"🚀 Lancement du test sur le fichier : {os.path.basename(fichier_test)}\n")
    
    try:
        # 1. Chargement et reprojection (EPSG:2154)
        gdf = load_and_reproject(fichier_test)
        
        # 2. Nettoyage des géométries
        gdf = clean_geometry(gdf)
        
        # 3. Affichage d'un résumé de la donnée
        print("\n📊 --- RÉSUMÉ DES DONNÉES ---")
        print(f"Nombre total de lignes (entités) : {len(gdf)}")
        print(f"Système de coordonnées final : {gdf.crs}")
        print(f"Colonnes disponibles : {', '.join(gdf.columns.tolist())}")
        print("----------------------------\n")
        
    except Exception as e:
        print(f"❌ Une erreur est survenue lors du traitement : {e}")

if __name__ == "__main__":
    tester_donnees()