#!/usr/bin/env python3
"""
Fix Unicode normalization in filenames and README links.
Renames NFD-normalized filenames (decomposed, e.g. е + ̈) to NFC (composed, e.g. ё).
This fixes broken GitHub Pages URLs containing %CC%88, %CC%86, etc.

Usage:
    python fix_unicode_filenames.py /path/to/transcripts/FedorKrasheninnikov
"""

import os
import sys
import unicodedata

def fix_folder(folder):
    if not os.path.isdir(folder):
        print(f"Error: folder '{folder}' not found")
        sys.exit(1)

    print(f"Scanning: {folder}")
    print("=" * 60)

    renamed = 0
    rename_map = {}  # old_name -> new_name, for fixing README links

    for filename in os.listdir(folder):
        if not filename.endswith('.md'):
            continue

        normalized = unicodedata.normalize('NFC', filename)

        if filename != normalized:
            old_path = os.path.join(folder, filename)
            new_path = os.path.join(folder, normalized)

            if os.path.exists(new_path):
                print(f"⚠ Skipping (target already exists): {normalized}")
                continue

            print(f"Renaming:")
            print(f"  FROM: {filename}")
            print(f"    TO: {normalized}")
            os.rename(old_path, new_path)
            rename_map[filename] = normalized
            renamed += 1
        else:
            pass  # already NFC, nothing to do

    if renamed == 0:
        print("No files needed renaming — all filenames are already NFC.")
    else:
        print(f"\nRenamed {renamed} file(s).")

    # Fix README.md links
    readme_path = os.path.join(folder, 'README.md')
    if not os.path.exists(readme_path):
        print("\nNo README.md found — skipping link fix.")
        return

    print(f"\nFixing links in README.md...")

    with open(readme_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Normalize the entire README content to NFC
    # This fixes any decomposed characters in link paths
    fixed_content = unicodedata.normalize('NFC', content)

    if content == fixed_content:
        print("README.md links already NFC — no changes needed.")
    else:
        with open(readme_path, 'w', encoding='utf-8') as f:
            f.write(fixed_content)
        print("✓ README.md updated.")

    print("\nDone!")
    print("\nVerify by checking for combining characters in README:")
    print("  python3 -c \"import unicodedata; [print(i, repr(c)) for i, c in enumerate(open('README.md').read()) if unicodedata.combining(c)]\"")

if __name__ == '__main__':
    folder = sys.argv[1] if len(sys.argv) > 1 else '.'
    fix_folder(folder)
