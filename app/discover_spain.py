"""Проверка согласованных источников без Google Sheets, Telegram и WordPress."""
import argparse
import json
import logging
from pathlib import Path
from app.sources.spanish_calendars import APPROVED_SOURCES
from app.sources.spanish_structured import scrape_source
from app.spain import select_new_events


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-pages", type=int, default=120)
    parser.add_argument("--known-json", help="Локальная копия строк RACES для проверки сравнения")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("discovery.es")
    candidates = []
    counts = {}
    for source in APPROVED_SOURCES:
        events = scrape_source(source, logger, max_pages=args.max_pages)
        counts[source["name"]] = len(events)
        candidates.extend(dict(event, source=source["name"]) for event in events)
    known = json.loads(Path(args.known_json).read_text()) if args.known_json else []
    new = select_new_events(candidates, known)
    report = {"source_counts": counts, "total_before_dedup": len(candidates),
              "new_count": len(new), "events": new}
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
    logger.info("Проверка завершена: %s", {k:v for k,v in report.items() if k != "events"})


if __name__ == "__main__":
    main()
