"""Один изолированный адаптер без записи таблиц и без отправки уведомлений."""
import json
import logging
from pathlib import Path
import sys
from app.config import load_config
from app.integrations.matching import KnownIndex, MatchConfig
from app.integrations.sheets import fetch_country_records
from app.unified import SOURCES


def collect(source, config):
    logger=logging.getLogger('race_monitor.worker.'+source)
    country,label=SOURCES[source]
    if source.startswith('es_'):
        from app.sources.spanish_structured import scrape_source
        import os
        adapter='running_life' if source=='es_life' else 'rockthesport'
        settings=next(s for s in json.loads(os.environ['ES_SOURCES_JSON']) if s.get('adapter')==adapter)
        return [dict(e,country=country,source=label,_source_id=source) for e in scrape_source(settings,logger,max_pages=int(os.getenv('ES_MAX_PAGINATION_PAGES','120')))]
    from playwright.sync_api import sync_playwright
    from app.sources.source1_portugalruncalendar import scrape_source1
    from app.sources.source2_portugalrunning import scrape_source2
    rows=fetch_country_records(config.sheet_id,config.worksheet_name,config.google_credentials_path,logger,'pt',config.url_column)
    known=KnownIndex([r.get('WEBSITE','') for r in rows],MatchConfig(lang_prefixes=config.canonical_lang_prefixes,subpage_segments=config.subpage_segments,container_segments=config.container_segments,service_blocklist=config.service_page_blocklist,block_homepage=config.block_homepage,block_generic_forms=config.block_generic_forms,cross_platform_match=config.cross_platform_match,cross_platform_min_slug_len=config.cross_platform_min_slug_len,slug_stoplist=config.slug_stoplist,name_match=config.name_match),names=[r.get(k,'') for r in rows for k in config.race_name_columns])
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(headless=config.run_headless)
        context=browser.new_context(user_agent=config.user_agent)
        try:
            if source=='pt_calendar':
                values=scrape_source1(context,config.source1_url,config.source1_event_links,config.source1_next_button_selector,config.source1_coords_selector,config.source1_detail_links,config.timeout_ms,config.max_pagination_pages,config.opencage_base_url,config.opencage_api_key,config.opencage_delay_sec,logger)
            else:
                values=scrape_source2(context,config.source2_rest_url,config.source2_export_base,config.source2_ical_key,config.source2_event_links,config.timeout_ms,config.opencage_base_url,config.opencage_api_key,config.opencage_delay_sec,known,logger)
        finally:context.close();browser.close()
    return [dict(country=country,source=label,url=v[0],coords=v[1],name=v[2] if len(v)>2 else '',date='',city='',region='',_source_id=source) for v in values.values()]


if __name__=='__main__':
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(name)s %(message)s')
    source,output=sys.argv[1:];events=collect(source,load_config());Path(output).write_text(json.dumps(events,ensure_ascii=False));logging.info('%s: %d событий',source,len(events))
