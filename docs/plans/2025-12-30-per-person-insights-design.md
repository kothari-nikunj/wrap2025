# Per-Person Relationship Insights Design

## Overview

Add three new relationship-focused insights that show per-person metrics instead of aggregate stats. These complement existing aggregate metrics (overall response time, overall starter %) with person-specific breakdowns.

## New Insights

### 1. YOUR PRIORITY LIST
**What it shows:** Top 5 people you reply to fastest (your average response time per person)

**SQL Pattern (iMessage):**
```sql
WITH chat_participants AS (
    SELECT chat_id, COUNT(*) as participant_count
    FROM chat_handle_join GROUP BY chat_id
),
one_on_one_messages AS (
    SELECT m.ROWID as msg_id
    FROM message m
    JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
    JOIN chat_participants cp ON cmj.chat_id = cp.chat_id
    WHERE cp.participant_count = 1
),
response_pairs AS (
    SELECT m.handle_id,
           (m.date/1000000000+978307200) ts,
           m.is_from_me,
           LAG(m.date/1000000000+978307200) OVER (PARTITION BY m.handle_id ORDER BY m.date) pt,
           LAG(m.is_from_me) OVER (PARTITION BY m.handle_id ORDER BY m.date) pf
    FROM message m
    WHERE (m.date/1000000000+978307200) > {ts_start}
    AND m.ROWID IN (SELECT msg_id FROM one_on_one_messages)
)
SELECT h.id, AVG(rp.ts - rp.pt)/60.0 as avg_resp_min, COUNT(*) as reply_count
FROM response_pairs rp
JOIN handle h ON rp.handle_id = h.ROWID
WHERE rp.is_from_me = 1 AND rp.pf = 0
AND (rp.ts - rp.pt) BETWEEN 10 AND 86400
GROUP BY h.id
HAVING reply_count >= 10
ORDER BY avg_resp_min ASC
LIMIT 5
```

**Display:** Ranked list showing person name and response time in minutes
**Slide label:** `// YOUR PRIORITY LIST`
**Subtext:** "who you reply to fastest"

### 2. WHO DROPS EVERYTHING
**What it shows:** Top 5 people who reply to YOU fastest

**SQL Pattern:** Same as above, but flip `is_from_me` logic:
```sql
-- Change WHERE clause:
WHERE rp.is_from_me = 0 AND rp.pf = 1
-- This finds: their message following your message
```

**Display:** Ranked list showing person name and their response time
**Slide label:** `// WHO DROPS EVERYTHING`
**Subtext:** "your fastest responders"

### 3. WHO ALWAYS TEXTS FIRST
**What it shows:** Per-person breakdown of who initiates conversations (after 4+ hour gap)

**SQL Pattern (iMessage):**
```sql
WITH chat_participants AS (...),
one_on_one_messages AS (...),
conversation_starts AS (
    SELECT m.handle_id, m.is_from_me,
           (m.date/1000000000+978307200) ts,
           LAG(m.date/1000000000+978307200) OVER (PARTITION BY m.handle_id ORDER BY m.date) prev_ts
    FROM message m
    WHERE (m.date/1000000000+978307200) > {ts_start}
    AND m.ROWID IN (SELECT msg_id FROM one_on_one_messages)
)
SELECT h.id,
       SUM(CASE WHEN cs.is_from_me = 1 THEN 1 ELSE 0 END) as you_started,
       SUM(CASE WHEN cs.is_from_me = 0 THEN 1 ELSE 0 END) as they_started,
       COUNT(*) as total_convos
FROM conversation_starts cs
JOIN handle h ON cs.handle_id = h.ROWID
WHERE cs.prev_ts IS NULL OR (cs.ts - cs.prev_ts) > 14400
GROUP BY h.id
HAVING total_convos >= 5
ORDER BY (you_started * 1.0 / total_convos) DESC
LIMIT 10
```

**Display:** Two sections:
- "You always reach out" (top 3 where you_started % > 70%)
- "They always find you" (top 3 where they_started % > 70%)

**Slide label:** `// WHO TEXTS FIRST`
**Subtext:** "per-person initiation breakdown"

## UI/Design Fixes

### Issue 1: Save Button Icon Missing
**Problem:** Camera emoji (📸) renders as rectangle on some systems
**Fix:** Replace emoji with SVG icon inline

```html
<button class="slide-save-btn" onclick="saveSlide(...)">
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
    <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
    <circle cx="8.5" cy="8.5" r="1.5"/>
    <polyline points="21 15 16 10 5 21"/>
  </svg>
  Save
</button>
```

### Issue 2: Save Button Overlaps Toggle Button
**Problem:** Both buttons positioned absolutely, causing overlap on slides with "Show full top 10"
**Fix:** Stack buttons properly with flexbox container at bottom

```css
.slide-buttons {
    position: absolute;
    bottom: 80px;
    left: 50%;
    transform: translateX(-50%);
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 12px;
}

.toggle-busiest-btn {
    /* Remove margin-bottom: 80px; */
    margin: 0;
}

.slide-save-btn {
    /* Remove position: absolute; bottom: 100px; */
    position: static;
    transform: none;
}
```

**HTML structure change:**
```html
<div class="slide-buttons">
    <button class="toggle-busiest-btn">Show full top 10</button>
    <button class="slide-save-btn">Save</button>
</div>
```

### Issue 3: Top 10 List Gets Cramped
**Problem:** When expanded to 10 items, list overflows or feels cramped
**Fix:**
1. Reduce font size slightly when expanded
2. Add max-height with scroll if needed
3. Smooth animation on expand

```css
.rank-list.expanded {
    max-height: 400px;
    overflow-y: auto;
}

.rank-list.expanded .rank-item {
    padding: 6px 0;  /* Tighter padding */
    font-size: 14px;  /* Slightly smaller */
}

.rank-list {
    transition: max-height 0.3s ease;
}
```

## Implementation Notes

- Add queries to `analyze()` function in each file
- Store results in `d['priority_list']`, `d['fast_responders']`, `d['initiation_breakdown']`
- Add slides after existing relationship slides (after "Down Bad")
- Apply same filters (exclude shortcodes, URN handles)
- Minimum threshold: 10 replies for response time, 5 conversations for initiation

## Files to Modify

1. `imessage_wrapped.py` - Add queries + slides + CSS fixes
2. `whatsapp_wrapped.py` - Add queries + slides + CSS fixes
3. `combined_wrapped.py` - Add queries + merge logic + slides + CSS fixes
