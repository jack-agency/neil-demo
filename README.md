# Neil Demo — Guide de démonstration prospect

Guide interactif de 60 minutes pour la démonstration de l'ERP Neil en visioconférence. Application web interne réservée aux comptes `@neil.app`.

## Stack technique

- **Frontend** : HTML / CSS / JS vanilla (pas de build, pas de framework)
- **Backend** : Flask (Python 3) — sert les fichiers statiques et expose l'API seeder
- **Auth** : Google Sign-In, restreint au domaine `neil.app`

## Lancer le projet

```bash
# 1. Installer les dépendances
pip install -r requirements.txt

# 2. Configurer les variables d'environnement (optionnel)
#    GOOGLE_CLIENT_ID=...       → pour l'auth Google
#    FLASK_SECRET_KEY=...       → clé de session Flask
#    DEV_BYPASS_AUTH=true       → bypass l'auth en local

# 3. Démarrer le serveur
DEV_BYPASS_AUTH=true python3 server.py
```

Le guide est accessible sur `http://localhost:8000`.

## Structure du projet

```
neil-demo/
├── index.html           # Page principale du guide
├── login.html           # Page de connexion Google
├── server.py            # Serveur Flask (API + static)
├── requirements.txt     # Dépendances Python
├── css/
│   ├── tokens.css       # Design tokens (couleurs, variables)
│   ├── base.css         # Reset et styles de base
│   ├── layout.css       # Navigation, barre de progression, responsive
│   ├── components.css   # Composants UI (badges, cards, steps, callouts…)
│   ├── seeder.css       # Interface du seeder
│   └── login.css        # Page de connexion
├── js/
│   ├── auth.js          # Authentification et gestion de session
│   ├── navigation.js    # Toggle des sections et barre de progression
│   ├── seeder.js        # API seeder (config, génération, polling)
│   └── app.js           # Initialisation
└── seeder/              # Scripts Python de génération de données
```

## API endpoints

| Méthode | Route                    | Description                          |
|---------|--------------------------|--------------------------------------|
| GET     | `/api/config`            | Récupérer la config du seeder        |
| POST    | `/api/config`            | Sauvegarder la config du seeder      |
| POST    | `/api/sessions/generate` | Lancer la génération de séances      |
| GET     | `/api/sessions/status`   | Statut de la génération en cours     |
| POST    | `/api/sessions/stop`     | Arrêter la génération                |
| POST    | `/auth/google`           | Authentification via token Google    |
| GET     | `/auth/me`               | Info utilisateur connecté            |
| POST    | `/auth/logout`           | Déconnexion                          |

## Dataset Poudlard

Le seeder génère un environnement complet basé sur l'univers Harry Potter : ~75 étudiants, 20 collaborateurs, 5 formules, des inscriptions, notes, plannings et bulletins.
