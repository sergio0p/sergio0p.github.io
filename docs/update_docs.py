#!/usr/bin/env python3
"""Publish the Research Atlas at https://sergio0p.github.io/docs/.

What it does, each run:
  1. Clone the public sergio0p.github.io repo into a temp dir.
  2. Copy every HTML artifact from  <SOURCE>/<project>/docs/*.html
     into the repo at  docs/<project>/  (HTML only — no .md/.jl/.wls/etc.).
     Stale copies (renamed/deleted at the source) are pruned.
  3. Regenerate docs/index.html — the atlas — with same-origin links.
  4. Commit + push (skipped if nothing changed).

Only rendered HTML ever leaves the private project repos.

Usage:
  python3 update_docs.py                 # sync + push
  python3 update_docs.py --dry-run       # build into the temp clone, don't push (keeps it for inspection)
  python3 update_docs.py --source PATH   # override research dir (default ~/Dropbox/Research)
"""
import argparse
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

GH_USER = "sergio0p"
REPO = "sergio0p.github.io"
DEFAULT_SOURCE = os.path.expanduser("~/Dropbox/Research")
EXCLUDE = {"doc-map.html", "index.html", "todo.html"}  # compared against name.lower()

# Program metadata. Taglines are written from the actual artifact titles, not invented.
PROJECTS = [
    {"dir": "1-Cartan", "code": "Cartan", "glyph": "∧",
     "tag": "Cartan program — no published artifacts yet."},
    {"dir": "2-ElimContest", "code": "Elimination Contest", "glyph": "Π₂",
     "tag": "Two-round elimination contests: equilibrium support, the tropical structure of the round-2 payoff, and the round-1 signaling obstruction."},
    {"dir": "3-Tortoise", "code": "Tortoise", "glyph": "σ",
     "tag": "Dynamic contests with a terminal aggregate — the σ(m,n) comb, chain monotonicity, and the competitive limit."},
    {"dir": "4-WinProb", "code": "Win Probability", "glyph": "W·G",
     "tag": "Inverting the win-probability map W↦G — Lorentzian signature, properness, and coupling recursions."},
    {"dir": "5-Meritocracy", "code": "Meritocracy", "glyph": "A",
     "tag": "Handicaps and quotas in all-pay contests — equilibrium-density FOCs and the Parreiras–Rubinchik program."},
]

TITLE_RE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def sh(args, cwd=None):
    """Run a command, raising on failure, returning stdout."""
    r = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    if r.returncode != 0:
        sys.exit(f"[update_docs] command failed: {' '.join(args)}\n{r.stderr.strip()}")
    return r.stdout


def is_excluded(name):
    low = name.lower()
    return low in EXCLUDE or low.endswith("_old.html")


def title_of(path, fallback):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            m = TITLE_RE.search(fh.read(8192))
        if m:
            t = html.unescape(re.sub(r"\s+", " ", m.group(1)).strip())
            if t:
                return t
    except OSError:
        pass
    return fallback


def esc(s):
    return html.escape(s, quote=True)


def collect(source):
    """Return [(project, [artifact...])]; artifact keys: file, title, url, mtime, date."""
    data = []
    for p in PROJECTS:
        docs = os.path.join(source, p["dir"], "docs")
        arts = []
        if os.path.isdir(docs):
            for name in os.listdir(docs):
                if not name.endswith(".html") or is_excluded(name):
                    continue
                path = os.path.join(docs, name)
                mtime = os.path.getmtime(path)
                arts.append({
                    "file": name,
                    "src": path,
                    "title": title_of(path, name),
                    "url": f"{p['dir']}/{name}",  # same-origin, relative to docs/index.html
                    "mtime": mtime,
                    "date": time.strftime("%Y-%m-%d", time.localtime(mtime)),
                })
        arts.sort(key=lambda a: a["mtime"], reverse=True)
        data.append((p, arts))
    return data


def sync_files(repo_docs, data):
    """Copy artifact HTML into repo docs/<project>/, pruning stale files. Returns count copied."""
    copied = 0
    for p, arts in data:
        dest_dir = os.path.join(repo_docs, p["dir"])
        # prune: drop the whole per-project dir, then recreate from the current source set
        if os.path.isdir(dest_dir):
            shutil.rmtree(dest_dir)
        if arts:
            os.makedirs(dest_dir, exist_ok=True)
            for a in arts:
                shutil.copy2(a["src"], os.path.join(dest_dir, a["file"]))
                copied += 1
    return copied


def render(data):
    total = sum(len(a) for _, a in data)
    live = sum(1 for _, a in data if a)
    plates = []
    for i, (p, arts) in enumerate(data, start=1):
        num = f"{i:02d}"
        count = len(arts)
        items = "\n".join(
            f'''        <li class="art" data-hay="{esc((a["title"]+" "+a["file"]).lower())}">
          <a href="{esc(a["url"])}">
            <span class="art-title">{esc(a["title"])}</span>
            <span class="art-date" title="{esc(a["file"])}">{esc(a["date"])}</span>
          </a>
        </li>''' for a in arts
        )
        if not arts:
            body = '<p class="empty">No published artifacts yet.</p>'
            open_attr = ""
        else:
            body = f'      <ul class="arts">\n{items}\n      </ul>'
            open_attr = " open" if count <= 14 else ""
        count_label = f"{count} artifact" + ("" if count == 1 else "s")
        plates.append(f'''  <details class="plate"{open_attr} data-code="{esc(p['code'].lower())}">
    <summary>
      <span class="plate-num">{num}</span>
      <span class="plate-head">
        <span class="plate-code">{esc(p['code'])}</span>
        <span class="plate-tag">{esc(p['tag'])}</span>
      </span>
      <span class="plate-count" data-count="{count}">{count_label}</span>
      <span class="plate-glyph" aria-hidden="true">{esc(p['glyph'])}</span>
    </summary>
{body}
  </details>''')
    plates_html = "\n".join(plates)
    return TEMPLATE.format(GH_USER=GH_USER, total=total, live=live, plates_html=plates_html)


def main():
    ap = argparse.ArgumentParser(description="Publish the Research Atlas to sergio0p.github.io/docs/")
    ap.add_argument("--source", default=DEFAULT_SOURCE, help="research dir (default ~/Dropbox/Research)")
    ap.add_argument("--dry-run", action="store_true", help="build but do not push; keep the temp clone")
    args = ap.parse_args()

    source = os.path.expanduser(args.source)
    if not os.path.isdir(source):
        sys.exit(f"[update_docs] source not found: {source}")

    data = collect(source)
    total = sum(len(a) for _, a in data)
    print(f"[update_docs] found {total} HTML artifacts in {source}")

    work = tempfile.mkdtemp(prefix="atlas-")
    repo = os.path.join(work, REPO)
    print(f"[update_docs] cloning {GH_USER}/{REPO} ...")
    sh(["gh", "repo", "clone", f"{GH_USER}/{REPO}", repo, "--", "--depth", "1", "--quiet"])

    repo_docs = os.path.join(repo, "docs")
    os.makedirs(repo_docs, exist_ok=True)

    copied = sync_files(repo_docs, data)
    with open(os.path.join(repo_docs, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(render(data))
    # keep this script version-controlled alongside the atlas
    shutil.copy2(os.path.abspath(__file__), os.path.join(repo_docs, "update_docs.py"))
    # retire the superseded generator if it is still in the repo
    old = os.path.join(repo_docs, "build.py")
    if os.path.exists(old):
        os.remove(old)
    print(f"[update_docs] copied {copied} artifacts, wrote docs/index.html")

    if sh(["git", "status", "--porcelain"], cwd=repo).strip() == "":
        print("[update_docs] no changes — site already up to date.")
        shutil.rmtree(work)
        return

    if args.dry_run:
        print(f"[update_docs] dry run — not pushing. Inspect the built clone at:\n  {repo}")
        return

    sh(["git", "add", "-A"], cwd=repo)
    msg = (f"Update research atlas ({total} artifacts)\n\n"
           "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>")
    sh(["git", "commit", "-q", "-m", msg], cwd=repo)
    sh(["git", "push", "-q", "origin", "HEAD"], cwd=repo)
    shutil.rmtree(work)
    print(f"[update_docs] pushed. Live at https://{GH_USER}.github.io/docs/ (Pages rebuilds in ~1 min).")


# ---------------------------------------------------------------------------
# HTML template (kept at the bottom so the logic reads top-down).
# ---------------------------------------------------------------------------
TEMPLATE = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Research Atlas · {GH_USER}</title>
<meta name="description" content="Live proof artifacts across five research programs in contest theory.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,600;1,9..144,500&family=IBM+Plex+Mono:ital,wght@0,400;0,500;1,400&display=swap" rel="stylesheet">
<style>
  :root{{
    --paper:#15171c; --panel:#1b1e25; --panel-2:#20242c;
    --ink:#e9e6de; --muted:#9a968c; --faint:#6f6c64;
    --line:rgba(233,230,222,.10); --line-2:rgba(233,230,222,.18);
    --brass:#c8a24c; --brass-hi:#e4c36a; --link:#7fb2b0; --link-hi:#a7d0ce;
  }}
  *{{box-sizing:border-box}}
  html{{-webkit-text-size-adjust:100%}}
  body{{
    margin:0; background:var(--paper); color:var(--ink);
    font-family:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
    font-size:15px; line-height:1.5;
    background-image:radial-gradient(1200px 600px at 78% -8%, rgba(200,162,76,.07), transparent 60%);
    background-repeat:no-repeat;
  }}
  a{{color:var(--link); text-decoration:none}}
  .wrap{{max-width:960px; margin:0 auto; padding:clamp(28px,6vw,72px) clamp(18px,5vw,40px) 96px}}
  header{{border-bottom:1px solid var(--line); padding-bottom:34px; margin-bottom:8px}}
  .eyebrow{{font-size:12px; letter-spacing:.34em; text-transform:uppercase; color:var(--brass); margin:0 0 22px}}
  h1{{font-family:"Fraunces",Georgia,serif; font-weight:400; font-size:clamp(44px,9vw,88px); line-height:.96; letter-spacing:-.015em; margin:0; color:var(--ink)}}
  h1 em{{font-style:italic; color:var(--brass-hi)}}
  .lede{{color:var(--muted); margin:22px 0 0; max-width:52ch}}
  .lede b{{color:var(--ink); font-weight:500}}
  .search{{position:sticky; top:0; z-index:5; padding:20px 0 12px; background:linear-gradient(var(--paper) 72%, transparent); margin-top:26px}}
  .search input{{width:100%; background:var(--panel); color:var(--ink); border:1px solid var(--line-2); border-radius:2px; font-family:inherit; font-size:15px; padding:13px 15px; outline:none; transition:border-color .15s}}
  .search input::placeholder{{color:var(--faint)}}
  .search input:focus{{border-color:var(--brass)}}
  .search .hint{{color:var(--faint); font-size:12px; margin:8px 2px 0; letter-spacing:.04em}}
  .plate{{position:relative; overflow:hidden; border:1px solid var(--line); border-radius:3px; background:var(--panel); margin-top:16px; transition:border-color .18s, background .18s}}
  .plate:hover{{border-color:var(--line-2)}}
  .plate[open]{{background:var(--panel-2)}}
  .plate.hidden{{display:none}}
  summary{{list-style:none; cursor:pointer; user-select:none; display:grid; grid-template-columns:auto 1fr auto; gap:20px; align-items:baseline; padding:22px clamp(18px,3vw,26px)}}
  summary::-webkit-details-marker{{display:none}}
  summary:focus-visible{{outline:2px solid var(--brass); outline-offset:3px}}
  .plate-num{{font-family:"Fraunces",Georgia,serif; font-weight:500; font-style:italic; font-size:34px; line-height:1; color:var(--brass); min-width:1.6em}}
  .plate-head{{display:flex; flex-direction:column; gap:7px; min-width:0}}
  .plate-code{{font-family:"Fraunces",Georgia,serif; font-weight:600; font-size:clamp(22px,3.4vw,29px); line-height:1.02; color:var(--ink); letter-spacing:-.01em}}
  .plate-tag{{color:var(--muted); font-size:13.5px; line-height:1.45; max-width:56ch}}
  .plate-count{{color:var(--faint); font-size:12px; letter-spacing:.08em; white-space:nowrap; text-align:right}}
  .plate-glyph{{position:absolute; right:-8px; top:50%; transform:translateY(-50%); font-family:"Fraunces",Georgia,serif; font-style:italic; font-weight:400; font-size:190px; line-height:1; color:rgba(200,162,76,.06); pointer-events:none; z-index:0; letter-spacing:-.03em}}
  summary>*{{position:relative; z-index:1}}
  .arts{{list-style:none; margin:0; padding:0 clamp(14px,3vw,22px) 14px; border-top:1px solid var(--line)}}
  .art a{{display:flex; justify-content:space-between; align-items:baseline; gap:18px; padding:11px 12px 11px calc(1.6em + 20px); border-radius:2px; color:var(--ink); transition:background .12s}}
  .art a:hover{{background:rgba(127,178,176,.09)}}
  .art a:focus-visible{{outline:2px solid var(--brass); outline-offset:-2px}}
  .art-title{{flex:1; min-width:0; line-height:1.4}}
  .art a:hover .art-title{{color:var(--link-hi)}}
  .art-date{{color:var(--faint); font-size:12px; white-space:nowrap; font-variant-numeric:tabular-nums; letter-spacing:.02em; cursor:help}}
  .art.hidden{{display:none}}
  .empty{{color:var(--faint); font-style:italic; padding:2px clamp(14px,3vw,22px) 20px; border-top:1px solid var(--line); margin:0}}
  footer{{margin-top:56px; padding-top:22px; border-top:1px solid var(--line); color:var(--faint); font-size:12px; display:flex; justify-content:space-between; flex-wrap:wrap; gap:10px; letter-spacing:.03em}}
  footer a{{color:var(--muted)}}
  @media (max-width:560px){{
    summary{{grid-template-columns:auto 1fr; gap:6px 16px}}
    .plate-count{{grid-column:2; text-align:left; margin-top:2px}}
    .plate-glyph{{font-size:130px; opacity:.7}}
    .art a{{padding-left:12px; flex-direction:column; gap:3px}}
  }}
  @media (prefers-reduced-motion:reduce){{*{{transition:none!important}}}}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <p class="eyebrow">Research Atlas</p>
    <h1>Working<br><em>papers</em> index</h1>
    <p class="lede"><b>{total} live proof artifacts</b> across {live} active programs in contest theory. Each plate opens to its catalogue; every entry links to the rendered document.</p>
  </header>
  <div class="search" role="search">
    <input id="q" type="search" placeholder="Filter artifacts — title, keyword, or filename…" autocomplete="off" aria-label="Filter artifacts">
    <p class="hint" id="hint"></p>
  </div>
  <main id="plates">
{plates_html}
  </main>
  <footer>
    <span>Generated by update_docs.py · {total} artifacts</span>
    <span><a href="https://github.com/{GH_USER}">github.com/{GH_USER}</a></span>
  </footer>
</div>
<script>
(function(){{
  var q = document.getElementById('q');
  var hint = document.getElementById('hint');
  var plates = Array.prototype.slice.call(document.querySelectorAll('.plate'));
  var openState = new Map();
  function apply(){{
    var term = q.value.trim().toLowerCase();
    var shownArts = 0, shownPlates = 0;
    plates.forEach(function(p){{
      var arts = Array.prototype.slice.call(p.querySelectorAll('.art'));
      var localMatch = 0;
      arts.forEach(function(a){{
        var hit = !term || a.getAttribute('data-hay').indexOf(term) !== -1;
        a.classList.toggle('hidden', !hit);
        if (hit) localMatch++;
      }});
      var codeHit = !term || p.getAttribute('data-code').indexOf(term) !== -1;
      var visible = arts.length === 0 ? codeHit : (localMatch > 0 || codeHit);
      p.classList.toggle('hidden', !visible);
      if (visible) shownPlates++;
      shownArts += localMatch;
      if (term){{
        if (!openState.has(p)) openState.set(p, p.open);
        p.open = localMatch > 0;
      }} else if (openState.has(p)){{
        p.open = openState.get(p); openState.delete(p);
      }}
    }});
    hint.textContent = term
      ? shownArts + ' artifact' + (shownArts===1?'':'s') + ' in ' + shownPlates + ' program' + (shownPlates===1?'':'s')
      : '';
  }}
  q.addEventListener('input', apply);
  q.addEventListener('keydown', function(e){{ if(e.key==='Escape'){{ q.value=''; apply(); }} }});
}})();
</script>
</body>
</html>
'''


if __name__ == "__main__":
    main()
