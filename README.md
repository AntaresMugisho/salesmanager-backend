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

Les lignes « Utilisateurs », « Paramètres », « Catalogue » et « Mouvements de
stock » sont appliquées ; les autres arrivent avec leur sous-projet. La
suppression définitive (`DELETE`) est toujours réservée au propriétaire, y
compris sur le catalogue, où l'écriture est ouverte au gérant.

## Endpoints

Toutes les routes exigent une authentification. Le slash final est
**obligatoire** : `POST /api/auth/login` (sans slash) renvoie une 301, et
`fetch` rétrograde alors la requête en GET.

| Route | Méthodes | Écriture réservée à |
|---|---|---|
| `/api/auth/login/` `refresh/` `logout/` `me/` | POST, GET | — |
| `/api/settings/` | GET, PATCH | propriétaire |
| `/api/users/` `…/{id}/` | GET POST PATCH DELETE | propriétaire |
| `/api/categories/` `…/{id}/` | GET POST PATCH DELETE | gérant · DELETE propriétaire |
| `/api/suppliers/` `…/{id}/` | GET POST PATCH DELETE | gérant · DELETE propriétaire |
| `/api/articles/` `…/{id}/` | GET POST PATCH DELETE | gérant · DELETE propriétaire |
| `/api/stock/movements/` | GET, POST | gérant |
| `/api/stock/low-stock/` | GET | — |
| `/api/stock/dashboard/` | GET | — |

Il n'y a pas de route d'archivage : `archiveArticle` côté frontend est un
`PATCH { isActive: false }`.

Une valeur de filtre invalide renvoie une 400 avec `fieldErrors`, plutôt que
d'être ignorée — un filtre silencieusement abandonné renvoie *plus* de lignes
que demandé tout en ressemblant à une réponse correcte.

## Fuseau horaire

`TIME_ZONE` reste `UTC` : tout est stocké en UTC. `SHOP_TIME_ZONE`
(défaut `Africa/Kinshasa`, réglable dans `.env`) sert **uniquement** à
interpréter les dates calendaires du client — `?dateFrom=2026-07-01`,
`?dateTo=`, et « aujourd'hui » sur le tableau de bord.

Sans ce réglage, un mouvement saisi à 00h30 à Goma serait comptabilisé la
veille : c'est 23h30 UTC.

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
