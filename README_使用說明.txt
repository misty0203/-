甲衛 V4 個人雲端版｜GitHub 上傳說明
================================
本更新包製作日期：2026-10-17
此版本保留你目前 GitHub 的 core.py，不需手動貼上任何 Python 程式碼。

【上傳 3 個檔案】
請先解壓縮 ZIP，回到 GitHub 專案 misty0203/- 的根目錄。
透過「Add file → Upload files」一次選取：
  1. app.py          （覆蓋 GitHub 上原本的 app.py）
  2. cloud_store.py  （新增）
  3. questions.csv    （新增，原 100 題已轉為 V3 欄位格式）
提交到 main。原本的 core.py、requirements.txt 都保留不變。
注意：只上傳 ZIP 不會自動解壓，也不能讓 Streamlit 讀取內部程式。

【Streamlit Secrets 仍須本人填入】
SUPABASE_URL = "https://你的專案識別碼.supabase.co"
SUPABASE_SECRET_KEY = "sb_secret_這裡填入你已複製的完整密鑰"
APP_PASSWORD = "你自己設定的至少12字元登入密碼"
以上是範例，必須換成你真正的值才可執行；絕不可上傳 GitHub。
Streamlit 專案網址與金鑰不是我能代替你填入的私人憑證。

【現有資料的影響】
新版使用當次工作階段建立的乾淨 SQLite 暫存題庫，不再讀取舊的重複資料庫。
100 題會自動從 questions.csv 匯入，再加上原有 5 道示範題；
若題幹相同會跳過，因此總數大約 100～105 題。
舊有本機測驗紀錄不會自動搬進 Supabase；如果已有要保存的紀錄，
請先在舊版「紀錄匯出」下載 CSV 備份，再進行部署。
新版本的每次成功提交會寫入 Supabase 的 oh_exam_sessions、oh_exam_answers。
如果 Supabase 連線失敗，系統會停止答題，防止無聲遺失新作答。

【安全】
僅後端使用 Secret key；登入前不會執行任何雲端資料查詢。
APP_PASSWORD 是單人使用的簡易登入門檻，非企業級身分管理。
請勿在 GitHub 或聊天中張貼 Secret key。若懷疑外洩請到 Supabase 立即輪替。

【重要】
已建立的兩張 Supabase 資料表不需要再次執行建表 SQL。
題目仍是自編練習題，未經持證專家逐題獨立審核；不可視為官方考題。

【驗證流程】
1. Streamlit 部署完成後，確認會先要求個人密碼。
2. 登入後「題庫來源」確認 100～105 題左右，不再是 493 題。
3. 在「章節練習」提交 1 題，應出現儲存成功。
4. 進入「雲端紀錄」確認該筆紀錄與時間。
5. 登出、重新整理、重新登入，紀錄仍應存在。
6. 建議立即下載一份雲端 CSV 備份。
