DEFAULT_TROOP_PROFILE_NAME = "default-pracEqual-formalEqAndIneq"

DEFAULT_TROOP_PROFILE_ROWS = (
    {"soldiersA": 7, "soldiersB": 7},
    {"soldiersA": 8, "soldiersB": 8},
    {"soldiersA": 7, "soldiersB": 7},
    {"soldiersA": 8, "soldiersB": 9},
    {"soldiersA": 7, "soldiersB": 8},
    {"soldiersA": 9, "soldiersB": 8},
    {"soldiersA": 8, "soldiersB": 7},
)


def default_troop_profile_payload() -> dict:
    rows = [dict(row) for row in DEFAULT_TROOP_PROFILE_ROWS]
    return {
        "name": DEFAULT_TROOP_PROFILE_NAME,
        "built_in": True,
        "practice_trials": 1,
        "formal_trials": len(rows) - 1,
        "rows": rows,
    }
