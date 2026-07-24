from flask import Flask

from data_formulator.insight.routes.health import insight_health_bp


def test_health_route_reports_business_insight_mode():
    app = Flask(__name__)
    app.config["CLI_ARGS"] = {
        "product_mode": "business_insight",
        "workspace_backend": "local",
    }
    app.register_blueprint(insight_health_bp)

    response = app.test_client().get("/api/insight/health")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "success"
    assert payload["data"]["productMode"] == "business_insight"
    assert payload["data"]["domainSchemaVersion"] == "1.0"
