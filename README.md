# Wrapped 2025

Your texting habits, exposed. A Spotify Wrapped-style visualization of your iMessage and WhatsApp history.

**[-> wrap2025.com](https://wrap2025.com)**

## Features

- **Total messages + words** – sent, received, per day
- **Inner circle** – top person + top 10 contacts (expandable)
- **Group chats** – overview + expandable top 10 groups on one slide
- **Personality** – diagnosis with starter %, reply time, sent/recv ratio, peak day/hour
- **Who texts first** – conversation initiator %
- **Response time** – how fast you reply
- **3AM bestie** – late night conversations (midnight–5am)
- **Busiest day** – your wildest day with top 10 people from that day (expandable)
- **Grind + marathon** – longest streak of daily texting and biggest single-day 1:1 marathon
- **Vibe check** – who’s heating up (H2 > H1) vs ghosted (dropped after June)
- **Biggest fan / Down bad** – who texts you most vs who you text most
- **Peak hours** – most active day/hour
- **Top emojis** – your most-used emoji lineup

## Installation

### iMessage Wrapped

#### 1. Download the script

```bash
curl -O https://raw.githubusercontent.com/kothari-nikunj/wrap2025/main/imessage_wrapped.py
```

#### 2. Grant Terminal access

The script needs to read your Messages database:

**System Settings -> Privacy & Security -> Full Disk Access -> Add Terminal**

(Or iTerm/Warp if you use those)

#### 3. Run it

```bash
python3 imessage_wrapped.py
```

---

### WhatsApp Wrapped

#### 1. Download the script

```bash
curl -O https://raw.githubusercontent.com/kothari-nikunj/wrap2025/main/whatsapp_wrapped.py
```

#### 2. Grant Terminal access

The script needs to read your WhatsApp database:

**System Settings -> Privacy & Security -> Full Disk Access -> Add Terminal**

(Or iTerm/Warp if you use those)

#### 3. Run it

```bash
python3 whatsapp_wrapped.py
```

---

### Combined Wrapped (iMessage + WhatsApp)

Merges stats from both platforms into a single unified report.

#### 1. Download the script

```bash
curl -O https://raw.githubusercontent.com/kothari-nikunj/wrap2025/main/combined_wrapped.py
```

#### 2. Grant Terminal access

The script needs to read both message databases:

**System Settings -> Privacy & Security -> Full Disk Access -> Add Terminal**

(Or iTerm/Warp if you use those)

#### 3. Run it

```bash
python3 combined_wrapped.py
```

The combined script will:
- Analyze both iMessage and WhatsApp data
- Use your AddressBook to reconcile contacts across platforms
- Merge top contacts, group chats, and all other stats
- Show a platform breakdown slide
- Work even if you only have one platform installed

---

Your wrapped will open in your browser automatically.

## Options

```bash
# Use 2024 data instead of 2025
python3 imessage_wrapped.py --use-2024
python3 whatsapp_wrapped.py --use-2024
python3 combined_wrapped.py --use-2024

# Custom output filename
python3 imessage_wrapped.py -o my_wrapped.html
python3 whatsapp_wrapped.py -o my_wrapped.html
python3 combined_wrapped.py -o my_wrapped.html
```

If you don't have enough 2025 messages yet, the script will automatically fall back to 2024.

## Privacy

**100% Local** - Your data never leaves your computer

- No servers, no uploads, no tracking
- No external dependencies (Python stdlib only)
- All analysis happens locally
- Output is a single HTML file

You can read the entire source code yourself.

## Requirements

- macOS (uses local message databases)
- Python 3 (pre-installed on macOS)
- Full Disk Access for Terminal
- For WhatsApp: WhatsApp desktop app installed with chat history

## How it works

### iMessage
The script reads your local `chat.db` (iMessage database) and `AddressBook` (Contacts) using SQLite queries.

### WhatsApp
The script reads your local `ChatStorage.sqlite` (WhatsApp database) using SQLite queries. WhatsApp stores contact names directly in the database.

### Combined
The combined script reads both databases and merges the data:
- Uses AddressBook contacts to reconcile names across platforms
- Combines message counts, response times, and other stats
- Merges top contacts (deduplicating by name when possible)
- Shows platform breakdown with message counts per platform
- Works even if only one platform is available

All scripts analyze your message patterns, resolve identifiers to contact names, and generate a self-contained HTML file with an interactive gallery.

## FAQ

**Q: Is this safe?**
A: Yes. The scripts only read local databases, write one HTML file, and make zero network requests. No data is sent anywhere.

**Q: Why do I need Full Disk Access?**
A: Apple protects message databases. Terminal needs permission to read them.

**Q: Can I run this on iOS?**
A: No, iOS doesn't allow access to message databases. macOS only.

**Q: The names are showing as phone numbers**
A: The script tries to match identifiers to contact names. Some may not resolve if the formatting differs.

**Q: Where is the WhatsApp database?**
A: WhatsApp stores its database at:
- `~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite` (current version)
- `~/Library/Containers/com.whatsapp/Data/Library/Application Support/WhatsApp/ChatStorage.sqlite` (older versions)

## Credits

Made by [@nikunj](https://x.com/nikunj)

Not affiliated with Apple, Meta, Spotify, or WhatsApp.

## License

MIT
