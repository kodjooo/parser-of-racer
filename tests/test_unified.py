import copy
import datetime as dt
from types import SimpleNamespace
from unittest.mock import Mock
from app.unified import SOURCES,event_key,was_notified,merge_results,missing_events,digest_message,load_state,atomic_json,HEADERS,write_rows
from app.scheduler import next_due
from app.integrations.matching import MatchConfig


def event(country='Portugal',url='https://race.test/a-2026',name='Run 2026',date='2026-12-01'):
    return dict(country=country,source='source',url=url,name=name,date=date,city='Lisboa',coords='38.7,-9.1',region='')


def config():
    m=MatchConfig();return SimpleNamespace(**m.__dict__,canonical_lang_prefixes=m.lang_prefixes, service_page_blocklist=m.service_blocklist, race_name_columns=('RACE NAME','RACE NAME (PT)'))


def test_country_is_part_of_identity_and_known_matching():
    a=event();b=event('Spain');assert event_key(a)!=event_key(b)
    rows=[{'COUNTRY':'Spain','WEBSITE':a['url'],'RACE NAME':a['name'],'EVENT START DATE':'2026-12-01'}]
    assert missing_events([a,b],rows,config())==[a]


def test_old_history_still_suppresses_existing_notifications(tmp_path):
    from app.integrations.url_normalize import normalize_url
    a=event();s=load_state(tmp_path/'new.json');s['legacy_notified']['pt'][normalize_url(a['url'])]={'source':'old'}
    assert was_notified(a,s) and not was_notified(event('Spain'),s)
    atomic_json(tmp_path/'new.json',s);assert load_state(tmp_path/'new.json')==s


def test_source_failure_preserves_only_its_previous_results_and_others_run():
    old=event();s={'sources':{'pt_calendar':{'events':[old],'last_success':'old'}}};visited=[]
    def collect(source):
        visited.append(source)
        if source=='pt_calendar':raise RuntimeError('unavailable')
        return [event('Spain' if source.startswith('es') else 'Portugal',url='https://race.test/'+source)]
    candidates,errors,counts=merge_results(s,collect,'now')
    assert visited==list(SOURCES) and old in candidates and list(errors)==['pt_calendar']
    assert s['sources']['pt_calendar']['last_success']=='old' and s['sources']['es_rock']['last_success']=='now'


def test_one_digest_contains_both_countries_and_failure():
    text=digest_message([event(),event('Spain')],[event()],{'pt_calendar':'bad <source>'},'https://example.test','2026-11-10')
    assert 'PT:' in text and 'ES:' in text and text.count('<a href=')==1 and '&lt;source&gt;' in text


def test_table_replaces_data_without_clear_and_preserves_tail_shape(monkeypatch):
    w=Mock();w.row_count=10;w.col_count=8;w.get_all_values.return_value=[HEADERS]+[['old']]*4;w.id=7
    book=Mock();book.worksheet.return_value=w
    assert write_rows(book,'Missing races',[event()],Mock())==7
    w.clear.assert_not_called();args=w.update.call_args.kwargs
    assert args['values'][0]==HEADERS and args['values'][1][0]=='Portugal' and args['values'][-1]==['']*8


def test_restart_does_not_repeat_completed_day_but_recovers_missed_day():
    now=dt.datetime(2026,11,10,12,tzinfo=dt.timezone.utc)
    assert next_due(now,0,15,'2026-11-10').day==11
    assert next_due(now,0,15,'2026-11-09')==now
    assert next_due(now,0,15,None).day==11
    before=now.replace(hour=0,minute=0)
    assert next_due(before,0,15,'2026-11-10').day==11


def test_telegram_marked_channel_is_resolved_correctly():
    from telethon.utils import resolve_id
    from telethon.tl.types import PeerChannel,PeerUser
    raw,typ=resolve_id(-1001234567890);assert raw==1234567890 and typ is PeerChannel
    raw,typ=resolve_id(1234567890);assert typ is PeerUser


def test_migration_preserves_original_metadata_and_both_lists():
    from app.migrate_unified import merge_legacy_history,legacy_events
    old={'notified':{'race.test/2026':{'first_seen_at':'old','source':'pt'}}}
    pt=legacy_events([['Источник','Ссылка','Координаты'],['portugalruncalendar.com','https://race.test/2026','38,-9']],'Portugal')
    es=legacy_events([['Источник','Ссылка','Название','Дата'],['Running.life','https://es.test/2026','Carrera','2026-12-01']],'Spain')
    state=merge_legacy_history(old,{'notified':{}},pt+es)
    assert state['legacy_history']['pt']==old and state['legacy_notified']['pt']['race.test/2026']['first_seen_at']=='old'
    assert sum(len(x['events']) for x in state['sources'].values())==2


def test_unexpected_empty_source_does_not_erase_previous_events():
    old=event();state={'sources':{'pt_calendar':{'events':[old],'last_success':'before'}}}
    rows,errors,_=merge_results(state,lambda source:[],'now')
    assert old in rows and 'pt_calendar' in errors and state['sources']['pt_calendar']['last_success']=='before'


def runtime_config(tmp_path):
    c=config();c.__dict__.update(worksheet_name='RACES',missing_worksheet_name='Missing races',google_credentials_path='key.json',sheet_id='book',state_path=str(tmp_path/'state.json'),dry_run=False,telegram_api_id=1,telegram_api_hash='test',telegram_session_path='session',telegram_session_string=None,telegram_target='@test')
    return c


def setup_runtime(monkeypatch,tmp_path):
    import app.unified as u
    c=runtime_config(tmp_path);book=Mock();book.worksheet.return_value.get_all_values.return_value=[['COUNTRY','WEBSITE']]
    monkeypatch.setattr(u.Credentials,'from_service_account_file',Mock())
    monkeypatch.setattr(u.gspread,'authorize',Mock(return_value=Mock(open_by_key=Mock(return_value=book))))
    monkeypatch.setattr(u,'collect_worker',lambda source,timeout:[event('Spain' if source.startswith('es') else 'Portugal',url='https://race.test/'+source,name=source+' 2026')])
    writer=Mock(return_value=9);sender=Mock();monkeypatch.setattr(u,'write_rows',writer);monkeypatch.setattr(u,'send_message',sender)
    monkeypatch.setenv('TELEGRAM_NOTIFICATIONS_ENABLED','true');monkeypatch.setenv('UNIFIED_REPORT_PATH',str(tmp_path/'report.json'))
    return u,c,writer,sender


def test_digest_sent_once_a_day_and_history_committed_only_after_delivery(monkeypatch,tmp_path):
    u,c,writer,sender=setup_runtime(monkeypatch,tmp_path)
    assert u.run_unified(c)==0 and u.run_unified(c)==0
    assert sender.call_count==1 and len(u.load_state(c.state_path)['notified'])==4


def test_failed_telegram_does_not_mark_events_as_notified(monkeypatch,tmp_path):
    import pytest
    u,c,writer,sender=setup_runtime(monkeypatch,tmp_path);sender.side_effect=RuntimeError('not delivered')
    with pytest.raises(RuntimeError):u.run_unified(c)
    s=u.load_state(c.state_path);assert s['notified']=={} and 'last_digest_date' not in s
    assert len(s['sources'])==4


def test_dry_run_never_writes_sheet_state_or_message(monkeypatch,tmp_path):
    u,c,writer,sender=setup_runtime(monkeypatch,tmp_path);c.dry_run=True
    assert u.run_unified(c)==0
    writer.assert_not_called();sender.assert_not_called();assert not __import__('pathlib').Path(c.state_path).exists()
