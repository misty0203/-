import csv, io, json, sqlite3, datetime, math
from pathlib import Path
DB=Path(__file__).with_name('study.db')
FIELDS=['topic','kind','stem','options','answer','explanation','source','source_url','source_type','source_year','source_number','law_reference','law_version','verification','verification_note','points','tolerance','rubric']
VERIFICATIONS=['官方已核對','計算已驗證','待人工複核','答案有爭議']
TYPES=['官方原題','官方法規衍生題','自編計算題','AI補強題','自編概念題']
KINDS=['單選','複選','是非','數值','填空','申論']

def connect(db=DB):
 c=sqlite3.connect(db);c.row_factory=sqlite3.Row;return c

def init(db=DB):
 with connect(db) as c:
  c.execute('CREATE TABLE IF NOT EXISTS questions(id INTEGER PRIMARY KEY,topic TEXT,kind TEXT,stem TEXT,options TEXT,answer TEXT,explanation TEXT,source TEXT,points INTEGER DEFAULT 10)')
  c.execute('CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY,question_id INTEGER,submitted TEXT,correct INTEGER,score REAL,created_at TEXT,mode TEXT)')
  existing={r[1] for r in c.execute('PRAGMA table_info(questions)')}
  for field in FIELDS:
   if field not in existing:c.execute(f'ALTER TABLE questions ADD COLUMN {field} '+('REAL' if field=='tolerance' else 'TEXT'))
  existing_a={r[1] for r in c.execute('PRAGMA table_info(attempts)')}
  for field,typ in [('feedback','TEXT'),('verification_snapshot','TEXT'),('max_score','REAL')]:
   if field not in existing_a:c.execute(f'ALTER TABLE attempts ADD COLUMN {field} {typ}')
  c.execute('CREATE TABLE IF NOT EXISTS sessions(id INTEGER PRIMARY KEY,created_at TEXT,finished_at TEXT,question_ids TEXT,mode TEXT,seconds INTEGER,score REAL,max_score REAL)')
  c.execute("UPDATE questions SET verification='待人工複核' WHERE verification IS NULL OR verification='' ")
  c.execute("UPDATE questions SET source_type='自編概念題' WHERE source_type IS NULL OR source_type='' ")
  c.execute("UPDATE questions SET tolerance=0.001 WHERE tolerance IS NULL")
  if c.execute('SELECT COUNT(*) FROM questions').fetchone()[0]==0:
   for item in SEED:
    d={k:item.get(k,'') for k in FIELDS};d['points']=int(d['points'] or 10);d['tolerance']=float(d['tolerance'] or 0);validate(d)
    c.execute('INSERT INTO questions('+','.join(FIELDS)+') VALUES('+','.join('?' for _ in FIELDS)+')',[d[k] for k in FIELDS])

def validate(d):
 for k in ['topic','kind','stem','answer','explanation','source','source_type','verification']:
  if not str(d.get(k,'')).strip():raise ValueError(f'缺少必填欄位：{k}')
 if d['kind'] not in KINDS:raise ValueError('未知題型')
 if d['verification'] not in VERIFICATIONS:raise ValueError('未知驗證狀態')
 if d['source_type'] not in TYPES:raise ValueError('未知來源類型')
 if d['verification']=='官方已核對':
  if d['source_type']!='官方原題' or not d.get('source_url') or not d.get('source_number'):raise ValueError('官方已核對需官方原題、來源網址與原題號')
 if d['verification']=='計算已驗證' and d['kind']!='數值':raise ValueError('計算已驗證只適用數值題')
 if d['kind'] in ['單選','複選','是非'] and not d.get('options'):raise ValueError('選擇題須提供選項')
 if d['kind']=='數值':float(str(d['answer']).replace(',',''))
 if float(d.get('points') or 0)<=0:raise ValueError('配分須大於零')
 if float(d.get('tolerance') or 0)<0:raise ValueError('容許誤差不得為負')

def add_question(d,db=DB):
 d={k:d.get(k,'') for k in FIELDS};d['points']=int(d['points'] or 10);d['tolerance']=float(d['tolerance'] or 0)
 validate(d)
 with connect(db) as c:
  cur=c.execute('INSERT INTO questions('+','.join(FIELDS)+') VALUES('+','.join('?' for _ in FIELDS)+')',[d[k] for k in FIELDS]);return cur.lastrowid

def get_questions(db=DB):
 with connect(db) as c:return [dict(r) for r in c.execute('SELECT * FROM questions ORDER BY id')]

def eligible(q):return q['verification'] in ('官方已核對','計算已驗證') and q['kind']!='申論'

def grade(q,answer):
 kind=q['kind'];expected=str(q['answer']).strip();got=str(answer).strip()
 if kind=='申論':return None,'申論題需依配分規準人工複核，系統不自動宣稱正確'
 if not got:return False,'未作答'
 if kind=='數值':
  try:
   value=float(got.replace(',',''));target=float(expected.replace(',',''))
   tolerance=float(q.get('tolerance') or 0)
   ok=math.isfinite(value) and abs(value-target)<=tolerance+1e-9
   return ok,f'標準值 {target:g}，容許絕對誤差 ±{tolerance:g}；差值 {abs(value-target):g}'
  except ValueError:return False,'請輸入純數值；單位請依題幹判讀'
 if kind=='複選':return set(x.strip() for x in got.split('|') if x.strip())==set(x.strip() for x in expected.split('|') if x.strip()),'複選採全對才給分'
 return got.casefold()==expected.casefold(),'比對標準答案'

def save_attempt(q,answer,mode,db=DB):
 correct,feedback=grade(q,answer)
 if not eligible(q):
  correct=None;feedback='題目未達正式計分驗證門檻；僅供練習或人工複核'
 score=q['points'] if correct else (0 if correct is False else None)
 with connect(db) as c:c.execute('INSERT INTO attempts(question_id,submitted,correct,score,created_at,mode,feedback,verification_snapshot,max_score) VALUES(?,?,?,?,?,?,?,?,?)',(q['id'],answer,None if correct is None else int(correct),score,datetime.datetime.now().isoformat(timespec='seconds'),mode,feedback,q['verification'],q['points']))
 return correct,feedback

def attempts(db=DB):
 with connect(db) as c:return [dict(r) for r in c.execute('SELECT * FROM attempts ORDER BY id DESC')]

def wrong_questions(db=DB):
 qs={q['id']:q for q in get_questions(db)};latest={}
 for a in attempts(db):
  if a['question_id'] not in latest and a['correct'] is not None:latest[a['question_id']]=a
 return [qs[k] for k,a in latest.items() if a['correct']==0 and k in qs]

def import_csv(blob,db=DB):
 data=list(csv.DictReader(io.StringIO(blob.decode('utf-8-sig'))))
 if not data:raise ValueError('CSV 沒有資料')
 for idx,d in enumerate(data,2):
  try:validate({**{k:'' for k in FIELDS},**d,'points':d.get('points') or 10})
  except Exception as e:raise ValueError(f'第 {idx} 列：{e}')
 # transaction prevents partial imports
 with connect(db) as c:
  for d in data:
   d={k:d.get(k,'') for k in FIELDS};d['points']=int(d['points'] or 10);d['tolerance']=float(d['tolerance'] or 0)
   c.execute('INSERT INTO questions('+','.join(FIELDS)+') VALUES('+','.join('?' for _ in FIELDS)+')',[d[k] for k in FIELDS])
 return len(data)

LAW='https://law.moj.gov.tw/LawClass/LawAll.aspx?PCODE=N0060004'
SEED=[
 dict(topic='暴露評估',kind='數值',stem='某物質暴露4小時80 ppm、2小時120 ppm、2小時60 ppm，求全8小時TWA（ppm）。',options='',answer='85',explanation='依第4條：TWA=(80×4+120×2+60×2)/8=85 ppm。這只是平均濃度；判斷合規仍須對照物質的容許濃度及其他限制。',source='依《勞工作業場所容許暴露標準》第4條自編',source_url=LAW,source_type='自編計算題',law_reference='勞工作業場所容許暴露標準 第4條',law_version='114-04-11修正；注意附表部分116-01-01施行',verification='計算已驗證',verification_note='依明列時段加權，85 ppm；以單元測試驗算',points=10,tolerance=0.01),
 dict(topic='暴露評估',kind='數值',stem='兩種有害物假設適用相加效應，濃度/各自容許濃度分別為 30/100 與 40/80，求加成指數（無單位）。',options='',answer='0.8',explanation='依第9條且題設適用相加效應：30/100+40/80=0.30+0.50=0.80；是否超標須按該條判定。',source='依《勞工作業場所容許暴露標準》第9條自編',source_url=LAW,source_type='自編計算題',law_reference='勞工作業場所容許暴露標準 第9條',law_version='114-04-11修正',verification='計算已驗證',verification_note='以分數獨立驗算為0.8；前提為相加效應',points=10,tolerance=0.001),
 dict(topic='暴露評估',kind='數值',stem='某物質8小時容許濃度為 20 ppm，依第3條變量係數表，求其短時間時量平均容許濃度（ppm）。假設非「高」標記。',options='',answer='30',explanation='第3條：10以上未滿100，變量係數1.5，20×1.5=30 ppm；短時間暴露是任何連續15分鐘的平均，不是瞬時最高值。',source='依《勞工作業場所容許暴露標準》第3條自編',source_url=LAW,source_type='自編計算題',law_reference='勞工作業場所容許暴露標準 第3條',law_version='114-04-11修正',verification='計算已驗證',verification_note='20×1.5=30；需排除「高」標記',points=10,tolerance=0.001),
 dict(topic='暴露評估',kind='單選',stem='依《勞工作業場所容許暴露標準》，哪一項最能正確說明第8條的暴露控制要求？',options='只要8小時平均合格，任何15分鐘暴露都可超標|8小時平均、15分鐘平均及最高容許濃度均須分別符合適用要求|只需符合最高容許濃度|只要員工無症狀即視為符合',answer='8小時平均、15分鐘平均及最高容許濃度均須分別符合適用要求',explanation='第8條分別規範全程工作日TWA、任一連續15分鐘TWA與任何時間最高容許濃度。注意個別物質是否適用各種限值。',source='依《勞工作業場所容許暴露標準》第8條自編',source_url=LAW,source_type='自編概念題',law_reference='勞工作業場所容許暴露標準 第8條',law_version='114-04-11修正',verification='待人工複核',verification_note='有正式法規依據，但非官方原題；需人工逐字複核後才納入正式計分',points=10,tolerance=0),
 dict(topic='暴露評估',kind='是非',stem='作業環境中有兩種以上有害物時，不論效應如何，均必須直接套用相加效應公式。',options='是|否',answer='否',explanation='第9條有前提：相互間效應非屬相乘效應或獨立效應時，才視為相加效應。',source='依《勞工作業場所容許暴露標準》第9條自編',source_url=LAW,source_type='自編概念題',law_reference='勞工作業場所容許暴露標準 第9條',law_version='114-04-11修正',verification='待人工複核',verification_note='非官方原題；待人工確認題幹無歧義',points=10,tolerance=0),
]
