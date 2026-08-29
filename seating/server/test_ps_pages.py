import os, sys, time, json, pathlib
os.environ.update(DEV="1", SESSION_SECRET="local-test-only")
sys.path.insert(0, str(pathlib.Path.home()/"Dropbox/Teaching/Projects/PersonalWebsite/seating/server"))
import main
from playwright.sync_api import sync_playwright

B="http://localhost:8099"

# The staff group's record, wiped so every run starts from nothing. Only ever
# touches 02_101166 -- the Parreiras & Wang group, which exists for exactly this.
from google.cloud import firestore
_db=firestore.Client(project="econ416-seating")
_ref=_db.collection("submissions").document("02_101166")
for _v in _ref.collection("versions").stream(): _v.reference.delete()
_ref.delete()
print("cleared submissions/02_101166\n")
SERGIO=("PID_INSTRUCTOR","5256","Sergio Parreiras")
TOBIAS=("PID_TA","104516","Tobias Wang")
ok=True
def check(n,c,d=""):
    global ok
    print(("  PASS  " if c else "  FAIL  ")+n+(f"   {d}" if d and not c else ""));  ok = ok and c

def ctx(browser, who):
    c = browser.new_context(viewport={"width":1280,"height":1000})
    c.add_cookies([{"name":main.COOKIE,
                    "value":main.make_session(who[0],who[1],who[2],time.time()+3600),
                    "domain":"localhost","path":"/"}])
    return c

with sync_playwright() as p:
    br=p.chromium.launch(channel="chrome")
    errs=[]
    A=ctx(br,SERGIO); a=A.new_page(); a.on("pageerror",lambda e:errs.append("A:"+str(e)))
    a.goto(f"{B}/ps/ps02-part1.html",wait_until="networkidle"); a.wait_for_timeout(1200)
    check("page loads behind the gate", a.locator("#title").count()==1)
    check("the widget rendered", a.locator("g[aria-label='basket a']").count()>0,
          a.locator("#items").inner_text()[:120])
    check("nothing filed yet", "Nothing submitted yet" in a.locator("#status").inner_text(),
          a.locator("#status").inner_text())

    live=".ps-item:not([hidden])"
    def arrow(pg,f,t,r):
        pg.locator(f"{live} g[aria-label='basket {f}']").click()
        pg.locator(f"{live} g[aria-label='basket {t}']").click()
        pg.locator(f"{live} .rp-rank[data-rel='{r}']").click(); pg.wait_for_timeout(200)
    for x in [('a','b','DR'),('b','c','DR'),('a','c','IR')]: arrow(a,*x)
    for _ in range(3):
        a.locator(f"{live} .rp-submit").click(); a.wait_for_timeout(900)
    check("Part I filed, Part II flagged outstanding",
          "Part II is still outstanding" in a.locator("#status").inner_text(),
          a.locator("#status").inner_text())

    # --- THE PARTNER, a separate browser context with Tobias's own session ----
    T=ctx(br,TOBIAS); t=T.new_page(); t.on("pageerror",lambda e:errs.append("T:"+str(e)))
    t.goto(f"{B}/ps/ps02-part1.html",wait_until="networkidle"); t.wait_for_timeout(1500)
    st=t.locator("#status").inner_text()
    check("Tobias sees Part I is in, and who filed it",
          "Sergio Parreiras" in st and "Part I is in" in st, st)
    drew=t.evaluate("()=>window.__ps1.get().answers['I-I']")
    check("and Sergio's arrows are on Tobias's screen",
          sorted(drew)==['a>b:DR','a>c:IR','b>c:DR'], str(drew))

    t.goto(f"{B}/ps/ps02-part2.html",wait_until="networkidle"); t.wait_for_timeout(1000)
    for idx in (1,1,0,0):
        t.locator(".opt").nth(idx).click(); t.wait_for_timeout(700)
    t.locator("#submit").click(); t.wait_for_timeout(1200)
    check("finishing the pair opens the group confirmation",
          t.locator("#confirm").evaluate("d=>d.open"))
    check("named for the real Canvas group",
          t.locator("[data-confirm-group]").inner_text()=="Parreiras & Wang PS 02",
          t.locator("[data-confirm-group]").inner_text())
    t.locator("[data-confirm-yes]").click(); t.wait_for_timeout(500)

    a.reload(wait_until="networkidle"); a.wait_for_timeout(1500)
    st=a.locator("#status").inner_text()
    check("Sergio now sees the whole set is in", "PS 02" in st and "Tobias" in st, st)

    # --- the key stays shut until Tuesday ------------------------------------
    r=a.evaluate("async()=>(await fetch('/api/ps/02/key')).status")
    check("the answer key is a 404 before the due date", r==404, str(r))
    a.goto(f"{B}/ps/ps02-answers.html",wait_until="domcontentloaded")
    a.wait_for_selector(".ps-answers-embargo",timeout=15000)
    check("and the answers page says when it opens",
          a.locator(".ps-answers-embargo").is_visible())
    r=a.evaluate("async()=>(await fetch('/ps/keys/PS02.json')).status")
    check("the key cannot be fetched round the side", r==404, str(r))

    check("no uncaught JS errors", not errs, "; ".join(errs[:3]))
    br.close()
print("\n"+("ALL CHECKS PASSED" if ok else "FAILURES ABOVE")); sys.exit(0 if ok else 1)
