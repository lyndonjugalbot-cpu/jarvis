import json

from tools.notes import make_notes_tools, slugify
from tools.registry import ToolRegistry


async def yes(summary: str) -> bool:
    return True


def registry(tmp_path):
    return ToolRegistry(make_notes_tools(tmp_path / "notes"), confirmer=yes)


async def test_write_list_read(tmp_path):
    reg = registry(tmp_path)
    saved = json.loads((await reg.run("write_note", {"title": "Groceries", "text": "milk"})).text)
    assert saved == {"saved": "groceries.md", "added_to_existing": False}
    await reg.run("write_note", {"title": "groceries", "text": "eggs"})

    listed = json.loads((await reg.run("list_notes", {})).text)
    assert [n["title"] for n in listed] == ["Groceries"]
    assert "milk" in listed[0]["preview"] and "eggs" in listed[0]["preview"]

    body = (await reg.run("read_note", {"title": "Groceries"})).text
    assert "milk" in body and "eggs" in body


async def test_list_filters_and_missing_note(tmp_path):
    reg = registry(tmp_path)
    assert json.loads((await reg.run("list_notes", {})).text) == []
    await reg.run("write_note", {"title": "Ideas", "text": "holographic toaster"})
    await reg.run("write_note", {"title": "Todo", "text": "call mum"})
    found = json.loads((await reg.run("list_notes", {"query": "toaster"})).text)
    assert [n["title"] for n in found] == ["Ideas"]
    missing = await reg.run("read_note", {"title": "nope"})
    assert missing.is_error and "list_notes" in missing.text


async def test_titles_cannot_escape_the_notes_folder(tmp_path):
    assert slugify("../../etc/passwd") == "etc-passwd"
    assert slugify("!!!") == "untitled"
    await registry(tmp_path).run("write_note", {"title": "../../evil", "text": "x"})
    assert (tmp_path / "notes" / "evil.md").exists()
    assert not (tmp_path / "evil.md").exists()


async def test_writing_needs_approval(tmp_path):
    async def no(summary: str) -> bool:
        return False

    reg = ToolRegistry(make_notes_tools(tmp_path / "notes"), confirmer=no)
    assert (await reg.run("write_note", {"title": "x", "text": "y"})).is_error
    assert not (tmp_path / "notes").exists()
