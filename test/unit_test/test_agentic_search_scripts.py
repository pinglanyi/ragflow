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


def test_scripts_default_to_stateless_calls_and_keep_chat_id_optional():
    powershell = (ROOT / "scripts" / "test_agentic_search.ps1").read_text(encoding="utf-8")
    bash = (ROOT / "scripts" / "test_agentic_search.sh").read_text(encoding="utf-8")
    test_chat_id = "1c9dc6468a2511f1b194b520b0860b27"

    assert test_chat_id not in powershell
    assert test_chat_id not in bash
    assert '[string]$ChatId = ""' in powershell
    assert "if ($ChatId) { $body.chat_id = $ChatId }" in powershell
    assert '[string]$Model = ""' in powershell
    assert "if ($Model) { $body.model = $Model }" in powershell
    assert 'CHAT_ID=""' in bash
    assert 'MODEL=""' in bash
    assert 'if $chat == "" then {} else {chat_id:$chat} end' in bash
    assert 'if $model == "" then {} else {model:$model} end' in bash


def test_bash_script_accepts_one_comma_separated_dataset_ids():
    bash = (ROOT / "scripts" / "test_agentic_search.sh").read_text(encoding="utf-8")
    assert 'DATASET_IDS=""' in bash
    assert 'DATASET_IDS="$2"' in bash
    assert "--arg datasets" in bash
    assert "dataset_ids:$datasets" in bash
    assert "DATASET_IDS+=(" not in bash


def test_scripts_allow_automatic_routing_without_dataset_ids():
    powershell = (ROOT / "scripts" / "test_agentic_search.ps1").read_text(encoding="utf-8")
    bash = (ROOT / "scripts" / "test_agentic_search.sh").read_text(encoding="utf-8")
    assert '[string]$DatasetIds = ""' in powershell
    assert "if ($DatasetIds) { $body.dataset_ids = $DatasetIds }" in powershell
    assert "At least one DatasetIds" not in powershell
    assert "At least one --dataset-id" not in bash
    assert 'if $datasets == "" then {} else {dataset_ids:$datasets} end' in bash
