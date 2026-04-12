import json
import sys

ast = json.load(open('ast_temp.json', encoding='utf-8'))
with open('debug_blocks.txt', 'w', encoding='utf-8') as out:
    for i in range(120, 280):
        c_repr = repr(ast['blocks'][i])[:200]
        out.write(f"{i}: {c_repr}\n")
