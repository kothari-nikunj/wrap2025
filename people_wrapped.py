#!/usr/bin/env python3
"""
People Wrapped 2025 - AI-powered analysis of your top messaging relationships.

## Quick Start

1. Download this file
2. Start Claude Code with: `claude --dangerously-skip-permissions`
3. Say: "Run python3 people_wrapped.py"
4. Wait ~10 minutes for extraction + AI summaries
5. Open people_wrapped_2025.html in your browser

That's it! No API key needed - Claude Code generates the summaries.

Note: The --dangerously-skip-permissions flag is needed because Claude Code writes
25 summary files. Without it, you'd have to approve each file write individually.

## Prerequisites

- macOS with iMessage and/or WhatsApp
- Full Disk Access for Terminal (System Settings → Privacy & Security → Full Disk Access)
- Claude Code

## How It Works

1. Script extracts your top 25 contacts from iMessage/WhatsApp databases
2. Script prints "CLAUDE CODE: Please generate summaries..."
3. Claude Code reads the message files and generates personalized summaries
4. Script builds a beautiful swipeable HTML report

The "trick" is that Claude Code itself IS the AI - no external API call needed.

---

## FOR CLAUDE CODE

When this script prints "CLAUDE CODE: Please generate summaries...", read each JSON
file in people_wrapped_data/ and write a personal, specific summary of that relationship.

The messages array contains the full year of conversation. Write something that would
make the user smile - pull out inside jokes, memorable moments, how the relationship
evolved. Be specific, quote messages when they capture something real.

Examples:

"You and Alex started 2025 with big dreams and bigger spreadsheets. The 'Moonshot
Monday' ritual you invented ('What if we just... did it?') became a running joke
that somehow turned into three actual projects."

"Mom was your steady anchor through a chaotic year. When you shared your promotion
news, her 'I knew it. I always knew it' hit different - not surprised, just proud."

"This year with Sarah was about building something real. From apartment hunting in
February ('this one has LIGHT') to the Thanksgiving trip that almost broke you both,
you came out stronger."

IMPORTANT: Do NOT use the Task tool or parallel agents. Process each contact directly.
Use /model sonnet for larger context. After all summaries: python3 people_wrapped.py build

---
"""

import sqlite3, os, sys, re, subprocess, argparse, glob, threading, time, base64, json
from datetime import datetime, timedelta
from pathlib import Path

# Database paths
IMESSAGE_DB = os.path.expanduser("~/Library/Messages/chat.db")
ADDRESSBOOK_DIR = os.path.expanduser("~/Library/Application Support/AddressBook")
WHATSAPP_PATHS = [
    os.path.expanduser("~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite"),
    os.path.expanduser("~/Library/Containers/com.whatsapp/Data/Library/Application Support/WhatsApp/ChatStorage.sqlite"),
    os.path.expanduser("~/Library/Containers/desktop.WhatsApp/Data/Library/Application Support/WhatsApp/ChatStorage.sqlite"),
]

WHATSAPP_DB = None
DATA_DIR = "people_wrapped_data"

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
            print(f"\r  {frame} {self.message}", end='', flush=True)
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
            print(f"\r  ✓ {final_message}".ljust(60))
        else:
            print()

# Cocoa offset for timestamp conversion
COCOA_OFFSET = 978307200

def extract_text_from_attributed_body(data):
    """Extract plain text from iMessage attributedBody blob."""
    if not data:
        return None
    try:
        idx = data.find(b'NSString')
        if idx != -1:
            match = re.search(b'\\x95\\x84\\x01\\+.(.*?)\\x86', data[idx:], re.DOTALL)
            if match:
                text = match.group(1)
                try:
                    return text.decode('utf-8', errors='ignore').strip()
                except:
                    pass
            match = re.search(b'\\x01\\+.(.*?)(?:\\x86|\\x00\\x00)', data[idx:], re.DOTALL)
            if match:
                text = match.group(1)
                try:
                    return text.decode('utf-8', errors='ignore').strip()
                except:
                    pass
    except:
        pass
    return None

def get_year_timestamps(year):
    """Get start/end timestamps for a year in both iMessage and WhatsApp formats."""
    year = int(year)
    start_dt = datetime(year, 1, 1)
    end_dt = datetime(year, 12, 31, 23, 59, 59)

    start_unix = int(start_dt.timestamp())
    end_unix = int(end_dt.timestamp())

    start_imessage = start_unix
    end_imessage = end_unix

    start_whatsapp = start_unix - COCOA_OFFSET
    end_whatsapp = end_unix - COCOA_OFFSET

    return {
        'start_unix': start_unix,
        'end_unix': end_unix,
        'start_imessage': start_imessage,
        'end_imessage': end_imessage,
        'start_whatsapp': start_whatsapp,
        'end_whatsapp': end_whatsapp,
    }

def normalize_phone(phone):
    if not phone: return None
    digits = re.sub(r'\D', '', str(phone))
    if len(digits) == 11 and digits.startswith('1'):
        digits = digits[1:]
    elif len(digits) > 10:
        return digits
    return digits[-10:] if len(digits) >= 10 else (digits if len(digits) >= 7 else None)

def extract_imessage_contacts():
    """Extract contacts from macOS AddressBook with their record IDs for photo matching."""
    contacts = {}
    contact_record_ids = {}
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
                        contact_record_ids[digits] = owner
                        if len(digits) >= 10:
                            contacts[digits[-10:]] = name
                            contact_record_ids[digits[-10:]] = owner
                        if len(digits) >= 7:
                            contacts[digits[-7:]] = name
                            contact_record_ids[digits[-7:]] = owner
                        if len(digits) == 11 and digits.startswith('1'):
                            contacts[digits[1:]] = name
                            contact_record_ids[digits[1:]] = owner
            for owner, email in conn.execute("SELECT ZOWNER, ZADDRESS FROM ZABCDEMAILADDRESS WHERE ZADDRESS IS NOT NULL"):
                if owner in people:
                    key = email.lower().strip()
                    contacts[key] = people[owner]
                    contact_record_ids[key] = owner
            conn.close()
        except: pass
    return contacts, contact_record_ids

def extract_whatsapp_contacts():
    """Extract contact names from WhatsApp's push names and chat session partner names."""
    contacts = {}
    if not WHATSAPP_DB:
        return contacts
    try:
        conn = sqlite3.connect(WHATSAPP_DB)
        for row in conn.execute("SELECT ZJID, ZPUSHNAME FROM ZWAPROFILEPUSHNAME WHERE ZPUSHNAME IS NOT NULL"):
            jid, name = row
            if jid and name:
                contacts[jid] = name
        for row in conn.execute("SELECT ZCONTACTJID, ZPARTNERNAME FROM ZWACHATSESSION WHERE ZSESSIONTYPE = 0 AND ZPARTNERNAME IS NOT NULL"):
            jid, name = row
            if jid and name and jid not in contacts:
                contacts[jid] = name
        conn.close()
    except:
        pass
    return contacts

def get_contact_photo(record_id):
    """Get contact photo as base64 string from AddressBook."""
    if not record_id:
        return None

    search_patterns = [
        os.path.join(ADDRESSBOOK_DIR, "Sources", "*", "Images", f"{record_id}"),
        os.path.join(ADDRESSBOOK_DIR, "Images", f"{record_id}"),
    ]

    for pattern in search_patterns:
        matches = glob.glob(pattern)
        for path in matches:
            if os.path.isfile(path):
                try:
                    with open(path, 'rb') as f:
                        data = f.read()
                        if data[:8] == b'\x89PNG\r\n\x1a\n':
                            mime = 'image/png'
                        elif data[:2] == b'\xff\xd8':
                            mime = 'image/jpeg'
                        else:
                            mime = 'image/jpeg'
                        return f"data:{mime};base64,{base64.b64encode(data).decode()}"
                except:
                    pass
    return None

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

def get_record_id_for_handle(handle, contact_record_ids):
    """Get AddressBook record ID for a handle."""
    if '@' in handle:
        lookup = handle.lower().strip()
        if lookup in contact_record_ids:
            return contact_record_ids[lookup]
        return None
    digits = re.sub(r'\D', '', str(handle))
    if digits in contact_record_ids:
        return contact_record_ids[digits]
    if len(digits) == 11 and digits.startswith('1'):
        if digits[1:] in contact_record_ids:
            return contact_record_ids[digits[1:]]
    if len(digits) >= 10 and digits[-10:] in contact_record_ids:
        return contact_record_ids[digits[-10:]]
    if len(digits) >= 7 and digits[-7:] in contact_record_ids:
        return contact_record_ids[digits[-7:]]
    return None

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
    """Check access to databases. Returns (has_imessage, has_whatsapp)."""
    global WHATSAPP_DB

    has_imessage = False
    has_whatsapp = False

    if os.path.exists(IMESSAGE_DB):
        try:
            conn = sqlite3.connect(IMESSAGE_DB)
            conn.execute("SELECT 1 FROM message LIMIT 1")
            conn.close()
            has_imessage = True
        except:
            pass

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

def count_addressbook_photos():
    """Count available contact photos."""
    count = 0
    search_patterns = [
        os.path.join(ADDRESSBOOK_DIR, "Sources", "*", "Images", "*"),
        os.path.join(ADDRESSBOOK_DIR, "Images", "*"),
    ]
    seen = set()
    for pattern in search_patterns:
        for path in glob.glob(pattern):
            if os.path.isfile(path) and path not in seen:
                seen.add(path)
                count += 1
    return count

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

def get_top_contacts_combined(timestamps, top_n, has_imessage, has_whatsapp, imessage_contacts, whatsapp_contacts, contact_record_ids):
    """Get top N contacts by message count across both platforms."""
    contacts_data = {}
    phone_to_name = {}

    ts_start_im = timestamps['start_imessage']
    ts_end_im = timestamps['end_imessage']
    ts_start_wa = timestamps['start_whatsapp']
    ts_end_wa = timestamps['end_whatsapp']

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

    if has_imessage:
        rows = q_imessage(f"""{one_on_one_cte}
            SELECT h.id, COUNT(*) t, SUM(CASE WHEN m.is_from_me=1 THEN 1 ELSE 0 END), SUM(CASE WHEN m.is_from_me=0 THEN 1 ELSE 0 END)
            FROM message m JOIN handle h ON m.handle_id=h.ROWID
            WHERE (m.date/1000000000+{COCOA_OFFSET}) BETWEEN {ts_start_im} AND {ts_end_im}
            AND m.ROWID IN (SELECT msg_id FROM one_on_one_messages)
            AND NOT (LENGTH(REPLACE(REPLACE(h.id, '+', ''), '-', '')) BETWEEN 5 AND 6 AND REPLACE(REPLACE(h.id, '+', ''), '-', '') GLOB '[0-9]*')
            GROUP BY h.id ORDER BY t DESC LIMIT 100
        """)
        for h, t, s, r in rows:
            name = get_name_imessage(h, imessage_contacts)
            record_id = get_record_id_for_handle(h, contact_record_ids)
            if name not in contacts_data:
                contacts_data[name] = {
                    'name': name,
                    'total': 0,
                    'sent': 0,
                    'received': 0,
                    'handles': {},
                    'record_id': record_id,
                }
            contacts_data[name]['total'] += t
            contacts_data[name]['sent'] += s
            contacts_data[name]['received'] += r
            contacts_data[name]['handles']['imessage'] = h
            if record_id and not contacts_data[name]['record_id']:
                contacts_data[name]['record_id'] = record_id
            normalized = normalize_phone(h)
            if normalized:
                phone_to_name[normalized] = name

    if has_whatsapp:
        wa_cte = """
            WITH dm_sessions AS (
                SELECT Z_PK, ZCONTACTJID FROM ZWACHATSESSION WHERE ZSESSIONTYPE = 0
            ),
            dm_messages AS (
                SELECT m.Z_PK as msg_id, m.ZCHATSESSION, s.ZCONTACTJID
                FROM ZWAMESSAGE m JOIN dm_sessions s ON m.ZCHATSESSION = s.Z_PK
            )
        """
        rows = q_whatsapp(f"""{wa_cte}
            SELECT dm.ZCONTACTJID, COUNT(*) t, SUM(CASE WHEN m.ZISFROMME=1 THEN 1 ELSE 0 END), SUM(CASE WHEN m.ZISFROMME=0 THEN 1 ELSE 0 END)
            FROM ZWAMESSAGE m JOIN dm_messages dm ON m.Z_PK = dm.msg_id
            WHERE m.ZMESSAGEDATE BETWEEN {ts_start_wa} AND {ts_end_wa}
            GROUP BY dm.ZCONTACTJID ORDER BY t DESC LIMIT 100
        """)
        for h, t, s, r in rows:
            wa_phone = None
            if h and '@' in h:
                wa_phone = normalize_phone(h.split('@')[0])

            merge_name = None
            if wa_phone and wa_phone in phone_to_name:
                merge_name = phone_to_name[wa_phone]

            if not merge_name and wa_phone:
                ab_name = imessage_contacts.get(wa_phone)
                if ab_name and ab_name in contacts_data:
                    merge_name = ab_name

            if merge_name and merge_name in contacts_data:
                contacts_data[merge_name]['total'] += t
                contacts_data[merge_name]['sent'] += s
                contacts_data[merge_name]['received'] += r
                contacts_data[merge_name]['handles']['whatsapp'] = h
            else:
                name = get_name_whatsapp(h, whatsapp_contacts)
                if wa_phone:
                    ab_name = imessage_contacts.get(wa_phone)
                    if ab_name:
                        name = ab_name
                if name not in contacts_data:
                    contacts_data[name] = {
                        'name': name,
                        'total': 0,
                        'sent': 0,
                        'received': 0,
                        'handles': {},
                        'record_id': get_record_id_for_handle(wa_phone, contact_record_ids) if wa_phone else None,
                    }
                contacts_data[name]['total'] += t
                contacts_data[name]['sent'] += s
                contacts_data[name]['received'] += r
                contacts_data[name]['handles']['whatsapp'] = h

    sorted_contacts = sorted(contacts_data.values(), key=lambda x: -x['total'])[:top_n]

    for contact in sorted_contacts:
        contact['photo'] = get_contact_photo(contact['record_id'])

    return sorted_contacts

def get_messages_for_contact(contact, timestamps, has_imessage, has_whatsapp):
    """Get all messages for a contact, pre-filtered for analysis."""
    messages = []

    ts_start_im = timestamps['start_imessage']
    ts_end_im = timestamps['end_imessage']
    ts_start_wa = timestamps['start_whatsapp']
    ts_end_wa = timestamps['end_whatsapp']

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

    if has_imessage and 'imessage' in contact['handles']:
        handle = contact['handles']['imessage']
        handle_escaped = handle.replace("'", "''")
        chat_query = f"""
            SELECT c.ROWID
            FROM chat c
            JOIN chat_handle_join chj ON c.ROWID = chj.chat_id
            JOIN handle h ON chj.handle_id = h.ROWID
            WHERE h.id = '{handle_escaped}'
            GROUP BY c.ROWID
            HAVING COUNT(*) = 1
        """
        rows = q_imessage(f"""
            WITH target_chats AS ({chat_query})
            SELECT m.text, m.attributedBody, m.is_from_me, (m.date/1000000000+{COCOA_OFFSET}) as ts
            FROM message m
            JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
            WHERE cmj.chat_id IN (SELECT ROWID FROM target_chats)
            AND (m.date/1000000000+{COCOA_OFFSET}) BETWEEN {ts_start_im} AND {ts_end_im}
            AND (m.text IS NOT NULL OR m.attributedBody IS NOT NULL)
            ORDER BY m.date
        """)
        for text, attributed_body, is_from_me, ts in rows:
            msg_text = text
            if not msg_text and attributed_body:
                msg_text = extract_text_from_attributed_body(attributed_body)
            if msg_text:
                messages.append({
                    'text': msg_text,
                    'from_me': bool(is_from_me),
                    'ts': ts,
                    'platform': 'imessage'
                })

    if has_whatsapp and 'whatsapp' in contact['handles']:
        jid = contact['handles']['whatsapp']
        jid_escaped = jid.replace("'", "''")
        wa_cte = f"""
            WITH dm_sessions AS (
                SELECT Z_PK FROM ZWACHATSESSION WHERE ZSESSIONTYPE = 0 AND ZCONTACTJID = '{jid_escaped}'
            )
        """
        rows = q_whatsapp(f"""{wa_cte}
            SELECT m.ZTEXT, m.ZISFROMME, (m.ZMESSAGEDATE+{COCOA_OFFSET}) as ts
            FROM ZWAMESSAGE m
            WHERE m.ZCHATSESSION IN (SELECT Z_PK FROM dm_sessions)
            AND m.ZMESSAGEDATE BETWEEN {ts_start_wa} AND {ts_end_wa}
            AND m.ZTEXT IS NOT NULL
            ORDER BY m.ZMESSAGEDATE
        """)
        for text, is_from_me, ts in rows:
            if text:
                messages.append({
                    'text': text,
                    'from_me': bool(is_from_me),
                    'ts': ts,
                    'platform': 'whatsapp'
                })

    messages.sort(key=lambda x: x['ts'])

    filtered = []
    prev_text = None
    for msg in messages:
        text = msg['text'].strip()

        if len(text) < 3:
            continue

        if text in ['￼', 'Image', 'Attachment', 'Photo', 'Video', 'Audio', 'Sticker']:
            continue

        if text.startswith(('Loved "', 'Liked "', 'Disliked "', 'Laughed at "', 'Emphasized "', 'Questioned "')):
            continue

        if re.match(r'^https?://\S+$', text):
            continue

        if text == prev_text:
            continue

        prev_text = text
        msg['text'] = text
        filtered.append(msg)

    return filtered

def generate_initials_svg(name):
    """Generate an SVG avatar with initials."""
    parts = name.split()
    if len(parts) >= 2:
        initials = parts[0][0].upper() + parts[-1][0].upper()
    elif parts:
        initials = parts[0][0].upper()
    else:
        initials = "?"

    hash_val = sum(ord(c) for c in name)
    hue = hash_val % 360

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <rect width="100" height="100" fill="hsl({hue}, 60%, 45%)"/>
  <text x="50" y="50" font-family="system-ui, -apple-system, sans-serif" font-size="40" font-weight="600" fill="white" text-anchor="middle" dominant-baseline="central">{initials}</text>
</svg>'''

    return f"data:image/svg+xml;base64,{base64.b64encode(svg.encode()).decode()}"

def generate_html(contacts_with_summaries, year, output_path):
    """Generate the swipeable HTML report."""

    slides_html = []

    for i, contact in enumerate(contacts_with_summaries):
        name = contact['name']
        photo = contact.get('photo') or generate_initials_svg(name)
        summary = contact.get('summary', 'No summary available.')
        total = contact['total']
        sent = contact['sent']
        received = contact['received']
        platforms = list(contact['handles'].keys())
        platform_icons = []
        if 'imessage' in platforms:
            platform_icons.append('iMessage')
        if 'whatsapp' in platforms:
            platform_icons.append('WhatsApp')

        summary_html = summary.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        summary_html = summary_html.replace('\n\n', '</p><p>').replace('\n', '<br>')
        summary_html = f'<p>{summary_html}</p>'

        slide = f'''
    <div class="slide person" data-index="{i}">
      <div class="slide-label">// #{i + 1} - {' + '.join(platform_icons).upper()}</div>
      <div class="slide-header">
        <div class="contact-photo">
          <img src="{photo}" alt="{name}">
        </div>
        <h2 class="contact-name">{name}</h2>
        <div class="stats-bar">
          <span class="stat"><span class="num">{total:,}</span> messages</span>
          <span class="stat"><span class="num">{sent:,}</span> sent</span>
          <span class="stat"><span class="num">{received:,}</span> received</span>
        </div>
      </div>
      <div class="summary-content">
        {summary_html}
      </div>
      <div class="slide-watermark">wrap2025.com</div>
    </div>'''
        slides_html.append(slide)

    # Favicon as base64 SVG
    favicon = "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🌯</text></svg>"

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
  <title>People Wrapped {year}</title>
  <link rel="icon" href="{favicon}">
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

    * {{
      margin: 0;
      padding: 0;
      box-sizing: border-box;
      -webkit-tap-highlight-color: transparent;
    }}

    html, body {{
      height: 100%;
      overflow: hidden;
    }}

    body {{
      font-family: var(--font-body);
      background: var(--bg);
      color: var(--text);
    }}

    .gallery {{
      display: flex;
      height: 100%;
      transition: transform 0.55s cubic-bezier(0.22, 1, 0.36, 1);
    }}

    .slide {{
      position: relative;
      min-width: 100vw;
      height: 100vh;
      display: flex;
      flex-direction: column;
      padding: 40px 30px 100px;
      background: var(--bg);
      cursor: pointer;
    }}

    .slide.intro {{
      background: linear-gradient(145deg, #12121f 0%, #1a1a2e 50%, #0f2847 100%);
      justify-content: center;
      align-items: center;
      text-align: center;
    }}

    .slide.person {{
      background: linear-gradient(145deg, #12121f 0%, #1f1a3d 100%);
    }}

    /* Intro slide */
    .slide.intro .slide-icon {{
      font-size: 80px;
      margin-bottom: 16px;
    }}

    .slide.intro h1 {{
      font-family: var(--font-pixel);
      font-size: 36px;
      font-weight: 400;
      line-height: 1.2;
      margin: 20px 0;
    }}

    .slide.intro .subtitle {{
      font-size: 18px;
      color: var(--muted);
      margin-top: 8px;
    }}

    .tap-hint {{
      position: absolute;
      bottom: 60px;
      font-size: 16px;
      color: var(--muted);
      animation: pulse 2s infinite;
    }}

    @keyframes pulse {{
      0%, 100% {{ opacity: 0.4; }}
      50% {{ opacity: 1; }}
    }}

    /* Person slides */
    .slide-label {{
      font-family: var(--font-pixel);
      font-size: 12px;
      font-weight: 400;
      color: var(--purple);
      letter-spacing: 0.5px;
      margin-bottom: 16px;
      text-align: center;
    }}

    .slide-header {{
      text-align: center;
      flex-shrink: 0;
    }}

    .contact-photo {{
      width: 100px;
      height: 100px;
      margin: 0 auto 15px;
      border-radius: 50%;
      overflow: hidden;
      border: 3px solid rgba(167, 139, 250, 0.4);
      box-shadow: 0 4px 20px rgba(167, 139, 250, 0.2);
    }}

    .contact-photo img {{
      width: 100%;
      height: 100%;
      object-fit: cover;
    }}

    .contact-name {{
      font-family: var(--font-body);
      font-size: 32px;
      font-weight: 600;
      margin-bottom: 12px;
      color: var(--text);
    }}

    .stats-bar {{
      display: flex;
      justify-content: center;
      gap: 16px;
      margin-bottom: 24px;
      flex-wrap: wrap;
    }}

    .stat {{
      font-family: var(--font-mono);
      font-size: 12px;
      color: var(--muted);
      padding: 6px 14px;
      background: rgba(255, 255, 255, 0.05);
      border-radius: 20px;
      border: 1px solid rgba(255, 255, 255, 0.1);
    }}

    .stat .num {{
      color: var(--cyan);
      font-weight: 600;
    }}

    .summary-content {{
      flex: 1;
      overflow-y: auto;
      padding: 24px;
      background: rgba(255, 255, 255, 0.03);
      border-radius: 16px;
      border: 1px solid rgba(255, 255, 255, 0.05);
      scrollbar-width: thin;
      scrollbar-color: #333 transparent;
    }}

    .summary-content::-webkit-scrollbar {{
      width: 6px;
    }}

    .summary-content::-webkit-scrollbar-track {{
      background: transparent;
    }}

    .summary-content::-webkit-scrollbar-thumb {{
      background: #333;
      border-radius: 3px;
    }}

    .summary-content p {{
      font-size: 16px;
      line-height: 1.8;
      color: var(--text);
      margin-bottom: 18px;
      opacity: 0.9;
    }}

    .summary-content p:last-child {{
      margin-bottom: 0;
    }}

    .slide-watermark {{
      position: absolute;
      bottom: 20px;
      left: 50%;
      transform: translateX(-50%);
      font-size: 11px;
      color: rgba(255, 255, 255, 0.2);
      letter-spacing: 1px;
    }}

    /* Progress bar */
    .progress-bar {{
      position: fixed;
      top: 0;
      left: 0;
      height: 3px;
      background: var(--purple);
      z-index: 200;
      transition: width 0.3s ease;
    }}

    /* Navigation dots */
    .nav-dots {{
      position: fixed;
      bottom: 40px;
      left: 50%;
      transform: translateX(-50%);
      display: flex;
      gap: 8px;
      z-index: 100;
    }}

    .nav-dot {{
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: rgba(255, 255, 255, 0.2);
      cursor: pointer;
      transition: all 0.2s;
    }}

    .nav-dot:hover {{
      background: rgba(255, 255, 255, 0.4);
    }}

    .nav-dot.active {{
      background: var(--purple);
      transform: scale(1.3);
    }}

    /* Slide animations */
    .slide .slide-label,
    .slide .contact-photo,
    .slide .contact-name,
    .slide .stats-bar,
    .slide .summary-content,
    .slide.intro .slide-icon,
    .slide.intro h1,
    .slide.intro .subtitle {{
      opacity: 0;
      transform: translateY(20px);
    }}

    .slide.active .slide-label {{ animation: fadeUp 0.4s ease-out 0.1s forwards; }}
    .slide.active .contact-photo {{ animation: fadeUp 0.4s ease-out 0.15s forwards; }}
    .slide.active .contact-name {{ animation: fadeUp 0.4s ease-out 0.2s forwards; }}
    .slide.active .stats-bar {{ animation: fadeUp 0.4s ease-out 0.25s forwards; }}
    .slide.active .summary-content {{ animation: fadeUp 0.4s ease-out 0.3s forwards; }}
    .slide.intro.active .slide-icon {{ animation: iconPop 0.5s cubic-bezier(0.34, 1.56, 0.64, 1) forwards; }}
    .slide.intro.active h1 {{ animation: fadeUp 0.5s ease-out 0.3s forwards; }}
    .slide.intro.active .subtitle {{ animation: fadeUp 0.4s ease-out 0.45s forwards; }}

    @keyframes fadeUp {{
      0% {{ opacity: 0; transform: translateY(20px); }}
      100% {{ opacity: 1; transform: translateY(0); }}
    }}

    @keyframes iconPop {{
      0% {{ opacity: 0; transform: translateY(20px) scale(0.4) rotate(-15deg); }}
      50% {{ transform: translateY(-8px) scale(1.15) rotate(8deg); }}
      75% {{ transform: translateY(2px) scale(0.95) rotate(-3deg); }}
      100% {{ opacity: 1; transform: translateY(0) scale(1) rotate(0); }}
    }}

    @media (max-width: 600px) {{
      .slide {{
        padding: 30px 20px 100px;
      }}

      .contact-photo {{
        width: 80px;
        height: 80px;
      }}

      .contact-name {{
        font-size: 26px;
      }}

      .summary-content {{
        padding: 18px;
      }}

      .summary-content p {{
        font-size: 15px;
      }}
    }}
  </style>
</head>
<body>
  <div class="progress-bar" id="progressBar"></div>
  <div class="gallery" id="gallery">
    <div class="slide intro active">
      <div class="slide-icon">👥</div>
      <h1>PEOPLE<br>WRAPPED</h1>
      <p class="subtitle">your top {len(contacts_with_summaries)} relationships of {year}</p>
      <div class="tap-hint">click anywhere to start →</div>
    </div>
    {''.join(slides_html)}
  </div>
  <div class="nav-dots" id="navDots"></div>

  <script>
    const gallery = document.getElementById('gallery');
    const slides = document.querySelectorAll('.slide');
    const progressBar = document.getElementById('progressBar');
    const navDots = document.getElementById('navDots');

    let currentIndex = 0;
    const total = slides.length;

    // Create nav dots
    for (let i = 0; i < total; i++) {{
      const dot = document.createElement('div');
      dot.className = 'nav-dot' + (i === 0 ? ' active' : '');
      dot.onclick = () => goToSlide(i);
      navDots.appendChild(dot);
    }}

    function updateSlide() {{
      gallery.style.transform = `translateX(-${{currentIndex * 100}}vw)`;
      progressBar.style.width = `${{((currentIndex + 1) / total) * 100}}%`;

      slides.forEach((s, i) => s.classList.toggle('active', i === currentIndex));
      document.querySelectorAll('.nav-dot').forEach((d, i) => d.classList.toggle('active', i === currentIndex));
    }}

    function goToSlide(index) {{
      currentIndex = Math.max(0, Math.min(index, total - 1));
      updateSlide();
    }}

    function next() {{ goToSlide(currentIndex + 1); }}
    function prev() {{ goToSlide(currentIndex - 1); }}

    // Click anywhere to advance
    gallery.onclick = (e) => {{
      const x = e.clientX / window.innerWidth;
      if (x < 0.3) prev();
      else next();
    }};

    document.addEventListener('keydown', (e) => {{
      if (e.key === 'ArrowLeft' || e.key === 'k') prev();
      if (e.key === 'ArrowRight' || e.key === 'j' || e.key === ' ') next();
    }});

    let touchStartX = 0;
    document.addEventListener('touchstart', (e) => {{ touchStartX = e.changedTouches[0].screenX; }});
    document.addEventListener('touchend', (e) => {{
      const diff = touchStartX - e.changedTouches[0].screenX;
      if (Math.abs(diff) > 50) {{ diff > 0 ? next() : prev(); }}
    }});

    updateSlide();
  </script>
</body>
</html>'''

    with open(output_path, 'w') as f:
        f.write(html)


def extract_messages(year='2025', top_n=25):
    """Phase 1: Extract messages to JSON files."""
    print()
    print("=" * 60)
    print("  PEOPLE WRAPPED 2025 - Step 1: Extracting Messages")
    print("=" * 60)
    print()

    spinner = Spinner()
    print("Checking database access...")
    has_imessage, has_whatsapp = check_access()
    print(f"  {'✓' if has_imessage else '✗'} iMessage")
    print(f"  {'✓' if has_whatsapp else '✗'} WhatsApp")

    photo_count = count_addressbook_photos()
    print(f"  ✓ AddressBook ({photo_count} contact photos)")
    print()

    spinner.start("Extracting contacts...")
    imessage_contacts, contact_record_ids = extract_imessage_contacts()
    whatsapp_contacts = extract_whatsapp_contacts()
    spinner.stop(f"Contacts: {len(imessage_contacts)} iMessage, {len(whatsapp_contacts)} WhatsApp")

    timestamps = get_year_timestamps(year)

    spinner.start("Identifying top contacts...")
    top_contacts = get_top_contacts_combined(
        timestamps, top_n,
        has_imessage, has_whatsapp,
        imessage_contacts, whatsapp_contacts, contact_record_ids
    )
    spinner.stop(f"Found {len(top_contacts)} contacts")

    print()
    print(f"Top {len(top_contacts)} contacts:")
    for i, c in enumerate(top_contacts):
        platforms = list(c['handles'].keys())
        platform_str = ', '.join(platforms)
        print(f"  {i+1:2}. {c['name'][:25]:<25} — {c['total']:,} messages ({platform_str})")

    # Create data directory
    os.makedirs(DATA_DIR, exist_ok=True)

    print()
    print("Extracting messages...")

    for i, contact in enumerate(top_contacts):
        name = contact['name']
        safe_name = re.sub(r'[^\w\s-]', '', name).strip().replace(' ', '_')

        messages = get_messages_for_contact(contact, timestamps, has_imessage, has_whatsapp)

        # Save to JSON
        data = {
            'index': i,
            'name': name,
            'total': contact['total'],
            'sent': contact['sent'],
            'received': contact['received'],
            'handles': contact['handles'],
            'photo': contact.get('photo'),
            'record_id': contact.get('record_id'),
            'messages': messages,
            'year': year,
        }

        json_path = os.path.join(DATA_DIR, f"{i+1:02d}_{safe_name}.json")
        with open(json_path, 'w') as f:
            json.dump(data, f, indent=2)

        print(f"  [{i+1}/{len(top_contacts)}] {name}: {len(messages)} messages")

    print()
    print(f"✓ Messages extracted to {DATA_DIR}/")
    return True


def get_contacts_needing_summaries():
    """Get list of contacts that don't have summaries yet."""
    if not os.path.exists(DATA_DIR):
        return []

    json_files = sorted(glob.glob(os.path.join(DATA_DIR, "*.json")))
    needs_summary = []

    for json_path in json_files:
        with open(json_path) as f:
            data = json.load(f)
        if not data.get('summary'):
            needs_summary.append({
                'path': json_path,
                'name': data['name'],
                'total': data['total'],
                'message_count': len(data.get('messages', []))
            })

    return needs_summary


def build_html(year='2025'):
    """Phase 3: Build HTML from JSON files with summaries."""
    output_path = f'people_wrapped_{year}.html'

    if not os.path.exists(DATA_DIR):
        print(f"Error: {DATA_DIR}/ not found.")
        return False

    json_files = sorted(glob.glob(os.path.join(DATA_DIR, "*.json")))
    if not json_files:
        print(f"Error: No JSON files found in {DATA_DIR}/")
        return False

    print()
    print("=" * 60)
    print("  PEOPLE WRAPPED 2025 - Step 3: Building HTML")
    print("=" * 60)
    print()

    contacts = []
    for json_path in json_files:
        with open(json_path) as f:
            data = json.load(f)
        contacts.append(data)
        has_summary = 'summary' in data and data['summary']
        status = "✓" if has_summary else "✗"
        print(f"  {status} {data['name']}")

    spinner = Spinner()
    spinner.start("Generating HTML...")
    generate_html(contacts, year, output_path)
    spinner.stop(f"Saved to {output_path}")

    print()
    print(f"✓ Done! Open {output_path} in your browser.")
    return True


def print_summary_instructions():
    """Print instructions for Claude Code to generate summaries."""
    needs_summary = get_contacts_needing_summaries()

    print()
    print("=" * 60)
    print("  PEOPLE WRAPPED 2025 - Step 2: Generate Summaries")
    print("=" * 60)
    print()
    print(f"  {len(needs_summary)} contacts need summaries:")
    for c in needs_summary:
        print(f"    - {c['name']} ({c['message_count']:,} messages)")
    print()
    print("=" * 60)
    print()
    print("  CLAUDE CODE: Please generate summaries for the contacts above.")
    print()
    print("  Read each JSON file in people_wrapped_data/ and write a personal,")
    print("  specific summary. Pull out inside jokes, memorable moments, how")
    print("  the relationship evolved. Be specific, quote when it captures")
    print("  something real.")
    print()
    print("  IMPORTANT: Do NOT use Task tool or parallel agents.")
    print("  Use /model sonnet for larger context window.")
    print()
    print("  When done: python3 people_wrapped.py build")
    print()


def main():
    """Main entry point - handles the full workflow."""
    parser = argparse.ArgumentParser(
        description='People Wrapped 2025 - AI-powered messaging relationship analysis',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
How it works:
  1. Run: python3 people_wrapped.py
  2. Script extracts your top 25 contacts from iMessage/WhatsApp
  3. Claude Code generates personalized summaries (no API key needed)
  4. Script builds a beautiful swipeable HTML report

Commands:
  python3 people_wrapped.py           Full workflow (extract → summarize → build)
  python3 people_wrapped.py extract   Just extract messages
  python3 people_wrapped.py summarize Show summary generation instructions
  python3 people_wrapped.py build     Just build HTML from existing data
  python3 people_wrapped.py status    Check progress

Options:
  --top N    Number of contacts to analyze (default: 25)
"""
    )
    parser.add_argument('command', nargs='?', default='run',
                       choices=['run', 'extract', 'summarize', 'build', 'status'],
                       help='Command to run')
    parser.add_argument('--year', default='2025', help='Year to analyze')
    parser.add_argument('--top', type=int, default=25, help='Number of top contacts (default: 25)')

    args = parser.parse_args()

    if args.command == 'extract':
        extract_messages(args.year, args.top)
    elif args.command == 'summarize':
        print_summary_instructions()
    elif args.command == 'build':
        build_html(args.year)
    elif args.command == 'status':
        needs = get_contacts_needing_summaries()
        total = len(glob.glob(os.path.join(DATA_DIR, "*.json"))) if os.path.exists(DATA_DIR) else 0
        complete = total - len(needs)
        print(f"\nProgress: {complete}/{total} summaries complete\n")
        if needs:
            print("Pending:")
            for c in needs:
                print(f"  - {c['name']}")
    elif args.command == 'run':
        # Full workflow
        print()
        print("╔════════════════════════════════════════════════════════════╗")
        print("║              PEOPLE WRAPPED 2025                           ║")
        print("║      AI-powered analysis of your top relationships         ║")
        print("╚════════════════════════════════════════════════════════════╝")

        # Step 1: Check if extraction needed
        if not os.path.exists(DATA_DIR) or not glob.glob(os.path.join(DATA_DIR, "*.json")):
            extract_messages(args.year, args.top)
        else:
            print()
            print("✓ Messages already extracted. Skipping Step 1.")

        # Step 2: Check if summaries needed
        needs_summary = get_contacts_needing_summaries()
        if needs_summary:
            print_summary_instructions()
            # Don't exit - Claude Code will see this and generate summaries
            return
        else:
            print()
            print("✓ All summaries complete. Proceeding to Step 3.")

        # Step 3: Build HTML
        build_html(args.year)


if __name__ == '__main__':
    main()
