# How the current matching logic works

This describes exactly how the monitor decides whether a scraped race is "new"
(and therefore added to the **Missing races** sheet and sent to Telegram).

## Step by step

1. **Read known races.**
   The monitor reads the **RACES** sheet, takes the `WEBSITE` column, and builds
   a set of already-known race URLs (`known_urls`).

2. **Scrape the sources.**
   It scrapes the two sites (`portugalruncalendar.com`, `portugalrunning.com`)
   and collects a URL for each event found.

3. **Normalize every URL** (both the known ones and the scraped ones) using the
   same rules, so that trivial differences don't count as different races.

4. **Compare by exact match.**
   For each source: `new = scraped_urls − known_urls`.
   A scraped race is considered "new" **only if its normalized URL is not present
   in the normalized known set**. This is a plain set difference — exact string
   equality after normalization. There is no fuzzy/partial matching.

5. **Write & notify.**
   Everything classified as "new" is written to *Missing races* (with source and
   coordinates) and counted in the Telegram message.

## What normalization does

Two URLs are treated as the **same** race only if they become identical after
applying ALL of these rules:

| Rule | Example |
|---|---|
| Drop the scheme (`http`/`https`) | `https://x.pt/a` → `x.pt/a` |
| Drop a leading `www.` | `www.x.pt/a` → `x.pt/a` |
| Lower-case the **domain only** (path stays as-is) | `WWW.X.pt/A` → `x.pt/A` |
| Collapse repeated slashes in the path | `x.pt//a///b` → `x.pt/a/b` |
| Remove a single trailing slash | `x.pt/a/` → `x.pt/a` |
| Drop tracking params (`utm_*`, `fbclid`, `gclid`, `mc_cid`, `mc_eid`) | `x.pt/a?utm_source=fb` → `x.pt/a` |
| Sort remaining query params alphabetically | `x.pt/a?b=2&a=1` → `x.pt/a?a=1&b=2` |

## What normalization does NOT do (so these count as DIFFERENT races)

- **Different domain or sub-domain** — `waitastart.com/race` ≠ `nativewarriors.pt/race`;
  `www.bol.pt/...` ≠ `ultramelidestroia.bol.pt/...`
- **Different path depth** — `site/eventos/race` ≠ `site/eventos/race/inscritos`
- **Language prefix** — `site/eventos/race` ≠ `site/pt/eventos/race`
- **Different path text**, including the year — `.../race-2025` ≠ `.../race-2026`
- **Path letter case** — `/Trail-Mirante` ≠ `/trail-mirante`
- **Query-string differences** other than the few tracking params above
- The **event name / title** is never compared — matching is URL-only.

## Consequence

The same real-world race is treated as "new" whenever its URL differs in any of
the ways listed above. That is why events already present in RACES under a
slightly different link, a different platform, or a previous year's edition still
end up in *Missing races*.
