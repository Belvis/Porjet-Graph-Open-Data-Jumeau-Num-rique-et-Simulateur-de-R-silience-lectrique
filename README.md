# Jumeau Numérique et Simulateur de Résilience Électrique — Île-de-France

Projet académique de modélisation du réseau électrique francilien sous forme de graphe, avec calcul de scores de résilience et tableau de bord interactif de simulation budgétaire.

---

## Fonctionnalités

- **Graphe du réseau électrique IDF** — lignes BT et HTA aériennes et souterraines (données ENEDIS open data)
- **Score IFS** (Indice de Fragilité Structurelle) — vieillissement, coupures historiques
- **Score SPR** (Score de Priorité de Rénovation) — 6 critères pondérables : vieillissement, densité de population, ERP, chantiers DICT, centralité, sensibilité environnementale (CLC)
- **Simulateur budgétaire** — ordonnancement des rénovations sur 20 ans selon un budget annuel
- **Stress tests** — simulation de canicule (stress thermique)
- **Dashboard Streamlit** — carte interactive pydeck, KPIs, graphe d'évolution du risque

---

## Prérequis

- Python **3.10 ou supérieur**
- pip

---

## Installation et lancement (3 étapes)

### Étape 1 — Cloner le dépôt

```bash
git clone https://github.com/Belvis/Porjet-Graph-Open-Data-Jumeau-Num-rique-et-Simulateur-de-R-silience-lectrique.git
cd Porjet-Graph-Open-Data-Jumeau-Num-rique-et-Simulateur-de-R-silience-lectrique
```

### Étape 2 — Installer les dépendances

Il est recommandé d'utiliser un environnement virtuel :

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### Étape 3 — Lancer le dashboard

```bash
streamlit run app.py
```

Le dashboard s'ouvre automatiquement dans le navigateur à l'adresse `http://localhost:8501`.

> **Les données pré-calculées sont incluses dans le dépôt** — le dashboard est opérationnel dès le premier lancement, sans aucune configuration supplémentaire.

---

## Structure du projet

```
.
├── app.py                  # Dashboard Streamlit (point d'entrée)
├── run_pipeline.py         # Pipeline complet de traitement
├── build_database.py       # Construction de la base depuis les CSV bruts
├── graph_builder.py        # Construction du graphe NetworkX
├── ifs_calculator.py       # Calcul du score IFS
├── spr_calculator.py       # Calcul du score SPR
├── spatial_filters.py      # Filtres spatiaux (population, ERP, CLC...)
├── scheduler.py            # Ordonnanceur budgétaire
├── stress_tests.py         # Tests de stress (canicule, inondation)
├── cleaning.py             # Nettoyage et reprojection des géométries
├── requirements.txt
├── src/
│   ├── data_prep/          # Préparation des données
│   ├── scoring/            # Modules de scoring
│   ├── optimization/       # Optimisation budgétaire
│   └── dashboard/          # Composants du tableau de bord
└── data/
    ├── 01_raw/             # Données brutes open data (non incluses, voir ci-dessous)
    ├── 02_interim/         # Données intermédiaires pré-calculées ✅
    └── 03_processed/       # Données finales pré-calculées ✅
```

---

## Données incluses dans le dépôt

| Fichier | Taille | Contenu |
|---|---|---|
| `data/02_interim/idf_data.db` | 0.3 Mo | Indicateurs de continuité, population INSEE, chantiers DICT (SQLite) |
| `data/03_processed/reseau.db` | 32 Mo | Réseau électrique optimisé (SQLite) |
| `data/03_processed/reseau_pydeck.parquet` | 44 Mo | Segments réseau pour la visualisation |
| `data/03_processed/reseau_pydeck_slim.parquet` | 8 Mo | Version allégée pour affichage rapide |
| `data/03_processed/noeuds_pydeck.parquet` | 1.5 Mo | Nœuds de jonction du réseau |

---

## Relancer le pipeline depuis les données brutes (optionnel)

Le dashboard fonctionne immédiatement avec les données pré-calculées. Si vous souhaitez **reconstruire la base depuis zéro** à partir des fichiers open data originaux :

### 1. Télécharger les données brutes

Placer les fichiers suivants dans `data/01_raw/` :

| Fichier | Source |
|---|---|
| Lignes électriques BT aériennes / souterraines | [ENEDIS Open Data](https://data.enedis.fr) |
| Lignes électriques HTA aériennes / souterraines | [ENEDIS Open Data](https://data.enedis.fr) |
| Position géographique des poteaux HTA et BT | [ENEDIS Open Data](https://data.enedis.fr) |
| Postes électriques | [ENEDIS Open Data](https://data.enedis.fr) |
| Indicateur de continuité d'alimentation | [ENEDIS Open Data](https://data.enedis.fr) |
| Zone sensible ERP | [ENEDIS Open Data](https://data.enedis.fr) |
| Données de déclaration DT et DICT | [ENEDIS Open Data](https://data.enedis.fr) |
| Densité par population (grille INSEE 200m) | [INSEE](https://www.insee.fr/fr/statistiques/7655475) |
| Indicateurs ICU (chaleur urbaine) | [data.gouv.fr](https://www.data.gouv.fr) |
| CLC Île-de-France (Corine Land Cover) | [Géoportail](https://www.geoportail.gouv.fr) |

### 2. Construire la base de données

```bash
python build_database.py
```

Cette étape est **longue** (30–60 min selon la machine) car elle traite plusieurs gigaoctets de CSV.

### 3. Lancer le dashboard normalement

```bash
streamlit run app.py
```

---

## Utilisation du dashboard

1. **Barre latérale** — régler le budget annuel (M€), la durée de projection (années) et activer le stress canicule
2. **Lancer la Simulation** — déclenche le pipeline de calcul (mise en cache automatique)
3. **Carte interactive** — visualiser les segments par score SPR, statut de rénovation ou année planifiée
4. **KPIs** — indice de résilience global, nombre de rénovations, ERP sécurisés, budget consommé
5. **Graphe temporel** — évolution du risque avec vs sans intervention sur 20 ans

---

## Technologies utilisées

| Technologie | Usage |
|---|---|
| [Streamlit](https://streamlit.io) | Dashboard interactif |
| [GeoPandas](https://geopandas.org) | Traitement des données géospatiales |
| [NetworkX](https://networkx.org) | Modélisation en graphe |
| [pydeck](https://deckgl.readthedocs.io) | Visualisation cartographique 3D |
| [Plotly](https://plotly.com) | Graphiques interactifs |
| [Shapely](https://shapely.readthedocs.io) | Géométries vectorielles |
| SQLite / GeoPackage | Stockage des données traitées |

---

## Auteur

**Belvis AGBOTON** — Projet Graph Open Data  
