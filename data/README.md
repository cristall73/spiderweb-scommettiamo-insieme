# Dati

Questa cartella conterrà i dataset usati dal progetto.

- `raw/`: file originali scaricati dalle fonti.
- `processed/`: dati puliti e uniformati.
- `output/`: risultati dei modelli, backtest e statistiche.

I file CSV generati non vengono salvati nella repository: possono essere ricreati automaticamente dagli script.

## Prima fonte scelta

Per la fase iniziale useremo Football-Data.co.uk, che mette a disposizione gratuitamente file CSV storici con risultati, statistiche di partita e quote pre-match/closing per numerosi campionati europei.

Prima di usare una colonna nel modello verrà verificato che l'informazione fosse disponibile prima del calcio d'inizio, per evitare look-ahead bias.
