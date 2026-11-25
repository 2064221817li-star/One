"""支持 `python -m smart_proxy_manager` 方式运行 CLI。"""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
