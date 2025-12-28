# People Wrapped 2025 - Design Document

## Overview

A standalone swipeable HTML report with AI-generated insights on your top 25 messaging relationships. Analyzes iMessage and WhatsApp conversations to surface themes, moments of joy/pain, relationship dynamics, and unfiltered observations.

## Data Sources

- **iMessage:** `~/Library/Messages/chat.db`
- **WhatsApp:** `~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite` (or alternate paths)
- **AddressBook:** `~/Library/Application Support/AddressBook/` (contacts + photos)

Graceful fallback if only one messaging platform exists.

## CLI Interface

```bash
# Default: 2025, top 25
python people_wrapped.py

# Options
python people_wrapped.py --year 2024
python people_wrapped.py --year both      # 2024 and 2025 comparison
python people_wrapped.py --top 10         # Only top 10 instead of 25
python people_wrapped.py -o my_report.html
```

## Extraction & Filtering

**What gets extracted per contact:**
- All messages from selected year(s)
- Timestamps, direction (sent/received), platform source

**Pre-filtering:**
- Strip media placeholders ("Image", "Attachment", "￼")
- Remove very short messages under 3 characters
- Remove link-only messages
- Keep reactions as metadata but don't analyze text
- Dedupe near-identical consecutive messages

**Contact ranking:**
- Combined message count across both platforms
- Only 1:1 conversations (no group chats)
- Exclude shortcodes (5-6 digit carrier alerts)

**Contact photos:**
- Extract from AddressBook Images folder
- Match via record ID
- Embed as base64 in HTML
- Fallback: Initial-based avatar ("JD" for John Doe)

## Analysis Approach

**Organic, not prescriptive.** Each person is different - the analysis reflects what's actually interesting about that specific relationship.

**Prompt guidance to Claude:**
> "You're reading a year of messages between me and [Name]. Tell me what stands out. What are the core themes? Any moments of real joy or real pain? What's the vibe of this relationship? Any extremes - the best, the worst, the weirdest? Be honest and specific. Don't force structure - just tell me what matters about this person and this year."

**Tone:** Facts + dynamics + brutally honest observations. Show everything, no content warnings.

**Year comparison (when --year both):** How the relationship changed between years.

## Terminal UX

Live feedback during execution:

```
People Wrapped 2025
═══════════════════════════════════════════════════

Checking database access...
  ✓ iMessage (chat.db)
  ✓ WhatsApp (ChatStorage.sqlite)
  ✓ AddressBook (12 contact photos found)

Scanning messages from 2025...
  Found 47,832 messages across 284 contacts

Identifying top 25 contacts...
  1. Sarah Chen — 4,291 messages
  2. Mom — 3,104 messages
  ...

═══════════════════════════════════════════════════

Analyzing relationships...

[1/25] Sarah Chen ████████████████████ analyzing...
       → 4,291 messages extracted (2,104 after filtering)
       → Ready for Claude analysis
```

## Workflow

Single-pass with Claude analyzing in real-time:

1. Script extracts messages, shows progress in terminal
2. Outputs each contact's filtered messages for Claude to analyze
3. Claude provides organic summaries in real-time
4. Script builds final HTML with summaries + embedded photos

## HTML Experience

**Structure:**
- Swipeable carousel (arrows + keyboard + touch)
- One person per slide, 25 slides ranked by message volume

**Each slide:**
- Contact photo (or initial fallback)
- Name
- Quick stats bar (message count, platforms, response time)
- AI-generated summary (main content, scrollable if long)
- Rank indicator ("3 of 25")

**Visual style:**
- Dark mode
- Clean typography for longer summaries
- Subtle slide transition animations
- Mobile-friendly

**Navigation:**
- Left/right arrow buttons
- Keyboard: arrow keys, j/k
- Touch: swipe gestures
- Optional: thumbnail strip for jumping

**Self-contained:**
- Single HTML file
- Photos embedded as base64
- No external dependencies
- Works offline

## Files

- `people_wrapped.py` - New standalone script
- Output: `people_wrapped_2025.html` (or custom via -o flag)

## Implementation Steps

1. Create `people_wrapped.py` with CLI argument parsing
2. Implement database access checking (iMessage, WhatsApp, AddressBook)
3. Implement contact extraction and photo retrieval
4. Implement message extraction with filtering
5. Implement top N contact ranking (combined across platforms)
6. Implement terminal progress UI
7. Implement message output for Claude analysis
8. Implement HTML template with swipeable carousel
9. Implement summary injection and final HTML generation
10. Test with --year 2024, --year 2025, --year both options
