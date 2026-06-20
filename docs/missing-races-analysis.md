# Why some races were added to "Missing races" — analysis & decision needed

## Short version

The monitor decides whether a race is "new" by comparing its **exact URL**
against the URLs already in the **RACES** sheet (column `WEBSITE`). It only
ignores small cosmetic differences (`http`/`https`, `www.`, a trailing slash,
tracking parameters).

In the last run **117 races** were added to *Missing races*. Technically the
logic worked — **none of them is a byte-for-byte duplicate** of a `WEBSITE`
value in RACES. But in practice many of them **are the same event** that is
already in RACES, just reachable through a different link. Exact-URL matching
cannot see that.

Below are the real cases, grouped, so you can decide what "already known"
should mean.

---

## Category A — Same event, slightly different URL on the same site
**These are true duplicates the system should have caught.**

| Added to "Missing races" | Already in RACES | Difference |
|---|---|---|
| `runporto.com/pt/eventos/corrida-s-joao/` | `runporto.com/pt/eventos/corrida-s-joao/corrida-de-s-joao-2026/` | RACES has a deeper sub-page |
| `runporto.com/eventos/marginal-noite-esposende/` | `runporto.com/pt/eventos/marginal-noite-esposende/...-2026/` | missing `/pt/` prefix + deeper path |
| `portimer.pt/eventos/hygoes_2026` | `portimer.pt/eventos/hygoes_2026/inscritos` | RACES points to the `/inscritos` sub-page |
| `portimer.pt/eventos/tmz2026/` | `portimer.pt/eventos/tmz2026/inscritos` | same as above |
| `portimer.pt/eventos/corrida_gandra_2026/` | `portimer.pt/eventos/corrida_gandra_2026/inscritos` | same as above |

**Question for you:** treat URLs as the same when one is a parent/child of the
other, or when they differ only by a `/pt/` language prefix? (We recommend yes.)

---

## Category B — Same event, different website / sub-domain
**The same race is sold on two platforms; RACES has one, the monitor found the other.**

| Added to "Missing races" | Already in RACES | Difference |
|---|---|---|
| `nativewarriors.pt/evento/corrida-das-fogueiras-2026` | `waitastart.com/corrida-das-fogueiras-2026` | different registration platform, same race name |
| `queroir.pt/evento/rotadabroa2026` | `totalcrono.pt/eventos/rotadabroa2026` | different platform, same race id |
| `www.bol.pt/.../172727-corrida_atlantica_2026-troia_grandola/` | `ultramelidestroia.bol.pt/.../172727-corrida_atlantica_2026-...` | same ticket id `172727`, different sub-domain |

**Question for you:** should two different URLs count as the same race when the
event name / id matches? This is harder and more error-prone, but it is the only
way to catch cross-platform duplicates.

---

## Category C — Next year's edition of a recurring race
**Last year's edition is already in RACES; the monitor found this year's.**

| Added to "Missing races" | Already in RACES |
|---|---|
| `lap2go.com/pt/event/mm-ovar-2026` | `lap2go.com/pt/event/mm-ovar-2025` |
| `lap2go.com/pt/event/trail-dos-arrozais-2026` | `lap2go.com/pt/event/trail-dos-arrozais-2025` |
| `lap2go.com/pt/event/al-cor-race-fun-2026` | `lap2go.com/pt/event/al-cor-race-fun-2025` |
| `xistarca.pt/eventos/bimbo-global-race-2026` | `xistarca.pt/eventos/bimbo-global-race-2025` |
| `waitastart.com/meia-maratona-benedita-2026/` | `waitastart.com/meia-maratona-benedita-2025/` |

**Question for you:** is the 2026 edition a **new race that should be added**,
or the **same recurring race that should be ignored** because the 2025 edition is
already tracked? (Both are defensible — this is a business decision.)

---

## Category D — Service / index pages (not real races)
**A separate, smaller problem:** source `portugalruncalendar.com` stores the
"registration" child link, and when a real registration link is missing it falls
back to a site homepage or a service page. These should probably never be added.

Examples:
- `dourorun.pt/` (site homepage)
- `portugalrunning.com/organizadores-provas/` (organizers page)
- `docs.google.com/forms/d/e/.../viewform` (a generic Google Form)
- `timerspeed.com/?tribe_events=...` (calendar listing, not one event)

**Recommendation:** filter these out regardless of the decision above.

---

## What we need from you

1. **Category A** — accept parent/child and `/pt/`-prefix URLs as the same race? *(recommended: yes)*
2. **Category B** — also match by event name/id across different sites? *(more powerful, higher risk of false matches)*
3. **Category C** — is next year's edition a NEW race (add) or the SAME race (ignore)?
4. **Category D** — drop homepages / service pages / generic forms? *(recommended: yes)*

Once these four points are decided, the matching logic can be updated
accordingly and re-tested against the current sheet.
