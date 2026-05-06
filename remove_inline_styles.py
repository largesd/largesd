#!/usr/bin/env python3
"""
Remove inline style="..." attributes from frontend HTML files
and replace them with CSS utility classes.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = REPO_ROOT / "frontend"

# Mapping of exact style values to CSS class names
STYLE_TO_CLASS = {
    'display:none;': 'hidden',
    'display: none;': 'hidden',
    'display:none': 'hidden',
    'box-shadow:none;margin:0': 'no-shadow-no-margin',
    'resize: none;': 'resize-none',
    'text-align:center;color:var(--muted)': 'text-center-muted',
    'text-align:center;color:var(--bad)': 'text-center-bad',
    'font-size:12px;color:var(--muted);margin-top:0': 'text-12-muted-mt-0',
    'font-size:12px;color:var(--muted)': 'text-12-muted',
    'color:var(--muted)': 'text-muted',
    'color:var(--good)': 'text-good',
    'color:var(--warn)': 'text-warn',
    'color:var(--bad)': 'text-bad',
    'margin-top:16px;': 'mt-16',
    'margin-top:12px;': 'mt-12',
    'margin-top:8px;': 'mt-8',
    'margin-top:6px;': 'mt-6',
    'margin-top:var(--space-sm)': 'mt-sm',
    'margin-top:0': 'mt-0',
    'margin-bottom:0': 'mb-0',
    'margin-bottom:var(--space-md);': 'mb-md',
    'margin-bottom:6px;': 'mb-6',
    'margin-bottom:16px;': 'mb-16',
    'margin:0': 'm-0',
    'margin:0;': 'm-0',
    'margin:4px 0;': 'my-4',
    'margin:4px 0;font-size:0.82rem;': 'my-4-text-82',
    'margin:8px 0 0 0;color:var(--muted)': 'mt-8-text-muted',
    'margin:8px 0 0 0;font-size:11px;flex-wrap:wrap;gap:6px;': 'mt-8-text-11-wrap-gap-6',
    'margin-top:8px;font-size:0.82rem;': 'mt-8-text-82',
    'margin-top:6px;font-size:0.82rem;': 'mt-6-text-82',
    'margin:4px 0 0 0;color:var(--ink-soft);': 'mt-4-text-ink-soft',
    'margin:4px 0 0 0;padding-left:16px;color:var(--ink-soft);': 'mt-4-pl-16-text-ink-soft',
    'margin:12px 0 4px 0;': 'my-12-4',
    'margin:10px 0 0 0': 'mt-10',
    'margin-top:0;margin-bottom:8px': 'mt-0-mb-8',
    'margin:0;font-size:0.84rem;': 'm-0-text-84',
    'margin:0 0 12px 0;': 'mb-12',
    'margin-bottom:0;font-size:0.88rem;color:var(--ink-default)': 'mb-0-text-88-ink-default',
    'margin-top:0;font-size:0.88rem;': 'mt-0-text-88',
    'margin-top:0;font-size:0.82rem;color:var(--ink-soft)': 'mt-0-text-82-ink-soft',
    'margin-top:0;font-size:14px': 'mt-0-text-14',
    'font-size:0.72rem': 'text-72',
    'font-size:0.72rem;': 'text-72',
    'font-size:1.05rem;': 'text-105',
    'font-size:13px': 'text-13',
    'font-size:0.84rem;color:var(--muted);': 'text-84-muted',
    'font-size:0.78rem;margin-top:4px;': 'text-78-mt-4',
    'font-weight:600': 'font-600',
    'flex-wrap:wrap;gap:var(--space-sm)': 'row-wrap-gap-sm',
    'flex-wrap:wrap;gap:var(--space-sm);margin-bottom:var(--space-md);': 'row-wrap-gap-sm-mb-md',
    'flex-wrap:wrap;gap:var(--space-sm);margin-top:var(--space-md);margin-bottom:var(--space-md);': 'row-wrap-gap-sm-my-md',
    'gap: var(--space-sm);': 'gap-sm',
    'gap:6px;flex-wrap:wrap': 'gap-6-wrap',
    'align-items:stretch;': 'items-stretch',
    'max-width:480px;': 'max-w-480',
    'padding:6px 10px;font-size:0.78rem': 'btn-compact',
    'white-space:pre-wrap;margin-bottom:0': 'pre-wrap-mb-0',
    'margin-top:12px;padding:12px;background:var(--bg);border:1px solid var(--border);border-radius:6px;font-size:0.8125rem;white-space:pre-wrap;': 'post-preview-pre',
    'flex-wrap:wrap;gap:6px;margin-top:4px': 'wrap-gap-6-mt-4',
    'display:block;margin-top:4px': 'block-mt-4',
    'display:block;margin-top:12px': 'block-mt-12',
    'background:var(--surface-muted);padding:10px;border-radius:8px;margin:8px 0;border:1px solid var(--line)': 'surface-box',
    'display:grid;gap:4px;margin-top:8px;': 'grid-gap-4-mt-8',
    'display:grid;grid-template-columns:80px 1fr auto;gap:8px;align-items:center;font-size:0.78rem;': 'grid-80-1fr-auto-gap-8-items-center-text-78',
    'height:14px;background:var(--surface-muted);border-radius:var(--radius-sm);overflow:hidden;border:1px solid var(--line);': 'bar-track',
    'margin-bottom: var(--space-md);': 'mb-md',
    'margin-top:var(--space-sm)': 'mt-sm',
    'margin:0;font-size:0.84rem;': 'm-0-text-84',
}

def replace_inline_styles(content: str) -> str:
    """Replace inline style attributes with CSS classes."""
    # Pattern to match style="..." where ... doesn't contain quotes
    pattern = re.compile(r'\s*style="([^"]*)"')

    def replacer(match):
        style_value = match.group(1)
        # Look for exact match in mapping
        cls = STYLE_TO_CLASS.get(style_value)
        if cls:
            return f' class="{cls}"'
        # Try some normalizations
        normalized = style_value.strip().rstrip(';')
        cls = STYLE_TO_CLASS.get(normalized)
        if cls:
            return f' class="{cls}"'
        # If not found, return unchanged so we can identify it
        return match.group(0)

    # We need to handle elements that already have a class attribute.
    # Process the whole content, but for each match check if the tag already has class="..."
    # This is complex with regex. Let's use a different approach: find all style attributes,
    # and for each, look backwards in the same tag for a class attribute.

    result = []
    last_end = 0
    for match in pattern.finditer(content):
        start = match.start()
        style_value = match.group(1)

        cls = STYLE_TO_CLASS.get(style_value)
        if not cls:
            normalized = style_value.strip().rstrip(';')
            cls = STYLE_TO_CLASS.get(normalized)

        if not cls:
            # Unknown style - skip this match (will be handled manually)
            continue

        # Find the start of the current tag
        tag_start = content.rfind('<', last_end, start)
        if tag_start == -1:
            continue

        # Get the tag content up to the style attribute
        tag_prefix = content[tag_start:start]

        # Check if the tag already has a class attribute
        class_match = re.search(r'\sclass="([^"]*)"', tag_prefix)

        if class_match:
            # Append to existing class
            existing_class = class_match.group(1)
            new_class = f'{existing_class} {cls}'
            # Replace the class attribute in the tag prefix
            new_tag_prefix = tag_prefix[:class_match.start()] + f' class="{new_class}"' + tag_prefix[class_match.end():]
            result.append(content[last_end:tag_start])
            result.append(new_tag_prefix)
            # Skip the style attribute
            last_end = match.end()
        else:
            # Add new class attribute
            result.append(content[last_end:start])
            result.append(f' class="{cls}"')
            last_end = match.end()

    result.append(content[last_end:])
    return ''.join(result)


def main():
    html_files = sorted(FRONTEND_DIR.glob('*.html'))
    unknown_styles = set()

    for html_file in html_files:
        content = html_file.read_text(encoding='utf-8')
        new_content = replace_inline_styles(content)

        # Check for remaining inline styles
        remaining = re.findall(r'style="([^"]*)"', new_content)
        for style in remaining:
            unknown_styles.add((html_file.name, style))

        if new_content != content:
            html_file.write_text(new_content, encoding='utf-8')
            print(f"Updated {html_file.name}")

    if unknown_styles:
        print("\n=== Remaining inline styles (need manual handling) ===")
        for fname, style in sorted(unknown_styles):
            print(f"  {fname}: style=\"{style}\"")
    else:
        print("\n✓ No remaining inline styles found.")


if __name__ == '__main__':
    main()
