#!/usr/bin/env python3
"""
iMessage Wrapped 2025 - Your texting habits, exposed.
Usage: python3 imessage_wrapped.py
"""

import sqlite3, os, sys, re, subprocess, argparse, glob
from datetime import datetime

IMESSAGE_DB = os.path.expanduser("~/Library/Messages/chat.db")
ADDRESSBOOK_DIR = os.path.expanduser("~/Library/Application Support/AddressBook")

TS_2025 = 1735689600
TS_JUN_2025 = 1748736000
TS_2024 = 1704067200
TS_JUN_2024 = 1717200000

def normalize_phone(phone):
    if not phone: return None
    digits = re.sub(r'\D', '', str(phone))
    if len(digits) == 11 and digits.startswith('1'): digits = digits[1:]
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
                    norm = normalize_phone(phone)
                    if norm: contacts[norm] = people[owner]
            for owner, email in conn.execute("SELECT ZOWNER, ZADDRESS FROM ZABCDEMAILADDRESS WHERE ZADDRESS IS NOT NULL"):
                if owner in people: contacts[email.lower().strip()] = people[owner]
            conn.close()
        except: pass
    return contacts

def get_name(handle, contacts):
    lookup = handle.lower().strip() if '@' in handle else normalize_phone(handle)
    if lookup and lookup in contacts: return contacts[lookup]
    return handle.split('@')[0] if '@' in handle else handle

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
    d['stats'] = q(f"SELECT COUNT(*), SUM(CASE WHEN is_from_me=1 THEN 1 ELSE 0 END), SUM(CASE WHEN is_from_me=0 THEN 1 ELSE 0 END), COUNT(DISTINCT handle_id) FROM message WHERE (date/1000000000+978307200)>{ts_start}")[0]
    d['top'] = q(f"SELECT h.id, COUNT(*) t, SUM(CASE WHEN m.is_from_me=1 THEN 1 ELSE 0 END), SUM(CASE WHEN m.is_from_me=0 THEN 1 ELSE 0 END) FROM message m JOIN handle h ON m.handle_id=h.ROWID WHERE (m.date/1000000000+978307200)>{ts_start} GROUP BY h.id ORDER BY t DESC LIMIT 20")
    d['late'] = q(f"SELECT h.id, COUNT(*) n FROM message m JOIN handle h ON m.handle_id=h.ROWID WHERE (m.date/1000000000+978307200)>{ts_start} AND CAST(strftime('%H',datetime((m.date/1000000000+978307200),'unixepoch','localtime')) AS INT)<5 GROUP BY h.id HAVING n>5 ORDER BY n DESC LIMIT 5")
    
    r = q(f"SELECT CAST(strftime('%H',datetime((date/1000000000+978307200),'unixepoch','localtime')) AS INT) h, COUNT(*) c FROM message WHERE (date/1000000000+978307200)>{ts_start} GROUP BY h ORDER BY c DESC LIMIT 1")
    d['hour'] = r[0][0] if r else 12
    days = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday']
    r = q(f"SELECT CAST(strftime('%w',datetime((date/1000000000+978307200),'unixepoch','localtime')) AS INT) d, COUNT(*) FROM message WHERE (date/1000000000+978307200)>{ts_start} GROUP BY d ORDER BY 2 DESC LIMIT 1")
    d['day'] = days[r[0][0]] if r else '???'
    
    d['ghosted'] = q(f"SELECT h.id, SUM(CASE WHEN m.is_from_me=0 AND (m.date/1000000000+978307200)<{ts_jun} THEN 1 ELSE 0 END) b, SUM(CASE WHEN m.is_from_me=0 AND (m.date/1000000000+978307200)>={ts_jun} THEN 1 ELSE 0 END) a FROM message m JOIN handle h ON m.handle_id=h.ROWID WHERE (m.date/1000000000+978307200)>{ts_start-31536000} GROUP BY h.id HAVING b>10 AND a<3 ORDER BY b DESC LIMIT 5")
    d['heating'] = q(f"SELECT h.id, SUM(CASE WHEN (m.date/1000000000+978307200)<{ts_jun} THEN 1 ELSE 0 END) h1, SUM(CASE WHEN (m.date/1000000000+978307200)>={ts_jun} THEN 1 ELSE 0 END) h2 FROM message m JOIN handle h ON m.handle_id=h.ROWID WHERE (m.date/1000000000+978307200)>{ts_start} GROUP BY h.id HAVING h1>20 AND h2>h1*1.5 ORDER BY (h2-h1) DESC LIMIT 5")
    d['fan'] = q(f"SELECT h.id, SUM(CASE WHEN m.is_from_me=0 THEN 1 ELSE 0 END) t, SUM(CASE WHEN m.is_from_me=1 THEN 1 ELSE 0 END) y FROM message m JOIN handle h ON m.handle_id=h.ROWID WHERE (m.date/1000000000+978307200)>{ts_start} GROUP BY h.id HAVING t>y*2 AND (t+y)>100 ORDER BY (t*1.0/NULLIF(y,0)) DESC LIMIT 5")
    d['simp'] = q(f"SELECT h.id, SUM(CASE WHEN m.is_from_me=1 THEN 1 ELSE 0 END) y, SUM(CASE WHEN m.is_from_me=0 THEN 1 ELSE 0 END) t FROM message m JOIN handle h ON m.handle_id=h.ROWID WHERE (m.date/1000000000+978307200)>{ts_start} GROUP BY h.id HAVING y>t*2 AND (t+y)>100 ORDER BY (y*1.0/NULLIF(t,0)) DESC LIMIT 5")
    
    r = q(f"WITH g AS (SELECT (date/1000000000+978307200) ts, is_from_me, LAG(date/1000000000+978307200) OVER (ORDER BY date) pt, LAG(is_from_me) OVER (ORDER BY date) pf FROM message WHERE (date/1000000000+978307200)>{ts_start}) SELECT AVG(ts-pt)/60.0 FROM g WHERE is_from_me=1 AND pf=0 AND (ts-pt)<86400 AND (ts-pt)>10")
    d['resp'] = int(r[0][0] or 30)
    
    emojis = ['😂','❤️','😭','🔥','💀','✨','🙏','👀','💯','😈']
    counts = {}
    for e in emojis:
        r = q(f"SELECT COUNT(*) FROM message WHERE text LIKE '%{e}%' AND (date/1000000000+978307200)>{ts_start} AND is_from_me=1")
        counts[e] = r[0][0]
    d['emoji'] = sorted(counts.items(), key=lambda x:-x[1])[:5]
    
    # NEW: Total words sent
    r = q(f"SELECT SUM(LENGTH(text) - LENGTH(REPLACE(text, ' ', '')) + 1) FROM message WHERE (date/1000000000+978307200)>{ts_start} AND is_from_me=1 AND text IS NOT NULL AND text != ''")
    d['words'] = r[0][0] or 0
    
    # NEW: Busiest day
    r = q(f"SELECT DATE(datetime((date/1000000000+978307200),'unixepoch','localtime')) d, COUNT(*) c FROM message WHERE (date/1000000000+978307200)>{ts_start} GROUP BY d ORDER BY c DESC LIMIT 1")
    if r:
        d['busiest_day'] = (r[0][0], r[0][1])  # ('2025-03-15', 523)
    else:
        d['busiest_day'] = None
    
    # NEW: Conversation starter % (who texts first after 4+ hour gap)
    r = q(f"""
        WITH convos AS (
            SELECT is_from_me, 
                   (date/1000000000+978307200) as ts,
                   LAG(date/1000000000+978307200) OVER (PARTITION BY handle_id ORDER BY date) as prev_ts
            FROM message 
            WHERE (date/1000000000+978307200)>{ts_start}
        )
        SELECT 
            SUM(CASE WHEN is_from_me=1 THEN 1 ELSE 0 END) as you_started,
            COUNT(*) as total
        FROM convos 
        WHERE prev_ts IS NULL OR (ts - prev_ts) > 14400
    """)
    if r and r[0][1] > 0:
        d['starter_pct'] = round((r[0][0] / r[0][1]) * 100)
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
    return d

def gen_html(d, contacts, path):
    s = d['stats']
    top = d['top']
    n = lambda h: get_name(h, contacts)
    ptype, proast = d['personality']
    hr = d['hour']
    hr_str = f"{hr}AM" if hr < 12 else f"{hr-12 if hr > 12 else 12}PM"
    
    # Format busiest day
    if d['busiest_day']:
        from datetime import datetime as dt
        bd = dt.strptime(d['busiest_day'][0], '%Y-%m-%d')
        busiest_str = bd.strftime('%b %d')
        busiest_count = d['busiest_day'][1]
    else:
        busiest_str = "N/A"
        busiest_count = 0
    
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
            <div class="stat-item"><span class="stat-num">{s[0]//365}</span><span class="stat-lbl">/day</span></div>
            <div class="stat-item"><span class="stat-num">{s[1]:,}</span><span class="stat-lbl">sent</span></div>
            <div class="stat-item"><span class="stat-num">{s[2]:,}</span><span class="stat-lbl">received</span></div>
        </div>
    </div>''')
    
    # Slide 3: Words sent
    words_k = d['words'] // 1000
    slides.append(f'''
    <div class="slide">
        <div class="slide-label">// WORD COUNT</div>
        <div class="big-number cyan">{words_k:,}K</div>
        <div class="slide-text">words you typed</div>
        <div class="roast">that's about {d['words']//250:,} pages of a novel</div>
    </div>''')
    
    # Slide 4: Your #1
    slides.append(f'''
    <div class="slide pink-bg">
        <div class="slide-label">// YOUR #1</div>
        <div class="slide-text">most texted person</div>
        <div class="huge-name">{n(top[0][0])}</div>
        <div class="big-number yellow">{top[0][1]:,}</div>
        <div class="slide-text">messages</div>
    </div>''')
    
    # Slide 5: Top 5
    top5_html = ''.join([f'<div class="rank-item"><span class="rank-num">{i}</span><span class="rank-name">{n(h)}</span><span class="rank-count">{t:,}</span></div>' for i,(h,t,_,_) in enumerate(top[:5],1)])
    slides.append(f'''
    <div class="slide">
        <div class="slide-label">// INNER CIRCLE</div>
        <div class="slide-text">your top 5</div>
        <div class="rank-list">{top5_html}</div>
    </div>''')
    
    # Slide 6: Personality
    slides.append(f'''
    <div class="slide purple-bg">
        <div class="slide-label">// DIAGNOSIS</div>
        <div class="slide-text">texting personality</div>
        <div class="personality-type">{ptype}</div>
        <div class="roast">"{proast}"</div>
    </div>''')
    
    # Slide 7: Conversation Starter
    starter_label = "YOU START" if d['starter_pct'] > 50 else "THEY START"
    starter_class = "green" if d['starter_pct'] > 50 else "yellow"
    slides.append(f'''
    <div class="slide">
        <div class="slide-label">// WHO TEXTS FIRST</div>
        <div class="slide-text">conversation initiator</div>
        <div class="big-number {starter_class}">{d['starter_pct']}<span class="pct">%</span></div>
        <div class="slide-text">of convos started by you</div>
        <div class="badge {starter_class}">{starter_label}</div>
    </div>''')
    
    # Slide 8: Busiest Day
    if d['busiest_day']:
        slides.append(f'''
        <div class="slide">
            <div class="slide-label">// BUSIEST DAY</div>
            <div class="slide-text">your most unhinged day</div>
            <div class="big-number orange">{busiest_str}</div>
            <div class="slide-text"><span class="yellow">{busiest_count:,}</span> messages in one day</div>
            <div class="roast">what happened??</div>
        </div>''')
    
    # Slide 9: 3AM Bestie
    if d['late']:
        ln = d['late'][0]
        slides.append(f'''
        <div class="slide">
            <div class="slide-label">// 3AM BESTIE</div>
            <div class="slide-icon">🌙</div>
            <div class="huge-name cyan">{n(ln[0])}</div>
            <div class="big-number yellow">{ln[1]}</div>
            <div class="slide-text">late night texts</div>
        </div>''')
    
    # Slide 10: Peak hours
    slides.append(f'''
    <div class="slide">
        <div class="slide-label">// PEAK HOURS</div>
        <div class="slide-text">most active</div>
        <div class="big-number green">{hr_str}</div>
        <div class="slide-text">on <span class="yellow">{d['day']}s</span></div>
    </div>''')
    
    # Slide 11: Heating Up
    if d['heating']:
        heat_html = ''.join([f'<div class="rank-item"><span class="rank-num">🔥</span><span class="rank-name">{n(h)}</span><span class="rank-count green">+{h2-h1}</span></div>' for h,h1,h2 in d['heating'][:5]])
        slides.append(f'''
        <div class="slide orange-bg">
            <div class="slide-label">// HEATING UP</div>
            <div class="slide-text">getting stronger in H2</div>
            <div class="rank-list">{heat_html}</div>
        </div>''')
    
    # Slide 12: Biggest fan
    if d['fan']:
        f = d['fan'][0]
        ratio = round(f[1]/(f[2]+1), 1)
        slides.append(f'''
        <div class="slide">
            <div class="slide-label">// BIGGEST FAN</div>
            <div class="slide-text">texts you most</div>
            <div class="huge-name orange">{n(f[0])}</div>
            <div class="slide-text"><span class="big-number yellow" style="font-size:56px">{ratio}x</span> more than you</div>
        </div>''')
    
    # Slide 13: Down bad
    if d['simp']:
        si = d['simp'][0]
        ratio = round(si[1]/(si[2]+1), 1)
        slides.append(f'''
        <div class="slide red-bg">
            <div class="slide-label">// DOWN BAD</div>
            <div class="slide-text">you simp for</div>
            <div class="huge-name">{n(si[0])}</div>
            <div class="slide-text">you text <span class="big-number yellow" style="font-size:56px">{ratio}x</span> more</div>
        </div>''')
    
    # Slide 14: Ghosted
    if d['ghosted']:
        ghost_html = ''.join([f'<div class="rank-item"><span class="rank-num">👻</span><span class="rank-name">{n(h)}</span><span class="rank-count"><span class="green">{b}</span>→<span class="red">{a}</span></span></div>' for h,b,a in d['ghosted'][:5]])
        slides.append(f'''
        <div class="slide">
            <div class="slide-label">// GHOSTED</div>
            <div class="slide-text">they chose peace</div>
            <div class="rank-list">{ghost_html}</div>
            <div class="roast">before June → after</div>
        </div>''')
    
    # Slide 15: Response time
    resp_class = 'green' if d['resp'] < 10 else 'yellow' if d['resp'] < 60 else 'red'
    resp_label = "INSTANT" if d['resp'] < 10 else "NORMAL" if d['resp'] < 60 else "SLOW"
    slides.append(f'''
    <div class="slide">
        <div class="slide-label">// RESPONSE TIME</div>
        <div class="slide-text">avg reply</div>
        <div class="big-number {resp_class}">{d['resp']}</div>
        <div class="slide-text">minutes</div>
        <div class="badge {resp_class}">{resp_label}</div>
    </div>''')
    
    # Slide 16: Emojis
    if d['emoji'] and any(e[1] > 0 for e in d['emoji']):
        emo = '  '.join([e[0] for e in d['emoji'] if e[1] > 0])
        slides.append(f'''
        <div class="slide">
            <div class="slide-label">// EMOJIS</div>
            <div class="slide-text">your emotional range</div>
            <div class="emoji-row">{emo}</div>
        </div>''')
    
    # Final slide: Summary card
    top3_names = ', '.join([n(h) for h,_,_,_ in top[:3]])
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
                    <span class="summary-stat-val">{words_k:,}K</span>
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
<style>
@import url('https://fonts.googleapis.com/css2?family=Silkscreen&family=Azeret+Mono:wght@400;500;600;700&family=Space+Grotesk:wght@400;500;700&display=swap');

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

.slide h1 {{ font-family:var(--font-pixel); font-size:36px; font-weight:400; line-height:1.2; margin:20px 0; }}
.slide-label {{ font-family:var(--font-pixel); font-size:10px; font-weight:400; color:var(--green); letter-spacing:0.5px; margin-bottom:16px; }}
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

.rank-list {{ width:100%; max-width:420px; margin-top:20px; }}
.rank-item {{ display:flex; align-items:center; padding:14px 0; border-bottom:1px solid rgba(255,255,255,0.1); gap:16px; }}
.rank-num {{ font-family:var(--font-mono); font-size:20px; font-weight:600; color:var(--green); width:36px; text-align:center; }}
.rank-name {{ flex:1; font-size:16px; text-align:left; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.rank-count {{ font-family:var(--font-mono); font-size:18px; font-weight:600; color:var(--yellow); }}

.badge {{ display:inline-block; padding:8px 18px; border-radius:24px; font-family:var(--font-pixel); font-size:9px; font-weight:400; text-transform:uppercase; letter-spacing:0.3px; margin-top:20px; border:2px solid; }}
.badge.green {{ border-color:var(--green); color:var(--green); background:rgba(74,222,128,0.1); }}
.badge.yellow {{ border-color:var(--yellow); color:var(--yellow); background:rgba(251,191,36,0.1); }}
.badge.red {{ border-color:var(--red); color:var(--red); background:rgba(248,113,113,0.1); }}

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
.slide .rank-list,
.slide .emoji-row,
.slide h1,
.slide .subtitle {{
    opacity: 0;
    transform: translateY(20px);
}}

.slide.active .slide-label {{
    animation: fadeSlideUp 0.5s ease-out forwards;
}}

.slide.active .slide-icon {{
    animation: popIn 0.6s cubic-bezier(0.34, 1.56, 0.64, 1) 0.1s forwards;
}}

.slide.active h1 {{
    animation: fadeSlideUp 0.6s ease-out 0.15s forwards;
}}

.slide.active .subtitle {{
    animation: fadeSlideUp 0.5s ease-out 0.3s forwards;
}}

.slide.active .slide-text {{
    animation: fadeSlideUp 0.4s ease-out 0.2s forwards;
}}

.slide.active .big-number {{
    animation: countReveal 0.7s cubic-bezier(0.34, 1.56, 0.64, 1) 0.3s forwards;
}}

.slide.active .huge-name {{
    animation: nameReveal 0.6s cubic-bezier(0.22, 1, 0.36, 1) 0.35s forwards;
}}

.slide.active .personality-type {{
    animation: glitchReveal 0.8s ease-out 0.3s forwards;
}}

.slide.active .roast {{
    animation: fadeSlideUp 0.5s ease-out 0.6s forwards;
}}

.slide.active .badge {{
    animation: badgePop 0.5s cubic-bezier(0.34, 1.56, 0.64, 1) 0.7s forwards;
}}

.slide.active .stat-grid {{
    animation: fadeSlideUp 0.5s ease-out 0.5s forwards;
}}

.slide.active .rank-list {{
    animation: fadeIn 0.3s ease-out 0.3s forwards;
}}

.slide.active .rank-item {{
    opacity: 0;
    animation: rankCascade 0.4s ease-out forwards;
}}

.slide.active .rank-item:nth-child(1) {{ animation-delay: 0.35s; }}
.slide.active .rank-item:nth-child(2) {{ animation-delay: 0.45s; }}
.slide.active .rank-item:nth-child(3) {{ animation-delay: 0.55s; }}
.slide.active .rank-item:nth-child(4) {{ animation-delay: 0.65s; }}
.slide.active .rank-item:nth-child(5) {{ animation-delay: 0.75s; }}

.slide.active .emoji-row {{
    animation: emojiWave 0.8s ease-out 0.3s forwards;
}}

/* Summary card special treatment */
.slide.active .summary-card {{
    animation: cardReveal 0.7s cubic-bezier(0.22, 1, 0.36, 1) 0.2s forwards;
}}

.slide.active .screenshot-btn {{
    opacity: 0;
    animation: fadeSlideUp 0.5s ease-out 0.8s forwards;
}}

.slide.active .share-hint {{
    opacity: 0;
    animation: fadeSlideUp 0.4s ease-out 1s forwards;
}}

/* Keyframes */
@keyframes fadeSlideUp {{
    from {{ opacity: 0; transform: translateY(20px); }}
    to {{ opacity: 1; transform: translateY(0); }}
}}

@keyframes fadeIn {{
    from {{ opacity: 0; }}
    to {{ opacity: 1; }}
}}

@keyframes popIn {{
    0% {{ opacity: 0; transform: translateY(20px) scale(0.8); }}
    70% {{ transform: translateY(-5px) scale(1.1); }}
    100% {{ opacity: 1; transform: translateY(0) scale(1); }}
}}

@keyframes countReveal {{
    0% {{ opacity: 0; transform: translateY(30px) scale(0.9); }}
    60% {{ transform: translateY(-8px) scale(1.02); }}
    100% {{ opacity: 1; transform: translateY(0) scale(1); }}
}}

@keyframes nameReveal {{
    0% {{ opacity: 0; transform: translateY(40px); }}
    100% {{ opacity: 1; transform: translateY(0); }}
}}

@keyframes glitchReveal {{
    0% {{ opacity: 0; transform: translateY(20px); filter: blur(8px); }}
    20% {{ opacity: 0.5; transform: translateY(10px) skewX(-5deg); filter: blur(4px); }}
    40% {{ opacity: 0.7; transform: translateY(5px) skewX(3deg); filter: blur(2px); }}
    60% {{ opacity: 0.9; transform: translateY(-2px) skewX(-1deg); filter: blur(0); }}
    80% {{ transform: translateY(1px) skewX(0.5deg); }}
    100% {{ opacity: 1; transform: translateY(0) skewX(0); }}
}}

@keyframes badgePop {{
    0% {{ opacity: 0; transform: translateY(10px) scale(0.8); }}
    70% {{ transform: translateY(-3px) scale(1.1); }}
    100% {{ opacity: 1; transform: translateY(0) scale(1); }}
}}

@keyframes rankCascade {{
    0% {{ opacity: 0; transform: translateX(-30px); }}
    100% {{ opacity: 1; transform: translateX(0); }}
}}

@keyframes emojiWave {{
    0% {{ opacity: 0; transform: translateY(30px) scale(0.8); }}
    50% {{ transform: translateY(-5px) scale(1.05); }}
    100% {{ opacity: 1; transform: translateY(0) scale(1); }}
}}

@keyframes cardReveal {{
    0% {{ opacity: 0; transform: translateY(40px) scale(0.95); }}
    100% {{ opacity: 1; transform: translateY(0) scale(1); }}
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
        link.download = 'imessage_wrapped_2025.png';
        link.href = canvas.toDataURL('image/png');
        link.click();
        btn.innerHTML = '<span class="btn-icon">✓</span><span>Saved!</span>';
        setTimeout(() => {{ btn.innerHTML = '<span class="btn-icon">📸</span><span>Save Screenshot</span>'; btn.disabled = false; }}, 2000);
    }} catch (err) {{
        btn.innerHTML = '<span class="btn-icon">📸</span><span>Save Screenshot</span>';
        btn.disabled = false;
    }}
}}

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
    
    print(f"[*] Analyzing {year}...")
    data = analyze(ts_start, ts_jun)
    print(f"    ✓ {data['stats'][0]:,} messages")
    
    print(f"[*] Generating...")
    gen_html(data, contacts, args.output)
    print(f"    ✓ {args.output}")
    
    subprocess.run(['open', args.output])
    print("\n  Done! Click through your wrapped.\n")

if __name__ == '__main__':
    main()
