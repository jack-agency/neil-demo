# Neil ERP — Seed Scripts

## Projet

Scripts de seed pour l'instance de démo Neil ERP. L'objectif est de remplir l'ERP avec des données réalistes et cohérentes.

**Architecture config-driven** : toutes les données sont paramétrables via `seed_config.json`. Chaque script lit la config et le manifest, crée les ressources via l'API, puis écrit les IDs créés dans `seed_manifest.json` pour les scripts downstream.

## Architecture

### Fichiers centraux

| Fichier | Rôle |
|---------|------|
| `seed_lib.py` | Bibliothèque partagée : config/manifest I/O, helpers API, logging, pools de noms, `generate_default_config()` |
| `seed_config.json` | Configuration utilisateur (entrée) : nombre d'écoles, formations, thèmes, prix, étudiants... |
| `seed_manifest.json` | État partagé (runtime) : IDs créés par chaque script, lu par les scripts downstream |

### Flux de données

```
seed_config.json ──→ seed_neil.py ──→ seed_manifest.json (infrastructure, calendars)
                 ──→ seed_formulas.py ──→ seed_manifest.json (+formations, formulas)
                 ──→ seed_teaching_units.py ──→ seed_manifest.json (+teaching_units)
                 ──→ seed_students.py ──→ seed_manifest.json (+students)
                 ──→ ... chaque script lit le manifest et y ajoute sa section
```

### Manifest — sections principales

| Clé | Écrit par | Lu par | Contenu |
|-----|-----------|--------|---------|
| `infrastructure` | `seed_neil` | formulas, students, sequences | schools, faculties, companies, levels, centers, rooms |
| `calendars` | `seed_neil` | sequences | calendar IDs, zones, center mappings |
| `formations` | `seed_formulas` | module_types, teaching_units, groups, sequences, scores | formation IDs, themes, hours, faculty_ids |
| `formulas` | `seed_formulas` | enrollments, payments | formula IDs, steps, discounts, sets |
| `teaching_units` | `seed_teaching_units` | sequences, scores | totaux UEs, sous-UEs, modules |
| `profiles` | `seed_profiles` | users | profile IDs |
| `students` | `seed_students` | parents, ibans, enrollments | all_ids, minor_ids, by_school |
| `parents` | `seed_parents` | — | total, families, fratries |
| `ibans` | `seed_ibans` | payments | student_ibans, parent_ibans |
| `employees` | `seed_users` | sequences | all_ids, teachers_ids, managers_ids |
| `enrollments` | `seed_enrollments` | groups, payments | total, by_formula |
| `groups` | `seed_groups` | sequences, scores | main/td/tp group_ids par formation |
| `sequences` | `seed_sequences` | absences | total, rooms_used, teachers_used |
| `absences` | `seed_absences` | — | total_absences, total_delays, justified_pct |
| `scores` | `seed_scores` | report_cards | total_scores, total_compound |
| `report_cards` | `seed_report_cards` | — | total, published_students, bulletin_ids |
| `payments` | `seed_payments` | — | total_payments, breakdown |
| `employers` | `seed_employers` | — | all_ids, total, locations_created, contacts_created |

## API

- **URL** : configurable dans `seed_config.json`
- **Auth** : Header `X-Lucius-Api-Key` (clé dans `seed_config.json`)
- **Swagger** : `GET /swagger.json` (incomplet, beaucoup de champs non documentés)

## Quirks de l'API (non documentés)

- `FormationCreate` requiert `is_active: true` et `tags: []` (sinon 500)
- `FormulaCreate` requiert `company_id` (absent du swagger)
- Unités d'enseignement : le champ est `unit` et non `name`
- Module creation : `POST` retourne un array, `default_duration` se set via `PATCH` séparé
- Types de modules : `GET/POST /formations/{id}/module-types`, assignation via `PATCH /formations/{id}/modules/{mid}` avec `{"module_type_id": N}`
- Suppression type : `DELETE /formations/{id}/module-types/{type_id}` (reset d'abord les modules assignés)
- Partage de formation inter-écoles bloqué (`protected_resource`)
- Prix en **centimes** (850000 = 8500.00 EUR), durées en **secondes** (3600 = 1h)
- Horaires centres (`openings_schedule`) : clés numériques `"0"`=lundi … `"6"`=dimanche, valeurs `{"open": sec, "close": sec}` en secondes depuis minuit. Le PATCH fait un deep merge (impossible de supprimer une clé existante).
- Étapes d'inscription : `PATCH /formulas/{id}/steps` avec body `{"steps": [...]}`
- Dernière étape ne peut pas avoir d'avance (advance)
- Échéanciers utilisent les step IDs comme clés
- Remises : utiliser le type `fixed` avec montant en centimes (pas `variable`)
- Inscription étudiant : `POST /students/{id}/formulas` avec `{"formulas": {"formula_id": N}}`
- Avancement d'étape : `PATCH /students/{id}/formulas/{sf_id}` avec `{"step": {"formula_step_id": N}}`
- Ajout de réduction : même PATCH avec `{"discounts": [{"formula_discount_id": N}]}`
- Suppression module : `DELETE /formations/{fid}/modules/{module_id}` (module_id de l'array modules, pas node_id)
- Suppression UE : `DELETE /formations/{fid}/teaching-units/{node_id}` (échoue si enfants existent)
- Sous-UE : même endpoint que UE mais avec `parent_node_id`
- UE par défaut : chaque formation a une "Unité d'enseignement par défaut" créée automatiquement. **Bonne pratique** : la renommer via `PATCH /formations/{id}/teaching-units/{node_id}` avec `{"unit": "Nouveau nom", "order": N}` et l'utiliser comme première UE au lieu de la supprimer
- Création groupe : `POST /formations/{fid}/groups` avec `{"groups": {"name", "group_set_id", "color", "capacity"}}` (retourne array)
- Création ensemble : `POST /formations/{fid}/group-sets` avec `{"name": "..."}`
- Affectation étudiants : `POST /formations/{fid}/groups/{gid}/students` avec `{"students": [{"student_id": N}]}`
- Chaque formation a un ensemble par défaut "Ensemble de classes par défaut" (renommable via PATCH)
- Affectation formations : `PATCH /students/{id}/formulas/{sf_id}` avec `{"sets": [{"set_id": N, "formations": [N]}]}`
- Les sets persistent : pas besoin de les renvoyer lors des PATCH suivants (step, discount)
- Calendriers de contraintes : `POST /constraints-calendar` avec `{"name", "faculties": [faculty_ids], "constraints": [{"name", "type": "holiday", "start_date", "end_date"}]}`
- Lien calendrier ↔ formation : `PATCH /formations/{id}/constraints-calendars` avec `{"faculty_id": N, "calendar_ids": [N]}`
- **Important** : `faculties: [ids]` est obligatoire à la création du calendrier sinon il devient orphelin (GET 404, DELETE 404)
- `GET /formations/{id}/constraints-calendars` filtre par chevauchement de dates avec la formation
- Suppression calendrier sans faculties impossible (bug API) — utiliser un nom unique si besoin de recréer
- Profils : `POST /profiles` crée le profil, `POST /profiles/{id}/permissions` assigne les permissions (format `{"permissions": {"module": {"feature": {"perm": true}}}}`)
- Profils : créer le profil SANS permissions dans le body, puis les ajouter via `POST /profiles/{id}/permissions` séparément (sinon 403 sur certaines combinaisons)
- Profils : le module `custom` (notifications) n'est pas accessible via l'API key service-account (403)
- Obfuscation : `PATCH /profiles/{id}` avec `{"obfuscate": {"student": ["field1"], "parent": ["field2"], "employee": ["field3"]}}` — valeurs possibles : last_name, first_name, birth_name, email, phone_number, address, city, photo (+ personal_email, personal_phone_number pour employee)
- Parents : `POST /students/{id}/parents` crée un parent inline (first_name, last_name, email requis) ou lie un existant avec `{"parent_id": N}`
- Parents : la recherche se fait via `POST /parents/search` (pas GET)
- Parents : `GET /students/{id}/parents` retourne `{"parents": [...]}`
- Employés : `POST /employees` (champs requis: first_name, last_name, email, birth_date), profil via `POST /employees/{id}/profiles` avec `{"profile_id": N, "scope": {...}}`
- `DELETE /employees/{id}` retourne 500 (bug API) — utiliser `PATCH /employees/{id}/deactivate` + suppression des profils
- Séances : `POST /formations/{id}/sequences` avec `{"sequences": [...]}` — start_date, room_id et managers dans la création (pas de PATCH schedule séparé nécessaire)
- Audience séance : `{"groups": {"gs_id": true}}` (tout l'ensemble) ou `{"groups": {"gs_id": {"g_id": true}}}` (un groupe spécifique)
- Managers séance : `[employee_id, ...]` — seuls les employés avec permission pedagogy.sequences.schedule sont autorisés (pas resp admissions, comptable, RH)
- Managers formation : `POST /formations/{fid}/managers` avec `{"managers": [employee_profile_ids]}` — utilise les **employee_profile_ids** (pas employee_ids)
- Managers module : `PATCH /formations/{fid}/modules/{mid}` avec `{"managers": {"add": [employee_profile_ids]}}` — utilise les **employee_profile_ids** avec format add/remove
- Managers groupe : `POST /formations/{fid}/groups/{gid}/managers` avec `{"managers": [employee_profile_ids]}` — utilise les **employee_profile_ids**
- **Important** : formations/modules/groupes utilisent `employee_profile_id` (retourné par `POST /employees/{id}/profiles`), tandis que les séances utilisent `employee_id`
- Échéanciers : `POST /students/{id}/formulas/{sf_id}/payments` crée une échéance. **Ne pas utiliser PATCH batch** (bug : items dupliqués)
- IBAN dans paiements : seuls les IBANs actifs (`is_active: 1`) sont acceptés, sinon erreur 400
- Templates d'échéancier : pas d'API d'application directe — lire `formula.schedule_templates` et créer manuellement chaque paiement
- Avatar upload (3 étapes) : 1) `POST /students/{id}/avatar` avec `{"original_name", "type": "image/jpeg", "size": N}` → réponse avec `X-Upload-Location` header 2) `POST` binary image au `X-Upload-Location` URL (Cloud Run → GCS) 3) `PATCH /students/{id}/avatar` avec la réponse JSON du step 2 (contient `type`, `assets.media`, `assets.files`)
- Sources avatars : pravatar.cc (visages divers, fallback randomuser.me). Configurable via `seeder.include_avatars` (défaut `true`)
- Émargement : `PATCH /formations/{fid}/sequences/{seqId}/attendance-list` avec `{"attendances": [{"student_id": N, "type": "absence"|"delay"|"present", "absence_slug": "...", "delay": seconds, "justified": 0|1, "comment": "..."}]}`
- Émargement lecture : `GET /formations/{fid}/sequences/{seqId}/attendance-list`
- `absence_slug` valeurs : sick_leave, no_reason, transportation_problem, family_reason, medical_appointment, extented_vacation (sic), administrative_meeting, other
- Bulletins de notes — flux complet (status 0→1→2→3→published) :
  1. `POST /report-cards` avec `{name, faculty_id, year_from, year_to, from, to}` — name max **64 chars**
  2. `PATCH /report-cards/{id}/audience` avec `{audience: {formula_id, formula_formation_set_id, formation_id}}`
  3. `PATCH /report-cards/{id}/audience/validate` → status 1
  4. `POST /report-cards/{id}/items` avec `{items: [{teaching_unit_node_id, order, children: [...]}]}` — retourne `{items, scores, formations}`
  5. `PATCH /report-cards/{id}/items/{item_id}/scores` avec `{scores: [{score_id}]}` — **PATCH** obligatoire (POST retourne 404)
  6. `PATCH /report-cards/{id}/scores/validate` → status 2
  7. `PATCH /report-cards/{id}/options` avec `{max, precision, include_audience: true, include_groups: true, include_overall_average: true, include_ranking: true, include_median: true, include_chart: true}`
  8. `PATCH /report-cards/{id}/options/validate` → status 3
  9. `PATCH /report-cards/{id}/students/publish` avec `{ids: [student_ids]}` — utiliser `student.id` (pas l'ID du lien bulletin-étudiant)
- Bulletins — suggestions de notes : `GET /report-cards/{id}/scores/suggestions` retourne les notes disponibles pour la période du bulletin
- Bulletins — notes composées : ont `module: null` dans les suggestions (filtrer avant assignation)
- Bulletins — champ `order` : peut être `null` (pas juste absent), utiliser `or 0` pour le tri
- Bulletins — recherche : `POST /report-cards/search` avec `{filters: {}}` retourne la liste
- Bulletins — suppression : `DELETE /report-cards/{id}` — **échoue 409** si des étudiants sont publiés. Flux de suppression complet : 1) dépublier via `PATCH /report-cards/{id}/students/unpublish` avec `{ids: [student_ids]}` 2) `DELETE /report-cards/{id}/options` (status 3→2) 3) `DELETE /report-cards/{id}/scores` (2→1) 4) `DELETE /report-cards/{id}/audience` (1→0) 5) `DELETE /report-cards/{id}`
- Bulletins — liste étudiants : `GET /report-cards/{id}/students` retourne `[{id: N, student: {id: M}, is_published: 0}]`
- Diplômes : `POST /degrees` avec `{school_id, faculty_id, degree_level_id, name, official_name}` — `name` et `official_name` max 64 chars, `code` **exactement 8 chars** alphanumériques (padding avec `"0"` si plus court)
- Diplômes — niveaux : `GET /degrees/levels` retourne 25 niveaux (1=phd, 4=master, 9=licence, 12=bts, 18=other_4/bac, 23=bachelor, etc.)
- Diplômes — certifications : `POST /degrees/{id}/certifications` avec `{start_date, end_date, rncp_level?, rncp_number?}`
- Diplômes — liaison formule : `PATCH /formulas/{id}` avec `{degree_id: N, degree_certification_id: N}`
- Diplômes — recherche : `POST /degrees/search` avec `{filters: {}}`
- Diplômes — suppression : `DELETE /degrees/{id}` (supprimer certifications d'abord), délier formules via `PATCH /formulas/{id}` avec `{degree_id: null}`
- Employeurs : `POST /employers` avec `{siren, legal_name, commercial_name?, sector?, naf?, employees_count?, phone_number?, site_url?}` — `siren` (9 chiffres) + `legal_name` obligatoires, `sector` = "private"|"public" (défaut "private")
- Employeurs — établissements : `POST /employers/{id}/business-locations` avec `{siret, name, address: {address, postal_code, city}}` — `siret` = SIREN + NIC (14 chiffres)
- Employeurs — contacts : `POST /employers/{id}/contacts` avec `{first_name, last_name, email, phone_number?, position?}`
- Employeurs — recherche : `POST /employers/search` avec `{filters: {s: "..."}}` ou `{filters: {}}`
- Employeurs — suppression : `DELETE /employers/{id}` → 204

## Configuration (seed_config.json)

La config est générée automatiquement par `seed_lib.generate_default_config()` ou éditée manuellement. Elle définit QUOI créer :

### Sections principales

| Section | Clé | Description | Défaut |
|---------|-----|-------------|--------|
| Meta | `meta.academic_year` | Année scolaire | "2025-2026" |
| Meta | `meta.random_seed` | Graine aléatoire | 2026 |
| API | `api.base_url` | URL de l'API | (à configurer) |
| API | `api.key` | Clé API | (à configurer) |
| Écoles | `schools[]` | Écoles avec key, name, short, theme | 2 (sciences, arts) |
| Campus | `campuses[]` | Campus avec city, zone, center_name | 2 par école |
| Sociétés | `companies[]` | Sociétés avec school_keys | 1 par école |
| Niveaux | `levels[]` | Noms des niveaux | Prépa, L1-L3, M1-M2 |
| Centres | `centers.rooms_per_campus` | Salles par campus | 4 |
| Formations | `formations[]` | Formations avec theme, hours, campus_keys | 9 |
| Formules | `formulas[]` | Formules avec steps, discounts, prix | 5 |
| Employeurs | `employers.total` | Nombre d'employeurs | 10 |
| Employeurs | `employers.dataset` | Dataset employeurs | "standard" |
| Étudiants | `students.total` | Nombre total d'étudiants | 200 |
| Inscriptions | `enrollments.final_pct` | % inscrits définitifs | 65 |
| Notes | `scores.mean` | Moyenne des notes (×100) | 1200 |
| UE | `teaching_units.themes` | Définitions de cours par thème | auto |
| Séances publiées | `seeder.sequence_publish_pct` | % de séances publiées | 100 |
| Absences | `seeder.absence_rate_pct` | % d'absences par séance | 8 |
| Retards | `seeder.delay_rate_pct` | % de retards par séance | 5 |

### Thèmes disponibles

Chaque école est associée à un thème qui détermine les noms de formations, cours, salles et évaluations :

- `sciences` — Mathématiques, Physique, Informatique, Chimie, Biologie
- `arts` — Histoire de l'art, Pratique artistique, Culture visuelle, Création contemporaine
- `droit` — Droit civil, Droit public, Sciences politiques
- `sante` — Sciences fondamentales, Clinique, Pharmacologie
- `ingenierie` — Sciences de l'ingénieur, Génie, Informatique industrielle

## Données générées (config par défaut)

Avec la config par défaut (2 écoles, 4 campus, 9 formations, 5 formules, 200 étudiants) :

### Infrastructure
- 2 écoles : Sciences & Technologies, Arts & Lettres
- 4 campus (2 par école) avec centres d'activité et horaires
- ~16-18 salles (4 par campus)
- 2 sociétés, 6 niveaux (Prépa → M2)
- 4 calendriers de contraintes (1 par campus, zones A/B/C)

### Structure pédagogique
- 9 formations (5 sciences, 4 arts) de 100h à 1200h
- 9 types de modules × 9 formations
- ~30 UEs, ~65 sous-UEs, ~1000 modules (générés par thème)
- Noms de cours thématiques (ex: "Cours Analyse", "TD Algèbre", "Atelier Dessin-Peinture")

### Utilisateurs
- 200 étudiants (100 S&T, 80 A&L, 20 double cursus)
- ~6 mineurs avec 2 parents chacun
- ~10 fratries avec parents partagés
- ~250 IBANs (étudiants majeurs + parents)
- 20 employés (10 enseignants, 2 directeurs, 2 resp. péda, 2 resp. admissions, 1 secrétaire, 1 comptable, 1 RH, 1 multi-profil)
- 7 profils utilisateurs avec permissions granulaires

### Employeurs
- 10 employeurs (entreprises partenaires) avec établissements et contacts
- 2 datasets : "standard" (30 entreprises françaises réalistes) et "poudlard" (15 entreprises magiques)
- 1 établissement (siège social) et 1-2 contacts par employeur

### Inscriptions & classes
- ~220 inscriptions (65% définitifs, ~30% avec réduction)
- ~16 ensembles de classes, ~38 classes (taille basée sur effectif)
- Structure dynamique : ≥40 étu. → CM+TD+TP ; 20-40 → Classe+TD ; <20 → groupes spécialisés

### Planification & Vie scolaire
- ~2000+ séances planifiées (sept. 2025 → juin 2026)
- 0 conflits de salles/intervenants (scheduler avec détection)
- Vacances et fériés respectés par zone
- Absences (~8% par séance) et retards (~5%) avec motifs réalistes et justifications (~60%)
- ~200+ relevés de notes, ~50+ notes composées (distribution gaussienne)
- ~700+ échéanciers de paiement

## Conventions

- **Langue** : noms et données en français
- **Pas de confirmation** : exécuter directement sans demander
- **Update plutôt que delete/create** : utiliser PATCH quand possible
- **Modules** : nommer avec Cours, TP, TD, Atelier, Projet (jamais "Séance")
- **Tous les scripts en Python** (plus de scripts Bash)
- **Config-driven** : les scripts lisent `seed_config.json`, pas de variables d'environnement
- **Manifest-driven** : les IDs dynamiques viennent de `seed_manifest.json`, jamais hardcodés
- **Toujours push sur le repo** après modification des scripts

## Ordre d'exécution

```bash
python3 seed_neil.py              # 1. Infrastructure (écoles, campus, centres, salles, calendriers)
python3 seed_formulas.py          # 2. Formations, formules, étapes, remises + liaison calendriers
python3 seed_teaching_units.py    # 3. UE, sous-UE et modules (générés par thème)
python3 seed_module_types.py      # 4. Types de modules pédagogiques (requiert modules existants)
python3 seed_students.py          # 5. Étudiants
python3 seed_parents.py           # 5b. Parents (mineurs, fratries, familles)
python3 seed_ibans.py             # 5c. IBANs (étudiants majeurs + parents)
python3 seed_enrollments.py       # 6. Inscriptions aux formules
python3 seed_groups.py            # 7. Classes et groupes
python3 seed_profiles.py          # 8. Profils utilisateurs
python3 seed_users.py             # 9. Employés + affectation profils
python3 seed_sequences.py         # 10. Séances (planification complète)
python3 seed_absences.py          # 11. Absences et retards sur les séances
python3 seed_scores.py            # 12. Relevés de notes et notes composées
python3 seed_report_cards.py      # 13. Bulletins de notes (par semestre, par formation)
python3 seed_payments.py          # 14. Échéanciers de paiement
# python3 seed_documents.py       # 15. Documents pédagogiques (désactivé)
python3 seed_employers.py         # 16. Employeurs (entreprises partenaires)
```

Chaque script vérifie ses dépendances via `require_step()` et échoue si un prérequis manque.

### Remise à zéro

```bash
python3 seed_reset.py              # Supprime TOUTES les données (préserve admin/service)
```

Le script `seed_reset.py` supprime toutes les données dans l'ordre inverse du pipeline (employeurs → paiements → bulletins → notes → absences/retards → séances → groupes → inscriptions → IBANs → parents → étudiants → employés → profils → modules → types de modules → types de documents → matières → calendriers → diplômes → formations+formules → infrastructure), puis remet le manifest à zéro. Les calendriers sont supprimés AVANT les formations car le search filtre par chevauchement de dates. Les diplômes sont déliés des formules puis supprimés (avec leurs certifications) avant les formules. Les pièces justificatives des étapes de formules sont nettoyées avant suppression des formules.

**Protections** :
- Les comptes de service (IDs 1, 2, 3) ne sont jamais supprimés
- Les comptes administrateur (`is_admin=True`) ne sont jamais supprimés
- Les profils réservés (`is_reserved=True`) ne sont jamais supprimés
- Les employés non supprimables sont désactivés (bug API `DELETE /employees/{id}` → 500)

Disponible aussi via le bouton **💣 Remettre à zéro** dans le dashboard (onglet Pipeline), avec confirmation obligatoire.

## Dashboard Streamlit

Interface graphique pour exécuter, configurer et monitorer le pipeline de seed.

```bash
pip install streamlit
streamlit run seed_dashboard.py
```

### 3 onglets

1. **🚀 Pipeline** : exécution séquentielle ou individuelle des 15 scripts
   - Statuts : ⚪ Not run / 🔵 Running / 🟢 Success / 🔴 Error
   - Run All / Run individuel / Stop
   - **💣 Remettre à zéro** : suppression complète avec confirmation
   - Console temps réel avec sortie ANSI

2. **⚙️ Configuration** : paramétrage de `seed_config.json`
   - **Quick Setup** : sliders pour nombre d'écoles (1-5), campus/école (1-4), thèmes, étudiants (50-1000), employés (5-30), % inscriptions, notes...
   - **JSON Editor** : édition manuelle avec validation
   - Bouton "Générer config" → `generate_default_config()` → `seed_config.json`

3. **📊 Manifest** : visualisation de `seed_manifest.json`
   - Cards résumé (infrastructure, formations, étudiants, employés)
   - Sections expansibles par clé du manifest
   - JSON brut

## Personnalisation

### Ajouter une école

1. Modifier `seed_config.json` : ajouter une entrée dans `schools[]` + `campuses[]` + `companies[]`
2. Ajouter des formations dans `formations[]` avec le bon `school_key`
3. Ajouter des formules dans `formulas[]` avec les `formation_keys` correspondantes
4. Ajuster `students.by_school` avec le nombre d'étudiants
5. Relancer le pipeline complet

### Changer le thème d'une école

1. Via le dashboard Quick Setup, changer le thème dans le selectbox
2. Ou manuellement : modifier le champ `theme` dans `schools[]` et les `theme` dans `formations[]`
3. Les thèmes disponibles : sciences, arts, droit, sante, ingenierie
4. Les noms de cours, évaluations, salles, groupes s'adaptent automatiquement

### Ajouter un thème personnalisé

1. Ajouter la définition dans `THEME_DEFINITIONS` dans `seed_lib.py` :
   - `ues` : liste de noms d'UE
   - `sub_ues` : dict {ue_name: [sous-ues]}
   - `module_patterns` : patterns de modules avec prefix, hours, weight
2. Ajouter les templates correspondants dans `FORMATION_TEMPLATES`, `FORMULA_TEMPLATES`, `SCORE_TEMPLATES_BY_THEME`
3. Ajouter les pools de noms dans `ROOM_POOLS`, `ROOM_FAMOUS_NAMES`, `CAMPUS_CITIES`
