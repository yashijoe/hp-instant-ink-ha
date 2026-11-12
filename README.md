# HP Instant Ink per Home Assistant

Integrazione locale per Home Assistant che tiene il conto delle pagine di un piano
**HP Instant Ink**: quante ne hai stampate periodo per periodo e quante ne accumuli.

Legge il contatore direttamente dalla stampante in rete locale, senza passare dal cloud HP.
Il conteggio per periodo di fatturazione, le pagine accumulate e lo storico sono calcolati
dall'integrazione a partire dal contatore totale della stampante.

## Stampanti supportate

Stampanti HP recenti con l'interfaccia web "CDM" su HTTPS (provata su **HP Envy 6100e**).
Le stampanti più vecchie, che espongono `DevMgmt/ProductUsageDyn.xml`, non sono supportate.

Per verificare la tua stampante senza installare nulla in Home Assistant:

```bash
pip install aiohttp
python scripts/check_printer.py 192.168.1.50
```

## Installazione

1. Copia la cartella `custom_components/hp_instant_ink` dentro `config/custom_components`
   di Home Assistant (oppure aggiungi questa repo a HACS come repository personalizzato).
2. Riavvia Home Assistant.
3. Vai in **Impostazioni → Dispositivi e servizi → Aggiungi integrazione → HP Instant Ink**.

## Configurazione

Tutti i valori si inseriscono a mano e si possono cambiare dopo dal pulsante **Configura**:

| Campo | Significato |
|---|---|
| Indirizzo IP della stampante | Es. `192.168.1.50` |
| Pagine incluse al mese | Le pagine del tuo piano (es. 50) |
| Massimo di pagine accumulabili | HP consente il triplo del piano (es. 150) |
| Giorno di rinnovo | Giorno del mese in cui inizia il periodo di fatturazione |
| Pagine e prezzo di ogni set aggiuntivo | Es. 10 pagine a 1,50 |
| Riporto dei set aggiuntivi | Se le pagine non usate di un set aggiuntivo passano al mese dopo |
| Pagine già stampate nel periodo | Solo alla prima configurazione, dal tuo account HP |
| Pagine accumulate a inizio periodo | Solo alla prima configurazione, dal tuo account HP |

Conviene assegnare alla stampante un indirizzo IP fisso dal router.

## Sensori

| Sensore | Cosa indica |
|---|---|
| Pagine totali stampate | Contatore a vita della stampante |
| Pagine stampate nel periodo | Pagine stampate dal giorno di rinnovo |
| Pagine del piano rimanenti | Pagine incluse non ancora usate |
| Pagine accumulate disponibili | Pagine accumulate dai mesi precedenti ancora utilizzabili |
| Pagine accumulate al rinnovo | Quante pagine accumulate avrai al prossimo rinnovo se smetti di stampare ora |
| Pagine gratuite rimanenti | Piano più accumulate |
| Pagine extra / Costo pagine extra | Pagine oltre piano e accumulate, e costo dei set aggiuntivi |
| Giorni al rinnovo / Prossimo rinnovo / Inizio periodo | Date del periodo |
| Pagine stampate nel periodo precedente | Con l'attributo `history`: lo storico dei periodi chiusi |
| Inchiostro nero / a colori | Livello delle cartucce |

## Storico mese per mese

A ogni rinnovo il periodo viene chiuso e salvato nello storico (attributo `history`
del sensore "Pagine stampate nel periodo precedente"), con:

- `printed`: pagine stampate nel periodo
- `accumulated`: pagine accumulate (o consumate, se negativo) in quel periodo
- `rollover_end`: totale di pagine accumulate a fine periodo
- `overage_pages`, `overage_cost`: pagine extra e relativo costo

Lo storico parte dal momento dell'installazione: i periodi precedenti non sono recuperabili
dalla stampante. Nella cartella `cards` trovi due card pronte, una con lo stato del periodo
e una con la tabella dello storico.

## Allineare i contatori

Se i valori non coincidono con quelli del tuo account HP, usa l'azione
`hp_instant_ink.adjust` da **Strumenti per sviluppatori → Azioni**:

```yaml
action: hp_instant_ink.adjust
data:
  printed_pages: 12
  rollover_pages: 30
```

## Sviluppo

I test della logica di calcolo girano ovunque:

```bash
pip install pytest
pytest tests/test_ledger.py
```

I test che caricano l'integrazione dentro Home Assistant richiedono Linux o macOS:

```bash
pip install pytest-homeassistant-custom-component
pytest
```
