"""Offline JJC refresh smoke: run from repository root with its Playwright environment.

Every browser request is fulfilled from public/ or local API fixtures. Poll delays
of 3000ms are shortened to 25ms; no bot process or live upstream is contacted.
Screenshots are written to /tmp, outside the repository.
"""
import asyncio
import json
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[3] / 'public'
URL = 'http://127.0.0.1:8765/public/jjc-synced-matches.html'
RESULTS = []

def data(name='角色甲', page=1, refresh=None, latest='latest-old', has_more=True):
    return {'player': {'name': name, 'server': '梦江南'}, 'identity': {'identity_id': name, 'name': name, 'server': '梦江南'},
            'pagination': {'page': page, 'page_size': 20, 'has_more': has_more, 'total': 60},
            'recent_matches': [{'match_id': f'{name}-history{page}', 'kungfu': '太虚剑意', 'won': True, 'start_time': 1792425600, 'duration': 120}],
            'latest_matches': [{'match_id': f'{name}-{latest}', 'kungfu': '太虚剑意', 'won': True, 'start_time': 1792425600, 'duration': 120}],
            'refresh': refresh or {'state': 'disabled', 'enabled': False}}

class Harness:
    def __init__(self, browser, width):
        self.browser, self.width = browser, width
        self.calls, self.errors = [], []
        self.handler = None
        self.expected_http_errors = False
    async def start(self):
        self.context = await self.browser.new_context(viewport={'width': self.width, 'height': 1080 if self.width == 1920 else 844})
        await self.context.add_init_script('''const originalTimeout=window.setTimeout;window.setTimeout=(fn,ms,...args)=>originalTimeout(fn,ms===3000?25:ms,...args);''')
        await self.context.route('**/*', self.route)
        self.page = await self.context.new_page()
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.on('console', lambda message: self.errors.append(message.text) if message.type in ('warning','error') else None)
        await self.page.goto(URL)
        await self.page.wait_for_function('!document.querySelector("#server-input").disabled')
        assert await self.page.title() == 'JJC 对局查询'
        assert self.page.url == URL
        assert await self.page.locator('vite-error-overlay, nextjs-portal').count() == 0
        assert await self.page.locator('h1').inner_text()
        assert not await self.page.evaluate('document.documentElement.scrollWidth > innerWidth')
        return self
    async def route(self, route):
        request = route.request
        parsed = urlparse(request.url)
        name = Path(parsed.path).name
        if name in ('jjc-synced-matches.html', 'jjc-site.css'):
            await route.fulfill(content_type='text/css' if name.endswith('.css') else 'text/html',body=(ROOT/name).read_text())
            return
        if 'cdn.jsdelivr.net' in request.url:
            await route.fulfill(content_type='application/javascript', body='')
            return
        call = {'path': name, 'method': request.method, 'query': parse_qs(parsed.query)}
        self.calls.append(call)
        if self.handler and name in ('synced-role-matches','synced-role-refresh'):
            result = await self.handler(call)
            if result is not None:
                status, payload = result
                await route.fulfill(status=status, json={'status_code': 0 if status == 200 else 503, 'data': payload, 'status_msg': 'success' if status == 200 else 'worker unavailable'})
                return
        if name == 'servers':
            payload = {'servers':[{'server':'梦江南', 'zone':'电信五区'}]}
        elif name == 'synced-role':
            payload = data(call['query'].get('name',['角色甲'])[0])
        elif name == 'synced-role-matches':
            payload = data(call['query'].get('name',['角色甲'])[0], int(call['query'].get('page',['1'])[0]))
        elif name == 'role-indicator':
            payload = {}
        else:
            payload = {'items':[], 'announcement':None, 'has_more':False}
        await route.fulfill(json={'status_code':0, 'status_msg':'success','data':payload})
    async def seed(self, refresh=None):
        await self.page.evaluate('(d)=>{stopLatestPolling();searchToken++;renderRoleContent(d,null);renderMatches(d,false);}', data(refresh=refresh))
    async def ids(self):
        return await self.page.locator('#match-list-panel [data-match-id]').evaluate_all('(items)=>items.map(i=>i.dataset.matchId)')
    async def latest(self):
        return await self.page.locator('#latest-match-panel [data-match-id]').evaluate_all('(items)=>items.map(i=>i.dataset.matchId)')
    async def more(self):
        await self.page.locator('#load-more-btn').click()
        await self.page.wait_for_function('currentPagination.page===2 && !currentPagination.isLoading')
    async def switch(self):
        await self.page.locator('#server-input').select_option('梦江南')
        await self.page.locator('#name-input').fill('角色乙')
        await self.page.locator('#search-btn').click()
        await self.page.wait_for_function('currentRole?.name === "角色乙" && !!document.querySelector("#match-list-panel [data-match-id]")')
    async def finish(self, label):
        relevant = [e for e in self.errors if not (self.expected_http_errors and '503' in e)]
        assert not relevant, relevant
        await self.page.screenshot(path=f'/tmp/jjc-refresh-{label}-{self.width}.png', full_page=True)
        await self.context.close()

async def disabled(browser,width):
    h = await Harness(browser,width).start()
    await h.seed()
    await h.page.locator('#refresh-match-list-btn').click()
    await h.page.wait_for_function('!refreshInFlight')
    assert await h.latest() == ['角色甲-latest-old']
    assert await h.ids() == ['角色甲-history1']
    assert not [c for c in h.calls if c['method']=='POST']
    assert '本地已同步' in await h.page.locator('#latest-refresh-label').inner_text()
    await h.finish('disabled')

async def queued_poll(browser,width):
    h = await Harness(browser,width).start()
    await h.seed({'state':'idle','enabled':True})
    await h.more()
    old = await h.ids()
    polls=0
    async def handler(call):
        nonlocal polls
        if call['path']=='synced-role-refresh':
            return 200, {'state':'queued','enabled':True}
        polls += 1
        return 200, data(refresh={'state':'running' if polls < 10 else 'success','enabled':True},latest='latest-new')
    h.handler=handler
    await h.page.locator('#refresh-match-list-btn').click()
    await h.page.wait_for_function('latestRefresh.state === "success"')
    await h.page.wait_for_timeout(150)
    assert polls == 10, polls
    assert await h.ids() == old
    assert await h.latest() == ['角色甲-latest-new']
    assert len([c for c in h.calls if c['method']=='POST'])==1
    await h.finish('queued-success')

async def poll_limit(browser,width):
    h=await Harness(browser,width).start()
    await h.seed({'state':'idle','enabled':True})
    count=0
    async def handler(call):
        nonlocal count
        if call['method']=='POST': return 200,{'state':'queued','enabled':True}
        count+=1
        return 200,data(refresh={'state':'running','enabled':True})
    h.handler=handler
    await h.page.locator('#refresh-match-list-btn').click()
    await h.page.wait_for_function('document.querySelector("#status-line").textContent.includes("仍在等待")')
    await h.page.wait_for_timeout(150)
    assert count==10,count
    assert await h.ids()==['角色甲-history1']
    await h.finish('poll-limit')

async def failed_post(browser,width):
    h=await Harness(browser,width).start()
    await h.seed({'state':'idle','enabled':True})
    await h.more()
    before=await h.ids()
    h.expected_http_errors=True
    async def handler(call):
        return (503, {}) if call['method']=='POST' else None
    h.handler=handler
    await h.page.locator('#refresh-match-list-btn').click()
    await h.page.wait_for_function('document.querySelector("#status-line").textContent.includes("已保留当前")')
    assert await h.ids()==before
    assert await h.latest()==['角色甲-latest-old']
    assert await h.page.locator('#refresh-match-list-btn').is_enabled()
    await h.finish('503-keeps-history')

async def switch_race(browser,width,poll):
    h=await Harness(browser,width).start()
    await h.seed({'state':'idle','enabled':True})
    received, release = asyncio.Event(), asyncio.Event()
    async def handler(call):
        role=call['query'].get('name',['角色甲'])[0]
        if call['method']=='POST':
            if not poll:
                received.set()
                await release.wait()
            return 200, {'state':'queued','enabled':True}
        if role=='角色甲':
            received.set()
            await release.wait()
            return 200,data(refresh={'state':'success','enabled':True},latest='stale-response')
        return None
    h.handler=handler
    await h.page.locator('#refresh-match-list-btn').click()
    await asyncio.wait_for(received.wait(),3)
    await h.switch()
    before=await h.ids()
    release.set()
    await h.page.wait_for_timeout(150)
    assert await h.ids()==before==['角色乙-history1']
    assert await h.latest()==['角色乙-latest-old']
    assert await h.page.locator('.role-title').inner_text()=='角色乙 · 梦江南'
    await h.finish('switch-stale-'+('poll' if poll else 'post'))

async def refresh_more_race(browser,width):
    h=await Harness(browser,width).start()
    await h.seed()
    await h.more()
    first_received,release_first=asyncio.Event(),asyncio.Event()
    third_received,release_third=asyncio.Event(),asyncio.Event()
    async def handler(call):
        page=int(call['query'].get('page',['1'])[0])
        if page==1:
            first_received.set();await release_first.wait()
        if page==3:
            third_received.set();await release_third.wait()
        return 200,data(page=page)
    h.handler=handler
    await h.page.locator('#refresh-match-list-btn').click()
    await asyncio.wait_for(first_received.wait(),3)
    assert await h.ids()==['角色甲-history1','角色甲-history2']
    if await h.page.locator('#load-more-btn').is_enabled():
        await h.page.locator('#load-more-btn').click()
        # A guarded handler may intentionally ignore this click without issuing a request.
        try: await asyncio.wait_for(third_received.wait(),0.15)
        except asyncio.TimeoutError: pass
    release_first.set()
    await h.page.wait_for_function('!refreshInFlight')
    release_third.set()
    await h.page.wait_for_timeout(100)
    ids=await h.ids()
    await h.page.screenshot(path=f'/tmp/jjc-refresh-more-race-{width}.png',full_page=True)
    await h.finish('refresh-more-race')
    assert not ('角色甲-history3' in ids and '角色甲-history2' not in ids), {'ids':ids,'page3_requested':third_received.is_set()}

async def more_refresh_race(browser,width):
    h=await Harness(browser,width).start()
    await h.seed()
    await h.more()
    received,release=asyncio.Event(),asyncio.Event()
    async def handler(call):
        page=int(call['query'].get('page',['1'])[0])
        if page==3:
            received.set()
            await release.wait()
        return 200,data(page=page)
    h.handler=handler
    await h.page.locator('#load-more-btn').click()
    await asyncio.wait_for(received.wait(),3)
    if await h.page.locator('#refresh-match-list-btn').is_enabled():
        await h.page.locator('#refresh-match-list-btn').click()
    await h.page.wait_for_timeout(100)
    release.set()
    await h.page.wait_for_function('!currentPagination.isLoading && !refreshInFlight')
    ids=await h.ids()
    await h.finish('more-refresh-race')
    assert not ('角色甲-history3' in ids and '角色甲-history2' not in ids), ids

async def switch_more_race(browser,width,fail):
    h=await Harness(browser,width).start()
    await h.seed()
    await h.more()
    old_received,old_release=asyncio.Event(),asyncio.Event()
    new_received,new_release=asyncio.Event(),asyncio.Event()
    h.expected_http_errors=fail
    async def handler(call):
        role=call['query'].get('name',['角色甲'])[0]
        page=int(call['query'].get('page',['1'])[0])
        if role=='角色甲' and page==3:
            old_received.set()
            await old_release.wait()
            return (503,{}) if fail else (200,data(page=page))
        if role=='角色乙' and page==2:
            new_received.set()
            await new_release.wait()
            return 200,data(name=role,page=page)
        return None
    h.handler=handler
    await h.page.locator('#load-more-btn').click()
    await asyncio.wait_for(old_received.wait(),3)
    await h.switch()
    await h.page.locator('#load-more-btn').click()
    await asyncio.wait_for(new_received.wait(),3)
    old_release.set()
    await h.page.wait_for_timeout(100)
    state=await h.page.evaluate('({loading:currentPagination.isLoading,page:currentPagination.page})')
    ids=await h.ids()
    new_release.set()
    await h.page.wait_for_function('currentPagination.page===2 && !currentPagination.isLoading')
    await h.finish('switch-more-'+('failure' if fail else 'success'))
    assert ids==['角色乙-history1'], ids
    assert state=={'loading':True,'page':1},state

async def main():
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        for width in (1920,390):
            for name, test in [('disabled',disabled),('queued_poll',queued_poll),('poll_limit',poll_limit),('503_keeps_history',failed_post),('switch_stale_post',lambda b,w:switch_race(b,w,False)),('switch_stale_poll',lambda b,w:switch_race(b,w,True)),('refresh_more_race',refresh_more_race),('more_refresh_race',more_refresh_race),('switch_more_success',lambda b,w:switch_more_race(b,w,False)),('switch_more_failure',lambda b,w:switch_more_race(b,w,True))]:
                try:
                    await test(browser,width)
                    result={'case':name,'viewport':width,'result':'PASS'}
                except Exception as error:
                    result={'case':name,'viewport':width,'result':'FAIL','error':repr(error)}
                RESULTS.append(result)
                print(json.dumps(result,ensure_ascii=False),flush=True)
        await browser.close()
    print(json.dumps({'cases':len(RESULTS),'passed':sum(r['result']=='PASS' for r in RESULTS),'results':RESULTS,'environment':{'url':URL,'browser':'Chromium headless','browser_plugin':'Browser plugin not available','network':'Every request fulfilled from local files or fixtures; no online services','poll_timer':'Only 3000ms poll delay accelerated to 25ms'}},ensure_ascii=False,indent=2))
    if any(r['result']=='FAIL' for r in RESULTS):raise SystemExit(1)

asyncio.run(main())
