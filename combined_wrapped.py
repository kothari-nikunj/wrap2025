#!/usr/bin/env python3
"""
Combined Wrapped 2025 - Your texting habits across iMessage AND WhatsApp, exposed.
Usage: python3 combined_wrapped.py
"""

import sqlite3, os, sys, re, subprocess, argparse, glob, threading, time
from datetime import datetime, timedelta

# Database paths
IMESSAGE_DB = os.path.expanduser("~/Library/Messages/chat.db")
ADDRESSBOOK_DIR = os.path.expanduser("~/Library/Application Support/AddressBook")
WHATSAPP_PATHS = [
    os.path.expanduser("~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite"),
    os.path.expanduser("~/Library/Containers/com.whatsapp/Data/Library/Application Support/WhatsApp/ChatStorage.sqlite"),
    os.path.expanduser("~/Library/Containers/desktop.WhatsApp/Data/Library/Application Support/WhatsApp/ChatStorage.sqlite"),
]

WHATSAPP_DB = None

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

# Timestamps
# iMessage: Unix timestamp in nanoseconds since 2001
TS_2025_IMESSAGE = 1735689600
TS_JUN_2025_IMESSAGE = 1748736000
TS_2024_IMESSAGE = 1704067200
TS_JUN_2024_IMESSAGE = 1717200000

# WhatsApp: Cocoa Core Data Time (seconds since Jan 1, 2001)
COCOA_OFFSET = 978307200
TS_2025_WHATSAPP = 757382400
TS_JUN_2025_WHATSAPP = 770428800
TS_2024_WHATSAPP = 725846400
TS_JUN_2024_WHATSAPP = 738892800

def normalize_phone(phone):
    if not phone: return None
    digits = re.sub(r'\D', '', str(phone))
    if len(digits) == 11 and digits.startswith('1'):
        digits = digits[1:]
    elif len(digits) > 10:
        return digits
    return digits[-10:] if len(digits) >= 10 else (digits if len(digits) >= 7 else None)

def extract_imessage_contacts():
    """Extract contacts from macOS AddressBook."""
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
                    if digits:
                        contacts[digits] = name
                        if len(digits) >= 10:
                            contacts[digits[-10:]] = name
                        if len(digits) >= 7:
                            contacts[digits[-7:]] = name
                        if len(digits) == 11 and digits.startswith('1'):
                            contacts[digits[1:]] = name
            for owner, email in conn.execute("SELECT ZOWNER, ZADDRESS FROM ZABCDEMAILADDRESS WHERE ZADDRESS IS NOT NULL"):
                if owner in people: contacts[email.lower().strip()] = people[owner]
            conn.close()
        except: pass
    return contacts

def extract_whatsapp_contacts():
    """Extract contact names from WhatsApp's ZWAPROFILEPUSHNAME table."""
    contacts = {}
    if not WHATSAPP_DB:
        return contacts
    try:
        conn = sqlite3.connect(WHATSAPP_DB)
        for row in conn.execute("SELECT ZJID, ZPUSHNAME FROM ZWAPROFILEPUSHNAME WHERE ZPUSHNAME IS NOT NULL"):
            jid, name = row
            if jid and name:
                contacts[jid] = name
        conn.close()
    except:
        pass
    return contacts

def get_name_imessage(handle, contacts):
    if '@' in handle:
        lookup = handle.lower().strip()
        if lookup in contacts: return contacts[lookup]
        return handle.split('@')[0]
    digits = re.sub(r'\D', '', str(handle))
    if digits in contacts: return contacts[digits]
    if len(digits) == 11 and digits.startswith('1'):
        if digits[1:] in contacts: return contacts[digits[1:]]
    if len(digits) >= 10 and digits[-10:] in contacts:
        return contacts[digits[-10:]]
    if len(digits) >= 7 and digits[-7:] in contacts:
        return contacts[digits[-7:]]
    return handle

def get_name_whatsapp(jid, contacts):
    if not jid:
        return "Unknown"
    if jid in contacts:
        return contacts[jid]
    if '@' in jid:
        phone = jid.split('@')[0]
        if len(phone) == 10:
            return f"({phone[:3]}) {phone[3:6]}-{phone[6:]}"
        elif len(phone) == 11 and phone.startswith('1'):
            return f"+1 ({phone[1:4]}) {phone[4:7]}-{phone[7:]}"
        return f"+{phone}"
    return jid

def find_whatsapp_database():
    """Find the WhatsApp database path."""
    for path in WHATSAPP_PATHS:
        if os.path.exists(path):
            return path
    return None

def check_access():
    """Check access to both databases. Returns (has_imessage, has_whatsapp)."""
    global WHATSAPP_DB

    has_imessage = False
    has_whatsapp = False

    # Check iMessage
    if os.path.exists(IMESSAGE_DB):
        try:
            conn = sqlite3.connect(IMESSAGE_DB)
            conn.execute("SELECT 1 FROM message LIMIT 1")
            conn.close()
            has_imessage = True
        except:
            pass

    # Check WhatsApp
    WHATSAPP_DB = find_whatsapp_database()
    if WHATSAPP_DB:
        try:
            conn = sqlite3.connect(WHATSAPP_DB)
            conn.execute("SELECT 1 FROM ZWAMESSAGE LIMIT 1")
            conn.close()
            has_whatsapp = True
        except:
            pass

    if not has_imessage and not has_whatsapp:
        print("\n[!] ACCESS DENIED - Neither iMessage nor WhatsApp accessible")
        print("   System Settings -> Privacy & Security -> Full Disk Access -> Add Terminal")
        subprocess.run(['open', 'x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles'])
        sys.exit(1)

    return has_imessage, has_whatsapp

def q_imessage(sql):
    conn = sqlite3.connect(IMESSAGE_DB)
    r = conn.execute(sql).fetchall()
    conn.close()
    return r

def q_whatsapp(sql):
    conn = sqlite3.connect(WHATSAPP_DB)
    r = conn.execute(sql).fetchall()
    conn.close()
    return r

def analyze_imessage(ts_start, ts_jun):
    """Analyze iMessage data and return stats dict."""
    d = {}

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

    # Stats
    raw_stats = q_imessage(f"""{one_on_one_cte}
        SELECT COUNT(*), SUM(CASE WHEN is_from_me=1 THEN 1 ELSE 0 END), SUM(CASE WHEN is_from_me=0 THEN 1 ELSE 0 END), COUNT(DISTINCT handle_id)
        FROM message m
        WHERE (date/1000000000+978307200)>{ts_start}
        AND m.ROWID IN (SELECT msg_id FROM one_on_one_messages)
    """)[0]
    d['stats'] = (raw_stats[0] or 0, raw_stats[1] or 0, raw_stats[2] or 0, raw_stats[3] or 0)

    # Top contacts
    d['top'] = q_imessage(f"""{one_on_one_cte}
        SELECT h.id, COUNT(*) t, SUM(CASE WHEN m.is_from_me=1 THEN 1 ELSE 0 END), SUM(CASE WHEN m.is_from_me=0 THEN 1 ELSE 0 END)
        FROM message m JOIN handle h ON m.handle_id=h.ROWID
        WHERE (m.date/1000000000+978307200)>{ts_start}
        AND m.ROWID IN (SELECT msg_id FROM one_on_one_messages)
        AND NOT (LENGTH(REPLACE(REPLACE(h.id, '+', ''), '-', '')) BETWEEN 5 AND 6 AND REPLACE(REPLACE(h.id, '+', ''), '-', '') GLOB '[0-9]*')
        AND h.id NOT LIKE 'urn:%'
        GROUP BY h.id ORDER BY t DESC LIMIT 20
    """)

    # Late night
    d['late'] = q_imessage(f"""{one_on_one_cte}
        SELECT h.id, COUNT(*) n FROM message m JOIN handle h ON m.handle_id=h.ROWID
        WHERE (m.date/1000000000+978307200)>{ts_start}
        AND CAST(strftime('%H',datetime((m.date/1000000000+978307200),'unixepoch','localtime')) AS INT)<5
        AND m.ROWID IN (SELECT msg_id FROM one_on_one_messages)
        AND NOT (LENGTH(REPLACE(REPLACE(h.id, '+', ''), '-', '')) BETWEEN 5 AND 6 AND REPLACE(REPLACE(h.id, '+', ''), '-', '') GLOB '[0-9]*')
        AND h.id NOT LIKE 'urn:%'
        GROUP BY h.id HAVING n>5 ORDER BY n DESC LIMIT 10
    """)

    # Peak hour
    r = q_imessage(f"SELECT CAST(strftime('%H',datetime((date/1000000000+978307200),'unixepoch','localtime')) AS INT) h, COUNT(*) c FROM message WHERE (date/1000000000+978307200)>{ts_start} GROUP BY h ORDER BY c DESC LIMIT 1")
    d['hour'] = r[0][0] if r else 12

    # Peak day
    days = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday']
    r = q_imessage(f"SELECT CAST(strftime('%w',datetime((date/1000000000+978307200),'unixepoch','localtime')) AS INT) d, COUNT(*) FROM message WHERE (date/1000000000+978307200)>{ts_start} GROUP BY d ORDER BY 2 DESC LIMIT 1")
    d['day'] = days[r[0][0]] if r else '???'

    # Ghosted
    d['ghosted'] = q_imessage(f"""{one_on_one_cte}
        SELECT h.id, SUM(CASE WHEN m.is_from_me=0 AND (m.date/1000000000+978307200)<{ts_jun} THEN 1 ELSE 0 END) b, SUM(CASE WHEN m.is_from_me=0 AND (m.date/1000000000+978307200)>={ts_jun} THEN 1 ELSE 0 END) a
        FROM message m JOIN handle h ON m.handle_id=h.ROWID
        WHERE (m.date/1000000000+978307200)>{ts_start}
        AND m.ROWID IN (SELECT msg_id FROM one_on_one_messages)
        AND NOT (LENGTH(REPLACE(REPLACE(h.id, '+', ''), '-', '')) BETWEEN 5 AND 6 AND REPLACE(REPLACE(h.id, '+', ''), '-', '') GLOB '[0-9]*')
        AND h.id NOT LIKE 'urn:%'
        GROUP BY h.id HAVING b>10 AND a<3 ORDER BY b DESC LIMIT 10
    """)

    # Heating up
    d['heating'] = q_imessage(f"""{one_on_one_cte}
        SELECT h.id, SUM(CASE WHEN (m.date/1000000000+978307200)<{ts_jun} THEN 1 ELSE 0 END) h1, SUM(CASE WHEN (m.date/1000000000+978307200)>={ts_jun} THEN 1 ELSE 0 END) h2
        FROM message m JOIN handle h ON m.handle_id=h.ROWID
        WHERE (m.date/1000000000+978307200)>{ts_start}
        AND m.ROWID IN (SELECT msg_id FROM one_on_one_messages)
        AND NOT (LENGTH(REPLACE(REPLACE(h.id, '+', ''), '-', '')) BETWEEN 5 AND 6 AND REPLACE(REPLACE(h.id, '+', ''), '-', '') GLOB '[0-9]*')
        AND h.id NOT LIKE 'urn:%'
        GROUP BY h.id HAVING h1>20 AND h2>h1*1.5 ORDER BY (h2-h1) DESC LIMIT 10
    """)

    # Biggest fan
    d['fan'] = q_imessage(f"""{one_on_one_cte}
        SELECT h.id, SUM(CASE WHEN m.is_from_me=0 THEN 1 ELSE 0 END) t, SUM(CASE WHEN m.is_from_me=1 THEN 1 ELSE 0 END) y
        FROM message m JOIN handle h ON m.handle_id=h.ROWID
        WHERE (m.date/1000000000+978307200)>{ts_start}
        AND m.ROWID IN (SELECT msg_id FROM one_on_one_messages)
        AND NOT (LENGTH(REPLACE(REPLACE(h.id, '+', ''), '-', '')) BETWEEN 5 AND 6 AND REPLACE(REPLACE(h.id, '+', ''), '-', '') GLOB '[0-9]*')
        AND h.id NOT LIKE 'urn:%'
        GROUP BY h.id HAVING t>y*2 AND (t+y)>100 ORDER BY (t*1.0/NULLIF(y,0)) DESC LIMIT 10
    """)

    # Simp
    d['simp'] = q_imessage(f"""{one_on_one_cte}
        SELECT h.id, SUM(CASE WHEN m.is_from_me=1 THEN 1 ELSE 0 END) y, SUM(CASE WHEN m.is_from_me=0 THEN 1 ELSE 0 END) t
        FROM message m JOIN handle h ON m.handle_id=h.ROWID
        WHERE (m.date/1000000000+978307200)>{ts_start}
        AND m.ROWID IN (SELECT msg_id FROM one_on_one_messages)
        AND NOT (LENGTH(REPLACE(REPLACE(h.id, '+', ''), '-', '')) BETWEEN 5 AND 6 AND REPLACE(REPLACE(h.id, '+', ''), '-', '') GLOB '[0-9]*')
        AND h.id NOT LIKE 'urn:%'
        GROUP BY h.id HAVING y>t*2 AND (t+y)>100 ORDER BY (y*1.0/NULLIF(t,0)) DESC LIMIT 10
    """)

    # Response time
    r = q_imessage(f"""
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

    # Emojis
    emojis = ['😂','❤️','😭','🔥','💀','✨','🙏','👀','💯','😈']
    counts = {}
    for e in emojis:
        r = q_imessage(f"SELECT COUNT(*) FROM message WHERE text LIKE '%{e}%' AND (date/1000000000+978307200)>{ts_start} AND is_from_me=1")
        counts[e] = r[0][0]
    d['emoji'] = counts

    # Words
    r = q_imessage(f"""
        SELECT COUNT(*), COALESCE(SUM(LENGTH(text) - LENGTH(REPLACE(text, ' ', ''))), 0)
        FROM message
        WHERE (date/1000000000+978307200)>{ts_start}
        AND is_from_me=1 AND text IS NOT NULL AND LENGTH(text) > 0
        AND text NOT LIKE 'Loved "%' AND text NOT LIKE 'Liked "%'
        AND text NOT LIKE 'Disliked "%' AND text NOT LIKE 'Laughed at "%'
        AND text NOT LIKE 'Emphasized "%' AND text NOT LIKE 'Questioned "%'
        AND text NOT LIKE '%￼%'
    """)
    d['words'] = (r[0][0] or 0) + (r[0][1] or 0)

    # Busiest day
    r = q_imessage(f"SELECT DATE(datetime((date/1000000000+978307200),'unixepoch','localtime')) d, COUNT(*) c FROM message WHERE (date/1000000000+978307200)>{ts_start} GROUP BY d ORDER BY c DESC LIMIT 1")
    d['busiest_day'] = (r[0][0], r[0][1]) if r else None

    # Starter %
    r = q_imessage(f"""
        WITH chat_participants AS (
            SELECT chat_id, COUNT(*) as participant_count
            FROM chat_handle_join GROUP BY chat_id
        ),
        one_on_one_messages AS (
            SELECT m.ROWID as msg_id FROM message m
            JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
            JOIN chat_participants cp ON cmj.chat_id = cp.chat_id
            WHERE cp.participant_count = 1
        ),
        convos AS (
            SELECT m.is_from_me, (m.date/1000000000+978307200) as ts,
                   LAG(m.date/1000000000+978307200) OVER (PARTITION BY m.handle_id ORDER BY m.date) as prev_ts
            FROM message m WHERE (m.date/1000000000+978307200)>{ts_start}
            AND m.ROWID IN (SELECT msg_id FROM one_on_one_messages)
        )
        SELECT SUM(CASE WHEN is_from_me=1 THEN 1 ELSE 0 END), COUNT(*)
        FROM convos WHERE prev_ts IS NULL OR (ts - prev_ts) > 14400
    """)
    d['starter_pct'] = round((r[0][0] or 0) / max(r[0][1] or 1, 1) * 100) if r and r[0][1] else 50

    # Daily counts
    daily_counts = q_imessage(f"""
        SELECT DATE(datetime((date/1000000000+978307200),'unixepoch','localtime')) as d, COUNT(*) as c
        FROM message WHERE (date/1000000000+978307200)>{ts_start} GROUP BY d ORDER BY d
    """)
    d['daily_counts'] = {row[0]: row[1] for row in daily_counts}

    # Group stats
    group_chat_cte = """
        WITH chat_participants AS (
            SELECT chat_id, COUNT(*) as participant_count FROM chat_handle_join GROUP BY chat_id
        ),
        group_chats AS (
            SELECT chat_id FROM chat_participants WHERE participant_count >= 2
        ),
        group_messages AS (
            SELECT m.ROWID as msg_id, cmj.chat_id FROM message m
            JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
            WHERE cmj.chat_id IN (SELECT chat_id FROM group_chats)
        )
    """
    r = q_imessage(f"""{group_chat_cte}
        SELECT
            (SELECT COUNT(DISTINCT chat_id) FROM group_messages gm
             JOIN message m ON gm.msg_id = m.ROWID WHERE (m.date/1000000000+978307200)>{ts_start}),
            COUNT(*), SUM(CASE WHEN m.is_from_me=1 THEN 1 ELSE 0 END)
        FROM message m WHERE (m.date/1000000000+978307200)>{ts_start}
        AND m.ROWID IN (SELECT msg_id FROM group_messages)
    """)
    d['group_stats'] = {'count': r[0][0] or 0, 'total': r[0][1] or 0, 'sent': r[0][2] or 0} if r else {'count': 0, 'total': 0, 'sent': 0}

    # Group leaderboard
    r = q_imessage(f"""
        WITH chat_participants AS (
            SELECT chat_id, COUNT(*) as participant_count FROM chat_handle_join GROUP BY chat_id
        ),
        group_chats AS (
            SELECT chat_id FROM chat_participants WHERE participant_count >= 2
        ),
        group_messages AS (
            SELECT m.ROWID as msg_id, cmj.chat_id FROM message m
            JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
            WHERE cmj.chat_id IN (SELECT chat_id FROM group_chats)
            AND (m.date/1000000000+978307200)>{ts_start}
        )
        SELECT c.ROWID, c.display_name, COUNT(*),
            (SELECT COUNT(*) FROM chat_handle_join WHERE chat_id = c.ROWID)
        FROM chat c JOIN group_messages gm ON c.ROWID = gm.chat_id
        GROUP BY c.ROWID ORDER BY 3 DESC LIMIT 10
    """)
    d['group_leaderboard'] = []
    for row in r:
        chat_id, display_name, msg_count, participant_count = row
        name = display_name if display_name else f"Group ({participant_count} people)"
        d['group_leaderboard'].append({'name': name, 'msg_count': msg_count})

    return d

def analyze_whatsapp(ts_start, ts_jun):
    """Analyze WhatsApp data and return stats dict."""
    d = {}

    one_on_one_cte = """
        WITH dm_sessions AS (
            SELECT Z_PK, ZCONTACTJID FROM ZWACHATSESSION WHERE ZSESSIONTYPE = 0
        ),
        dm_messages AS (
            SELECT m.Z_PK as msg_id, m.ZCHATSESSION, s.ZCONTACTJID
            FROM ZWAMESSAGE m JOIN dm_sessions s ON m.ZCHATSESSION = s.Z_PK
        )
    """

    # Stats
    raw_stats = q_whatsapp(f"""{one_on_one_cte}
        SELECT COUNT(*), SUM(CASE WHEN m.ZISFROMME=1 THEN 1 ELSE 0 END), SUM(CASE WHEN m.ZISFROMME=0 THEN 1 ELSE 0 END), COUNT(DISTINCT dm.ZCONTACTJID)
        FROM ZWAMESSAGE m JOIN dm_messages dm ON m.Z_PK = dm.msg_id
        WHERE m.ZMESSAGEDATE>{ts_start}
    """)[0]
    d['stats'] = (raw_stats[0] or 0, raw_stats[1] or 0, raw_stats[2] or 0, raw_stats[3] or 0)

    # Top contacts
    d['top'] = q_whatsapp(f"""{one_on_one_cte}
        SELECT dm.ZCONTACTJID, COUNT(*) t, SUM(CASE WHEN m.ZISFROMME=1 THEN 1 ELSE 0 END), SUM(CASE WHEN m.ZISFROMME=0 THEN 1 ELSE 0 END)
        FROM ZWAMESSAGE m JOIN dm_messages dm ON m.Z_PK = dm.msg_id
        WHERE m.ZMESSAGEDATE>{ts_start} GROUP BY dm.ZCONTACTJID ORDER BY t DESC LIMIT 20
    """)

    # Late night
    d['late'] = q_whatsapp(f"""{one_on_one_cte}
        SELECT dm.ZCONTACTJID, COUNT(*) n FROM ZWAMESSAGE m
        JOIN dm_messages dm ON m.Z_PK = dm.msg_id
        WHERE m.ZMESSAGEDATE>{ts_start}
        AND CAST(strftime('%H',datetime(m.ZMESSAGEDATE+{COCOA_OFFSET},'unixepoch','localtime')) AS INT)<5
        GROUP BY dm.ZCONTACTJID HAVING n>5 ORDER BY n DESC LIMIT 10
    """)

    # Peak hour
    r = q_whatsapp(f"SELECT CAST(strftime('%H',datetime(ZMESSAGEDATE+{COCOA_OFFSET},'unixepoch','localtime')) AS INT) h, COUNT(*) c FROM ZWAMESSAGE WHERE ZMESSAGEDATE>{ts_start} GROUP BY h ORDER BY c DESC LIMIT 1")
    d['hour'] = r[0][0] if r else 12

    # Peak day
    days = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday']
    r = q_whatsapp(f"SELECT CAST(strftime('%w',datetime(ZMESSAGEDATE+{COCOA_OFFSET},'unixepoch','localtime')) AS INT) d, COUNT(*) FROM ZWAMESSAGE WHERE ZMESSAGEDATE>{ts_start} GROUP BY d ORDER BY 2 DESC LIMIT 1")
    d['day'] = days[r[0][0]] if r else '???'

    # Ghosted
    d['ghosted'] = q_whatsapp(f"""{one_on_one_cte}
        SELECT dm.ZCONTACTJID, SUM(CASE WHEN m.ZISFROMME=0 AND m.ZMESSAGEDATE<{ts_jun} THEN 1 ELSE 0 END) b, SUM(CASE WHEN m.ZISFROMME=0 AND m.ZMESSAGEDATE>={ts_jun} THEN 1 ELSE 0 END) a
        FROM ZWAMESSAGE m JOIN dm_messages dm ON m.Z_PK = dm.msg_id
        WHERE m.ZMESSAGEDATE>{ts_start} GROUP BY dm.ZCONTACTJID HAVING b>10 AND a<3 ORDER BY b DESC LIMIT 10
    """)

    # Heating up
    d['heating'] = q_whatsapp(f"""{one_on_one_cte}
        SELECT dm.ZCONTACTJID, SUM(CASE WHEN m.ZMESSAGEDATE<{ts_jun} THEN 1 ELSE 0 END) h1, SUM(CASE WHEN m.ZMESSAGEDATE>={ts_jun} THEN 1 ELSE 0 END) h2
        FROM ZWAMESSAGE m JOIN dm_messages dm ON m.Z_PK = dm.msg_id
        WHERE m.ZMESSAGEDATE>{ts_start} GROUP BY dm.ZCONTACTJID HAVING h1>20 AND h2>h1*1.5 ORDER BY (h2-h1) DESC LIMIT 10
    """)

    # Biggest fan
    d['fan'] = q_whatsapp(f"""{one_on_one_cte}
        SELECT dm.ZCONTACTJID, SUM(CASE WHEN m.ZISFROMME=0 THEN 1 ELSE 0 END) t, SUM(CASE WHEN m.ZISFROMME=1 THEN 1 ELSE 0 END) y
        FROM ZWAMESSAGE m JOIN dm_messages dm ON m.Z_PK = dm.msg_id
        WHERE m.ZMESSAGEDATE>{ts_start} GROUP BY dm.ZCONTACTJID HAVING t>y*2 AND (t+y)>100 ORDER BY (t*1.0/NULLIF(y,0)) DESC LIMIT 10
    """)

    # Simp
    d['simp'] = q_whatsapp(f"""{one_on_one_cte}
        SELECT dm.ZCONTACTJID, SUM(CASE WHEN m.ZISFROMME=1 THEN 1 ELSE 0 END) y, SUM(CASE WHEN m.ZISFROMME=0 THEN 1 ELSE 0 END) t
        FROM ZWAMESSAGE m JOIN dm_messages dm ON m.Z_PK = dm.msg_id
        WHERE m.ZMESSAGEDATE>{ts_start} GROUP BY dm.ZCONTACTJID HAVING y>t*2 AND (t+y)>100 ORDER BY (y*1.0/NULLIF(t,0)) DESC LIMIT 10
    """)

    # Response time
    r = q_whatsapp(f"""
        WITH dm_sessions AS (
            SELECT Z_PK, ZCONTACTJID FROM ZWACHATSESSION WHERE ZSESSIONTYPE = 0
        ),
        dm_messages AS (
            SELECT m.Z_PK as msg_id, m.ZCHATSESSION FROM ZWAMESSAGE m
            JOIN dm_sessions s ON m.ZCHATSESSION = s.Z_PK
        ),
        g AS (
            SELECT m.ZMESSAGEDATE ts, m.ZISFROMME, m.ZCHATSESSION,
                   LAG(m.ZMESSAGEDATE) OVER (PARTITION BY m.ZCHATSESSION ORDER BY m.ZMESSAGEDATE) pt,
                   LAG(m.ZISFROMME) OVER (PARTITION BY m.ZCHATSESSION ORDER BY m.ZMESSAGEDATE) pf
            FROM ZWAMESSAGE m JOIN dm_messages dm ON m.Z_PK = dm.msg_id
            WHERE m.ZMESSAGEDATE>{ts_start}
        )
        SELECT AVG(ts-pt)/60.0 FROM g
        WHERE ZISFROMME=1 AND pf=0 AND (ts-pt)<86400 AND (ts-pt)>10
    """)
    d['resp'] = int(r[0][0] or 30)

    # Emojis
    emojis = ['😂','❤️','😭','🔥','💀','✨','🙏','👀','💯','😈']
    counts = {}
    for e in emojis:
        r = q_whatsapp(f"SELECT COUNT(*) FROM ZWAMESSAGE WHERE ZTEXT LIKE '%{e}%' AND ZMESSAGEDATE>{ts_start} AND ZISFROMME=1")
        counts[e] = r[0][0]
    d['emoji'] = counts

    # Words
    r = q_whatsapp(f"""
        SELECT COUNT(*), COALESCE(SUM(LENGTH(ZTEXT) - LENGTH(REPLACE(ZTEXT, ' ', ''))), 0)
        FROM ZWAMESSAGE WHERE ZMESSAGEDATE>{ts_start} AND ZISFROMME=1
        AND ZTEXT IS NOT NULL AND LENGTH(ZTEXT) > 0
    """)
    d['words'] = (r[0][0] or 0) + (r[0][1] or 0)

    # Busiest day
    r = q_whatsapp(f"SELECT DATE(datetime(ZMESSAGEDATE+{COCOA_OFFSET},'unixepoch','localtime')) d, COUNT(*) c FROM ZWAMESSAGE WHERE ZMESSAGEDATE>{ts_start} GROUP BY d ORDER BY c DESC LIMIT 1")
    d['busiest_day'] = (r[0][0], r[0][1]) if r else None

    # Starter %
    r = q_whatsapp(f"""
        WITH dm_sessions AS (
            SELECT Z_PK, ZCONTACTJID FROM ZWACHATSESSION WHERE ZSESSIONTYPE = 0
        ),
        dm_messages AS (
            SELECT m.Z_PK as msg_id, m.ZCHATSESSION FROM ZWAMESSAGE m
            JOIN dm_sessions s ON m.ZCHATSESSION = s.Z_PK
        ),
        convos AS (
            SELECT m.ZISFROMME, m.ZMESSAGEDATE as ts,
                   LAG(m.ZMESSAGEDATE) OVER (PARTITION BY m.ZCHATSESSION ORDER BY m.ZMESSAGEDATE) as prev_ts
            FROM ZWAMESSAGE m JOIN dm_messages dm ON m.Z_PK = dm.msg_id
            WHERE m.ZMESSAGEDATE>{ts_start}
        )
        SELECT SUM(CASE WHEN ZISFROMME=1 THEN 1 ELSE 0 END), COUNT(*)
        FROM convos WHERE prev_ts IS NULL OR (ts - prev_ts) > 14400
    """)
    d['starter_pct'] = round((r[0][0] or 0) / max(r[0][1] or 1, 1) * 100) if r and r[0][1] else 50

    # Daily counts
    daily_counts = q_whatsapp(f"""
        SELECT DATE(datetime(ZMESSAGEDATE+{COCOA_OFFSET},'unixepoch','localtime')) as d, COUNT(*) as c
        FROM ZWAMESSAGE WHERE ZMESSAGEDATE>{ts_start} GROUP BY d ORDER BY d
    """)
    d['daily_counts'] = {row[0]: row[1] for row in daily_counts}

    # Group stats
    group_chat_cte = """
        WITH group_sessions AS (
            SELECT Z_PK FROM ZWACHATSESSION WHERE ZSESSIONTYPE = 1
        ),
        group_messages AS (
            SELECT m.Z_PK as msg_id, m.ZCHATSESSION FROM ZWAMESSAGE m
            JOIN group_sessions s ON m.ZCHATSESSION = s.Z_PK
        )
    """
    r = q_whatsapp(f"""{group_chat_cte}
        SELECT
            (SELECT COUNT(DISTINCT gm.ZCHATSESSION) FROM group_messages gm
             JOIN ZWAMESSAGE m ON m.Z_PK = gm.msg_id WHERE m.ZMESSAGEDATE>{ts_start}),
            COUNT(*), SUM(CASE WHEN m.ZISFROMME=1 THEN 1 ELSE 0 END)
        FROM ZWAMESSAGE m WHERE m.ZMESSAGEDATE>{ts_start}
        AND m.Z_PK IN (SELECT msg_id FROM group_messages)
    """)
    d['group_stats'] = {'count': r[0][0] or 0, 'total': r[0][1] or 0, 'sent': r[0][2] or 0} if r else {'count': 0, 'total': 0, 'sent': 0}

    # Group leaderboard
    r = q_whatsapp(f"""
        WITH group_sessions AS (
            SELECT Z_PK, ZPARTNERNAME FROM ZWACHATSESSION WHERE ZSESSIONTYPE = 1
        )
        SELECT s.Z_PK, s.ZPARTNERNAME, COUNT(*)
        FROM ZWAMESSAGE m JOIN group_sessions s ON m.ZCHATSESSION = s.Z_PK
        WHERE m.ZMESSAGEDATE>{ts_start} GROUP BY s.Z_PK ORDER BY 3 DESC LIMIT 10
    """)
    d['group_leaderboard'] = []
    for row in r:
        chat_id, name, msg_count = row
        d['group_leaderboard'].append({'name': name or "Unnamed Group", 'msg_count': msg_count})

    return d

def merge_data(imessage_data, whatsapp_data, imessage_contacts, whatsapp_contacts, has_imessage, has_whatsapp):
    """Merge iMessage and WhatsApp data into combined stats."""
    d = {}

    # Helper to create unified contact lookup
    def get_name(handle, source='imessage'):
        if source == 'imessage':
            return get_name_imessage(handle, imessage_contacts)
        else:
            return get_name_whatsapp(handle, whatsapp_contacts)

    # Merge stats
    im_stats = imessage_data.get('stats', (0, 0, 0, 0)) if has_imessage else (0, 0, 0, 0)
    wa_stats = whatsapp_data.get('stats', (0, 0, 0, 0)) if has_whatsapp else (0, 0, 0, 0)
    d['stats'] = (
        im_stats[0] + wa_stats[0],  # total
        im_stats[1] + wa_stats[1],  # sent
        im_stats[2] + wa_stats[2],  # received
        im_stats[3] + wa_stats[3],  # unique contacts
    )
    d['imessage_stats'] = im_stats
    d['whatsapp_stats'] = wa_stats

    # Merge top contacts (with source tracking)
    top_combined = []
    if has_imessage:
        for h, t, s, r in imessage_data.get('top', []):
            name = get_name(h, 'imessage')
            top_combined.append({'name': name, 'total': t, 'sent': s, 'received': r, 'source': 'imessage', 'handle': h})
    if has_whatsapp:
        for h, t, s, r in whatsapp_data.get('top', []):
            name = get_name(h, 'whatsapp')
            top_combined.append({'name': name, 'total': t, 'sent': s, 'received': r, 'source': 'whatsapp', 'handle': h})

    # Sort by total and dedupe by name (keep higher count)
    name_counts = {}
    for entry in top_combined:
        name = entry['name']
        if name not in name_counts or entry['total'] > name_counts[name]['total']:
            name_counts[name] = entry
    d['top'] = sorted(name_counts.values(), key=lambda x: -x['total'])[:10]

    # Merge late night
    late_combined = []
    if has_imessage:
        for h, n in imessage_data.get('late', []):
            late_combined.append((get_name(h, 'imessage'), n, 'imessage'))
    if has_whatsapp:
        for h, n in whatsapp_data.get('late', []):
            late_combined.append((get_name(h, 'whatsapp'), n, 'whatsapp'))
    name_counts = {}
    for name, count, source in late_combined:
        if name not in name_counts or count > name_counts[name][1]:
            name_counts[name] = (name, count, source)
    d['late'] = sorted(name_counts.values(), key=lambda x: -x[1])[:5]

    # Use dominant platform for hour/day (whichever has more messages)
    if im_stats[0] >= wa_stats[0] and has_imessage:
        d['hour'] = imessage_data.get('hour', 12)
        d['day'] = imessage_data.get('day', '???')
    elif has_whatsapp:
        d['hour'] = whatsapp_data.get('hour', 12)
        d['day'] = whatsapp_data.get('day', '???')
    else:
        d['hour'] = 12
        d['day'] = '???'

    # Merge ghosted
    ghosted_combined = []
    if has_imessage:
        for h, b, a in imessage_data.get('ghosted', []):
            ghosted_combined.append((get_name(h, 'imessage'), b, a))
    if has_whatsapp:
        for h, b, a in whatsapp_data.get('ghosted', []):
            ghosted_combined.append((get_name(h, 'whatsapp'), b, a))
    d['ghosted'] = sorted(ghosted_combined, key=lambda x: -x[1])[:5]

    # Merge heating
    heating_combined = []
    if has_imessage:
        for h, h1, h2 in imessage_data.get('heating', []):
            heating_combined.append((get_name(h, 'imessage'), h1, h2))
    if has_whatsapp:
        for h, h1, h2 in whatsapp_data.get('heating', []):
            heating_combined.append((get_name(h, 'whatsapp'), h1, h2))
    d['heating'] = sorted(heating_combined, key=lambda x: -(x[2] - x[1]))[:5]

    # Merge fans
    fan_combined = []
    if has_imessage:
        for h, t, y in imessage_data.get('fan', []):
            fan_combined.append((get_name(h, 'imessage'), t, y))
    if has_whatsapp:
        for h, t, y in whatsapp_data.get('fan', []):
            fan_combined.append((get_name(h, 'whatsapp'), t, y))
    d['fan'] = sorted(fan_combined, key=lambda x: -(x[1] / max(x[2], 1)))[:5]

    # Merge simps
    simp_combined = []
    if has_imessage:
        for h, y, t in imessage_data.get('simp', []):
            simp_combined.append((get_name(h, 'imessage'), y, t))
    if has_whatsapp:
        for h, y, t in whatsapp_data.get('simp', []):
            simp_combined.append((get_name(h, 'whatsapp'), y, t))
    d['simp'] = sorted(simp_combined, key=lambda x: -(x[1] / max(x[2], 1)))[:5]

    # Weighted average response time
    im_resp = imessage_data.get('resp', 30) if has_imessage else 30
    wa_resp = whatsapp_data.get('resp', 30) if has_whatsapp else 30
    im_weight = im_stats[0]
    wa_weight = wa_stats[0]
    total_weight = im_weight + wa_weight
    if total_weight > 0:
        d['resp'] = int((im_resp * im_weight + wa_resp * wa_weight) / total_weight)
    else:
        d['resp'] = 30

    # Merge emoji counts
    emoji_counts = {}
    if has_imessage:
        for e, c in imessage_data.get('emoji', {}).items():
            emoji_counts[e] = emoji_counts.get(e, 0) + c
    if has_whatsapp:
        for e, c in whatsapp_data.get('emoji', {}).items():
            emoji_counts[e] = emoji_counts.get(e, 0) + c
    d['emoji'] = sorted(emoji_counts.items(), key=lambda x: -x[1])[:5]

    # Merge words
    im_words = imessage_data.get('words', 0) if has_imessage else 0
    wa_words = whatsapp_data.get('words', 0) if has_whatsapp else 0
    d['words'] = im_words + wa_words

    # Busiest day (pick the one with more messages)
    im_busiest = imessage_data.get('busiest_day') if has_imessage else None
    wa_busiest = whatsapp_data.get('busiest_day') if has_whatsapp else None
    if im_busiest and wa_busiest:
        d['busiest_day'] = im_busiest if im_busiest[1] >= wa_busiest[1] else wa_busiest
    else:
        d['busiest_day'] = im_busiest or wa_busiest

    # Weighted starter %
    im_starter = imessage_data.get('starter_pct', 50) if has_imessage else 50
    wa_starter = whatsapp_data.get('starter_pct', 50) if has_whatsapp else 50
    if total_weight > 0:
        d['starter_pct'] = int((im_starter * im_weight + wa_starter * wa_weight) / total_weight)
    else:
        d['starter_pct'] = 50

    # Merge daily counts
    daily_counts = {}
    if has_imessage:
        for date, count in imessage_data.get('daily_counts', {}).items():
            daily_counts[date] = daily_counts.get(date, 0) + count
    if has_whatsapp:
        for date, count in whatsapp_data.get('daily_counts', {}).items():
            daily_counts[date] = daily_counts.get(date, 0) + count
    d['daily_counts'] = daily_counts

    # Calculate merged daily stats
    if daily_counts:
        all_counts = list(daily_counts.values())
        d['max_daily'] = max(all_counts)
        d['active_days'] = len([c for c in all_counts if c > 0])
        d['avg_daily'] = round(sum(all_counts) / max(len(all_counts), 1))

        monthly_counts = {}
        for date_str, count in daily_counts.items():
            month_key = date_str[:7]
            monthly_counts[month_key] = monthly_counts.get(month_key, 0) + count
        if monthly_counts:
            busiest_month_key = max(monthly_counts, key=monthly_counts.get)
            d['busiest_month'] = datetime.strptime(busiest_month_key, '%Y-%m').strftime('%b')
        else:
            d['busiest_month'] = 'N/A'

        first_dt = datetime.strptime(min(daily_counts.keys()), '%Y-%m-%d').date()
        last_dt = datetime.strptime(max(daily_counts.keys()), '%Y-%m-%d').date()
        total_days = (last_dt - first_dt).days + 1
        d['quiet_days'] = total_days - d['active_days']
    else:
        d['max_daily'] = 0
        d['active_days'] = 0
        d['avg_daily'] = 0
        d['busiest_month'] = 'N/A'
        d['quiet_days'] = 0

    # Merge group stats
    im_groups = imessage_data.get('group_stats', {'count': 0, 'total': 0, 'sent': 0}) if has_imessage else {'count': 0, 'total': 0, 'sent': 0}
    wa_groups = whatsapp_data.get('group_stats', {'count': 0, 'total': 0, 'sent': 0}) if has_whatsapp else {'count': 0, 'total': 0, 'sent': 0}
    d['group_stats'] = {
        'count': im_groups['count'] + wa_groups['count'],
        'total': im_groups['total'] + wa_groups['total'],
        'sent': im_groups['sent'] + wa_groups['sent']
    }

    # Merge group leaderboard
    group_lb = []
    if has_imessage:
        for g in imessage_data.get('group_leaderboard', []):
            group_lb.append({'name': g['name'], 'msg_count': g['msg_count'], 'source': 'imessage'})
    if has_whatsapp:
        for g in whatsapp_data.get('group_leaderboard', []):
            group_lb.append({'name': g['name'], 'msg_count': g['msg_count'], 'source': 'whatsapp'})
    d['group_leaderboard'] = sorted(group_lb, key=lambda x: -x['msg_count'])[:5]

    # Personality (based on combined stats)
    s = d['stats']
    ratio = s[1] / (s[2] + 1)
    if d['hour'] < 5 or d['hour'] > 22:
        d['personality'] = ("NOCTURNAL MENACE", "terrorizes people at ungodly hours")
    elif d['resp'] < 5:
        d['personality'] = ("TERMINALLY ONLINE", "has never touched grass")
    elif d['resp'] > 120:
        d['personality'] = ("TOO COOL TO REPLY", "leaves everyone on read")
    elif ratio < 0.5:
        d['personality'] = ("POPULAR (ALLEGEDLY)", "everyone wants a piece")
    elif ratio > 2:
        d['personality'] = ("THE YAPPER", "carries every conversation alone")
    elif d['starter_pct'] > 65:
        d['personality'] = ("CONVERSATION STARTER", "always making the first move")
    elif d['starter_pct'] < 35:
        d['personality'] = ("THE WAITER", "never texts first, ever")
    else:
        d['personality'] = ("SUSPICIOUSLY NORMAL", "no notes. boring but stable.")

    return d

def gen_html(d, path, year, has_imessage, has_whatsapp):
    """Generate the combined wrapped HTML report."""
    s = d['stats']
    top = d['top']
    ptype, proast = d['personality']
    hr = d['hour']

    # Format hour
    if hr == 0:
        hr_str = "12AM"
    elif hr < 12:
        hr_str = f"{hr}AM"
    elif hr == 12:
        hr_str = "12PM"
    else:
        hr_str = f"{hr-12}PM"

    # Format busiest day
    if d['busiest_day']:
        bd = datetime.strptime(d['busiest_day'][0], '%Y-%m-%d')
        busiest_str = bd.strftime('%b %d')
        busiest_count = d['busiest_day'][1]
    else:
        busiest_str = "N/A"
        busiest_count = 0

    # Calculate days elapsed
    now = datetime.now()
    year_start = datetime(int(year), 1, 1)
    days_elapsed = max(1, (now - year_start).days)
    msgs_per_day = s[0] // days_elapsed

    words = d['words']
    words_display = f"{words // 1000:,}K" if words >= 1000 else f"{words:,}"

    # Platform breakdown
    im_stats = d.get('imessage_stats', (0, 0, 0, 0))
    wa_stats = d.get('whatsapp_stats', (0, 0, 0, 0))

    slides = []

    # Slide 1: Intro
    platforms_text = []
    if has_imessage:
        platforms_text.append("iMessage")
    if has_whatsapp:
        platforms_text.append("WhatsApp")
    platform_str = " + ".join(platforms_text)

    slides.append(f'''
    <div class="slide intro">
        <div class="slide-icon">📱💬</div>
        <h1>TEXTS<br>WRAPPED</h1>
        <p class="subtitle">{platform_str}</p>
        <p class="subtitle2">your {year} texting habits, exposed</p>
        <div class="tap-hint">click anywhere to start →</div>
    </div>''')

    # Slide 2: Total messages with platform breakdown
    slides.append(f'''
    <div class="slide">
        <div class="slide-label">// TOTAL DAMAGE</div>
        <div class="big-number gradient">{s[0]:,}</div>
        <div class="slide-text">messages across all platforms</div>
        <div class="stat-grid">
            <div class="stat-item"><span class="stat-num">{msgs_per_day}</span><span class="stat-lbl">/day</span></div>
            <div class="stat-item"><span class="stat-num">{s[1]:,}</span><span class="stat-lbl">sent</span></div>
            <div class="stat-item"><span class="stat-num">{s[2]:,}</span><span class="stat-lbl">received</span></div>
        </div>
        <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_total_messages.png', this)">📸 Save</button>
        <div class="slide-watermark">wrap2025.com</div>
    </div>''')

    # Slide 3: Platform breakdown
    if has_imessage and has_whatsapp:
        im_pct = round(im_stats[0] / max(s[0], 1) * 100)
        wa_pct = 100 - im_pct
        slides.append(f'''
        <div class="slide platform-breakdown">
            <div class="slide-label">// PLATFORM SPLIT</div>
            <div class="slide-text">where you text the most</div>
            <div class="platform-bars">
                <div class="platform-bar imessage" style="width:{max(im_pct, 15)}%">
                    <span class="platform-icon">📱</span>
                    <span class="platform-name">iMessage</span>
                    <span class="platform-pct">{im_pct}%</span>
                    <span class="platform-count">{im_stats[0]:,}</span>
                </div>
                <div class="platform-bar whatsapp" style="width:{max(wa_pct, 15)}%">
                    <span class="platform-icon">💬</span>
                    <span class="platform-name">WhatsApp</span>
                    <span class="platform-pct">{wa_pct}%</span>
                    <span class="platform-count">{wa_stats[0]:,}</span>
                </div>
            </div>
            <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_platform_split.png', this)">📸 Save</button>
            <div class="slide-watermark">wrap2025.com</div>
        </div>''')

    # Slide 4: Words sent
    pages = max(1, words // 250)
    slides.append(f'''
    <div class="slide">
        <div class="slide-label">// WORD COUNT</div>
        <div class="big-number cyan">{words_display}</div>
        <div class="slide-text">words you typed</div>
        <div class="roast">that's about {pages:,} pages of a novel</div>
        <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_word_count.png', this)">📸 Save</button>
        <div class="slide-watermark">wrap2025.com</div>
    </div>''')

    # Slide 5: Contribution Graph
    if d['daily_counts']:
        from datetime import date as ddate
        today = datetime.now().date()
        year_int = int(year)
        year_start = ddate(year_int, 1, 1)
        year_end = today if year_int == today.year else ddate(year_int, 12, 31)

        cal_cells = []
        first_day = year_start - timedelta(days=(year_start.weekday() + 1) % 7)
        last_day = year_end + timedelta(days=(5 - year_end.weekday()) % 7)

        current_date = first_day
        max_count = max(d['daily_counts'].values()) if d['daily_counts'] else 1
        month_labels = []
        last_month = None
        week_idx = 0

        while current_date <= last_day:
            week_cells = []
            for _ in range(7):
                date_str = current_date.strftime('%Y-%m-%d')
                count = d['daily_counts'].get(date_str, 0)

                if (year_start <= current_date <= year_end) and current_date.month != last_month:
                    month_labels.append((week_idx, current_date.strftime('%b')))
                    last_month = current_date.month

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

                in_year = year_start <= current_date <= year_end
                week_cells.append((date_str, count, level, in_year))
                current_date += timedelta(days=1)

            cal_cells.append(week_cells)
            week_idx += 1
            if week_idx > 60:
                break

        contrib_html = '<div class="contrib-graph">'
        contrib_html += '<div class="contrib-container">'
        contrib_html += '<div class="contrib-days"><span>Sun</span><span>Mon</span><span>Tue</span><span>Wed</span><span>Thu</span><span>Fri</span><span>Sat</span></div>'
        contrib_html += '<div class="contrib-main">'
        contrib_html += '<div class="contrib-months">'
        for week_num, month_name in month_labels:
            left_px = week_num * 12
            contrib_html += f'<span style="position:absolute;left:{left_px}px">{month_name}</span>'
        contrib_html += '</div>'
        contrib_html += '<div class="contrib-grid">'
        for week in cal_cells:
            contrib_html += '<div class="contrib-week">'
            for date_str, count, level, in_year in week:
                if in_year:
                    try:
                        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                        formatted_date = date_obj.strftime('%b %d, %Y')
                    except:
                        formatted_date = date_str
                    msg_text = "message" if count == 1 else "messages"
                    contrib_html += f'<div class="contrib-cell level-{level}" data-date="{formatted_date}" data-count="{count}" data-msg-text="{msg_text}"></div>'
                else:
                    contrib_html += '<div class="contrib-cell empty"></div>'
            contrib_html += '</div>'
        contrib_html += '</div></div></div>'
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

    # Slide 6: Your #1
    if top:
        t = top[0]
        source_icon = "📱" if t.get('source') == 'imessage' else "💬"
        slides.append(f'''
        <div class="slide gradient-bg">
            <div class="slide-label">// YOUR #1</div>
            <div class="slide-text">most texted person</div>
            <div class="huge-name">{t['name']}</div>
            <div class="big-number yellow">{t['total']:,}</div>
            <div class="slide-text">messages <span class="source-badge">{source_icon}</span></div>
            <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_your_number_one.png', this)">📸 Save</button>
            <div class="slide-watermark">wrap2025.com</div>
        </div>''')

        # Slide 7: Top 5
        top5_html = ''.join([
            f'<div class="rank-item"><span class="rank-num">{i}</span><span class="rank-name">{t["name"]}</span><span class="rank-count">{t["total"]:,}</span><span class="source-icon">{"📱" if t.get("source") == "imessage" else "💬"}</span></div>'
            for i, t in enumerate(top[:5], 1)
        ])
        slides.append(f'''
        <div class="slide">
            <div class="slide-label">// INNER CIRCLE</div>
            <div class="slide-text">your top 5 across all platforms</div>
            <div class="rank-list">{top5_html}</div>
            <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_inner_circle.png', this)">📸 Save</button>
            <div class="slide-watermark">wrap2025.com</div>
        </div>''')

    # Group chat slides
    gs = d['group_stats']
    if gs['count'] > 0:
        lurker_pct = round((1 - gs['sent'] / max(gs['total'], 1)) * 100)
        lurker_label = "LURKER" if lurker_pct > 60 else "CONTRIBUTOR" if lurker_pct < 40 else "BALANCED"
        lurker_class = "yellow" if lurker_pct > 60 else "green" if lurker_pct < 40 else "cyan"

        slides.append(f'''
        <div class="slide">
            <div class="slide-label">// GROUP CHATS</div>
            <div class="slide-icon">👥</div>
            <div class="big-number gradient">{gs['count']}</div>
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

        if d['group_leaderboard']:
            gc_html = ''.join([
                f'<div class="rank-item"><span class="rank-num">{i}</span><span class="rank-name">{gc["name"]}</span><span class="rank-count">{gc["msg_count"]:,}</span><span class="source-icon">{"📱" if gc.get("source") == "imessage" else "💬"}</span></div>'
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

    # Personality slide
    slides.append(f'''
    <div class="slide purple-bg">
        <div class="slide-label">// DIAGNOSIS</div>
        <div class="slide-text">texting personality</div>
        <div class="personality-type">{ptype}</div>
        <div class="roast">"{proast}"</div>
        <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_personality.png', this)">📸 Save</button>
        <div class="slide-watermark">wrap2025.com</div>
    </div>''')

    # Who texts first
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

    # Response time
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

    # Peak hours
    slides.append(f'''
    <div class="slide">
        <div class="slide-label">// PEAK HOURS</div>
        <div class="slide-text">most active</div>
        <div class="big-number gradient">{hr_str}</div>
        <div class="slide-text">on <span class="yellow">{d['day']}s</span></div>
        <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_peak_hours.png', this)">📸 Save</button>
        <div class="slide-watermark">wrap2025.com</div>
    </div>''')

    # 3AM Bestie
    if d['late']:
        ln = d['late'][0]
        slides.append(f'''
        <div class="slide">
            <div class="slide-label">// 3AM BESTIE</div>
            <div class="slide-icon">🌙</div>
            <div class="huge-name cyan">{ln[0]}</div>
            <div class="big-number yellow">{ln[1]}</div>
            <div class="slide-text">late night texts</div>
            <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_3am_bestie.png', this)">📸 Save</button>
            <div class="slide-watermark">wrap2025.com</div>
        </div>''')

    # Busiest Day
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

    # Biggest fan
    if d['fan']:
        f = d['fan'][0]
        ratio = round(f[1] / (f[2] + 1), 1)
        slides.append(f'''
        <div class="slide">
            <div class="slide-label">// BIGGEST FAN</div>
            <div class="slide-text">texts you most</div>
            <div class="huge-name orange">{f[0]}</div>
            <div class="slide-text"><span class="big-number yellow" style="font-size:56px">{ratio}x</span> more than you</div>
            <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_biggest_fan.png', this)">📸 Save</button>
            <div class="slide-watermark">wrap2025.com</div>
        </div>''')

    # Down bad
    if d['simp']:
        si = d['simp'][0]
        ratio = round(si[1] / (si[2] + 1), 1)
        slides.append(f'''
        <div class="slide red-bg">
            <div class="slide-label">// DOWN BAD</div>
            <div class="slide-text">you simp for</div>
            <div class="huge-name">{si[0]}</div>
            <div class="slide-text">you text <span class="big-number yellow" style="font-size:56px">{ratio}x</span> more</div>
            <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_down_bad.png', this)">📸 Save</button>
            <div class="slide-watermark">wrap2025.com</div>
        </div>''')

    # Heating Up
    if d['heating']:
        heat_html = ''.join([f'<div class="rank-item"><span class="rank-num">🔥</span><span class="rank-name">{h}</span><span class="rank-count green">+{h2-h1}</span></div>' for h, h1, h2 in d['heating'][:5]])
        slides.append(f'''
        <div class="slide orange-bg">
            <div class="slide-label">// HEATING UP</div>
            <div class="slide-text">getting stronger in H2</div>
            <div class="rank-list">{heat_html}</div>
            <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_heating_up.png', this)">📸 Save</button>
            <div class="slide-watermark">wrap2025.com</div>
        </div>''')

    # Ghosted
    if d['ghosted']:
        ghost_html = ''.join([f'<div class="rank-item"><span class="rank-num">👻</span><span class="rank-name">{h}</span><span class="rank-count"><span class="green">{b}</span> → <span class="red">{a}</span></span></div>' for h, b, a in d['ghosted'][:5]])
        slides.append(f'''
        <div class="slide">
            <div class="slide-label">// GHOSTED</div>
            <div class="slide-text">they chose peace</div>
            <div class="rank-list">{ghost_html}</div>
            <div class="roast" style="margin-top:16px;">before June → after</div>
            <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_ghosted.png', this)">📸 Save</button>
            <div class="slide-watermark">wrap2025.com</div>
        </div>''')

    # Emojis
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

    # Final slide: Summary
    top3_names = ', '.join([t['name'] for t in top[:3]]) if top else "No contacts"
    slides.append(f'''
    <div class="slide summary-slide">
        <div class="summary-card" id="summaryCard">
            <div class="summary-header">
                <span class="summary-logo">📱💬</span>
                <span class="summary-title">TEXTS WRAPPED {year}</span>
            </div>
            <div class="summary-hero">
                <div class="summary-big-stat">
                    <span class="summary-big-num">{s[0]:,}</span>
                    <span class="summary-big-label">messages</span>
                </div>
            </div>
            <div class="summary-platform-split">
                <span class="summary-platform imessage">📱 {im_stats[0]:,}</span>
                <span class="summary-platform whatsapp">💬 {wa_stats[0]:,}</span>
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

    favicon = "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🌯</text></svg>"

    html = f'''<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Texts Wrapped {year}</title>
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
    --imessage: #4ade80;
    --whatsapp: #25D366;
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

.slide.intro {{ background:linear-gradient(145deg,#12121f 0%,#1a2f1a 50%,#0f2847 100%); }}
.slide.gradient-bg {{ background:linear-gradient(145deg,#12121f 0%,#1a2f1a 50%,#0d2f2f 100%); }}
.slide.purple-bg {{ background:linear-gradient(145deg,#12121f 0%,#1f1a3d 100%); }}
.slide.orange-bg {{ background:linear-gradient(145deg,#12121f 0%,#2d1f1a 100%); }}
.slide.red-bg {{ background:linear-gradient(145deg,#12121f 0%,#2d1a1a 100%); }}
.slide.summary-slide {{ background:linear-gradient(145deg,#1a2f1a 0%,#12121f 50%,#1a1a2e 100%); }}
.slide.contrib-slide {{ background:linear-gradient(145deg,#12121f 0%,#0d1f1a 100%); padding:24px 16px 80px; }}
.slide.platform-breakdown {{ background:linear-gradient(145deg,#12121f 0%,#1a2a1a 50%,#0d2f2f 100%); }}

/* === CONTRIBUTION GRAPH STYLES === */
.contrib-graph {{ display:flex; flex-direction:column; align-items:center; margin:20px auto; padding:0 8px; }}
.contrib-container {{ display:flex; gap:4px; }}
.contrib-days {{ display:flex; flex-direction:column; gap:2px; font-size:9px; color:var(--muted); padding-top:20px; min-width:28px; text-align:right; padding-right:4px; }}
.contrib-days span {{ height:10px; line-height:10px; }}
.contrib-main {{ display:flex; flex-direction:column; }}
.contrib-months {{ position:relative; height:16px; margin-bottom:4px; font-size:10px; color:var(--muted); }}
.contrib-months span {{ position:absolute; white-space:nowrap; }}
.contrib-grid {{ display:flex; gap:2px; }}
.contrib-week {{ display:flex; flex-direction:column; gap:2px; }}
.contrib-cell {{ width:10px; height:10px; border-radius:2px; background:rgba(255,255,255,0.05); }}
.contrib-cell.empty {{ background:transparent; }}
.contrib-cell.level-0 {{ background:rgba(255,255,255,0.12); }}
.contrib-cell.level-1 {{ background:rgba(74,222,128,0.25); }}
.contrib-cell.level-2 {{ background:rgba(74,222,128,0.45); }}
.contrib-cell.level-3 {{ background:rgba(74,222,128,0.70); }}
.contrib-cell.level-4 {{ background:var(--green); }}
.contrib-cell:not(.empty) {{ cursor:pointer; position:relative; }}
.contrib-tooltip {{ position:fixed; background:rgba(20,20,30,0.95); color:var(--text); padding:8px 12px; border-radius:6px; font-size:12px; pointer-events:none; z-index:1000; white-space:nowrap; border:1px solid rgba(255,255,255,0.1); box-shadow:0 4px 12px rgba(0,0,0,0.3); }}
.contrib-tooltip .tooltip-count {{ font-family:var(--font-mono); color:var(--green); font-weight:600; }}
.contrib-tooltip .tooltip-date {{ color:var(--muted); font-size:11px; margin-top:2px; }}
.contrib-legend {{ display:flex; align-items:center; justify-content:center; gap:4px; margin-top:12px; font-size:10px; color:var(--muted); }}
.contrib-legend .contrib-cell {{ cursor:default; }}
.contrib-stats {{ display:flex; gap:32px; margin-top:24px; justify-content:center; }}
.contrib-stat {{ display:flex; flex-direction:column; align-items:center; }}
.contrib-stat-num {{ font-family:var(--font-mono); font-size:28px; font-weight:600; color:var(--green); }}
.contrib-stat-lbl {{ font-size:11px; color:var(--muted); margin-top:4px; text-transform:uppercase; letter-spacing:0.5px; }}

/* Platform breakdown slide */
.platform-bars {{ display:flex; flex-direction:column; gap:16px; width:100%; max-width:500px; margin:32px 0; }}
.platform-bar {{ display:flex; align-items:center; gap:12px; padding:20px 24px; border-radius:16px; min-width:120px; transition:all 0.3s; }}
.platform-bar.imessage {{ background:linear-gradient(90deg, rgba(74,222,128,0.25), rgba(74,222,128,0.1)); border:2px solid rgba(74,222,128,0.4); }}
.platform-bar.whatsapp {{ background:linear-gradient(90deg, rgba(37,211,102,0.25), rgba(37,211,102,0.1)); border:2px solid rgba(37,211,102,0.4); }}
.platform-icon {{ font-size:28px; flex-shrink:0; }}
.platform-name {{ font-size:16px; text-align:left; flex-shrink:0; min-width:80px; }}
.platform-pct {{ font-family:var(--font-mono); font-size:28px; font-weight:700; flex:1; text-align:center; }}
.platform-bar.imessage .platform-pct {{ color:var(--imessage); }}
.platform-bar.whatsapp .platform-pct {{ color:var(--whatsapp); }}
.platform-count {{ font-family:var(--font-mono); font-size:16px; font-weight:500; opacity:0.8; flex-shrink:0; }}
.platform-bar.imessage .platform-count {{ color:var(--imessage); }}
.platform-bar.whatsapp .platform-count {{ color:var(--whatsapp); }}

.slide h1 {{ font-family:var(--font-pixel); font-size:36px; font-weight:400; line-height:1.2; margin:20px 0; }}
.slide-label {{ font-family:var(--font-pixel); font-size:12px; font-weight:400; color:var(--green); letter-spacing:0.5px; margin-bottom:16px; }}
.slide-icon {{ font-size:80px; margin-bottom:16px; }}
.slide-text {{ font-size:18px; color:var(--muted); margin:8px 0; }}
.subtitle {{ font-size:18px; color:var(--muted); margin-top:8px; }}
.subtitle2 {{ font-size:16px; color:var(--muted); margin-top:4px; opacity:0.7; }}

.big-number {{ font-family:var(--font-mono); font-size:80px; font-weight:500; line-height:1; letter-spacing:-2px; }}
.big-number.gradient {{ background:linear-gradient(90deg, var(--imessage), var(--whatsapp)); -webkit-background-clip:text; -webkit-text-fill-color:transparent; background-clip:text; }}
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

.source-badge {{ font-size:16px; margin-left:4px; }}
.source-icon {{ font-size:14px; opacity:0.7; }}

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
.slide .subtitle2,
.slide .summary-card,
.slide .contrib-graph,
.slide .contrib-stats,
.slide .platform-bars {{
    opacity: 0;
    transform: translateY(20px);
}}

.gallery {{ transition: transform 0.55s cubic-bezier(0.22, 1, 0.36, 1); }}

.slide.active .slide-label {{ animation: textFade 0.4s ease-out forwards; }}
.slide.active .slide-text {{ animation: textFade 0.4s ease-out 0.1s forwards; }}
.slide.active .slide-icon {{ animation: iconPop 0.5s cubic-bezier(0.34, 1.56, 0.64, 1) 0.05s forwards; }}
.slide.active h1 {{ animation: titleReveal 0.5s ease-out 0.12s forwards; }}
.slide.active .subtitle {{ animation: textFade 0.4s ease-out 0.25s forwards; }}
.slide.active .subtitle2 {{ animation: textFade 0.4s ease-out 0.35s forwards; }}
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
.slide.active .rank-item:nth-child(1) {{ animation-delay: 0.1s; }}
.slide.active .rank-item:nth-child(2) {{ animation-delay: 0.18s; }}
.slide.active .rank-item:nth-child(3) {{ animation-delay: 0.26s; }}
.slide.active .rank-item:nth-child(4) {{ animation-delay: 0.34s; }}
.slide.active .rank-item:nth-child(5) {{ animation-delay: 0.42s; }}
.slide.active .emoji-row {{ animation: emojiSpread 0.6s ease-out 0.2s forwards; }}
.slide.active .summary-card {{ animation: cardRise 0.6s ease-out 0.1s forwards; }}
.slide.active .screenshot-btn {{ opacity: 0; animation: buttonSlide 0.4s ease-out 0.5s forwards; }}
.slide.active .share-hint {{ opacity: 0; animation: hintFade 0.4s ease-out 0.7s forwards; }}
.slide.active .contrib-graph {{ animation: graphReveal 0.8s ease-out 0.15s forwards; }}
.slide.active .contrib-stats {{ animation: none; opacity: 1; transform: none; }}
.slide.active .contrib-stat {{ animation: statFade 0.35s ease-out forwards; }}
.slide.active .contrib-stat:nth-child(1) {{ animation-delay: 0.5s; }}
.slide.active .contrib-stat:nth-child(2) {{ animation-delay: 0.6s; }}
.slide.active .contrib-stat:nth-child(3) {{ animation-delay: 0.7s; }}
.slide.active .platform-bars {{ animation: textFade 0.5s ease-out 0.2s forwards; }}

@keyframes textFade {{ 0% {{ opacity: 0; transform: translateY(15px); }} 100% {{ opacity: 1; transform: translateY(0); }} }}
@keyframes titleReveal {{ 0% {{ opacity: 0; transform: translateY(25px) scale(0.95); }} 70% {{ transform: translateY(-3px) scale(1.01); }} 100% {{ opacity: 1; transform: translateY(0) scale(1); }} }}
@keyframes iconPop {{ 0% {{ opacity: 0; transform: translateY(20px) scale(0.4) rotate(-15deg); }} 50% {{ transform: translateY(-8px) scale(1.15) rotate(8deg); }} 75% {{ transform: translateY(2px) scale(0.95) rotate(-3deg); }} 100% {{ opacity: 1; transform: translateY(0) scale(1) rotate(0); }} }}
@keyframes numberFlip {{ 0% {{ opacity: 0; transform: perspective(400px) rotateX(-60deg) translateY(20px); }} 60% {{ transform: perspective(400px) rotateX(10deg); }} 100% {{ opacity: 1; transform: perspective(400px) rotateX(0) translateY(0); }} }}
@keyframes nameBlur {{ 0% {{ opacity: 0; transform: translateY(20px); filter: blur(8px); }} 100% {{ opacity: 1; transform: translateY(0); filter: blur(0); }} }}
@keyframes roastType {{ 0% {{ opacity: 0; clip-path: inset(0 100% 0 0); }} 100% {{ opacity: 1; clip-path: inset(0 0 0 0); }} }}
@keyframes statFade {{ 0% {{ opacity: 0; transform: translateY(12px); }} 100% {{ opacity: 1; transform: translateY(0); }} }}
@keyframes rankSlide {{ 0% {{ opacity: 0; transform: translateX(-20px); }} 100% {{ opacity: 1; transform: translateX(0); }} }}
@keyframes badgeStamp {{ 0% {{ opacity: 0; transform: scale(1.4); }} 60% {{ transform: scale(0.95); }} 100% {{ opacity: 1; transform: scale(1); }} }}
@keyframes emojiSpread {{ 0% {{ opacity: 0; letter-spacing: 0px; }} 100% {{ opacity: 1; letter-spacing: 20px; }} }}
@keyframes cardRise {{ 0% {{ opacity: 0; transform: translateY(40px); }} 100% {{ opacity: 1; transform: translateY(0); }} }}
@keyframes graphReveal {{ 0% {{ opacity: 0; transform: translateY(30px) scale(0.95); }} 100% {{ opacity: 1; transform: translateY(0) scale(1); }} }}
@keyframes buttonSlide {{ 0% {{ opacity: 0; transform: translateY(15px); }} 100% {{ opacity: 1; transform: translateY(0); }} }}
@keyframes hintFade {{ 0% {{ opacity: 0; }} 100% {{ opacity: 1; }} }}
@keyframes glitchReveal {{ 0% {{ opacity: 0; transform: translateY(15px); filter: blur(4px); }} 50% {{ opacity: 0.8; transform: translateY(3px) skewX(-3deg); filter: blur(1px); }} 100% {{ opacity: 1; transform: translateY(0) skewX(0); filter: blur(0); }} }}

.summary-card {{
    background:linear-gradient(145deg,#1a1a2e 0%,#1a2f1a 100%);
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
.summary-big-num {{ font-family:var(--font-mono); font-size:56px; font-weight:600; background:linear-gradient(90deg, var(--imessage), var(--whatsapp)); -webkit-background-clip:text; -webkit-text-fill-color:transparent; background-clip:text; line-height:1; letter-spacing:-1px; }}
.summary-big-label {{ font-size:13px; color:var(--muted); text-transform:uppercase; letter-spacing:1px; margin-top:8px; }}
.summary-platform-split {{ display:flex; justify-content:center; gap:24px; margin:16px 0; padding:12px 0; border-top:1px solid rgba(255,255,255,0.05); border-bottom:1px solid rgba(255,255,255,0.05); }}
.summary-platform {{ font-family:var(--font-mono); font-size:14px; }}
.summary-platform.imessage {{ color:var(--imessage); }}
.summary-platform.whatsapp {{ color:var(--whatsapp); }}
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
    background:linear-gradient(90deg, var(--imessage), var(--whatsapp)); color:#000; border:none;
    padding:16px 32px; border-radius:12px; margin-top:28px;
    cursor:pointer; transition:transform 0.2s,background 0.2s;
}}
.screenshot-btn:hover {{ transform:scale(1.02); }}
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

.slide.capturing, .slide.capturing * {{
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
    slides.forEach(s => s.classList.remove('active'));
    current = idx;
    gallery.style.transform = `translateX(-${{current * 100}}vw)`;
    dots.forEach((d, i) => d.classList.toggle('active', i === current));
    prevBtn.classList.toggle('hidden', current === 0);
    nextBtn.classList.toggle('hidden', current === total - 1);
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
    // Force visibility for screenshot capture
    card.style.opacity = '1';
    card.style.transform = 'none';
    await new Promise(r => setTimeout(r, 100));
    try {{
        const canvas = await html2canvas(card, {{ backgroundColor:'#1a2f1a', scale:2, logging:false, useCORS:true }});
        const link = document.createElement('a');
        link.download = 'texts_wrapped_{year}_summary.png';
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
    const watermark = slideEl.querySelector('.slide-watermark');
    if (watermark) watermark.style.display = 'block';
    btn.style.visibility = 'hidden';
    slideEl.classList.add('capturing');
    await new Promise(r => setTimeout(r, 50));
    const computedBg = getComputedStyle(slideEl).backgroundColor;
    const bgColor = computedBg && computedBg !== 'rgba(0, 0, 0, 0)' ? computedBg : '#0a0a12';
    try {{
        const canvas = await html2canvas(slideEl, {{ backgroundColor: bgColor, scale: 2, logging: false, useCORS: true, width: slideEl.offsetWidth, height: slideEl.offsetHeight }});
        const size = Math.min(canvas.width, canvas.height);
        const squareCanvas = document.createElement('canvas');
        squareCanvas.width = size;
        squareCanvas.height = size;
        const ctx = squareCanvas.getContext('2d');
        ctx.fillStyle = bgColor;
        ctx.fillRect(0, 0, size, size);
        const srcX = (canvas.width - size) / 2;
        const srcY = (canvas.height - size) / 2;
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

    with open(path, 'w') as f:
        f.write(html)
    return path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', '-o', default='combined_wrapped_2025.html')
    parser.add_argument('--use-2024', action='store_true')
    args = parser.parse_args()

    print("\n" + "="*50)
    print("  COMBINED WRAPPED 2025 | wrap2025.com")
    print("="*50 + "\n")

    print("[*] Checking access...")
    has_imessage, has_whatsapp = check_access()

    platforms = []
    if has_imessage:
        platforms.append("iMessage")
        print(f"    ✓ iMessage: {IMESSAGE_DB}")
    if has_whatsapp:
        platforms.append("WhatsApp")
        print(f"    ✓ WhatsApp: {WHATSAPP_DB}")

    print(f"\n[*] Platforms: {' + '.join(platforms)}")

    print("[*] Loading contacts...")
    imessage_contacts = extract_imessage_contacts() if has_imessage else {}
    whatsapp_contacts = extract_whatsapp_contacts() if has_whatsapp else {}
    print(f"    ✓ {len(imessage_contacts)} from AddressBook, {len(whatsapp_contacts)} from WhatsApp")

    # Determine year
    year = "2024" if args.use_2024 else "2025"

    # Check if we have enough 2025 data
    if not args.use_2024:
        total_2025 = 0
        if has_imessage:
            r = q_imessage(f"SELECT COUNT(*) FROM message WHERE (date/1000000000+978307200)>{TS_2025_IMESSAGE}")
            total_2025 += r[0][0]
        if has_whatsapp:
            r = q_whatsapp(f"SELECT COUNT(*) FROM ZWAMESSAGE WHERE ZMESSAGEDATE>{TS_2025_WHATSAPP}")
            total_2025 += r[0][0]

        if total_2025 < 100:
            print(f"    ⚠️  Only {total_2025} msgs in 2025, using 2024")
            year = "2024"

    spinner = Spinner()

    # Analyze each platform
    imessage_data = {}
    whatsapp_data = {}

    if has_imessage:
        ts_start = TS_2024_IMESSAGE if year == "2024" else TS_2025_IMESSAGE
        ts_jun = TS_JUN_2024_IMESSAGE if year == "2024" else TS_JUN_2025_IMESSAGE
        print(f"[*] Analyzing iMessage {year}...")
        spinner.start("Reading iMessage database...")
        imessage_data = analyze_imessage(ts_start, ts_jun)
        spinner.stop(f"{imessage_data['stats'][0]:,} iMessage messages analyzed")

    if has_whatsapp:
        ts_start = TS_2024_WHATSAPP if year == "2024" else TS_2025_WHATSAPP
        ts_jun = TS_JUN_2024_WHATSAPP if year == "2024" else TS_JUN_2025_WHATSAPP
        print(f"[*] Analyzing WhatsApp {year}...")
        spinner.start("Reading WhatsApp database...")
        whatsapp_data = analyze_whatsapp(ts_start, ts_jun)
        spinner.stop(f"{whatsapp_data['stats'][0]:,} WhatsApp messages analyzed")

    print(f"[*] Merging data...")
    spinner.start("Combining platform stats...")
    merged_data = merge_data(imessage_data, whatsapp_data, imessage_contacts, whatsapp_contacts, has_imessage, has_whatsapp)
    spinner.stop(f"{merged_data['stats'][0]:,} total messages combined")

    print(f"[*] Generating report...")
    spinner.start("Building your wrapped...")
    gen_html(merged_data, args.output, year, has_imessage, has_whatsapp)
    spinner.stop(f"Saved to {args.output}")

    subprocess.run(['open', args.output])
    print("\n  Done! Click through your wrapped.\n")

if __name__ == '__main__':
    main()
