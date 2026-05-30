import os

def create_project_structure(base_path):
    """Crée l'arborescence des dossiers et des fichiers d'initialisation du projet."""
    
    directories = [
        "data/01_raw",
        "data/02_interim",
        "data/03_processed",
        "src/data_prep",
        "src/scoring",
        "src/optimization",
        "src/dashboard",
        "notebooks"
    ]
    
    init_files = [
        "src/__init__.py",
        "src/data_prep/__init__.py",
        "src/scoring/__init__.py",
        "src/optimization/__init__.py",
        "src/dashboard/__init__.py",
        "app.py",
        "requirements.txt"
    ]

    print(f"Création de l'arborescence dans : {base_path}...\n")

    # Création des dossiers
    for directory in directories:
        dir_path = os.path.join(base_path, directory)
        os.makedirs(dir_path, exist_ok=True)
        print(f"📁 Créé : {directory}")

    # Création des fichiers d'initialisation vides
    for file in init_files:
        file_path = os.path.join(base_path, file)
        with open(file_path, 'a') as f:
            pass
        print(f"📄 Créé : {file}")

if __name__ == "__main__":
    # Le script s'exécute dans le dossier où il se trouve
    create_project_structure(os.path.abspath(os.path.dirname(__file__)))