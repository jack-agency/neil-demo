# Neil ERP — Scripts de Seed

Scripts de génération de données de démonstration pour l'ERP Neil.

## Contenu

| Script | Description |
|--------|-------------|
| `seed_neil.sh` | Création des écoles, campus, centres d'activité, salles, sociétés, niveaux et liaisons |
| `seed_formulas.sh` | Création des formations et formules avec sets, étapes, échéanciers, remises |
| `seed_module_types.py` | Création des 9 types de modules pédagogiques et assignation aux 1042 modules |
| `seed_teaching_units.py` | Création des UE, sous-UE et modules (cours 1h/2h/4h) dans chaque formation |
| `seed_students.py` | Génération de 200 étudiants avec données complètes et photos de profil |
| `seed_enrollments.py` | Inscription des étudiants aux formules avec répartition par étapes et réductions |
| `seed_groups.py` | Création des ensembles de classes, classes et affectation des étudiants |
| `seed_profiles.py` | Création de 7 profils utilisateurs avec permissions granulaires et obfuscation |
| `seed_users.py` | Création de 20 employés avec affectation de profils (10 enseignants, intervenants séances) |
| `seed_sequences.py` | Planification de 2122 séances sans conflits (salles, intervenants, vacances) sur l'année 2025-2026 |

## Données générées

- **2 écoles** : Sciences & Technologies, Arts & Lettres
- **4 campus** : Paris-Saclay, Lyon-Part-Dieu, Bordeaux-Chartrons, Marseille-Vieux-Port
- **4 centres d'activité** : avec horaires d'ouverture et 18 salles (dont un amphi 120 places)
- **2 sociétés** : SAS ÉduSciences (1 établissement), SARL ArtsCréa (2 établissements)
- **6 niveaux** : Prépa, L1, L2, L3, M1, M2
- **9 formations** : tronc commun, trimestres, stages, ateliers, workshops
- **5 formules** : avec 8 sets liant formules et formations
- **9 types de modules** : Cours magistral, TD, TP, Atelier, Projet, Stage/Résidence, Examen/Concours, Séminaire/Conférence, Soutenance/Restitution
- **31 UE, 65 sous-UE et 1042 modules** : structure pédagogique complète (chaque module = cours de 1h, 2h ou 4h, total = durée de la formation), chaque module typé automatiquement
- **200 étudiants** : avec noms, emails, dates de naissance, adresses, n° sécu, photos de profil, répartis sur les deux écoles (dont 20 en double cursus)
- **220 inscriptions** : 65% inscrits définitivement, reste réparti sur les étapes intermédiaires, 30% avec réduction
- **16 ensembles de classes et 38 classes** : groupes CM, TD, TP, ateliers et projets avec étudiants répartis
- **7 profils utilisateurs** : Directeur d'école, Responsable pédagogique, Responsable des admissions, Secrétaire pédagogique, Comptable, Enseignant, Responsable RH — avec permissions granulaires et obfuscation de données sensibles
- **20 employés** : 10 enseignants (intervenants sur séances), 2 directeurs, 2 resp. pédagogiques, 2 resp. admissions, 1 secrétaire, 1 comptable, 1 resp. RH, 1 multi-profil
- **2122 séances** : planifiées sur l'année scolaire 2025-2026, ventilées par formation/classe/module, sans conflits de salles ni d'intervenants, en respectant les vacances scolaires et jours fériés

### Formules & Formations

| Formule | École | Sets | Cas couvert |
|---------|-------|------|-------------|
| Licence Sciences L2-L3 | S&T | 1 set (tronc commun) | Formation sur 2 ans |
| Prépa Scientifique Intensive | S&T | 2 sets (T1 + T2) | Formule divisée en 2 trimestres |
| Stage Recherche en Laboratoire | S&T | 1 set (stage) | Stage commercialisé (`is_salable`) |
| Licence Arts Plastiques | A&L | 2 sets (théorie + pratique) | Cursus classique |
| Master Création Contemporaine | A&L | 2 sets (tronc commun + options) | Stage en option (min:1, max:2) |

## Prérequis

```bash
# Pour le script Python
pip3 install requests
```

## Utilisation

```bash
# 1. Écoles, campus, centres, salles, sociétés, niveaux
bash seed_neil.sh

# 2. Formations et formules
bash seed_formulas.sh

# 3. Types de modules pédagogiques
python3 seed_module_types.py

# 4. Unités d'enseignement, sous-UE et modules
python3 seed_teaching_units.py

# 5. Étudiants
python3 seed_students.py

# 6. Inscriptions aux formules
python3 seed_enrollments.py

# 7. Classes et groupes
python3 seed_groups.py

# 8. Profils utilisateurs
python3 seed_profiles.py

# 9. Utilisateurs (employés + profils)
python3 seed_users.py

# 10. Séances (planification complète)
python3 seed_sequences.py
```

## Configuration

Les scripts utilisent :
- **API** : `https://neil-claude.erp.neil.app/api/`
- **Auth** : Header `X-Lucius-Api-Key`

Modifiez les constantes `API_BASE` et `API_KEY` dans chaque script pour pointer vers votre instance.
