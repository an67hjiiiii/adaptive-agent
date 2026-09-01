from routes import register_routes


def create_app():
    return register_routes()


if __name__ == "__main__":
    create_app()
