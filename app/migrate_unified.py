"""Однократный перенос старых списков и истории без изменения основной RACES."""
import argparse
import copy
import json
import logging
from pathlib import Path
import uuid
import gspread
from google.oauth2.service_account import Credentials
from app.config import load_config
from app.unified import SOURCES,FIELDS,atomic_json,write_rows
from app.integrations.url_normalize import normalize_url


def source_id(label,country):
    text=label.lower().replace('https://','').replace('www.','')
    for key,(_,name) in SOURCES.items():
        if name.lower() in text or (key=='es_life' and 'running.life' in text):return key
    return None


def legacy_events(values,country):
    if not values:return []
    h=values[0];out=[]
    for raw in values[1:]:
        r=dict(zip(h,raw));url=r.get('Ссылка','')
        if not url:continue
        e=dict(zip(FIELDS,[country,r.get('Источник',''),r.get('Название',''),r.get('Дата',''),url,
                           r.get('Координаты',''),r.get('Регион',''),r.get('Город','')]))
        e['_source_id']=source_id(e['source'],country);out.append(e)
    return out


def merge_legacy_history(pt,es,events):
    state={'schema':1,'notified':{},'legacy_notified':{'pt':{},'es':{}},'sources':{}}
    state['legacy_history']={'pt':copy.deepcopy(pt),'es':copy.deepcopy(es)}
    for country,old in [('pt',pt),('es',es)]:
        for key,value in old.get('notified',{}).items():
            url,separator,date=key.partition('|')
            state['legacy_notified'][country][normalize_url(url)+(separator+date if separator else '')]=copy.deepcopy(value)
    state['legacy_rows']=[]
    for event in events:
        source=event.get('_source_id')
        if source:state['sources'].setdefault(source,{'events':[],'last_success':None})['events'].append(event)
        else:state['legacy_rows'].append(event)
    return state


def main():
    p=argparse.ArgumentParser();p.add_argument('--pt-state',required=True);p.add_argument('--es-state',required=True);p.add_argument('--apply',action='store_true');args=p.parse_args()
    c=load_config();statepath=Path(c.state_path)
    if statepath.exists():raise ValueError('Общая история уже существует; повторная миграция запрещена')
    credentials=Credentials.from_service_account_file(c.google_credentials_path,scopes=['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']);book=gspread.authorize(credentials).open_by_key(c.sheet_id)
    pt=book.worksheet('Missing races');es=book.worksheet('Missing races ES');pv=pt.get_all_values();ev=es.get_all_values();events=legacy_events(pv,'Portugal')+legacy_events(ev,'Spain')
    oldpt=json.loads(Path(args.pt_state).read_text());oldes=json.loads(Path(args.es_state).read_text());state=merge_legacy_history(oldpt,oldes,events)
    report={'pt_rows':len(legacy_events(pv,'Portugal')),'es_rows':len(legacy_events(ev,'Spain')),'pt_history':len(oldpt.get('notified',{})),'es_history':len(oldes.get('notified',{})),'legacy_unmapped_rows':len(state['legacy_rows'])}
    if args.apply:
        backup=statepath.parent/'migration-backup';backup.mkdir(parents=True,exist_ok=False)
        for name,value in [('pt-state',oldpt),('es-state',oldes),('pt-sheet',pv),('es-sheet',ev)]:atomic_json(backup/(name+'.json'),value)
        title='Missing races PT archive 20261110';sid=uuid.uuid4().int%1000000000+1000000000
        book.batch_update({'requests':[{'duplicateSheet':{'sourceSheetId':pt.id,'newSheetId':sid,'newSheetName':title}},{'updateSheetProperties':{'properties':{'sheetId':sid,'hidden':True},'fields':'hidden'}}]})
        gid=write_rows(book,'Missing races',events,logging.getLogger('migration'));assert gid==pt.id
        after=pt.get_all_values();assert len(after)==len(events)+1
        for row,event in zip(after[1:],events):
            assert row[0]==event['country'] and row[4]==event['url']
        formatting=[{'updateSheetProperties':{'properties':{'sheetId':pt.id,'gridProperties':{'frozenRowCount':1}},'fields':'gridProperties.frozenRowCount'}},
                    {'setBasicFilter':{'filter':{'range':{'sheetId':pt.id,'startRowIndex':0,'startColumnIndex':0,'endColumnIndex':8}}}},
                    {'repeatCell':{'range':{'sheetId':pt.id,'startRowIndex':0,'endRowIndex':1,'startColumnIndex':0,'endColumnIndex':8},'cell':{'userEnteredFormat':{'textFormat':{'bold':True},'backgroundColor':{'red':.88,'green':.94,'blue':1}}},'fields':'userEnteredFormat(textFormat,backgroundColor)'}}]
        for column,width in enumerate([110,180,420,120,400,180,160,160]):
            formatting.append({'updateDimensionProperties':{'range':{'sheetId':pt.id,'dimension':'COLUMNS','startIndex':column,'endIndex':column+1},'properties':{'pixelSize':width},'fields':'pixelSize'}})
        formatting.append({'updateSheetProperties':{'properties':{'sheetId':es.id,'title':'Missing races ES archive 20261110','hidden':True},'fields':'title,hidden'}})
        book.batch_update({'requests':formatting})
        atomic_json(statepath,state);report.update({'sheet_gid':gid,'pt_backup_gid':sid,'es_archive_gid':es.id,'legacy_history_preserved_exactly':state['legacy_history']=={'pt':oldpt,'es':oldes}})
        atomic_json(backup/'report.json',report)
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
