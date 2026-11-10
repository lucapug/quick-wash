from src.hello import greeting, main


def test_module_returns_ponte():
    assert greeting() == "PONTE"


def test_main_prints_ponte(capsys):
    main()
    assert capsys.readouterr().out.strip() == "PONTE"
