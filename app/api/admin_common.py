from ..services.events import add_audit


def audit(db, admin, action: str, target_type: str, target_id: str, payload: dict | None = None) -> None:
    add_audit(db, admin.id, action, target_type, target_id, payload)


def audit_import_report(report: dict) -> dict:
    safe = {key: value for key, value in report.items() if key not in ("rows", "errors")}
    for key in ("rows", "errors"):
        if key in report:
            safe[key] = [
                {field: value for field, value in row.items() if field != "name"}
                for row in report[key]
            ]
    return safe
