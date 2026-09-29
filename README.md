# JBudget

Importe l'export CSV du compte ING et le relevé VISA (PDF), classe chaque ligne par règles,
et apprend de tes corrections.

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
```

## Utilisation

```powershell
.\.venv\Scripts\jbudget import data                 # un dossier, ou des fichiers .csv / .pdf
.\.venv\Scripts\jbudget serve                       # interface : http://127.0.0.1:5000
.\.venv\Scripts\jbudget summary --month 2026-09     # résumé d'un mois
.\.venv\Scripts\jbudget todo                        # marchands encore « À classer »
.\.venv\Scripts\jbudget rules list COLRUYT
.\.venv\Scripts\jbudget rules add "CHEZ MARIO" "Restaurants" --direction out
.\.venv\Scripts\jbudget reclassify
```

La base est `jbudget.db` dans le dossier courant (ou `--db chemin`, ou la variable `JBUDGET_DB`).
Réimporter un fichier ne crée pas de doublons.

## Règles personnelles

Les règles qui contiennent des données privées (IBAN de tes comptes, noms de proches, commerces du quartier)
vont dans `rules.local.json`, ignoré par Git. Copie `rules.example.json` pour démarrer.
Ces règles sont ajoutées à la création de la base ; ensuite, on gère les règles depuis l'interface.

Les tests utilisent les relevés présents dans `data/` (ignoré par Git) et sont sautés s'il n'y en a pas.

## Comment une ligne est classée

1. Montant à 0,00 € → **Ignoré**.
2. Règles actives, de la plus haute priorité à la plus basse (à égalité, le motif le plus long) :
   règles manuelles 300, apprises 200, de départ 100 à 150.
3. Mémoire : la catégorie que tu as choisie à la main pour ce marchand (même sens entrée/sortie).
4. Sinon **À classer**.

Une transaction corrigée à la main est verrouillée : aucune règle ne la déplace ensuite.
Dans l'écran Transactions, changer une catégorie propose soit « seulement celle-ci »,
soit « créer une règle pour ce marchand », qui reclasse aussitôt les autres lignes.

## Statistiques

- Les paiements « Paiement ING : VISA » sont des **transferts** hors statistiques : le détail vient du PDF VISA.
- Le groupe **Épargne** (comptes perso, compte d'investissement, épargne des enfants) est affiché à part.
- Les remboursements Solidaris sont dans **Santé** et réduisent son total (coût net).

## Tests

```powershell
.\.venv\Scripts\python -m pytest
```
