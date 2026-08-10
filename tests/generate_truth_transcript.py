import os
import glob
import xml.etree.ElementTree as ET
import json

def generate_truth():
    base_dir = r"c:\Users\Davis\Downloads\meeting_mins_git\es2002\ES2002"
    words_dir = os.path.join(base_dir, "words")
    
    all_segments = []
    
    for xml_file in glob.glob(os.path.join(words_dir, "*.words.xml")):
        filename = os.path.basename(xml_file)
        parts = filename.split('.')
        meeting_id = parts[0]
        speaker = f"SPEAKER_{parts[1]}"
        
        # We add an offset for b, c, d to simulate one long meeting
        offset = 0
        if "b" in meeting_id: offset = 2000
        if "c" in meeting_id: offset = 4000
        if "d" in meeting_id: offset = 6000
        
        tree = ET.parse(xml_file)
        root = tree.getroot()
        
        current_text = []
        seg_start = None
        seg_end = None
        
        for w in root:
            if not w.tag.endswith('w'): continue
            if 'starttime' not in w.attrib or 'endtime' not in w.attrib: continue
            
            start = float(w.attrib['starttime']) + offset
            end = float(w.attrib['endtime']) + offset
            text = w.text if w.text else ""
            
            if not seg_start:
                seg_start = start
            
            if seg_end and (start - seg_end) > 2.0:
                # new segment
                if current_text:
                    all_segments.append({
                        "speaker": speaker,
                        "speakers": [speaker],
                        "start": seg_start,
                        "end": seg_end,
                        "duration": seg_end - seg_start,
                        "text": " ".join(current_text),
                        "overlap": False
                    })
                current_text = [text]
                seg_start = start
                seg_end = end
            else:
                current_text.append(text)
                seg_end = end
                
        if current_text:
            all_segments.append({
                "speaker": speaker,
                "speakers": [speaker],
                "start": seg_start,
                "end": seg_end,
                "duration": seg_end - seg_start,
                "text": " ".join(current_text),
                "overlap": False
            })

    # Sort all segments by start time
    all_segments.sort(key=lambda x: x['start'])
    
    final_json = {
        "metadata": {
            "meeting_id": "ES2002_truth",
            "segments": len(all_segments),
            "total_duration": sum(s['duration'] for s in all_segments)
        },
        "segments": all_segments
    }
    
    with open(r"c:\Users\Davis\Downloads\meeting_mins_git\es2002\ES2002_truth_transcript.json", "w") as f:
        json.dump(final_json, f, indent=2)
        
    print(f"Generated truth transcript with {len(all_segments)} segments.")

if __name__ == "__main__":
    generate_truth()
