import geopandas as gpd
import pandas as pd
import os
import json
from shapely import wkt
from shapely.geometry import shape

TARGET_CRS = "EPSG:2154"  # Lambert 93 (Projection officielle française métrique)

def parse_geometry(geom_str):
    """Tente de convertir une chaîne de texte (WKT ou GeoJSON) en géométrie Shapely."""
    if pd.isna(geom_str):
        return None
    try:
        # Essai 1 : Format WKT (ex: "LINESTRING (2.3 48.8, 2.4 48.9)")
        return wkt.loads(str(geom_str))
    except Exception:
        try:
            # Essai 2 : Format GeoJSON (ex: '{"type": "LineString", "coordinates": [...]}')
            return shape(json.loads(str(geom_str)))
        except Exception:
            return None

def load_and_reproject(file_path):
    """
    Charge un fichier SIG géospatial et le reprojette systématiquement en Lambert 93.
    Indispensable pour calculer des buffers et des longueurs en mètres de manière précise.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"❌ Le fichier {file_path} est introuvable.")
        
    print(f"📂 Chargement de {os.path.basename(file_path)}...")
    
    if file_path.lower().endswith('.csv'):
        # Lecture du CSV en laissant Pandas deviner le séparateur (virgule ou point-virgule)
        df = pd.read_csv(file_path, sep=None, engine='python')
        
        if 'geometry' in df.columns:
            print("🪄 Conversion de la colonne texte 'geometry' en formes spatiales...")
            df['geometry'] = df['geometry'].apply(parse_geometry)
            gdf = gpd.GeoDataFrame(df, geometry='geometry')
            gdf.set_crs("EPSG:4326", inplace=True) # Généralement du GPS (WGS84) dans les CSV
            
        elif 'Longitude' in df.columns and 'Latitude' in df.columns:
            print("📍 Création de points géographiques à partir de Longitude/Latitude...")
            # On nettoie les valeurs nulles éventuelles pour éviter les crashs
            df = df.dropna(subset=['Longitude', 'Latitude'])
            gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df['Longitude'], df['Latitude']))
            gdf.set_crs("EPSG:4326", inplace=True)
        else:
            raise ValueError("Ce CSV n'a ni colonne 'geometry', ni 'Longitude'/'Latitude'.")
    else:
        gdf = gpd.read_file(file_path)
    
    if gdf.crs is None:
        print("⚠️ CRS manquant. Assignation par défaut en WGS84 (EPSG:4326) avant reprojection.")
        gdf.set_crs("EPSG:4326", inplace=True)
        
    if gdf.crs != TARGET_CRS:
        print(f"🔄 Reprojection en cours : {gdf.crs} -> {TARGET_CRS}...")
        gdf = gdf.to_crs(TARGET_CRS)
    else:
        print(f"✅ Le fichier est déjà correctement projeté en {TARGET_CRS}.")
        
    return gdf

def clean_geometry(gdf):
    """
    Nettoie le GeoDataFrame : géométries nulles, vides, invalides, doublons et micro-segments.
    """
    initial_count = len(gdf)
    
    # 1. Suppression des géométries manquantes ou vides
    gdf = gdf.dropna(subset=['geometry'])
    gdf = gdf[~gdf.geometry.is_empty]
    
    # 2. Suppression des géométries topologiquement invalides
    gdf = gdf[gdf.is_valid]
    
    # 3. Suppression des doublons parfaits (très fréquents dans l'Open Data)
    gdf = gdf.drop_duplicates(subset=['geometry'])
    
    # 4. Suppression des micro-segments (< 1 cm) pour éviter les bugs dans le graphe
    if not gdf.empty and gdf.geom_type.isin(['LineString', 'MultiLineString']).any():
        mask_lignes = gdf.geom_type.isin(['LineString', 'MultiLineString'])
        mask_valides = (gdf.geometry.length >= 0.01)
        # On garde les points/polygones, ET les lignes qui font au moins 1 cm
        gdf = gdf[~mask_lignes | mask_valides]
        
    final_count = len(gdf)
    print(f"🧹 Nettoyage topologique : {initial_count - final_count} anomalies (doublons/invalides) supprimées.")
    return gdf.copy()