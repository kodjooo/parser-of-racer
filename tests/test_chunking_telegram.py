from app.integrations.telegram import chunk_lines


def test_chunking_telegram() -> None:
    lines = ["Header", "link1", "link2", "link3"]
    chunks = chunk_lines(lines, max_chars=12)
    assert chunks == ["Header\nlink1", "link2\nlink3"]
