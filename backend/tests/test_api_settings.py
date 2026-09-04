"""
/api/settings/scraper — the sidebar's "Apify Usage" toggle. Covers the
read/write endpoints themselves; test_api_scrape.py covers the part that
actually matters (that a paused toggle stops POST /run and /run-manual from
starting an Instagram/Apify run).
"""


def test_scraper_settings_default_to_instagram_enabled(client):
    resp = client.get("/api/settings/scraper")
    assert resp.status_code == 200, resp.text
    assert resp.json()["instagramScrapingEnabled"] is True


def test_scraper_settings_can_be_toggled_off_and_on(client):
    off = client.patch("/api/settings/scraper", json={"instagram_scraping_enabled": False})
    assert off.status_code == 200, off.text
    assert off.json()["instagramScrapingEnabled"] is False

    # persists across a fresh read, not just echoed back
    assert client.get("/api/settings/scraper").json()["instagramScrapingEnabled"] is False

    on = client.patch("/api/settings/scraper", json={"instagram_scraping_enabled": True})
    assert on.json()["instagramScrapingEnabled"] is True
