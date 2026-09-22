# Competitive landscape

Sellers competing with Forum Sport on the running and trail catalogue.
Generated from `dataset/Competidores_PricingDinamico.xlsx` by
`scripts/competitors_to_md.py` — regenerate rather than edit by hand.

**39 sellers · 389.469 records.**

> **What "records" counts is not defined in the source file.** It behaves
> like matched product listings or offers observed, not revenue and not
> visits. Treat it as relative presence, not market share.

## The market is top-heavy

| | Share of records |
|---|---|
| Top 1 | 31,0 % |
| Top 3 | 58,7 % |
| Top 5 | 75,2 % |
| Top 10 | 87,3 % |

The top 5 sellers carry **75,2 %** of all records and the top 10
**87,3 %**, so 29 of the 39 names are a long tail. Monitoring that
covers the top 10 covers most of the visible market.

## By type of seller

| Type | Sellers | Records | Share |
|---|--:|--:|--:|
| Especialista Deporte | 21 | 167.419 | 43,0 % |
| Comparador | 1 | 120.727 | 31,0 % |
| Retail Generalista | 4 | 77.723 | 20,0 % |
| Running Puro | 6 | 21.611 | 5,5 % |
| Marca | 7 | 1.989 | 0,5 % |

Two of these behave differently from the rest and are worth separating
before any pricing rule is written:

- **Google Shopping is a comparador, not a retailer.** It is the single
  largest line at 31 %, but it resells nothing — it is the surface where
  the others' prices are compared. Counting it as a competitor double-counts
  the sellers listed inside it. It is a *channel to monitor*, not a rival.
- **Tradeinn is an aggregate** of Runnerinn, Dressinn and Trekkinn, so its
  single line represents several storefronts.

## Brands that are also competitors

Every seller classified `Marca` sells a brand Forum Sport stocks — they
compete directly with their own retailer.

| Brand | D2C records | Models in catalogue | Average PVP |
|---|--:|--:|--:|
| Nike | 888 | 239 | 143,82 € |
| Adidas | 606 | 231 | 128,87 € |
| Salomon | 229 | 153 | 150,33 € |
| Helly Hansen | 105 | 19 | 149,47 € |
| Puma | 64 | 106 | 99,21 € |
| The North Face | 56 | 20 | 145,00 € |
| Under Armour | 41 | 7 | 136,71 € |

Those brands account for **775 of 1.483 models (52,3 %)** of the catalogue.
Their direct presence is small in records (0,5 % of the total) but it sets
the reference price for more than half of what Forum Sport sells: a brand's
own site is the price customers treat as official.

## All sellers

| # | Seller | Type | Records | Share | Site |
|--:|---|---|--:|--:|---|
| 1 | Google Shopping | Comparador | 120.727 | 31,0 % | [shopping.google.com](https://shopping.google.com) |
| 2 | Tradeinn (incl. Runnerinn, Dressinn, Trekkinn) | Especialista Deporte | 69.368 | 17,8 % | [tradeinn.com](https://www.tradeinn.com) |
| 3 | Deporvillage | Especialista Deporte | 38.600 | 9,9 % | [deporvillage.com](https://www.deporvillage.com) |
| 4 | Amazon | Retail Generalista | 32.830 | 8,4 % | [amazon.es](https://www.amazon.es) |
| 5 | Zalando | Retail Generalista | 31.330 | 8,0 % | [zalando.es](https://www.zalando.es) |
| 6 | El Corte Inglés | Retail Generalista | 12.780 | 3,3 % | [elcorteingles.es](https://www.elcorteingles.es) |
| 7 | Atmósfera Sport | Especialista Deporte | 10.461 | 2,7 % | [atmosferasport.es](https://www.atmosferasport.es) |
| 8 | Sprinter | Especialista Deporte | 10.132 | 2,6 % | [sprinter.es](https://www.sprinter.es) |
| 9 | Decathlon | Especialista Deporte | 7.891 | 2,0 % | [decathlon.es](https://www.decathlon.es) |
| 10 | SportsShoes | Running Puro | 5.926 | 1,5 % | [sportsshoes.com](https://www.sportsshoes.com) |
| 11 | Running Emotion | Running Puro | 5.586 | 1,4 % | [runningemotion.com](https://www.runningemotion.com) |
| 12 | Alltricks | Especialista Deporte | 5.258 | 1,4 % | [alltricks.es](https://www.alltricks.es) |
| 13 | Ekosport | Especialista Deporte | 4.931 | 1,3 % | [ekosport.es](https://www.ekosport.es) |
| 14 | RunningXpert | Running Puro | 4.105 | 1,1 % | [runningxpert.com](https://www.runningxpert.com) |
| 15 | i-Run | Running Puro | 3.970 | 1,0 % | [i-run.es](https://www.i-run.es) |
| 16 | Bike24 | Especialista Deporte | 3.824 | 1,0 % | [bike24.es](https://www.bike24.es) |
| 17 | Nencini Sport | Especialista Deporte | 2.985 | 0,8 % | [nencinisport.it](https://www.nencinisport.it) |
| 18 | Wala | Especialista Deporte | 2.871 | 0,7 % | [walashop.com](https://www.walashop.com) |
| 19 | JD Sports | Especialista Deporte | 1.898 | 0,5 % | [jdsports.es](https://www.jdsports.es) |
| 20 | Base | Especialista Deporte | 1.854 | 0,5 % | [base.net](https://www.base.net) |
| 21 | Bergfreunde | Especialista Deporte | 1.808 | 0,5 % | [bergfreunde.es](https://www.bergfreunde.es) |
| 22 | Tennis Point | Especialista Deporte | 1.634 | 0,4 % | [tennis-point.es](https://www.tennis-point.es) |
| 23 | Top4Running | Running Puro | 1.612 | 0,4 % | [top4running.es](https://top4running.es) |
| 24 | Barrabés | Especialista Deporte | 1.470 | 0,4 % | [barrabes.com](https://www.barrabes.com) |
| 25 | Viladomat | Especialista Deporte | 1.329 | 0,3 % | [viladomat.com](https://www.viladomat.com) |
| 26 | Nike | Marca | 888 | 0,2 % | [nike.com/es](https://www.nike.com/es) |
| 27 | ASOS | Retail Generalista | 783 | 0,2 % | [asos.com](https://www.asos.com) |
| 28 | Foot Locker | Especialista Deporte | 632 | 0,2 % | [footlocker.es](https://www.footlocker.es) |
| 29 | Adidas | Marca | 606 | 0,2 % | [adidas.es](https://www.adidas.es) |
| 30 | Running Warehouse | Running Puro | 412 | 0,1 % | [runningwarehouse.eu](https://www.runningwarehouse.eu) |
| 31 | Fútbol Emotion | Especialista Deporte | 406 | 0,1 % | [futbolemotion.com](https://www.futbolemotion.com) |
| 32 | Salomon | Marca | 229 | 0,1 % | [salomon.com/es-es](https://www.salomon.com/es-es) |
| 33 | Helly Hansen | Marca | 105 | 0,0 % | [hellyhansen.com/es_es](https://www.hellyhansen.com/es_es) |
| 34 | Puma | Marca | 64 | 0,0 % | [eu.puma.com/es/es](https://eu.puma.com/es/es) |
| 35 | The North Face | Marca | 56 | 0,0 % | [thenorthface.es](https://www.thenorthface.es) |
| 36 | Under Armour | Marca | 41 | 0,0 % | [underarmour.es](https://www.underarmour.es) |
| 37 | 11teamsports | Especialista Deporte | 37 | 0,0 % | [11teamsports.es](https://www.11teamsports.es) |
| 38 | Décimas | Especialista Deporte | 25 | 0,0 % | [decimas.com](https://www.decimas.com) |
| 39 | Basketball Emotion | Especialista Deporte | 5 | 0,0 % | [basketballemotion.com](https://www.basketballemotion.com) |

## Notes on the source

- URLs in the spreadsheet carried citation artifacts (`[tradeinn.com]`,
  a duplicated `[runningemotion.com]`); the generator strips them.
- Category labels are kept verbatim from the source, in Spanish.
- Several sellers are not Spanish storefronts (`nencinisport.it`,
  `sportsshoes.com`, `bike24.es`, `runningwarehouse.eu`), so shipping cost
  and delivery time sit between their listed price and the customer's real
  cost. A price-match rule that ignores that will chase prices that were
  never truly comparable.

## Why this matters for dynamic pricing

The catalogue analysis found the problem; this list constrains the fix.
**60,2 % of the lowest-stock tier is already discounted against a 55,6 %
catalogue average** — Forum Sport is discounting what it barely has.
Before a rule reprices against a rival, it needs to know:

1. **Which sellers count.** The top 10 cover 87,3 % of records;
   the tail mostly adds noise.
2. **Whether the rival is comparable.** A comparador, a cross-border seller
   and the brand's own site are three different kinds of reference price.
3. **Whether matching is worth it.** Margin is banded at 15/20/30/40 %, so on
   a *muy bajo* margin model there is very little room to follow a rival down.
