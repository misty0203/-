"""甲衛私人雲端作答紀錄 — 只允許伺服器端使用 Supabase secret key。

Requires two PostgreSQL tables:
  public.oh_exam_sessions
  public.oh_exam_answers

API calls use 'apikey' header only for sb_secret keys, NOT Authorization: Bearer.
Never import or expose this module in browser-side JavaScript.
"""
from __future__ import annotations

import hashlib
import json
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone


class CloudError(Exception):
    """Failed saving/loading official practice records."""


def question_key(q):
    """Stable across app restarts and SQLite auto-incremented IDs."""
    kind = str(q.get('kind') or '').strip()
    stem = unicodedata.normalize('NFKC', str(q.get('stem') or '')).strip()
    return hashlib.sha256((kind + '\n' + stem).encode('utf-8')).hexdigest()


class CloudStore:
    TABLES = {'oh_exam_sessions', 'oh_exam_answers'}

    def __init__(self, url, secret):
        url = url.strip().rstrip('/')
        if not url.startswith('https://') or not urllib.parse.urlsplit(url).hostname.endswith('.supabase.co'):
            raise CloudError('Supabase URL 格式不正確，請確認 Secrets 設定。')
        if not secret.startswith('sb_secret_'):
            raise CloudError('Supabase Secret key 格式不正確，請確認使用 sb_secret_ 開頭的金鑰。')
        self.base = url + '/rest/v1/'
        self.secret = secret

    def _call(self, method, table, *, params=None, payload=None):
        if table not in self.TABLES:
            raise CloudError('不允許讀取此資料表。')
        url = self.base + table
        if params:
            url += '?' + urllib.parse.urlencode(params)
        headers = {
            'apikey': self.secret,
            'Accept': 'application/json',
            'User-Agent': 'oh-exam-private-backend/4.0',
        }
        content = None
        if payload is not None:
            content = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            headers['Content-Type'] = 'application/json'
            headers['Prefer'] = 'return=representation'
        request = urllib.request.Request(url, data=content, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                raw = response.read()
                return json.loads(raw.decode('utf-8')) if raw else []
        except urllib.error.HTTPError as exc:
            # Do not show the response body: it could include sensitive values.
            raise CloudError(f'Supabase 回應 HTTP {exc.code}，請確認金鑰、資料表及權限。') from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise CloudError('無法連上 Supabase，請檢查網路或稍後再試。') from None
        except (ValueError, UnicodeError) as exc:
            raise CloudError('Supabase 回應格式異常。') from None

    def list_rows(self, table, order_field, max_rows=20000):
        all_rows = []
        page_size = 1000
        while len(all_rows) < max_rows:
            batch = self._call('GET', table, params={
                'select': '*', 'order': order_field + '.desc',
                'limit': page_size, 'offset': len(all_rows),
            })
            if not isinstance(batch, list):
                raise CloudError('雲端資料讀取格式不符。')
            all_rows.extend(batch)
            if len(batch) < page_size:
                break
        return all_rows[:max_rows]

    def history(self):
        sessions = self.list_rows('oh_exam_sessions', 'started_at')
        answers = self.list_rows('oh_exam_answers', 'answered_at')
        return sessions, answers

    def save_answers(self, mode, pairs, *, started_at=None):
        """Store a session and its answer rows; return results only after remote commit.

        pairs: iterable of (question_dict, submitted_answer).
        """
        import core  # Existing local question-grading logic.

        pairs = list(pairs)
        if not pairs:
            raise CloudError('沒有可儲存的答案。')
        now = datetime.now(timezone.utc).isoformat()
        graded = []
        for q, submitted in pairs:
            submitted = str(submitted or '')
            correct, feedback = core.grade(q, submitted)
            if not core.eligible(q):
                correct = None
                feedback = '題目尚未通過正式計分驗證；保留作答紀錄供練習及人工複核。'
            pts = float(q.get('points') or 0)
            graded.append({
                'q': q, 'submitted': submitted,
                'correct': correct, 'feedback': feedback,
                'score': (pts if correct is True else 0.0 if correct is False else None),
                'possible': pts if correct is not None else None,
            })
        total_score = sum(row['score'] or 0 for row in graded)
        max_score = sum(row['possible'] or 0 for row in graded)
        body = {
            'mode': mode, 'started_at': started_at or now,
            'finished_at': now,
            'total_score': total_score, 'max_score': max_score,
            'question_count': len(graded),
        }
        saved = self._call('POST', 'oh_exam_sessions', payload=body)
        if not isinstance(saved, list) or not saved or not saved[0].get('id'):
            raise CloudError('雲端未回傳測驗紀錄 ID，無法確定是否儲存。')
        session_id = saved[0]['id']
        answer_rows = []
        for row in graded:
            q = row['q']
            answer_rows.append({
                'session_id': session_id,
                'question_key': question_key(q),
                'question_text': q['stem'],
                'topic': q.get('topic') or '',
                'user_answer': row['submitted'],
                'expected_answer': str(q.get('answer') or ''),
                'is_correct': row['correct'],
                'earned_points': row['score'],
                'possible_points': row['possible'],
                'feedback': row['feedback'],
            })
        try:
            saved_answers = self._call('POST', 'oh_exam_answers', payload=answer_rows)
            if not isinstance(saved_answers, list) or len(saved_answers) != len(answer_rows):
                raise CloudError('雲端回傳的作答筆數不符，請檢查紀錄，勿直接重複送出。')
        except CloudError:
            # Session may exist even if answers weren't saved. Flag this explicitly.
            raise CloudError('作答明細未能確認寫入；請到「雲端紀錄」檢查後再決定是否重新作答。') from None
        return session_id, graded
