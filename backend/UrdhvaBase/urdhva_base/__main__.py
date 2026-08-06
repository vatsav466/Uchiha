from inspect import indentsize
from logging import debug
import os
import sys
import urdhva_base
import uvicorn
import argparse

sys.path.append(os.getcwd())
parser = argparse.ArgumentParser(description='Parse Model & generate code for a target language.')
parser.add_argument('-c','--config', action='store_true', help='Sample config file.')
args = parser.parse_args()

if __name__ == "__main__":
    log_level: str = None
    reload: bool = False
    port: int = int(os.environ.get("PORT", 9000))
    # Bind on all interfaces by default so the API is reachable on the
    # container/host IP (e.g. http://<server>:8002/docs). Override with HOST.
    host: str = os.environ.get("HOST", "0.0.0.0")
    # print(os.getcwd(), sys.path)
    if args.config:
        print(urdhva_base.settings.json(indent=2))
        sys.exit(0)

    if os.environ.get("MODE", "prod") == "dev":
        log_level = "debug"
        reload = True

    uvicorn.run("urdhva_base.restapi:app", host=host, port=port, log_level=log_level, reload=reload, reload_dirs=[os.getcwd()])
