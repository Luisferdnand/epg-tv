#!/usr/bin/env python3
"""Roda no Termux: monta config.json (alias, canais que precisam de EPG externo) a partir dos seus arquivos."""
import ast, json, os, re, sys
import gen
H = os.path.expanduser('~')
ADULT = re.compile(r'adult|xxx|porn|sex|erot|hentai|playboy|\+ ?18|18 ?\+', re.I)


def literais(path, nomes):
    out = {}
    for n in ast.parse(open(path, encoding='utf-8').read()).body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) and n.targets[0].id in nomes:
            v = n.value
            out[n.targets[0].id] = v.args[0].value if isinstance(v, ast.Call) else ast.literal_eval(v)
    return out


a = literais(H + '/.pd-epgx.py', {'ALIAS', 'rxe'})
ALIAS, rx = a['ALIAS'], re.compile(a['rxe'], re.I)
pares = literais(H + '/.pd-alias.py', {'pares'}).get('pares', {})
d = json.load(open(H + '/.pd-live.json', encoding='utf-8'))


def chave(n):
    r = gen.raw_norm(n)
    return ALIAS.get(r, r)


sem = [x for x in d if (not x.get('epg_channel_id') or rx.search(x.get('name') or '')) and not ADULT.search(x.get('name') or '')]
names = sorted({chave(x['name']) for x in sem if chave(x['name'])})
ids = re.search(r'IDS\s*=\s*(\[[^\]]*\])', open(H + '/gerar-epgsbt.js', encoding='utf-8').read())
ids = [str(i) for i in json.loads(ids.group(1).replace("'", '"'))] if ids else []
por_id = {str(x['stream_id']): x['name'] for x in d}
sbt = sorted({chave(por_id[i]) for i in ids if i in por_id})
cfg = {'alias': ALIAS, 'names': names, 'sbt': sbt, 'pares': {gen.raw_norm(k): gen.raw_norm(v) for k, v in pares.items()}}
json.dump(cfg, open('config.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
print('alias: %d | canais: %d | sbt: %s | pares: %d' % (len(ALIAS), len(names), sbt, len(cfg['pares'])))
