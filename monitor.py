import asyncio, json, os, re
from datetime import date, timedelta
from pathlib import Path
from playwright.async_api import async_playwright

URL='https://booking.capenature.co.za/booking/Robberg'
START=date(2026,12,5); END=date(2026,12,15)
STATE=Path('state.json')

def load():
    try:return json.loads(STATE.read_text())
    except:return {'available':[]}

def save(x): STATE.write_text(json.dumps(x,indent=2))

async def check(page,a,d):
    await page.goto(URL,wait_until='domcontentloaded',timeout=45000)
    await page.wait_for_timeout(1200)
    inputs=page.locator('input')
    # Prefer labelled fields, otherwise date inputs.
    arr=page.get_by_label(re.compile('arrival',re.I)).first
    dep=page.get_by_label(re.compile('departure',re.I)).first
    try: await arr.wait_for(timeout=4000)
    except:
        ds=page.locator('input[type=date]')
        if await ds.count()<2: raise RuntimeError('Could not find date fields')
        arr,dep=ds.nth(0),ds.nth(1)
    for loc,val in ((arr,a.isoformat()),(dep,d.isoformat())):
        await loc.fill(val); await loc.dispatch_event('input'); await loc.dispatch_event('change')
    btn=page.get_by_role('button',name=re.compile('search',re.I)).first
    await btn.click()
    await page.wait_for_timeout(1800)
    text=(await page.locator('body').inner_text()).lower()
    i=text.find('fountain shack')
    section=text[i:i+3000] if i>=0 else text
    bad=['no available units','no availability','fully booked','sold out','not available']
    if any(x in section for x in bad): return False
    if 'no available units for the selected search criteria' in text:return False
    return any(x in section for x in ['book now','available','add to basket','select','units available'])

async def main():
    old=load(); oldset={x['arrival'] for x in old.get('available',[])}
    found=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        page=await browser.new_page(locale='en-GB')
        a=START
        while a<END:
            d=a+timedelta(days=1)
            try:
                ok=await check(page,a,d); print(a,d,ok)
                if ok: found.append({'arrival':a.isoformat(),'departure':d.isoformat()})
            except Exception as e: print(a,d,'ERROR',e)
            a=d
        await browser.close()
    save({'available':found,'last_checked':date.today().isoformat()})
    new=[x for x in found if x['arrival'] not in oldset]
    if new: await notify(new)

async def notify(items):
    msg='🚨 ROBBERG FOUNTAIN SHACK AVAILABLE!\n\n'+'\n'.join(f"• {x['arrival']} → {x['departure']}" for x in items)+f'\n\nBook: {URL}'
    token=os.getenv('TELEGRAM_BOT_TOKEN'); chat=os.getenv('TELEGRAM_CHAT_ID')
    if token and chat:
        import urllib.request,urllib.parse
        data=urllib.parse.urlencode({'chat_id':chat,'text':msg}).encode()
        urllib.request.urlopen(urllib.request.Request(f'https://api.telegram.org/bot{token}/sendMessage',data=data),timeout=20).read()
    print(msg)

asyncio.run(main())
