import importlib


def test_queue_runtime_reuses_configured_security_and_network_manager():
    runtime = importlib.import_module("app.queue_runtime")
    from app.main import network_manager as main_network_manager, security as main_security

    assert runtime.network_policy.security is main_security
    assert runtime.network_policy.network_manager is main_network_manager


def test_queue_runtime_defines_worker_lifespan():
    runtime = importlib.import_module("app.queue_runtime")

    assert callable(runtime._lifespan)
    assert runtime.app.router.lifespan_context is not None
