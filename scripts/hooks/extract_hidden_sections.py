import os
import re
import sys

def extract_hidden_sections(extracted_dir: str, template_dir: str):
    """
    Hooks for extracting hidden sections (like Conclusion and Accomplishments) 
    that were not formatted as Headings in Word and got mixed into chapters or references.
    """
    print(f"  [Hook] Running extract_hidden_sections on {extracted_dir}")
    
    ch_dir = os.path.join(extracted_dir, "chapters")
    if not os.path.exists(ch_dir):
        return
    
    misc_dir = os.path.join(template_dir, "misc")
    os.makedirs(misc_dir, exist_ok=True)

    # 1. Detect and extract '结语' from the last chapter
    ch_files = sorted([f for f in os.listdir(ch_dir) if f.endswith('.tex')])
    if ch_files:
        last_ch = os.path.join(ch_dir, ch_files[-1])
        with open(last_ch, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Look for standalone "结语"
        # The pattern might be "结语" preceded by a newline and followed by a newline, or at the end
        match = re.search(r'\n(结语)\s*\n(.*)', content, re.DOTALL)
        if match:
            # We found it!
            print(f"    -> Found '结语' in {ch_files[-1]}, splitting...")
            new_ch_content = content[:match.start()].strip() + '\n'
            conclusion_content = match.group(2).strip()
            
            with open(last_ch, 'w', encoding='utf-8') as f:
                f.write(new_ch_content)
                
            conclusion_tex = "\\chapter*{结语}\n\\addcontentsline{toc}{chapter}{结语}\n\\markboth{结语}{结语}\n\n" + conclusion_content + "\n"
            with open(os.path.join(misc_dir, 'conclusion.tex'), 'w', encoding='utf-8') as f:
                f.write(conclusion_tex)
                
    # 2. Detect and extract '攻读硕士学位期间取得的成果' from references_raw.txt
    refs_file = os.path.join(extracted_dir, "references_raw.txt")
    if os.path.exists(refs_file):
        with open(refs_file, 'r', encoding='utf-8') as f:
            refs_content = f.read()
        
        match = re.search(r'(攻读[博硕]士学位期间取得的成果)(.*)', refs_content, re.DOTALL)
        if match:
            print(f"    -> Found '攻读学位期间取得的成果' in references_raw.txt, splitting...")
            new_refs_content = refs_content[:match.start()].strip() + '\n'
            acc_content = match.group(2).strip()
            
            with open(refs_file, 'w', encoding='utf-8') as f:
                f.write(new_refs_content)
                
            # Process acc_content into enumerate
            items = re.split(r'\[\d+\]', acc_content)
            acc_tex = "\\chapter*{攻读硕士学位期间取得的成果}\n\\addcontentsline{toc}{chapter}{攻读硕士学位期间取得的成果}\n\\markboth{攻读硕士学位期间取得的成果}{攻读硕士学位期间取得的成果}\n\n\\begin{enumerate}[label={[\\arabic*]}, leftmargin=2.5em, itemsep=0.5em]\n"
            for item in items:
                item = item.strip()
                if item:
                    acc_tex += f"  \\item {item}\n"
            acc_tex += "\\end{enumerate}\n"
            
            with open(os.path.join(misc_dir, 'accomplishments.tex'), 'w', encoding='utf-8') as f:
                f.write(acc_tex)

if __name__ == "__main__":
    if len(sys.argv) > 2:
        extract_hidden_sections(sys.argv[1], sys.argv[2])
    else:
        print("Usage: python extract_hidden_sections.py <extracted_dir> <template_dir>")
