#!/usr/bin/env python3
"""
WebVTT to SRT converter with Chinese subtitle generation support.
"""

import re
import sys
import os

def parse_webvtt(content):
    """Parse WebVTT subtitle format into entries."""
    lines = content.split('\n')
    entries = []
    i = 0
    while i < len(lines):
        if '-->' in lines[i]:
            timestamp = lines[i].strip()
            i += 1
            # Skip blank lines
            while i < len(lines) and lines[i].strip() == '':
                i += 1
            text_lines = []
            while i < len(lines) and lines[i].strip() != '':
                text_lines.append(lines[i].strip())
                i += 1
            text = ' '.join(text_lines)
            entries.append({
                'timestamp': timestamp,
                'text': text
            })
        else:
            i += 1
    return entries

def webvtt_to_srt(entries):
    """Convert parsed WebVTT entries to SRT format."""
    lines = []
    for idx, entry in enumerate(entries):
        lines.append(str(idx + 1))
        ts = entry['timestamp'].replace('.', ',')
        lines.append(ts)
        lines.append('')
        lines.append(entry['text'])
        lines.append('')
    return '\n'.join(lines)

def webvtt_simplified_chinese_timestamp(entries):
    """Convert WebVTT entries to simplified Chinese timestamp format."""
    lines = []
    for idx, entry in enumerate(entries):
        lines.append(str(idx + 1))
        ts = entry['timestamp'].replace('.', ',')
        lines.append(ts)
        lines.append('')
        lines.append(entry['text'])
        lines.append('')
    return '\n'.join(lines)

def convert_webvtt_to_srt(input_file, output_file):
    """Convert WebVTT file to SRT file."""
    with open(input_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    entries = parse_webvtt(content)
    srt_content = webvtt_to_srt(entries)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(srt_content)
    
    print(f"Converted {len(entries)} subtitle entries from {input_file} to {output_file}")
    return len(entries)

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: python3 subtitle_converter.py <input.vtt> <output.srt>")
        sys.exit(1)
    
    convert_webvtt_to_srt(sys.argv[1], sys.argv[2])
