from unittest.mock import MagicMock

from prospere.cli.chat import _handle_chat_command
from prospere.cli.optim_chat import _handle_optim_chat_command


def test_handle_chat_command_logic() -> None:
    console = MagicMock()
    console.width = 80
    engine = MagicMock()
    # Mock engine attributes for _print_banner
    engine.baseline_result.percentile_50 = [100, 200]
    engine.scenario_meta = {"years": 10}
    user = "test_user"
    scenario = "test_scenario"

    # Test exit command
    cont, msgs = _handle_chat_command("exit", console, engine, user, scenario)
    if cont is not False:
        raise AssertionError
    if msgs is not None:
        raise AssertionError

    # Test help command (should be a command, returns empty list)
    cont, msgs = _handle_chat_command("/help", console, engine, user, scenario)
    if cont is not True:
        raise AssertionError
    if msgs != []:
        raise AssertionError

    # Test clear command (should be a command, returns new system message)
    engine._build_system_message.return_value = {"role": "system", "content": "hi"}
    cont, msgs = _handle_chat_command("clear", console, engine, user, scenario)
    if cont is not True:
        raise AssertionError
    if msgs != [{"role": "system", "content": "hi"}]:
        raise AssertionError

    # Test non-command (should return None to trigger AI)
    cont, msgs = _handle_chat_command("hello", console, engine, user, scenario)
    if cont is not True:
        raise AssertionError
    if msgs is not None:
        raise AssertionError


def test_handle_optim_chat_command_logic() -> None:
    console = MagicMock()
    console.width = 80
    engine = MagicMock()
    # Mock engine attributes for _print_banner
    engine.baseline_result.percentile_50 = [100, 200]
    engine.scenario_meta = {"years": 10}
    engine.scenario_id = "test_scenario"
    user = "test_user"

    # Test exit command
    cont, msgs = _handle_optim_chat_command("exit", console, engine, user)
    if cont is not False:
        raise AssertionError
    if msgs is not None:
        raise AssertionError

    # Test help command
    cont, msgs = _handle_optim_chat_command("/help", console, engine, user)
    if cont is not True:
        raise AssertionError
    if msgs != []:
        raise AssertionError

    # Test non-command
    cont, msgs = _handle_optim_chat_command("optimize my life", console, engine, user)
    if cont is not True:
        raise AssertionError
    if msgs is not None:
        raise AssertionError
