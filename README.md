# StockManager — Backend

API Django/DRF de l'application de gestion de stock. Le contrat est défini
par `stockmanager-frontend` : les charges utiles sont en camelCase et les
messages d'erreur en français.

## Démarrage

```bash
python -m pip install -r requirements.txt
cp .env.example .env          # puis renseigner SECRET_KEY
python manage.py migrate
python manage.py bootstrap    # crée l'établissement et le propriétaire
python manage.py runserver
```

## Rôles

| | Propriétaire | Gérant | Caissier |
|---|---|---|---|
| Utilisateurs et rôles | oui | — | — |
| Paramètres | oui | — | — |
| Catalogue : écriture | oui | oui | — |
| Catalogue : lecture | oui | oui | oui |
| Mouvements de stock | oui | oui | — |
| Ventes et encaissements | oui | oui | oui |
| Annulation d'une vente | oui | oui | — |
| Dépenses, finances, rapports | oui | oui | — |

Seules les lignes réservées au propriétaire sont appliquées dans le
sous-projet 1 ; les autres arrivent avec leur sous-projet.

## Conventions

Toute erreur est rendue sous la forme du type `ApiError` du frontend :

```json
{ "code": "validation_error",
  "message": "Les données envoyées sont invalides.",
  "fieldErrors": { "email": ["Cette adresse e-mail est déjà utilisée."] } }
```

Les paramètres de requête sont acceptés en camelCase
(`?pageSize=50&ordering=-createdAt`) via `CamelCaseQueryParamsMixin`.
La bibliothèque camel-case ne traduit **pas** les valeurs de tri : c'est
`apps/common/filters.py` qui s'en charge.

## Tests

```bash
python -m pytest
python -m pytest --cov=apps --cov-report=term-missing
```

## Documents

- Spécifications : `docs/superpowers/specs/`
- Plans d'implémentation : `docs/superpowers/plans/`
