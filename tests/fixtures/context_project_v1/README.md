# Context V1 fixture

The project entry point is `app.py`. It creates the application by calling
`routes.register_routes`. The `/api/project` route is implemented in
`routes.py` and calls `service.summarize_project`, which reads the project name
from `config.py`.
