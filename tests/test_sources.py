import pytest

from ytexplain.sources import extract_playlist_id, extract_video_id

VIDEO = "dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com/watch?v=dQw4w9WgXcQ&t=90s",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ?si=abcdef",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        "https://www.youtube.com/embed/dQw4w9WgXcQ",
        "https://www.youtube.com/live/dQw4w9WgXcQ",
        "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ",
        "www.youtube.com/watch?v=dQw4w9WgXcQ",
        "dQw4w9WgXcQ",
    ],
)
def test_extract_video_id(url):
    assert extract_video_id(url) == VIDEO


@pytest.mark.parametrize(
    "url",
    ["https://vimeo.com/12345", "https://www.youtube.com/watch?v=tooshort", "not a url"],
)
def test_rejects_non_video_urls(url):
    assert extract_video_id(url) is None


def test_playlist_id_extracted_from_watch_url():
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLu0W_9lII9ag"
    assert extract_playlist_id(url) == "PLu0W_9lII9ag"
    # A watch URL still resolves to its single video unless a playlist is requested.
    assert extract_video_id(url) == VIDEO


@pytest.mark.parametrize("playlist_id", ["RDabc123", "WL", "LL", "ULabc"])
def test_rejects_unenumerable_playlists(playlist_id):
    assert extract_playlist_id(f"https://www.youtube.com/playlist?list={playlist_id}") is None
