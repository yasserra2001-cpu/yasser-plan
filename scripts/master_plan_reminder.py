"""
Daily Telegram reminder for Yasser_Master_Plan_v10 (interview prep).
Reads from yasser_master_state.json gist, generates a personalized
study/prep summary, and sends it via Telegram Bot API.

Uses the SAME Telegram bot/chat as the Plan 2026 reminders
(same TG_TOKEN, TG_CHAT_ID secrets — no separate bot needed).

Required env vars (set as GitHub secrets):
  GIST_ID        - the gist holding yasser_master_state.json
  GH_TOKEN       - GitHub PAT with `gist` scope
  TG_TOKEN       - Telegram bot token (same as plan-2026 reminder)
  TG_CHAT_ID     - Telegram chat id (same as plan-2026 reminder)
"""
import os
import json
import requests
from datetime import datetime, timezone, timedelta

try:
    from zoneinfo import ZoneInfo
    ZONEINFO_OK = True
except ImportError:
    ZONEINFO_OK = False

GIST_ID = os.environ['GIST_ID']
GH_TOKEN = os.environ['GH_TOKEN']
TG_TOKEN = os.environ['TG_TOKEN']
TG_CHAT_ID = os.environ['TG_CHAT_ID']
FILENAME = 'yasser_master_state.json'


def cairo_now():
    if ZONEINFO_OK:
        try:
            return datetime.now(ZoneInfo('Africa/Cairo')).replace(tzinfo=None)
        except Exception:
            pass
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=3)


def fetch_state():
    r = requests.get(
        f'https://api.github.com/gists/{GIST_ID}',
        headers={'Authorization': f'Bearer {GH_TOKEN}',
                 'Accept': 'application/vnd.github+json'},
        timeout=20,
    )
    r.raise_for_status()
    files = r.json().get('files', {})
    if FILENAME not in files:
        return {}
    content = files[FILENAME].get('content', '')
    if not content or content.strip() in ('', '{}'):
        return {}
    return json.loads(content)


def parse_field(state, key, default):
    v = state.get(key, default)
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return default
    return v if v is not None else default


def build_message(state):
    now = cairo_now()
    date_str = now.strftime('%A %d %B %Y')

    sessions = parse_field(state, 'yk', [])
    sr = parse_field(state, 'qa_sr', {})
    conf = parse_field(state, 'qa_conf', {})
    streak = parse_field(state, 'yStudyStreak', {'count': 0, 'lastDay': ''})
    favs = parse_field(state, 'yfavQA', [])
    mocks = parse_field(state, 'yMockHistory', [])
    interview_date = state.get('yintdate') or state.get('interviewDate', '')

    completed_days = set()
    for s in sessions if isinstance(sessions, list) else []:
        if isinstance(s, dict) and s.get('d'):
            completed_days.add(s['d'])
    next_day = 1
    for i in range(1, 91):
        if i not in completed_days:
            next_day = i
            break

    mastered = sum(1 for v in sr.values() if v == 'know')
    need_work = sum(1 for v in sr.values() if v == 'need')
    avg_conf = (sum(int(v) for v in conf.values() if v) / max(1, len(conf))) if conf else 0
    last_mock = mocks[-1] if mocks else None

    days_to_int = ''
    if interview_date:
        try:
            id_d = datetime.fromisoformat(interview_date)
            delta = (id_d.date() - now.date()).days
            days_to_int = f'{delta} days' if delta > 0 else ('TODAY' if delta == 0 else f'{-delta} days ago')
        except Exception:
            pass

    m = f"🎯 *Interview Prep — Daily Brief*\n📅 {date_str}\n\n"
    m += "*📊 Progress snapshot:*\n"
    m += f"🔥 Study streak: *{streak.get('count', 0)} days*\n"
    m += f"📋 Plan: Day *{next_day}/90* ({len(completed_days)} sessions logged)\n"
    m += f"✅ Q&A mastered: *{mastered}* · Need work: *{need_work}*\n"
    m += f"💪 Avg confidence: *{avg_conf:.1f}/5*\n"
    m += f"⭐ Favorites: *{len(favs)}* questions\n"
    if last_mock:
        m += f"🎬 Last mock: *{last_mock.get('answered', 0)}/{last_mock.get('total', 0)}* in {last_mock.get('totalMin', 0)}min\n"
    if days_to_int:
        m += f"📆 Interview: *{days_to_int}*\n"

    m += "\n*🚀 Today's recommendations:*\n"
    if streak.get('count', 0) == 0:
        m += "• Open a Q&A and rate confidence — start your streak today\n"
    if need_work > 5:
        m += f"• {need_work} questions marked Need Practice — drill them first\n"
    if avg_conf > 0 and avg_conf < 3.5:
        m += "• Avg confidence below 3.5 — focus on Weak Areas Dashboard\n"
    if last_mock:
        try:
            last_mock_date = datetime.fromisoformat(last_mock.get('date', '')[:19])
            if (now - last_mock_date).days > 7:
                m += "• No mock this week — run a 8Q timed simulator (~25 min)\n"
        except Exception:
            pass
    else:
        m += "• Try the Mock Interview Simulator — first time\n"
    m += f"• Plan task for today: Day {next_day} (open Plan tab)\n"
    m += "• Use AI Coach on at least 1 Q&A answer\n\n"

    m += "_💡 Open the app to drill, mock, or use AI Coach._"
    return m


def send_telegram(text):
    r = requests.post(
        f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
        json={'chat_id': TG_CHAT_ID, 'text': text,
              'parse_mode': 'Markdown',
              'disable_web_page_preview': True},
        timeout=30,
    )
    print(f'Telegram status: {r.status_code}')
    print(f'Telegram response: {r.text[:300]}')
    r.raise_for_status()


def main():
    print(f'Cairo time: {cairo_now().isoformat()}')
    state = fetch_state()
    print(f'State keys: {sorted(state.keys()) if state else "(empty)"}')
    msg = build_message(state)
    print(f'Message length: {len(msg)}')
    print('--- preview ---')
    print(msg)
    print('--- end ---')
    send_telegram(msg)
    print('✅ Sent')


if __name__ == '__main__':
    main()
