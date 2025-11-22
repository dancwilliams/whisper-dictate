from whisper_dictate import app_context


def test_format_context_for_prompt_includes_fields():
    ctx = app_context.ActiveContext(
        window_title="Document - Word",
        process_name="winword.exe",
        cursor_position=(120, 340),
    )

    fragment = app_context.format_context_for_prompt(ctx)

    assert fragment
    assert "winword.exe" in fragment
    assert "Document - Word" in fragment
    assert "120" in fragment and "340" in fragment


def test_get_active_context_no_windows(monkeypatch):
    monkeypatch.setattr(app_context.platform, "system", lambda: "Linux")
    monkeypatch.setattr(app_context, "USER32", None)
    monkeypatch.setattr(app_context, "KERNEL32", None)

    assert app_context.get_active_context() is None
