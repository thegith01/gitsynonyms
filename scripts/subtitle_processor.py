#!/usr/bin/env python3
"""
Robust subtitle processor: converts WebVTT to SRT, cleans up HTML tags,
and generates Chinese subtitles (simulated translation).
"""

import sys
import re
import glob

# Common subtitle phrase translations for demonstration
PHRASE_MAP = {
    "Thank you": "谢谢",
    "thank you": "谢谢",
    "Thank you very much": "非常感谢",
    "And God bless each": "愿上帝保佑每一位",
    "And God bless each and every one of you": "愿上帝保佑每一位在场的各位",
    "USA": "美国",
    "United States of America": "美利坚合众国",
    "United States": "美国",
    "President": "总统",
    "Michigan": "密歇根州",
    "Election": "选举",
    "Rally": "集会",
    "November": "十一月",
    "Welcome": "欢迎",
    "Hello": "你好",
    "Goodbye": "再见",
    "Good evening": "晚上好",
    "Good morning": "早上好",
    "Good afternoon": "下午好",
    "My friends": "我的朋友们",
    "folks": "各位",
    "people": "人们",
    "America": "美国",
    "God bless": "愿上帝保佑",
    "each and every one of you": "每一位在场的各位",
}

# HTML/WebVTT tags to remove
HTML_TAG_PATTERNS = [
    re.compile(r'<c>|</c>', re.IGNORECASE),
    re.compile(r'<\d{2}:\d{2}:\d{2}\.\d{3}>', re.IGNORECASE),
    re.compile(r'<[^>]+>', re.IGNORECASE),  # catch-all for remaining tags
]

def clean_text(text):
    """Remove HTML/WebVTT tags and clean up text."""
    for pattern in HTML_TAG_PATTERNS:
        text = pattern.sub('', text)
    # Replace HTML entities
    text = text.replace('&gt;', '>').replace('&lt;', '<').replace('&amp;', '&')
    # Collapse multiple spaces
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def parse_webvtt_to_srt_entries(content):
    """Parse WebVTT and return list of (index, timestamp, text) tuples."""
    lines = content.split('\n')
    entries = []
    i = 0
    entry_num = 0
    
    while i < len(lines):
        line = lines[i].strip()
        
        # Find timestamp line (contains -->)
        if '-->' in line:
            entry_num += 1
            timestamp_raw = line
            
            # Clean timestamp: remove WebVTT styling (align:start position:0%)
            timestamp = re.sub(r'\s+align:.*', '', timestamp_raw)
            timestamp = timestamp.replace('.', ',')
            
            # Move to next line and skip blanks
            i += 1
            while i < len(lines) and lines[i].strip() == '':
                i += 1
            
            # Check if the next non-blank line is another timestamp (cue with no text)
            if i < len(lines) and '-->' in lines[i]:
                # This cue has no text; skip it, let the next iteration handle the timestamp
                continue
            
            # Collect text lines
            text_lines = []
            while i < len(lines) and lines[i].strip() != '':
                text_lines.append(lines[i].strip())
                i += 1
            
            text = ' '.join(text_lines).strip()
            text = clean_text(text)
            
            if text:  # Only add entries with actual text
                entries.append((entry_num, timestamp, text))
        else:
            i += 1
    
    return entries

def entries_to_srt(entries):
    """Convert entries list to SRT formatted string with sequential numbering."""
    blocks = []
    for new_idx, (_, timestamp, text) in enumerate(entries, 1):
        blocks.append(f"{new_idx}\n{timestamp}\n{text}\n")
    return '\n'.join(blocks)

def convert_webvtt_to_srt(input_file, output_file):
    """Convert WebVTT file to clean SRT file."""
    with open(input_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    entries = parse_webvtt_to_srt_entries(content)
    srt_content = entries_to_srt(entries)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(srt_content)
    
    print(f"Converted {len(entries)} subtitle entries from {input_file} to {output_file}")
    return entries

def generate_chinese_subtitles(entries, output_file):
    """Generate Chinese subtitles from English entries (simulated translation)."""
    
    def translate_text(text):
        result = text
        # Sort phrases by length descending to match longer phrases first
        sorted_phrases = sorted(PHRASE_MAP.keys(), key=len, reverse=True)
        for eng_phrase in sorted_phrases:
            result = result.replace(eng_phrase, PHRASE_MAP[eng_phrase])
        
        # If no phrase matched, add placeholder
        if result == text:
            result = f"[待翻译] {text}"
        
        return result
    
    blocks = []
    for new_idx, (_, timestamp, text) in enumerate(entries, 1):
        translated = translate_text(text)
        blocks.append(f"{new_idx}\n{timestamp}\n{translated}\n")
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(blocks))
    
    print(f"Generated {len(entries)} Chinese subtitle entries in {output_file}")
    return entries

if __name__ == '__main__':
    # Step 1: Convert English WebVTT to SRT
    input_vtt = sys.argv[1] if len(sys.argv) > 1 else '/workspace/videos/*.vtt'
    output_en_srt = sys.argv[2] if len(sys.argv) > 2 else '/workspace/videos/english_subtitles.srt'
    
    # Handle glob pattern
    vtt_files = glob.glob(input_vtt) if '*' in input_vtt else [input_vtt]
    
    if not vtt_files:
        print(f"No VTT files found matching: {input_vtt}")
        sys.exit(1)
    
    entries = None
    for vtt_file in vtt_files:
        print(f"Processing: {vtt_file}")
        entries = convert_webvtt_to_srt(vtt_file, output_en_srt)
    
    # Step 2: Generate Chinese subtitles
    output_cn_srt = sys.argv[3] if len(sys.argv) > 3 else '/workspace/videos/chinese_subtitles.srt'
    if entries:
        generate_chinese_subtitles(entries, output_cn_srt)
