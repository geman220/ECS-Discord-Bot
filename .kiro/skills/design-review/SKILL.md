---
name: design-review
description: Post-deploy visual review of the live application. Catalog UX issues, run contrast checks, and log findings to the spec.
metadata:
  author: cascadian-gamers
  version: "1.0"
---
# Design Review

Post-deploy visual review of the live application. Catalog UX issues, run contrast checks, and log findings to the spec.

## When to Run

After any deploy that changes UI — CSS, templates, layout, components. Especially after CSS framework migrations.

## Process

### Phase 1: Visual Inspection

Check each major page/route in the deployed app:
1. Dashboard (if exists)
2. At least 2 data list pages (tables)
3. At least 1 form page
4. Any page with a new/changed component

For each page, evaluate:
- **Layout**: Does the page structure look correct? Sidebar, content area, spacing.
- **Color**: Are brand colors visible? Is there visual hierarchy or is it flat?
- **Typography**: Are headings distinct from body text? Labels readable?
- **Components**: Do cards, tables, badges, buttons render correctly?
- **Contrast**: Is text readable on its background? Are icons visible?
- **Responsiveness**: Does it work at mobile width? (resize browser)

### Phase 2: Contrast Verification

For any color pairing that looks questionable, run the contrast calculation:
```python
python3 -c "
def luminance(h):
    r,g,b = int(h[1:3],16)/255, int(h[3:5],16)/255, int(h[5:7],16)/255
    def a(c): return c/12.92 if c<=0.03928 else ((c+0.055)/1.055)**2.4
    return 0.2126*a(r)+0.7152*a(g)+0.0722*a(b)
def contrast(c1,c2):
    l1,l2=luminance(c1),luminance(c2)
    if l1<l2: l1,l2=l2,l1
    return (l1+0.05)/(l2+0.05)
print(f'{contrast(\"#TEXT\", \"#BG\"):.1f}:1')
"
```
WCAG AA minimums: 4.5:1 for normal text, 3:1 for large text and icons.

### Phase 3: Catalog Issues

Log each issue to the spec under a "Post-Deploy UX Issues" section:

```markdown
### Issue PN: {Short description}
**Severity**: 🔴 Must Fix / 🟡 Should Fix / 🟢 Nit
**Problem**: {What's wrong and why}
**Design**: {Proposed fix with specific CSS/HTML changes}
**Files**: {Which files to modify}
```

### Phase 4: Prioritize

Create a summary table sorted by severity:
| Issue | Description | Effort | Priority |
|-------|-------------|--------|----------|

Group related issues (e.g., "all tables need cards" is one issue, not 5).
Identify root causes — one fix may resolve multiple symptoms.

### Phase 5: Reassess

After identifying all issues, reassess with the `design-frontend` skill:
- Do any issues share a root cause?
- Would fixing one issue resolve others?
- Are any issues caused by a CSS bug rather than a design gap?
- Run contrast checks on proposed fix colors against ALL backgrounds they'll appear on.

## Rules

- Catalog issues in the spec, don't implement during review.
- Always run contrast calculations — don't eyeball color accessibility.
- Check colors on ALL backgrounds they appear on (sidebar, content, cards, badges).
- Group related issues — "tables need styling" is one issue, not per-table.
- Identify root causes before prioritizing fixes.
- Refer to the user as "The Brougham 22".
