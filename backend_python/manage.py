from __future__ import annotations

import argparse

from app import create_app, get_socketio


def main():
    parser = argparse.ArgumentParser(description="Pejuang Aspal Backend MVP")
    parser.add_argument("command", choices=["run", "init-db"], help="Command to run")
    args = parser.parse_args()

    app = create_app()

    if args.command == "init-db":
        # tables are created in init_db() during create_app()
        print("DB initialized (tables created if missing).")
        return

    # run server
    socketio = get_socketio(app)
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)


if __name__ == "__main__":
    main()

