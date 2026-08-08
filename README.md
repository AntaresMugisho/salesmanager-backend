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
| `/api/stock/transactions/` | GET, POST | gérant |
| `/api/stock/transactions/{id}/` | GET | — |
| `/api/stock/low-stock/` | GET | — |
| `/api/stock/dashboard/` | GET | — |
| `/api/customers/` `…/{id}/` | GET POST PATCH DELETE | gérant · DELETE propriétaire |
| `/api/sales/` | GET, POST | tous, caissier compris |
| `/api/sales/{id}/` | GET | — |
| `/api/sales/{id}/cancel/` | POST | gérant |
| `/api/sales/{id}/payments/` | POST | tous, caissier compris |
| `/api/expenses/` `…/{id}/` | GET POST PATCH DELETE | gérant |
| `/api/finance/summary/` `series/` `breakdown/` | GET | gérant |
| `/api/reports/result/` | GET | gérant |
| `/api/reports/sales/` | GET | gérant |
| `/api/reports/profitability/` | GET | gérant |
| `/api/reports/stock/` | GET | gérant |

Il n'y a pas de route d'archivage : `archiveArticle` côté frontend est un
`PATCH { isActive: false }`.

Une valeur de filtre invalide renvoie une 400 avec `fieldErrors`, plutôt que
d'être ignorée — un filtre silencieusement abandonné renvoie *plus* de lignes
que demandé tout en ressemblant à une réponse correcte.

## Transactions de stock

Une transaction regroupe plusieurs mouvements écrits ensemble : un seul type
et un seul motif s'appliquent à toutes les lignes. Elle est **immuable** — ni
`PATCH` ni `DELETE`, qui renvoient une 405. Corriger une transaction consiste
à en enregistrer une nouvelle, compensatoire.

Deux champs portent le mot « référence », et ils sont distincts :

| champ | contenu |
|---|---|
| `reference` | le numéro généré `TR-YYYY-NNNN` |
| `userReference` | le numéro de bon de livraison saisi par l'utilisateur, ou `null` |

Chaque mouvement de la transaction reçoit dans sa propre `reference` le numéro
saisi par l'utilisateur, ou à défaut le numéro `TR-` — un mouvement reste ainsi
rattachable à sa transaction depuis le journal.

La séquence repart à `0001` à chaque année civile, dans `SHOP_TIME_ZONE`. Elle
est allouée à l'intérieur de la transaction de base de données : une écriture
refusée annule aussi l'incrément, et **ne laisse donc aucun trou** dans la
numérotation.

## Ventes

Une vente **est** la facture : sa `reference` est le numéro `FA-YYYY-NNNN`,
alloué depuis la même séquence annuelle que les `TR-` des transactions. Une
vente refusée n'y laisse aucun trou.

Elle est immuable, à une exception près : l'**annulation**. Celle-ci ne
supprime aucun mouvement — le stock est rendu par un mouvement compensatoire
`IN` / `RETURN` portant la même vente, ce qui permet au journal d'afficher les
deux moitiés. **L'argent déjà encaissé n'est pas remboursé** ici ; le frontend
l'affiche comme « Remboursement dû ».

Trois champs ne sont **jamais stockés** et sont recalculés à chaque lecture :

| champ | règle |
|---|---|
| `paidAmount` | somme des paiements |
| `balance` | 0 si la vente est annulée, sinon `total − paidAmount`, plancher à 0 |
| `paymentStatus` | `UNPAID` / `PARTIAL` / `PAID`, dérivé des deux ci-dessus |

Une colonne de statut serait une seconde source de vérité, libre de contredire
les paiements qu'elle prétend résumer. Une vente annulée n'apparaît dans aucun
filtre `?paymentStatus=` : personne ne doit rien dessus.

Chaque ligne fige le nom, la référence, l'unité, le prix, **le coût d'achat**
et le taux de TVA de l'article au moment de la vente. Reclasser ou réévaluer un
article ne réécrit donc jamais une vente déjà enregistrée — c'est ce qui permet
au sous-projet 6 de calculer une marge historique juste.

Les caissiers enregistrent les ventes et les encaissements : c'est la caisse.
Ils n'annulent pas.

## Charges et finances

Les trois lectures financières prennent un `from` et un `to` **obligatoires**
(bornes incluses) et renvoient des chiffres finis : le frontend ne fait plus
aucun calcul.

Trois points que l'on lit souvent de travers :

- **`receivables` et la liste des impayés ignorent la période.** Ce sont des
  chiffres « à ce jour », pas des chiffres de la période.
- **Un encaissement sur une vente annulée par la suite reste un
  encaissement.** L'argent a bel et bien été reçu ; l'annulation rend le
  stock, pas la monnaie.
- **La courbe de trésorerie cumulée repart de zéro** au premier point de la
  période. Elle répond à « qu'est-ce que cette période a fait à ma
  trésorerie », pas à « combien y a-t-il en caisse ».

Les libellés des points (« 12 juil. », « juil. 2026 ») proviennent d'une table
figée, transcrite depuis l'`Intl` du frontend : la locale française de Django
écrit « jan. » et « fév. » là où le contrat attend « janv. » et « févr. ».

Une charge est modifiable et supprimable, contrairement à une vente : rien ne
la référence, et c'est un relevé interne, pas un document remis à quelqu'un.

## Rapports

Quatre documents imprimables, mêmes bornes `from`/`to` que les lectures
financières, mêmes messages d'erreur : `parse_range` est partagé.

Chaque réponse porte un bloc `meta` avec la période demandée et un
`generatedAt`. L'en-tête et les chiffres viennent donc de la même réponse : un
document ne peut pas imprimer une période que ses chiffres ne couvrent pas.

Quatre points qui surprennent à la lecture du code :

- **Le compte de résultat ne recalcule rien.** Il appelle `summarise()` et
  `build_expense_breakdown()` d'`apps.finance`. C'est aussi vrai des quatre
  chiffres que le rapport des ventes partage avec lui et des fonctions par
  ligne du rapport de rentabilité. Les trois documents et `/finances` ne
  peuvent donc pas se contredire sur une même période — des tests le
  vérifient de bout en bout, pas contre des constantes.
- **Le rapport de stock porte deux dates.** `categories` et `stockTotals`
  décrivent le stock à `generatedAt` ; tout le reste couvre `range`. Un
  intervalle situé en 1999 renvoie quand même le stock d'aujourd'hui.
- **Un achat sans coût unitaire compte pour zéro**, jamais au prix du jour :
  le valoriser au prix actuel réécrirait ce que la période a réellement
  coûté. `withoutCostCount` garde l'omission visible.
- **Le nom et la référence d'un article viennent de l'instantané de la ligne
  de vente**, jamais du catalogue. Renommer un article ne réécrit pas ce
  qu'une période passée dit avoir vendu. Le catalogue ne sert qu'à retrouver
  la catégorie.

Le tri français passe par `apps/common/collation.py` : NFKD, marques
diacritiques retirées, casse repliée, plus une table de ligatures — Unicode ne
décompose pas « Œ », donc sans elle « Œufs » se classe après « Zeste ». Les
noms qui ne diffèrent que par un accent, une casse ou une ligature sont
départagés par l'identifiant, pas comme ICU ; c'est une limite documentée.

Le journal des mouvements n'est pas paginé : le contrat ne le prévoit pas et
un rapport est un document. Sur une longue période et une boutique active, la
réponse peut être volumineuse.

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
