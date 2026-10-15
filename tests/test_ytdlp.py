from radar import ytdlp


def test_options_without_cookies_or_proxy(monkeypatch, tmp_path):
    monkeypatch.setenv("YOUTUBE_COOKIES", str(tmp_path / "missing.txt"))
    monkeypatch.delenv("RADAR_HTTP_PROXY", raising=False)
    opts = ytdlp.options(skip_download=True)
    assert opts["skip_download"] is True and opts["quiet"] is True
    assert "cookiefile" not in opts and "proxy" not in opts


def test_options_use_cookies_and_proxy(monkeypatch, tmp_path):
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n")
    monkeypatch.setenv("YOUTUBE_COOKIES", str(cookies))
    monkeypatch.setenv("RADAR_HTTP_PROXY", "http://proxy:8080")
    opts = ytdlp.options(format="bestaudio/best")
    assert opts["cookiefile"] == str(cookies)
    assert opts["proxy"] == "http://proxy:8080"
    assert opts["format"] == "bestaudio/best"


def test_explain_bot_check(monkeypatch, tmp_path):
    monkeypatch.setenv("YOUTUBE_COOKIES", str(tmp_path / "missing.txt"))
    message = "[youtube] abc: Sign in to confirm you’re not a bot. Use --cookies"
    assert "secrets/youtube/cookies.txt" in ytdlp.explain(message)
    assert ytdlp.explain("HTTP Error 404") == "HTTP Error 404"
