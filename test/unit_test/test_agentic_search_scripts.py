from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_powershell_script_targets_agentic_search_api_and_logs_calls():
    content = (ROOT / "scripts" / "test_agentic_search.ps1").read_text(encoding="utf-8")
    assert "/api/v1/agentic-search" in content
    assert "/api/v1/chat/completions" not in content
    assert "-ApiKey" in content or "$ApiKey" in content
    assert "$Query" in content
    assert "Write-Event" in content
    assert "REDACTED_API_KEY" in content


def test_bash_script_targets_agentic_search_api_and_logs_calls():
    content = (ROOT / "scripts" / "test_agentic_search.sh").read_text(encoding="utf-8")
    assert "/api/v1/agentic-search" in content
    assert "/api/v1/chat/completions" not in content
    for argument in ("--api-key", "--query", "--base-url", "--chat-id", "--dataset-id", "--model", "--reasoning", "--log"):
        assert argument in content
    assert "log_event" in content
    assert "REDACTED_API_KEY" in content


def test_scripts_do_not_mutate_chat_configuration():
    powershell = (ROOT / "scripts" / "test_agentic_search.ps1").read_text(encoding="utf-8")
    bash = (ROOT / "scripts" / "test_agentic_search.sh").read_text(encoding="utf-8")
    assert "/api/v1/chats/" not in powershell
    assert "/api/v1/chats/" not in bash
    assert "configure_chat" not in powershell
    assert "configure_chat" not in bash
