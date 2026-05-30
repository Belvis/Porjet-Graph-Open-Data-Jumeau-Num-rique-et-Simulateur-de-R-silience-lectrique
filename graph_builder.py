import networkx as nx
from shapely.geometry import LineString, Point


def _snap(coord, tolerance):
    """Arrondit une coordonnée sur la grille de tolérance (snapping)."""
    if tolerance <= 0:
        return coord
    return (round(coord[0] / tolerance) * tolerance,
            round(coord[1] / tolerance) * tolerance)


def build_graph_from_lines(gdf_lines, tolerance=0.5, gdf_poteaux=None, gdf_postes=None):
    """
    Convertit un GeoDataFrame de lignes en graphe NetworkX.

    - Chaque segment LineString → une arête avec attributs (longueur, SPR, IFS…).
    - Les nœuds sont les extrémités des segments (snappées à la tolérance).
    - Si gdf_poteaux / gdf_postes sont fournis, leurs points deviennent des nœuds
      enrichis avec le type 'poteau' ou 'poste'.

    :param gdf_lines: GeoDataFrame de lignes électriques (Lambert 93).
    :param tolerance: Tolérance de snapping en mètres (0.5 m par défaut).
    :param gdf_poteaux: Points des poteaux électriques (optionnel).
    :param gdf_postes: Points des postes HTA/BT (optionnel).
    :return: Graphe NetworkX non-orienté.
    """
    print(f"🕸️ Construction du graphe (snapping : {tolerance} m)...")
    G = nx.Graph()

    # ── Attributs à récupérer par arête ──────────────────────────────────────
    cols_aretes = ['SPR', 'IFS', 'Risk_DICT', 'Pop_Score',
                   'statut_renovation', 'cout_estime']

    for idx, row in gdf_lines.iterrows():
        geom = row['geometry']

        if isinstance(geom, LineString):
            segments = [geom]
        elif geom is not None and hasattr(geom, 'geoms'):
            segments = list(geom.geoms)
        else:
            continue

        for seg in segments:
            if not isinstance(seg, LineString):
                continue
            coords = list(seg.coords)
            start = _snap(coords[0], tolerance)
            end = _snap(coords[-1], tolerance)

            attrs = {'length': seg.length, 'id': idx}
            for col in cols_aretes:
                if col in gdf_lines.columns:
                    attrs[col] = row[col]

            G.add_edge(start, end, **attrs)

    # ── Enrichissement avec les poteaux (nœuds intermédiaires) ───────────────
    if gdf_poteaux is not None and not gdf_poteaux.empty:
        nb = 0
        for _, row in gdf_poteaux.iterrows():
            geom = row['geometry']
            if not isinstance(geom, Point):
                continue
            noeud = _snap((geom.x, geom.y), tolerance)
            if not G.has_node(noeud):
                G.add_node(noeud)
            G.nodes[noeud]['type'] = 'poteau'
            nb += 1
        print(f"  ⚡ {nb} poteaux ajoutés comme nœuds.")

    # ── Enrichissement avec les postes HTA/BT (nœuds sources/puits) ──────────
    if gdf_postes is not None and not gdf_postes.empty:
        nb = 0
        for _, row in gdf_postes.iterrows():
            geom = row['geometry']
            if not isinstance(geom, Point):
                continue
            noeud = _snap((geom.x, geom.y), tolerance)
            if not G.has_node(noeud):
                G.add_node(noeud)
            G.nodes[noeud]['type'] = 'poste_distribution'
            nb += 1
        print(f"  🏭 {nb} postes HTA/BT ajoutés comme nœuds sources.")

    nb_noeuds = G.number_of_nodes()
    nb_aretes = G.number_of_edges()
    nb_composantes = nx.number_connected_components(G) if nb_noeuds else 0
    print(f"  ✅ Graphe : {nb_noeuds} nœuds | {nb_aretes} arêtes | {nb_composantes} composante(s).")

    return G
