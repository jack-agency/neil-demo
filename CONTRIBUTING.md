# Contribuer au Guide de démo Neil

## Conventions

### CSS
- Les couleurs et variables sont dans `css/tokens.css` — ne jamais hardcoder de couleurs
- Les composants réutilisables sont dans `css/components.css`
- Préférer les classes CSS aux styles inline
- Nommage : `.composant-variante` (ex. `.badge-green`, `.step-num-purple`)

### JavaScript
- Vanilla JS, pas de framework ni bundler
- Un fichier par domaine : `auth.js`, `navigation.js`, `seeder.js`
- Les fonctions appelées depuis le HTML (`onclick`) doivent rester globales

### HTML
- Chaque section de démo suit le pattern : `section.demo-section > .section-header + .section-body`
- Les cartes de contenu utilisent `.entity > .entity-head + contenu`
- Les étapes utilisent `ol.steps > li.step > .step-num + .step-text`

## Ajouter une section de démo

1. Créer un nouveau `<section class="demo-section collapsed" id="sX">` dans `index.html`
2. Ajouter un segment dans la barre de progression (`#progressBar`)
3. Choisir une couleur via les classes existantes (`section-num-green`, `badge-blue`, etc.)
4. Si une nouvelle couleur est nécessaire, l'ajouter dans `css/tokens.css` et créer les classes associées dans `css/components.css`

## Ajouter un composant CSS

1. Définir le composant dans `css/components.css`
2. Utiliser les variables de `tokens.css` pour les couleurs
3. Documenter le pattern HTML attendu dans un commentaire

## Tester

Pas de tests automatisés — vérification manuelle :
- Ouvrir `http://localhost:8000` avec `DEV_BYPASS_AUTH=true`
- Vérifier chaque section s'ouvre/se ferme
- Vérifier la barre de progression
- Tester le responsive (< 900px)
- Vérifier que le seeder fonctionne (config + génération)
