#!/usr/bin/env python3
"""Platform health dashboard of palermo-sites (website-platform-kit decision 0008), modelled on the agentic platform
kit's: the platform's structure (operators -> the platform kit -> website systems -> their repositories and
environments, UAT then prod, and the services they share) drawn as a landscape, and each system's health in an
Octopus-style project group (a tile per environment), with its scorecard summary and links to its scorecard report
and health dashboard.

Inputs, all public: the registry snapshot in registry/ (pushed here by the kit's workflow registry on every change),
each system's published health.json (its own health dashboard), GitHub API reads of the system repositories (GH_TOKEN:
the run's own token) and each system's scorecard-data/latest.json. Writes --out: index.html, platform.json.
"""
import argparse, datetime as dt, html, json, os, time, urllib.error, urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo('America/New_York')
UTC = dt.timezone.utc
ROOT = Path(__file__).resolve().parent.parent


def get(url, token=None, timeout=20):
    h = {'User-Agent': 'platform-health-dashboard'}
    if token and url.startswith('https://api.github.com/'):
        h |= {'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None


def last_run(repo, wf, token, **q):
    qs = '&'.join(f'{k}={v}' for k, v in q.items())
    d = get(f'https://api.github.com/repos/{repo}/actions/workflows/{wf}/runs?per_page=5&{qs}', token) or {}
    rs = d.get('workflow_runs', [])
    done = next((r for r in rs if r['status'] == 'completed' and r['conclusion'] not in ('cancelled', 'skipped')), None)
    fly = next((r for r in rs if r['status'] != 'completed'), None)
    pick = lambda r: r and {'url': r['html_url'], 'sha': r['head_sha'][:7], 'status': r['status'], 'conclusion': r['conclusion'],
                            'at': r.get('run_started_at') or r['created_at'], 'title': r.get('display_title', '')}
    return pick(done), pick(fly)


def collect(token):
    now = dt.datetime.now(UTC)
    plat = json.loads((ROOT / 'registry' / 'platform.json').read_text())
    org = plat['githubOrg']
    systems = []
    for f in sorted((ROOT / 'registry' / 'systems').glob('*.json')):
        s = json.loads(f.read_text())
        if s.get('example'):
            continue
        slug = s['slug']
        repo = f'{org}/{slug}{plat["systemRepositorySuffix"]}'
        uat = plat.get('uat', {})
        uat_repo = f'{org}/{slug}{uat.get("repositorySuffix", "-site-uat")}'
        health_url = f'https://{org}.github.io/{slug}{plat["systemRepositorySuffix"]}-health/'
        meta = get(f'https://api.github.com/repos/{repo}', token)
        pages = get(f'https://api.github.com/repos/{repo}/pages', token) or {}
        health = get(health_url + 'health.json?' + str(int(time.time())))
        envs = []
        for name, label, wf, url, q in (('uat', 'UAT', uat.get('workflow', 'uat.yml'), s.get('uatUrl'), {}),
                                        ('prod', 'Prod', 'deploy.yml', pages.get('html_url'), {'branch': 'main'})):
            done, fly = last_run(repo, wf, token, **q) if meta else (None, None)
            h = next((e for e in (health or {}).get('environments', []) if e['name'] == name), None)
            envs.append({'name': name, 'label': label, 'url': url, 'workflow': wf, 'last': done, 'inFlight': fly,
                         'up': None if not h else h['state'] != 'down', 'state': h['state'] if h else None,
                         'uptime': h['uptime']['share'] if h else None, 'probe': h['probe'] if h else None})
        ci, ci_fly = last_run(repo, 'ci.yml', token, branch='main') if meta else (None, None)
        latest = get(f'https://raw.githubusercontent.com/{repo}/scorecard-data/latest.json')
        sc = None
        if latest:
            v = latest.get('views', {})
            sc = {'today': latest.get('today'), 'rolling7': v.get('rolling7'), 'rolling30': v.get('rolling30'),
                  'report': f'https://htmlpreview.github.io/?https://raw.githubusercontent.com/{repo}/scorecard-data/index.html',
                  'data': f'https://github.com/{repo}/tree/scorecard-data'}
        prod = envs[1]
        problems = []
        if not meta:
            problems.append('repository missing')
        if prod['up'] is False:
            problems.append('prod is down')
        if prod['last'] and prod['last']['conclusion'] != 'success':
            problems.append('last prod deploy failed')
        if envs[0]['up'] is False:
            problems.append('UAT is down')
        if envs[0]['last'] and envs[0]['last']['conclusion'] != 'success':
            problems.append('last UAT deploy failed')
        if ci and ci['conclusion'] != 'success':
            problems.append('main is not green')
        if not health:
            problems.append('health dashboard not read')
        state = 'production affected' if any(p.startswith(('prod', 'last prod')) for p in problems) else ('needs attention' if problems else 'as declared')
        systems.append({'slug': slug, 'name': s['name'], 'owner': s.get('owner'), 'framework': s.get('framework'), 'hosting': s.get('hosting'),
                        'repository': repo, 'repositoryUrl': f'https://github.com/{repo}', 'uatRepository': uat_repo,
                        'uatRepositoryUrl': f'https://github.com/{uat_repo}', 'domain': s.get('domain'), 'domainConnected': bool(pages.get('cname')),
                        'healthDashboard': health_url if health else None, 'healthRead': (health or {}).get('generated'),
                        'environments': envs, 'green': ci, 'ciInFlight': ci_fly, 'scorecard': sc, 'problems': problems, 'state': state,
                        'deploying': any(e['inFlight'] for e in envs)})
    return {'generated': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'platform': {'name': plat['name'], 'repository': plat['repository'], 'org': org,
                         'registryCommit': (ROOT / 'registry' / 'COMMIT').read_text().strip() if (ROOT / 'registry' / 'COMMIT').exists() else None},
            'systems': systems}


CSS = """
:root{--bg:#0f1b2d;--bar:#0b1524;--side:#122036;--card:#16263f;--line:#2a3d5c;--ink:#e6edf6;--muted:#93a4bd;--link:#7cc4ff;
--ok:#1f9d55;--ok-fill:#16794a;--warn:#e0a400;--crit:#e5484d;--crit-fill:#a52a2e;--cm-blue:#004B87;--cm-primary:#0085CA;--cm-sky:#24ABE1}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 Roboto,"Segoe UI",system-ui,sans-serif}
a{color:var(--link);text-decoration:none}a:hover{text-decoration:underline}
.top{display:flex;align-items:center;gap:16px;background:var(--bar);border-bottom:1px solid var(--line);padding:10px 20px}
.brand{font-weight:600;letter-spacing:.02em}.pill{border:1px solid var(--line);border-radius:4px;padding:3px 10px;color:var(--muted)}
main{max-width:1280px;margin:0 auto;padding:20px}h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:28px 0 10px}
.muted{color:var(--muted)}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin:16px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:10px 12px}.card .v{font-size:24px;font-weight:600}.card .k{color:var(--muted);font-size:12px}
.card.bad{border-color:var(--crit)}.card.good{border-color:var(--ok)}
.env{background:var(--card);border:1px solid var(--line);border-radius:6px;margin:12px 0;padding:14px 16px}
.env h3{margin:0 0 8px;font-size:15px;display:flex;gap:10px;align-items:center}
.state{font-size:12px;border-radius:10px;padding:1px 9px;font-weight:600}.state.healthy,.state.success{background:var(--ok-fill)}
.state.down,.state.failure{background:var(--crit-fill)}.state.degraded,.state.attention{background:#8a6500}.state.none{background:#33475f}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:10px}
.box{border:1px solid var(--line);border-radius:6px;padding:10px 12px;background:#132339}.box .t{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.04em}
.spark{display:flex;gap:2px;margin-top:6px}.spark i{display:block;width:6px;height:16px;border-radius:1px;background:var(--ok)}.spark i.x{background:var(--crit)}
table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--muted);font-weight:500;font-size:12px}
.tile{display:inline-flex;align-items:center;justify-content:center;width:18px;height:18px;border-radius:3px;font-size:12px;font-weight:700;margin-right:6px;vertical-align:-3px}
.tile.success{background:var(--ok-fill)}.tile.failure{background:var(--crit-fill)}.tile.run{background:var(--cm-sky)}.tile.none{background:#33475f}
.flow{display:flex;flex-wrap:wrap;align-items:stretch;gap:8px}.node{background:var(--cm-blue);border:1px solid var(--cm-primary);border-radius:6px;padding:8px 12px;min-width:150px}
.arrow{align-self:center;color:var(--muted)}footer{color:var(--muted);font-size:12px;margin:30px 0 10px}
"""
CSS += """
/* Zoomed into one system: its health dashboard over the whole screen, inside the platform's page (agentic kit 0017). */
.zoom{position:fixed;inset:0;z-index:10;display:grid;grid-template-rows:auto minmax(0,1fr);background:var(--bg);transform-origin:0 0;will-change:transform,opacity}
.zoom[hidden]{display:none}
.zoom-bar{display:flex;flex-wrap:wrap;align-items:center;gap:6px 18px;padding:8px clamp(12px,2vw,28px);background:var(--bar);font-size:.9rem}
.zoom-bar button{font:inherit;font-weight:500;padding:6px 14px;color:var(--link);background:transparent;border:1px solid var(--link);border-radius:6px;cursor:pointer}
.zoom-bar #zoom-name{font-weight:700;font-size:1.1rem}.zoom-bar a{margin-left:auto}
.zoom-stage{min-height:0}.zoom iframe{display:block;width:100%;height:100%;border:0;background:var(--bg)}
body[data-zoomed]{overflow:hidden}body[data-zoomed] .layout{visibility:hidden}
[data-zoom]{cursor:zoom-in}[data-zoom]:focus-visible{outline:2px solid var(--link);outline-offset:3px}

.layout{display:grid;grid-template-columns:190px 1fr}.side{background:var(--side);border-right:1px solid var(--line);min-height:100vh;padding:14px 0}
.side a{display:block;padding:6px 18px;color:var(--ink)}.side .h{padding:12px 18px 4px;color:var(--muted);font-size:11px;letter-spacing:.06em}
.land{background:#0c1727;border:1px solid var(--line);border-radius:6px;padding:14px}.row{display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:center}
.lbox{background:var(--cm-primary);border-radius:4px;padding:8px 14px;text-align:center;min-width:220px}.lbox.platform{background:var(--cm-blue);border:1px solid var(--cm-primary)}
.frame{border:1px dashed var(--cm-primary);border-radius:6px;padding:10px;margin:10px 0}.frame .ft{color:var(--muted);font-size:12px;margin-bottom:8px}
.sys{background:var(--cm-blue);border:2px solid var(--cm-primary);border-radius:4px;padding:8px 10px;width:230px;text-align:center;display:block;color:var(--ink)}
.sys.affected{border-color:var(--crit)}.sys.attention{border-color:#f08c00}.sys .tiles{display:flex;justify-content:center;gap:14px;margin:6px 0}
.sys .tiles div{font-size:11px;color:var(--muted)}.shared{background:var(--cm-blue);border-radius:4px;padding:8px 12px;min-width:200px;text-align:center}
.down{color:var(--muted);font-size:12px;text-align:center;margin:6px 0}.pg{background:var(--card);border:1px solid var(--line);border-radius:6px;margin:12px 0}
.pg .ph{display:flex;align-items:center;gap:10px;padding:10px 14px;border-bottom:1px solid var(--line)}.pg .pb{padding:10px 14px}
.legend{color:var(--muted);font-size:12px;margin-top:8px}
"""


def esc(v):
    return html.escape('' if v is None else str(v))


def ago(ts, now):
    if not ts:
        return 'never'
    sec = (now - dt.datetime.fromisoformat(ts.replace('Z', '+00:00'))).total_seconds()
    return f'{int(sec // 60)} min ago' if sec < 3600 else (f'{sec / 3600:.1f} h ago' if sec < 172800 else f'{sec / 86400:.0f} days ago')


def et(ts):
    return dt.datetime.fromisoformat(ts.replace('Z', '+00:00')).astimezone(ET).strftime('%b %d %H:%M ET') if ts else '–'


def tile(r, fly=None):
    if fly:
        return '<span class="tile run" title="deploying">↻</span>'
    if not r:
        return '<span class="tile none">·</span>'
    return '<span class="tile success">✓</span>' if r['conclusion'] == 'success' else '<span class="tile failure">✕</span>'


def num(v, digits=0):
    return '–' if v is None else (f'{v:.{digits}f}' if digits else str(v))


def page(d):
    now = dt.datetime.fromisoformat(d['generated'].replace('Z', '+00:00'))
    P, S = d['platform'], d['systems']
    cnt = lambda st: sum(1 for x in S if x['state'] == st)
    up_all = sum(1 for x in S for e in x['environments'] if e['up'])
    nodes = sum(len(x['environments']) for x in S)
    green = sum(1 for x in S if x['green'] and x['green']['conclusion'] == 'success')
    deliv7 = sum(((x['scorecard'] or {}).get('rolling7') or {}).get('counts', {}).get('itemsDelivered', 0) for x in S)
    today = sum((((x['scorecard'] or {}).get('today') or {}).get('counts') or {}).get('itemsDelivered', 0) for x in S)
    cards = [(len(S), 'website systems', ''), (cnt('production affected'), 'production affected', 'bad' if cnt('production affected') else ''),
             (cnt('needs attention'), 'need attention', 'bad' if cnt('needs attention') else ''), (f'{up_all}/{nodes}', 'environments up', 'good' if up_all == nodes else 'bad'),
             (f'{green}/{len(S)}', 'main green', 'good' if green == len(S) else 'bad'), (sum(1 for x in S if x['deploying']), 'deploying', ''),
             (today, 'delivered today', ''), (deliv7, 'delivered, last 7 days', '')]
    cls = {'production affected': 'affected', 'needs attention': 'attention'}
    h = ['<header class="top"><span class="brand">palermo-sites</span><span class="pill">' + esc(P['name']) + '</span></header><div class="layout"><nav class="side">',
         '<div class="h">PLATFORM</div><a href="#landscape">Landscape</a><a href="#systems">Systems</a><a href="#shared">Shared services</a>',
         '<div class="h">ELSEWHERE</div>' + ''.join(f'<a href="{esc(x["healthDashboard"])}">{esc(x["slug"])} health</a>' for x in S if x['healthDashboard'])
         + '<a href="platform.json">platform.json</a></nav><main>',
         f'<h1>Platform Health Dashboard</h1><p class="muted">Read <span data-ago="{esc(d["generated"])}">{esc(et(d["generated"]))}</span>. Website systems registered in '
         f'<code>{esc(P["repository"])}</code>; health from each system\'s health dashboard and GitHub; delivery from each site\'s scorecard.</p>',
         '<div class="cards">' + ''.join(f'<div class="card {c}"><div class="v">{esc(v)}</div><div class="k">{esc(k)}</div></div>' for v, k, c in cards) + '</div>']
    # landscape
    h.append('<h2 id="landscape">Landscape</h2><div class="land"><div class="row"><div class="lbox"><b>Operators</b><br><span style="font-size:12px">Jeffrey Palermo and agent sessions: register systems, review pull requests</span></div>'
             '<span class="muted">→ change the registry →</span>'
             f'<div class="lbox platform"><b>{esc(P["name"])}</b><br><span style="font-size:12px">website-platform-kit: registry, template, rules, decisions</span></div></div>'
             '<div class="down">↓ creates each system from the template; oversees it here</div>'
             f'<div class="frame"><div class="ft">GitHub organization <b>{esc(P["org"])}</b>: where the systems live and run</div><div class="row">')
    for x in S:
        tiles = ''.join(f'<div>{tile(e["last"], e["inFlight"])}<br>{esc(e["label"].upper())}</div>' for e in x['environments'])
        prod = x['environments'][-1]
        h.append(f'<a class="sys {cls.get(x["state"], "")}" href="{esc(x["healthDashboard"] or x["repositoryUrl"])}"{(" data-zoom=" + chr(34) + esc(x["slug"]) + chr(34)) if x["healthDashboard"] else ""}><b>{esc(x["slug"])}</b><br>'
                 f'<span style="font-size:12px">{esc(x["name"])}</span><br><span class="muted" style="font-size:11px">{esc(x["framework"] or "")} · GitHub Pages × 2</span>'
                 f'<div class="tiles">{tiles}</div><span style="font-size:12px">prod {esc(prod["last"]["sha"] if prod["last"] else "–")} · {esc(ago(prod["last"]["at"], now) if prod["last"] else "")}</span><br>'
                 f'<span style="font-size:12px;color:{"#ff8a8a" if x["problems"] else "#8fe0b0"}">{esc(x["state"])}</span></a>')
    h.append('</div></div><div class="down">↓ every system builds, deploys and is scored with</div><div class="row" id="shared">'
             '<div class="shared"><b>GitHub Actions</b><br><span style="font-size:12px">ci, uat, deploy, scorecard, health</span></div>'
             '<div class="shared"><b>GitHub Pages</b><br><span style="font-size:12px">prod in the site repository, UAT in &lt;slug&gt;-site-uat, health in &lt;slug&gt;-site-health</span></div>'
             '<div class="shared"><b>Scorecard (cmis)</b><br><span style="font-size:12px">daily delivery facts on each site\'s scorecard-data</span></div></div>'
             '<div class="legend"><span class="tile success">✓</span>last deploy succeeded <span class="tile failure">✕</span>failed <span class="tile run">↻</span>deploying <span class="tile none">·</span>none yet · A system\'s box zooms into its health dashboard.</div></div>')
    # systems
    h.append(f'<h2 id="systems">Systems</h2>')
    for x in S:
        sc = x['scorecard'] or {}
        t = sc.get('today') or {}
        r7 = sc.get('rolling7') or {}
        r30 = sc.get('rolling30') or {}
        rows = ''
        for e in x['environments']:
            l = e['last']
            rows += (f'<tr><td><b>{esc(e["label"])}</b><br><a href="{esc(e["url"])}">{esc((e["url"] or "").split("//")[-1])}</a></td>'
                     f'<td>{tile(l, e["inFlight"])}{("<a href=" + chr(34) + esc(l["url"]) + chr(34) + ">" + esc(l["sha"]) + "</a> · " + esc(et(l["at"]))) if l else "no deploy yet"}</td>'
                     f'<td>{"<span class=" + chr(34) + "state healthy" + chr(34) + ">up</span>" if e["up"] else ("<span class=" + chr(34) + "state down" + chr(34) + ">down</span>" if e["up"] is False else "<span class=muted>not read</span>")}'
                     f' {esc(e["probe"]["code"]) if e["probe"] else ""} {esc(num(e["probe"]["ms"]) + " ms") if e["probe"] and e["probe"].get("ms") is not None else ""}</td>'
                     f'<td>{esc(f"{e["uptime"] * 100:.2f}%" if e["uptime"] is not None else "–")}</td><td class="muted">{esc(e["workflow"])}</td></tr>')
        g = x['green']
        prodc = ((t.get('deployments') or {}).get('prod') or {}).get('count')
        h.append(f'<div class="pg"><div class="ph">{("<a data-zoom=" + chr(34) + esc(x["slug"]) + chr(34) + " href=" + chr(34) + esc(x["healthDashboard"]) + chr(34) + "><b>" + esc(x["slug"]) + "</b></a>") if x["healthDashboard"] else "<b>" + esc(x["slug"]) + "</b>"} <span class="muted">{esc(x["name"])} · owner {esc(x["owner"])}</span>'
                 f'<span class="state {"down" if x["state"] == "production affected" else ("degraded" if x["problems"] else "healthy")}" style="margin-left:auto">{esc(x["state"])}</span></div><div class="pb">'
                 f'<table><thead><tr><th>Environment</th><th>Last deploy</th><th>Node</th><th>Uptime 7 d</th><th>Workflow</th></tr></thead><tbody>{rows}</tbody></table>'
                 f'<div class="grid" style="margin-top:10px">'
                 f'<div class="box"><div class="t">Repositories</div><a href="{esc(x["repositoryUrl"])}">{esc(x["repository"])}</a> (site, prod Pages)<br><a href="{esc(x["uatRepositoryUrl"])}">{esc(x["uatRepository"])}</a> (UAT Pages)</div>'
                 f'<div class="box"><div class="t">Main is green</div>{tile(g)}{("<a href=" + chr(34) + esc(g["url"]) + chr(34) + ">" + esc(g["sha"]) + "</a> " + esc(g["conclusion"]) + " · " + esc(ago(g["at"], now))) if g else "no CI run"}</div>'
                 f'<div class="box"><div class="t">Domain</div>{esc(x["domain"] or "none")} <span class="state {"healthy" if x["domainConnected"] else "none"}">{"connected" if x["domainConnected"] else "not connected"}</span></div>'
                 f'<div class="box"><div class="t">Scorecard</div>today {num((t.get("counts") or {}).get("itemsDelivered"))} delivered, {num(prodc)} prod deploys<br>'
                 f'7 d {num((r7.get("counts") or {}).get("itemsDelivered"))} · 30 d {num((r30.get("counts") or {}).get("itemsDelivered"))} delivered, lead time {num((r30.get("delivery") or {}).get("mttdDays"), 3)} d<br>'
                 + (f'<a href="{esc(sc["report"])}">scorecard report</a> · <a href="{esc(sc["data"])}">data</a>' if sc else '<span class="muted">no scorecard data</span>') + '</div>'
                 f'<div class="box"><div class="t">Health dashboard</div>' + (f'<a href="{esc(x["healthDashboard"])}">{esc(x["healthDashboard"])}</a><br><span class="muted">read {esc(ago(x["healthRead"], now))}</span>' if x['healthDashboard'] else '<span class="muted">not published</span>') + '</div>'
                 '</div>' + (f'<p style="color:#ffb4b4">{esc("; ".join(x["problems"]))}</p>' if x['problems'] else '') + '</div></div>')
    h.append(f'<footer>Data: <a href="platform.json">platform.json</a>, written by workflow <code>platform</code> of palermo-sites/platform-health every 30 minutes and on every registry change'
             + (f' (registry at kit commit {esc(P["registryCommit"][:7])})' if P.get('registryCommit') else '') + '. Public data only; no secret. Kit decision 0008.</footer></main></div>')
    zs = {x['slug']: {'name': x['name'], 'url': x['healthDashboard']} for x in S if x['healthDashboard']}
    js = "document.querySelectorAll('[data-ago]').forEach(e=>{const m=Math.round((Date.now()-new Date(e.dataset.ago))/60000);e.textContent=m<1?'just now':m+' min ago'});"
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">'
            f'<title>Platform Health Dashboard – {esc(P["name"])}</title><style>{CSS}</style></head><body>{"".join(h)}'
            f'<div class="zoom" id="zoom" hidden><div class="zoom-bar"><button type="button" id="zoom-out">&larr; Platform</button><span id="zoom-name"></span>'
            f'<a id="zoom-own" target="_blank" rel="noopener">Open the dashboard itself</a></div><div class="zoom-stage" id="zoom-stage"></div></div>'
            f'<script type="application/json" id="zoom-systems">{json.dumps(zs).replace("<", "\\u003c")}</script><script>{js}{JS_ZOOM}</script></body></html>\n')


JS_ZOOM = r'''
// Zooming from the platform into one system and back out, as the agentic platform kit does (its decision 0017): a click
// on a system loads its health dashboard in a frame that starts exactly over what was clicked and grows to the whole
// screen while the platform scales up around that spot and fades. "Platform", Escape and Back zoom out.
(()=>{const byId=id=>document.getElementById(id);const still=()=>matchMedia('(prefers-reduced-motion: reduce)').matches;
const DURATION=800,EASING='cubic-bezier(.6, 0, .2, 1)';const SYS=JSON.parse(byId('zoom-systems').textContent);let open='';
const find=s=>SYS[s]||null;const wallEl=()=>document.querySelector('.layout');
function into(r){return `translate(${r.left}px, ${r.top}px) scale(${Math.max(r.width,1)/innerWidth}, ${Math.max(r.height,1)/innerHeight})`}
function origin(slug){const c=[...document.querySelectorAll(`[data-zoom="${CSS.escape(slug)}"]`)];return c.find(o=>{const r=o.getBoundingClientRect();return r.width>0&&r.bottom>0&&r.top<innerHeight})||c[0]||null}
function play(el,frames,back){if(still())return Promise.resolve();const a=el.animate(frames,{duration:DURATION,easing:EASING,direction:back?'reverse':'normal',fill:'both'});return a.finished.then(()=>a.cancel(),()=>{})}
function wallFrames(r){const w=wallEl().getBoundingClientRect();const sc=Math.min(12,Math.max(innerWidth/Math.max(r.width,1),innerHeight/Math.max(r.height,1)));const at=`${r.left+r.width/2-w.left}px ${r.top+r.height/2-w.top}px`;
return [{transformOrigin:at,transform:'scale(1)',opacity:1},{transformOrigin:at,transform:`scale(${sc})`,opacity:0}]}
async function zoomIn(slug,animate){const sy=find(slug);if(!sy||open===slug)return;const from=origin(slug);
const r=from?from.getBoundingClientRect():new DOMRect(innerWidth/2,innerHeight/2,1,1);const layer=byId('zoom');
byId('zoom-name').textContent=sy.name;byId('zoom-own').href=sy.url;
const f=document.createElement('iframe');f.id='zoom-frame';f.title=`The health dashboard of ${sy.name}`;f.referrerPolicy='no-referrer';f.src=sy.url;
byId('zoom-stage').replaceChildren(f);layer.hidden=false;open=slug;
if(animate)await Promise.all([play(layer,[{transform:into(r),opacity:.35},{transform:'none',opacity:1}],false),play(wallEl(),wallFrames(r),false)]);
document.body.dataset.zoomed=slug;byId('zoom-out').focus({preventScroll:true})}
async function zoomOut(animate){if(!open)return;const slug=open;const layer=byId('zoom');open='';delete document.body.dataset.zoomed;const from=origin(slug);
if(animate&&from){const r=from.getBoundingClientRect();await Promise.all([play(layer,[{transform:into(r),opacity:.35},{transform:'none',opacity:1}],true),play(wallEl(),wallFrames(r),true)])}
layer.hidden=true;byId('zoom-stage').replaceChildren();if(from)from.focus({preventScroll:true})}
function follow(animate){const slug=decodeURIComponent(location.hash.slice(1));if(slug&&find(slug))return zoomIn(slug,animate);return zoomOut(animate)}
function go(slug){history.pushState(null,'',`#${encodeURIComponent(slug)}`);zoomIn(slug,true)}
function out(){if(!open)return;history.pushState(null,'',location.pathname+location.search);zoomOut(true)}
document.addEventListener('click',e=>{if(e.defaultPrevented||e.button!==0||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;
const l=e.target.closest&&e.target.closest('[data-zoom]');if(!l||!find(l.dataset.zoom))return;e.preventDefault();go(l.dataset.zoom)});
document.addEventListener('keydown',e=>{if(e.key==='Escape')return out();
if(e.key===' '){const l=e.target.closest&&e.target.closest('[data-zoom]');if(l&&find(l.dataset.zoom)){e.preventDefault();go(l.dataset.zoom)}}});
byId('zoom-out').addEventListener('click',out);addEventListener('popstate',()=>follow(true));
// The health dashboard in the frame asks to go back to the platform with its own "Platform dashboard" link.
addEventListener('message',e=>{if(e.origin===location.origin&&e.data==='platform-zoom-out')out()});
follow(false)})();
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    data = collect(os.environ.get('GH_TOKEN'))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'platform.json').write_text(json.dumps(data, indent=2) + '\n')
    (out / 'index.html').write_text(page(data))
    (out / '.nojekyll').write_text('')
    print(f'{len(data["systems"])} system(s): ' + ', '.join(f'{s["slug"]} {s["state"]}' for s in data['systems']))


if __name__ == '__main__':
    main()
