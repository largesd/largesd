# BDA Submission v3 Schema

## Format
Plain text email body with structured headers.

## Required Headers
- `Debate-ID`: target debate identifier
- `Resolution`: debate resolution text (for human readability; not part of hash)
- `Submission-ID`: UUID v4
- `Submitted-At`: ISO 8601 UTC timestamp
- `Expires-At`: ISO 8601 UTC timestamp (token expiration)
- `Submitter-Email`: email address of the authenticated user
- `Position`: `FOR` or `AGAINST`
- `Topic-Area`: topic identifier (lowercase alphanumeric)
- `Payload-Hash-Alg`: always `sha256`
- `Payload-Hash`: base64url-no-pad SHA-256 of canonical payload
- `Auth-Token`: signed JWT

## Body Sections
- `Facts:` (required)
- `Inference:` (required)
- `Counter-Arguments:` (optional)

## Canonical Payload (for hashing)
JSON object with these keys only, sorted, compact separators:
```json
{
  "debate_id": "...",
  "side": "FOR",
  "topic_id": "t1",
  "facts": "...",
  "inference": "...",
  "counter_arguments": "..."
}
```
The hash is computed as:
```
base64url_nopad(sha256(canonical_json_bytes))
```

## Important Notes
- Editing any field in the canonical payload after draft generation
  changes the hash and causes rejection.
- The `Resolution` header is NOT included in the hash.
- The `Auth-Token` JWT contains the same `payload_hash` claim.
- Mail clients may wrap long JWT lines. The parser tolerates safe
  continuation lines that start with whitespace.
