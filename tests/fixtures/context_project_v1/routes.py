from service import summarize_project

API_PREFIX = "/api"


def register_routes():
    return {"GET /api/project": summarize_project}
