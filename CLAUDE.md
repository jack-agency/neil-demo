# Neil Demo — Guide de démo prospect

## Projet
- Guide interactif de démonstration de l'ERP Neil (60 min, visio)
- Flask backend + HTML/CSS/JS statique, pas de build tools
- Auth Google Sign-In restreint @neil.app
- Dev local : `DEV_BYPASS_AUTH=true python3 server.py` → http://localhost:8000

## Architecture

```
index.html          → HTML structure uniquement (pas de CSS/JS inline)
login.html          → Page de connexion
server.py           → Flask : static files + API seeder + auth
css/tokens.css      → Design tokens (source unique pour les couleurs)
css/base.css        → Reset, body
css/layout.css      → Nav, progress bar, main, responsive
css/components.css  → Tous les composants UI
css/seeder.css      → Interface seeder
css/login.css       → Page login
js/auth.js          → Fetch wrapper, loadUser, logout
js/navigation.js    → toggleSection, progress bar clicks
js/seeder.js        → Config, génération, polling, UI update
js/app.js           → Init (appelle loadConfig + loadUser)
seeder/             → Scripts Python de génération de données
```

## Conventions CSS
- Couleurs : toujours via variables CSS (`var(--green)`, `var(--blue-light)`, etc.)
- Tokens définis dans `css/tokens.css` : gray, green, purple, orange, blue, red, finance, pink
- Composants nommés `.composant-variante` : `.badge-green`, `.step-num-purple`, `.section-num-finance`
- Brand Neil : font Inter, border-radius 14px (cards) / 20px (badges) / 8-12px (petits éléments)

## Conventions HTML
- Section de démo : `section.demo-section > .section-header + .section-body`
- Carte : `.entity > .entity-head + contenu`
- Étapes : `ol.steps > li.step > .step-num.step-num-{color} + .step-text`
- Callouts : `.callout.callout-{color}`

## API
- `GET/POST /api/config` — config seeder
- `POST /api/sessions/generate` — lancer génération (body: start_date, end_date)
- `GET /api/sessions/status` — polling statut
- `POST /api/sessions/stop` — arrêter génération
- `POST /auth/google` — auth token Google
- `GET /auth/me` — utilisateur connecté
- `POST /auth/logout` — déconnexion

## Commit convention
- Préfixe par scope : `demo:`, `seeder:`, `global:`
