from app.kill_switch import KillSwitch


def test_kill_switch_is_durable(tmp_path):
    database = tmp_path / "kill-switch.db"

    first = KillSwitch(str(database))
    assert not first.is_active()

    engaged = first.engage("operator emergency")
    assert engaged["active"] is True
    assert engaged["reason"] == "operator emergency"

    second = KillSwitch(str(database))
    assert second.is_active()
    assert second.status()["reason"] == "operator emergency"

    released = second.release()
    assert released["active"] is False
    assert not first.is_active()
