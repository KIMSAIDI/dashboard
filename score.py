import os
import xml.etree.ElementTree as ET

def extract_scores(base_dir):
    result = {}

    # Parcourir tous les dossiers dans le répertoire principal
    for folder in os.listdir(base_dir):
        folder_path = os.path.join(base_dir, folder)

        # Vérifier si c'est un dossier et ignorer les dossiers spécifiques
        if os.path.isdir(folder_path) and folder not in ["RonDoor_Scenario", "Selectionneur", "Tutoriel", "ELS"]:
            folder_scores = {}

            # Parcourir les fichiers dans le dossier
            for file in os.listdir(folder_path):
                if file.endswith(".xml"):
                    file_path = os.path.join(folder_path, file)

                    # Extraire le score max du fichier XML
                    try:
                        tree = ET.parse(file_path)
                        root = tree.getroot()

                        # Rechercher l'élément <score>
                        score_element = root.find(".//score")
                        if score_element is not None:
                            three_stars = score_element.get("threeStars")
                            if three_stars is not None:
                                # Enregistrer le score max dans le dictionnaire
                                mission_name = os.path.splitext(file)[0].replace("Niveau", "mission")
                                folder_scores[mission_name] = int(three_stars)
                    except ET.ParseError:
                        print(f"Erreur de parsing dans le fichier : {file_path}")

            # Ajouter les scores du dossier au résultat principal
            result[folder] = folder_scores

    return result

# Exemple d'utilisation
base_directory = "Levels"
scores_max = extract_scores(base_directory)
#print(scores_max)

# Afficher les résultats
# for folder, score_dict in scores.items():
#     print(f"Dossier: {folder}")
#     for mission, score in score_dict.items():
#         print(f"  {mission}: {score}")
