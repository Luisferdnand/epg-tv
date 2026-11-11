#!/usr/bin/env python3
"""Gera epg.json: programacao por NOME de canal (sem senha e sem stream_id).
Fontes: XMLTV publicos + grade do SBT (meuguia.tv). Roda no GitHub Actions."""
import calendar, datetime, gzip, html, io, json, os, re, sys, time, unicodedata, urllib.request
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
UA = {'User-Agent': 'Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 Chrome/120 Safari/537.36'}
ANTES = 3 * 3600          # guarda programas que acabaram ha ate 3 h
DEPOIS = 72 * 3600        # e os das proximas 72 h


def raw_norm(x):
    """Mesma regra do app Android (Epg.norm): nome do canal -> chave sem alias."""
    x = unicodedata.normalize('NFKD', (x or '').replace('\u00b3', '')).encode('ascii', 'ignore').decode()
    x = re.sub(r'\[[^\]]*\]|\([^)]*\)', '', x)
    x = re.sub(r'\b(FHD|UHD|HD|SD|4K|8K|H\.?265|HEVC|HDR)\b', '', x, flags=re.I)
    x = re.sub(r'[^a-z0-9]+', ' ', x.lower()).strip()
    x = re.sub(r'^(sao paulo sp|brasil|brazil) ', '', x)
    x = re.sub(r' (br|brazil|brasil)$', '', x)
    return x


def get(url, cap=80 * 1024 * 1024):
    h = dict(UA)
    if 'api.github.com' in url and os.environ.get('GITHUB_TOKEN'):
        h['Authorization'] = 'Bearer ' + os.environ['GITHUB_TOKEN']
    b = urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=90).read(cap + 1)
    if len(b) > cap:
        raise Exception('arquivo grande demais')
    return b


def ts(s):
    s = s.strip()
    base, off = s[:14], (s[14:].strip() or '+0000')
    dt = datetime.datetime.strptime(base, '%Y%m%d%H%M%S')
    sg = -1 if off[0] == '-' else 1
    try:
        o = int(off[1:3]) * 3600 + int(off[3:5]) * 60
    except Exception:
        o = 0
    return int((dt - datetime.datetime(1970, 1, 1)).total_seconds() - sg * o)


def parse(b, norm, now):
    if b[:2] == b'\x1f\x8b':
        b = gzip.decompress(b)
    nomes, prog = {}, {}
    for ev, el in ET.iterparse(io.BytesIO(b), events=('end',)):
        if el.tag == 'channel':
            i = el.get('id') or ''
            nomes.setdefault(norm(re.sub(r'\.[a-z]{2,3}\d?$', '', i)), i)
            for dn in el.findall('display-name'):
                if dn.text:
                    nomes.setdefault(norm(dn.text), i)
            el.clear()
        elif el.tag == 'programme':
            try:
                s, e = ts(el.get('start')), ts(el.get('stop'))
                if e > now - ANTES and s < now + DEPOIS:
                    t = el.find('title')
                    t = (t.text or '').strip() if t is not None else ''
                    if t:
                        prog.setdefault(el.get('channel'), []).append([s, e, t[:60]])
            except Exception:
                pass
            el.clear()
    return nomes, prog


def lista(repo):
    out = []
    try:
        for it in json.loads(get('https://api.github.com/repos/%s/contents' % repo)):
            if it['type'] == 'file' and it['name'].lower().endswith(('.xml', '.xml.gz')):
                out.append(it['download_url'])
    except Exception as e:
        print('nao listei', repo, str(e)[:60])
    return out


def fontes():
    return (['https://i.mjh.nz/PlutoTV/br.xml.gz'] + lista('limaalef/BrazilTVEPG')
            + ['https://epg.pw/xmltv/epg_BR.xml.gz', 'https://epgshare01.online/epgshare01/epg_ripper_BR1.xml.gz'])


def sbt(now):
    """Grade do SBT em meuguia.tv: [[inicio, fim, titulo], ...]."""
    h = get('https://meuguia.tv/programacao/canal/SBT').decode('utf-8', 'replace')
    h = re.sub(r'<!--[\s\S]*?-->', '', h)
    rx = re.compile(r'<li class="subheader devicepadding">[^<]*?(\d\d)/(\d\d)</li>'
                    r"|<div class='lileft time'>(\d\d):(\d\d)</div>[\s\S]*?<h2>([^<]*)</h2>")
    br = datetime.datetime.utcfromtimestamp(now - 3 * 3600)
    cy, cm = br.year, br.month
    d = mo = off = 0
    y = cy
    last = -1
    L = []
    for m in rx.finditer(h):
        if m.group(1):
            d, mo = int(m.group(1)), int(m.group(2))
            y = cy
            if mo < cm - 6:
                y = cy + 1
            elif mo > cm + 6:
                y = cy - 1
            off = 0
            last = -1
            continue
        if not d:
            continue
        hh, mi = int(m.group(3)), int(m.group(4))
        t = hh * 60 + mi
        if t < last:
            off += 1
        last = t
        L.append([calendar.timegm((y, mo, d, hh, mi, 0)) + (off * 24 + 3) * 3600, 0, html.unescape(m.group(5)).strip()])
    L.sort(key=lambda x: x[0])
    L = [x for i, x in enumerate(L) if not i or x[0] > L[i - 1][0]]
    for i in range(len(L)):
        L[i][1] = L[i + 1][0] if i < len(L) - 1 else L[i][0] + 3600
    if len(L) < 10:
        raise Exception('poucos programas: %d' % len(L))
    return L


def main():
    cfg = json.load(open(os.path.join(HERE, 'config.json'), encoding='utf-8'))
    ALIAS = cfg.get('alias', {})
    quero = set(cfg.get('names', []))
    now = int(time.time())

    def norm(x):
        r = raw_norm(x)
        return ALIAS.get(r, r)

    antigo = {}
    try:
        antigo = json.load(open(os.path.join(HERE, 'epg.json'), encoding='utf-8')).get('p', {})
    except Exception:
        pass

    cand = {}
    for i, u in enumerate(fontes()):
        try:
            nomes, prog = parse(get(u), norm, now)
        except Exception as ex:
            print('X', u.split('/')[-1][:28], str(ex)[:60])
            continue
        n = 0
        for k in quero:
            g = nomes.get(k)
            if g and g in prog:
                cand.setdefault(k, []).append(sorted(prog[g]))
                n += 1
        print('%-28s +%d canais' % (u.split('/')[-1][:28], n))

    p = {}
    for k, L in cand.items():
        best = L[0]
        if max(x[1] for x in best) < now + 6 * 3600:      # primeira fonte acaba cedo: pega a que vai mais longe
            best = max(L, key=lambda l: max(x[1] for x in l))
        p[k] = best

    sbt_keys = cfg.get('sbt', [])
    if sbt_keys:
        try:
            L = sbt(now)
            for k in sbt_keys:
                p[k] = L
            print('SBT: %d programas' % len(L))
        except Exception as e:
            print('SBT falhou (mantenho o anterior):', str(e)[:80])
            for k in sbt_keys:
                if k in antigo:
                    p[k] = [x for x in antigo[k] if x[1] > now - ANTES]

    if not p:
        print('nada gerado; epg.json anterior mantido')
        sys.exit(1)
    out = {'v': 1, 'g': now, 'al': ALIAS, 'pr': cfg.get('pares', {}), 'p': p}
    tmp = os.path.join(HERE, 'epg.json.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(out, f, separators=(',', ':'), ensure_ascii=False)
    os.replace(tmp, os.path.join(HERE, 'epg.json'))
    fim = max(x[1] for L in p.values() for x in L)
    print('epg.json: %d canais, %d KB, ate %s' % (len(p), os.path.getsize(os.path.join(HERE, 'epg.json')) // 1024,
                                                   datetime.datetime.utcfromtimestamp(fim - 3 * 3600).strftime('%d/%m %H:%M')))


if __name__ == '__main__':
    main()
