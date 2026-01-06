#!/usr/bin/env python3
"""
LOCAL BRIEF - A private, local-first daily dashboard for macOS

Displays your calendar, tasks, messages, screen time, and more - all from
local databases. No cloud services, no API keys, completely offline.

Requirements:
    - macOS 10.14+ (Mojave or later)
    - Full Disk Access permission

Quick Start:
    1. Download this file
    2. Grant Full Disk Access: System Settings → Privacy & Security → 
       Full Disk Access → enable Terminal (or your terminal app)
    3. Run: /usr/bin/python3 ~/Downloads/localbrief.py

Note: Use /usr/bin/python3 (macOS system Python) - it includes everything needed.
      Homebrew Python requires additional setup (brew install python-tk).

Keyboard Shortcuts:
    ⌘R - Refresh data
    ⌘Q - Quit

Data Sources (all local, all private):
    - Calendar.app events
    - Reminders.app tasks  
    - Messages.app (iMessage)
    - WhatsApp (if installed)
    - Screen Time data
    - Chrome history (if installed)
    - Downloads folder

License: MIT
Version: 1.0.0
"""

__version__ = "1.0.0"

import sys
import os

# ═══════════════════════════════════════════════════════════════════════════════
# PREFLIGHT CHECKS
# ═══════════════════════════════════════════════════════════════════════════════

# Check macOS
if sys.platform != "darwin":
    print("Error: Local Brief only runs on macOS")
    sys.exit(1)

# Check Python version
if sys.version_info < (3, 8):
    print(f"Error: Python 3.8+ required (you have {sys.version_info.major}.{sys.version_info.minor})")
    sys.exit(1)

# Check Tkinter
try:
    import tkinter as tk
except ImportError:
    print("Error: Tkinter not available")
    print("")
    print("Solution: Use macOS system Python instead:")
    print("  /usr/bin/python3 " + " ".join(sys.argv))
    print("")
    print("Or if using Homebrew Python:")
    print("  brew install python-tk@3.12")
    sys.exit(1)

# Standard library imports (no pip install needed)
import sqlite3
import subprocess
import tempfile
import shutil
import threading
import traceback
import re
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
from urllib.parse import urlparse

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

REFRESH_HOURS = 3
WINDOW_WIDTH = 540
WINDOW_HEIGHT = 900
MESSAGE_LOOKBACK_DAYS = 7

# ═══════════════════════════════════════════════════════════════════════════════
# THEME
# ═══════════════════════════════════════════════════════════════════════════════

BG = "#1c1c1e"
FG = "#e5e0d8"
FG_DIM = "#706b63"
FG_BRIGHT = "#f5f0e8"
FG_ACCENT = "#e8734a"
FG_TEAL = "#4a9e8f"
FG_BAR = "#5daa9a"
FG_SECTION = "#8a857d"

# ═══════════════════════════════════════════════════════════════════════════════
# PATHS
# ═══════════════════════════════════════════════════════════════════════════════

HOME = Path.home()
DOWNLOADS = HOME / "Downloads"
IMESSAGE_DB = HOME / "Library/Messages/chat.db"
WHATSAPP_DB = HOME / "Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite"
KNOWLEDGE_DB = HOME / "Library/Application Support/Knowledge/knowledgeC.db"
CALENDAR_DB = HOME / "Library/Group Containers/group.com.apple.calendar/Calendar.sqlitedb"
REMINDERS_DIR = HOME / "Library/Group Containers/group.com.apple.reminders/Container_v1/Stores"
CONTACTS_DIR = HOME / "Library/Application Support/AddressBook/Sources"
CHROME_HISTORY = HOME / "Library/Application Support/Google/Chrome/Default/History"
MAC_EPOCH = 978307200

APP_NAMES = {
    'claudefordesktop': 'Claude', 'safari': 'Safari', 'chrome': 'Chrome',
    'finder': 'Finder', 'mail': 'Mail', 'messages': 'Messages',
    'mobilesms': 'Messages', 'slack': 'Slack', 'notion': 'Notion',
    'superhuman': 'Superhuman', 'conductor': 'Conductor', 'app': 'Conductor',
    'terminal': 'Terminal', 'code': 'VS Code', 'cursor': 'Cursor',
    'whatsapp': 'WhatsApp', 'zoom': 'Zoom', 'teams': 'Teams',
    'figma': 'Figma', 'spotify': 'Spotify', 'discord': 'Discord',
    'telegram': 'Telegram', 'linear': 'Linear', 'arc': 'Arc',
}

# ═══════════════════════════════════════════════════════════════════════════════
# DATABASE HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def snapshot_db(db_path: Path, tmp_dir: Path) -> Path:
    """Copy database to temp dir to avoid locks."""
    if not db_path or not db_path.exists():
        return None
    try:
        snap = tmp_dir / db_path.name
        shutil.copy2(db_path, snap)
        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(db_path) + suffix)
            if sidecar.exists():
                shutil.copy2(sidecar, Path(str(snap) + suffix))
        return snap
    except PermissionError:
        return None
    except Exception:
        return None


def copy_chrome_history(tmp_dir: Path) -> Path:
    """Copy Chrome history via Finder (Chrome locks its db)."""
    if not CHROME_HISTORY.exists():
        return None
    dest = tmp_dir / "ChromeHistory"
    try:
        script = f'''
        tell application "Finder"
            duplicate POSIX file "{CHROME_HISTORY}" to POSIX file "{tmp_dir}" with replacing
        end tell
        '''
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
        copied = tmp_dir / "History"
        if copied.exists():
            copied.rename(dest)
            return dest
    except Exception:
        pass
    return None


def query_db(db_path, sql: str) -> list:
    """Execute read-only SQL query."""
    if not db_path or not Path(db_path).exists():
        return []
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2.0)
        conn.row_factory = sqlite3.Row
        results = conn.execute(sql).fetchall()
        conn.close()
        return results
    except Exception:
        return []

# ═══════════════════════════════════════════════════════════════════════════════
# FORMATTERS
# ═══════════════════════════════════════════════════════════════════════════════

def parse_datetime(dt_str: str) -> datetime:
    try:
        return datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None


def format_time(dt_str: str) -> str:
    """Format as ' 9:30a' or '12:30p' (6 chars, right-aligned)."""
    try:
        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
        hour = dt.hour % 12 or 12
        ampm = "a" if dt.hour < 12 else "p"
        return f"{hour:2}:{dt.minute:02}{ampm}"
    except (ValueError, TypeError):
        return "      "


def format_duration(minutes: float) -> str:
    if minutes < 60:
        return f"{int(minutes)}m"
    hours = int(minutes // 60)
    mins = int(minutes % 60)
    return f"{hours}h {mins}m" if mins else f"{hours}h"


def format_relative(dt: datetime) -> str:
    diff = datetime.now() - dt
    if diff.total_seconds() < 3600:
        return f"{int(diff.total_seconds() / 60)}m ago"
    elif diff.total_seconds() < 86400:
        return f"{int(diff.total_seconds() / 3600)}h ago"
    return f"{diff.days}d ago"


def format_time_until(dt: datetime) -> str:
    diff = dt - datetime.now()
    if diff.total_seconds() < 60:
        return "now"
    elif diff.total_seconds() < 3600:
        return f"in {int(diff.total_seconds() / 60)}m"
    hours = int(diff.total_seconds() / 3600)
    mins = int((diff.total_seconds() % 3600) / 60)
    return f"in {hours}h {mins}m" if mins else f"in {hours}h"


def get_app_name(bundle_id: str) -> str:
    if not bundle_id:
        return "Other"
    last_part = bundle_id.split('.')[-1].lower()
    return APP_NAMES.get(last_part, last_part.title())

# ═══════════════════════════════════════════════════════════════════════════════
# CONTACTS
# ═══════════════════════════════════════════════════════════════════════════════

def load_contacts(tmp_dir: Path) -> dict:
    """Load contacts from AddressBook for phone/email resolution."""
    contacts = {}
    try:
        for db_path in CONTACTS_DIR.glob("*/AddressBook-v22.abcddb"):
            snap = snapshot_db(db_path, tmp_dir)
            if not snap:
                continue
            # Phone numbers
            for row in query_db(snap, """
                SELECT TRIM(COALESCE(r.ZFIRSTNAME,'') || ' ' || COALESCE(r.ZLASTNAME,'')) as name,
                       REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(p.ZFULLNUMBER, ' ', ''), '-', ''), '(', ''), ')', ''), '+', '') as phone
                FROM ZABCDRECORD r JOIN ZABCDPHONENUMBER p ON r.Z_PK = p.ZOWNER 
                WHERE r.ZFIRSTNAME IS NOT NULL AND p.ZFULLNUMBER IS NOT NULL"""):
                if row['phone'] and len(row['phone']) >= 7:
                    contacts[row['phone'][-7:]] = row['name']
                    if len(row['phone']) >= 10:
                        contacts[row['phone'][-10:]] = row['name']
            # Emails
            for row in query_db(snap, """
                SELECT TRIM(COALESCE(r.ZFIRSTNAME,'') || ' ' || COALESCE(r.ZLASTNAME,'')) as name, 
                       LOWER(e.ZADDRESS) as email
                FROM ZABCDRECORD r JOIN ZABCDEMAILADDRESS e ON r.Z_PK = e.ZOWNER 
                WHERE r.ZFIRSTNAME IS NOT NULL AND e.ZADDRESS IS NOT NULL"""):
                if row['email']:
                    contacts[row['email']] = row['name']
    except Exception:
        pass
    return contacts


def resolve_contact(identifier: str, contacts: dict, whatsapp_name: str = None) -> str:
    """Resolve a phone/email to a contact name."""
    if not identifier:
        return None
    if whatsapp_name and whatsapp_name.strip():
        return whatsapp_name.strip()
    
    ident = str(identifier).strip()
    
    # Email
    if '@' in ident:
        key = ident.lower()
        if key in contacts:
            return contacts[key]
        username = ident.split('@')[0]
        if any(c.isalpha() for c in username):
            return username
        return None
    
    # Phone
    cleaned = re.sub(r'[^\d]', '', ident)
    if 5 <= len(cleaned) <= 6:  # Short codes
        return None
    if len(cleaned) >= 10 and cleaned[-10:-7] in ('800', '888', '877', '866', '855', '844', '833'):
        return None  # Toll-free
    if len(cleaned) >= 10 and cleaned[-10:] in contacts:
        return contacts[cleaned[-10:]]
    if len(cleaned) >= 7 and cleaned[-7:] in contacts:
        return contacts[cleaned[-7:]]
    return None

# ═══════════════════════════════════════════════════════════════════════════════
# DATA LOADER
# ═══════════════════════════════════════════════════════════════════════════════

def load_all_data(progress_cb=None) -> dict:
    """Load all data from local databases."""
    try:
        with tempfile.TemporaryDirectory(prefix="localbrief-") as td:
            tmp_dir = Path(td)
            now = datetime.now()
            today_str = now.strftime('%Y-%m-%d')
            yesterday_str = (now - timedelta(days=1)).strftime('%Y-%m-%d')
            
            # Contacts
            if progress_cb: progress_cb("contacts")
            contacts = load_contacts(tmp_dir)
            
            # Snapshot databases
            if progress_cb: progress_cb("messages")
            chat_db = snapshot_db(IMESSAGE_DB, tmp_dir)
            wa_db = snapshot_db(WHATSAPP_DB, tmp_dir) if WHATSAPP_DB.exists() else None
            
            if progress_cb: progress_cb("calendar")
            calendar_db = snapshot_db(CALENDAR_DB, tmp_dir)
            
            if progress_cb: progress_cb("screen time")
            knowledge_db = snapshot_db(KNOWLEDGE_DB, tmp_dir)
            
            if progress_cb: progress_cb("browser")
            chrome_db = copy_chrome_history(tmp_dir)
            
            # ─────────────────────────────────────────────────────────────
            # CALENDAR EVENTS
            # ─────────────────────────────────────────────────────────────
            events = []
            if calendar_db:
                for r in query_db(calendar_db, f"""
                    SELECT ci.summary, 
                           datetime(ci.start_date + {MAC_EPOCH}, 'unixepoch', 'localtime') as start,
                           datetime(ci.end_date + {MAC_EPOCH}, 'unixepoch', 'localtime') as end
                    FROM CalendarItem ci JOIN Calendar c ON ci.calendar_id = c.ROWID
                    WHERE date(datetime(ci.start_date + {MAC_EPOCH}, 'unixepoch', 'localtime')) = '{today_str}'
                    AND ci.summary IS NOT NULL
                    AND c.title NOT LIKE '%Holiday%' AND c.title NOT LIKE '%Birthday%'
                    AND c.title != 'Scheduled Reminders'
                    ORDER BY ci.start_date"""):
                    events.append({'summary': r['summary'], 'start': r['start'], 'end': r['end']})
            
            # Week calendar counts
            week_cal = {}
            if calendar_db:
                today = now.date()
                week_end = today + timedelta(days=6)
                for r in query_db(calendar_db, f"""
                    SELECT date(datetime(ci.start_date + {MAC_EPOCH}, 'unixepoch', 'localtime')) as day, 
                           COUNT(*) as count
                    FROM CalendarItem ci JOIN Calendar c ON ci.calendar_id = c.ROWID
                    WHERE date(datetime(ci.start_date + {MAC_EPOCH}, 'unixepoch', 'localtime')) 
                          BETWEEN '{today}' AND '{week_end}'
                    AND ci.summary IS NOT NULL 
                    AND c.title NOT LIKE '%Holiday%' AND c.title NOT LIKE '%Birthday%'
                    AND c.title != 'Scheduled Reminders' 
                    AND ci.summary NOT LIKE '%Busy (via Clockwise)%'
                    GROUP BY day ORDER BY day"""):
                    week_cal[r['day']] = r['count']
            
            # ─────────────────────────────────────────────────────────────
            # REMINDERS
            # ─────────────────────────────────────────────────────────────
            if progress_cb: progress_cb("tasks")
            reminders = []
            today = now.date()
            for db_path in REMINDERS_DIR.glob("Data-*.sqlite"):
                if '-shm' in str(db_path) or '-wal' in str(db_path):
                    continue
                snap = snapshot_db(db_path, tmp_dir)
                if not snap:
                    continue
                for r in query_db(snap, """
                    SELECT ZTITLE as title, ZDUEDATE as due_ts 
                    FROM ZREMCDREMINDER 
                    WHERE ZCOMPLETED = 0 AND ZTITLE IS NOT NULL AND ZDUEDATE IS NOT NULL"""):
                    due = datetime.fromtimestamp(r['due_ts'] + MAC_EPOCH).date()
                    status = 'OVERDUE' if due < today else ('TODAY' if due == today else 'FUTURE')
                    reminders.append({'title': r['title'], 'status': status})
            
            # ─────────────────────────────────────────────────────────────
            # MESSAGES
            # ─────────────────────────────────────────────────────────────
            if progress_cb: progress_cb("analyzing")
            cutoff = (now - timedelta(days=MESSAGE_LOOKBACK_DAYS)).strftime('%Y-%m-%d')
            
            imessages = []
            if chat_db:
                for r in query_db(chat_db, f"""
                    SELECT h.id as handle, m.is_from_me,
                           datetime((m.date/1000000000 + {MAC_EPOCH}), 'unixepoch', 'localtime') as ts
                    FROM message m JOIN handle h ON m.handle_id = h.ROWID
                    WHERE date(datetime((m.date/1000000000 + {MAC_EPOCH}), 'unixepoch', 'localtime')) >= '{cutoff}'
                    AND COALESCE(m.associated_message_type, 0) = 0 AND m.handle_id > 0"""):
                    imessages.append((r['handle'], r['is_from_me'], r['ts']))
            
            wa_messages = []
            if wa_db:
                for r in query_db(wa_db, f"""
                    SELECT s.ZCONTACTJID as jid, s.ZPARTNERNAME as partner_name, 
                           m.ZISFROMME as is_from_me,
                           datetime(m.ZMESSAGEDATE + {MAC_EPOCH}, 'unixepoch', 'localtime') as ts
                    FROM ZWAMESSAGE m JOIN ZWACHATSESSION s ON m.ZCHATSESSION = s.Z_PK
                    WHERE date(datetime(m.ZMESSAGEDATE + {MAC_EPOCH}, 'unixepoch', 'localtime')) >= '{cutoff}'
                    AND m.ZMESSAGETYPE = 0"""):
                    wa_messages.append((r['jid'], r['partner_name'], r['is_from_me'], r['ts']))
            
            # Analyze conversations
            convos = defaultdict(lambda: {'sent': 0, 'received': 0, 'last_inbound': None, 'last_outbound': None})
            
            for handle, is_from_me, ts in imessages:
                name = resolve_contact(handle, contacts)
                if not name:
                    continue
                c = convos[name]
                if is_from_me:
                    c['sent'] += 1
                    if not c['last_outbound'] or ts > c['last_outbound']:
                        c['last_outbound'] = ts
                else:
                    c['received'] += 1
                    if not c['last_inbound'] or ts > c['last_inbound']:
                        c['last_inbound'] = ts
            
            for jid, partner_name, is_from_me, ts in wa_messages:
                if '@g.us' in (jid or ''):  # Skip group chats
                    continue
                name = resolve_contact((jid or '').split('@')[0], contacts, partner_name)
                if not name:
                    continue
                c = convos[name]
                if is_from_me:
                    c['sent'] += 1
                    if not c['last_outbound'] or ts > c['last_outbound']:
                        c['last_outbound'] = ts
                else:
                    c['received'] += 1
                    if not c['last_inbound'] or ts > c['last_inbound']:
                        c['last_inbound'] = ts
            
            # People awaiting reply
            needs_response = []
            for name, data in convos.items():
                if data['last_inbound']:
                    if not data['last_outbound'] or data['last_inbound'] > data['last_outbound']:
                        last_dt = parse_datetime(data['last_inbound'])
                        if last_dt:
                            needs_response.append({'name': name, 'last_dt': last_dt})
            needs_response.sort(key=lambda x: x['last_dt'])
            
            # ─────────────────────────────────────────────────────────────
            # SCREEN TIME (yesterday)
            # ─────────────────────────────────────────────────────────────
            screen_time = []
            if knowledge_db:
                rows = query_db(knowledge_db, f"""
                    SELECT ZVALUESTRING as app, 
                           ROUND(SUM(ZENDDATE - ZSTARTDATE) / 60.0, 1) as minutes
                    FROM ZOBJECT WHERE ZSTREAMNAME = '/app/usage'
                    AND date(datetime(ZSTARTDATE + {MAC_EPOCH}, 'unixepoch', 'localtime')) = '{yesterday_str}'
                    AND ZVALUESTRING IS NOT NULL
                    GROUP BY ZVALUESTRING ORDER BY minutes DESC""")
                for r in rows:
                    if r['minutes'] and r['minutes'] > 0.5:
                        screen_time.append((r['app'], r['minutes']))
            
            # Focus stats
            focus = {'longest_session': 0, 'longest_app': None, 'deep_blocks': 0}
            if knowledge_db:
                rows = query_db(knowledge_db, f"""
                    SELECT ZVALUESTRING as app, 
                           ROUND((ZENDDATE - ZSTARTDATE) / 60.0, 1) as duration_min
                    FROM ZOBJECT WHERE ZSTREAMNAME = '/app/usage'
                    AND date(datetime(ZSTARTDATE + {MAC_EPOCH}, 'unixepoch', 'localtime')) = '{yesterday_str}'
                    AND ZVALUESTRING IS NOT NULL ORDER BY duration_min DESC""")
                for row in rows:
                    d = row['duration_min'] or 0
                    if d > focus['longest_session']:
                        focus['longest_session'] = d
                        focus['longest_app'] = row['app']
                    if d >= 20:
                        focus['deep_blocks'] += 1
            
            # First screen on
            first_on = None
            if knowledge_db:
                rows = query_db(knowledge_db, f"""
                    SELECT datetime(ZSTARTDATE + {MAC_EPOCH}, 'unixepoch', 'localtime') as time
                    FROM ZOBJECT WHERE ZSTREAMNAME = '/display/isBacklit'
                    AND date(datetime(ZSTARTDATE + {MAC_EPOCH}, 'unixepoch', 'localtime')) = '{yesterday_str}'
                    AND ZVALUEINTEGER = 1 ORDER BY ZSTARTDATE LIMIT 1""")
                if rows:
                    first_on = rows[0]['time']
            
            # Yesterday's conversations
            yesterday_im = [(h, f, t) for h, f, t in imessages if t.startswith(yesterday_str)]
            yesterday_wa = [(j, p, f, t) for j, p, f, t in wa_messages if t.startswith(yesterday_str)]
            yesterday_convos = defaultdict(lambda: {'sent': 0, 'received': 0})
            
            for handle, is_from_me, ts in yesterday_im:
                name = resolve_contact(handle, contacts)
                if name:
                    if is_from_me:
                        yesterday_convos[name]['sent'] += 1
                    else:
                        yesterday_convos[name]['received'] += 1
            
            for jid, partner_name, is_from_me, ts in yesterday_wa:
                if '@g.us' in (jid or ''):
                    continue
                name = resolve_contact((jid or '').split('@')[0], contacts, partner_name)
                if name:
                    if is_from_me:
                        yesterday_convos[name]['sent'] += 1
                    else:
                        yesterday_convos[name]['received'] += 1
            
            # ─────────────────────────────────────────────────────────────
            # CHROME HISTORY
            # ─────────────────────────────────────────────────────────────
            top_sites = []
            if chrome_db:
                visits = query_db(chrome_db, f"""
                    SELECT u.url FROM urls u JOIN visits v ON u.id = v.url
                    WHERE date(datetime(v.visit_time/1000000-11644473600,'unixepoch','localtime')) = '{yesterday_str}'""")
                domains = defaultdict(int)
                for row in visits:
                    try:
                        domain = urlparse(row['url']).netloc.replace('www.', '')
                        if domain and 'google.com' not in domain:
                            domains[domain] += 1
                    except Exception:
                        pass
                top_sites = sorted(domains.items(), key=lambda x: x[1], reverse=True)[:5]
            
            # ─────────────────────────────────────────────────────────────
            # UNREAD DOWNLOADS
            # ─────────────────────────────────────────────────────────────
            unread = []
            for ext in ['*.pdf', '*.docx', '*.pptx', '*.xlsx']:
                for f in DOWNLOADS.glob(ext):
                    try:
                        result = subprocess.run(
                            ["mdls", "-name", "kMDItemLastUsedDate", "-raw", str(f)],
                            capture_output=True, text=True, timeout=2
                        )
                        if result.stdout.strip() == "(null)":
                            result2 = subprocess.run(
                                ["mdls", "-name", "kMDItemDateAdded", "-raw", str(f)],
                                capture_output=True, text=True, timeout=2
                            )
                            if result2.stdout.strip() != "(null)":
                                added = datetime.strptime(result2.stdout.strip()[:19], "%Y-%m-%d %H:%M:%S")
                                unread.append({'name': f.name, 'days_old': (now - added).days})
                    except Exception:
                        pass
            unread.sort(key=lambda x: x['days_old'])
            
            return {
                'events': events,
                'week_cal': week_cal,
                'reminders': reminders,
                'needs_response': needs_response[:5],
                'screen_time': screen_time[:5],
                'screen_time_total': sum(m for _, m in screen_time),
                'focus': focus,
                'first_on': first_on,
                'yesterday_convos': dict(yesterday_convos),
                'unread': unread[:5],
                'top_sites': top_sites,
            }
            
    except Exception as e:
        traceback.print_exc()
        return {'error': str(e)}

# ═══════════════════════════════════════════════════════════════════════════════
# USER INTERFACE
# ═══════════════════════════════════════════════════════════════════════════════

class LocalBrief:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Local Brief")
        self.root.configure(bg=BG)
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        
        # Main text widget
        self.text = tk.Text(
            self.root,
            bg=BG,
            fg=FG,
            font=("Menlo", 13),
            padx=28,
            pady=24,
            wrap="none",
            cursor="arrow",
            highlightthickness=0,
            borderwidth=0,
            insertbackground=FG,
            spacing1=0,
            spacing3=2,
        )
        
        # Scrollbar
        scrollbar = tk.Scrollbar(self.root, command=self.text.yview, bg=BG, troughcolor=BG)
        self.text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        
        # Mouse wheel scrolling
        self.text.bind("<MouseWheel>", self._on_scroll)
        self.root.bind_all("<MouseWheel>", self._on_scroll)
        
        # Text tags for styling
        self.text.tag_configure("title", font=("Menlo", 20, "bold"), foreground=FG_BRIGHT)
        self.text.tag_configure("subtitle", font=("Menlo", 12), foreground=FG_DIM)
        self.text.tag_configure("section", font=("Menlo", 11), foreground=FG_SECTION)
        self.text.tag_configure("dim", foreground=FG_DIM)
        self.text.tag_configure("bright", foreground=FG_BRIGHT)
        self.text.tag_configure("accent", foreground=FG_ACCENT)
        self.text.tag_configure("teal", foreground=FG_TEAL)
        self.text.tag_configure("bar", foreground=FG_BAR)
        self.text.tag_configure("now", font=("Menlo", 13, "bold"), foreground=FG_TEAL)
        
        # Keyboard bindings
        self.text.bind("<Key>", self._on_key)
        self.root.bind("<Command-r>", lambda e: self.refresh())
        self.root.bind("<Command-R>", lambda e: self.refresh())
        self.root.bind("<Command-q>", lambda e: self.root.quit())
        self.root.bind("<Command-Q>", lambda e: self.root.quit())
        
        # State
        self.data = None
        self.loading = False
        self.load_status = ""
        
        # Initial display
        self.text.insert("1.0", "\n\nLOCAL BRIEF\n\nLoading...", "title")
        self.root.after(100, self.refresh)
    
    def _on_scroll(self, event):
        self.text.yview_scroll(-1 * (event.delta // 40), "units")
        return "break"
    
    def _on_key(self, event):
        # Allow Cmd+C for copy
        if event.keysym in ('c', 'C') and (event.state & 0x8):
            return
        # Cmd+R for refresh
        if event.keysym in ('r', 'R') and (event.state & 0x8):
            self.refresh()
            return "break"
        return "break"
    
    def refresh(self):
        if self.loading:
            return
        self.loading = True
        self.load_status = "starting"
        self._update_loading()
        threading.Thread(target=self._load_data, daemon=True).start()
    
    def _update_loading(self):
        if not self.loading:
            return
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        
        frames = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
        frame = frames[int((datetime.now().timestamp() * 10) % len(frames))]
        
        self.text.insert("end", "\n\n")
        self.text.insert("end", "LOCAL BRIEF\n\n", "title")
        self.text.insert("end", f"{frame} Loading {self.load_status}...", "dim")
        
        self.text.configure(state="disabled")
        self.root.after(80, self._update_loading)
    
    def _load_data(self):
        def progress(status):
            self.load_status = status
        try:
            self.data = load_all_data(progress)
        except Exception as e:
            traceback.print_exc()
            self.data = {'error': str(e)}
        self.loading = False
        self.root.after(0, self.render)
    
    def w(self, text: str, tag: str = None):
        """Write text with optional tag."""
        if tag:
            self.text.insert("end", text, tag)
        else:
            self.text.insert("end", text)
    
    def ln(self, n: int = 1):
        """Write newlines."""
        self.text.insert("end", "\n" * n)
    
    def bar(self, value: float, max_val: float, width: int = 14) -> str:
        """Create a progress bar string."""
        if max_val == 0:
            return "░" * width
        filled = int((value / max_val) * width)
        return "█" * filled + "░" * (width - filled)
    
    def render(self):
        """Render the dashboard."""
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        
        if not self.data:
            self.w("\n\nNo data loaded\n", "accent")
            self.text.configure(state="disabled")
            return
        
        if 'error' in self.data:
            self.w(f"\n\nError: {self.data['error']}\n", "accent")
            self.w("\nMake sure Full Disk Access is enabled:\n", "dim")
            self.w("System Settings → Privacy & Security → Full Disk Access\n", "dim")
            self.text.configure(state="disabled")
            return
        
        now = datetime.now()
        today = now.date()
        yesterday = today - timedelta(days=1)
        events = self.data.get('events', [])
        
        # ════════════════════════════════════════════════════════════════
        # HEADER
        # ════════════════════════════════════════════════════════════════
        self.ln()
        self.w(f"{now.strftime('%A, %B %d').upper()}\n", "title")
        hour = now.hour % 12 or 12
        ampm = "am" if now.hour < 12 else "pm"
        self.w(f"{hour}:{now.minute:02d} {ampm}\n", "subtitle")
        
        # ════════════════════════════════════════════════════════════════
        # NEXT UP
        # ════════════════════════════════════════════════════════════════
        current = None
        next_mtg = None
        for e in events:
            if 'Busy (via Clockwise)' in e['summary']:
                continue
            start = parse_datetime(e['start'])
            end = parse_datetime(e['end'])
            if start and end:
                if start <= now <= end:
                    current = e
                elif start > now and not next_mtg:
                    next_mtg = e
        
        if current:
            self.ln()
            end_dt = parse_datetime(current['end'])
            mins = int((end_dt - now).total_seconds() / 60)
            self.w("▶ NOW   ", "now")
            self.w(f"{current['summary'][:40]}\n", "bright")
            self.w(f"        {mins}m remaining\n", "dim")
        
        if next_mtg:
            start = parse_datetime(next_mtg['start'])
            self.ln()
            countdown = format_time_until(start)
            self.w(f"→ {countdown:<10} ", "dim")
            self.w(f"{next_mtg['summary'][:38]}\n")
        
        # ════════════════════════════════════════════════════════════════
        # SCHEDULE
        # ════════════════════════════════════════════════════════════════
        self.ln()
        self.w("SCHEDULE\n", "section")
        self.ln()
        
        if events:
            seen = set()
            for e in events:
                if 'Busy (via Clockwise)' in e['summary']:
                    continue
                key = (e['summary'], e['start'])
                if key in seen:
                    continue
                seen.add(key)
                
                start = parse_datetime(e['start'])
                end = parse_datetime(e['end'])
                time_str = format_time(e['start'])
                
                if end and end < now:
                    self.w(f"{time_str}  ", "dim")
                    self.w("✓  ", "teal")
                    self.w(f"{e['summary'][:38]}\n", "dim")
                elif start and end and start <= now <= end:
                    self.w(f"{time_str}  ", "teal")
                    self.w("▶  ", "teal")
                    self.w(f"{e['summary'][:38]}\n", "bright")
                else:
                    self.w(f"{time_str}  ", "dim")
                    self.w("·  ")
                    self.w(f"{e['summary'][:38]}\n")
        else:
            self.w("No meetings today\n", "dim")
        
        # ════════════════════════════════════════════════════════════════
        # WEEK
        # ════════════════════════════════════════════════════════════════
        week_cal = self.data.get('week_cal', {})
        if week_cal:
            self.ln()
            self.w("WEEK\n", "section")
            self.ln()
            
            today_str = today.strftime('%Y-%m-%d')
            today_count = week_cal.get(today_str, 0)
            week_vals = list(week_cal.values())
            week_avg = sum(week_vals) / max(len(week_vals), 1)
            load = "light" if today_count <= week_avg * 0.6 else ("heavy" if today_count >= week_avg * 1.4 else "typical")
            
            # Day labels
            for i in range(5):
                d = today + timedelta(days=i)
                label = d.strftime('%a')[:2]
                self.w(f"{label}    ", "dim")
            self.ln()
            
            # Counts
            for i in range(5):
                d = today + timedelta(days=i)
                d_str = d.strftime('%Y-%m-%d')
                count = week_cal.get(d_str, 0)
                if d == today:
                    self.w(f"[{count}]   ", "bright")
                else:
                    self.w(f"{count}     ", "dim")
            self.w("meetings\n")
            self.w(f"Today is {load} ({today_count} mtgs)\n", "dim")
        
        # ════════════════════════════════════════════════════════════════
        # TASKS
        # ════════════════════════════════════════════════════════════════
        overdue = [r for r in self.data.get('reminders', []) if r['status'] == 'OVERDUE']
        today_tasks = [r for r in self.data.get('reminders', []) if r['status'] == 'TODAY']
        
        if overdue or today_tasks:
            self.ln()
            self.w("TASKS\n", "section")
            self.ln()
            for t in overdue[:3]:
                self.w("●  ", "accent")
                self.w(f"{t['title'][:45]}\n", "accent")
            for t in today_tasks[:3]:
                self.w("○  ", "dim")
                self.w(f"{t['title'][:45]}\n")
        
        # ════════════════════════════════════════════════════════════════
        # AWAITING REPLY
        # ════════════════════════════════════════════════════════════════
        needs_response = self.data.get('needs_response', [])
        if needs_response:
            self.ln()
            self.w("AWAITING REPLY\n", "section")
            self.ln()
            for p in needs_response:
                age = format_relative(p['last_dt'])
                warn = (datetime.now() - p['last_dt']).days >= 3
                name = p['name'][:28].ljust(28)
                self.w(f"{name}  ")
                if warn:
                    self.w(f"{age}\n", "accent")
                else:
                    self.w(f"{age}\n", "dim")
        
        # ════════════════════════════════════════════════════════════════
        # UNREAD FILES
        # ════════════════════════════════════════════════════════════════
        unread = self.data.get('unread', [])
        if unread:
            self.ln()
            self.w("UNREAD IN DOWNLOADS\n", "section")
            self.ln()
            for f in unread[:4]:
                name = f['name'][:36]
                if len(f['name']) > 36:
                    name = name[:33] + "..."
                age = "new" if f['days_old'] == 0 else f"{f['days_old']}d"
                self.w(f"{name:<36}  ", "dim")
                if f['days_old'] > 14:
                    self.w(f"{age}\n", "accent")
                else:
                    self.w(f"{age}\n", "dim")
        
        # ════════════════════════════════════════════════════════════════
        # YESTERDAY
        # ════════════════════════════════════════════════════════════════
        self.ln(2)
        self.w(f"{yesterday.strftime('%A, %B %d').upper()}\n", "subtitle")
        
        # ════════════════════════════════════════════════════════════════
        # SCREEN TIME
        # ════════════════════════════════════════════════════════════════
        screen_time = self.data.get('screen_time', [])
        if screen_time:
            total = format_duration(self.data.get('screen_time_total', 0))
            self.ln()
            self.w("SCREEN TIME  ", "section")
            self.w(f"{total}\n")
            
            first_on = self.data.get('first_on')
            if first_on:
                self.w(f"First active {format_time(first_on).strip()}\n", "dim")
            
            self.ln()
            max_mins = screen_time[0][1] if screen_time else 1
            for app, mins in screen_time[:4]:
                name = get_app_name(app)[:12].ljust(12)
                b = self.bar(mins, max_mins)
                dur = format_duration(mins).rjust(8)
                self.w(f"{name}", "dim")
                self.w(f"{b}", "bar")
                self.w(f"{dur}\n", "dim")
        
        # ════════════════════════════════════════════════════════════════
        # TOP SITES
        # ════════════════════════════════════════════════════════════════
        top_sites = self.data.get('top_sites', [])
        if top_sites:
            self.ln()
            self.w("TOP SITES\n", "section")
            self.ln()
            for domain, count in top_sites[:4]:
                d = domain[:34].ljust(34)
                self.w(f"{d}  ", "dim")
                self.w(f"{count}\n", "dim")
        
        # ════════════════════════════════════════════════════════════════
        # FOCUS
        # ════════════════════════════════════════════════════════════════
        focus = self.data.get('focus', {})
        if focus.get('longest_session', 0) > 0:
            self.ln()
            self.w("FOCUS\n", "section")
            self.ln()
            self.w("Longest session  ", "dim")
            self.w(f"{int(focus['longest_session'])}m ")
            self.w(f"({get_app_name(focus.get('longest_app'))})\n", "dim")
            if focus.get('deep_blocks', 0) > 0:
                self.w("Deep work (20m+)  ", "dim")
                self.w(f"{focus['deep_blocks']} blocks\n")
        
        # ════════════════════════════════════════════════════════════════
        # CONVERSATIONS
        # ════════════════════════════════════════════════════════════════
        yesterday_convos = self.data.get('yesterday_convos', {})
        if yesterday_convos:
            sorted_convos = sorted(
                yesterday_convos.items(),
                key=lambda x: x[1]['sent'] + x[1]['received'],
                reverse=True
            )[:4]
            if sorted_convos:
                max_msgs = max(c['sent'] + c['received'] for _, c in sorted_convos)
                
                self.ln()
                self.w("CONVERSATIONS\n", "section")
                self.ln()
                for name, d in sorted_convos:
                    total = d['sent'] + d['received']
                    n = name[:14].ljust(14)
                    b = self.bar(total, max_msgs)
                    self.w(f"{n}", "dim")
                    self.w(f"{b}", "bar")
                    self.w(f"{total:4}\n", "dim")
        
        # ════════════════════════════════════════════════════════════════
        # FOOTER
        # ════════════════════════════════════════════════════════════════
        self.ln(2)
        self.w("⌘R refresh  ·  auto-refresh 3h\n", "dim")
        
        self.text.configure(state="disabled")
        
        # Schedule auto-refresh
        self.root.after(REFRESH_HOURS * 60 * 60 * 1000, self.refresh)
    
    def run(self):
        """Start the application."""
        self.root.mainloop()

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    """Entry point."""
    # Handle --help
    if len(sys.argv) > 1 and sys.argv[1] in ('-h', '--help'):
        print(__doc__)
        sys.exit(0)
    
    # Handle --version
    if len(sys.argv) > 1 and sys.argv[1] in ('-v', '--version'):
        print(f"Local Brief {__version__}")
        sys.exit(0)
    
    # Check Full Disk Access by testing if we can read a protected path
    test_path = HOME / "Library/Messages/chat.db"
    if test_path.exists():
        try:
            with open(test_path, 'rb') as f:
                f.read(1)
        except PermissionError:
            print("Error: Full Disk Access required")
            print("")
            print("Grant access in System Settings:")
            print("  System Settings → Privacy & Security → Full Disk Access")
            print("  → Enable for Terminal (or your terminal app)")
            print("")
            print("Then run again:")
            print(f"  /usr/bin/python3 {sys.argv[0]}")
            sys.exit(1)
    
    # Run the app
    app = LocalBrief()
    app.run()


if __name__ == "__main__":
    main()
