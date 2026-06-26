import argparse
from pathlib import Path

import db
from config import SAMPLES_DIR
from pipeline.process import process_paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Обработка прайс-листов MedRate")
    parser.add_argument("paths", nargs="*", help="файлы, папки или zip-архивы (по умолчанию data/samples/)")
    parser.add_argument("--reset", action="store_true", help="очистить таблицы перед обработкой")
    parser.add_argument("--max-chunks", type=int, default=None, help="ограничить число фрагментов на файл")
    args = parser.parse_args()

    paths = [Path(p) for p in args.paths] or [SAMPLES_DIR]
    conn = db.connect()
    db.init_db(conn)
    if args.reset:
        db.clear_pipeline_tables(conn)

    def report(name: str, index: int, total: int) -> None:
        print(f"[{index}/{total}] {name}")

    stats = process_paths(paths, conn, report, max_chunks=args.max_chunks)
    print(stats)


if __name__ == "__main__":
    main()
