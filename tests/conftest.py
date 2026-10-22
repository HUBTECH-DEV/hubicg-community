import pytest


@pytest.fixture(autouse=True)
def isolated_machine_home(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every test away from the real per-machine role library.

    The CLI reads the machine library during selection and search, so a test
    run on a machine that has it installed would otherwise see 65 extra roles.
    """
    monkeypatch.setenv("HUBICG_HOME", str(tmp_path_factory.mktemp("hubicg-home")))
