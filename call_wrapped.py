#!/usr/bin/env python3
"""
Call Wrapped 2025 - Your calling habits across Phone, FaceTime & WhatsApp, exposed.
Usage: python3 call_wrapped.py
"""

import sqlite3, os, sys, re, subprocess, argparse, glob, threading, time
from datetime import datetime, timedelta
from collections import defaultdict

# Database paths
CALL_HISTORY_DB = os.path.expanduser("~/Library/Application Support/CallHistoryDB/CallHistory.storedata")
WHATSAPP_CALLS_DB = os.path.expanduser("~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/CallHistory.sqlite")
ADDRESSBOOK_DIR = os.path.expanduser("~/Library/Application Support/AddressBook")

# Mac epoch offset (Jan 1, 2001 -> Jan 1, 1970)
MAC_EPOCH = 978307200

# Timestamps for 2025
TS_2025_START = datetime(2025, 1, 1).timestamp()
TS_2025_END = datetime(2025, 12, 31, 23, 59, 59).timestamp()
TS_JUN_2025 = datetime(2025, 6, 1).timestamp()

# Timestamps for 2024
TS_2024_START = datetime(2024, 1, 1).timestamp()
TS_2024_END = datetime(2024, 12, 31, 23, 59, 59).timestamp()
TS_JUN_2024 = datetime(2024, 6, 1).timestamp()


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


def normalize_phone(phone):
    """Normalize phone number to last 10 digits."""
    if not phone:
        return None
    digits = re.sub(r'\D', '', str(phone))
    if len(digits) == 11 and digits.startswith('1'):
        digits = digits[1:]
    elif len(digits) > 10:
        return digits[-10:]
    return digits[-10:] if len(digits) >= 10 else (digits if len(digits) >= 7 else None)


def extract_contacts():
    """Extract contacts from macOS AddressBook."""
    contacts = {}
    db_paths = glob.glob(os.path.join(ADDRESSBOOK_DIR, "Sources", "*", "AddressBook-v22.abcddb"))
    main_db = os.path.join(ADDRESSBOOK_DIR, "AddressBook-v22.abcddb")
    if os.path.exists(main_db):
        db_paths.append(main_db)

    for db_path in db_paths:
        try:
            conn = sqlite3.connect(db_path)
            people = {}
            for row in conn.execute("SELECT ROWID, ZFIRSTNAME, ZLASTNAME FROM ZABCDRECORD WHERE ZFIRSTNAME IS NOT NULL OR ZLASTNAME IS NOT NULL"):
                name = f"{row[1] or ''} {row[2] or ''}".strip()
                if name:
                    people[row[0]] = name
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
            conn.close()
        except:
            pass
    return contacts


def get_name(phone, contacts):
    """Resolve phone number to contact name."""
    if not phone:
        return None
    digits = re.sub(r'\D', '', str(phone))

    # Skip short codes
    if 5 <= len(digits) <= 6:
        return None

    # Skip toll-free
    if len(digits) >= 10 and digits[-10:-7] in ('800', '888', '877', '866', '855', '844', '833'):
        return None

    if digits in contacts:
        return contacts[digits]
    if len(digits) == 11 and digits.startswith('1'):
        if digits[1:] in contacts:
            return contacts[digits[1:]]
    if len(digits) >= 10 and digits[-10:] in contacts:
        return contacts[digits[-10:]]
    if len(digits) >= 7 and digits[-7:] in contacts:
        return contacts[digits[-7:]]
    return None


def check_access():
    """Check access to call databases. Returns (has_phone, has_whatsapp)."""
    has_phone = False
    has_whatsapp = False

    # Check Phone/FaceTime
    if os.path.exists(CALL_HISTORY_DB):
        try:
            conn = sqlite3.connect(CALL_HISTORY_DB)
            conn.execute("SELECT 1 FROM ZCALLRECORD LIMIT 1")
            conn.close()
            has_phone = True
        except:
            pass

    # Check WhatsApp
    if os.path.exists(WHATSAPP_CALLS_DB):
        try:
            conn = sqlite3.connect(WHATSAPP_CALLS_DB)
            conn.execute("SELECT 1 FROM ZWAAGGREGATECALLEVENT LIMIT 1")
            conn.close()
            has_whatsapp = True
        except:
            pass

    if not has_phone and not has_whatsapp:
        print("\n[!] ACCESS DENIED - Neither Phone nor WhatsApp call history accessible")
        print("   System Settings -> Privacy & Security -> Full Disk Access -> Add Terminal")
        subprocess.run(['open', 'x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles'])
        sys.exit(1)

    return has_phone, has_whatsapp


def q_phone(sql):
    """Query phone call history database."""
    conn = sqlite3.connect(CALL_HISTORY_DB)
    r = conn.execute(sql).fetchall()
    conn.close()
    return r


def q_whatsapp(sql):
    """Query WhatsApp call history database."""
    conn = sqlite3.connect(WHATSAPP_CALLS_DB)
    r = conn.execute(sql).fetchall()
    conn.close()
    return r


def format_duration(seconds):
    """Format seconds as human-readable duration."""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins}m {secs}s" if secs else f"{mins}m"
    else:
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        return f"{hours}h {mins}m" if mins else f"{hours}h"


def format_duration_short(seconds):
    """Format seconds as short duration (e.g., '2h 15m')."""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        return f"{int(seconds // 60)}m"
    else:
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        return f"{hours}h {mins}m" if mins else f"{hours}h"


def analyze_phone_calls(ts_start, ts_end, ts_jun, contacts):
    """Analyze phone/FaceTime call history."""
    calls = []

    # Get all calls in date range
    rows = q_phone(f"""
        SELECT ZADDRESS, ZDURATION, ZDATE, ZORIGINATED, ZANSWERED, ZCALLTYPE
        FROM ZCALLRECORD
        WHERE (ZDATE + {MAC_EPOCH}) > {ts_start} AND (ZDATE + {MAC_EPOCH}) < {ts_end}
        ORDER BY ZDATE
    """)

    for row in rows:
        phone, duration, ts, originated, answered, call_type = row
        name = get_name(phone, contacts)
        if not name:
            continue

        # Determine call type: 1=Phone, 8=FaceTime Audio, 16=FaceTime Video
        if call_type in (8, 16):
            platform = 'FaceTime'
            is_video = call_type == 16
        else:
            platform = 'Phone'
            is_video = False

        calls.append({
            'name': name,
            'phone': normalize_phone(phone),
            'duration': duration or 0,
            'timestamp': ts + MAC_EPOCH,
            'outgoing': originated == 1,
            'answered': answered == 1,
            'platform': platform,
            'is_video': is_video,
        })

    return calls


def analyze_whatsapp_calls(ts_start, ts_end, ts_jun, contacts):
    """Analyze WhatsApp call history."""
    calls = []

    # Get WhatsApp contact names
    wa_contacts = {}
    try:
        wa_msg_db = os.path.expanduser("~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite")
        if os.path.exists(wa_msg_db):
            conn = sqlite3.connect(wa_msg_db)
            for row in conn.execute("SELECT ZJID, ZPUSHNAME FROM ZWAPROFILEPUSHNAME WHERE ZPUSHNAME IS NOT NULL"):
                jid, name = row
                if jid and name:
                    wa_contacts[jid] = name
            conn.close()
    except:
        pass

    # Get all WhatsApp calls from ZWACDCALLEVENT (has duration!)
    # Join with participant table to get phone number/JID
    rows = q_whatsapp(f"""
        SELECT e.ZDURATION, e.ZDATE, e.ZOUTCOME, p.ZJIDSTRING
        FROM ZWACDCALLEVENT e
        JOIN ZWACDCALLEVENTPARTICIPANT p ON p.Z1PARTICIPANTS = e.Z_PK
        WHERE (e.ZDATE + {MAC_EPOCH}) > {ts_start} AND (e.ZDATE + {MAC_EPOCH}) < {ts_end}
        ORDER BY e.ZDATE
    """)

    for row in rows:
        duration, ts, outcome, jid = row

        # Handle both @s.whatsapp.net (phone) and @lid (internal ID) formats
        phone = jid.split('@')[0] if jid else None
        name = None

        # Try WhatsApp contacts first
        if jid in wa_contacts:
            name = wa_contacts[jid]
        # Try AddressBook lookup by phone number
        if not name and phone:
            name = get_name(phone, contacts)
        if not name:
            continue

        calls.append({
            'name': name,
            'phone': normalize_phone(phone),
            'duration': duration or 0,
            'timestamp': ts + MAC_EPOCH,
            'outgoing': True,  # Direction not in this table
            'answered': (duration or 0) > 0,  # Has duration = was answered
            'platform': 'WhatsApp',
            'is_video': False,  # Video flag not in this table
        })

    return calls


def analyze_calls(phone_calls, whatsapp_calls, ts_start, ts_end, ts_jun):
    """Combine and analyze all calls."""
    all_calls = phone_calls + whatsapp_calls
    all_calls.sort(key=lambda x: x['timestamp'])

    d = {}

    # Basic stats
    total_calls = len(all_calls)
    outgoing = sum(1 for c in all_calls if c['outgoing'])
    incoming = total_calls - outgoing
    answered = sum(1 for c in all_calls if c['answered'])
    missed = total_calls - answered
    total_duration = sum(c['duration'] for c in all_calls)

    d['stats'] = {
        'total': total_calls,
        'outgoing': outgoing,
        'incoming': incoming,
        'answered': answered,
        'missed': missed,
        'total_duration': total_duration,
    }

    # Platform breakdown
    platform_stats = defaultdict(lambda: {'count': 0, 'duration': 0})
    for c in all_calls:
        platform_stats[c['platform']]['count'] += 1
        platform_stats[c['platform']]['duration'] += c['duration']
    d['platforms'] = dict(platform_stats)

    # Video vs voice
    video_calls = sum(1 for c in all_calls if c['is_video'])
    voice_calls = total_calls - video_calls
    d['video_voice'] = {'video': video_calls, 'voice': voice_calls}

    # Top contacts by call count - key by phone number to deduplicate
    phone_stats = defaultdict(lambda: {
        'count': 0, 'duration': 0, 'outgoing': 0, 'incoming': 0,
        'answered': 0, 'missed': 0, 'platforms': set(), 'names': set()
    })
    for c in all_calls:
        # Use last 10 digits of phone as key for consistent matching across platforms
        phone = c['phone']
        if phone:
            digits = re.sub(r'\D', '', str(phone))
            key = digits[-10:] if len(digits) >= 7 else None
        else:
            key = None
        # Fall back to name if no valid phone
        if not key:
            key = f"name:{c['name']}"
        cs = phone_stats[key]
        cs['count'] += 1
        cs['duration'] += c['duration']
        cs['outgoing'] += 1 if c['outgoing'] else 0
        cs['incoming'] += 0 if c['outgoing'] else 1
        cs['answered'] += 1 if c['answered'] else 0
        cs['missed'] += 0 if c['answered'] else 1
        cs['platforms'].add(c['platform'])
        cs['names'].add(c['name'])

    # Convert to contact_stats with best display name (longest name = most complete)
    contact_stats = {}
    for key, stats in phone_stats.items():
        # Pick the longest name as display name (e.g., "Shimolee Kothari" > "Shimolee")
        best_name = max(stats['names'], key=len)
        stats['platforms'] = list(stats['platforms'])
        del stats['names']
        contact_stats[best_name] = stats

    # Top 10 by call count
    top_by_count = sorted(contact_stats.items(), key=lambda x: x[1]['count'], reverse=True)[:10]
    d['top_count'] = [(name, stats) for name, stats in top_by_count]

    # Top 10 by duration
    top_by_duration = sorted(contact_stats.items(), key=lambda x: x[1]['duration'], reverse=True)[:10]
    d['top_duration'] = [(name, stats) for name, stats in top_by_duration]

    # Longest single call
    if all_calls:
        longest = max(all_calls, key=lambda x: x['duration'])
        d['longest_call'] = longest
    else:
        d['longest_call'] = None

    # Peak hour
    hour_counts = defaultdict(int)
    for c in all_calls:
        hour = datetime.fromtimestamp(c['timestamp']).hour
        hour_counts[hour] += 1
    if hour_counts:
        peak_hour = max(hour_counts.items(), key=lambda x: x[1])[0]
        d['peak_hour'] = peak_hour
    else:
        d['peak_hour'] = 12

    # Peak day of week
    day_counts = defaultdict(int)
    days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
    for c in all_calls:
        day = datetime.fromtimestamp(c['timestamp']).strftime('%w')
        day_counts[int(day)] += 1
    if day_counts:
        peak_day = max(day_counts.items(), key=lambda x: x[1])[0]
        d['peak_day'] = days[peak_day]
    else:
        d['peak_day'] = 'Unknown'

    # Night owl calls (midnight - 5am)
    night_owl_stats = defaultdict(int)
    for c in all_calls:
        hour = datetime.fromtimestamp(c['timestamp']).hour
        if hour < 5:
            night_owl_stats[c['name']] += 1
    night_owls = sorted(night_owl_stats.items(), key=lambda x: x[1], reverse=True)[:5]
    d['night_owls'] = night_owls

    # Early bird calls (6-9am)
    early_bird_stats = defaultdict(int)
    for c in all_calls:
        hour = datetime.fromtimestamp(c['timestamp']).hour
        if 6 <= hour <= 9:
            early_bird_stats[c['name']] += 1
    early_birds = sorted(early_bird_stats.items(), key=lambda x: x[1], reverse=True)[:5]
    d['early_birds'] = early_birds

    # Missed call king (who you miss calls from most)
    missed_from = defaultdict(int)
    for c in all_calls:
        if not c['answered'] and not c['outgoing']:
            missed_from[c['name']] += 1
    missed_kings = sorted(missed_from.items(), key=lambda x: x[1], reverse=True)[:5]
    d['missed_kings'] = missed_kings

    # Call avoider (who you call but doesn't answer)
    unanswered_to = defaultdict(lambda: {'attempts': 0, 'answered': 0})
    for c in all_calls:
        if c['outgoing']:
            unanswered_to[c['name']]['attempts'] += 1
            if c['answered']:
                unanswered_to[c['name']]['answered'] += 1

    avoiders = []
    for name, stats in unanswered_to.items():
        if stats['attempts'] >= 5:
            miss_rate = (stats['attempts'] - stats['answered']) / stats['attempts']
            if miss_rate > 0.5:
                avoiders.append((name, stats['attempts'] - stats['answered'], stats['attempts']))
    avoiders.sort(key=lambda x: x[1], reverse=True)
    d['avoiders'] = avoiders[:5]

    # Speed dialer (shortest avg call duration)
    avg_durations = []
    for name, stats in contact_stats.items():
        if stats['count'] >= 5 and stats['duration'] > 0:
            avg = stats['duration'] / stats['count']
            avg_durations.append((name, avg, stats['count']))
    avg_durations.sort(key=lambda x: x[1])
    d['speed_dialers'] = avg_durations[:5]

    # Marathon talkers (longest avg call duration)
    marathon_talkers = sorted(avg_durations, key=lambda x: x[1], reverse=True)[:5]
    d['marathon_talkers'] = marathon_talkers

    # Busiest day
    daily_counts = defaultdict(int)
    for c in all_calls:
        day_str = datetime.fromtimestamp(c['timestamp']).strftime('%Y-%m-%d')
        daily_counts[day_str] += 1

    d['daily_counts'] = dict(daily_counts)

    if daily_counts:
        busiest_day = max(daily_counts.items(), key=lambda x: x[1])
        d['busiest_day'] = busiest_day
    else:
        d['busiest_day'] = None

    # H1 vs H2 comparison
    h1_calls = sum(1 for c in all_calls if c['timestamp'] < ts_jun)
    h2_calls = sum(1 for c in all_calls if c['timestamp'] >= ts_jun)
    d['h1_h2'] = {'h1': h1_calls, 'h2': h2_calls}

    # Heating up (more calls in H2)
    contact_h1_h2 = defaultdict(lambda: {'h1': 0, 'h2': 0})
    for c in all_calls:
        if c['timestamp'] < ts_jun:
            contact_h1_h2[c['name']]['h1'] += 1
        else:
            contact_h1_h2[c['name']]['h2'] += 1

    heating_up = []
    for name, stats in contact_h1_h2.items():
        if stats['h1'] >= 3 and stats['h2'] > stats['h1'] * 1.5:
            heating_up.append((name, stats['h1'], stats['h2']))
    heating_up.sort(key=lambda x: x[2] - x[1], reverse=True)
    d['heating_up'] = heating_up[:5]

    # Cooling down (less calls in H2)
    cooling_down = []
    for name, stats in contact_h1_h2.items():
        if stats['h1'] >= 5 and stats['h2'] < stats['h1'] * 0.5:
            cooling_down.append((name, stats['h1'], stats['h2']))
    cooling_down.sort(key=lambda x: x[1] - x[2], reverse=True)
    d['cooling_down'] = cooling_down[:5]

    # Monthly breakdown
    monthly_counts = defaultdict(int)
    monthly_duration = defaultdict(int)
    for c in all_calls:
        month = datetime.fromtimestamp(c['timestamp']).strftime('%b')
        monthly_counts[month] += 1
        monthly_duration[month] += c['duration']
    d['monthly_counts'] = dict(monthly_counts)
    d['monthly_duration'] = dict(monthly_duration)

    # Busiest month
    if monthly_counts:
        d['busiest_month'] = max(monthly_counts.items(), key=lambda x: x[1])[0]
    else:
        d['busiest_month'] = 'N/A'

    # Average calls per day
    if daily_counts:
        d['avg_daily'] = round(total_calls / len(daily_counts), 1)
    else:
        d['avg_daily'] = 0

    # Quiet days (zero calls)
    year_start = datetime.fromtimestamp(ts_start)
    year_end = min(datetime.fromtimestamp(ts_end), datetime.now())
    total_days = (year_end - year_start).days + 1
    days_with_calls = len(daily_counts)
    d['quiet_days'] = total_days - days_with_calls

    # Unique contacts
    d['unique_contacts'] = len(contact_stats)

    # === NEW DELIGHTFUL INSIGHTS ===

    # First call of the year
    if all_calls:
        first_call = all_calls[0]
        d['first_call'] = first_call
    else:
        d['first_call'] = None

    # Who calls YOU most (biggest fan - inbound only)
    inbound_from = defaultdict(int)
    for c in all_calls:
        if not c['outgoing']:
            inbound_from[c['name']] += 1
    biggest_fans = sorted(inbound_from.items(), key=lambda x: x[1], reverse=True)[:5]
    d['biggest_fans'] = biggest_fans

    # Longest streak (consecutive days calling same person)
    streaks = {}
    for name in contact_stats.keys():
        person_dates = sorted(set(
            datetime.fromtimestamp(c['timestamp']).strftime('%Y-%m-%d')
            for c in all_calls if c['name'] == name
        ))
        if len(person_dates) < 2:
            continue
        max_streak = 1
        current_streak = 1
        for i in range(1, len(person_dates)):
            d1 = datetime.strptime(person_dates[i-1], '%Y-%m-%d')
            d2 = datetime.strptime(person_dates[i], '%Y-%m-%d')
            if (d2 - d1).days == 1:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 1
        if max_streak >= 3:
            streaks[name] = max_streak
    if streaks:
        best_streak = max(streaks.items(), key=lambda x: x[1])
        d['longest_streak'] = best_streak
    else:
        d['longest_streak'] = None

    # Weekday vs Weekend breakdown
    weekday_calls = sum(1 for c in all_calls if datetime.fromtimestamp(c['timestamp']).weekday() < 5)
    weekend_calls = total_calls - weekday_calls
    d['weekday_weekend'] = {'weekday': weekday_calls, 'weekend': weekend_calls}

    # Call duration buckets (quick <2min, normal 2-15min, marathon 15min+)
    quick_calls = sum(1 for c in all_calls if c['answered'] and c['duration'] < 120)
    normal_calls = sum(1 for c in all_calls if c['answered'] and 120 <= c['duration'] < 900)
    long_calls = sum(1 for c in all_calls if c['answered'] and c['duration'] >= 900)
    d['duration_buckets'] = {'quick': quick_calls, 'normal': normal_calls, 'marathon': long_calls}

    # Ghost protocol (missed calls you never returned)
    # Build set of people you called (outgoing)
    people_you_called = set()
    call_times_to = defaultdict(list)  # name -> list of outgoing call timestamps
    for c in all_calls:
        if c['outgoing']:
            people_you_called.add(c['name'])
            call_times_to[c['name']].append(c['timestamp'])

    # Find missed calls you never returned (or returned very late)
    ghosts = defaultdict(int)
    for c in all_calls:
        if not c['outgoing'] and not c['answered']:
            # Check if you ever called them back after this
            later_calls = [t for t in call_times_to.get(c['name'], []) if t > c['timestamp']]
            if not later_calls:
                ghosts[c['name']] += 1
    ghost_list = sorted(ghosts.items(), key=lambda x: x[1], reverse=True)[:5]
    d['ghosts'] = ghost_list

    # Call back speed (avg time to return missed calls, in minutes)
    callback_times = []
    for c in all_calls:
        if not c['outgoing'] and not c['answered']:
            # Find first outgoing call to this person after the missed call
            later_calls = [t for t in call_times_to.get(c['name'], []) if t > c['timestamp']]
            if later_calls:
                callback_time = (min(later_calls) - c['timestamp']) / 60  # minutes
                if callback_time < 1440:  # within 24 hours
                    callback_times.append(callback_time)
    if callback_times:
        d['avg_callback_time'] = round(sum(callback_times) / len(callback_times))
    else:
        d['avg_callback_time'] = None

    # Calling personality diagnosis
    # Based on: call frequency, duration, missed rate, callback speed, outgoing ratio
    answered_calls = [c for c in all_calls if c['answered']]
    avg_duration = sum(c['duration'] for c in answered_calls) / max(len(answered_calls), 1)
    outgoing_ratio = outgoing / max(total_calls, 1)
    miss_rate = missed / max(total_calls, 1)

    if avg_duration < 60 and total_calls > 200:
        personality = ("THE SPEED DIALER", "You treat calls like texts - quick, efficient, gone")
    elif avg_duration > 600 and total_calls > 50:
        personality = ("THE CHATTY CATHY", "Once you're on the phone, you're ON the phone")
    elif miss_rate > 0.4:
        personality = ("THE SCREENER", "Your phone is always on silent, isn't it?")
    elif outgoing_ratio > 0.7:
        personality = ("THE INITIATOR", "You don't wait for calls, you make them happen")
    elif outgoing_ratio < 0.3:
        personality = ("THE POPULAR ONE", "Everyone wants to talk to you")
    elif d['avg_callback_time'] and d['avg_callback_time'] < 10:
        personality = ("THE RESPONSIVE ONE", "Missed call? You'll call back in minutes")
    elif total_calls < 50:
        personality = ("THE PHONE PHOBIC", "Calls? In this economy? You prefer texts")
    elif weekend_calls > weekday_calls * 0.5:
        personality = ("THE WEEKEND WARRIOR", "Your phone comes alive on weekends")
    else:
        personality = ("THE BALANCED CALLER", "A healthy relationship with your phone")
    d['personality'] = personality

    return d


def get_data_coverage(ts_start, ts_end, has_phone, has_whatsapp):
    """Check how much of the year we have data for."""
    earliest = None
    latest = None

    if has_phone:
        rows = q_phone(f"""
            SELECT MIN(ZDATE + {MAC_EPOCH}), MAX(ZDATE + {MAC_EPOCH})
            FROM ZCALLRECORD
            WHERE (ZDATE + {MAC_EPOCH}) > {ts_start} AND (ZDATE + {MAC_EPOCH}) < {ts_end}
        """)
        if rows and rows[0][0]:
            earliest = rows[0][0]
            latest = rows[0][1]

    if has_whatsapp:
        rows = q_whatsapp(f"""
            SELECT MIN(ZFIRSTDATE + {MAC_EPOCH}), MAX(ZFIRSTDATE + {MAC_EPOCH})
            FROM ZWAAGGREGATECALLEVENT
            WHERE (ZFIRSTDATE + {MAC_EPOCH}) > {ts_start} AND (ZFIRSTDATE + {MAC_EPOCH}) < {ts_end}
        """)
        if rows and rows[0][0]:
            if earliest is None or rows[0][0] < earliest:
                earliest = rows[0][0]
            if latest is None or rows[0][1] > latest:
                latest = rows[0][1]

    return earliest, latest


def gen_html(d, path, year, has_phone, has_whatsapp, earliest_date, latest_date):
    """Generate the wrapped HTML report."""
    stats = d['stats']

    # Format peak hour
    hr = d['peak_hour']
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

    # Data coverage warning
    coverage_warning = ""
    if earliest_date:
        earliest_dt = datetime.fromtimestamp(earliest_date)
        year_start = datetime(int(year), 1, 1)
        if earliest_dt > year_start + timedelta(days=7):
            coverage_warning = f"Data starts {earliest_dt.strftime('%b %d')}"

    slides = []

    # Slide 1: Intro
    platforms_text = []
    if has_phone:
        platforms_text.append("Phone + FaceTime")
    if has_whatsapp:
        platforms_text.append("WhatsApp")
    platform_str = " & ".join(platforms_text)

    slides.append(f'''
    <div class="slide intro">
        <div class="slide-icon">📞</div>
        <h1>CALLS<br>WRAPPED</h1>
        <p class="subtitle">{platform_str}</p>
        <p class="subtitle2">your {year} calling habits, exposed</p>
        {f'<p class="coverage-warning">⚠️ {coverage_warning}</p>' if coverage_warning else ''}
        <div class="tap-hint">click anywhere to start →</div>
    </div>''')

    # Slide 2: Total calls
    avg_per_day = d['avg_daily']
    total_duration_str = format_duration_short(stats['total_duration'])

    slides.append(f'''
    <div class="slide">
        <div class="slide-label">// TOTAL DAMAGE</div>
        <div class="big-number gradient">{stats['total']:,}</div>
        <div class="slide-text">calls this year</div>
        <div class="stat-grid">
            <div class="stat-item"><span class="stat-num">{avg_per_day}</span><span class="stat-lbl">/day</span></div>
            <div class="stat-item"><span class="stat-num">{stats['outgoing']:,}</span><span class="stat-lbl">outgoing</span></div>
            <div class="stat-item"><span class="stat-num">{stats['incoming']:,}</span><span class="stat-lbl">incoming</span></div>
        </div>
        <div class="roast" style="margin-top:24px;">that's {total_duration_str} of your life on calls</div>
        <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_total_calls.png', this)">📸 Save</button>
        <div class="slide-watermark">wrap2025.com</div>
    </div>''')

    # Slide 3: Platform breakdown
    if len(d['platforms']) > 1:
        platform_bars = []
        total_calls = stats['total']
        for platform in ['Phone', 'FaceTime', 'WhatsApp']:
            if platform in d['platforms']:
                pct = round(d['platforms'][platform]['count'] / max(total_calls, 1) * 100)
                count = d['platforms'][platform]['count']
                icon = '📱' if platform == 'Phone' else ('📹' if platform == 'FaceTime' else '💬')
                css_class = 'phone' if platform == 'Phone' else ('facetime' if platform == 'FaceTime' else 'whatsapp')
                platform_bars.append(f'''
                <div class="platform-bar {css_class}" style="width:{max(pct, 15)}%">
                    <span class="platform-icon">{icon}</span>
                    <span class="platform-name">{platform}</span>
                    <span class="platform-pct">{pct}%</span>
                    <span class="platform-count">{count:,}</span>
                </div>''')

        slides.append(f'''
        <div class="slide platform-breakdown">
            <div class="slide-label">// PLATFORM SPLIT</div>
            <div class="slide-text">where you call the most</div>
            <div class="platform-bars">
                {''.join(platform_bars)}
            </div>
            <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_platform_split.png', this)">📸 Save</button>
            <div class="slide-watermark">wrap2025.com</div>
        </div>''')

    # Slide 4: Video vs Voice
    video = d['video_voice']['video']
    voice = d['video_voice']['voice']
    if video > 0:
        video_pct = round(video / max(stats['total'], 1) * 100)
        slides.append(f'''
        <div class="slide">
            <div class="slide-label">// VIDEO VS VOICE</div>
            <div class="dual-stats">
                <div class="dual-stat">
                    <span class="dual-icon">🎥</span>
                    <span class="dual-num cyan">{video:,}</span>
                    <span class="dual-label">video calls</span>
                </div>
                <div class="dual-stat">
                    <span class="dual-icon">🎤</span>
                    <span class="dual-num yellow">{voice:,}</span>
                    <span class="dual-label">voice calls</span>
                </div>
            </div>
            <div class="roast">{video_pct}% of your calls were face-to-face</div>
            <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_video_voice.png', this)">📸 Save</button>
            <div class="slide-watermark">wrap2025.com</div>
        </div>''')

    # Slide 5: Your #1 by calls
    if d['top_count']:
        top = d['top_count'][0]
        name, stats_top = top
        platforms_icons = ' '.join(['📱' if p == 'Phone' else ('📹' if p == 'FaceTime' else '💬') for p in stats_top['platforms']])
        slides.append(f'''
        <div class="slide gradient-bg">
            <div class="slide-label">// YOUR #1</div>
            <div class="slide-text">most called person</div>
            <div class="huge-name">{name}</div>
            <div class="big-number yellow">{stats_top['count']:,}</div>
            <div class="slide-text">calls <span class="source-badge">{platforms_icons}</span></div>
            <div class="roast">{format_duration_short(stats_top['duration'])} total talk time</div>
            <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_your_number_one.png', this)">📸 Save</button>
            <div class="slide-watermark">wrap2025.com</div>
        </div>''')

    # Slide 6: Inner Circle (Top 5 by calls)
    if d['top_count']:
        top5_html = ''.join([
            f'<div class="rank-item"><span class="rank-num">{i}</span><span class="rank-name">{name}</span><span class="rank-count">{stats["count"]:,}</span></div>'
            for i, (name, stats) in enumerate(d['top_count'][:5], 1)
        ])
        slides.append(f'''
        <div class="slide">
            <div class="slide-label">// INNER CIRCLE</div>
            <div class="slide-text">top 5 by call count</div>
            <div class="rank-list">{top5_html}</div>
            <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_inner_circle.png', this)">📸 Save</button>
            <div class="slide-watermark">wrap2025.com</div>
        </div>''')

    # Slide 7: Talk Time Champions (Top 5 by duration)
    if d['top_duration']:
        duration_html = ''.join([
            f'<div class="rank-item"><span class="rank-num">{i}</span><span class="rank-name">{name}</span><span class="rank-count cyan">{format_duration_short(stats["duration"])}</span></div>'
            for i, (name, stats) in enumerate(d['top_duration'][:5], 1)
        ])
        slides.append(f'''
        <div class="slide orange-bg">
            <div class="slide-label">// TALK TIME CHAMPIONS</div>
            <div class="slide-text">who you spend the most time with</div>
            <div class="rank-list">{duration_html}</div>
            <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_talk_time.png', this)">📸 Save</button>
            <div class="slide-watermark">wrap2025.com</div>
        </div>''')

    # Slide 8: Longest Call
    if d['longest_call']:
        lc = d['longest_call']
        call_date = datetime.fromtimestamp(lc['timestamp']).strftime('%b %d')
        call_type = 'video' if lc['is_video'] else 'voice'
        slides.append(f'''
        <div class="slide purple-bg">
            <div class="slide-label">// MARATHON CALL</div>
            <div class="slide-icon">🏆</div>
            <div class="huge-name cyan">{lc['name']}</div>
            <div class="big-number yellow">{format_duration(lc['duration'])}</div>
            <div class="slide-text">longest single call</div>
            <div class="roast">{call_type} call on {call_date}</div>
            <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_longest_call.png', this)">📸 Save</button>
            <div class="slide-watermark">wrap2025.com</div>
        </div>''')

    # Slide 9: Contribution Graph (Call Activity)
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
                    call_text = "call" if count == 1 else "calls"
                    contrib_html += f'<div class="contrib-cell level-{level}" data-date="{formatted_date}" data-count="{count}" data-msg-text="{call_text}"></div>'
                else:
                    contrib_html += '<div class="contrib-cell empty"></div>'
            contrib_html += '</div>'
        contrib_html += '</div></div></div>'
        contrib_html += '<div class="contrib-legend"><span>Less</span><div class="contrib-cell level-0"></div><div class="contrib-cell level-1"></div><div class="contrib-cell level-2"></div><div class="contrib-cell level-3"></div><div class="contrib-cell level-4"></div><span>More</span></div>'
        contrib_html += '</div>'

        slides.append(f'''
        <div class="slide contrib-slide">
            <div class="slide-label">// CALL ACTIVITY</div>
            <div class="slide-text">your calling throughout the year</div>
            {contrib_html}
            <div class="contrib-stats">
                <div class="contrib-stat"><span class="contrib-stat-num">{d['avg_daily']}</span><span class="contrib-stat-lbl">avg/day</span></div>
                <div class="contrib-stat"><span class="contrib-stat-num">{d['busiest_month']}</span><span class="contrib-stat-lbl">busiest month</span></div>
                <div class="contrib-stat"><span class="contrib-stat-num">{d['quiet_days']}</span><span class="contrib-stat-lbl">quiet days</span></div>
            </div>
            <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_call_activity.png', this)">📸 Save</button>
            <div class="slide-watermark">wrap2025.com</div>
        </div>''')

    # Slide 10: Peak Hours
    slides.append(f'''
    <div class="slide">
        <div class="slide-label">// PEAK HOURS</div>
        <div class="slide-text">most active calling time</div>
        <div class="big-number gradient">{hr_str}</div>
        <div class="slide-text">on <span class="yellow">{d['peak_day']}s</span></div>
        <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_peak_hours.png', this)">📸 Save</button>
        <div class="slide-watermark">wrap2025.com</div>
    </div>''')

    # Slide 11: Busiest Day
    if d['busiest_day']:
        slides.append(f'''
        <div class="slide">
            <div class="slide-label">// BUSIEST DAY</div>
            <div class="slide-text">your most call-heavy day</div>
            <div class="big-number orange">{busiest_str}</div>
            <div class="slide-text"><span class="yellow">{busiest_count}</span> calls in one day</div>
            <div class="roast">someone was popular</div>
            <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_busiest_day.png', this)">📸 Save</button>
            <div class="slide-watermark">wrap2025.com</div>
        </div>''')

    # Slide 12: Night Owl
    if d['night_owls']:
        owl = d['night_owls'][0]
        slides.append(f'''
        <div class="slide">
            <div class="slide-label">// NIGHT OWL</div>
            <div class="slide-icon">🌙</div>
            <div class="huge-name cyan">{owl[0]}</div>
            <div class="big-number yellow">{owl[1]}</div>
            <div class="slide-text">late night calls (midnight-5am)</div>
            <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_night_owl.png', this)">📸 Save</button>
            <div class="slide-watermark">wrap2025.com</div>
        </div>''')

    # Slide 13: Missed Call King
    if d['missed_kings']:
        king = d['missed_kings'][0]
        slides.append(f'''
        <div class="slide red-bg">
            <div class="slide-label">// MISSED CALL KING</div>
            <div class="slide-icon">📵</div>
            <div class="huge-name">{king[0]}</div>
            <div class="big-number yellow">{king[1]}</div>
            <div class="slide-text">calls you missed from them</div>
            <div class="roast">maybe check your phone?</div>
            <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_missed_king.png', this)">📸 Save</button>
            <div class="slide-watermark">wrap2025.com</div>
        </div>''')

    # Slide: First Call of the Year
    if d['first_call']:
        fc = d['first_call']
        fc_date = datetime.fromtimestamp(fc['timestamp']).strftime('%b %d at %I:%M%p')
        fc_direction = "to" if fc['outgoing'] else "from"
        slides.append(f'''
        <div class="slide purple-bg">
            <div class="slide-label">// FIRST CALL OF {year}</div>
            <div class="slide-icon">🎉</div>
            <div class="slide-text">your year started with a call {fc_direction}</div>
            <div class="huge-name cyan">{fc['name']}</div>
            <div class="roast">{fc_date}</div>
            <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_first_call.png', this)">📸 Save</button>
            <div class="slide-watermark">wrap2025.com</div>
        </div>''')

    # Slide: Biggest Fan (who calls YOU most)
    if d['biggest_fans']:
        fan = d['biggest_fans'][0]
        slides.append(f'''
        <div class="slide gradient-bg">
            <div class="slide-label">// BIGGEST FAN</div>
            <div class="slide-text">who calls YOU the most</div>
            <div class="huge-name">{fan[0]}</div>
            <div class="big-number yellow">{fan[1]}</div>
            <div class="slide-text">incoming calls from them</div>
            <div class="roast">someone really wants to hear your voice</div>
            <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_biggest_fan.png', this)">📸 Save</button>
            <div class="slide-watermark">wrap2025.com</div>
        </div>''')

    # Slide: Longest Streak
    if d['longest_streak']:
        streak_name, streak_days = d['longest_streak']
        slides.append(f'''
        <div class="slide">
            <div class="slide-label">// LONGEST STREAK</div>
            <div class="slide-icon">🔥</div>
            <div class="huge-name cyan">{streak_name}</div>
            <div class="big-number yellow">{streak_days}</div>
            <div class="slide-text">consecutive days calling</div>
            <div class="roast">commitment level: high</div>
            <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_longest_streak.png', this)">📸 Save</button>
            <div class="slide-watermark">wrap2025.com</div>
        </div>''')

    # Slide: Weekday vs Weekend
    ww = d['weekday_weekend']
    weekday_pct = round(ww['weekday'] / max(stats['total'], 1) * 100)
    weekend_pct = 100 - weekday_pct
    slides.append(f'''
    <div class="slide">
        <div class="slide-label">// WORK-LIFE BALANCE</div>
        <div class="dual-stats">
            <div class="dual-stat">
                <span class="dual-icon">💼</span>
                <span class="dual-num cyan">{weekday_pct}%</span>
                <span class="dual-label">weekday calls</span>
            </div>
            <div class="dual-stat">
                <span class="dual-icon">🎉</span>
                <span class="dual-num yellow">{weekend_pct}%</span>
                <span class="dual-label">weekend calls</span>
            </div>
        </div>
        <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_weekday_weekend.png', this)">📸 Save</button>
        <div class="slide-watermark">wrap2025.com</div>
    </div>''')

    # Slide: Call Duration Buckets
    buckets = d['duration_buckets']
    total_answered = buckets['quick'] + buckets['normal'] + buckets['marathon']
    if total_answered > 0:
        slides.append(f'''
        <div class="slide">
            <div class="slide-label">// CALL STYLE</div>
            <div class="slide-text">how long are your calls?</div>
            <div class="duration-buckets">
                <div class="bucket">
                    <span class="bucket-icon">⚡</span>
                    <span class="bucket-num cyan">{buckets['quick']}</span>
                    <span class="bucket-label">quick<br>&lt;2 min</span>
                </div>
                <div class="bucket">
                    <span class="bucket-icon">💬</span>
                    <span class="bucket-num yellow">{buckets['normal']}</span>
                    <span class="bucket-label">normal<br>2-15 min</span>
                </div>
                <div class="bucket">
                    <span class="bucket-icon">🗣️</span>
                    <span class="bucket-num orange">{buckets['marathon']}</span>
                    <span class="bucket-label">marathon<br>15+ min</span>
                </div>
            </div>
            <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_call_style.png', this)">📸 Save</button>
            <div class="slide-watermark">wrap2025.com</div>
        </div>''')

    # Slide: Ghost Protocol (unreturned missed calls)
    if d['ghosts']:
        ghost_html = ''.join([
            f'<div class="rank-item"><span class="rank-num">👻</span><span class="rank-name">{name}</span><span class="rank-count red">{count}</span></div>'
            for name, count in d['ghosts'][:5]
        ])
        slides.append(f'''
        <div class="slide red-bg">
            <div class="slide-label">// GHOST PROTOCOL</div>
            <div class="slide-text">missed calls you never returned</div>
            <div class="rank-list">{ghost_html}</div>
            <div class="roast" style="margin-top:16px;">they're still waiting...</div>
            <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_ghost_protocol.png', this)">📸 Save</button>
            <div class="slide-watermark">wrap2025.com</div>
        </div>''')

    # Slide: Callback Speed
    if d['avg_callback_time']:
        cb_time = d['avg_callback_time']
        if cb_time < 5:
            cb_label = "LIGHTNING"
            cb_class = "green"
        elif cb_time < 30:
            cb_label = "RESPONSIVE"
            cb_class = "cyan"
        elif cb_time < 120:
            cb_label = "EVENTUALLY"
            cb_class = "yellow"
        else:
            cb_label = "WHENEVER"
            cb_class = "red"

        cb_display = f"{cb_time}m" if cb_time < 60 else f"{cb_time // 60}h {cb_time % 60}m"
        slides.append(f'''
        <div class="slide">
            <div class="slide-label">// CALLBACK SPEED</div>
            <div class="slide-text">avg time to return missed calls</div>
            <div class="big-number {cb_class}">{cb_display}</div>
            <div class="badge {cb_class}">{cb_label}</div>
            <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_callback_speed.png', this)">📸 Save</button>
            <div class="slide-watermark">wrap2025.com</div>
        </div>''')

    # Slide: Calling Personality
    ptype, proast = d['personality']
    slides.append(f'''
    <div class="slide purple-bg">
        <div class="slide-label">// DIAGNOSIS</div>
        <div class="slide-text">your calling personality</div>
        <div class="personality-type">{ptype}</div>
        <div class="roast">"{proast}"</div>
        <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_personality.png', this)">📸 Save</button>
        <div class="slide-watermark">wrap2025.com</div>
    </div>''')

    # Slide 17: Heating Up
    if d['heating_up']:
        heat_html = ''.join([
            f'<div class="rank-item"><span class="rank-num">🔥</span><span class="rank-name">{name}</span><span class="rank-count green">+{h2-h1}</span></div>'
            for name, h1, h2 in d['heating_up'][:5]
        ])
        slides.append(f'''
        <div class="slide">
            <div class="slide-label">// HEATING UP</div>
            <div class="slide-text">calling more in H2</div>
            <div class="rank-list">{heat_html}</div>
            <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_heating_up.png', this)">📸 Save</button>
            <div class="slide-watermark">wrap2025.com</div>
        </div>''')

    # Slide 18: Cooling Down
    if d['cooling_down']:
        cool_html = ''.join([
            f'<div class="rank-item"><span class="rank-num">🧊</span><span class="rank-name">{name}</span><span class="rank-count"><span class="green">{h1}</span> → <span class="red">{h2}</span></span></div>'
            for name, h1, h2 in d['cooling_down'][:5]
        ])
        slides.append(f'''
        <div class="slide">
            <div class="slide-label">// COOLING DOWN</div>
            <div class="slide-text">calling less in H2</div>
            <div class="rank-list">{cool_html}</div>
            <div class="roast" style="margin-top:16px;">H1 → H2</div>
            <button class="slide-save-btn" onclick="saveSlide(this.parentElement, 'wrapped_cooling_down.png', this)">📸 Save</button>
            <div class="slide-watermark">wrap2025.com</div>
        </div>''')

    # Final slide: Summary
    top3_names = ', '.join([name for name, _ in d['top_count'][:3]]) if d['top_count'] else "No contacts"

    # Platform breakdown for summary
    platform_summary = []
    for platform in ['Phone', 'FaceTime', 'WhatsApp']:
        if platform in d['platforms']:
            icon = '📱' if platform == 'Phone' else ('📹' if platform == 'FaceTime' else '💬')
            platform_summary.append(f'{icon} {d["platforms"][platform]["count"]:,}')
    platform_summary_html = ' '.join(platform_summary)

    slides.append(f'''
    <div class="slide summary-slide">
        <div class="summary-card" id="summaryCard">
            <div class="summary-header">
                <span class="summary-logo">📞</span>
                <span class="summary-title">CALLS WRAPPED {year}</span>
            </div>
            <div class="summary-hero">
                <div class="summary-big-stat">
                    <span class="summary-big-num">{stats['total']:,}</span>
                    <span class="summary-big-label">calls</span>
                </div>
            </div>
            <div class="summary-platform-split">
                {platform_summary_html}
            </div>
            <div class="summary-stats">
                <div class="summary-stat">
                    <span class="summary-stat-val">{d['unique_contacts']}</span>
                    <span class="summary-stat-lbl">people</span>
                </div>
                <div class="summary-stat">
                    <span class="summary-stat-val">{format_duration_short(stats['total_duration'])}</span>
                    <span class="summary-stat-lbl">talk time</span>
                </div>
                <div class="summary-stat">
                    <span class="summary-stat-val">{stats['answered']}</span>
                    <span class="summary-stat-lbl">answered</span>
                </div>
                <div class="summary-stat">
                    <span class="summary-stat-val">{stats['missed']}</span>
                    <span class="summary-stat-lbl">missed</span>
                </div>
            </div>
            <div class="summary-personality">
                <span class="summary-personality-type">{d['personality'][0]}</span>
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
        <div class="share-hint">share your call stats</div>
    </div>''')

    slides_html = ''.join(slides)
    num_slides = len(slides)

    favicon = "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>📞</text></svg>"

    html = f'''<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Calls Wrapped {year}</title>
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
    --phone: #4ade80;
    --facetime: #22d3ee;
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

.slide.intro {{ background:linear-gradient(145deg,#12121f 0%,#1a1f2f 50%,#0f2030 100%); }}
.slide.gradient-bg {{ background:linear-gradient(145deg,#12121f 0%,#1a2f1a 50%,#0d2f2f 100%); }}
.slide.purple-bg {{ background:linear-gradient(145deg,#12121f 0%,#1f1a3d 100%); }}
.slide.orange-bg {{ background:linear-gradient(145deg,#12121f 0%,#2d1f1a 100%); }}
.slide.red-bg {{ background:linear-gradient(145deg,#12121f 0%,#2d1a1a 100%); }}
.slide.summary-slide {{ background:linear-gradient(145deg,#1a2f1a 0%,#12121f 50%,#1a1a2e 100%); }}
.slide.contrib-slide {{ background:linear-gradient(145deg,#12121f 0%,#0d1f1a 100%); padding:24px 16px 80px; }}
.slide.platform-breakdown {{ background:linear-gradient(145deg,#12121f 0%,#1a2a1a 50%,#0d2f2f 100%); }}

.coverage-warning {{ font-size:12px; color:var(--yellow); margin-top:12px; opacity:0.8; }}

/* Contribution graph */
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
.contrib-cell.level-1 {{ background:rgba(34,211,238,0.25); }}
.contrib-cell.level-2 {{ background:rgba(34,211,238,0.45); }}
.contrib-cell.level-3 {{ background:rgba(34,211,238,0.70); }}
.contrib-cell.level-4 {{ background:var(--cyan); }}
.contrib-cell:not(.empty) {{ cursor:pointer; position:relative; }}
.contrib-tooltip {{ position:fixed; background:rgba(20,20,30,0.95); color:var(--text); padding:8px 12px; border-radius:6px; font-size:12px; pointer-events:none; z-index:1000; white-space:nowrap; border:1px solid rgba(255,255,255,0.1); box-shadow:0 4px 12px rgba(0,0,0,0.3); }}
.contrib-tooltip .tooltip-count {{ font-family:var(--font-mono); color:var(--cyan); font-weight:600; }}
.contrib-tooltip .tooltip-date {{ color:var(--muted); font-size:11px; margin-top:2px; }}
.contrib-legend {{ display:flex; align-items:center; justify-content:center; gap:4px; margin-top:12px; font-size:10px; color:var(--muted); }}
.contrib-legend .contrib-cell {{ cursor:default; }}
.contrib-stats {{ display:flex; gap:32px; margin-top:24px; justify-content:center; }}
.contrib-stat {{ display:flex; flex-direction:column; align-items:center; }}
.contrib-stat-num {{ font-family:var(--font-mono); font-size:28px; font-weight:600; color:var(--cyan); }}
.contrib-stat-lbl {{ font-size:11px; color:var(--muted); margin-top:4px; text-transform:uppercase; letter-spacing:0.5px; }}

/* Platform breakdown */
.platform-bars {{ display:flex; flex-direction:column; gap:16px; width:100%; max-width:500px; margin:32px 0; }}
.platform-bar {{ display:flex; align-items:center; gap:12px; padding:20px 24px; border-radius:16px; min-width:120px; transition:all 0.3s; }}
.platform-bar.phone {{ background:linear-gradient(90deg, rgba(74,222,128,0.25), rgba(74,222,128,0.1)); border:2px solid rgba(74,222,128,0.4); }}
.platform-bar.facetime {{ background:linear-gradient(90deg, rgba(34,211,238,0.25), rgba(34,211,238,0.1)); border:2px solid rgba(34,211,238,0.4); }}
.platform-bar.whatsapp {{ background:linear-gradient(90deg, rgba(37,211,102,0.25), rgba(37,211,102,0.1)); border:2px solid rgba(37,211,102,0.4); }}
.platform-icon {{ font-size:28px; flex-shrink:0; }}
.platform-name {{ font-size:16px; text-align:left; flex-shrink:0; min-width:80px; }}
.platform-pct {{ font-family:var(--font-mono); font-size:28px; font-weight:700; flex:1; text-align:center; }}
.platform-bar.phone .platform-pct {{ color:var(--phone); }}
.platform-bar.facetime .platform-pct {{ color:var(--facetime); }}
.platform-bar.whatsapp .platform-pct {{ color:var(--whatsapp); }}
.platform-count {{ font-family:var(--font-mono); font-size:16px; font-weight:500; opacity:0.8; flex-shrink:0; }}

/* Dual stats (video vs voice) */
.dual-stats {{ display:flex; gap:48px; margin:32px 0; }}
.dual-stat {{ display:flex; flex-direction:column; align-items:center; }}
.dual-icon {{ font-size:48px; margin-bottom:12px; }}
.dual-num {{ font-family:var(--font-mono); font-size:48px; font-weight:600; }}
.dual-label {{ font-size:14px; color:var(--muted); margin-top:8px; }}

/* Duration buckets */
.duration-buckets {{ display:flex; gap:32px; margin:32px 0; justify-content:center; }}
.bucket {{ display:flex; flex-direction:column; align-items:center; padding:20px; background:rgba(255,255,255,0.05); border-radius:16px; min-width:100px; }}
.bucket-icon {{ font-size:32px; margin-bottom:8px; }}
.bucket-num {{ font-family:var(--font-mono); font-size:36px; font-weight:600; }}
.bucket-label {{ font-size:12px; color:var(--muted); margin-top:8px; text-align:center; line-height:1.3; }}

/* Personality type */
.personality-type {{ font-family:var(--font-pixel); font-size:18px; font-weight:400; line-height:1.25; color:var(--purple); margin:24px 0; text-transform:uppercase; letter-spacing:0.5px; }}

.slide h1 {{ font-family:var(--font-pixel); font-size:36px; font-weight:400; line-height:1.2; margin:20px 0; }}
.slide-label {{ font-family:var(--font-pixel); font-size:12px; font-weight:400; color:var(--cyan); letter-spacing:0.5px; margin-bottom:16px; }}
.slide-icon {{ font-size:80px; margin-bottom:16px; }}
.slide-text {{ font-size:18px; color:var(--muted); margin:8px 0; }}
.subtitle {{ font-size:18px; color:var(--muted); margin-top:8px; }}
.subtitle2 {{ font-size:16px; color:var(--muted); margin-top:4px; opacity:0.7; }}

.big-number {{ font-family:var(--font-mono); font-size:80px; font-weight:500; line-height:1; letter-spacing:-2px; }}
.big-number.gradient {{ background:linear-gradient(90deg, var(--cyan), var(--green)); -webkit-background-clip:text; -webkit-text-fill-color:transparent; background-clip:text; }}
.pct {{ font-family:var(--font-body); font-size:48px; }}
.huge-name {{ font-family:var(--font-body); font-size:32px; font-weight:600; line-height:1.25; word-break:break-word; max-width:90%; margin:16px 0; }}
.roast {{ font-style:italic; color:var(--muted); font-size:18px; margin-top:16px; max-width:400px; }}

.green {{ color:var(--green); }}
.yellow {{ color:var(--yellow); }}
.red {{ color:var(--red); }}
.cyan {{ color:var(--cyan); }}
.pink {{ color:var(--pink); }}
.orange {{ color:var(--orange); }}
.purple {{ color:var(--purple); }}

.source-badge {{ font-size:16px; margin-left:4px; }}

.stat-grid {{ display:flex; gap:40px; margin-top:28px; }}
.stat-item {{ display:flex; flex-direction:column; align-items:center; }}
.stat-num {{ font-family:var(--font-mono); font-size:24px; font-weight:600; color:var(--cyan); }}
.stat-lbl {{ font-size:11px; color:var(--muted); margin-top:6px; text-transform:uppercase; letter-spacing:0.5px; }}

.rank-list {{ width:100%; max-width:420px; margin-top:20px; padding:0 16px 16px; }}
.rank-item {{ display:flex; align-items:center; padding:14px 0; border-bottom:1px solid rgba(255,255,255,0.1); gap:16px; }}
.rank-item:last-child {{ border-bottom:none; }}
.rank-item:first-child {{ background:linear-gradient(90deg, rgba(34,211,238,0.15) 0%, transparent 100%); padding:14px 12px; margin:0 -12px; border-radius:8px; border-bottom:none; }}
.rank-item:first-child .rank-name {{ font-weight:600; color:var(--cyan); }}
.rank-item:first-child .rank-count {{ font-size:20px; }}
.rank-num {{ font-family:var(--font-mono); font-size:20px; font-weight:600; color:var(--cyan); width:36px; text-align:center; }}
.rank-name {{ flex:1; font-size:16px; text-align:left; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.rank-count {{ font-family:var(--font-mono); font-size:18px; font-weight:600; color:var(--yellow); }}

.tap-hint {{ position:absolute; bottom:60px; font-size:16px; color:var(--muted); animation:pulse 2s infinite; }}
@keyframes pulse {{ 0%,100%{{opacity:0.4}} 50%{{opacity:1}} }}

/* Animations */
.slide .slide-label,
.slide .slide-text,
.slide .slide-icon,
.slide .big-number,
.slide .huge-name,
.slide .roast,
.slide .stat-grid,
.slide .rank-item,
.slide h1,
.slide .subtitle,
.slide .subtitle2,
.slide .summary-card,
.slide .contrib-graph,
.slide .contrib-stats,
.slide .platform-bars,
.slide .dual-stats,
.slide .duration-buckets,
.slide .personality-type {{
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
.slide.active .roast {{ animation: roastType 0.6s ease-out 0.4s forwards; }}
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
.slide.active .dual-stats {{ animation: textFade 0.5s ease-out 0.2s forwards; }}
.slide.active .duration-buckets {{ animation: textFade 0.5s ease-out 0.2s forwards; }}
.slide.active .personality-type {{ animation: glitchReveal 0.8s ease-out 0.15s forwards; }}

@keyframes glitchReveal {{ 0% {{ opacity: 0; transform: translateY(15px); filter: blur(4px); }} 50% {{ opacity: 0.8; transform: translateY(3px) skewX(-3deg); filter: blur(1px); }} 100% {{ opacity: 1; transform: translateY(0) skewX(0); filter: blur(0); }} }}

@keyframes textFade {{ 0% {{ opacity: 0; transform: translateY(15px); }} 100% {{ opacity: 1; transform: translateY(0); }} }}
@keyframes titleReveal {{ 0% {{ opacity: 0; transform: translateY(25px) scale(0.95); }} 70% {{ transform: translateY(-3px) scale(1.01); }} 100% {{ opacity: 1; transform: translateY(0) scale(1); }} }}
@keyframes iconPop {{ 0% {{ opacity: 0; transform: translateY(20px) scale(0.4) rotate(-15deg); }} 50% {{ transform: translateY(-8px) scale(1.15) rotate(8deg); }} 75% {{ transform: translateY(2px) scale(0.95) rotate(-3deg); }} 100% {{ opacity: 1; transform: translateY(0) scale(1) rotate(0); }} }}
@keyframes numberFlip {{ 0% {{ opacity: 0; transform: perspective(400px) rotateX(-60deg) translateY(20px); }} 60% {{ transform: perspective(400px) rotateX(10deg); }} 100% {{ opacity: 1; transform: perspective(400px) rotateX(0) translateY(0); }} }}
@keyframes nameBlur {{ 0% {{ opacity: 0; transform: translateY(20px); filter: blur(8px); }} 100% {{ opacity: 1; transform: translateY(0); filter: blur(0); }} }}
@keyframes roastType {{ 0% {{ opacity: 0; clip-path: inset(0 100% 0 0); }} 100% {{ opacity: 1; clip-path: inset(0 0 0 0); }} }}
@keyframes statFade {{ 0% {{ opacity: 0; transform: translateY(12px); }} 100% {{ opacity: 1; transform: translateY(0); }} }}
@keyframes rankSlide {{ 0% {{ opacity: 0; transform: translateX(-20px); }} 100% {{ opacity: 1; transform: translateX(0); }} }}
@keyframes cardRise {{ 0% {{ opacity: 0; transform: translateY(40px); }} 100% {{ opacity: 1; transform: translateY(0); }} }}
@keyframes graphReveal {{ 0% {{ opacity: 0; transform: translateY(30px) scale(0.95); }} 100% {{ opacity: 1; transform: translateY(0) scale(1); }} }}
@keyframes buttonSlide {{ 0% {{ opacity: 0; transform: translateY(15px); }} 100% {{ opacity: 1; transform: translateY(0); }} }}
@keyframes hintFade {{ 0% {{ opacity: 0; }} 100% {{ opacity: 1; }} }}

.summary-card {{
    background:linear-gradient(145deg,#1a1a2e 0%,#1a2f2f 100%);
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
.summary-big-num {{ font-family:var(--font-mono); font-size:56px; font-weight:600; background:linear-gradient(90deg, var(--cyan), var(--green)); -webkit-background-clip:text; -webkit-text-fill-color:transparent; background-clip:text; line-height:1; letter-spacing:-1px; }}
.summary-big-label {{ font-size:13px; color:var(--muted); text-transform:uppercase; letter-spacing:1px; margin-top:8px; }}
.summary-platform-split {{ display:flex; justify-content:center; gap:16px; margin:16px 0; padding:12px 0; border-top:1px solid rgba(255,255,255,0.05); border-bottom:1px solid rgba(255,255,255,0.05); font-family:var(--font-mono); font-size:14px; color:var(--cyan); }}
.summary-stats {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin:24px 0; padding:20px 0; border-top:1px solid rgba(255,255,255,0.1); border-bottom:1px solid rgba(255,255,255,0.1); }}
.summary-stat {{ display:flex; flex-direction:column; align-items:center; }}
.summary-stat-val {{ font-family:var(--font-mono); font-size:20px; font-weight:600; color:var(--cyan); }}
.summary-stat-lbl {{ font-size:9px; color:var(--muted); text-transform:uppercase; margin-top:4px; letter-spacing:0.3px; }}
.summary-personality {{ margin:16px 0; }}
.summary-personality-type {{ font-family:var(--font-pixel); font-size:11px; font-weight:400; color:var(--purple); text-transform:uppercase; letter-spacing:0.3px; }}
.summary-top3 {{ margin:16px 0; display:flex; flex-direction:column; gap:6px; }}
.summary-top3-label {{ font-size:10px; color:var(--muted); text-transform:uppercase; letter-spacing:0.5px; }}
.summary-top3-names {{ font-size:13px; color:var(--text); }}
.summary-footer {{ margin-top:20px; padding-top:16px; border-top:1px solid rgba(255,255,255,0.1); font-size:11px; color:var(--cyan); font-family:var(--font-pixel); font-weight:400; }}

.screenshot-btn {{
    display:flex; align-items:center; justify-content:center; gap:10px;
    font-family:var(--font-pixel); font-size:10px; font-weight:400; text-transform:uppercase; letter-spacing:0.3px;
    background:linear-gradient(90deg, var(--cyan), var(--green)); color:#000; border:none;
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
    background:rgba(34,211,238,0.15); color:var(--cyan); border:1px solid rgba(34,211,238,0.3);
    padding:10px 20px; border-radius:8px;
    cursor:pointer; transition:all 0.2s; opacity:0;
}}
.slide.active .slide-save-btn {{ opacity:1; }}
.slide-save-btn:hover {{ background:rgba(34,211,238,0.25); border-color:var(--cyan); }}

.slide.capturing, .slide.capturing * {{
    animation: none !important;
    opacity: 1 !important;
    transform: none !important;
    filter: none !important;
    clip-path: none !important;
}}
.slide-watermark {{
    position:absolute; bottom:24px; left:50%; transform:translateX(-50%);
    font-family:var(--font-pixel); font-size:10px; color:var(--cyan); opacity:0.6;
    display:none;
}}

.progress {{ position:fixed; bottom:24px; left:50%; transform:translateX(-50%); display:flex; gap:8px; z-index:100; }}
.dot {{ width:10px; height:10px; border-radius:50%; background:rgba(255,255,255,0.2); transition:all 0.3s; cursor:pointer; }}
.dot:hover {{ background:rgba(255,255,255,0.4); }}
.dot.active {{ background:var(--cyan); transform:scale(1.3); }}

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
    card.style.opacity = '1';
    card.style.transform = 'none';
    await new Promise(r => setTimeout(r, 100));
    try {{
        const canvas = await html2canvas(card, {{ backgroundColor:'#1a2f2f', scale:2, logging:false, useCORS:true }});
        const link = document.createElement('a');
        link.download = 'calls_wrapped_{year}_summary.png';
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
    parser = argparse.ArgumentParser(description='Call Wrapped 2025 - Your calling habits exposed')
    parser.add_argument('--output', '-o', default=None, help='Output HTML file path')
    parser.add_argument('--use-2024', action='store_true', help='Use 2024 data instead of 2025')
    args = parser.parse_args()

    print("\n" + "=" * 50)
    print("  CALLS WRAPPED 2025 | wrap2025.com")
    print("=" * 50 + "\n")

    print("[*] Checking access...")
    has_phone, has_whatsapp = check_access()

    platforms = []
    if has_phone:
        platforms.append("Phone/FaceTime")
        print(f"    ✓ Phone/FaceTime: {CALL_HISTORY_DB}")
    if has_whatsapp:
        platforms.append("WhatsApp")
        print(f"    ✓ WhatsApp: {WHATSAPP_CALLS_DB}")

    print(f"\n[*] Platforms: {' + '.join(platforms)}")

    print("[*] Loading contacts...")
    contacts = extract_contacts()
    print(f"    ✓ {len(contacts)} contacts loaded")

    # Determine year
    year = "2024" if args.use_2024 else "2025"
    ts_start = TS_2024_START if year == "2024" else TS_2025_START
    ts_end = TS_2024_END if year == "2024" else TS_2025_END
    ts_jun = TS_JUN_2024 if year == "2024" else TS_JUN_2025

    # Check data coverage
    earliest, latest = get_data_coverage(ts_start, ts_end, has_phone, has_whatsapp)
    if earliest:
        earliest_dt = datetime.fromtimestamp(earliest)
        print(f"    ℹ️  Earliest call data: {earliest_dt.strftime('%b %d, %Y')}")

    # Check if we have enough 2025 data
    if not args.use_2024:
        total_2025 = 0
        if has_phone:
            r = q_phone(f"SELECT COUNT(*) FROM ZCALLRECORD WHERE (ZDATE + {MAC_EPOCH}) > {ts_start}")
            total_2025 += r[0][0]
        if has_whatsapp:
            r = q_whatsapp(f"SELECT COUNT(*) FROM ZWAAGGREGATECALLEVENT WHERE (ZFIRSTDATE + {MAC_EPOCH}) > {ts_start}")
            total_2025 += r[0][0]

        if total_2025 < 10:
            print(f"    ⚠️  Only {total_2025} calls in 2025, using 2024")
            year = "2024"
            ts_start = TS_2024_START
            ts_end = TS_2024_END
            ts_jun = TS_JUN_2024
            earliest, latest = get_data_coverage(ts_start, ts_end, has_phone, has_whatsapp)

    output_file = args.output or f'call_wrapped_{year}.html'

    spinner = Spinner()

    # Analyze phone calls
    phone_calls = []
    if has_phone:
        print(f"[*] Analyzing Phone/FaceTime {year}...")
        spinner.start("Reading call history...")
        phone_calls = analyze_phone_calls(ts_start, ts_end, ts_jun, contacts)
        spinner.stop(f"{len(phone_calls)} phone/FaceTime calls analyzed")

    # Analyze WhatsApp calls
    whatsapp_calls = []
    if has_whatsapp:
        print(f"[*] Analyzing WhatsApp {year}...")
        spinner.start("Reading WhatsApp calls...")
        whatsapp_calls = analyze_whatsapp_calls(ts_start, ts_end, ts_jun, contacts)
        spinner.stop(f"{len(whatsapp_calls)} WhatsApp calls analyzed")

    print("[*] Combining and analyzing...")
    spinner.start("Crunching numbers...")
    data = analyze_calls(phone_calls, whatsapp_calls, ts_start, ts_end, ts_jun)
    spinner.stop(f"{data['stats']['total']} total calls processed")

    print("[*] Generating report...")
    spinner.start("Building your wrapped...")
    gen_html(data, output_file, year, has_phone, has_whatsapp, earliest, latest)
    spinner.stop(f"Saved to {output_file}")

    subprocess.run(['open', output_file])
    print("\n  Done! Click through your call wrapped.\n")


if __name__ == '__main__':
    main()
