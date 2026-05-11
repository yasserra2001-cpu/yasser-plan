"""
Daily Telegram reminder for Yasser Plan 2026.
Reads state from a private GitHub Gist, builds the dynamic message,
sends it via Telegram Bot API as text + Arabic voice (gTTS).

Required env vars (set as GitHub secrets):
  GIST_ID        - the gist holding yasser_plan_state.json
  GH_TOKEN       - GitHub PAT with `gist` scope
  TG_TOKEN       - Telegram bot token from @BotFather
  TG_CHAT_ID     - Telegram chat id (numeric)
  TIME_OF_DAY    - 'morning', 'midday', or 'evening'
"""
import os
import sys
import json
import tempfile
import requests
from datetime import datetime, timezone, timedelta

try:
    from zoneinfo import ZoneInfo
    ZONEINFO_OK = True
except ImportError:
    ZONEINFO_OK = False

try:
    from hijri_converter import Gregorian
    HIJRI_OK = True
except ImportError:
    HIJRI_OK = False

try:
    from gtts import gTTS
    TTS_OK = True
except ImportError:
    TTS_OK = False

def _env(key, default=None):
    v = os.environ.get(key, default)
    if v is None:
        raise KeyError(f'Missing required env var: {key}')
    return v.strip()  # Strip whitespace/newlines (common paste mistake)

GIST_ID = _env('GIST_ID')
GH_TOKEN = _env('GH_TOKEN')
TG_TOKEN = _env('TG_TOKEN')
TG_CHAT_ID = _env('TG_CHAT_ID')
TIME_OF_DAY = _env('TIME_OF_DAY', 'auto')
FILENAME = 'yasser_plan_state.json'

# Cairo time is computed dynamically via Africa/Cairo timezone (handles DST automatically).
# User can override from the app via state.dstOverride: 'auto' | 'on' | 'off'.
_dst_override = 'auto'

# Habit names — must exactly match HA array in yasser_plan_2026.html
HA_NAMES = ["الصلوات", "حفظ الورد", "رياضه", "ورد المراجعه", "English",
            "Reading", "Tech", "Jobs", "التفسير", "AI", "Manag", "تلاوة القران"]

# Month keys — must match MO array in yasser_plan_2026.html
MONTH_KEYS = ["Jan", "Feb", "Mar", "Apr", "May", "June", "July",
              "Aug", "Sep", "Oct", "Nov", "Dec"]

ARABIC_DAYS = ['الإثنين', 'الثلاثاء', 'الأربعاء', 'الخميس',
               'الجمعة', 'السبت', 'الأحد']

# Index 0 unused so month numbers map directly (1-12).
HIJRI_MONTHS = ['', 'محرم', 'صفر', 'ربيع الأول', 'ربيع الآخر',
                'جمادى الأولى', 'جمادى الآخرة', 'رجب', 'شعبان',
                'رمضان', 'شوال', 'ذو القعدة', 'ذو الحجة']

# ─── MEAL PLAN HELPERS ─────────────────────────────────────────
# FOOD_DB mirrors the constant in yasser_plan_2026.html — keep in sync.
FOOD_DB = {
    'fish_grilled': {'n': 'سمك مشوي', 'cal': 150, 'p': 25, 'unit': '100g'},
    'chicken_grilled': {'n': 'فراخ مشوية', 'cal': 165, 'p': 31, 'unit': '100g'},
    'lamb_grilled': {'n': 'لحم ضاني مشوي', 'cal': 250, 'p': 25, 'unit': '100g'},
    'egg_boiled': {'n': 'بيض مسلوق', 'cal': 78, 'p': 6, 'unit': 'حبة'},
    'tuna': {'n': 'تونة', 'cal': 130, 'p': 28, 'unit': '100g'},
    'shrimp': {'n': 'جمبري', 'cal': 99, 'p': 24, 'unit': '100g'},
    'kebab': {'n': 'كباب لحم', 'cal': 220, 'p': 22, 'unit': '100g'},
    'kofta': {'n': 'كفتة', 'cal': 200, 'p': 18, 'unit': '100g'},
    'foul': {'n': 'فول مدمس', 'cal': 110, 'p': 8, 'unit': '100g'},
    'lentils': {'n': 'عدس مطبوخ', 'cal': 116, 'p': 9, 'unit': '100g'},
    'chickpeas': {'n': 'حمص مطبوخ', 'cal': 164, 'p': 9, 'unit': '100g'},
    'beans': {'n': 'فاصولياء', 'cal': 130, 'p': 9, 'unit': '100g'},
    'brown_rice': {'n': 'أرز بني', 'cal': 112, 'p': 2.6, 'unit': '100g'},
    'bulgur': {'n': 'برغل', 'cal': 83, 'p': 3, 'unit': '100g'},
    'oats': {'n': 'شوفان', 'cal': 389, 'p': 17, 'unit': '100g'},
    'bread_baladi': {'n': 'خبز بلدي', 'cal': 80, 'p': 4, 'unit': 'شريحة'},
    'sweet_potato': {'n': 'بطاطا حلوة', 'cal': 90, 'p': 2, 'unit': '100g'},
    'pasta_whole': {'n': 'مكرونة قمح كامل', 'cal': 124, 'p': 5, 'unit': '100g'},
    'salad_green': {'n': 'سلطة خضراء', 'cal': 20, 'p': 1, 'unit': '100g'},
    'cucumber': {'n': 'خيار', 'cal': 16, 'p': 0.7, 'unit': '100g'},
    'tomato': {'n': 'طماطم', 'cal': 18, 'p': 0.9, 'unit': '100g'},
    'arugula': {'n': 'جرجير', 'cal': 25, 'p': 2.6, 'unit': '100g'},
    'mixed_veg': {'n': 'خضار مشكل', 'cal': 50, 'p': 3, 'unit': '100g'},
    'carrot': {'n': 'جزر', 'cal': 41, 'p': 0.9, 'unit': '100g'},
    'mahshi': {'n': 'محشي ورق عنب', 'cal': 170, 'p': 3, 'unit': '100g'},
    'apple': {'n': 'تفاح', 'cal': 78, 'p': 0.5, 'unit': 'حبة'},
    'banana': {'n': 'موز', 'cal': 107, 'p': 1.3, 'unit': 'حبة'},
    'orange': {'n': 'برتقال', 'cal': 70, 'p': 1.4, 'unit': 'حبة'},
    'pomegranate': {'n': 'رمان', 'cal': 125, 'p': 2.5, 'unit': 'نصف'},
    'date': {'n': 'تمر', 'cal': 28, 'p': 0.3, 'unit': 'تمرة'},
    'grapes': {'n': 'عنب', 'cal': 67, 'p': 0.6, 'unit': '100g'},
    'watermelon': {'n': 'بطيخ', 'cal': 90, 'p': 1.8, 'unit': 'شريحة'},
    'cantaloupe': {'n': 'شمام', 'cal': 68, 'p': 1.7, 'unit': 'شريحة'},
    'strawberry': {'n': 'فراولة', 'cal': 32, 'p': 0.7, 'unit': '100g'},
    'pear': {'n': 'كمثرى', 'cal': 85, 'p': 0.5, 'unit': 'حبة'},
    'peach': {'n': 'خوخ', 'cal': 58, 'p': 1.4, 'unit': 'حبة'},
    'apricot': {'n': 'مشمش', 'cal': 24, 'p': 0.7, 'unit': 'حبة'},
    'fig': {'n': 'تين', 'cal': 37, 'p': 0.4, 'unit': 'حبة'},
    'plum': {'n': 'برقوق', 'cal': 30, 'p': 0.5, 'unit': 'حبة'},
    'yogurt_low': {'n': 'زبادي قليل الدسم', 'cal': 56, 'p': 5, 'unit': '100g'},
    'milk': {'n': 'لبن', 'cal': 60, 'p': 3.2, 'unit': '100ml'},
    'labneh': {'n': 'لبنة', 'cal': 230, 'p': 8, 'unit': '100g'},
    'cheese_white': {'n': 'جبن أبيض', 'cal': 250, 'p': 18, 'unit': '100g'},
    'almonds': {'n': 'لوز', 'cal': 162, 'p': 6, 'unit': 'حفنة'},
    'walnuts': {'n': 'جوز', 'cal': 183, 'p': 4, 'unit': 'حفنة'},
    'olive_oil': {'n': 'زيت زيتون', 'cal': 124, 'p': 0, 'unit': 'ملعقة'},
    'tahini': {'n': 'طحينة', 'cal': 89, 'p': 3, 'unit': 'ملعقة'},
    'honey': {'n': 'عسل', 'cal': 21, 'p': 0, 'unit': 'ملعقة'},
    'olives': {'n': 'زيتون', 'cal': 115, 'p': 0.8, 'unit': '100g'},
    'water': {'n': 'ماء', 'cal': 0, 'p': 0, 'unit': 'كوب'},
    'tea': {'n': 'شاي', 'cal': 0, 'p': 0, 'unit': 'كوب'},
    'green_tea': {'n': 'شاي أخضر', 'cal': 0, 'p': 0, 'unit': 'كوب'},
    'coffee': {'n': 'قهوة', 'cal': 2, 'p': 0, 'unit': 'كوب'},
}

DAY_KEYS = ['sunday', 'monday', 'tuesday', 'wednesday',
            'thursday', 'friday', 'saturday']  # weekday() index
MEAL_KEYS = ['breakfast', 'lunch', 'dinner', 'snack']
MEAL_LABELS = {'breakfast': '🌅 فطار', 'lunch': '☀️ غداء',
               'dinner': '🌙 عشاء', 'snack': '🍎 سناك'}


def lookup_food(food_id, custom_foods):
    if food_id in FOOD_DB:
        return FOOD_DB[food_id]
    for f in custom_foods or []:
        if f.get('id') == food_id:
            return {'n': f.get('n', ''), 'cal': f.get('cal', 0),
                    'p': f.get('p', 0), 'unit': f.get('unit', '')}
    return None


def item_totals(item, custom_foods):
    f = lookup_food(item.get('id'), custom_foods)
    if not f:
        return {'cal': 0, 'p': 0}
    q = item.get('q', 0)
    unit = (f.get('unit') or '').lower()
    factor = (q / 100) if ('100' in unit) else q
    return {'cal': f['cal'] * factor, 'p': f['p'] * factor}


def meal_summary(items, custom_foods):
    totals = {'cal': 0, 'p': 0}
    names = []
    for it in items or []:
        f = lookup_food(it.get('id'), custom_foods)
        if not f:
            continue
        names.append(f['n'])
        t = item_totals(it, custom_foods)
        totals['cal'] += t['cal']
        totals['p'] += t['p']
    return totals, names


def day_totals(day_plan, custom_foods):
    totals = {'cal': 0, 'p': 0}
    for m in MEAL_KEYS:
        t, _ = meal_summary((day_plan or {}).get(m, []), custom_foods)
        totals['cal'] += t['cal']
        totals['p'] += t['p']
    return totals


def calorie_advice(total_cal, goal):
    pct = round((total_cal / goal) * 100) if goal else 0
    if pct >= 110:
        return '🔴', f'تجاوز الهدف بـ {int(total_cal - goal)} سعر'
    if pct >= 95:
        return '🟡', f'قريب من الحد ({pct}%)'
    if pct >= 70:
        return '🟢', f'ضمن الهدف ({pct}%)'
    if total_cal > 0:
        return '🟡', f'قليل ({pct}%)'
    return '⚪', 'لا توجد وجبات مخططة'


def cairo_now():
    if _dst_override == 'on':
        return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=3)
    if _dst_override == 'off':
        return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=2)
    if ZONEINFO_OK:
        try:
            return datetime.now(ZoneInfo('Africa/Cairo')).replace(tzinfo=None)
        except Exception:
            pass
    # Fallback: assume UTC+3 (current Egypt DST)
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=3)


def fetch_state():
    r = requests.get(
        f'https://api.github.com/gists/{GIST_ID}',
        headers={
            'Authorization': f'Bearer {GH_TOKEN}',
            'Accept': 'application/vnd.github+json',
        },
        timeout=20,
    )
    r.raise_for_status()
    content = r.json()['files'][FILENAME]['content']
    if not content or content.strip() in ('', '{}'):
        return {}
    return json.loads(content)


def hijri_for(date):
    if not HIJRI_OK:
        return None
    g = Gregorian(date.year, date.month, date.day).to_hijri()
    return {'day': g.day, 'month': g.month, 'year': g.year}


def fasting_info_for(date):
    dow = date.weekday()  # 0 = Monday
    if dow == 0:
        return 'الإثنين (سنة)'
    if dow == 3:
        return 'الخميس (سنة)'
    h = hijri_for(date)
    if h and 13 <= h['day'] <= 15:
        m_name = HIJRI_MONTHS[h['month']] if 1 <= h['month'] <= 12 else ''
        return f"الأيام البيض ({h['day']} {m_name})"
    return None


def date_header():
    """Returns 2 lines: Gregorian date, Hijri date."""
    now = cairo_now()
    g = f"📅 {ARABIC_DAYS[now.weekday()]} {now.day}/{now.month}/{now.year} ميلادي"
    h = hijri_for(now)
    if h:
        m_name = HIJRI_MONTHS[h['month']] if 1 <= h['month'] <= 12 else str(h['month'])
        g += f"\n🌙 {h['day']} {m_name} {h['year']}"
    return g


def build_morning(state):
    now = cairo_now()
    today_key = now.strftime('%Y-%m-%d')
    meds = (state.get('meds') or {}).get(today_key, {})
    fasting = (state.get('fasting') or {}).get(today_key, {})
    weight_target = (state.get('weightGoal') or {}).get('target', 74)
    fast_today = fasting_info_for(now)

    m = f"🌅 *صباح الخير يا ياسر*\n{date_header()}\n\n"
    m += "💊 *دواء الصباح:*\n"
    m += f"• كاربيمازول 5 ملج {'✅ تم' if meds.get('carbAM') else '⏰ يحتاج تناوله'}\n\n"
    if fast_today:
        m += f"🌙 *اليوم يوم صيام: {fast_today}*\n"
        m += '✅ مسجّل\n\n' if fasting.get('fasted') else 'لا تنس تسجيل النية\n\n'

    # Meal plan for today
    day_idx = DAY_KEYS[now.weekday() if now.weekday() < 6 else 6]
    # Python weekday: Mon=0, Sun=6. Map to our day keys: Mon -> 'monday' etc.
    day_idx = ['monday', 'tuesday', 'wednesday', 'thursday',
               'friday', 'saturday', 'sunday'][now.weekday()]
    plan = (state.get('mealPlan') or {}).get(day_idx)
    custom = state.get('customFoods') or []
    goal = state.get('calorieGoal') or 2000
    if plan:
        m += "🥗 *وجبات اليوم (الطيبات):*\n"
        for mk in MEAL_KEYS:
            t, names = meal_summary(plan.get(mk, []), custom)
            if not names:
                continue
            m += f"• {MEAL_LABELS[mk]} ({int(t['cal'])} سعر): {' + '.join(names)}\n"
        dt = day_totals(plan, custom)
        icon, advice = calorie_advice(dt['cal'], goal)
        m += f"\n📊 *الإجمالي:* {int(dt['cal'])} / {goal} سعر · "
        m += f"بروتين {int(dt['p'])}ج\n{icon} {advice}\n\n"
    else:
        m += "🥗 *وجبات اليوم:*\n• حسب خطة الطيبات (راجع التطبيق)\n\n"

    m += "💧 8 أكواب ماء\n"
    m += "🚶 30 دقيقة مشي\n"
    m += f"⚖️ الهدف: {weight_target} كجم بنهاية 2026\n\n"
    m += "💪 بالتوفيق وكن مع الله"
    return m


def build_midday(state):
    now = cairo_now()
    today_key = now.strftime('%Y-%m-%d')
    meds = (state.get('meds') or {}).get(today_key, {})
    fasting = (state.get('fasting') or {}).get(today_key, {})
    health = (state.get('health') or {}).get(f'h_{today_key}', {})
    fast_today = fasting_info_for(now)

    # Today's habits — array of 12 booleans
    month_key = MONTH_KEYS[now.month - 1]
    day_key = str(now.day)
    habits = ((state.get('hd') or {}).get(month_key) or {}).get(day_key, [])

    todos = state.get('todos') or []
    pending = [t for t in todos
               if isinstance(t, dict) and not t.get('done') and not t.get('completed')][:3]

    m = f"☀️ *منتصف اليوم يا ياسر*\n{date_header()}\n\n"

    if habits and len(habits) >= 12:
        done = sum(1 for x in habits if x)
        m += f"✅ *العادات: {done}/12 مكتملة*\n"
        for i, name in enumerate(HA_NAMES):
            if i < len(habits):
                icon = '✅' if habits[i] else '⏰'
                m += f"  {icon} {name}\n"
        m += '\n'
    else:
        m += '✅ *العادات*: لم يتم تحديثها بعد اليوم\n\n'

    if pending:
        m += "📋 *أهم 3 مهام معلقة:*\n"
        for i, t in enumerate(pending):
            text = t.get('text') or t.get('title') or t.get('name') or '(بدون عنوان)'
            m += f"  {i + 1}. {text}\n"
        m += '\n'
    else:
        m += "📋 *المهام*: لا توجد مهام معلقة 🎉\n\n"

    m += "🌅 *إنجاز الصباح:*\n"
    m += f"  • كاربيمازول: {'✅' if meds.get('carbAM') else '⏰ ذكّر نفسك'}\n"
    if fast_today:
        m += f"  • الصيام: {'✅ مسجّل' if fasting.get('fasted') else '⏰ سجّل النية'}\n"
    water = health.get('water', 0)
    m += f"  • ماء: {water}/8\n"
    steps = health.get('steps', 0)
    m += f"  • خطوات: {steps}\n\n"

    # Lunch + dinner reminder with calories
    day_idx = ['monday', 'tuesday', 'wednesday', 'thursday',
               'friday', 'saturday', 'sunday'][now.weekday()]
    plan = (state.get('mealPlan') or {}).get(day_idx)
    custom = state.get('customFoods') or []
    if plan:
        for mk in ['lunch', 'dinner']:
            t, names = meal_summary(plan.get(mk, []), custom)
            if not names:
                continue
            m += f"🍽️ *{MEAL_LABELS[mk]}* ({int(t['cal'])} سعر): {' + '.join(names)}\n"
        m += '\n'

    m += "🚀 *المتبقي للمساء:*\n"
    m += "  • اندرال 10 ملج (6م)\n"
    m += "  • مشي 30 دقيقة (لو فاتك)\n"
    m += "  • أكمل العادات والمهام\n\n"
    m += "💪 يلا نكمل بقوة!"
    return m


def build_evening(state):
    now = cairo_now()
    today_key = now.strftime('%Y-%m-%d')
    meds = (state.get('meds') or {}).get(today_key, {})
    fasting = (state.get('fasting') or {}).get(today_key, {})
    health = (state.get('health') or {}).get(f'h_{today_key}', {})
    fast_today = fasting_info_for(now)

    tomorrow = now + timedelta(days=1)
    suhoor = fasting_info_for(tomorrow)

    m = f"🌙 *مراجعة المساء يا ياسر*\n{date_header()}\n\n"
    m += "💊 *دواء المساء:*\n"
    m += f"• اندرال 10 ملج {'✅ تم' if meds.get('indPM') else '⏰ يحتاج تناوله'}\n\n"
    m += "📊 *مراجعة اليوم:*\n"
    m += f"• كاربيمازول الصباح: {'✅' if meds.get('carbAM') else '❌ فاتت'}\n"
    if fast_today:
        m += f"• الصيام: {'✅ صمت' if fasting.get('fasted') else '⚠️ لم يُسجّل'}\n"
    water = health.get('water', 0)
    m += f"• الماء: {water}/8 {'✅' if water >= 8 else ''}\n"
    exercise = health.get('exercise', 0)
    m += f"• المشي: {exercise} دقيقة {'✅' if exercise >= 30 else ''}\n"
    steps = health.get('steps', 0)
    m += f"• الخطوات: {steps}\n\n"
    # Daily calorie review
    day_idx = ['monday', 'tuesday', 'wednesday', 'thursday',
               'friday', 'saturday', 'sunday'][now.weekday()]
    plan = (state.get('mealPlan') or {}).get(day_idx)
    custom = state.get('customFoods') or []
    goal = state.get('calorieGoal') or 2000
    if plan:
        dt = day_totals(plan, custom)
        icon, advice = calorie_advice(dt['cal'], goal)
        m += f"🍽️ *الوجبات (مخطط):* {int(dt['cal'])} / {goal} سعر · بروتين {int(dt['p'])}ج\n"
        m += f"{icon} {advice}\n\n"

    if suhoor:
        m += f"🌅 *تذكير*: غدًا {suhoor} — لا تنس السحور!\n\n"
    m += "🛌 نوم 8 ساعات\n"
    m += "🤲 ادعُ لي ولأهلك"
    return m


def build_message(state, time_of_day):
    if time_of_day == 'morning':
        return build_morning(state)
    if time_of_day == 'midday':
        return build_midday(state)
    return build_evening(state)


def build_voice_summary(state, time_of_day):
    """Arabic spoken summary — reads the same data shown in the text message."""
    now = cairo_now()
    today_key = now.strftime('%Y-%m-%d')
    meds = (state.get('meds') or {}).get(today_key, {})
    fasting = (state.get('fasting') or {}).get(today_key, {})
    health = (state.get('health') or {}).get(f'h_{today_key}', {})
    fast_today = fasting_info_for(now)
    weight_target = (state.get('weightGoal') or {}).get('target', 74)

    # Today's meal plan
    day_idx = ['monday', 'tuesday', 'wednesday', 'thursday',
               'friday', 'saturday', 'sunday'][now.weekday()]
    plan = (state.get('mealPlan') or {}).get(day_idx)
    custom = state.get('customFoods') or []

    if time_of_day == 'morning':
        v = "صباح الخير يا ياسر. "
        v += "تذكير بدواء الكاربيمازول خمسة ملج صباحا. " if not meds.get('carbAM') else "تم تسجيل الكاربيمازول. "
        if fast_today:
            v += f"اليوم يوم صيام، {fast_today}. "
            if not fasting.get('fasted'):
                v += "لا تنس تسجيل النية. "
        if plan:
            # Read meal names from actual plan
            meal_ar = {'breakfast': 'الفطار', 'lunch': 'الغداء',
                       'dinner': 'العشاء', 'snack': 'سناك'}
            for mk in MEAL_KEYS:
                items = plan.get(mk, [])
                if not items:
                    continue
                names = []
                for it in items:
                    f = lookup_food(it.get('id'), custom)
                    if f:
                        # Use Arabic-style food name (strip parens)
                        n = f['n'].split('(')[0].strip()
                        names.append(n)
                if names:
                    v += f"{meal_ar.get(mk, mk)}: {' و '.join(names[:3])}. "
            dt = day_totals(plan, custom)
            v += f"إجمالي السعرات حوالي {int(dt['cal'])} سعر. "
        v += "لا تنس شرب الماء والمشي ثلاثين دقيقة. "
        v += f"الهدف: {weight_target} كجم بنهاية العام."
        return v

    if time_of_day == 'midday':
        v = "منتصف النهار يا ياسر. "
        v += "تذكير بأن الكاربيمازول الصباحي " + ("تم تناوله. " if meds.get('carbAM') else "لم يُسجَّل بعد. ")
        if fast_today:
            v += "اليوم يوم صيام. " + ("الصيام مسجل. " if fasting.get('fasted') else "")
        # Read lunch + dinner from plan
        if plan:
            meal_ar = {'lunch': 'الغداء', 'dinner': 'العشاء'}
            for mk in ['lunch', 'dinner']:
                items = plan.get(mk, [])
                if not items:
                    continue
                names = []
                for it in items:
                    f = lookup_food(it.get('id'), custom)
                    if f:
                        names.append(f['n'].split('(')[0].strip())
                if names:
                    v += f"{meal_ar[mk]}: {' و '.join(names[:3])}. "
        water = health.get('water', 0)
        v += f"شربت {water} من ثمانية أكواب ماء. " if water else "لم يُسجَّل ماء بعد. "
        v += "اندرال في السادسة مساء. "
        v += "أكمل المهام والعادات المتبقية بقوة."
        return v

    # evening
    v = "مساء الخير يا ياسر. "
    v += "تذكير بدواء الاندرال عشرة ملج مساء. " if not meds.get('indPM') else "تم تسجيل الاندرال. "
    v += "مراجعة اليوم: "
    v += "الكاربيمازول الصباحي " + ("تم. " if meds.get('carbAM') else "فات. ")
    if fast_today:
        v += "الصيام " + ("تم. " if fasting.get('fasted') else "لم يُسجَّل. ")
    water = health.get('water', 0)
    v += f"الماء {water} أكواب. "
    exercise = health.get('exercise', 0)
    if exercise:
        v += f"المشي {exercise} دقيقة. "
    if plan:
        dt = day_totals(plan, custom)
        v += f"إجمالي السعرات اليوم حوالي {int(dt['cal'])} سعر. "
    tomorrow = now + timedelta(days=1)
    suhoor = fasting_info_for(tomorrow)
    if suhoor:
        v += f"تذكير مهم: غدا يوم صيام، {suhoor}. لا تنس السحور. "
    v += "نوم ثماني ساعات، وكن مع الله."
    return v


def send_telegram_text(text):
    r = requests.post(
        f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
        json={
            'chat_id': TG_CHAT_ID,
            'text': text,
            'parse_mode': 'Markdown',
            'disable_web_page_preview': True,
        },
        timeout=30,
    )
    print(f'Text status: {r.status_code}')
    print(f'Text response: {r.text[:300]}')
    r.raise_for_status()


def send_telegram_voice(text):
    """Generate Arabic TTS via gTTS and send as audio."""
    if not TTS_OK:
        print('⚠️ gTTS not installed, skipping voice')
        return
    try:
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
            tmppath = f.name
        gTTS(text=text, lang='ar', slow=False).save(tmppath)
        with open(tmppath, 'rb') as audio_file:
            r = requests.post(
                f'https://api.telegram.org/bot{TG_TOKEN}/sendAudio',
                data={'chat_id': TG_CHAT_ID, 'title': 'تذكير صوتي'},
                files={'audio': ('reminder.mp3', audio_file, 'audio/mpeg')},
                timeout=60,
            )
            print(f'Voice status: {r.status_code}')
            print(f'Voice response: {r.text[:300]}')
            r.raise_for_status()
        try:
            os.unlink(tmppath)
        except OSError:
            pass
        print('✅ Voice sent')
    except Exception as e:
        # Don't crash the whole job if voice fails — text already delivered.
        print(f'⚠️ Voice failed: {e}')


def main():
    global _dst_override
    print(f'Requested time-of-day: {TIME_OF_DAY}')
    print(f'Hijri available: {HIJRI_OK}')
    print(f'TTS available: {TTS_OK}')
    print(f'ZoneInfo available: {ZONEINFO_OK}')
    state = fetch_state()
    print(f'State keys: {sorted(state.keys()) if state else "(empty)"}')

    # Apply user's DST override from app settings (synced via gist)
    pref = (state.get('dstOverride') or 'auto').lower()
    if pref in ('auto', 'on', 'off'):
        _dst_override = pref
    print(f'DST mode: {_dst_override}')
    print(f'Cairo time now: {cairo_now().isoformat()}')

    # Auto-detect time of day from current Cairo hour
    tod = TIME_OF_DAY
    if tod == 'auto':
        h = cairo_now().hour
        if 6 <= h <= 8:
            tod = 'morning'
        elif 12 <= h <= 14:
            tod = 'midday'
        elif 17 <= h <= 19:
            tod = 'evening'
        else:
            print(f'Skip: Cairo hour {h} not in any target window (6-8, 12-14, 17-19)')
            sys.exit(0)
    print(f'Resolved time-of-day: {tod}')

    text = build_message(state, tod)
    print(f'Text length: {len(text)}')
    print('--- Text preview ---')
    print(text)
    print('--- end ---')
    send_telegram_text(text)

    voice = build_voice_summary(state, tod)
    print(f'Voice length: {len(voice)}')
    print('--- Voice preview ---')
    print(voice)
    print('--- end ---')
    send_telegram_voice(voice)

    print('✅ All sent')


if __name__ == '__main__':
    main()
