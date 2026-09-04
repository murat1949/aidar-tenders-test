# -*- coding: utf-8 -*-
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from datetime import datetime, timedelta
import json, urllib.request, urllib.error, urllib.parse, re, sys, importlib.util

ROOT=Path(__file__).resolve().parent

try:
    import websocket
except Exception:
    print("Installing websocket-client...")
    import subprocess
    subprocess.check_call([sys.executable,"-m","pip","install","websocket-client"])
    import websocket

def find_config():
    files=[]
    for base in [ROOT,ROOT.parent]:
        try: files += list(base.glob("**/config.txt"))
        except: pass
    files=[p for p in files if p.exists()]
    return sorted(files,key=lambda p:p.stat().st_mtime,reverse=True)[0] if files else None

def load_cfg(path):
    d={}
    for line in path.read_text(encoding="utf-8",errors="replace").splitlines():
        if "=" in line:
            k,v=line.split("=",1); d[k.strip()]=v.strip()
    return d

def get_tabs():
    with urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


def diagnose_samruk_tabs():
    """
    Диагностика всех вкладок Samruk на CDP-порту 9222.
    Возвращает URL, title, "Найдено N", число видимых карточек и выбранную вкладку.
    """
    tabs=get_tabs()
    out=[]

    probe_js=r"""
    (() => {
      const clean=s=>(s||'').replace(/\s+/g,' ').trim();
      const body=clean(document.body ? document.body.innerText : '');
      let cards=0;
      const seen=new Set();
      for(const el of [...document.querySelectorAll('body *')]){
        const txt=clean(el.innerText);
        const m=txt.match(/№\s*(\d{5,})/);
        if(!m) continue;
        if(!/(Осталось:|Стоимость:|Запрос ценовых|тендер|закупк)/i.test(txt)) continue;
        seen.add(m[1]);
      }
      cards=seen.size;

      let target=0;
      let mm=body.match(/Найдено\s*([\d\s]+)/i);
      if(mm) target=parseInt(mm[1].replace(/\s/g,''),10)||0;
      if(!target){
        mm=body.match(/Показано\s+\d+\s*-\s*\d+\s+из\s+([\d\s]+)/i);
        if(mm) target=parseInt(mm[1].replace(/\s/g,''),10)||0;
      }

      const q=(new URL(location.href)).searchParams.get('q') || '';
      return {
        title:document.title || '',
        url:location.href,
        target,
        cards,
        q,
        body_head:body.slice(0,220)
      };
    })()
    """

    for t in tabs:
        if "zakup.sk.kz" not in (t.get("url") or ""):
            continue
        item={
            "id":t.get("id"),
            "title":t.get("title"),
            "url":t.get("url")
        }
        try:
            ws=websocket.create_connection(
                t["webSocketDebuggerUrl"],timeout=8,origin="http://localhost"
            )
            ws.send(json.dumps({
                "id":1,
                "method":"Runtime.evaluate",
                "params":{"expression":probe_js,"returnByValue":True}
            }))
            val={}
            while True:
                m=json.loads(ws.recv())
                if m.get("id")==1:
                    val=((m.get("result") or {}).get("result") or {}).get("value") or {}
                    break
            ws.close()
            item.update(val)
        except Exception as e:
            item["error"]=str(e)
        out.append(item)

    chosen=choose_samruk_tab(tabs)
    chosen_id=chosen.get("id") if chosen else None
    for item in out:
        item["chosen"]=(item.get("id")==chosen_id)

    return out



def diagnose_samruk_pages():
    """
    TEST8 / DIAG-PAGES.
    НИЧЕГО не пишет в Supabase и не скачивает PDF.
    Проверяет, что Samruk реально переключает страницы выдачи и возвращает
    разные наборы lot_id (например 10 + 9 при target=19).
    После проверки возвращает исходный URL.
    """
    tabs=get_tabs()
    tab=choose_samruk_tab(tabs)
    if not tab:
        raise RuntimeError("Не найден открытый Samruk в Chrome collector mode.")

    ws=websocket.create_connection(tab["webSocketDebuggerUrl"],timeout=45,origin="http://localhost")
    cid=0

    def cdp(method,params=None):
        nonlocal cid
        cid+=1
        req={"id":cid,"method":method}
        if params is not None:
            req["params"]=params
        ws.send(json.dumps(req))
        while True:
            m=json.loads(ws.recv())
            if m.get("id")==cid:
                if "error" in m:
                    raise RuntimeError(str(m["error"]))
                return m.get("result",{})

    def snap():
        js=r"""
        (() => {
          const clean=s=>(s||'').replace(/\s+/g,' ').trim();
          const body=clean(document.body ? document.body.innerText : '');

          let target=0, shownFrom=0, shownTo=0;
          let m=body.match(/Найдено\s*([\d\s]+)/i);
          if(m) target=parseInt(m[1].replace(/\s/g,''),10)||0;

          let p=body.match(/Показано\s+(\d+)\s*-\s*(\d+)\s+из\s+([\d\s]+)/i);
          if(p){
            shownFrom=parseInt(p[1],10)||0;
            shownTo=parseInt(p[2],10)||0;
            if(!target) target=parseInt(p[3].replace(/\s/g,''),10)||0;
          }

          const raw=[];
          for(const el of [...document.querySelectorAll('div,li,article,tr')]){
            const txt=clean(el.innerText);
            if(!txt||txt.length<30||txt.length>1200) continue;
            const nm=txt.match(/№\s*(\d{5,})/);
            if(!nm) continue;
            if(!/(Осталось:|Стоимость:|Запрос ценовых|тендер|закупк)/i.test(txt)) continue;

            const kids=[...el.children].filter(ch=>{
              const t=clean(ch.innerText);
              return t&&t.length>=30&&t.length<txt.length&&/№\s*\d{5,}/.test(t)&&
                     /(Осталось:|Стоимость:|Запрос ценовых|тендер|закупк)/i.test(t);
            });
            if(kids.length) continue;
            raw.push(nm[1]);
          }

          const lots=[...new Set(raw)];
          const u=new URL(location.href);
          const page=u.searchParams.get('page') ||
                     (new URLSearchParams((location.hash.split('?')[1]||''))).get('page') || '';
          return {
            url:location.href,
            page:String(page||''),
            target,
            shown_from:shownFrom,
            shown_to:shownTo,
            lots,
            count:lots.length,
            body_head:body.slice(0,260)
          };
        })()
        """
        r=cdp("Runtime.evaluate",{"expression":js,"returnByValue":True})
        return ((r.get("result") or {}).get("value")) or {}

    def make_page_url(url,n):
        # page= находится у Samruk внутри hash-route, но regex одинаково работает
        # по всей строке URL.
        if re.search(r"([?&]page=)\d+",url):
            return re.sub(r"([?&]page=)\d+",lambda m:m.group(1)+str(n),url)
        sep="&" if "?" in url else "?"
        return url+sep+"page="+str(n)

    def wait_expected(n,target,previous_lots,timeout=15):
        expected_from=(n-1)*10+1
        expected_to=min(n*10,target) if target else 0
        deadline=time.time()+timeout
        last={}
        stable_lots=None
        stable_count=0
        while time.time()<deadline:
            time.sleep(0.55)
            last=snap()
            lots=last.get("lots") or []
            if lots==stable_lots:
                stable_count+=1
            else:
                stable_lots=list(lots)
                stable_count=1
            shown_from=int(last.get("shown_from") or 0)
            shown_to=int(last.get("shown_to") or 0)
            page=str(last.get("page") or "")

            expected_count=(expected_to-expected_from+1) if expected_to>=expected_from else 0
            range_ok=(shown_from==expected_from and (not expected_to or shown_to==expected_to))
            count_ok=(expected_count>0 and len(lots)==expected_count)
            page_ok=(page==str(n))
            changed=(not previous_lots) or (lots and lots!=previous_lots)

            # TEST10M CONTENTGUARD: Samruk SPA может уже показать новый page/диапазон,
            # но карточки DOM ещё оставить от предыдущей страницы. Поэтому кроме номера,
            # диапазона и количества требуем фактическую смену списка лотов и его стабильность.
            if lots and range_ok and count_ok and page_ok and changed and stable_count>=2:
                return last,True
            # Fallback допустим только для полной 10-строчной страницы и тоже только
            # после реальной смены карточек относительно предыдущей страницы.
            if lots and expected_count==10 and page_ok and changed and len(lots)==10 and stable_count>=2:
                return last,True
        return last,False

    original=snap()
    if not original.get("url"):
        ws.close()
        raise RuntimeError("Не удалось определить URL текущей выдачи Samruk.")
    if not original.get("target"):
        ws.close()
        raise RuntimeError("На выбранной вкладке Samruk не найдено значение 'Найдено N'.")

    original_url=original["url"]
    target=int(original.get("target") or 0)
    pages=max(1,(target+9)//10)
    pages=min(pages,50)  # TEST10M OPERATIONAL: диагностика до 50 страниц.

    report=[]
    unique=[]
    seen=set()
    previous_lots=[]

    try:
        for n in range(1,pages+1):
            url=make_page_url(original_url,n)
            method="Page.navigate"
            cdp("Page.navigate",{"url":url})
            s,ok=wait_expected(n,target,previous_lots,15)

            # Если SPA оставила старый DOM, пробуем ещё один безопасный способ.
            if not ok:
                method="location.href"
                cdp("Runtime.evaluate",{
                    "expression":"location.href="+json.dumps(url,ensure_ascii=False)+"; true",
                    "returnByValue":True
                })
                s,ok=wait_expected(n,target,previous_lots,12)

            if not ok:
                method+=" + reload"
                try:
                    cdp("Page.reload",{"ignoreCache":True})
                except Exception:
                    pass
                s,ok=wait_expected(n,target,previous_lots,12)

            lots=s.get("lots") or []
            for lot in lots:
                if lot not in seen:
                    seen.add(lot)
                    unique.append(lot)

            report.append({
                "requested_page":n,
                "ok":bool(ok),
                "method":method,
                "actual_page":s.get("page"),
                "shown_from":s.get("shown_from"),
                "shown_to":s.get("shown_to"),
                "count":len(lots),
                "lots":lots,
                "url":s.get("url")
            })
            previous_lots=lots
    finally:
        try:
            cdp("Page.navigate",{"url":original_url})
            time.sleep(1.0)
        except Exception:
            pass
        try:
            ws.close()
        except Exception:
            pass

    return {
        "build":"v6.8_TEST10M_OPERATIONAL",
        "safe_mode":True,
        "writes_supabase":False,
        "downloads_pdf":False,
        "target":target,
        "expected_pages":pages,
        "unique_count":len(unique),
        "unique_lots":unique,
        "complete":bool(target and len(unique)>=target),
        "pages":report,
        "original_url":original_url
    }

def choose_samruk_tab(tabs):
    """
    Выбирает именно вкладку Samruk с живыми результатами поиска.
    Сначала проверяет DOM каждой Samruk-вкладки; URL используется только как приоритет.
    """
    candidates=[
        t for t in tabs
        if "zakup.sk.kz" in (t.get("url") or "") and t.get("webSocketDebuggerUrl")
    ]
    if not candidates:
        return None

    def url_score(t):
        u=(t.get("url") or "").lower()
        s=0
        if "q=" in u: s+=100
        if "page=" in u: s+=40
        if "tabs=lot" in u or "tabs=purchase" in u: s+=20
        if "popup=item" in u: s-=100
        return s

    candidates.sort(key=url_score,reverse=True)

    probe_js=r"""
    (() => {
      const clean=s=>(s||'').replace(/\s+/g,' ').trim();
      const body=clean(document.body ? document.body.innerText : '');
      let cards=0;
      const nodes=[...document.querySelectorAll('div,li,article,tr')];
      for(const el of nodes){
        const txt=clean(el.innerText);
        if(!txt||txt.length<30||txt.length>1200)continue;
        if(!/№\s*\d{5,}/.test(txt))continue;
        if(!/(Осталось:|Стоимость:|Запрос ценовых|тендер|закупк)/i.test(txt))continue;
        cards++;
      }
      let target=0;
      let mm=body.match(/Найдено\s*([\d\s]+)/i);
      if(mm) target=parseInt(mm[1].replace(/\s/g,''),10)||0;
      if(!target){
        mm=body.match(/Показано\s+\d+\s*-\s*\d+\s+из\s+([\d\s]+)/i);
        if(mm) target=parseInt(mm[1].replace(/\s/g,''),10)||0;
      }
      return {
        cards,
        target,
        hasFound:target>0,
        url:location.href
      };
    })()
    """

    best=None
    best_score=-10**9

    for t in candidates:
        score=url_score(t)
        try:
            ws=websocket.create_connection(t["webSocketDebuggerUrl"],timeout=8,origin="http://localhost")
            ws.send(json.dumps({
                "id":1,
                "method":"Runtime.evaluate",
                "params":{"expression":probe_js,"returnByValue":True}
            }))
            val={}
            while True:
                m=json.loads(ws.recv())
                if m.get("id")==1:
                    val=((m.get("result") or {}).get("result") or {}).get("value") or {}
                    break
            ws.close()

            target=int(val.get("target",0) or 0)
            if target>0:
                # Главный признак правильной выдачи — максимальное реальное "Найдено N".
                score+=100000 + target*100
            if val.get("cards",0)>0:
                score+=1000+min(int(val.get("cards",0)),100)
            elif val.get("hasFound"):
                score+=300
        except Exception:
            pass

        if score>best_score:
            best_score=score
            best=t

    return best



def read_current_samruk():
    """
    TEST10M: сбор всей выдачи Samruk выполняется в ОТДЕЛЬНОЙ временной вкладке.
    Пользовательская вкладка Samruk не переключается между страницами.
    Это убирает зависимость /update-samruk от состояния DOM после /diagnose-pages.
    """
    tabs=get_tabs()
    tab=choose_samruk_tab(tabs)
    if not tab:
        raise RuntimeError("Не найден открытый Samruk в Chrome collector mode.")

    master_ws=websocket.create_connection(tab["webSocketDebuggerUrl"],timeout=45,origin="http://localhost")
    master_cid=0
    def master_cdp(method,params=None):
        nonlocal master_cid
        master_cid+=1
        req={"id":master_cid,"method":method}
        if params is not None:req["params"]=params
        master_ws.send(json.dumps(req))
        while True:
            m=json.loads(master_ws.recv())
            if m.get("id")==master_cid:
                if "error" in m: raise RuntimeError(str(m["error"]))
                return m.get("result",{})

    probe_js=r"""
    (() => {
      const clean=s=>(s||'').replace(/\s+/g,' ').trim();
      const inp=[...document.querySelectorAll('input')].find(x =>
        ((x.placeholder||'').toLowerCase().includes('слово для поиска')) ||
        ((x.placeholder||'').toLowerCase().includes('номер закупки'))
      );
      const keyword=inp?clean(inp.value):'';
      const body=clean(document.body ? document.body.innerText : '');
      let target=0;
      let m=body.match(/Найдено\s*([\d\s]+)/i);
      if(m) target=parseInt(m[1].replace(/\s/g,''),10)||0;
      if(!target){
        m=body.match(/Показано\s+\d+\s*-\s*\d+\s+из\s+([\d\s]+)/i);
        if(m) target=parseInt(m[1].replace(/\s/g,''),10)||0;
      }
      return {
        keyword,target,url:location.href,
        loggedIn:!!localStorage.getItem('jhi-authenticationtoken')
      };
    })()
    """

    rr=master_cdp("Runtime.evaluate",{"expression":probe_js,"returnByValue":True})
    master=((rr.get("result") or {}).get("value")) or {}
    if not master.get("loggedIn"):
        try: master_ws.close()
        except Exception: pass
        raise RuntimeError("Samruk открыт, но авторизация не найдена.")

    search_url=master.get("url") or tab.get("url") or ""
    keyword=master.get("keyword") or ""
    target=int(master.get("target") or 0)
    if "zakup.sk.kz" not in search_url:
        try: master_ws.close()
        except Exception: pass
        raise RuntimeError("Не удалось определить URL поисковой выдачи Samruk.")
    if not target:
        try: master_ws.close()
        except Exception: pass
        raise RuntimeError("На выбранной выдаче Samruk не найдено значение 'Найдено N'.")

    created=master_cdp("Target.createTarget",{"url":search_url})
    target_id=created.get("targetId")
    if not target_id:
        try: master_ws.close()
        except Exception: pass
        raise RuntimeError("Не удалось создать временную вкладку для сбора Samruk.")

    temp_ws=None
    try:
        deadline=time.time()+12
        temp_tab=None
        while time.time()<deadline:
            time.sleep(0.35)
            for t in get_tabs():
                if t.get("id")==target_id:
                    temp_tab=t
                    break
            if temp_tab: break
        if not temp_tab:
            raise RuntimeError("Временная вкладка Samruk для сбора не появилась.")

        temp_ws=websocket.create_connection(temp_tab["webSocketDebuggerUrl"],timeout=45,origin="http://localhost")
        cid=0
        def cdp(method,params=None):
            nonlocal cid
            cid+=1
            req={"id":cid,"method":method}
            if params is not None:req["params"]=params
            temp_ws.send(json.dumps(req))
            while True:
                m=json.loads(temp_ws.recv())
                if m.get("id")==cid:
                    if "error" in m: raise RuntimeError(str(m["error"]))
                    return m.get("result",{})

        def page_snapshot():
            js=r"""
            (() => {
              const clean=s=>(s||'').replace(/\s+/g,' ').trim();
              const inp=[...document.querySelectorAll('input')].find(x =>
                ((x.placeholder||'').toLowerCase().includes('слово для поиска')) ||
                ((x.placeholder||'').toLowerCase().includes('номер закупки'))
              );
              const kw=inp?clean(inp.value):'';
              const body=clean(document.body ? document.body.innerText : '');
              let tgt=0, shownFrom=0, shownTo=0;
              let m=body.match(/Найдено\s*([\d\s]+)/i);
              if(m) tgt=parseInt(m[1].replace(/\s/g,''),10)||0;
              let p=body.match(/Показано\s+(\d+)\s*-\s*(\d+)\s+из\s+([\d\s]+)/i);
              if(p){
                shownFrom=parseInt(p[1],10)||0;
                shownTo=parseInt(p[2],10)||0;
                if(!tgt) tgt=parseInt(p[3].replace(/\s/g,''),10)||0;
              }
              const raw=[];
              for(const el of [...document.querySelectorAll('div,li,article,tr')]){
                const txt=clean(el.innerText);
                if(!txt||txt.length<30||txt.length>1200)continue;
                const nm=txt.match(/№\s*(\d{5,})/);
                if(!nm)continue;
                if(!/(Осталось:|Стоимость:|Запрос ценовых|тендер|закупк)/i.test(txt))continue;
                const kids=[...el.children].filter(ch=>{
                  const t=clean(ch.innerText);
                  return t&&t.length>=30&&t.length<txt.length&&/№\s*\d{5,}/.test(t)&&
                         /(Осталось:|Стоимость:|Запрос ценовых|тендер|закупк)/i.test(t);
                });
                if(kids.length)continue;
                const a=el.querySelector('a[href]');
                raw.push({lot:nm[1],text:txt,href:a?a.href:''});
              }
              const seen=new Set(), cards=[];
              for(const x of raw){
                if(seen.has(x.lot))continue;
                seen.add(x.lot);cards.push(x);
              }
              const u=new URL(location.href);
              const pg=u.searchParams.get('page') ||
                       (new URLSearchParams((location.hash.split('?')[1]||''))).get('page') || '';
              return {keyword:kw,target:tgt,shown_from:shownFrom,shown_to:shownTo,
                      cards,page:String(pg||''),url:location.href,
                      loggedIn:!!localStorage.getItem('jhi-authenticationtoken')};
            })()
            """
            r=cdp("Runtime.evaluate",{"expression":js,"returnByValue":True})
            return ((r.get("result") or {}).get("value")) or {}

        def make_page_url(url,n):
            if re.search(r"([?&]page=)\d+",url):
                return re.sub(r"([?&]page=)\d+",lambda m:m.group(1)+str(n),url)
            sep="&" if "?" in url else "?"
            return url+sep+"page="+str(n)

        def wait_page(n,prev_lots,timeout=18):
            expected_from=(n-1)*10+1
            expected_to=min(n*10,target)
            deadline=time.time()+timeout
            last={}
            stable_lots=None
            stable_count=0
            while time.time()<deadline:
                time.sleep(0.6)
                try:
                    last=page_snapshot()
                except Exception:
                    continue
                cards=last.get("cards") or []
                lots=[str(x.get("lot") or "") for x in cards if x.get("lot")]
                if not lots:
                    continue
                if lots==stable_lots:
                    stable_count+=1
                else:
                    stable_lots=lots
                    stable_count=1
                shown_from=int(last.get("shown_from") or 0)
                shown_to=int(last.get("shown_to") or 0)
                pg=str(last.get("page") or "")
                expected_count=(expected_to-expected_from+1) if expected_to>=expected_from else 0
                range_ok=(shown_from==expected_from and shown_to==expected_to)
                count_ok=(expected_count>0 and len(lots)==expected_count)
                page_ok=(pg==str(n))
                changed=(not prev_lots) or (lots!=prev_lots)
                # TEST10M CONTENTGUARD: page/"Показано" могут измениться раньше DOM карточек.
                # Принимаем страницу только после реальной смены списка лотов, совпадения
                # номера/диапазона/количества и двух одинаковых стабильных снимков подряд.
                if range_ok and count_ok and page_ok and changed and stable_count>=2:
                    return last,True
                # Fallback только для обычной полной страницы из 10 карточек.
                if expected_count==10 and page_ok and changed and len(lots)==10 and stable_count>=2:
                    return last,True
            return last,False

        # Даём новой вкладке полностью загрузиться перед первой навигацией.
        ready_deadline=time.time()+15
        while time.time()<ready_deadline:
            time.sleep(0.6)
            s=page_snapshot()
            if s.get("loggedIn") and (s.get("cards") or []):
                if not keyword: keyword=s.get("keyword") or keyword
                break
        else:
            raise RuntimeError("Временная вкладка Samruk не загрузила поисковую выдачу.")

        pages=max(1,(target+9)//10)
        pages=min(pages,50)
        collected={}

        for pass_no in range(1,4):
            prev_lots=[]
            print("Samruk TEST10M: проход %s/3, сейчас уникальных %s/%s." % (pass_no,len(collected),target), flush=True)
            for n in range(1,pages+1):
                url=make_page_url(search_url,n)
                ok=False
                snap={}
                for attempt in range(1,4):
                    if attempt==1:
                        cdp("Page.navigate",{"url":url})
                    elif attempt==2:
                        cdp("Runtime.evaluate",{"expression":"location.href="+json.dumps(url,ensure_ascii=False)+"; true","returnByValue":True})
                    else:
                        try: cdp("Page.reload",{"ignoreCache":True})
                        except Exception: pass
                    snap,ok=wait_page(n,prev_lots,18)
                    if ok: break
                if not ok:
                    print("Samruk TEST10M: страница %s/%s не подтвердилась в проходе %s; продолжаю следующий проход." % (n,pages,pass_no), flush=True)
                    prev_lots=[]
                    continue

                current=[]
                for c in (snap.get("cards") or []):
                    lot=str(c.get("lot") or "").strip()
                    if not lot: continue
                    current.append(lot)
                    cc=dict(c)
                    cc["samruk_page"]=n
                    cc["samruk_page_url"]=url
                    collected[lot]=cc
                prev_lots=current
                print("Samruk TEST10M: проход %s, страница %s/%s, lot_id=%s, уникальных %s/%s." % (
                    pass_no,n,pages,",".join(current),len(collected),target), flush=True)

            if len(collected)>=target:
                break
            time.sleep(1.0)

        cards=list(collected.values())
        if len(cards)<target:
            raise RuntimeError("Samruk: ожидалось %s результатов, собрано только %s." % (target,len(cards)))
        print("Samruk TEST10M: собрано %s/%s уникальных строк во временной вкладке." % (len(cards),target), flush=True)
        return keyword,cards

    finally:
        try:
            if temp_ws: temp_ws.close()
        except Exception:
            pass
        try:
            master_cdp("Target.closeTarget",{"targetId":target_id})
        except Exception:
            pass
        try: master_ws.close()
        except Exception: pass

def money(s):
    try:return float(str(s).replace(" ","").replace(",","."))
    except:return None

def parse_cards(keyword,cards):
    rows=[]
    now=datetime.now()
    for c in cards:
        txt=c.get("text","")
        # TEST10H SERVERFILTER: карточки уже отфильтрованы самим Samruk по текущему запросу.
        # Поисковое слово может находиться в скрытых деталях/техспецификации и не быть
        # видимым в кратком тексте карточки (например запрос "тонер" даёт карточки
        # с заголовком "Картридж"). Поэтому повторно фильтровать txt по keyword нельзя.
        num=re.search(r"№\s*(\d{5,})",txt)
        amount=re.search(r"Стоимость:\s*([\d\s.,]+)\s*₸",txt,re.I)
        days=re.search(r"Осталось:\s*(\d+)\s*д",txt,re.I)
        title=txt[num.end():].strip() if num else txt
        title=re.split(r"\s+(?:Запрос ценовых|Открытый тендер|Осталось:|Стоимость:)",title,maxsplit=1,flags=re.I)[0].strip()
        method=None
        low=txt.lower()
        if "на понижение" in low:method="Запрос ценовых предложений на понижение"
        elif "запрос ценовых предложений" in low:method="Запрос ценовых предложений"
        exp=(now+timedelta(days=int(days.group(1)))).replace(microsecond=0).isoformat() if days else None
        rows.append({
            "source_code":"samruk",
            "source_tender_id":None,
            "source_lot_id":num.group(1) if num else None,
            "public_url":c.get("href") or None,
            "title":title[:300] or "Закупка Samruk",
            "description":txt,
            "customer_name":None,"customer_bin":None,"region":None,
            "procurement_method":method,
            "status_code":None,"status_name":"Опубликовано",
            "amount":money(amount.group(1)) if amount else None,
            "currency":"KZT","quantity":None,"unit":None,
            "category":keyword or None,
            "published_at":None,"started_at":None,"expires_at":exp,
            "is_active":True,
            "raw":{"keyword":keyword,"raw_text":txt,"samruk_page":c.get("samruk_page"),"samruk_page_url":c.get("samruk_page_url")}
        })
    return rows



def load_techspec_module():
    p=ROOT / "extract_samruk_techspec.py"
    if not p.exists():
        raise RuntimeError("Не найден extract_samruk_techspec.py рядом с bridge.")
    spec=importlib.util.spec_from_file_location("samruk_techspec_extractor", str(p))
    if not spec or not spec.loader:
        raise RuntimeError("Не удалось загрузить extract_samruk_techspec.py")
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def find_latest_techspec_pdf():
    roots=[ROOT, Path.home()/"Downloads"]
    files=[]
    for base in roots:
        try:
            files += list(base.glob("Lot_*.pdf"))
        except Exception:
            pass
    files=[p for p in files if p.exists()]
    if not files:
        raise RuntimeError("Не найден PDF Lot_*.pdf ни в тестовой папке, ни в Downloads.")
    return max(files, key=lambda p:p.stat().st_mtime)

def supabase_cfg():
    cp=find_config()
    if not cp: raise RuntimeError("Не найден config.txt с настройками Supabase.")
    c=load_cfg(cp)
    url=c.get("SUPABASE_URL","").rstrip("/")
    key=c.get("SUPABASE_SERVICE_ROLE_KEY") or c.get("SUPABASE_SECRET_KEY") or ""
    if not url or not key: raise RuntimeError("В config.txt нет Supabase URL/secret key.")
    return url,key

def save_techspec_to_tender(data):
    lot_id=str(data.get("lot_id") or "").strip()
    if not lot_id:
        raise RuntimeError("В PDF не определён номер лота.")
    url,key=supabase_cfg()
    q=urllib.parse.urlencode({
        "source_code":"eq.samruk",
        "source_lot_id":"eq."+lot_id,
        "select":"id,raw"
    }, safe=".,")
    endpoint=url+"/rest/v1/tenders?"+q
    req=urllib.request.Request(endpoint, headers={"apikey":key,"Authorization":"Bearer "+key})
    with urllib.request.urlopen(req,timeout=60) as r:
        found=json.loads(r.read().decode("utf-8"))
    if not found:
        raise RuntimeError("Лот "+lot_id+" не найден в Supabase. Сначала обновите Samruk.")
    row=found[0]
    raw=row.get("raw") if isinstance(row.get("raw"),dict) else {}
    raw=dict(raw)
    raw["techspec"]=data
    patch={"raw":raw}
    if data.get("customer"): patch["customer_name"]=data.get("customer")
    if data.get("quantity") is not None: patch["quantity"]=data.get("quantity")
    if data.get("unit"): patch["unit"]=data.get("unit")
    patch_url=url+"/rest/v1/tenders?id=eq."+urllib.parse.quote(str(row.get("id")))
    preq=urllib.request.Request(patch_url,
        data=json.dumps(patch,ensure_ascii=False).encode("utf-8"),
        headers={"apikey":key,"Authorization":"Bearer "+key,"Content-Type":"application/json","Prefer":"return=representation"},
        method="PATCH")
    with urllib.request.urlopen(preq,timeout=90) as r:
        body=r.read().decode("utf-8")
        return r.status, json.loads(body) if body else []

def process_latest_techspec():
    pdf=find_latest_techspec_pdf()
    mod=load_techspec_module()
    data=mod.parse(pdf)
    json_path=pdf.with_suffix(".techspec.json")
    json_path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    status,_=save_techspec_to_tender(data)
    return {
        "ok":True,
        "pdf":pdf.name,
        "lot_id":data.get("lot_id"),
        "customer":data.get("customer"),
        "quantity":data.get("quantity"),
        "unit":data.get("unit"),
        "delivery_terms":data.get("delivery_terms"),
        "payment_terms":data.get("payment_terms"),
        "compatibility":(data.get("parsed_fields") or {}).get("compatibility"),
        "json":json_path.name,
        "http":status
    }


def tender_has_techspec(lot_id):
    """Проверяет, есть ли уже raw.techspec у Samruk-лота в Supabase."""
    url,key=supabase_cfg()
    q=urllib.parse.urlencode({
        "source_code":"eq.samruk",
        "source_lot_id":"eq."+str(lot_id),
        "select":"id,raw"
    }, safe=".,")
    endpoint=url+"/rest/v1/tenders?"+q
    req=urllib.request.Request(endpoint,headers={
        "apikey":key,
        "Authorization":"Bearer "+key
    })
    with urllib.request.urlopen(req,timeout=40) as r:
        rows=json.loads(r.read().decode("utf-8"))
    if not rows:
        return False
    raw=rows[0].get("raw")
    return isinstance(raw,dict) and isinstance(raw.get("techspec"),dict)


def diagnose_techspec_coverage(rows):
    """READ ONLY: проверяет покрытие raw.techspec для текущей выдачи Samruk."""
    url,key=supabase_cfg()
    q=urllib.parse.urlencode({
        "source_code":"eq.samruk",
        "select":"source_lot_id,raw"
    }, safe=".,")
    endpoint=url+"/rest/v1/tenders?"+q
    req=urllib.request.Request(endpoint,headers={
        "apikey":key,
        "Authorization":"Bearer "+key
    })
    with urllib.request.urlopen(req,timeout=60) as r:
        db_rows=json.loads(r.read().decode("utf-8"))

    db={}
    for x in db_rows:
        lot=str(x.get("source_lot_id") or "").strip()
        if lot:
            db[lot]=x.get("raw")

    current=[]
    with_spec=[]
    without_spec=[]
    not_in_db=[]
    for row in rows:
        lot=str(row.get("source_lot_id") or "").strip()
        if not lot or lot in current:
            continue
        current.append(lot)
        if lot not in db:
            not_in_db.append(lot)
            without_spec.append(lot)
            continue
        raw=db.get(lot)
        has=isinstance(raw,dict) and isinstance(raw.get("techspec"),dict)
        if has:
            with_spec.append(lot)
        else:
            without_spec.append(lot)

    return {
        "build":"v6.8_TEST10M_OPERATIONAL",
        "safe_mode":True,
        "writes_supabase":False,
        "downloads_pdf":False,
        "current_rows":len(current),
        "with_techspec":len(with_spec),
        "without_techspec":len(without_spec),
        "not_in_db":len(not_in_db),
        "available_for_batch5":len(without_spec)>=5,
        "with_techspec_lots":with_spec,
        "without_techspec_lots":without_spec,
        "not_in_db_lots":not_in_db
    }


def auto_download_and_process_techspecs(rows):
    """
    v6.8_TEST10M_OPERATIONAL:
    1) Открывает настоящий popup лота (наличие блока "Документы" больше не требуется).
    2) Если у лота есть обычная ссылка "Техническая спецификация лота закупки" —
       скачивает PDF и обрабатывает прежним проверенным способом.
    3) Если техспека находится только на уровне закупки — переходит по "Перейти на закупку"
       и проверяет документы закупки.
    4) Если отдельной заполненной техспеки нет, сохраняет структурированные технические
       данные непосредственно из карточки лота в raw.techspec (status=techspec_from_lot_card).
    """
    tabs=get_tabs()
    tab=choose_samruk_tab(tabs)
    if not tab:
        raise RuntimeError("Не найден Samruk Chrome на порту 9222.")

    master_ws=websocket.create_connection(
        tab["webSocketDebuggerUrl"],timeout=50,origin="http://localhost"
    )
    ws=master_ws
    cid=0

    def cdp(method,params=None):
        nonlocal cid, ws
        cid+=1
        req={"id":cid,"method":method}
        if params is not None:
            req["params"]=params
        ws.send(json.dumps(req))
        while True:
            m=json.loads(ws.recv())
            if m.get("id")==cid:
                if "error" in m:
                    raise RuntimeError(str(m["error"]))
                return m.get("result",{})

    def eval_js(js, await_promise=False):
        rr=cdp("Runtime.evaluate",{
            "expression":js,
            "returnByValue":True,
            "awaitPromise":await_promise
        })
        return ((rr.get("result") or {}).get("value")) or {}

    def wait_search(timeout=15):
        deadline=time.time()+timeout
        while time.time()<deadline:
            time.sleep(0.5)
            try:
                v=eval_js(r"""
                (() => {
                  const clean=s=>(s||'').replace(/\s+/g,' ').trim();
                  const body=clean(document.body ? document.body.innerText : '');
                  const lots=[...document.querySelectorAll('body *')].filter(e =>
                    /№\s*\d{5,}/.test(clean(e.innerText)) &&
                    /(Осталось:|Стоимость:|Запрос ценовых)/i.test(clean(e.innerText))
                  ).length;
                  return {ok:(/Найдено\s*\d+/i.test(body) ||
                    /Показано\s+\d+\s*-\s*\d+\s+из\s+\d+/i.test(body)) && lots>0};
                })()
                """)
                if v.get("ok"):
                    return True
            except Exception:
                pass
        return False

    def set_download_dir():
        try:
            cdp("Page.setDownloadBehavior",{"behavior":"allow","downloadPath":str(ROOT)})
        except Exception:
            try:
                cdp("Browser.setDownloadBehavior",{"behavior":"allow","downloadPath":str(ROOT)})
            except Exception:
                pass

    def wait_lot_popup(lot_id, timeout=10):
        deadline=time.time()+timeout
        while time.time()<deadline:
            time.sleep(0.5)
            try:
                js=r"""
                (() => {
                  const lot=%s;
                  const clean=s=>(s||'').replace(/\s+/g,' ').trim();
                  const body=clean(document.body ? document.body.innerText : '');
                  const hasLot=body.includes('№ '+lot)||body.includes('№'+lot)||body.includes(lot);
                  const detail=/НАЧАЛО ПРИЕМА ЗАЯВОК/i.test(body) &&
                               /(ОБЩАЯ ИНФОРМАЦИЯ|КОЛИЧЕСТВО|УСЛОВИЯ ОПЛАТЫ)/i.test(body);
                  return {ok:!!(hasLot&&detail),url:location.href};
                })()
                """ % json.dumps(str(lot_id),ensure_ascii=False)
                v=eval_js(js)
                if v.get("ok"):
                    return True
            except Exception:
                pass
        return False

    def capture_lot_card(lot_id,row):
        js=r"""
        (() => {
          const lot=%s;
          const raw=(document.body ? document.body.innerText : '').replace(/\r/g,'');
          const lines=raw.split('\n').map(s=>s.replace(/\s+/g,' ').trim()).filter(Boolean);
          const upper=lines.map(s=>s.toUpperCase());
          function pos(label){return upper.findIndex(x=>x===label || x.startsWith(label+' '));}
          function one(label){
            const i=pos(label); if(i<0) return '';
            return (lines[i+1]||'').trim();
          }
          function block(label,stops){
            const i=pos(label); if(i<0) return '';
            const out=[];
            for(let j=i+1;j<lines.length && out.length<12;j++){
              const u=upper[j];
              if(stops.some(s=>u===s || u.startsWith(s+' '))) break;
              out.push(lines[j]);
            }
            return out.join(' ').trim();
          }
          function num(s){
            const m=String(s||'').replace(/\s/g,'').replace(',','.').match(/-?\d+(?:\.\d+)?/);
            return m ? Number(m[0]) : null;
          }
          const purchase=[...document.querySelectorAll('a')].find(a=>/Перейти на закупку/i.test((a.innerText||'').trim()));
          const href=purchase ? (purchase.href||'') : '';
          let pm=href.match(/item\/(\d+)\/advert/i);
          if(!pm) pm=href.match(/item%%?2F(\d+)%%?2Fadvert/i);
          const short=one('КРАТКАЯ ХАРАКТЕРИСТИКА');
          const additional=block('ДОПОЛНИТЕЛЬНЫЕ ХАРАКТЕРИСТИКИ',[
            'КОД ОКТРУ','ПРИОРИТЕТ','КОЛИЧЕСТВО','СРОКИ','УСЛОВИЯ ОПЛАТЫ'
          ]);
          const customer=one('ЗАКАЗЧИК');
          const deliveryPlace=one('МЕСТО ПОСТАВКИ');
          const deliveryPeriod=block('СРОКИ',['УСЛОВИЯ ОПЛАТЫ','УСЛОВИЯ ПОСТАВКИ']);
          const payment=block('УСЛОВИЯ ОПЛАТЫ',['УСЛОВИЯ ПОСТАВКИ','УЧАСТВОВАТЬ В ЗАКУПКЕ']);
          const deliveryTerms=block('УСЛОВИЯ ПОСТАВКИ',['УЧАСТВОВАТЬ В ЗАКУПКЕ']);
          const q=one('КОЛИЧЕСТВО');
          const unit=one('ЕДИНИЦА ИЗМЕРЕНИЯ');
          return {
            ok:true,
            purchase_id:pm ? pm[1] : '',
            purchase_href:href,
            customer,
            short_description:short,
            additional_characteristics:additional,
            quantity:num(q),
            quantity_text:q,
            unit,
            delivery_place:deliveryPlace,
            delivery_period:deliveryPeriod,
            payment_terms:payment,
            delivery_terms:deliveryTerms,
            raw_popup_text:raw.replace(/\s+/g,' ').trim().slice(0,12000)
          };
        })()
        """ % json.dumps(str(lot_id),ensure_ascii=False)
        v=eval_js(js)
        v["lot_id"]=str(lot_id)
        v["title"]=str(row.get("title") or "")
        return v

    def make_card_techspec(snap,row,lot_id):
        purchase_id=str(snap.get("purchase_id") or "").strip()
        short=str(snap.get("short_description") or row.get("title") or "").strip()
        additional=str(snap.get("additional_characteristics") or "").strip()
        raw_text=str(snap.get("raw_popup_text") or "").strip()
        technical=additional or raw_text
        data={
            "source_type":"samruk_lot_card",
            "extraction_method":"lot_card_fallback",
            "source_note":"Отдельная заполненная техспецификация не найдена; данные взяты из карточки лота Samruk.",
            "purchase_id":purchase_id or None,
            "procurement_id":purchase_id or None,
            "tender_id":purchase_id or None,
            "lot_id":str(lot_id),
            "customer":snap.get("customer") or None,
            "short_description":short or None,
            "quantity":snap.get("quantity"),
            "unit":snap.get("unit") or None,
            "delivery_place":snap.get("delivery_place") or None,
            "delivery_terms":snap.get("delivery_terms") or None,
            "delivery_period":snap.get("delivery_period") or None,
            "payment_terms":snap.get("payment_terms") or None,
            "additional_characteristics":additional or None,
            "technical_requirements":technical or None,
            "raw_text":raw_text or None,
            "parsed_fields":{
                "purpose":short or None,
                "compatibility":None,
                "color":None,
                "volume":None
            }
        }
        return data

    def tech_link_exists():
        v=eval_js(r"""
        (() => {
          const clean=s=>(s||'').replace(/\s+/g,' ').trim();
          const a=[...document.querySelectorAll('a')].find(a=>
            /Техническая спецификация лота закупки/i.test(clean(a.innerText))
          );
          return {ok:!!a,text:a?clean(a.innerText):''};
        })()
        """)
        return bool(v.get("ok"))

    def expand_docs_and_find():
        js=r"""
        (async () => {
          const clean=s=>(s||'').replace(/\s+/g,' ').trim();
          function tech(){return [...document.querySelectorAll('a')].find(a=>
            /Техническая спецификация лота закупки/i.test(clean(a.innerText)));}
          if(tech()) return {ok:true,tech:true};
          const docs=[...document.querySelectorAll('button,a,div,span')].filter(e=>{
            const t=clean(e.innerText),r=e.getBoundingClientRect();
            return /^Документы(?:\s*\d+)?$/i.test(t)&&r.width>0&&r.height>0;
          });
          if(!docs.length) return {ok:true,tech:false,docs:false};
          docs.sort((a,b)=>{
            const ra=a.getBoundingClientRect(),rb=b.getBoundingClientRect();
            return (ra.width*ra.height)-(rb.width*rb.height);
          });
          try{docs[0].click();}catch(e){}
          await new Promise(r=>setTimeout(r,1300));
          const links=[...document.querySelectorAll('a')].map(a=>clean(a.innerText)).filter(Boolean);
          return {ok:true,tech:!!tech(),docs:true,links:links.filter(x=>/договор|специф|прилож|объяв/i.test(x)).slice(0,20)};
        })()
        """
        return eval_js(js,True)

    def goto_purchase_popup():
        js=r"""
        (() => {
          const clean=s=>(s||'').replace(/\s+/g,' ').trim();
          const a=[...document.querySelectorAll('a')].find(a=>/Перейти на закупку/i.test(clean(a.innerText)));
          if(!a) return {ok:false,message:'Ссылка Перейти на закупку не найдена'};
          try{a.click();}catch(e){}
          a.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true,view:window}));
          return {ok:true,href:a.href||''};
        })()
        """
        v=eval_js(js)
        if not v.get("ok"):
            return False
        deadline=time.time()+10
        while time.time()<deadline:
            time.sleep(0.5)
            try:
                p=eval_js(r"""
                (()=>{const b=(document.body?document.body.innerText:'').replace(/\s+/g,' ');
                return {ok:/ОБЩАЯ СУММА ЛОТОВ/i.test(b)&&/Документы/i.test(b)};})()
                """)
                if p.get("ok"):
                    return True
            except Exception:
                pass
        return False

    def download_current_techspec(lot_id,mod):
        before={str(p.resolve()) for p in ROOT.glob("Lot_*.pdf")}
        started=time.time()
        v=eval_js(r"""
        (() => {
          const clean=s=>(s||'').replace(/\s+/g,' ').trim();
          const a=[...document.querySelectorAll('a')].find(a=>
            /Техническая спецификация лота закупки/i.test(clean(a.innerText))
          );
          if(!a) return {ok:false,message:'Техспецификация не найдена'};
          a.click(); return {ok:true,text:clean(a.innerText)};
        })()
        """)
        if not v.get("ok"):
            raise RuntimeError(v.get("message") or "Не удалось нажать техспецификацию.")
        pdf=None
        deadline=time.time()+22
        while time.time()<deadline:
            time.sleep(0.5)
            partial=list(ROOT.glob("*.crdownload"))
            fresh=[p for p in ROOT.glob("Lot_*.pdf")
                   if str(p.resolve()) not in before and p.stat().st_mtime >= started-2]
            exact=[p for p in fresh if str(lot_id) in p.name]
            pool=exact or fresh
            if pool and not partial:
                pdf=max(pool,key=lambda p:p.stat().st_mtime)
                s1=pdf.stat().st_size; time.sleep(0.4); s2=pdf.stat().st_size
                if s1==s2 and s2>0: break
                pdf=None
        if not pdf:
            raise RuntimeError("PDF после автоклика не найден.")
        data=mod.parse(pdf)
        parsed_lot=str(data.get("lot_id") or "").strip()
        if parsed_lot and parsed_lot!=str(lot_id):
            raise RuntimeError("Скачан PDF другого лота: "+parsed_lot)
        json_path=pdf.with_suffix(".techspec.json")
        json_path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
        status,_=save_techspec_to_tender(data)
        return pdf,json_path,status

    if not wait_search(8):
        master_ws.close()
        raise RuntimeError("На исходной странице Samruk не найдена живая выдача.")
    search_url=tab.get("url") or ""
    if "zakup.sk.kz" not in search_url:
        master_ws.close()
        raise RuntimeError("Не удалось определить URL поисковой выдачи Samruk.")

    mod=load_techspec_module()
    results=[]
    test_rows=[]
    for r in rows:
        lot=str(r.get("source_lot_id") or "").strip()
        if lot and not tender_has_techspec(lot):
            test_rows.append(r)
        if len(test_rows)>=5:
            break
    if not test_rows:
        test_rows=rows[:1]

    selected=[str(r.get("source_lot_id") or "").strip() for r in test_rows]
    print("TEST10M: выбраны лоты: %s" % ", ".join(selected), flush=True)

    for idx,row in enumerate(test_rows,1):
        lot_id=str(row.get("source_lot_id") or "").strip()
        if not lot_id: continue
        item={"lot_id":lot_id}
        temp_ws=None; target_id=None
        print("TEST10M [%s/%s] лот %s: старт" % (idx,len(test_rows),lot_id), flush=True)
        try:
            if tender_has_techspec(lot_id):
                item.update({"ok":True,"status":"already_has_techspec"})
                results.append(item); continue

            row_raw=row.get("raw") if isinstance(row.get("raw"),dict) else {}
            row_page=int(row_raw.get("samruk_page") or 1)
            lot_search_url=row_raw.get("samruk_page_url") or search_url
            if not row_raw.get("samruk_page_url"):
                if re.search(r"([?&]page=)\d+",lot_search_url):
                    lot_search_url=re.sub(r"([?&]page=)\d+",lambda m:m.group(1)+str(row_page),lot_search_url)
                else:
                    sep="&" if "?" in lot_search_url else "?"
                    lot_search_url=lot_search_url+sep+"page="+str(row_page)
            item["page"]=row_page

            ws=master_ws
            created=cdp("Target.createTarget",{"url":lot_search_url})
            target_id=created.get("targetId")
            if not target_id: raise RuntimeError("Не удалось создать временную вкладку.")
            deadline=time.time()+10; temp_tab=None
            while time.time()<deadline:
                time.sleep(0.4)
                for t in get_tabs():
                    if t.get("id")==target_id: temp_tab=t; break
                if temp_tab: break
            if not temp_tab: raise RuntimeError("Временная вкладка Samruk не появилась.")
            temp_ws=websocket.create_connection(temp_tab["webSocketDebuggerUrl"],timeout=50,origin="http://localhost")
            ws=temp_ws; set_download_dir()
            if not wait_search(15): raise RuntimeError("Поисковая выдача не загрузилась во временной вкладке.")

            locate_card_js=r"""
            (() => {
              const lot=%s,clean=s=>(s||'').replace(/\s+/g,' ').trim();
              const els=[...document.querySelectorAll('body *')].filter(e=>{
                const t=clean(e.innerText); return t.includes('№ '+lot)||t.includes('№'+lot);
              });
              if(!els.length) return {ok:false,message:'Лот не найден на текущей странице'};
              els.sort((a,b)=>clean(a.innerText).length-clean(b.innerText).length);
              let p=els[0],card=null;
              for(let i=0;i<10&&p;i++,p=p.parentElement){
                const t=clean(p.innerText),r=p.getBoundingClientRect();
                if(t.includes(lot)&&/(Осталось:|Стоимость:|Запрос ценовых)/i.test(t)&&r.width>200&&r.height>60){card=p;break;}
              }
              card=card||els[0].parentElement||els[0]; card.scrollIntoView({block:'center'});
              const r=card.getBoundingClientRect(),a=card.querySelector('a[href]');
              return {ok:true,x:r.left+Math.min(r.width*0.45,Math.max(80,r.width-40)),y:r.top+r.height*0.5,href:a?a.href:''};
            })()
            """ % json.dumps(lot_id,ensure_ascii=False)
            pos=eval_js(locate_card_js)
            if not pos.get("ok"): raise RuntimeError(pos.get("message") or "Карточка лота не найдена.")
            x=float(pos.get("x") or 0); y=float(pos.get("y") or 0)
            if x>0 and y>0:
                cdp("Input.dispatchMouseEvent",{"type":"mouseMoved","x":x,"y":y})
                cdp("Input.dispatchMouseEvent",{"type":"mousePressed","x":x,"y":y,"button":"left","clickCount":1})
                cdp("Input.dispatchMouseEvent",{"type":"mouseReleased","x":x,"y":y,"button":"left","clickCount":1})
            popup=wait_lot_popup(lot_id,8)
            if not popup:
                retry_js=r"""
                (()=>{const lot=%s,clean=s=>(s||'').replace(/\s+/g,' ').trim();
                const n=[...document.querySelectorAll('body *')].filter(e=>{const t=clean(e.innerText);return t.includes('№ '+lot)||t.includes('№'+lot);});
                if(!n.length)return {ok:false};n.sort((a,b)=>clean(a.innerText).length-clean(b.innerText).length);
                let p=n[0],card=null;for(let i=0;i<10&&p;i++,p=p.parentElement){const t=clean(p.innerText),r=p.getBoundingClientRect();if(t.includes(lot)&&/(Осталось:|Стоимость:|Запрос ценовых)/i.test(t)&&r.width>200&&r.height>60){card=p;break;}}
                card=card||n[0].parentElement||n[0];try{card.click();}catch(e){};card.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true,view:window}));return {ok:true};})()
                """ % json.dumps(lot_id,ensure_ascii=False)
                eval_js(retry_js); popup=wait_lot_popup(lot_id,7)
            if not popup:
                raise RuntimeError("Popup лота действительно не открылся.")

            snap=capture_lot_card(lot_id,row)
            print("TEST10M [%s/%s] лот %s: popup открыт, данные карточки сняты" % (idx,len(test_rows),lot_id), flush=True)

            # Путь A: обычная техспека прямо в popup лота.
            direct=expand_docs_and_find()
            found=bool(direct.get("tech"))

            # Путь B: документы находятся на уровне закупки.
            if not found:
                if goto_purchase_popup():
                    purch=expand_docs_and_find()
                    found=bool(purch.get("tech"))
                    if not found:
                        item["purchase_documents"]=purch.get("links") or []

            if found:
                pdf,json_path,status=download_current_techspec(lot_id,mod)
                item.update({"ok":True,"status":"downloaded_and_saved","pdf":pdf.name,"json":json_path.name,"http":status})
                print("TEST10M [%s/%s] лот %s: PDF -> JSON -> Supabase HTTP %s" % (idx,len(test_rows),lot_id,status), flush=True)
            else:
                data=make_card_techspec(snap,row,lot_id)
                json_path=ROOT/("Lot_%s_CARD_%s.techspec.json" % (lot_id,datetime.now().strftime('%Y-%m-%d')))
                json_path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
                status,_=save_techspec_to_tender(data)
                item.update({"ok":True,"status":"techspec_from_lot_card","json":json_path.name,"http":status,"purchase_id":data.get("purchase_id")})
                print("TEST10M [%s/%s] лот %s: отдельной техспеки нет; карточка -> JSON -> Supabase HTTP %s" % (idx,len(test_rows),lot_id,status), flush=True)

        except Exception as e:
            item.update({"ok":False,"status":"error","message":str(e)})
            print("TEST10M [%s/%s] лот %s: ОШИБКА: %s" % (idx,len(test_rows),lot_id,str(e)), flush=True)
        finally:
            try:
                if temp_ws is not None:
                    ws=temp_ws
                    try: cdp("Page.close")
                    except Exception: pass
                    try: temp_ws.close()
                    except Exception: pass
            finally:
                ws=master_ws; time.sleep(0.5)
        results.append(item)
        print("TEST10M [%s/%s] лот %s: статус %s" % (idx,len(test_rows),lot_id,item.get("status")), flush=True)

    print("TEST10M: пакет завершён. Результатов: %s" % len(results), flush=True)
    try: master_ws.close()
    except Exception: pass
    return results

def process_pending_techspecs():
    """
    Обрабатывает новые PDF и восстанавливает techspec из уже существующих
    .techspec.json, если прошлый Samruk-upsert стёр raw.techspec в Supabase.
    """
    roots=[ROOT]
    downloads=Path.home()/"Downloads"
    if downloads.exists():
        roots.append(downloads)

    seen=set()
    pdfs=[]
    for root in roots:
        try:
            for p in root.glob("Lot_*.pdf"):
                rp=str(p.resolve()).lower()
                if rp in seen:
                    continue
                seen.add(rp)
                pdfs.append(p)
        except Exception:
            pass

    pdfs.sort(key=lambda p:p.stat().st_mtime if p.exists() else 0)
    if not pdfs:
        return []

    mod=load_techspec_module()
    results=[]

    for pdf in pdfs:
        json_path=pdf.with_suffix(".techspec.json")
        item={"pdf":pdf.name}
        try:
            if json_path.exists():
                data=json.loads(json_path.read_text(encoding="utf-8"))
            else:
                data=mod.parse(pdf)
                json_path.write_text(
                    json.dumps(data,ensure_ascii=False,indent=2),
                    encoding="utf-8"
                )

            lot_id=str(data.get("lot_id") or "").strip()
            if not lot_id:
                raise RuntimeError("Не удалось определить lot_id")

            # Если в БД techspec уже есть — ничего не делаем.
            if tender_has_techspec(lot_id):
                item.update({
                    "ok":True,
                    "lot_id":lot_id,
                    "status":"already_in_db",
                    "json":json_path.name
                })
            else:
                status,_=save_techspec_to_tender(data)
                item.update({
                    "ok":True,
                    "lot_id":lot_id,
                    "status":"restored_to_db" if json_path.exists() else "saved_to_db",
                    "http":status,
                    "json":json_path.name
                })
        except Exception as e:
            item.update({"ok":False,"message":str(e)})

        results.append(item)

    return results

def upload(rows):
    cp=find_config()
    if not cp: raise RuntimeError("Не найден config.txt с настройками Supabase.")
    c=load_cfg(cp)
    url=c.get("SUPABASE_URL","").rstrip("/")
    key=c.get("SUPABASE_SERVICE_ROLE_KEY") or c.get("SUPABASE_SECRET_KEY") or ""
    if not url or not key: raise RuntimeError("В config.txt нет Supabase URL/secret key.")

    # ВАЖНО: обычный upsert Samruk раньше заменял raw целиком и стирал raw.techspec.
    # Перед записью подмешиваем уже существующую techspec обратно в raw.
    for row in rows:
        if row.get("source_code")!="samruk":
            continue
        lot_id=str(row.get("source_lot_id") or "").strip()
        if not lot_id:
            continue
        try:
            q=urllib.parse.urlencode({
                "source_code":"eq.samruk",
                "source_lot_id":"eq."+lot_id,
                "select":"raw"
            }, safe=".,")
            req=urllib.request.Request(
                url+"/rest/v1/tenders?"+q,
                headers={"apikey":key,"Authorization":"Bearer "+key}
            )
            with urllib.request.urlopen(req,timeout=30) as r:
                found=json.loads(r.read().decode("utf-8"))
            if found:
                old_raw=found[0].get("raw")
                old_spec=old_raw.get("techspec") if isinstance(old_raw,dict) else None
                if isinstance(old_spec,dict):
                    new_raw=row.get("raw") if isinstance(row.get("raw"),dict) else {}
                    new_raw=dict(new_raw)
                    new_raw["techspec"]=old_spec
                    row["raw"]=new_raw
        except Exception:
            # Не блокируем обычное обновление, если чтение старого raw временно не удалось.
            pass

    endpoint=url+"/rest/v1/tenders?on_conflict=source_code,source_lot_id"
    req=urllib.request.Request(endpoint,
        data=json.dumps(rows,ensure_ascii=False).encode("utf-8"),
        headers={"apikey":key,"Authorization":"Bearer "+key,"Content-Type":"application/json",
                 "Prefer":"resolution=merge-duplicates,return=representation"},method="POST")
    with urllib.request.urlopen(req,timeout=90) as r:
        return r.status

class H(BaseHTTPRequestHandler):
    def headers_ok(self,code=200):
        self.send_response(code)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Access-Control-Allow-Methods","GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers","Content-Type")
        self.send_header("Access-Control-Allow-Private-Network","true")
        self.end_headers()
    def log_message(self,*a):pass
    def do_GET(self):
        if self.path.startswith("/diagnose-pages"):
            try:
                data=diagnose_samruk_pages()
                self.headers_ok(200)
                self.wfile.write(json.dumps({
                    "ok":True,
                    **data
                },ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.headers_ok(500)
                self.wfile.write(json.dumps({"ok":False,"build":"v6.8_TEST10M_OPERATIONAL","message":str(e)},ensure_ascii=False).encode("utf-8"))
        elif self.path.startswith("/diagnose-techspecs"):
            try:
                keyword,cards=read_current_samruk()
                rows=parse_cards(keyword,cards)
                if not rows:
                    raise RuntimeError("На открытой странице Samruk не найдены строки по текущему поиску.")
                data=diagnose_techspec_coverage(rows)
                self.headers_ok(200)
                self.wfile.write(json.dumps({
                    "ok":True,
                    "keyword":keyword,
                    **data
                },ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.headers_ok(500)
                self.wfile.write(json.dumps({"ok":False,"build":"v6.8_TEST10M_OPERATIONAL","message":str(e)},ensure_ascii=False).encode("utf-8"))
        elif self.path.startswith("/diagnose-tabs"):
            try:
                data=diagnose_samruk_tabs()
                self.headers_ok(200)
                self.wfile.write(json.dumps({
                    "ok":True,
                    "build":"v6.8_TEST10M_OPERATIONAL",
                    "samruk_tabs":data
                },ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.headers_ok(500)
                self.wfile.write(json.dumps({"ok":False,"message":str(e)},ensure_ascii=False).encode("utf-8"))
        elif self.path.startswith("/update-samruk"):
            try:
                keyword,cards=read_current_samruk()
                rows=parse_cards(keyword,cards)
                if not rows:
                    raise RuntimeError("На открытой странице Samruk не найдены строки по текущему поиску. Сначала выполните поиск на сайте.")
                status=upload(rows)

                # TEST10M: на этом контрольном запуске НЕ пересматриваем все старые PDF.
                # Это сокращает время запроса и изолирует проверку именно пакета из 5 новых лотов.
                pending=[]
                print("TEST10M: проверка старых pending PDF пропущена; запускаю только пакет новых лотов.", flush=True)

                # v6: затем для лотов без техспеки bridge сам открывает карточку,
                # нажимает "Техническая спецификация лота закупки",
                # скачивает PDF, разбирает его и пишет в Supabase.
                auto=auto_download_and_process_techspecs(rows)

                pending_ok=sum(1 for x in pending if x.get("ok"))
                pending_err=sum(1 for x in pending if not x.get("ok"))
                auto_ok=sum(1 for x in auto if x.get("ok") and x.get("status")=="downloaded_and_saved")
                auto_from_card=sum(1 for x in auto if x.get("ok") and x.get("status")=="techspec_from_lot_card")
                auto_existing=sum(1 for x in auto if x.get("ok") and x.get("status")=="already_has_techspec")
                auto_err=sum(1 for x in auto if not x.get("ok"))

                self.headers_ok(200)
                self.wfile.write(json.dumps({
                    "ok":True,
                    "rows":len(rows),
                    "keyword":keyword,
                    "http":status,
                    "pending_processed":pending_ok,
                    "pending_errors":pending_err,
                    "auto_techspec_downloaded":auto_ok,
                    "auto_techspec_from_card":auto_from_card,
                    "auto_techspec_existing":auto_existing,
                    "auto_techspec_errors":auto_err,
                    "auto_techspec_results":auto,
                    "build":"v6.8_TEST10M_OPERATIONAL"
                },ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.headers_ok(500)
                self.wfile.write(json.dumps({"ok":False,"message":str(e)},ensure_ascii=False).encode("utf-8"))
        elif self.path.startswith("/techspec-latest"):
            try:
                result=process_latest_techspec()
                self.headers_ok(200)
                self.wfile.write(json.dumps(result,ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.headers_ok(500)
                self.wfile.write(json.dumps({"ok":False,"message":str(e)},ensure_ascii=False).encode("utf-8"))
        elif self.path.startswith("/ping"):
            self.headers_ok(200);self.wfile.write(b'{"ok":true}')
        else:
            self.headers_ok(404);self.wfile.write(b'{"ok":false}')
    def do_OPTIONS(self):
        self.headers_ok(200)

print("ProcureVision TEST10M OPERATIONAL local bridge: http://127.0.0.1:8765")
print("Leave this window open while using the portal.")
HTTPServer(("127.0.0.1",8765),H).serve_forever()
