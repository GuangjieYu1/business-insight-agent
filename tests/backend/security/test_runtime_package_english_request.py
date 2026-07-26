from __future__ import annotations

from data_formulator.sandbox.runtime_packages import detect_explicit_runtime_package_requests


def test_english_install_request_stops_before_purpose_words(monkeypatch):
    monkeypatch.setattr('importlib.util.find_spec', lambda name: None)

    requested = detect_explicit_runtime_package_requests(
        'download xgboost for sales analysis'
    )

    assert [item.package_name for item in requested] == ['xgboost']
