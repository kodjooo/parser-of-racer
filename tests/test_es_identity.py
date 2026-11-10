import copy
import json
import logging
from unittest.mock import Mock
import pytest
from app.es_identity import enrich_identities, identity_urls, rock_identity
from app.spain import select_new_events
from app.unified import event_key, was_notified

LIFE='https://running.life/es/carrera/prueba'
ROCK='https://web.rockthesport.com/es/event/prueba-2027'
DATE='2027-01-30'


def pair():
    return [dict(country='Spain',source='Running.life',name='Prueba',date=DATE,url=LIFE,city='Madrid',coords='40.5, -3.8'),
            dict(country='Spain',source='RockTheSport',name='Prueba 2027',date=DATE,url=ROCK,city='',coords='40.4, -3.7')]


def page(date=DATE,href=ROCK,label='Inscripción',url=LIFE):
    data={'@type':'SportsEvent','name':'Prueba','url':url,'startDate':date,'location':{'address':{'addressCountry':'ES'}}}
    return '<script type="application/ld+json">'+json.dumps(data)+'</script><a href="'+href+'"><span>'+label+'</span></a>'


def resolve(events=None,html=None,cache=None,now=1000000):
    session=Mock();response=Mock(status_code=200,text=html or page(),content=b'html');session.get.return_value=response
    source=events or pair();before=copy.deepcopy(source)
    enriched,report=enrich_identities(source,cache if cache is not None else {},logging.getLogger(),session=session,now=now)
    assert source==before
    return enriched,report,session


def test_explicit_registration_beats_inaccurate_coordinates():
    events,report,session=resolve()
    assert report['confirmed_pairs']==1 and len(select_new_events(events,[]))==1
    session.get.assert_called_once_with(LIFE,timeout=20,allow_redirects=False)


@pytest.mark.parametrize('html',[page(date='2026-01-30'),page(href=ROCK+'-other'),page(label='Eventos cercanos'),page(url=LIFE+'-other')])
def test_uncertain_or_wrong_edition_link_never_merges(html):
    events,report,_=resolve(html=html)
    assert report['confirmed_pairs']==0 and len(select_new_events(events,[]))==2


def test_reused_url_for_different_year_stays_separate():
    events=pair();events.append(dict(events[0],date='2026-01-30'))
    enriched,_,_=resolve(events)
    assert len(select_new_events(enriched,[]))==2
    assert not identity_urls(enriched[-1])


def test_confirmation_cache_reused_and_expired_cache_refetched():
    cache={};resolve(cache=cache)
    _,report,session=resolve(cache=cache,now=1000001)
    session.get.assert_not_called();assert report['confirmed_pairs']==1
    _,report,session=resolve(cache=cache,now=1000000+8*86400)
    assert session.get.call_count==1


def test_network_failure_keeps_both_and_retries_after_negative_ttl():
    cache={};session=Mock();session.get.side_effect=RuntimeError('unavailable')
    events,report=enrich_identities(pair(),cache,logging.getLogger(),session=session,now=1000000)
    assert report['unresolved_pairs']==1 and len(select_new_events(events,[]))==2
    _,report,session=resolve(cache=cache,now=1000001);session.get.assert_not_called()
    _,report,session=resolve(cache=cache,now=1000000+86401);assert session.get.call_count==1 and report['confirmed_pairs']==1


def test_alternative_url_matches_races_and_preserves_notification_history():
    events,_,_=resolve()
    known=[{'COUNTRY':'Spain','WEBSITE':ROCK,'EVENT START DATE':DATE}]
    assert select_new_events(events,known)==[]
    state={'notified':{event_key(pair()[1]):{'source':'old'}}};before=copy.deepcopy(state)
    assert was_notified(events[0],state) and state==before
    different_year=[{'COUNTRY':'Spain','WEBSITE':ROCK,'EVENT START DATE':'2026-01-30'}]
    assert len(select_new_events(events,different_year))==1


def test_lookup_limit_and_unrelated_events_do_not_trigger_fetch():
    session=Mock();events,report=enrich_identities(pair(),{},logging.getLogger(),session=session,max_lookups=0)
    assert len(select_new_events(events,[]))==2 and report['lookups']==0
    unrelated=pair();unrelated[1]['name']='Another event 2027'
    enrich_identities(unrelated,{},logging.getLogger(),session=session);session.get.assert_not_called()


@pytest.mark.parametrize('url',['https://web.rockthesport.com.evil.test/es/event/prueba','http://web.rockthesport.com/es/event/prueba','https://user@web.rockthesport.com/es/event/prueba'])
def test_registration_identity_rejects_unapproved_urls(url):
    assert rock_identity(url) is None


def test_registration_normalizes_language_query_and_subpage():
    assert rock_identity('https://web.rockthesport.com/en/event/prueba-2027/registration?utm_source=test')==ROCK


def branded_pages(event_id='65813',date=DATE):
    brand='<iframe src="https://www.stay22.com/embed/gm?campaign=portada_'+event_id+'&amp;checkin='+date+'"></iframe>'
    rock=page(url=ROCK,date=DATE)+'<script>var event={"eventId":65813};</script>'
    return brand,rock


def test_branded_mychip_requires_matching_platform_id_and_edition():
    from app.es_identity import branded_event_id
    url='https://inscripciones.mychip.es/es/evento/prueba-2027'
    brand,rock=branded_pages()
    assert branded_event_id(brand,rock,url,ROCK,DATE)=='65813'
    wrong_id,_=branded_pages(event_id='99999')
    assert branded_event_id(wrong_id,rock,url,ROCK,DATE) is None
    wrong_year,_=branded_pages(date='2026-01-30')
    assert branded_event_id(wrong_year,rock,url,ROCK,DATE) is None
    assert branded_event_id(brand,rock,url+'-other',ROCK,DATE) is None
    assert branded_event_id(brand,rock+'<script>{"eventId":123}</script>',url,ROCK,DATE) is None


def test_branded_link_enriched_without_slug_only_guessing():
    url='https://inscripciones.mychip.es/es/evento/prueba-2027'
    brand,rock=branded_pages();session=Mock()
    def response(text):return Mock(status_code=200,text=text,content=b'html')
    session.get.side_effect=[response(page(href=url)),response(brand),response(rock)]
    events,report=enrich_identities(pair(),{},logging.getLogger(),session=session)
    assert report['lookups']==3 and report['confirmed_pairs']==1 and len(select_new_events(events,[]))==1


def test_proof_on_one_alias_covers_previously_notified_other_alias_both_orders():
    events,_,_=resolve()
    life_only={'notified':{event_key(pair()[0]):{}}}
    rock_only={'legacy_notified':{'es':{event_key(pair()[1]).split('|',1)[1]:{}}}}
    assert was_notified(events[1],life_only) and was_notified(events[0],rock_only)
    assert len(select_new_events(list(reversed(events)),[]))==1


def test_existing_geo_match_needs_no_detail_request():
    events=pair();events[1]['coords']=events[0]['coords'];session=Mock()
    enriched,report=enrich_identities(events,{},logging.getLogger(),session=session)
    session.get.assert_not_called();assert report['lookups']==0 and len(select_new_events(enriched,[]))==1


def test_changed_registration_target_invalidates_positive_cache():
    cache={};resolve(cache=cache)
    events=pair();events[1]['url']+='-new'
    enriched,report,session=resolve(events,html=page(href=events[1]['url']),cache=cache,now=1000001)
    session.get.assert_called_once();assert report['confirmed_pairs']==1 and len(select_new_events(enriched,[]))==1
