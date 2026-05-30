Jumeau Numérique & Simulateur de Résilience Électrique (IDF 2026)
1. Vision et Objectifs
Ce projet transforme l'infrastructure passive du réseau électrique d'Île-de-France en un outil de pilotage prédictif. À l'aide de la Théorie des Graphes, nous modélisons la "santé" du réseau face à trois menaces : l'usure du temps (vétusté), les agressions externes (chantiers) et les chocs climatiques (canicules) et qui se rapproche le plus de la réalité.
L'objectif : Offrir une plateforme de simulation permettant d'arbitrer entre investissement budgétaire et niveau de risque territorial.
2. Architecture des Données (Data Stack)
A. Ossature Topologique (Le Graphe)
•	Source : Enedis Open Data (Lignes électriques aériennes Basse Tension (BT), Position géographique des poteaux électriques HTA et BT, Lignes électriques souterraines Basse Tension (BT), Postes électriques de distribution publique (postes HTA/BT), Lignes électriques souterraines moyenne tension (HTA), Lignes électriques aériennes moyenne tension (HTA).
•	Rôle : Création du graphe G = (V, E). Nettoyage topologique (Snapping) pour assurer la continuité du flux électrique.
B. Diagnostic de Vétusté Structurelle (Score IFS)-((((((((((()))))))))))
•	Source : Indicateur réglementaire continuité d’alimentation.
•	Méthodologie : Moyenne glissante sur 5 ans pour isoler la fatigue matérielle réelle. Un taux de coupure répété > 5% classe le segment en "fin de vie statistique".
C. Menaces et Contexte (Les Filtres)
•	Chantiers (DT/DICT) : Buffers de 50m pour détecter les risques de rupture physique. 
o	Source : Données de déclaration DT et DICT
•	Impact Social (INSEE) : 
o	Priorisation par densité de population 
	Source : Densité par population
o	Proximité des ERP (Hôpitaux/Écoles).
	Source : Zone sensible ERP
•	Occupation du Sol (IGN OCSGE) : Estimation du coût (Bitume vs Terre).
o	Source : Dossier CLC_RIDF_RGF_SHP
3. Moteur d'Analyse et Optimisatio
Le cœur du projet repose sur le Score de Priorité de Rénovation (SPR) :
$$SPR = (IFS \times W_{vét}) + (Risk_{DICT} \times W_{ext}) + (Pop \times W_{soc})$$
L'Ordonnanceur : Un algorithme de sélection qui consomme l'enveloppe budgétaire annuelle en ciblant les segments au ratio $SPR/Coût$ le plus élevé, tout en respectant un quota de nuisance sonore.

4. Rendu Final : L'Interface de Simulation (Dashboard)
L'utilisateur interagit avec une application Streamlit divisée en trois zones :
 A. Le Panneau de Commande (Sidebar)
•	Curseur Budget : Définit l'investissement annuel (0 à 100M€ par exemple).
•	Sélecteur de Crise (Stress Test) :
o	Canicule : Stress thermique sur les transformateurs (zones d'îlots de chaleur).
	Source : indicateurs_icu
•	Curseur Timeline : Voyage temporel de 0 à 15 ans.
B. Le Split-Screen (Comparaison Synchrone)
L'écran affiche deux cartes Folium côte à côte :
•	Carte Gauche (Inaction) : L'évolution naturelle du réseau. La vétusté se propage, les zones rouges envahissent la carte.
•	Carte Droite (Optimisation SPR) : L'algorithme répare intelligemment. Les segments passent en bleu (chantier) puis en vert (robuste).
C. Les Indicateurs (KPIs)
•	Jauge de Résilience : Santé globale du territoire en %.
•	Compteur Social : Nombre d'habitants et d'ERP (Hôpitaux) sécurisés en temps réel.
•	Graphique Dynamique : Courbe du "Risque Résiduel" vs "Budget Consommé".

5. Stack Technique
Le projet articule des outils de pointe pour le calcul de graphes et l'analyse spatiale :
•	Logiciel SIG : QGIS 3.x (Préparation, nettoyage topologique et validation visuelle des couches).
•	Modélisation de Graphes : NetworkX (Calcul des centralités, points d'articulation et propagation de pannes).
•	Écosystème Géo-Python : GeoPandas, Shapely, PyPROJ (Calculs géométriques et projections).
•	Interface & Dashboard : Streamlit (Framework web), Folium (Cartes interactives), Plotly (Graphiques de performance).

6. Feuille de Route (Roadmap)
Phase 1 : Data Preparation (QGIS & Python)
•	Nettoyage des données Enedis (Snapping) pour assurer la connectivité.
•	Conversion des fichiers SIG en graphe topologique exploitable.
Phase 2 : Intelligence & Scoring
•	Calcul de l'IFS (Vétusté historique 15 ans).
•	Intégration du Stress Thermique (ICU) et du poids social (INSEE/ERP).
•	Estimation des coûts via l'occupation du sol (IGN).
Phase 3 : Optimisation & Simulation
•	Calcul du score SPR et ordonnancement des travaux sous contraintes budgétaires.
•	Gestion des priorités et des nuisances sonores.
Phase 4 : Dashboard & Crise
•	Développement du module Split-Screen (Inaction vs Optimisé).
•	Implémentation des Stress Tests climatiques (Crue/Canicule) avec cascade de pannes.

