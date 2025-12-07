#!/usr/bin/env python3
"""
iMessage Wrapped 2025 - Your texting habits, exposed.
Usage: python3 imessage_wrapped.py
"""

import sqlite3, os, sys, re, subprocess, argparse, glob, threading, time
from datetime import datetime

IMESSAGE_DB = os.path.expanduser("~/Library/Messages/chat.db")
ADDRESSBOOK_DIR = os.path.expanduser("~/Library/Application Support/AddressBook")

class Spinner:
    """Animated terminal spinner for long operations"""
    def __init__(self, message=""):
        self.message = message
        self.spinning = False
        self.thread = None
        self.frames = ['⣾', '⣽', '⣻', '⢿', '⡿', '⣟', '⣯', '⣷']

    def spin(self):
        i = 0
        while self.spinning:
            frame = self.frames[i % len(self.frames)]
            print(f"\r    {frame} {self.message}", end='', flush=True)
            time.sleep(0.1)
            i += 1

    def start(self, message=None):
        if message:
            self.message = message
        self.spinning = True
        self.thread = threading.Thread(target=self.spin)
        self.thread.start()

    def stop(self, final_message=None):
        self.spinning = False
        if self.thread:
            self.thread.join()
        if final_message:
            print(f"\r    ✓ {final_message}".ljust(60))
        else:
            print()

TS_2025 = 1735689600
TS_JUN_2025 = 1748736000
TS_2024 = 1704067200
TS_JUN_2024 = 1717200000

def normalize_phone(phone):
    if not phone: return None
    digits = re.sub(r'\D', '', str(phone))
    # Handle common international prefixes
    if len(digits) == 11 and digits.startswith('1'):
        digits = digits[1:]  # US/Canada +1
    elif len(digits) > 10:
        # For international numbers, store full digits for exact matching
        # but also try common formats
        return digits
    return digits[-10:] if len(digits) >= 10 else (digits if len(digits) >= 7 else None)

def extract_contacts():
    contacts = {}
    db_paths = glob.glob(os.path.join(ADDRESSBOOK_DIR, "Sources", "*", "AddressBook-v22.abcddb"))
    main_db = os.path.join(ADDRESSBOOK_DIR, "AddressBook-v22.abcddb")
    if os.path.exists(main_db): db_paths.append(main_db)
    for db_path in db_paths:
        try:
            conn = sqlite3.connect(db_path)
            people = {}
            for row in conn.execute("SELECT ROWID, ZFIRSTNAME, ZLASTNAME FROM ZABCDRECORD WHERE ZFIRSTNAME IS NOT NULL OR ZLASTNAME IS NOT NULL"):
                name = f"{row[1] or ''} {row[2] or ''}".strip()
                if name: people[row[0]] = name
            for owner, phone in conn.execute("SELECT ZOWNER, ZFULLNUMBER FROM ZABCDPHONENUMBER WHERE ZFULLNUMBER IS NOT NULL"):
                if owner in people:
                    name = people[owner]
                    digits = re.sub(r'\D', '', str(phone))
                    # Store multiple formats for better matching
                    if digits:
                        contacts[digits] = name  # Full international
                        if len(digits) >= 10:
                            contacts[digits[-10:]] = name  # Last 10
                        if len(digits) >= 7:
                            contacts[digits[-7:]] = name  # Last 7 (local)
                        if len(digits) == 11 and digits.startswith('1'):
                            contacts[digits[1:]] = name  # Without US prefix
            for owner, email in conn.execute("SELECT ZOWNER, ZADDRESS FROM ZABCDEMAILADDRESS WHERE ZADDRESS IS NOT NULL"):
                if owner in people: contacts[email.lower().strip()] = people[owner]
            conn.close()
        except: pass
    return contacts

def get_name(handle, contacts):
    if '@' in handle:
        lookup = handle.lower().strip()
        if lookup in contacts: return contacts[lookup]
        return handle.split('@')[0]
    # Try multiple phone formats for matching
    digits = re.sub(r'\D', '', str(handle))
    # Try full digits first (international)
    if digits in contacts: return contacts[digits]
    # Try without leading 1 (US/Canada)
    if len(digits) == 11 and digits.startswith('1'):
        if digits[1:] in contacts: return contacts[digits[1:]]
    # Try last 10 digits
    if len(digits) >= 10 and digits[-10:] in contacts:
        return contacts[digits[-10:]]
    # Try last 7 digits (local)
    if len(digits) >= 7 and digits[-7:] in contacts:
        return contacts[digits[-7:]]
    return handle

def check_access():
    if not os.path.exists(IMESSAGE_DB):
        print("\n[FATAL] Not macOS.")
        sys.exit(1)
    try:
        conn = sqlite3.connect(IMESSAGE_DB)
        conn.execute("SELECT 1 FROM message LIMIT 1")
        conn.close()
    except:
        print("\n⚠️  ACCESS DENIED")
        print("   System Settings → Privacy & Security → Full Disk Access → Add Terminal")
        subprocess.run(['open', 'x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles'])
        sys.exit(1)

def q(sql):
    conn = sqlite3.connect(IMESSAGE_DB)
    r = conn.execute(sql).fetchall()
    conn.close()
    return r

def analyze(ts_start, ts_jun):
    d = {}

    # === IDENTIFY 1:1 vs GROUP CHATS ===
    # 1:1 chats have exactly 1 participant in chat_handle_join
    # Group chats have 2+ participants
    # We'll use this CTE pattern to filter queries

    # Common table expression for 1:1 chat filtering
    one_on_one_cte = """
        WITH chat_participants AS (
            SELECT chat_id, COUNT(*) as participant_count
            FROM chat_handle_join
            GROUP BY chat_id
        ),
        one_on_one_messages AS (
            SELECT m.ROWID as msg_id
            FROM message m
            JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
            JOIN chat_participants cp ON cmj.chat_id = cp.chat_id
            WHERE cp.participant_count = 1
        )
    """

    # Stats: handle NULL from SUM when 0 messages (1:1 only)
    raw_stats = q(f"""{one_on_one_cte}
        SELECT COUNT(*), SUM(CASE WHEN is_from_me=1 THEN 1 ELSE 0 END), SUM(CASE WHEN is_from_me=0 THEN 1 ELSE 0 END), COUNT(DISTINCT handle_id)
        FROM message m
        WHERE (date/1000000000+978307200)>{ts_start}
        AND m.ROWID IN (SELECT msg_id FROM one_on_one_messages)
    """)[0]
    d['stats'] = (raw_stats[0] or 0, raw_stats[1] or 0, raw_stats[2] or 0, raw_stats[3] or 0)

    # Top contacts (1:1 only, excluding 5-6 digit shortcodes like 12345, 123456)
    d['top'] = q(f"""{one_on_one_cte}
        SELECT h.id, COUNT(*) t, SUM(CASE WHEN m.is_from_me=1 THEN 1 ELSE 0 END), SUM(CASE WHEN m.is_from_me=0 THEN 1 ELSE 0 END)
        FROM message m JOIN handle h ON m.handle_id=h.ROWID
        WHERE (m.date/1000000000+978307200)>{ts_start}
        AND m.ROWID IN (SELECT msg_id FROM one_on_one_messages)
        AND NOT (LENGTH(REPLACE(REPLACE(h.id, '+', ''), '-', '')) BETWEEN 5 AND 6 AND REPLACE(REPLACE(h.id, '+', ''), '-', '') GLOB '[0-9]*')
        GROUP BY h.id ORDER BY t DESC LIMIT 20
    """)

    # Late night texters (1:1 only, excluding shortcodes)
    d['late'] = q(f"""{one_on_one_cte}
        SELECT h.id, COUNT(*) n FROM message m JOIN handle h ON m.handle_id=h.ROWID
        WHERE (m.date/1000000000+978307200)>{ts_start}
        AND CAST(strftime('%H',datetime((m.date/1000000000+978307200),'unixepoch','localtime')) AS INT)<5
        AND m.ROWID IN (SELECT msg_id FROM one_on_one_messages)
        AND NOT (LENGTH(REPLACE(REPLACE(h.id, '+', ''), '-', '')) BETWEEN 5 AND 6 AND REPLACE(REPLACE(h.id, '+', ''), '-', '') GLOB '[0-9]*')
        GROUP BY h.id HAVING n>5 ORDER BY n DESC LIMIT 5
    """)
    
    r = q(f"SELECT CAST(strftime('%H',datetime((date/1000000000+978307200),'unixepoch','localtime')) AS INT) h, COUNT(*) c FROM message WHERE (date/1000000000+978307200)>{ts_start} GROUP BY h ORDER BY c DESC LIMIT 1")
    d['hour'] = r[0][0] if r else 12
    days = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday']
    r = q(f"SELECT CAST(strftime('%w',datetime((date/1000000000+978307200),'unixepoch','localtime')) AS INT) d, COUNT(*) FROM message WHERE (date/1000000000+978307200)>{ts_start} GROUP BY d ORDER BY 2 DESC LIMIT 1")
    d['day'] = days[r[0][0]] if r else '???'
    
    # Ghosted (1:1 only, excluding shortcodes)
    d['ghosted'] = q(f"""{one_on_one_cte}
        SELECT h.id, SUM(CASE WHEN m.is_from_me=0 AND (m.date/1000000000+978307200)<{ts_jun} THEN 1 ELSE 0 END) b, SUM(CASE WHEN m.is_from_me=0 AND (m.date/1000000000+978307200)>={ts_jun} THEN 1 ELSE 0 END) a
        FROM message m JOIN handle h ON m.handle_id=h.ROWID
        WHERE (m.date/1000000000+978307200)>{ts_start}
        AND m.ROWID IN (SELECT msg_id FROM one_on_one_messages)
        AND NOT (LENGTH(REPLACE(REPLACE(h.id, '+', ''), '-', '')) BETWEEN 5 AND 6 AND REPLACE(REPLACE(h.id, '+', ''), '-', '') GLOB '[0-9]*')
        GROUP BY h.id HAVING b>10 AND a<3 ORDER BY b DESC LIMIT 5
    """)

    # Heating up (1:1 only, excluding shortcodes)
    d['heating'] = q(f"""{one_on_one_cte}
        SELECT h.id, SUM(CASE WHEN (m.date/1000000000+978307200)<{ts_jun} THEN 1 ELSE 0 END) h1, SUM(CASE WHEN (m.date/1000000000+978307200)>={ts_jun} THEN 1 ELSE 0 END) h2
        FROM message m JOIN handle h ON m.handle_id=h.ROWID
        WHERE (m.date/1000000000+978307200)>{ts_start}
        AND m.ROWID IN (SELECT msg_id FROM one_on_one_messages)
        AND NOT (LENGTH(REPLACE(REPLACE(h.id, '+', ''), '-', '')) BETWEEN 5 AND 6 AND REPLACE(REPLACE(h.id, '+', ''), '-', '') GLOB '[0-9]*')
        GROUP BY h.id HAVING h1>20 AND h2>h1*1.5 ORDER BY (h2-h1) DESC LIMIT 5
    """)

    # Biggest fan (1:1 only, excluding shortcodes)
    d['fan'] = q(f"""{one_on_one_cte}
        SELECT h.id, SUM(CASE WHEN m.is_from_me=0 THEN 1 ELSE 0 END) t, SUM(CASE WHEN m.is_from_me=1 THEN 1 ELSE 0 END) y
        FROM message m JOIN handle h ON m.handle_id=h.ROWID
        WHERE (m.date/1000000000+978307200)>{ts_start}
        AND m.ROWID IN (SELECT msg_id FROM one_on_one_messages)
        AND NOT (LENGTH(REPLACE(REPLACE(h.id, '+', ''), '-', '')) BETWEEN 5 AND 6 AND REPLACE(REPLACE(h.id, '+', ''), '-', '') GLOB '[0-9]*')
        GROUP BY h.id HAVING t>y*2 AND (t+y)>100 ORDER BY (t*1.0/NULLIF(y,0)) DESC LIMIT 5
    """)

    # Simp (1:1 only, excluding shortcodes)
    d['simp'] = q(f"""{one_on_one_cte}
        SELECT h.id, SUM(CASE WHEN m.is_from_me=1 THEN 1 ELSE 0 END) y, SUM(CASE WHEN m.is_from_me=0 THEN 1 ELSE 0 END) t
        FROM message m JOIN handle h ON m.handle_id=h.ROWID
        WHERE (m.date/1000000000+978307200)>{ts_start}
        AND m.ROWID IN (SELECT msg_id FROM one_on_one_messages)
        AND NOT (LENGTH(REPLACE(REPLACE(h.id, '+', ''), '-', '')) BETWEEN 5 AND 6 AND REPLACE(REPLACE(h.id, '+', ''), '-', '') GLOB '[0-9]*')
        GROUP BY h.id HAVING y>t*2 AND (t+y)>100 ORDER BY (y*1.0/NULLIF(t,0)) DESC LIMIT 5
    """)
    
    # Response time: partition by handle_id so we measure per-conversation (1:1 only)
    r = q(f"""
        WITH chat_participants AS (
            SELECT chat_id, COUNT(*) as participant_count
            FROM chat_handle_join
            GROUP BY chat_id
        ),
        one_on_one_messages AS (
            SELECT m.ROWID as msg_id
            FROM message m
            JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
            JOIN chat_participants cp ON cmj.chat_id = cp.chat_id
            WHERE cp.participant_count = 1
        ),
        g AS (
            SELECT (m.date/1000000000+978307200) ts, m.is_from_me, m.handle_id,
                   LAG(m.date/1000000000+978307200) OVER (PARTITION BY m.handle_id ORDER BY m.date) pt,
                   LAG(m.is_from_me) OVER (PARTITION BY m.handle_id ORDER BY m.date) pf
            FROM message m
            WHERE (m.date/1000000000+978307200)>{ts_start}
            AND m.ROWID IN (SELECT msg_id FROM one_on_one_messages)
        )
        SELECT AVG(ts-pt)/60.0 FROM g
        WHERE is_from_me=1 AND pf=0 AND (ts-pt)<86400 AND (ts-pt)>10
    """)
    d['resp'] = int(r[0][0] or 30)
    
    emojis = ['😂','❤️','😭','🔥','💀','✨','🙏','👀','💯','😈']
    counts = {}
    for e in emojis:
        r = q(f"SELECT COUNT(*) FROM message WHERE text LIKE '%{e}%' AND (date/1000000000+978307200)>{ts_start} AND is_from_me=1")
        counts[e] = r[0][0]
    d['emoji'] = sorted(counts.items(), key=lambda x:-x[1])[:5]
    
    # Total words sent (excluding reactions, empty messages, and attachments-only)
    # Simple approach: count messages with text as minimum, then add extra for spaces
    # This ensures we get at least 1 word per text message
    r = q(f"""
        SELECT
            COUNT(*) as msg_count,
            COALESCE(SUM(LENGTH(text) - LENGTH(REPLACE(text, ' ', ''))), 0) as extra_words
        FROM message
        WHERE (date/1000000000+978307200)>{ts_start}
        AND is_from_me=1
        AND text IS NOT NULL
        AND LENGTH(text) > 0
        AND text NOT LIKE 'Loved "%'
        AND text NOT LIKE 'Liked "%'
        AND text NOT LIKE 'Disliked "%'
        AND text NOT LIKE 'Laughed at "%'
        AND text NOT LIKE 'Emphasized "%'
        AND text NOT LIKE 'Questioned "%'
        AND text NOT LIKE '%￼%'
    """)
    # Words = number of messages with text + number of spaces (each space = 1 extra word)
    msg_count = r[0][0] or 0
    extra_words = r[0][1] or 0
    d['words'] = msg_count + extra_words
    
    # NEW: Busiest day
    r = q(f"SELECT DATE(datetime((date/1000000000+978307200),'unixepoch','localtime')) d, COUNT(*) c FROM message WHERE (date/1000000000+978307200)>{ts_start} GROUP BY d ORDER BY c DESC LIMIT 1")
    if r:
        d['busiest_day'] = (r[0][0], r[0][1])  # ('2025-03-15', 523)
    else:
        d['busiest_day'] = None
    
    # NEW: Conversation starter % (who texts first after 4+ hour gap) - 1:1 only
    r = q(f"""
        WITH chat_participants AS (
            SELECT chat_id, COUNT(*) as participant_count
            FROM chat_handle_join
            GROUP BY chat_id
        ),
        one_on_one_messages AS (
            SELECT m.ROWID as msg_id
            FROM message m
            JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
            JOIN chat_participants cp ON cmj.chat_id = cp.chat_id
            WHERE cp.participant_count = 1
        ),
        convos AS (
            SELECT m.is_from_me,
                   (m.date/1000000000+978307200) as ts,
                   LAG(m.date/1000000000+978307200) OVER (PARTITION BY m.handle_id ORDER BY m.date) as prev_ts
            FROM message m
            WHERE (m.date/1000000000+978307200)>{ts_start}
            AND m.ROWID IN (SELECT msg_id FROM one_on_one_messages)
        )
        SELECT
            SUM(CASE WHEN is_from_me=1 THEN 1 ELSE 0 END) as you_started,
            COUNT(*) as total
        FROM convos
        WHERE prev_ts IS NULL OR (ts - prev_ts) > 14400
    """)
    if r and r[0][1] and r[0][1] > 0:
        you_started = r[0][0] or 0
        d['starter_pct'] = round((you_started / r[0][1]) * 100)
    else:
        d['starter_pct'] = 50
    
    # Personality
    s = d['stats']
    ratio = s[1] / (s[2] + 1)
    if d['hour'] < 5 or d['hour'] > 22: d['personality'] = ("NOCTURNAL MENACE", "terrorizes people at ungodly hours")
    elif d['resp'] < 5: d['personality'] = ("TERMINALLY ONLINE", "has never touched grass")
    elif d['resp'] > 120: d['personality'] = ("TOO COOL TO REPLY", "leaves everyone on read")
    elif ratio < 0.5: d['personality'] = ("POPULAR (ALLEGEDLY)", "everyone wants a piece")
    elif ratio > 2: d['personality'] = ("THE YAPPER", "carries every conversation alone")
    elif d['starter_pct'] > 65: d['personality'] = ("CONVERSATION STARTER", "always making the first move")
    elif d['starter_pct'] < 35: d['personality'] = ("THE WAITER", "never texts first, ever")
    else: d['personality'] = ("SUSPICIOUSLY NORMAL", "no notes. boring but stable.")

    # === CONTRIBUTION GRAPH DATA ===
    # Get daily message counts for the year
    daily_counts = q(f"""
        SELECT DATE(datetime((date/1000000000+978307200),'unixepoch','localtime')) as d, COUNT(*) as c
        FROM message
        WHERE (date/1000000000+978307200)>{ts_start}
        GROUP BY d
        ORDER BY d
    """)
    d['daily_counts'] = {row[0]: row[1] for row in daily_counts}

    # Calculate streaks and stats
    from datetime import datetime as dt, timedelta
    if d['daily_counts']:
        all_counts = list(d['daily_counts'].values())
        d['max_daily'] = max(all_counts) if all_counts else 0
        d['active_days'] = len([c for c in all_counts if c > 0])

        # Top 5 most active days
        sorted_days = sorted(d['daily_counts'].items(), key=lambda x: -x[1])[:5]
        d['top_days'] = sorted_days

        # Average messages per active day
        d['avg_daily'] = round(sum(all_counts) / max(len(all_counts), 1))

        # Find busiest month
        monthly_counts = {}
        for date_str, count in d['daily_counts'].items():
            month_key = date_str[:7]  # "2025-03" format
            monthly_counts[month_key] = monthly_counts.get(month_key, 0) + count
        if monthly_counts:
            busiest_month_key = max(monthly_counts, key=monthly_counts.get)
            d['busiest_month'] = dt.strptime(busiest_month_key, '%Y-%m').strftime('%b')
            d['busiest_month_count'] = monthly_counts[busiest_month_key]
        else:
            d['busiest_month'] = 'N/A'
            d['busiest_month_count'] = 0

        # Calculate quiet days (days with 0 messages in the year so far)
        first_data_date = min(d['daily_counts'].keys())
        last_data_date = max(d['daily_counts'].keys())
        first_dt = dt.strptime(first_data_date, '%Y-%m-%d').date()
        last_dt = dt.strptime(last_data_date, '%Y-%m-%d').date()
        total_days_in_range = (last_dt - first_dt).days + 1
        d['quiet_days'] = total_days_in_range - d['active_days']
    else:
        d['daily_counts'] = {}
        d['max_daily'] = 0
        d['active_days'] = 0
        d['top_days'] = []
        d['avg_daily'] = 0
        d['busiest_month'] = 'N/A'
        d['busiest_month_count'] = 0
        d['quiet_days'] = 0

    # === GROUP CHAT STATS ===
    # Group chats have 2+ participants in chat_handle_join
    group_chat_cte = """
        WITH chat_participants AS (
            SELECT chat_id, COUNT(*) as participant_count
            FROM chat_handle_join
            GROUP BY chat_id
        ),
        group_chats AS (
            SELECT chat_id FROM chat_participants WHERE participant_count >= 2
        ),
        group_messages AS (
            SELECT m.ROWID as msg_id, cmj.chat_id
            FROM message m
            JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
            WHERE cmj.chat_id IN (SELECT chat_id FROM group_chats)
        )
    """

    # Group chat overview: count of groups, total messages, sent by you
    r = q(f"""{group_chat_cte}
        SELECT
            (SELECT COUNT(DISTINCT chat_id) FROM group_messages gm
             JOIN message m ON gm.msg_id = m.ROWID
             WHERE (m.date/1000000000+978307200)>{ts_start}) as group_count,
            COUNT(*) as total_msgs,
            SUM(CASE WHEN m.is_from_me=1 THEN 1 ELSE 0 END) as sent
        FROM message m
        WHERE (m.date/1000000000+978307200)>{ts_start}
        AND m.ROWID IN (SELECT msg_id FROM group_messages)
    """)
    if r and r[0][0]:
        d['group_stats'] = {
            'count': r[0][0] or 0,
            'total': r[0][1] or 0,
            'sent': r[0][2] or 0
        }
    else:
        d['group_stats'] = {'count': 0, 'total': 0, 'sent': 0}

    # Group chat leaderboard: top 5 most active group chats
    # Get chat_id, display_name, message count, and participant handles for name fallback
    r = q(f"""
        WITH chat_participants AS (
            SELECT chat_id, COUNT(*) as participant_count
            FROM chat_handle_join
            GROUP BY chat_id
        ),
        group_chats AS (
            SELECT chat_id FROM chat_participants WHERE participant_count >= 2
        ),
        group_messages AS (
            SELECT m.ROWID as msg_id, cmj.chat_id
            FROM message m
            JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
            WHERE cmj.chat_id IN (SELECT chat_id FROM group_chats)
            AND (m.date/1000000000+978307200)>{ts_start}
        )
        SELECT
            c.ROWID as chat_id,
            c.display_name,
            COUNT(*) as msg_count,
            (SELECT COUNT(*) FROM chat_handle_join WHERE chat_id = c.ROWID) as participant_count
        FROM chat c
        JOIN group_messages gm ON c.ROWID = gm.chat_id
        GROUP BY c.ROWID
        ORDER BY msg_count DESC
        LIMIT 5
    """)
    d['group_leaderboard'] = []
    for row in r:
        chat_id, display_name, msg_count, participant_count = row
        if display_name:
            name = display_name
        else:
            # Get first 2 participant names for fallback
            handles = q(f"""
                SELECT h.id FROM chat_handle_join chj
                JOIN handle h ON chj.handle_id = h.ROWID
                WHERE chj.chat_id = {chat_id}
                LIMIT 2
            """)
            name = handles  # Will be resolved to names in gen_html
        d['group_leaderboard'].append({
            'chat_id': chat_id,
            'name': name,
            'msg_count': msg_count,
            'participant_count': participant_count
        })

    return d

def gen_html(d, contacts, path):
    s = d['stats']
    top = d['top']
    n = lambda h: get_name(h, contacts)
    ptype, proast = d['personality']
    hr = d['hour']
    # Format hour: 0->12AM, 1-11->AM, 12->12PM, 13-23->PM
    if hr == 0:
        hr_str = "12AM"
    elif hr < 12:
        hr_str = f"{hr}AM"
    elif hr == 12:
        hr_str = "12PM"
    else:
        hr_str = f"{hr-12}PM"
    
    # Format busiest day
    from datetime import datetime as dt
    if d['busiest_day']:
        bd = dt.strptime(d['busiest_day'][0], '%Y-%m-%d')
        busiest_str = bd.strftime('%b %d')
        busiest_count = d['busiest_day'][1]
    else:
        busiest_str = "N/A"
        busiest_count = 0

    # Calculate days elapsed in the year for accurate per-day stats
    now = dt.now()
    year_start = dt(now.year, 1, 1)
    days_elapsed = max(1, (now - year_start).days)  # At least 1 to avoid div by zero
    msgs_per_day = s[0] // days_elapsed

    slides = []

    # Slide 1: Intro
    slides.append('''
    <div class="slide intro">
        <div class="slide-icon">📱</div>
        <h1>iMESSAGE<br>WRAPPED</h1>
        <p class="subtitle">your 2025 texting habits, exposed</p>
        <div class="tap-hint">click anywhere to start →</div>
    </div>''')

    # Slide 2: Total messages
    slides.append(f'''
    <div class="slide">
        <div class="slide-label">// TOTAL DAMAGE</div>
        <div class="big-number green">{s[0]:,}</div>
        <div class="slide-text">messages this year</div>
        <div class="stat-grid">
            <div class="stat-item"><span class="stat-num">{msgs_per_day}</span><span class="stat-lbl">/day</span></div>
            <div class="stat-item"><span class="stat-num">{s[1]:,}</span><span class="stat-lbl">sent</span></div>
            <div class="stat-item"><span class="stat-num">{s[2]:,}</span><span class="stat-lbl">received</span></div>
        </div>
        <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_total_messages.png', this)">📸 Save</button>
        <div class="slide-watermark">wrap2025.com</div>
    </div>''')
    
    # Slide 3: Words sent
    words = d['words']
    words_display = f"{words // 1000:,}K" if words >= 1000 else f"{words:,}"
    pages = max(1, words // 250)  # At least 1 page
    slides.append(f'''
    <div class="slide">
        <div class="slide-label">// WORD COUNT</div>
        <div class="big-number cyan">{words_display}</div>
        <div class="slide-text">words you typed</div>
        <div class="roast">that's about {pages:,} pages of a novel</div>
        <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_word_count.png', this)">📸 Save</button>
        <div class="slide-watermark">wrap2025.com</div>
    </div>''')

    # Slide 4: Contribution Graph (GitHub-style activity heatmap) - Year overview
    if d['daily_counts']:
        from datetime import datetime as dt, timedelta
        # Use the analysis year passed from main, extend to current date
        year = d.get('year', now.year)
        year_start = dt(year, 1, 1)
        # Always extend to today's date
        today = dt.now()
        year_end = today

        # Build the calendar grid (53 weeks x 7 days)
        # GitHub style: columns are weeks, rows are days (Sun=0 to Sat=6)
        cal_cells = []

        # Find the first Sunday on or before Jan 1
        first_day = year_start
        while first_day.weekday() != 6:  # 6 = Sunday in Python
            first_day -= timedelta(days=1)

        # Generate 53 weeks of data
        current_date = first_day
        max_count = d['max_daily'] if d['max_daily'] > 0 else 1

        # Month labels - track when months start
        month_labels = []
        last_month = -1

        week_idx = 0
        while current_date <= year_end + timedelta(days=6):  # Go a bit past to fill last week
            week_cells = []
            for day_of_week in range(7):  # Sun to Sat
                date_str = current_date.strftime('%Y-%m-%d')
                count = d['daily_counts'].get(date_str, 0)

                # Track month changes for labels
                if current_date.month != last_month and year_start <= current_date <= year_end:
                    month_labels.append((week_idx, current_date.strftime('%b')))
                    last_month = current_date.month

                # Determine intensity level (0-4 like GitHub)
                if count == 0:
                    level = 0
                elif count <= max_count * 0.25:
                    level = 1
                elif count <= max_count * 0.5:
                    level = 2
                elif count <= max_count * 0.75:
                    level = 3
                else:
                    level = 4

                # Only show cells for the target year
                in_year = year_start <= current_date <= year_end
                week_cells.append((date_str, count, level, in_year))
                current_date += timedelta(days=1)

            cal_cells.append(week_cells)
            week_idx += 1
            if week_idx > 53:  # Safety limit
                break

        # Build the HTML grid
        contrib_html = '<div class="contrib-graph">'
        contrib_html += '<div class="contrib-months">'
        for week_num, month_name in month_labels[:12]:  # Max 12 months
            contrib_html += f'<span style="grid-column:{week_num + 1}">{month_name}</span>'
        contrib_html += '</div>'
        contrib_html += '<div class="contrib-days"><span>Sun</span><span>Mon</span><span>Tue</span><span>Wed</span><span>Thu</span><span>Fri</span><span>Sat</span></div>'
        contrib_html += '<div class="contrib-grid">'

        for week in cal_cells:
            contrib_html += '<div class="contrib-week">'
            for date_str, count, level, in_year in week:
                if in_year:
                    # Format date nicely for tooltip (e.g., "Dec 7, 2025")
                    from datetime import datetime as dt_parse
                    try:
                        date_obj = dt_parse.strptime(date_str, '%Y-%m-%d')
                        formatted_date = date_obj.strftime('%b %d, %Y')
                    except:
                        formatted_date = date_str
                    msg_text = "message" if count == 1 else "messages"
                    contrib_html += f'<div class="contrib-cell level-{level}" data-date="{formatted_date}" data-count="{count}" data-msg-text="{msg_text}"></div>'
                else:
                    contrib_html += '<div class="contrib-cell empty"></div>'
            contrib_html += '</div>'

        contrib_html += '</div>'
        # Legend
        contrib_html += '<div class="contrib-legend"><span>Less</span><div class="contrib-cell level-0"></div><div class="contrib-cell level-1"></div><div class="contrib-cell level-2"></div><div class="contrib-cell level-3"></div><div class="contrib-cell level-4"></div><span>More</span></div>'
        contrib_html += '</div>'

        slides.append(f'''
        <div class="slide contrib-slide">
            <div class="slide-label">// MESSAGE ACTIVITY</div>
            <div class="slide-text">your texting throughout the year</div>
            {contrib_html}
            <div class="contrib-stats">
                <div class="contrib-stat"><span class="contrib-stat-num">{d['avg_daily']}</span><span class="contrib-stat-lbl">avg/day</span></div>
                <div class="contrib-stat"><span class="contrib-stat-num">{d['busiest_month']}</span><span class="contrib-stat-lbl">busiest month</span></div>
                <div class="contrib-stat"><span class="contrib-stat-num">{d['quiet_days']}</span><span class="contrib-stat-lbl">quiet days</span></div>
            </div>
            <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_contribution_graph.png', this)">📸 Save</button>
            <div class="slide-watermark">wrap2025.com</div>
        </div>''')

    # Slide 5: Your #1 (only if we have contacts)
    if top:
        slides.append(f'''
        <div class="slide pink-bg">
            <div class="slide-label">// YOUR #1</div>
            <div class="slide-text">most texted person</div>
            <div class="huge-name">{n(top[0][0])}</div>
            <div class="big-number yellow">{top[0][1]:,}</div>
            <div class="slide-text">messages</div>
            <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_your_number_one.png', this)">📸 Save</button>
            <div class="slide-watermark">wrap2025.com</div>
        </div>''')

        # Slide 5: Top 5
        top5_html = ''.join([f'<div class="rank-item"><span class="rank-num">{i}</span><span class="rank-name">{n(h)}</span><span class="rank-count">{t:,}</span></div>' for i,(h,t,_,_) in enumerate(top[:5],1)])
        slides.append(f'''
        <div class="slide">
            <div class="slide-label">// INNER CIRCLE</div>
            <div class="slide-text">your top 5</div>
            <div class="rank-list">{top5_html}</div>
            <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_inner_circle.png', this)">📸 Save</button>
            <div class="slide-watermark">wrap2025.com</div>
        </div>''')
    
    # === GROUP CHAT SLIDES (after top 5, before personality) ===
    gs = d['group_stats']
    if gs['count'] > 0:
        # Calculate lurker vs contributor ratio
        lurker_pct = round((1 - gs['sent'] / max(gs['total'], 1)) * 100)
        lurker_label = "LURKER" if lurker_pct > 60 else "CONTRIBUTOR" if lurker_pct < 40 else "BALANCED"
        lurker_class = "yellow" if lurker_pct > 60 else "green" if lurker_pct < 40 else "cyan"

        # Slide 6: Group Chat Overview
        slides.append(f'''
        <div class="slide">
            <div class="slide-label">// GROUP CHATS</div>
            <div class="slide-icon">👥</div>
            <div class="big-number green">{gs['count']}</div>
            <div class="slide-text">active group chats</div>
            <div class="stat-grid">
                <div class="stat-item"><span class="stat-num">{gs['total']:,}</span><span class="stat-lbl">total msgs</span></div>
                <div class="stat-item"><span class="stat-num">{gs['sent']:,}</span><span class="stat-lbl">sent</span></div>
                <div class="stat-item"><span class="stat-num">{round(gs['sent']/max(gs['total'],1)*100)}%</span><span class="stat-lbl">yours</span></div>
            </div>
            <div class="badge {lurker_class}">{lurker_label}</div>
            <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_group_chats.png', this)">📸 Save</button>
            <div class="slide-watermark">wrap2025.com</div>
        </div>''')

        # Slide 7: Group Chat Leaderboard
        if d['group_leaderboard']:
            # Helper to format group name
            def format_group_name(gc):
                if isinstance(gc['name'], str):
                    return gc['name']
                else:
                    # gc['name'] is a list of handle tuples from SQL
                    handles = gc['name']
                    names = [n(h[0]) for h in handles[:2]]
                    extra = gc['participant_count'] - len(names)
                    if extra > 0:
                        return f"{', '.join(names)} +{extra}"
                    return ', '.join(names)

            gc_html = ''.join([
                f'<div class="rank-item"><span class="rank-num">{i}</span><span class="rank-name">{format_group_name(gc)}</span><span class="rank-count">{gc["msg_count"]:,}</span></div>'
                for i, gc in enumerate(d['group_leaderboard'][:5], 1)
            ])
            slides.append(f'''
            <div class="slide orange-bg">
                <div class="slide-label">// TOP GROUP CHATS</div>
                <div class="slide-text">your most active groups</div>
                <div class="rank-list">{gc_html}</div>
                <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_top_groups.png', this)">📸 Save</button>
                <div class="slide-watermark">wrap2025.com</div>
            </div>''')

    # Slide 8: Personality
    slides.append(f'''
    <div class="slide purple-bg">
        <div class="slide-label">// DIAGNOSIS</div>
        <div class="slide-text">texting personality</div>
        <div class="personality-type">{ptype}</div>
        <div class="roast">"{proast}"</div>
        <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_personality.png', this)">📸 Save</button>
        <div class="slide-watermark">wrap2025.com</div>
    </div>''')

    # Slide 9: Conversation Starter (Who texts first)
    starter_label = "YOU START" if d['starter_pct'] > 50 else "THEY START"
    starter_class = "green" if d['starter_pct'] > 50 else "yellow"
    slides.append(f'''
    <div class="slide">
        <div class="slide-label">// WHO TEXTS FIRST</div>
        <div class="slide-text">conversation initiator</div>
        <div class="big-number {starter_class}">{d['starter_pct']}<span class="pct">%</span></div>
        <div class="slide-text">of convos started by you</div>
        <div class="badge {starter_class}">{starter_label}</div>
        <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_who_texts_first.png', this)">📸 Save</button>
        <div class="slide-watermark">wrap2025.com</div>
    </div>''')

    # Slide 10: Response time
    resp_class = 'green' if d['resp'] < 10 else 'yellow' if d['resp'] < 60 else 'red'
    resp_label = "INSTANT" if d['resp'] < 10 else "NORMAL" if d['resp'] < 60 else "SLOW"
    slides.append(f'''
    <div class="slide">
        <div class="slide-label">// RESPONSE TIME</div>
        <div class="slide-text">avg reply</div>
        <div class="big-number {resp_class}">{d['resp']}</div>
        <div class="slide-text">minutes</div>
        <div class="badge {resp_class}">{resp_label}</div>
        <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_response_time.png', this)">📸 Save</button>
        <div class="slide-watermark">wrap2025.com</div>
    </div>''')

    # Slide 11: Peak hours
    slides.append(f'''
    <div class="slide">
        <div class="slide-label">// PEAK HOURS</div>
        <div class="slide-text">most active</div>
        <div class="big-number green">{hr_str}</div>
        <div class="slide-text">on <span class="yellow">{d['day']}s</span></div>
        <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_peak_hours.png', this)">📸 Save</button>
        <div class="slide-watermark">wrap2025.com</div>
    </div>''')

    # Slide 12: 3AM Bestie
    if d['late']:
        ln = d['late'][0]
        slides.append(f'''
        <div class="slide">
            <div class="slide-label">// 3AM BESTIE</div>
            <div class="slide-icon">🌙</div>
            <div class="huge-name cyan">{n(ln[0])}</div>
            <div class="big-number yellow">{ln[1]}</div>
            <div class="slide-text">late night texts</div>
            <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_3am_bestie.png', this)">📸 Save</button>
            <div class="slide-watermark">wrap2025.com</div>
        </div>''')

    # Slide 13: Busiest Day
    if d['busiest_day']:
        slides.append(f'''
        <div class="slide">
            <div class="slide-label">// BUSIEST DAY</div>
            <div class="slide-text">your most unhinged day</div>
            <div class="big-number orange">{busiest_str}</div>
            <div class="slide-text"><span class="yellow">{busiest_count:,}</span> messages in one day</div>
            <div class="roast">what happened??</div>
            <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_busiest_day.png', this)">📸 Save</button>
            <div class="slide-watermark">wrap2025.com</div>
        </div>''')

    # Slide 14: Biggest fan
    if d['fan']:
        f = d['fan'][0]
        ratio = round(f[1]/(f[2]+1), 1)
        slides.append(f'''
        <div class="slide">
            <div class="slide-label">// BIGGEST FAN</div>
            <div class="slide-text">texts you most</div>
            <div class="huge-name orange">{n(f[0])}</div>
            <div class="slide-text"><span class="big-number yellow" style="font-size:56px">{ratio}x</span> more than you</div>
            <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_biggest_fan.png', this)">📸 Save</button>
            <div class="slide-watermark">wrap2025.com</div>
        </div>''')

    # Slide 15: Down bad
    if d['simp']:
        si = d['simp'][0]
        ratio = round(si[1]/(si[2]+1), 1)
        slides.append(f'''
        <div class="slide red-bg">
            <div class="slide-label">// DOWN BAD</div>
            <div class="slide-text">you simp for</div>
            <div class="huge-name">{n(si[0])}</div>
            <div class="slide-text">you text <span class="big-number yellow" style="font-size:56px">{ratio}x</span> more</div>
            <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_down_bad.png', this)">📸 Save</button>
            <div class="slide-watermark">wrap2025.com</div>
        </div>''')

    # Slide 16: Heating Up
    if d['heating']:
        heat_html = ''.join([f'<div class="rank-item"><span class="rank-num">🔥</span><span class="rank-name">{n(h)}</span><span class="rank-count green">+{h2-h1}</span></div>' for h,h1,h2 in d['heating'][:5]])
        slides.append(f'''
        <div class="slide orange-bg">
            <div class="slide-label">// HEATING UP</div>
            <div class="slide-text">getting stronger in H2</div>
            <div class="rank-list">{heat_html}</div>
            <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_heating_up.png', this)">📸 Save</button>
            <div class="slide-watermark">wrap2025.com</div>
        </div>''')

    # Slide 17: Ghosted
    if d['ghosted']:
        ghost_html = ''.join([f'<div class="rank-item"><span class="rank-num">👻</span><span class="rank-name">{n(h)}</span><span class="rank-count"><span class="green">{b}</span> → <span class="red">{a}</span></span></div>' for h,b,a in d['ghosted'][:5]])
        slides.append(f'''
        <div class="slide">
            <div class="slide-label">// GHOSTED</div>
            <div class="slide-text">they chose peace</div>
            <div class="rank-list">{ghost_html}</div>
            <div class="roast" style="margin-top:16px;">before June → after</div>
            <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_ghosted.png', this)">📸 Save</button>
            <div class="slide-watermark">wrap2025.com</div>
        </div>''')

    # Slide 18: Emojis
    if d['emoji'] and any(e[1] > 0 for e in d['emoji']):
        emo = '  '.join([e[0] for e in d['emoji'] if e[1] > 0])
        slides.append(f'''
        <div class="slide">
            <div class="slide-label">// EMOJIS</div>
            <div class="slide-text">your emotional range</div>
            <div class="emoji-row">{emo}</div>
            <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_emojis.png', this)">📸 Save</button>
            <div class="slide-watermark">wrap2025.com</div>
        </div>''')

    # Final slide: Summary card
    top3_names = ', '.join([n(h) for h,_,_,_ in top[:3]]) if top else "No contacts"
    slides.append(f'''
    <div class="slide summary-slide">
        <div class="summary-card" id="summaryCard">
            <div class="summary-header">
                <span class="summary-logo">📱</span>
                <span class="summary-title">iMESSAGE WRAPPED 2025</span>
            </div>
            <div class="summary-hero">
                <div class="summary-big-stat">
                    <span class="summary-big-num">{s[0]:,}</span>
                    <span class="summary-big-label">messages</span>
                </div>
            </div>
            <div class="summary-stats">
                <div class="summary-stat">
                    <span class="summary-stat-val">{s[3]:,}</span>
                    <span class="summary-stat-lbl">people</span>
                </div>
                <div class="summary-stat">
                    <span class="summary-stat-val">{words_display}</span>
                    <span class="summary-stat-lbl">words</span>
                </div>
                <div class="summary-stat">
                    <span class="summary-stat-val">{d['starter_pct']}%</span>
                    <span class="summary-stat-lbl">starter</span>
                </div>
                <div class="summary-stat">
                    <span class="summary-stat-val">{d['resp']}m</span>
                    <span class="summary-stat-lbl">response</span>
                </div>
            </div>
            <div class="summary-personality">
                <span class="summary-personality-type">{ptype}</span>
            </div>
            <div class="summary-top3">
                <span class="summary-top3-label">TOP 3:</span>
                <span class="summary-top3-names">{top3_names}</span>
            </div>
            <div class="summary-footer">
                <span>wrap2025.com</span>
            </div>
        </div>
        <button class="screenshot-btn" onclick="takeScreenshot()">
            <span class="btn-icon">📸</span>
            <span>Save Screenshot</span>
        </button>
        <div class="share-hint">share your damage</div>
    </div>''')
    
    slides_html = ''.join(slides)
    num_slides = len(slides)
    
    # Favicon as base64 SVG
    favicon = "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🌯</text></svg>"
    
    html = f'''<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>iMessage Wrapped 2025</title>
<link rel="icon" href="{favicon}">
<script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Silkscreen&family=Azeret+Mono:wght@400;500;600;700&family=Space+Grotesk:wght@400;500;700&display=swap" rel="stylesheet">
<style>

:root {{
    --bg: #0a0a12;
    --text: #f0f0f0;
    --muted: #8892a0;
    --green: #4ade80;
    --yellow: #fbbf24;
    --red: #f87171;
    --cyan: #22d3ee;
    --pink: #f472b6;
    --orange: #fb923c;
    --purple: #a78bfa;
    --font-pixel: 'Silkscreen', cursive;
    --font-mono: 'Azeret Mono', monospace;
    --font-body: 'Space Grotesk', sans-serif;
}}

* {{ margin:0; padding:0; box-sizing:border-box; -webkit-tap-highlight-color:transparent; }}
html, body {{ height:100%; overflow:hidden; }}
body {{ font-family:'Space Grotesk',sans-serif; background:var(--bg); color:var(--text); }}

.gallery {{
    display:flex;
    height:100%;
    transition:transform 0.4s cubic-bezier(0.4,0,0.2,1);
}}

.slide {{
    position:relative;
    min-width:100vw;
    height:100vh;
    display:flex;
    flex-direction:column;
    justify-content:center;
    align-items:center;
    padding:40px 32px 80px;
    text-align:center;
    background:var(--bg);
}}

.slide.intro {{ background:linear-gradient(145deg,#12121f 0%,#1a1a2e 50%,#0f2847 100%); }}
.slide.pink-bg {{ background:linear-gradient(145deg,#12121f 0%,#2d1a3d 100%); }}
.slide.purple-bg {{ background:linear-gradient(145deg,#12121f 0%,#1f1a3d 100%); }}
.slide.orange-bg {{ background:linear-gradient(145deg,#12121f 0%,#2d1f1a 100%); }}
.slide.red-bg {{ background:linear-gradient(145deg,#12121f 0%,#2d1a1a 100%); }}
.slide.summary-slide {{ background:linear-gradient(145deg,#0f2847 0%,#12121f 50%,#1a1a2e 100%); }}
.slide.contrib-slide {{ background:linear-gradient(145deg,#12121f 0%,#0f1f2d 100%); padding:24px 16px 80px; }}

/* === CONTRIBUTION GRAPH STYLES === */
.contrib-graph {{ width:100%; max-width:900px; margin:20px auto; overflow-x:auto; padding:0 8px; }}
.contrib-months {{ display:grid; grid-template-columns:repeat(53,1fr); gap:0; margin-bottom:4px; margin-left:32px; font-size:10px; color:var(--muted); height:16px; }}
.contrib-months span {{ text-align:left; }}
.contrib-days {{ position:absolute; left:8px; display:flex; flex-direction:column; gap:2px; font-size:8px; color:var(--muted); margin-top:20px; }}
.contrib-days span {{ height:10px; line-height:10px; }}
.contrib-days span:nth-child(2), .contrib-days span:nth-child(4), .contrib-days span:nth-child(6) {{ visibility:hidden; }}
.contrib-grid {{ display:flex; gap:2px; margin-left:32px; }}
.contrib-week {{ display:flex; flex-direction:column; gap:2px; }}
.contrib-cell {{ width:10px; height:10px; border-radius:2px; background:rgba(255,255,255,0.05); }}
.contrib-cell.empty {{ background:transparent; }}
.contrib-cell.level-0 {{ background:rgba(255,255,255,0.05); }}
.contrib-cell.level-1 {{ background:rgba(74,222,128,0.25); }}
.contrib-cell.level-2 {{ background:rgba(74,222,128,0.45); }}
.contrib-cell.level-3 {{ background:rgba(74,222,128,0.70); }}
.contrib-cell.level-4 {{ background:var(--green); }}
.contrib-cell:not(.empty) {{ cursor:pointer; position:relative; }}
.contrib-tooltip {{ position:fixed; background:rgba(20,20,30,0.95); color:var(--text); padding:8px 12px; border-radius:6px; font-size:12px; pointer-events:none; z-index:1000; white-space:nowrap; border:1px solid rgba(255,255,255,0.1); box-shadow:0 4px 12px rgba(0,0,0,0.3); }}
.contrib-tooltip .tooltip-count {{ font-family:var(--font-mono); color:var(--green); font-weight:600; }}
.contrib-tooltip .tooltip-date {{ color:var(--muted); font-size:11px; margin-top:2px; }}
.contrib-legend {{ display:flex; align-items:center; justify-content:flex-end; gap:4px; margin-top:8px; font-size:10px; color:var(--muted); padding-right:8px; }}
.contrib-legend .contrib-cell {{ cursor:default; }}
.contrib-stats {{ display:flex; gap:32px; margin-top:24px; justify-content:center; }}
.contrib-stat {{ display:flex; flex-direction:column; align-items:center; }}
.contrib-stat-num {{ font-family:var(--font-mono); font-size:28px; font-weight:600; color:var(--green); }}
.contrib-stat-lbl {{ font-size:11px; color:var(--muted); margin-top:4px; text-transform:uppercase; letter-spacing:0.5px; }}
.top-days-list {{ display:flex; flex-direction:column; gap:8px; margin-top:16px; width:100%; max-width:300px; }}
.top-day-item {{ display:flex; justify-content:space-between; padding:8px 12px; background:rgba(255,255,255,0.05); border-radius:6px; }}
.top-day-date {{ color:var(--muted); font-size:14px; }}
.top-day-count {{ font-family:var(--font-mono); font-size:14px; color:var(--green); font-weight:600; }}

.slide h1 {{ font-family:var(--font-pixel); font-size:36px; font-weight:400; line-height:1.2; margin:20px 0; }}
.slide-label {{ font-family:var(--font-pixel); font-size:12px; font-weight:400; color:var(--green); letter-spacing:0.5px; margin-bottom:16px; }}
.slide-icon {{ font-size:80px; margin-bottom:16px; }}
.slide-text {{ font-size:18px; color:var(--muted); margin:8px 0; }}
.subtitle {{ font-size:18px; color:var(--muted); margin-top:8px; }}

.big-number {{ font-family:var(--font-mono); font-size:80px; font-weight:500; line-height:1; letter-spacing:-2px; }}
.pct {{ font-family:var(--font-body); font-size:48px; }}
.huge-name {{ font-family:var(--font-body); font-size:32px; font-weight:600; line-height:1.25; word-break:break-word; max-width:90%; margin:16px 0; }}
.personality-type {{ font-family:var(--font-pixel); font-size:18px; font-weight:400; line-height:1.25; color:var(--purple); margin:24px 0; text-transform:uppercase; letter-spacing:0.5px; }}
.roast {{ font-style:italic; color:var(--muted); font-size:18px; margin-top:16px; max-width:400px; }}

.green {{ color:var(--green); }}
.yellow {{ color:var(--yellow); }}
.red {{ color:var(--red); }}
.cyan {{ color:var(--cyan); }}
.pink {{ color:var(--pink); }}
.orange {{ color:var(--orange); }}
.purple {{ color:var(--purple); }}

.stat-grid {{ display:flex; gap:40px; margin-top:28px; }}
.stat-item {{ display:flex; flex-direction:column; align-items:center; }}
.stat-num {{ font-family:var(--font-mono); font-size:24px; font-weight:600; color:var(--cyan); }}
.stat-lbl {{ font-size:11px; color:var(--muted); margin-top:6px; text-transform:uppercase; letter-spacing:0.5px; }}

.rank-list {{ width:100%; max-width:420px; margin-top:20px; padding:0 16px 16px; }}
.rank-item {{ display:flex; align-items:center; padding:14px 0; border-bottom:1px solid rgba(255,255,255,0.1); gap:16px; }}
.rank-item:last-child {{ border-bottom:none; }}
.rank-item:first-child {{ background:linear-gradient(90deg, rgba(74,222,128,0.15) 0%, transparent 100%); padding:14px 12px; margin:0 -12px; border-radius:8px; border-bottom:none; }}
.rank-item:first-child .rank-name {{ font-weight:600; color:var(--green); }}
.rank-item:first-child .rank-count {{ font-size:20px; }}
.rank-num {{ font-family:var(--font-mono); font-size:20px; font-weight:600; color:var(--green); width:36px; text-align:center; }}
.rank-name {{ flex:1; font-size:16px; text-align:left; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.rank-count {{ font-family:var(--font-mono); font-size:18px; font-weight:600; color:var(--yellow); }}

.badge {{ display:inline-block; padding:8px 18px; border-radius:24px; font-family:var(--font-pixel); font-size:9px; font-weight:400; text-transform:uppercase; letter-spacing:0.3px; margin-top:20px; border:2px solid; }}
.badge.green {{ border-color:var(--green); color:var(--green); background:rgba(74,222,128,0.1); }}
.badge.yellow {{ border-color:var(--yellow); color:var(--yellow); background:rgba(251,191,36,0.1); }}
.badge.red {{ border-color:var(--red); color:var(--red); background:rgba(248,113,113,0.1); }}
.badge.cyan {{ border-color:var(--cyan); color:var(--cyan); background:rgba(34,211,238,0.1); }}

.emoji-row {{ font-size:64px; letter-spacing:20px; margin:28px 0; }}

.tap-hint {{ position:absolute; bottom:60px; font-size:16px; color:var(--muted); animation:pulse 2s infinite; }}
@keyframes pulse {{ 0%,100%{{opacity:0.4}} 50%{{opacity:1}} }}

/* === SLIDE ANIMATIONS === */
/* Elements start hidden, animate when slide is active */
.slide .slide-label,
.slide .slide-text,
.slide .slide-icon,
.slide .big-number,
.slide .huge-name,
.slide .personality-type,
.slide .roast,
.slide .badge,
.slide .stat-grid,
.slide .rank-item,
.slide .emoji-row,
.slide h1,
.slide .subtitle,
.slide .summary-card,
.slide .contrib-graph,
.slide .contrib-stats {{
    opacity: 0;
    transform: translateY(20px);
}}

/* Gallery transition */
.gallery {{ transition: transform 0.55s cubic-bezier(0.22, 1, 0.36, 1); }}

/* === DEFAULT ANIMATIONS - Varied motion styles === */
.slide.active .slide-label {{ animation: labelSlide 0.4s ease-out forwards; }}
.slide.active .slide-text {{ animation: textFade 0.4s ease-out 0.1s forwards; }}
.slide.active .slide-icon {{ animation: iconPop 0.5s cubic-bezier(0.34, 1.56, 0.64, 1) 0.05s forwards; }}
.slide.active h1 {{ animation: titleReveal 0.5s ease-out 0.12s forwards; }}
.slide.active .subtitle {{ animation: textFade 0.4s ease-out 0.25s forwards; }}
.slide.active .big-number {{ animation: numberFlip 0.6s ease-out 0.18s forwards; }}
.slide.active .huge-name {{ animation: nameBlur 0.5s ease-out 0.2s forwards; }}
.slide.active .personality-type {{ animation: glitchReveal 0.8s ease-out 0.15s forwards; }}
.slide.active .roast {{ animation: roastType 0.6s ease-out 0.4s forwards; }}
.slide.active .badge {{ animation: badgeStamp 0.4s ease-out 0.5s forwards; }}
.slide.active .stat-grid {{ animation: none; opacity: 1; transform: none; }}
.slide.active .stat-item {{ animation: statFade 0.35s ease-out forwards; }}
.slide.active .stat-item:nth-child(1) {{ animation-delay: 0.3s; }}
.slide.active .stat-item:nth-child(2) {{ animation-delay: 0.38s; }}
.slide.active .stat-item:nth-child(3) {{ animation-delay: 0.46s; }}
.slide.active .rank-list {{ animation: none; opacity: 1; transform: none; }}
.slide.active .rank-item {{ animation: rankSlide 0.35s ease-out forwards; }}
.slide.active .rank-item:first-child {{ animation: topRankDrop 0.45s ease-out forwards; }}
.slide.active .rank-item:nth-child(1) {{ animation-delay: 0.1s; }}
.slide.active .rank-item:nth-child(2) {{ animation-delay: 0.18s; }}
.slide.active .rank-item:nth-child(3) {{ animation-delay: 0.26s; }}
.slide.active .rank-item:nth-child(4) {{ animation-delay: 0.34s; }}
.slide.active .rank-item:nth-child(5) {{ animation-delay: 0.42s; }}
.slide.active .emoji-row {{ animation: emojiSpread 0.6s ease-out 0.2s forwards; }}
.slide.active .summary-card {{ animation: cardRise 0.6s ease-out 0.1s forwards; }}
.slide.active .screenshot-btn {{ opacity: 0; animation: buttonSlide 0.4s ease-out 0.5s forwards; }}
.slide.active .share-hint {{ opacity: 0; animation: hintFade 0.4s ease-out 0.7s forwards; }}

/* === INTRO SLIDE - Spin entrance === */
.slide.intro.active .slide-icon {{ animation: introIconSpin 0.7s ease-out forwards; }}
.slide.intro.active h1 {{ animation: introTitleGlitch 0.6s ease-out 0.3s forwards; }}
.slide.intro.active .subtitle {{ animation: textFade 0.4s ease-out 0.5s forwards; }}

/* === PINK SLIDE (#1 person) - Soft glow === */
.slide.pink-bg.active .slide-label {{ animation: textFade 0.4s ease-out forwards; }}
.slide.pink-bg.active .huge-name {{ animation: nameGlow 0.6s ease-out 0.15s forwards; }}
.slide.pink-bg.active .big-number {{ animation: numberFlip 0.5s ease-out 0.35s forwards; }}

/* === PURPLE SLIDE (Personality) - Glitch === */
.slide.purple-bg.active .slide-label {{ animation: labelGlitch 0.5s ease-out forwards; }}
.slide.purple-bg.active .personality-type {{ animation: personalityGlitch 0.8s ease-out 0.12s forwards; }}
.slide.purple-bg.active .roast {{ animation: flickerReveal 0.6s ease-out 0.45s forwards; }}

/* === RED SLIDE (Down Bad) - Drop from above === */
.slide.red-bg.active .slide-label {{ animation: textFade 0.4s ease-out forwards; }}
.slide.red-bg.active .huge-name {{ animation: dramaticDrop 0.5s ease-out 0.12s forwards; }}
.slide.red-bg.active .big-number {{ animation: shakeReveal 0.5s ease-out 0.35s forwards; }}

/* === ORANGE SLIDE (Heating Up / Top Groups) - Glow rise === */
.slide.orange-bg.active .slide-label {{ animation: fireLabel 0.4s ease-out forwards; }}
.slide.orange-bg.active .rank-item {{ animation: glowRise 0.4s ease-out forwards; }}
.slide.orange-bg.active .rank-item:first-child {{ animation: glowRise 0.45s ease-out forwards; }}
.slide.orange-bg.active .rank-item:nth-child(1) {{ animation-delay: 0.06s; }}
.slide.orange-bg.active .rank-item:nth-child(2) {{ animation-delay: 0.14s; }}
.slide.orange-bg.active .rank-item:nth-child(3) {{ animation-delay: 0.22s; }}
.slide.orange-bg.active .rank-item:nth-child(4) {{ animation-delay: 0.30s; }}
.slide.orange-bg.active .rank-item:nth-child(5) {{ animation-delay: 0.38s; }}

/* === SUMMARY SLIDE - Clean rise === */
.slide.summary-slide.active .summary-card {{ animation: cardRise 0.6s ease-out 0.1s forwards; }}

/* === CONTRIBUTION GRAPH SLIDE - Grid reveal === */
.slide.contrib-slide.active .contrib-graph {{ animation: graphReveal 0.8s ease-out 0.15s forwards; }}
.slide.contrib-slide.active .contrib-stats {{ animation: none; opacity: 1; transform: none; }}
.slide.contrib-slide.active .contrib-stat {{ animation: statFade 0.35s ease-out forwards; }}
.slide.contrib-slide.active .contrib-stat:nth-child(1) {{ animation-delay: 0.5s; }}
.slide.contrib-slide.active .contrib-stat:nth-child(2) {{ animation-delay: 0.6s; }}
.slide.contrib-slide.active .contrib-stat:nth-child(3) {{ animation-delay: 0.7s; }}

/* ===== KEYFRAMES ===== */

/* Base animations - VARIED STYLES */

/* Slide from diagonal */
@keyframes labelSlide {{
    0% {{ opacity: 0; transform: translateY(12px) translateX(-8px); }}
    100% {{ opacity: 1; transform: translateY(0) translateX(0); }}
}}

/* Simple fade up */
@keyframes textFade {{
    0% {{ opacity: 0; transform: translateY(15px); }}
    100% {{ opacity: 1; transform: translateY(0); }}
}}

/* Scale with slight overshoot */
@keyframes titleReveal {{
    0% {{ opacity: 0; transform: translateY(25px) scale(0.95); }}
    70% {{ transform: translateY(-3px) scale(1.01); }}
    100% {{ opacity: 1; transform: translateY(0) scale(1); }}
}}

/* Wobble rotation */
@keyframes iconPop {{
    0% {{ opacity: 0; transform: translateY(20px) scale(0.4) rotate(-15deg); }}
    50% {{ transform: translateY(-8px) scale(1.15) rotate(8deg); }}
    75% {{ transform: translateY(2px) scale(0.95) rotate(-3deg); }}
    100% {{ opacity: 1; transform: translateY(0) scale(1) rotate(0); }}
}}

/* 3D flip reveal - for impactful numbers */
@keyframes numberFlip {{
    0% {{ opacity: 0; transform: perspective(400px) rotateX(-60deg) translateY(20px); }}
    60% {{ transform: perspective(400px) rotateX(10deg); }}
    100% {{ opacity: 1; transform: perspective(400px) rotateX(0) translateY(0); }}
}}

/* Soft blur fade - for names */
@keyframes nameBlur {{
    0% {{ opacity: 0; transform: translateY(20px); filter: blur(8px); }}
    100% {{ opacity: 1; transform: translateY(0); filter: blur(0); }}
}}

/* Typewriter cursor feel */
@keyframes roastType {{
    0% {{ opacity: 0; clip-path: inset(0 100% 0 0); }}
    100% {{ opacity: 1; clip-path: inset(0 0 0 0); }}
}}

/* Stagger fade in - for stat items */
@keyframes statFade {{
    0% {{ opacity: 0; transform: translateY(12px); }}
    100% {{ opacity: 1; transform: translateY(0); }}
}}

/* Horizontal slide - for rank items */
@keyframes rankSlide {{
    0% {{ opacity: 0; transform: translateX(-20px); }}
    100% {{ opacity: 1; transform: translateX(0); }}
}}

/* Crown drop for #1 */
@keyframes topRankDrop {{
    0% {{ opacity: 0; transform: translateY(-30px); }}
    70% {{ transform: translateY(4px); }}
    100% {{ opacity: 1; transform: translateY(0); }}
}}

/* Pill stamp - for badges */
@keyframes badgeStamp {{
    0% {{ opacity: 0; transform: scale(1.4); }}
    60% {{ transform: scale(0.95); }}
    100% {{ opacity: 1; transform: scale(1); }}
}}

/* Letter spread - for emoji row */
@keyframes emojiSpread {{
    0% {{ opacity: 0; letter-spacing: 0px; }}
    100% {{ opacity: 1; letter-spacing: 20px; }}
}}

/* Clean rise - for cards */
@keyframes cardRise {{
    0% {{ opacity: 0; transform: translateY(40px); }}
    100% {{ opacity: 1; transform: translateY(0); }}
}}

/* Graph reveal - for contribution graph */
@keyframes graphReveal {{
    0% {{ opacity: 0; transform: translateY(30px) scale(0.95); }}
    100% {{ opacity: 1; transform: translateY(0) scale(1); }}
}}

/* Simple slide up */
@keyframes buttonSlide {{
    0% {{ opacity: 0; transform: translateY(15px); }}
    100% {{ opacity: 1; transform: translateY(0); }}
}}

/* Fade only */
@keyframes hintFade {{
    0% {{ opacity: 0; }}
    100% {{ opacity: 1; }}
}}

/* Intro slide - spin and glitch */
@keyframes introIconSpin {{
    0% {{ opacity: 0; transform: rotate(-180deg) scale(0.3); }}
    100% {{ opacity: 1; transform: rotate(0) scale(1); }}
}}

@keyframes introTitleGlitch {{
    0% {{ opacity: 0; transform: translateY(15px); filter: blur(6px); }}
    40% {{ opacity: 0.8; transform: translateY(3px) skewX(-3deg); filter: blur(2px); }}
    70% {{ transform: translateY(-2px) skewX(2deg); filter: blur(0); }}
    100% {{ opacity: 1; transform: translateY(0) skewX(0); }}
}}

/* Pink slide - soft glow */
@keyframes nameGlow {{
    0% {{ opacity: 0; transform: translateY(15px); filter: blur(4px) brightness(1.3); }}
    100% {{ opacity: 1; transform: translateY(0); filter: blur(0) brightness(1); }}
}}

/* Purple slide - glitch chaos */
@keyframes labelGlitch {{
    0% {{ opacity: 0; transform: skewX(-5deg); }}
    50% {{ opacity: 0.7; transform: skewX(3deg); }}
    100% {{ opacity: 1; transform: skewX(0); }}
}}

@keyframes personalityGlitch {{
    0% {{ opacity: 0; transform: translateY(20px); filter: blur(8px); }}
    20% {{ opacity: 0.5; transform: translateY(10px) skewX(-8deg); filter: blur(4px); }}
    40% {{ opacity: 0.7; transform: translateY(5px) skewX(5deg); filter: blur(2px); }}
    60% {{ opacity: 0.9; transform: translateY(-2px) skewX(-2deg); filter: blur(1px); }}
    80% {{ transform: skewX(1deg); }}
    100% {{ opacity: 1; transform: translateY(0) skewX(0); filter: blur(0); }}
}}

@keyframes flickerReveal {{
    0% {{ opacity: 0; }}
    20% {{ opacity: 0.4; }}
    35% {{ opacity: 0.1; }}
    50% {{ opacity: 0.7; }}
    65% {{ opacity: 0.3; }}
    80% {{ opacity: 0.9; }}
    100% {{ opacity: 1; }}
}}

@keyframes glitchReveal {{
    0% {{ opacity: 0; transform: translateY(15px); filter: blur(4px); }}
    50% {{ opacity: 0.8; transform: translateY(3px) skewX(-3deg); filter: blur(1px); }}
    100% {{ opacity: 1; transform: translateY(0) skewX(0); filter: blur(0); }}
}}

/* Red slide - dramatic drop */
@keyframes dramaticDrop {{
    0% {{ opacity: 0; transform: translateY(-50px); }}
    70% {{ transform: translateY(5px); }}
    100% {{ opacity: 1; transform: translateY(0); }}
}}

@keyframes shakeReveal {{
    0% {{ opacity: 0; transform: translateX(0); }}
    25% {{ opacity: 0.7; transform: translateX(-6px); }}
    50% {{ transform: translateX(6px); }}
    75% {{ transform: translateX(-3px); }}
    100% {{ opacity: 1; transform: translateX(0); }}
}}

/* Orange slide - glow rise */
@keyframes fireLabel {{
    0% {{ opacity: 0; filter: brightness(1.4); }}
    100% {{ opacity: 1; filter: brightness(1); }}
}}

@keyframes glowRise {{
    0% {{ opacity: 0; transform: translateY(20px); filter: brightness(1.3); }}
    100% {{ opacity: 1; transform: translateY(0); filter: brightness(1); }}
}}

.summary-card {{
    background:linear-gradient(145deg,#1a1a2e 0%,#0f1a2e 100%);
    border:2px solid rgba(255,255,255,0.1);
    border-radius:24px;
    padding:32px;
    width:100%;
    max-width:420px;
    text-align:center;
}}
.summary-header {{ display:flex; align-items:center; justify-content:center; gap:12px; margin-bottom:24px; padding-bottom:16px; border-bottom:1px solid rgba(255,255,255,0.1); }}
.summary-logo {{ font-size:28px; }}
.summary-title {{ font-family:var(--font-pixel); font-size:11px; font-weight:400; color:var(--text); }}
.summary-hero {{ margin:24px 0; }}
.summary-big-stat {{ display:flex; flex-direction:column; align-items:center; }}
.summary-big-num {{ font-family:var(--font-mono); font-size:56px; font-weight:600; color:var(--green); line-height:1; letter-spacing:-1px; }}
.summary-big-label {{ font-size:13px; color:var(--muted); text-transform:uppercase; letter-spacing:1px; margin-top:8px; }}
.summary-stats {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin:24px 0; padding:20px 0; border-top:1px solid rgba(255,255,255,0.1); border-bottom:1px solid rgba(255,255,255,0.1); }}
.summary-stat {{ display:flex; flex-direction:column; align-items:center; }}
.summary-stat-val {{ font-family:var(--font-mono); font-size:20px; font-weight:600; color:var(--cyan); }}
.summary-stat-lbl {{ font-size:9px; color:var(--muted); text-transform:uppercase; margin-top:4px; letter-spacing:0.3px; }}
.summary-personality {{ margin:20px 0; }}
.summary-personality-type {{ font-family:var(--font-pixel); font-size:12px; font-weight:400; color:var(--purple); text-transform:uppercase; letter-spacing:0.3px; }}
.summary-top3 {{ margin:16px 0; display:flex; flex-direction:column; gap:6px; }}
.summary-top3-label {{ font-size:10px; color:var(--muted); text-transform:uppercase; letter-spacing:0.5px; }}
.summary-top3-names {{ font-size:13px; color:var(--text); }}
.summary-footer {{ margin-top:20px; padding-top:16px; border-top:1px solid rgba(255,255,255,0.1); font-size:11px; color:var(--green); font-family:var(--font-pixel); font-weight:400; }}

.screenshot-btn {{
    display:flex; align-items:center; justify-content:center; gap:10px;
    font-family:var(--font-pixel); font-size:10px; font-weight:400; text-transform:uppercase; letter-spacing:0.3px;
    background:var(--green); color:#000; border:none;
    padding:16px 32px; border-radius:12px; margin-top:28px;
    cursor:pointer; transition:transform 0.2s,background 0.2s;
}}
.screenshot-btn:hover {{ background:#6ee7b7; transform:scale(1.02); }}
.screenshot-btn:active {{ transform:scale(0.98); }}
.btn-icon {{ font-size:20px; }}
.share-hint {{ font-size:14px; color:var(--muted); margin-top:16px; }}

.slide-save-btn {{
    position:absolute; bottom:100px; left:50%; transform:translateX(-50%);
    display:flex; align-items:center; justify-content:center; gap:8px;
    font-family:var(--font-pixel); font-size:9px; font-weight:400; text-transform:uppercase; letter-spacing:0.3px;
    background:rgba(74,222,128,0.15); color:var(--green); border:1px solid rgba(74,222,128,0.3);
    padding:10px 20px; border-radius:8px;
    cursor:pointer; transition:all 0.2s; opacity:0;
}}
.slide.active .slide-save-btn {{ opacity:1; }}
.slide-save-btn:hover {{ background:rgba(74,222,128,0.25); border-color:var(--green); }}

/* Force all elements visible for screenshot capture */
.slide.capturing,
.slide.capturing * {{
    animation: none !important;
    opacity: 1 !important;
    transform: none !important;
    filter: none !important;
    clip-path: none !important;
}}
.slide-watermark {{
    position:absolute; bottom:24px; left:50%; transform:translateX(-50%);
    font-family:var(--font-pixel); font-size:10px; color:var(--green); opacity:0.6;
    display:none;
}}

.progress {{ position:fixed; bottom:24px; left:50%; transform:translateX(-50%); display:flex; gap:8px; z-index:100; }}
.dot {{ width:10px; height:10px; border-radius:50%; background:rgba(255,255,255,0.2); transition:all 0.3s; cursor:pointer; }}
.dot:hover {{ background:rgba(255,255,255,0.4); }}
.dot.active {{ background:var(--green); transform:scale(1.3); }}

.nav {{ position:fixed; top:50%; transform:translateY(-50%); font-size:36px; color:rgba(255,255,255,0.2); cursor:pointer; z-index:100; padding:24px; transition:color 0.2s; user-select:none; }}
.nav:hover {{ color:rgba(255,255,255,0.5); }}
.nav.prev {{ left:8px; }}
.nav.next {{ right:8px; }}
.nav.hidden {{ opacity:0; pointer-events:none; }}
</style>
</head>
<body>

<div class="gallery" id="gallery">{slides_html}</div>
<div class="progress" id="progress"></div>
<div class="nav prev" id="prev">‹</div>
<div class="nav next" id="next">›</div>

<script>
const gallery = document.getElementById('gallery');
const progressEl = document.getElementById('progress');
const prevBtn = document.getElementById('prev');
const nextBtn = document.getElementById('next');
const total = {num_slides};
let current = 0;

for (let i = 0; i < total; i++) {{
    const dot = document.createElement('div');
    dot.className = 'dot' + (i === 0 ? ' active' : '');
    dot.onclick = () => goTo(i);
    progressEl.appendChild(dot);
}}
const dots = progressEl.querySelectorAll('.dot');

const slides = gallery.querySelectorAll('.slide');

function goTo(idx) {{
    if (idx < 0 || idx >= total) return;
    // Remove active from all slides
    slides.forEach(s => s.classList.remove('active'));
    current = idx;
    gallery.style.transform = `translateX(-${{current * 100}}vw)`;
    dots.forEach((d, i) => d.classList.toggle('active', i === current));
    prevBtn.classList.toggle('hidden', current === 0);
    nextBtn.classList.toggle('hidden', current === total - 1);
    // Add active to current slide after a tiny delay for animation reset
    setTimeout(() => slides[current].classList.add('active'), 50);
}}

document.addEventListener('click', (e) => {{
    if (e.target.closest('.nav, button, .dot')) return;
    const x = e.clientX / window.innerWidth;
    if (x < 0.3) goTo(current - 1);
    else goTo(current + 1);
}});

document.addEventListener('keydown', (e) => {{
    if (e.key === 'ArrowRight' || e.key === ' ') {{ e.preventDefault(); goTo(current + 1); }}
    if (e.key === 'ArrowLeft') {{ e.preventDefault(); goTo(current - 1); }}
}});

prevBtn.onclick = (e) => {{ e.stopPropagation(); goTo(current - 1); }};
nextBtn.onclick = (e) => {{ e.stopPropagation(); goTo(current + 1); }};

async function takeScreenshot() {{
    const card = document.getElementById('summaryCard');
    const btn = document.querySelector('.screenshot-btn');
    btn.innerHTML = '<span>Saving...</span>';
    btn.disabled = true;
    try {{
        const canvas = await html2canvas(card, {{ backgroundColor:'#0f1a2e', scale:2, logging:false, useCORS:true }});
        const link = document.createElement('a');
        link.download = 'imessage_wrapped_2025_summary.png';
        link.href = canvas.toDataURL('image/png');
        link.click();
        btn.innerHTML = '<span class="btn-icon">✓</span><span>Saved!</span>';
        setTimeout(() => {{ btn.innerHTML = '<span class="btn-icon">📸</span><span>Save Screenshot</span>'; btn.disabled = false; }}, 2000);
    }} catch (err) {{
        btn.innerHTML = '<span class="btn-icon">📸</span><span>Save Screenshot</span>';
        btn.disabled = false;
    }}
}}

async function saveSlide(slideEl, filename, btn) {{
    btn.innerHTML = '⏳';
    btn.disabled = true;

    // Show watermark for screenshot
    const watermark = slideEl.querySelector('.slide-watermark');
    if (watermark) watermark.style.display = 'block';

    // Hide the save button temporarily
    btn.style.visibility = 'hidden';

    // Add capturing class to force all animations to final state
    slideEl.classList.add('capturing');

    // Wait for browser to apply styles
    await new Promise(r => setTimeout(r, 50));

    // Get computed background color (html2canvas has issues with CSS variables)
    const computedBg = getComputedStyle(slideEl).backgroundColor;
    const bgColor = computedBg && computedBg !== 'rgba(0, 0, 0, 0)' ? computedBg : '#0a0a12';

    try {{
        const canvas = await html2canvas(slideEl, {{
            backgroundColor: bgColor,
            scale: 2,
            logging: false,
            useCORS: true,
            width: slideEl.offsetWidth,
            height: slideEl.offsetHeight
        }});

        // Create a square canvas centered on content
        const size = Math.min(canvas.width, canvas.height);
        const squareCanvas = document.createElement('canvas');
        squareCanvas.width = size;
        squareCanvas.height = size;
        const ctx = squareCanvas.getContext('2d');

        // Fill with background color
        ctx.fillStyle = bgColor;
        ctx.fillRect(0, 0, size, size);

        // Calculate crop position (center of original)
        const srcX = (canvas.width - size) / 2;
        const srcY = (canvas.height - size) / 2;

        // Draw centered portion
        ctx.drawImage(canvas, srcX, srcY, size, size, 0, 0, size, size);

        const link = document.createElement('a');
        link.download = filename;
        link.href = squareCanvas.toDataURL('image/png');
        link.click();
        btn.innerHTML = '✓';
        setTimeout(() => {{ btn.innerHTML = '📸 Save'; btn.disabled = false; btn.style.visibility = 'visible'; }}, 2000);
    }} catch (err) {{
        btn.innerHTML = '📸 Save';
        btn.disabled = false;
        btn.style.visibility = 'visible';
    }}

    // Remove capturing class and hide watermark
    slideEl.classList.remove('capturing');
    if (watermark) watermark.style.display = 'none';
}}

// Contribution graph tooltip
const tooltip = document.createElement('div');
tooltip.className = 'contrib-tooltip';
tooltip.style.display = 'none';
document.body.appendChild(tooltip);

document.querySelectorAll('.contrib-cell[data-date]').forEach(cell => {{
    cell.addEventListener('mouseenter', (e) => {{
        const count = cell.dataset.count;
        const date = cell.dataset.date;
        const msgText = cell.dataset.msgText;
        tooltip.innerHTML = `<div class="tooltip-count">${{count}} ${{msgText}}</div><div class="tooltip-date">${{date}}</div>`;
        tooltip.style.display = 'block';
    }});
    cell.addEventListener('mousemove', (e) => {{
        tooltip.style.left = (e.clientX + 12) + 'px';
        tooltip.style.top = (e.clientY - 10) + 'px';
    }});
    cell.addEventListener('mouseleave', () => {{
        tooltip.style.display = 'none';
    }});
}});

goTo(0);
</script>
</body></html>'''
    
    with open(path, 'w') as f: f.write(html)
    return path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', '-o', default='imessage_wrapped_2025.html')
    parser.add_argument('--use-2024', action='store_true')
    args = parser.parse_args()
    
    print("\n" + "="*50)
    print("  iMessage WRAPPED 2025 | wrap2025.com")
    print("="*50 + "\n")
    
    print("[*] Checking access...")
    check_access()
    print("    ✓ OK")
    
    print("[*] Loading contacts...")
    contacts = extract_contacts()
    print(f"    ✓ {len(contacts)} indexed")
    
    ts_start, ts_jun = (TS_2024, TS_JUN_2024) if args.use_2024 else (TS_2025, TS_JUN_2025)
    year = "2024" if args.use_2024 else "2025"
    
    test = q(f"SELECT COUNT(*) FROM message WHERE (date/1000000000+978307200)>{TS_2025}")[0][0]
    if test < 100 and not args.use_2024:
        print(f"    ⚠️  {test} msgs in 2025, using 2024")
        ts_start, ts_jun = TS_2024, TS_JUN_2024
        year = "2024"
    
    spinner = Spinner()

    print(f"[*] Analyzing {year}...")
    spinner.start("Reading message database...")
    data = analyze(ts_start, ts_jun)
    data['year'] = int(year)  # Pass the year to gen_html
    spinner.stop(f"{data['stats'][0]:,} messages analyzed")

    print(f"[*] Generating report...")
    spinner.start("Building your wrapped...")
    gen_html(data, contacts, args.output)
    spinner.stop(f"Saved to {args.output}")
    
    subprocess.run(['open', args.output])
    print("\n  Done! Click through your wrapped.\n")

if __name__ == '__main__':
    main()
