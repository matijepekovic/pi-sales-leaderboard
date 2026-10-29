"""Review stays in the checklist row and never changes MOD Notes."""
import os

import pytest

from printer_app.tests.test_mod_resulting_browser import mod_browser


pytestmark = pytest.mark.skipif(
    os.environ.get('PRINTER_BROWSER_TESTS') != '1', reason='CI browser dependencies')


@pytest.mark.parametrize('viewport', [(1200, 820), (390, 844)])
def test_review_checkbox_persists_independently_in_checklist_row(mod_browser, viewport):
    from playwright.sync_api import expect

    page, service, writer, origin, evidence = mod_browser
    page.set_viewport_size({'width': viewport[0], 'height': viewport[1]})
    assert page.goto(origin + '/mod-resulting').status == 200
    first = page.locator('.mod-sheet').first
    expect(first).to_have_class('mod-sheet surface-ready')
    review = first.get_by_role('checkbox', name='Review', exact=True)
    expect(review).not_to_be_checked()
    middle = first.locator('.field-bids').bounding_box()
    # Three labels and checkboxes must fit inside the original Bid Sheets box.
    last_right = middle['x']
    for label in first.locator('.field-bids label').all():
        bounds = label.bounding_box()
        assert bounds['x'] >= last_right - 1
        last_right = bounds['x'] + bounds['width']
        assert last_right <= middle['x'] + middle['width'] + 1
        for child in label.locator('span,input').all():
            box = child.bounding_box()
            assert box['x'] >= middle['x'] - 1
            assert box['x'] + box['width'] <= middle['x'] + middle['width'] + 1
            assert box['y'] >= middle['y'] - 1
            assert box['y'] + box['height'] <= middle['y'] + middle['height'] + 1
    def notes_geometry():
        sheet = first.bounding_box()
        box = first.locator('.field-notes').bounding_box()
        return (box['x'] - sheet['x'], box['y'] - sheet['y'], box['width'], box['height'])
    notes_bounds = notes_geometry()
    notes = first.locator('[data-key=notes]')
    black_note = 'Black comment stays here.'
    red_note = 'REDLINE STAYS IN MOD NOTES.'
    assert first.locator('.notes-text textarea').count() == 1
    notes.fill(black_note)
    expect(first.locator('.manual-redlines')).to_be_hidden()
    first.locator('[data-key=dispo]').select_option('pns')
    expect(notes).to_have_value(black_note)
    first.locator('.red-pen').click()
    popup = first.locator('.redlines-panel')
    expect(popup).to_be_visible()
    popup.locator('[data-key=redlines]').fill(red_note)
    popup.locator('.editor-primary').click()
    expect(first.locator('.manual-redlines')).to_have_text(red_note)
    assert first.locator('.manual-redlines').evaluate(
        '(el) => getComputedStyle(el).color') == 'rgb(176, 0, 0)'
    for selected in (True, False):
        review.set_checked(selected)
        assert notes_geometry() == pytest.approx(notes_bounds, abs=1)
        with page.expect_navigation(wait_until='domcontentloaded'):
            page.locator('#refresh').click()
        expect(first).to_have_class('mod-sheet surface-ready')
        # Review has no Salesforce source in this fake adapter, so Refresh
        # restores its authoritative false value even after local edits.
        expect(review).not_to_be_checked()
        expect(notes).to_have_value(black_note)
        assert first.locator('.notes-text textarea').count() == 1
        expect(first.locator('.manual-redlines')).to_have_text(red_note)
        draft = service.repository.sheets(service.day())[0]['draft']
        assert draft['review'] is False
        assert draft['notes'] == black_note
        assert draft['redlines'] == red_note
        assert draft['note_runs'] == []
    first.locator('[data-key=dispo]').select_option('')
    expect(notes).to_have_value(black_note)
    expect(first.locator('.manual-redlines')).to_have_text(red_note)
    assert page.evaluate('window.modCspViolations') == []
    assert service.allow_salesforce_writes is False and not writer.applied
    evidence('review-roundtrip-' + str(viewport[0]))
