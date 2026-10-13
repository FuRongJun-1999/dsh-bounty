import sys, json
p, out = sys.argv[1], sys.argv[2]
d = json.load(open(p, encoding='utf-8'))
print('STUB', d.get('kind'))
open(out,'wb').write(bytes.fromhex('89504e470d0a1a0a'))
