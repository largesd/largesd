---
name: Blind Debate Adjudicator
description: Clarity-first institutional interface for evidence-grounded debate workflows.
colors:
  primary-accent: "oklch(0.44 0.1 248)"
  primary-accent-hover: "oklch(0.39 0.11 248)"
  neutral-surface-base: "oklch(0.96 0.009 248)"
  neutral-surface-raised: "oklch(0.985 0.006 248)"
  neutral-surface-muted: "oklch(0.93 0.012 248)"
  neutral-surface-accent: "oklch(0.92 0.028 248)"
  neutral-ink-strong: "oklch(0.26 0.028 248)"
  neutral-ink-default: "oklch(0.37 0.024 248)"
  neutral-ink-soft: "oklch(0.5 0.02 248)"
  neutral-line: "oklch(0.84 0.015 248)"
  neutral-line-strong: "oklch(0.74 0.02 248)"
  status-good: "oklch(0.55 0.14 155)"
  status-warn: "oklch(0.69 0.14 88)"
  status-bad: "oklch(0.57 0.17 28)"
typography:
  display:
    fontFamily: "\"Source Serif 4\", \"Literata\", serif"
    fontSize: "clamp(1.6rem, 1.3rem + 1vw, 2.1rem)"
    fontWeight: 700
    lineHeight: 1.2
  headline:
    fontFamily: "\"Source Serif 4\", \"Literata\", serif"
    fontSize: "1.44rem"
    fontWeight: 700
    lineHeight: 1.2
  title:
    fontFamily: "\"Source Serif 4\", \"Literata\", serif"
    fontSize: "1.15rem"
    fontWeight: 700
    lineHeight: 1.2
  body:
    fontFamily: "\"Public Sans\", \"Noto Sans\", sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.56
  label:
    fontFamily: "\"Public Sans\", \"Noto Sans\", sans-serif"
    fontSize: "0.75rem"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "0.04em"
rounded:
  sm: "10px"
  md: "14px"
  lg: "20px"
  pill: "999px"
spacing:
  "2xs": "4px"
  xs: "8px"
  sm: "12px"
  md: "16px"
  lg: "24px"
  xl: "32px"
  "2xl": "48px"
components:
  button-primary:
    backgroundColor: "{colors.neutral-surface-accent}"
    textColor: "{colors.primary-accent}"
    rounded: "{rounded.pill}"
    padding: "7px 12px"
  button-primary-hover:
    backgroundColor: "{colors.neutral-surface-accent}"
    textColor: "{colors.primary-accent-hover}"
    rounded: "{rounded.pill}"
    padding: "7px 12px"
  button-secondary:
    backgroundColor: "{colors.neutral-surface-muted}"
    textColor: "{colors.neutral-ink-default}"
    rounded: "{rounded.pill}"
    padding: "7px 12px"
  input-default:
    backgroundColor: "{colors.neutral-surface-raised}"
    textColor: "{colors.neutral-ink-strong}"
    rounded: "{rounded.sm}"
    padding: "10px 12px"
  nav-pill:
    backgroundColor: "{colors.neutral-surface-raised}"
    textColor: "{colors.neutral-ink-default}"
    rounded: "{rounded.pill}"
    padding: "7px 11px"
  card-surface:
    backgroundColor: "{colors.neutral-surface-raised}"
    textColor: "{colors.neutral-ink-default}"
    rounded: "{rounded.md}"
    padding: "{spacing.lg}"
  badge-neutral:
    backgroundColor: "{colors.neutral-surface-muted}"
    textColor: "{colors.neutral-ink-soft}"
    rounded: "{rounded.pill}"
    padding: "6px 10px"
  table-shell:
    backgroundColor: "{colors.neutral-surface-muted}"
    textColor: "{colors.neutral-ink-default}"
    rounded: "{rounded.sm}"
    padding: "10px"
---

# Design System: Blind Debate Adjudicator

## Overview

**Creative North Star: "The Civic Ledger"**

This system should feel like a public record interface for serious reasoning, not a social feed and not a startup landing page. Every surface should communicate that arguments are being processed in a procedural environment where clarity, traceability, and fairness are more important than visual spectacle.

Density is moderate and deliberate. Panels, tables, and status strips are grouped with consistent spacing and soft structural boundaries so users can track debate state without cognitive overload. Motion remains functional and restrained, with reduced-motion support as a first-class requirement.

The interface explicitly rejects "trend-heavy vibecoded aesthetics that prioritize novelty over clarity" and rejects "overly playful or entertainment-first visual language that weakens perceived procedural integrity." It is rigorous, calm, and institutional at every decision point.

**Key Characteristics:**
- Clear hierarchy built on serif headings and neutral sans body text.
- Tinted blue-gray neutrals that preserve composure while avoiding sterile grayscale.
- Semantic status colors used for evidence and verdict context, never as decorative noise.
- Flat-by-default surfaces with minimal shadow and strong border logic.
- Navigation and actions that emphasize next-step clarity over visual novelty.

## Colors

The palette is a disciplined blue-leaning neutral field with a single civic accent and tightly scoped semantic signals.

### Primary
- **Civic Signal Blue** (`oklch(0.44 0.1 248)`): Primary links, actionable controls, and active navigation states where users need a clear cue for the next action.

### Secondary
- **Resolution Green** (`oklch(0.55 0.14 155)`): Positive factual or procedural outcomes, including successful state chips and confirmation messaging.

### Tertiary
- **Caution Amber** (`oklch(0.69 0.14 88)`): Pending, uncertain, or no-verdict states where attention is needed without alarm.
- **Dispute Red** (`oklch(0.57 0.17 28)`): Validation failures, error states, and blocked outcomes that require correction.

### Neutral
- **Archive Base** (`oklch(0.96 0.009 248)`): Page background and broad layout canvas.
- **Paper Raised** (`oklch(0.985 0.006 248)`): Cards, panel surfaces, and floating containers.
- **Soft Partition** (`oklch(0.93 0.012 248)`): Input and table shells, compact chips, and grouped state blocks.
- **Accent Wash** (`oklch(0.92 0.028 248)`): Hover and active treatments for controlled emphasis.
- **Record Ink Strong** (`oklch(0.26 0.028 248)`): Headings and high-priority labels.
- **Record Ink Default** (`oklch(0.37 0.024 248)`): Body text and standard metadata.
- **Record Ink Soft** (`oklch(0.5 0.02 248)`): Secondary labels, helper copy, and supporting text.
- **Rule Line** (`oklch(0.84 0.015 248)`): Default separators and structural borders.
- **Rule Line Strong** (`oklch(0.74 0.02 248)`): Emphasized borders and high-salience separators.

**The Evidence-First Contrast Rule.** Accent and status colors are for state and meaning. If a color does not encode action, verdict, confidence, or system condition, it should be removed.

## Typography

**Display Font:** Source Serif 4 (fallback: Literata, serif)  
**Body Font:** Public Sans (fallback: Noto Sans, sans-serif)  
**Label/Mono Font:** Red Hat Mono (fallback: Menlo, Consolas, monospace)

**Character:** Serif headlines establish institutional authority, while the sans body keeps workflows approachable for mixed technical audiences. Mono appears only for identifiers, metrics, and machine-like metadata.

### Hierarchy
- **Display** (700, `clamp(1.6rem, 1.3rem + 1vw, 2.1rem)`, 1.2): Page-level headings and key section titles.
- **Headline** (700, `1.44rem`, 1.2): Major panel and section headers.
- **Title** (700, `1.15rem`, 1.2): Subsection titles and component-level heading rows.
- **Body** (400, `1rem`, 1.56): Core narrative and explanatory content, constrained to roughly 65 to 75 characters per line.
- **Label** (600, `0.75rem`, 1.2, `0.04em` letter-spacing): Form labels, metric labels, state tags, and compact UI metadata.

**The Ledger Hierarchy Rule.** Serif marks structure, sans carries explanation, mono marks evidence metadata. Do not swap these roles.

## Elevation

The system is structurally flat by default. Depth is conveyed through neutral tonal layering, border contrast, and spacing before shadow is introduced. Shadows appear only where a floating object must be interpreted as distinct from the document plane.

### Shadow Vocabulary
- **Surface Rest** (`0 1px 1px color-mix(in oklch, var(--ink-strong), white 92%)`): Subtle resting shadow on standard cards and panels.
- **Overlay Lift** (`0 8px 20px color-mix(in oklch, var(--ink-strong), white 75%)`): Tooltip and transient overlay separation.

**The Flat-By-Default Rule.** If a component is not floating above other content, it should rely on border and tone, not blur-heavy shadow.

## Components

### Buttons
- **Shape:** Pill geometry (`999px` radius) with compact vertical rhythm (`7px 12px` padding).
- **Primary:** Accent-tinted surface with blue action text, used for decisive workflow actions such as generating snapshots or submitting state changes.
- **Hover / Focus:** Hover increases contrast in border and text; focus-visible uses a 3px accent outline with 2px offset.
- **Secondary:** Muted neutral surface with strong border for non-destructive alternatives.

### Chips
- **Style:** Rounded metadata chips (`999px`) using muted surfaces and strong border control for compact state communication.
- **State:** Semantic variants (`good`, `warn`, `bad`) use softened status backgrounds and darker semantic text for readability.

### Cards / Containers
- **Corner Style:** Rounded medium corners (`14px`) for primary cards and panels, small corners (`10px`) for compact utility blocks.
- **Background:** Raised neutral surface for major content, muted surface for inner utility shells.
- **Shadow Strategy:** Hairline shadow at rest, with border-led structure as the dominant separator.
- **Internal Padding:** Standard container rhythm starts at `24px`, compressing to `16px` on smaller screens.

### Inputs / Fields
- **Style:** Neutral raised fill, strong border (`var(--line-strong)`), and compact rounded shape (`8px`) with `10px 12px` padding.
- **Focus:** Unified accent focus ring appears consistently across input, select, textarea, button, and summary controls.
- **Error / Disabled:** Error treatments use semantic red backgrounds and borders; disabled buttons reduce opacity and pointer affordance.

### Navigation
- **Global nav links:** Pill links with transparent default, muted hover fill, and accent-tinted active state.
- **Overflow nav:** Compact summary trigger with matching active treatment and a bordered raised dropdown menu.
- **Subnav links:** Block links with subtle neutral hover and accent-border active state for dense topic navigation contexts.

### Data Tables
- **Container:** Bordered muted shell (`10px` radius) with overflow support and optional scroll fade indicator.
- **Typography:** Small uppercase headers for column labels; body cells remain normal-case for readability.
- **Sticky context:** First column remains sticky in large tables to preserve row identity during horizontal scan.

## Do's and Don'ts

### Do:
- **Do** keep action hierarchy explicit: primary actions use accent treatment, secondary actions stay neutral, destructive/error actions stay semantic.
- **Do** use status colors only for meaning-bearing states (success, caution, error, verdict confidence context), not decoration.
- **Do** preserve the spacing scale (`4, 8, 12, 16, 24, 32, 48`) and card padding rhythm (`24px` desktop, `16px` compact).
- **Do** keep reduced-motion support active and test with `prefers-reduced-motion: reduce` before shipping.
- **Do** maintain strong keyboard-visible focus for every interactive control.

### Don't:
- **Don't** introduce Social-feed styling that introduces status signals or engagement gamification (likes, popularity badges, influencer-style profiles).
- **Don't** use Trend-heavy "vibecoded" aesthetics that prioritize novelty over clarity (neon glows, decorative gradients, excessive visual effects).
- **Don't** drift into Overly playful or entertainment-first visual language that weakens perceived procedural integrity.
- **Don't** replace semantic status meaning with purely decorative color usage.
- **Don't** remove border structure in favor of blur-heavy elevation or glass-like overlays.
