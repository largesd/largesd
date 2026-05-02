# BDA Email Submission Format

This document is the single source of truth for the structured email body format used by the Blind Debate Adjudicator (BDA) email submission pipeline.

Both the **frontend** (`frontend/static/js/data_bridge.js`) and the **backend** (`backend/email_submission_parser.py`) MUST implement this format identically. Any divergence will cause parsing failures.

---

## Version: BDA Submission v1

### Header Block

The body must start with the magic header `BDA Submission v1` on its own line, followed by key-value headers:

```text
BDA Submission v1
Debate-ID: <debate_id>
Resolution: <resolution text>
Submission-ID: <uuid>
Submitted-At: <ISO 8601 timestamp>
Position: FOR | AGAINST
Topic-Area: <topic_id>
```

### Required Headers

| Header          | Description                              | Example                              |
|-----------------|------------------------------------------|--------------------------------------|
| `Debate-ID`     | The target debate identifier             | `deb_abc123`                         |
| `Resolution`    | The debate resolution text               | `AI should be regulated`             |
| `Submission-ID` | A UUID generated per submission          | `550e8400-e29b-41d4-a716-446655440000`|
| `Submitted-At`  | ISO 8601 timestamp in UTC                | `2026-04-30T01:00:00Z`               |
| `Position`      | Side of the debate                       | `FOR` or `AGAINST`                   |
| `Topic-Area`    | Topic identifier (lowercase alphanum)    | `t1`                                 |

### Body Sections

After a blank line following the headers, the body contains three sections:

```text

Facts:
<fact text>

Inference:
<inference text>

Counter-Arguments:
<optional counter-arguments text>
```

| Section            | Required | Description                        |
|--------------------|----------|------------------------------------|
| `Facts:`           | Yes      | Factual premises                   |
| `Inference:`       | Yes      | Conclusion / inference             |
| `Counter-Arguments:` | No     | Optional rebuttal or counter-args  |

### Full Example

```text
BDA Submission v1
Debate-ID: deb_abc123
Resolution: AI should be regulated
Submission-ID: 550e8400-e29b-41d4-a716-446655440000
Submitted-At: 2026-04-30T01:00:00Z
Position: FOR
Topic-Area: t1

Facts:
AI systems have caused measurable harm in hiring decisions.

Inference:
Therefore, AI should be regulated to prevent bias.

Counter-Arguments:
Regulation may stifle innovation.
```

---

## Version: BDA Submission v2 (Alternative)

An opt-in alternative using YAML frontmatter for unambiguous parsing.

```text
BDA Submission v2
---
Debate-ID: deb_abc123
Resolution: AI should be regulated
Submission-ID: 550e8400-e29b-41d4-a716-446655440000
Submitted-At: 2026-04-30T01:00:00Z
Position: FOR
Topic-Area: t1
---

Facts:
- Fact one
- Fact two

Inference:
The conclusion follows.

Counter-Arguments:
Optional rebuttal.
```

---

## Change Log

- **v1** — Initial format with newline-delimited headers.
- **v2** — Added YAML frontmatter alternative for robust parsing.
