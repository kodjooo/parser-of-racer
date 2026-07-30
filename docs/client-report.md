# Race Monitor — summary of changes

## What was improved (deduplication)

The monitor used to flag a race as "new" only when its **exact URL** was not in
the RACES sheet. The same real race often appears under slightly different links,
so duplicates kept landing in *Missing races*. We added smarter matching:

- **A — same site, different link.** Treats parent/child URLs and `/pt/`
  language-prefix differences as the same race
  (e.g. `…/corrida-s-joao/` = `…/corrida-s-joao/…-2026/`).
- **B — cross-platform / sub-domain.** Same event registered on different
  platforms is recognised by event slug/ID
  (e.g. `nativewarriors.pt/…` = `waitastart.com/…`; `bol.pt` sub-domains).
- **N — match by event name.** Same event is now matched by its **name + year**,
  using both the English and Portuguese names from the RACES sheet
  (e.g. "Trilho do Minério 2026"). This catches duplicates that no URL check could.
- **D — junk pages filtered out.** Homepages, organiser pages, generic Google
  Forms and service pages are no longer added.
- **New-year editions are kept.** A 2026 edition is still added even if the 2025
  edition exists (the year is always part of the match).

## Important: Source 2 was broken — results were understated

While working on this we found that **Source 2 (portugalrunning.com) had stopped
working**. The website redesigned its calendar and **removed the month
pagination**, so the monitor could only ever see the *current month* and silently
missed everything further ahead. This means **previous runs were undercounted** —
events from Source 2's future months were simply not included.

**This is now fixed.** Source 2 was switched to the site's official event feed
(iCal export), which returns the **complete forward calendar** in one reliable
request. We verified it:

- Full forward calendar now retrieved (**~335 upcoming events across all months**,
  vs. only the current month before).
- Cross-checked 1:1 against the website's visible month — **0 discrepancies**.

## Verified live

A full end-to-end run over **both sources** was executed successfully (events
written to *Missing races*, Telegram notification sent, **no errors**). All the
matching rules above were confirmed working on real data.

## Please verify on your side

Because Source 2 was previously missing most of its events, the next results will
include **many more races than before** — this is expected and correct. Please
review the *Missing races* sheet and confirm the entries look right, especially:

1. That the previously-missing Source 2 events now appear.
2. That the remaining entries are genuinely new (not duplicates of races already
   in RACES).
