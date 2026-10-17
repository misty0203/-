"""甲衛個人備考系統 V5: GitHub 固定題庫 + Supabase 雲端作答紀錄。

Only server-side code sees the sb_secret_ key. Login happens before any cloud read/write.
Keep app.py, cloud_store.py, core.py, questions.csv in the same GitHub folder.
"""
import collections
import csv
import hashlib
import hmac
import io
import random
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st

import core
from cloud_store import CloudError, CloudStore, question_key

st.set_page_config(page_title='甲衛備考 V5｜專業情境題庫', page_icon='📘', layout='centered', initial_sidebar_state='collapsed')
st.markdown('''<style>
.block-container{max-width:760px;padding-top:1rem;padding-bottom:4rem}
h1{font-size:1.5rem!important}h2,h3{font-size:1.17rem!important}
div[data-testid="stMetric"]{background:#253044;border-radius:12px;padding:14px}
div[data-testid="stMetric"] *{color:#fff!important}
.stButton>button,.stDownloadButton>button,div[data-testid="stFormSubmitButton"]>button{min-height:43px;border-radius:10px}
</style>''', unsafe_allow_html=True)


def setting(name):
    try:
        return str(st.secrets.get(name, '')).strip()
    except (FileNotFoundError, KeyError):
        return ''


required = ('SUPABASE_URL', 'SUPABASE_SECRET_KEY', 'APP_PASSWORD')
missing = [name for name in required if not setting(name) or '填入' in setting(name) or '貼上' in setting(name) or '設定你' in setting(name)]
if missing:
    st.error('尚未設定完成 Streamlit Secrets：' + '、'.join(missing))
    st.info('請先在「管理應用 → Settings → Secrets」填入真正的專案網址、sb_secret 金鑰及個人密碼。請勿把金鑰放到 GitHub。')
    st.stop()
if len(setting('APP_PASSWORD')) < 12:
    st.error('APP_PASSWORD 至少需要 12 個字元，請在 Secrets 設定較長的個人密碼。')
    st.stop()

if not st.session_state.get('signed_in', False):
    st.title('🔒 甲衛備考｜個人登入')
    st.caption('私人雲端作答紀錄。輸入在 Streamlit Secrets 設定的 APP_PASSWORD。')
    with st.form('login_form'):
        entered = st.text_input('登入密碼', type='password')
        login = st.form_submit_button('登入', type='primary')
    if login:
        if hmac.compare_digest(entered, setting('APP_PASSWORD')):
            st.session_state.signed_in = True
            st.session_state.login_errors = 0
            st.rerun()
        else:
            st.session_state.login_errors = st.session_state.get('login_errors', 0) + 1
            st.error('密碼不正確。')
            if st.session_state.login_errors >= 5:
                st.warning('已多次輸入錯誤，請稍後再嘗試。')
    st.stop()

logout_col, info_col = st.columns([1, 4])
if logout_col.button('登出'):
    st.session_state.signed_in = False
    st.rerun()
info_col.caption('🔐 個人模式｜雲端紀錄連線中')

try:
    store = CloudStore(setting('SUPABASE_URL'), setting('SUPABASE_SECRET_KEY'))
    sessions, answers = store.history()
except CloudError as err:
    st.error(f'雲端連線尚未成功：{err}')
    st.warning('為防止作答紀錄遺失，雲端連線修復前暫停答題。')
    st.stop()

# Build a clean, temporary question catalog for this browser session.
# The old duplicate-filled SQLite file is not touched or deleted.
if 'v5_db_path' not in st.session_state:
    local_dir = tempfile.mkdtemp(prefix='oh_exam_v5_')
    path = Path(local_dir) / 'questions.db'
    try:
        core.init(str(path))  # Initialize schema, then remove seed exercises from this NEW TEMPORARY database only.
        with sqlite3.connect(str(path)) as db:
            db.execute('DELETE FROM questions')  # Does not touch Supabase or old study.db
        file = Path(__file__).with_name('questions.csv')
        if not file.is_file():
            raise RuntimeError('找不到 questions.csv，請將題庫 CSV 與 app.py 放在 GitHub 同一層。')
        core.import_csv(file.read_bytes(), str(path))  # De-duplicate by stem.
        st.session_state.v5_db_path = str(path)
    except Exception as err:
        st.error('題庫載入失敗：' + str(err))
        st.stop()
DB = st.session_state.v5_db_path
questions = core.get_questions(DB)
by_id = {q['id']: q for q in questions}
by_key = {question_key(q): q for q in questions}
eligible = [q for q in questions if core.eligible(q)]
scored = [a for a in answers if a['is_correct'] is not None]


def local_time(iso):
    try:
        date = datetime.fromisoformat(iso.replace('Z', '+00:00'))
        return date.astimezone(ZoneInfo('Asia/Taipei')).strftime('%Y-%m-%d %H:%M')
    except (ValueError, TypeError, AttributeError):
        return str(iso or '')


def show_reference(q):
    st.markdown('**標準答案：** ' + str(q.get('answer', '')))
    st.markdown('**解析：** ' + str(q.get('explanation', '')))
    st.caption(f"來源：{q.get('source','')}｜驗證：{q.get('verification','')}")
    if q.get('source_url'):
        st.link_button('查閱相關法規／來源', q['source_url'])
    if q.get('law_reference'):
        st.caption('法規依據：' + q['law_reference'])
    if q.get('verification_note'):
        st.caption('驗證註記：' + q['verification_note'])


def answer_widget(q, key):
    st.write(q['stem'])
    options = q['options'].split('|') if q.get('options') else []
    if q['kind'] in ('單選', '是非'):
        return st.radio('選擇答案', options, index=None, key=key)
    if q['kind'] == '複選':
        return '|'.join(opt for opt in options if st.checkbox(opt, key=key + opt))
    if q['kind'] == '申論':
        return st.text_area('作答（不自動評分）', key=key)
    return st.text_input('輸入答案（數值不加單位）', key=key)


def submit_answers(mode, items, started_at=None):
    try:
        return store.save_answers(mode, items, started_at=started_at)
    except CloudError as err:
        st.error('雲端儲存未確認成功：' + str(err))
        return None


st.title('📘 甲衛甲級｜115新修法專業情境題')
st.caption('V5 新修法專業情境題版｜題庫由 GitHub 自動載入｜作答紀錄儲存在 Supabase')
st.warning(f'{len(questions)}題均為自編模擬題，非官方歷屆原題。自動計分僅供教學練習；未經獨立持證技師逐題審定。115-2官方原卷尚未完成逐題比對。')
PAGES = ['首頁與診斷', '章節練習', '術科申論', '錯題補強', '弱點分析', '法規生效日', '題庫來源', '雲端紀錄']
page = st.selectbox('功能選單', PAGES, label_visibility='collapsed')

if page == '首頁與診斷':
    a, b = st.columns(2)
    a.metric('專業情境題庫總數', len(questions))
    b.metric('教學可計分題數', len(eligible))
    a, b = st.columns(2)
    a.metric('雲端累計計分作答', len(scored))
    b.metric('雲端正確率', f"{sum(bool(x['is_correct']) for x in scored)/len(scored):.0%}" if scored else '—')
    st.subheader('綜合診斷（非官方自編模擬）')
    st.caption('混合法規／承攬／監測／化學管理／噪音與通風／跨領域計算；不只抽容許濃度公式。')
    if not eligible:
        st.info('目前沒有可計分題目。')
    else:
        limit = min(30, len(eligible))
        count = st.slider('本次抽題數', 1, limit, min(10, limit))
        if st.button('開始新測驗', type='primary'):
            # Balanced-topic sampling to avoid domination by the longest chapter.
            groups = collections.defaultdict(list)
            for qq in eligible:
                groups[qq['topic']].append(qq['id'])
            selected = []
            categories = list(groups.keys())
            random.shuffle(categories)
            for cat in categories:
                if len(selected) >= count: break
                selected.append(random.choice(groups[cat]))
            remaining = [qq['id'] for qq in eligible if qq['id'] not in selected]
            selected.extend(random.sample(remaining, min(count - len(selected), len(remaining))))
            random.shuffle(selected)
            st.session_state.exam_ids = selected
            st.session_state.exam_nonce = st.session_state.get('exam_nonce', 0) + 1
            st.session_state.exam_done = False
            st.session_state.exam_started = datetime.now().astimezone().isoformat()
            st.session_state.exam_result = []
            st.rerun()
        if st.session_state.get('exam_ids') and not st.session_state.get('exam_done'):
            pairs = []
            with st.form('exam_form'):
                for i, qid in enumerate(st.session_state.exam_ids, 1):
                    q = by_id[qid]
                    st.markdown(f'**第 {i} 題｜{q["topic"]}（{q["points"]} 分）**')
                    response = answer_widget(q, f'ex_{st.session_state.exam_nonce}_{i}')
                    pairs.append((q, response))
                    st.divider()
                submitted = st.form_submit_button('交卷並存入雲端', type='primary')
            if submitted:
                result = submit_answers('手機診斷', pairs, st.session_state.get('exam_started'))
                if result:
                    session_id, graded = result
                    st.session_state.exam_result = graded
                    st.session_state.exam_session_id = session_id
                    st.session_state.exam_done = True
                    st.rerun()
        if st.session_state.get('exam_done'):
            results = st.session_state.exam_result
            score = sum(r['score'] or 0 for r in results)
            maximum = sum(r['possible'] or 0 for r in results)
            st.success('已寫入 Supabase 雲端紀錄。')
            st.metric('本次成績', f'{score:g} / {maximum:g}')
            for r in results:
                q = r['q']
                with st.expander(('✅' if r['correct'] else '❌') + '｜' + q['topic'] + '｜' + q['stem'][:24], expanded=r['correct'] is False):
                    st.write('你的答案：', r['submitted'] or '未作答')
                    show_reference(q)

elif page == '章節練習':
    topic = st.selectbox('選擇章節', sorted({q['topic'] for q in questions}))
    choices = [q for q in questions if q['topic'] == topic]
    q = st.selectbox('題目', choices, format_func=lambda item: f"#{item['id']}｜{item['kind']}｜{item['stem'][:40]}")
    st.caption('「自編教學核對」的選擇題會教學自動計分，但不是官方／持證技師審定分數；申論題須人工評閱。')
    with st.form('practice_form'):
        response = answer_widget(q, 'practice_' + str(q['id']))
        submit = st.form_submit_button('提交並存入雲端')
    if submit:
        result = submit_answers('章節練習', [(q, response)])
        if result:
            _, graded = result
            row = graded[0]
            st.session_state.practice_result = (question_key(q), row)
            st.success('作答已儲存。')
    last = st.session_state.get('practice_result')
    if last and last[0] == question_key(q):
        result = last[1]
        if result['correct'] is True:
            st.success('答對！')
        elif result['correct'] is False:
            st.error('需要補強。')
        else:
            st.warning('本題待人工複核，已保留作答但不計分。')
        st.write(result['feedback'])
        show_reference(q)

elif page == '術科申論':
    essays = [q for q in questions if q['kind'] == '申論']
    st.subheader('術科申論｜20分案例題')
    st.info('申論作答可寫入雲端供日後檢視，系統不會以關鍵字假裝人工評分。請對照參考擬答與配分規準自行檢核。')
    item = st.selectbox('選擇術科題', essays, format_func=lambda q: q['stem'][:38])
    with st.form('essay_case'):
        st.markdown(item['stem'])
        response = st.text_area('依術科答題格式分點作答（可留空補交）', height=240)
        send = st.form_submit_button('儲存本次申論至雲端', type='primary')
    if send:
        saved = submit_answers('術科申論', [(item, response)])
        if saved:
            st.success('申論答案已備存；不自動計分。')
            st.session_state.essay_saved = question_key(item)
    if st.button('顯示參考擬答與配分規準'):
        st.markdown('**參考擬答（自編，待持證技師審查）**')
        st.write(item['answer'])
        st.markdown('**20分參考配分規準**')
        st.write(item.get('rubric') or '待人工評閱')
        show_reference(item)

elif page == '錯題補強':
    latest = {}
    for answer in answers:
        key = answer['question_key']
        if key not in latest and answer['is_correct'] is not None:
            latest[key] = answer
    wrong = [by_key[key] for key, a in latest.items() if a['is_correct'] is False and key in by_key]
    if not wrong:
        st.success('雲端紀錄中目前沒有需要補強的已計分錯題。')
    for q in wrong[:80]:
        with st.expander(f"{q['topic']}｜{q['stem'][:26]}"):
            with st.form('retry_' + question_key(q)):
                response = answer_widget(q, 'retry_answer_' + question_key(q))
                submitted = st.form_submit_button('重新作答並存入雲端')
            if submitted:
                saved = submit_answers('錯題補強', [(q, response)])
                if saved:
                    _, result = saved
                    st.success('答對，補強成功！') if result[0]['correct'] else st.warning('尚未答對，請閱讀解析。')
                    show_reference(q)

elif page == '弱點分析':
    stat = collections.defaultdict(lambda: [0, 0])
    for a in scored:
        stat[a.get('topic') or '其他'][0] += 1
        stat[a.get('topic') or '其他'][1] += int(bool(a['is_correct']))
    if not stat:
        st.info('尚無雲端計分紀錄。完成診斷或章節練習後將自動分析。')
    else:
        rows = [
            {'章節': topic, '作答次數': val[0], '答對次數': val[1], '正確率％': round(val[1] / val[0] * 100, 1)}
            for topic, val in stat.items()
        ]
        rows.sort(key=lambda row: row['正確率％'])
        st.dataframe(rows, hide_index=True, use_container_width=True)
        st.bar_chart({row['章節']: row['正確率％'] for row in rows})
        st.write('優先補強：', '、'.join(row['章節'] for row in rows[:3]))

elif page == '法規生效日':
    st.subheader('115年7月1日修法：分期施行提醒')
    st.warning('題目以115年10月17日已生效規定為現行基準；延後生效部分會寫明日期。考試以應試當天法規及命題公告為準。')
    schedule = [
        {'法規/條次':'職業安全衛生法114年修正條文','生效':'115-07-01','備註':'包含工程風險、承攬告知、職場霸凌'},
        {'法規/條次':'職業安全衛生管理辦法（風險評估第12-1條）','生效':'115-07-01','備註':'工作前事前風險評估'},
        {'法規/條次':'營造安全衛生設施標準第11-2條','生效':'116-07-01','備註':'115-10尚未生效'},
        {'法規/條次':'工程安全設計及整體工程統合管理辦法部分條款','生效':'116-07-01／117-07-01','備註':'依附表三與各條核對'},
        {'法規/條次':'勞工作業環境監測實施辦法部分新條文','生效':'116-01-01','備註':'第6、10、13等部分條項／附表'},
        {'法規/條次':'勞工作業場所容許暴露標準部分附表','生效':'116-01-01','備註':'附表一部分項次、附表二'},
        {'法規/條次':'勞工健康保護規則部分條文','生效':'116-07-01／117-01-01','備註':'依第29條核對'},
        {'法規/條次':'化學品標示及通識規則部分新附表','生效':'118-01-01','備註':'第5條附表一、第12條附表四'},
    ]
    st.dataframe(schedule, hide_index=True, use_container_width=True)
    st.link_button('查看職安署修法分期施行官方說明','https://www.osha.gov.tw/48110/48713/207079/207115/207278/post')
    st.link_button('查看最近一次已公布的甲衛原卷索引','https://www.oshbon.com.tw/license/OshSkillTest/QuestionBank')
    st.caption('115-2原卷目前未能完整讀取，故不宣稱排除所有重複考點。')

elif page == '題庫來源':
    st.success('系統已從 GitHub 的 questions.csv 自動載入，無須再手動匯入。')
    st.write(f'本次去重後題庫：**{len(questions)} 題**；可計分：**{len(eligible)} 題**。')
    st.caption('原先重複匯入的本機 SQLite 資料庫不會被刪除；新版使用乾淨的題庫副本。')
    topic = st.selectbox('檢視章節', ['全部'] + sorted({q['topic'] for q in questions}))
    filtered = questions if topic == '全部' else [q for q in questions if q['topic'] == topic]
    total_pages = max(1, (len(filtered) + 19)//20)
    p = st.number_input('檢視頁數（每頁20題）', min_value=1, max_value=total_pages, value=1, step=1)
    for q in filtered[(p-1)*20:p*20]:
        with st.expander(f"#{q['id']}｜{q['verification']}｜{q['stem'][:31]}"):
            show_reference(q)

elif page == '雲端紀錄':
    st.subheader('雲端測驗與作答紀錄')
    st.metric('測驗／練習次數', len(sessions))
    st.metric('逐題作答總筆數', len(answers))
    answer_by_session = collections.defaultdict(list)
    for a in answers:
        answer_by_session[a['session_id']].append(a)
    for ses in sessions[:30]:
        time_str = local_time(ses.get('started_at'))
        maximum = ses.get('max_score') or 0
        score_text = f"{ses.get('total_score') or 0:g}/{maximum:g}" if maximum else '未計分'
        with st.expander(f"{time_str}｜{ses.get('mode','')}｜{score_text}"):
            entries = answer_by_session.get(ses['id'], [])
            for a in entries:
                correct = a.get('is_correct')
                st.write(('✅ ' if correct is True else '❌ ' if correct is False else '⏳ ') + str(a.get('question_text', '')))
                st.caption(f"你的答案：{a.get('user_answer') or '未作答'}｜標準答案：{a.get('expected_answer') or ''}")
    output = io.StringIO()
    names = ['作答時間(台灣)', '測驗模式', '題目', '章節', '你的答案', '標準答案', '是否正確', '得分', '滿分', '回饋']
    writer = csv.DictWriter(output, fieldnames=names)
    writer.writeheader()
    session_index = {ses['id']: ses for ses in sessions}
    for a in answers:
        s = session_index.get(a['session_id'], {})
        writer.writerow({
            '作答時間(台灣)': local_time(a.get('answered_at')),
            '測驗模式': s.get('mode', ''),
            '題目': a.get('question_text', ''),
            '章節': a.get('topic', ''),
            '你的答案': a.get('user_answer', ''),
            '標準答案': a.get('expected_answer', ''),
            '是否正確': '未計分' if a.get('is_correct') is None else '正確' if a['is_correct'] else '錯誤',
            '得分': a.get('earned_points'),
            '滿分': a.get('possible_points'),
            '回饋': a.get('feedback', ''),
        })
    st.download_button('備份所有雲端作答紀錄 CSV', output.getvalue().encode('utf-8-sig'),
                       '甲衛_雲端作答紀錄備份.csv', mime='text/csv')
    st.caption('Supabase 免費專案可能因長期閒置而暫停。建議每月下載備份；雲端保存不等於永久零風險。')
