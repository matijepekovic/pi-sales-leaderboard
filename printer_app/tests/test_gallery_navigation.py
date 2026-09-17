"""Actual compact gallery UI in Chromium and iPhone-sized WebKit, no live devices."""
import os
import threading
import pytest

from printer_app.tests.test_gallery_recognition import seed


@pytest.mark.skipif(os.environ.get('PRINTER_BROWSER_TESTS')!='1',reason='CI browser dependencies')
@pytest.mark.parametrize('engine',['chromium','webkit'])
def test_compact_header_tall_first_card_related_back_and_pinned_notes(tmp_path,engine):
    from PIL import Image
    from playwright.sync_api import sync_playwright,expect
    from werkzeug.serving import make_server
    from printer_app.app import create_app
    from printer_app.config import Config
    env=tmp_path/'env'; env.write_text('EMAIL_ENABLED=0\n')
    app=create_app(Config(data_dir=tmp_path,env_file=env,secret_key='s'*64))
    service=app.extensions['printer_gallery']
    first=seed(service,1); second=seed(service,2)
    older=seed(service,3); service.date(older,'2026-09-15')
    for ident in (first,second,older):
        Image.new('RGB',(1200,2400 if ident==first else 420),'white').save(service.files.path('crops',ident))
    server=make_server('127.0.0.1',0,app,threaded=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with sync_playwright() as pw:
            browser=getattr(pw,engine).launch()
            page=browser.new_page(viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}/gallery/')
            expect(page.locator('#galleryChooseDate')).to_have_text('September 16, 2026 ⌄')
            expect(page.locator('.gallery-card')).to_have_count(2)
            card=page.locator('.gallery-card').first
            expect(card).to_have_attribute('data-id',first)
            expect(card).to_have_attribute('aria-pressed','true')
            nav=page.locator('.gallery-date-nav').bounding_box();box=card.bounding_box()
            assert abs(box['y']-nav['y']-nav['height'])<=3
            assert not page.locator('.gallery-day-heading').first.is_visible()
            assert page.locator('.gallery-header').count()==0
            image=card.locator('img');image.evaluate('(img)=>img.decode()')
            assert image.evaluate('(img)=>getComputedStyle(img).objectFit')=='contain'
            assert image.bounding_box()['height']==pytest.approx(image.bounding_box()['width']*2,abs=1)
            notes=page.locator('body > .gallery-dock [data-action="notes"]')
            expect(notes).to_be_enabled();notes.click()
            expect(page.locator('#galleryNote')).to_have_attribute('data-item-id',first)
            page.locator('#galleryNote [name="body"]').fill('Pinned tall-card note')
            page.set_viewport_size({'width':390,'height':560})
            page.locator('#galleryNote button').click()
            expect(page.locator('#galleryNoteMessage')).to_contain_text('Saved.')
            assert service.item(first)['notes'][0]['body']=='Pinned tall-card note'
            assert service.item(second)['notes']==[]
            page.locator('[data-close="galleryNotesSheet"]').click()
            expect(page.locator('#galleryNotesSheet')).not_to_be_visible()
            page.set_viewport_size({'width':390,'height':844})
            card.click(position={'x':120,'y':100})
            expect(page.locator('#galleryViewer')).to_be_visible()
            page.locator('#galleryFull').evaluate('(img)=>img.decode()')
            page.locator('#galleryViewer').evaluate('(node)=>node.scrollTop=240')
            page.locator('#galleryViewer [data-action="related"]').click()
            expect(page.locator('#galleryViewer')).not_to_be_visible()
            expect(page.locator('.gallery-card')).to_have_count(3)
            expect(page.locator('#galleryNotesSheet')).not_to_be_visible()
            page.locator('#galleryBack').click()
            expect(page.locator('#galleryViewer')).to_be_visible()
            expect(page.locator('#galleryFull')).to_have_attribute('src','/gallery/image/'+first)
            expect(page.locator('#galleryChooseDate')).to_have_text('September 16, 2026 ⌄')
            page.wait_for_function("() => Math.abs(document.getElementById('galleryViewer').scrollTop-240)<3")
            page.go_back();expect(page.locator('#galleryViewer')).not_to_be_visible()
            # Browser Back closes the sheet before leaving the gallery.
            page.locator('body > .gallery-dock [data-action="notes"]').click()
            page.go_back();expect(page.locator('#galleryNotesSheet')).not_to_be_visible()
            assert not errors
            assert app.extensions['printer_db'].rows('SELECT * FROM jobs')==[]
            browser.close()
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)
