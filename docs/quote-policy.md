# Politica delle quote

Il progetto separa sempre due concetti:

1. **Probabilita stimata dal modello**: deriva dai dati statistici e non da un singolo bookmaker.
2. **Quota di riferimento**: serve per confrontare il prezzo disponibile sul mercato con la probabilita stimata.

## Fonte iniziale

Nella prima fase le quote storiche arrivano dai file di Football-Data.co.uk. Quando disponibili, il sistema preferisce la **media di mercato** riportata nel dataset; in alternativa usa altre colonne disponibili e salva sempre la fonte effettivamente utilizzata.

Le quote visualizzate dal progetto **non devono essere considerate identiche alle quote Sisal**. Sisal, Betfair o altri operatori possono avere prezzi differenti e le quote possono cambiare rapidamente prima dell'inizio dell'evento.

## Informazione da mostrare sul futuro sito

> Le quote visualizzate provengono dalle fonti statistiche indicate e possono differire da quelle offerte da Sisal o da altri operatori. Verificare sempre la quota reale disponibile prima dell'evento.

## Regola per le segnalazioni

Una futura segnalazione non dovra limitarsi a mostrare una quota osservata. Dovra includere almeno:

- probabilita stimata dal modello;
- quota equa calcolata dal modello;
- quota minima accettabile;
- quota di riferimento rilevata;
- fonte della quota;
- data e ora della rilevazione, quando disponibili.

Esempio:

`Over 2.5 | Probabilita modello 61% | Quota equa 1,64 | Interessante da 1,75 | Quota di riferimento 1,82 | Fonte: mercato`

In questo modo il giudizio statistico rimane valido anche se la quota proposta da Sisal e leggermente diversa.
