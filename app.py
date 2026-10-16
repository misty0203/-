import os, random, time, tempfile, collections, csv, io
from pathlib import Path
import streamlit as st
import core

st.set_page_config(page_title='甲衛備考｜手機診斷版', page_icon='📘', layout='centered', initial_sidebar_state='collapsed')
st.markdown('''<style>
.block-container{max-width:760px;padding-top:1rem;padding-left:1rem;padding-right:1rem;padding-bottom:5rem}
h1{font-size:1.55rem!important;line-height:1.35!important}h2,h3{font-size:1.2rem!important}
div[data-testid="stMetric"]{background:#f5f7fa;border-radius:12px;padding:10px}
div[data-testid="stRadio"] label{padding:7px 0}
.stButton>button,.stDownloadButton>button,div[data-testid="stFormSubmitButton"]>button{min-height:44px;width:100%;border-radius:10px}
</style>''', unsafe_allow_html=True)
try:
    CLOUD = st.secrets.get('STREAMLIT_SHARING_MODE', '') == 'demo'
except (FileNotFoundError, KeyError):
    CLOUD = os.environ.get('STREAMLIT_SHARING_MODE') == 'demo'
# Each cloud visitor receives an independent, temporary database. No account and no durable cloud storage.
if 'db_path' not in st.session_state:
    if CLOUD:
        tempdir = tempfile.mkdtemp(prefix='oh_exam_session_')
        st.session_state.db_path = str(Path(tempdir) / 'study.db')
    else:
        st.session_state.db_path = str(Path(__file__).with_name('study.db'))
DB = st.session_state.db_path
core.init(DB)
qs = core.get_questions(DB)
ats = core.attempts(DB)
eligible_qs = [q for q in qs if core.eligible(q)]

st.title('📘 甲衛甲級｜診斷與補強')
st.caption('手機測試 V3 · B 模式：先診斷 → 看解析 → 錯題補強')
if CLOUD:
    st.warning('☁️ 公開測試模式：每個瀏覽器工作階段使用獨立暫存題庫；重啟、閒置斷線或重新連線可能遺失紀錄。請勿輸入姓名、個資或機密資料。')
else:
    st.info('💾 本機模式：紀錄儲存在程式資料夾 study.db。')
st.warning('目前只有 3 道經公式驗算的自編數值題可計分，沒有官方歷屆原題。這不是完整甲衛考試能力評估；「計算已驗證」不等於持證專家人工審核。')

PAGES = ['首頁與診斷','章節練習','錯題補強','弱點分析','題庫來源','紀錄匯出']
page = st.selectbox('功能選單', PAGES, label_visibility='collapsed')

def source(q):
    st.caption(f"來源：{q['source_type']}｜狀態：{q['verification']}｜{q['source']}")
    if q.get('source_url'): st.link_button('查閱來源法規（外部網站）', q['source_url'])
    if q.get('law_reference'): st.write('法規依據：', q['law_reference'])
    if q.get('law_version'): st.caption('法規版本註記：' + q['law_version'])
    if q.get('verification_note'): st.caption('驗證紀錄：' + q['verification_note'])

def explanation(q):
    st.markdown('**參考答案：** ' + str(q['answer']))
    st.markdown('**解析：** ' + str(q['explanation']))
    source(q)

def answer_widget(q, key):
    st.write(q['stem'])
    opts = q['options'].split('|') if q.get('options') else []
    if q['kind'] in ('單選','是非'):
        return st.radio('選擇答案',opts,index=None,key=key)
    if q['kind']=='複選':
        return '|'.join(v for v in opts if st.checkbox(v,key=key+v))
    if q['kind']=='申論': return st.text_area('作答（不自動給分）',key=key)
    return st.text_input('輸入答案（數值不加單位）',key=key)

def record(q, ans, mode):
    return core.save_attempt(q, ans or '', mode, DB)

if page=='首頁與診斷':
    a,b=st.columns(2)
    a.metric('題庫總數',len(qs)); b.metric('可計分題數',len(eligible_qs))
    scored=[x for x in ats if x['correct'] is not None]
    a,b=st.columns(2)
    a.metric('累積作答',len(scored))
    b.metric('正確率',f"{sum(x['correct'] for x in scored)/len(scored):.0%}" if scored else '—')
    st.subheader('正式難度診斷（示範）')
    if not eligible_qs: st.error('尚無已驗證題目');st.stop()
    count=st.slider('抽題數',1,len(eligible_qs),len(eligible_qs))
    if st.button('開始新測驗',type='primary'):
        st.session_state.exam_ids=random.sample([q['id'] for q in eligible_qs],count)
        st.session_state.exam_nonce=st.session_state.get('exam_nonce',0)+1
        st.session_state.exam_done=False
        st.session_state.exam_result=[]
        st.rerun()
    if st.session_state.get('exam_ids') and not st.session_state.get('exam_done'):
        with st.form('exam'):
            pairs=[]
            for i,qid in enumerate(st.session_state.exam_ids,1):
                q=next(q for q in eligible_qs if q['id']==qid)
                st.markdown(f'**第 {i} 題｜{q["topic"]}（{q["points"]} 分）**')
                ans=answer_widget(q,f'ex_{st.session_state.exam_nonce}_{i}')
                pairs.append((q,ans))
                st.divider()
            submit=st.form_submit_button('交卷並查看解析',type='primary')
        if submit:
            st.session_state.exam_result=[(q['id'],record(q,ans,'手機診斷')[0]) for q,ans in pairs]
            st.session_state.exam_done=True
            st.rerun()
    if st.session_state.get('exam_done'):
        result=st.session_state.exam_result
        score=sum(next(q for q in qs if q['id']==qid)['points'] for qid,ok in result if ok)
        maximum=sum(next(q for q in qs if q['id']==qid)['points'] for qid,_ in result)
        st.metric('本次成績',f'{score} / {maximum}')
        for qid,ok in result:
            q=next(q for q in qs if q['id']==qid)
            with st.expander(('✅' if ok else '❌')+' '+q['topic']+'｜'+q['stem'][:18],expanded=not ok): explanation(q)

elif page=='章節練習':
    topic=st.selectbox('章節',sorted(set(q['topic'] for q in qs)))
    choices=[q for q in qs if q['topic']==topic]
    q=st.selectbox('題目',choices,format_func=lambda x:f"#{x['id']}｜{x['kind']}｜{x['verification']}")
    st.caption('先作答再核對；待複核題目不納入正式計分。')
    with st.form(f'practice_{q["id"]}'):
        ans=answer_widget(q,f'p_{q["id"]}')
        submit=st.form_submit_button('提交答案')
    if submit:
        ok,feedback=record(q,ans,'章節練習')
        st.session_state.last_practice=(q['id'],ok,feedback)
    if st.session_state.get('last_practice') and st.session_state.last_practice[0]==q['id']:
        _,ok,feedback=st.session_state.last_practice
        st.success('答對') if ok is True else st.error('需要補強') if ok is False else st.warning('本題未通過正式計分驗證')
        st.write(feedback);explanation(q)

elif page=='錯題補強':
    wrong=core.wrong_questions(DB)
    if not wrong:st.success('目前沒有待補強的已評分錯題。')
    for q in wrong:
        with st.expander(f"#{q['id']}｜{q['topic']}｜{q['stem'][:20]}"):
            with st.form(f'retry_{q["id"]}'):
                ans=answer_widget(q,f'r_{q["id"]}')
                submit=st.form_submit_button('重新作答')
            if submit:
                ok,feedback=record(q,ans,'錯題補強')
                st.write('答對' if ok else '仍需補強',feedback)
                explanation(q)

elif page=='弱點分析':
    scored=[x for x in ats if x['correct'] is not None]
    stats=collections.defaultdict(lambda:[0,0]);byid={q['id']:q for q in qs}
    for a in scored:
        q=byid.get(a['question_id'])
        if q:stats[q['topic']][0]+=1;stats[q['topic']][1]+=a['correct']
    if not stats:st.info('請先完成診斷。')
    else:
        rows=[{'章節':k,'作答次數':v[0],'答對次數':v[1],'正確率':round(v[1]/v[0]*100,1)} for k,v in stats.items()]
        rows.sort(key=lambda x:x['正確率'])
        st.dataframe(rows,hide_index=True,use_container_width=True)
        st.bar_chart({x['章節']:x['正確率'] for x in rows})
        st.write('優先補強：', '、'.join(x['章節'] for x in rows[:3]))
        st.caption('題量極少，正確率只作為操作示範，不能預測考試成績。')

elif page=='題庫來源':
    st.subheader('題目驗證清單')
    for q in qs:
        with st.expander(f"#{q['id']}｜{q['verification']}｜{q['stem'][:22]}"):
            explanation(q)
    st.caption('本公開測試版不提供任意訪客修改官方驗證狀態的權限。正式題庫須有可查證的官方來源與審核紀錄。')

elif page=='紀錄匯出':
    st.write('測試結束請下載紀錄；雲端資料不保證保存。')
    out=io.StringIO();fields=['created_at','question_id','submitted','correct','score','max_score','mode','feedback','verification_snapshot']
    writer=csv.DictWriter(out,fieldnames=fields);writer.writeheader()
    for a in ats:writer.writerow({k:a.get(k,'') for k in fields})
    st.download_button('下載學習紀錄 CSV',out.getvalue().encode('utf-8-sig'),'甲衛學習紀錄.csv',mime='text/csv')
    st.caption('如需保留題庫，可從 V2 本機管理版匯出 CSV，再經審核匯入正式系統。')
