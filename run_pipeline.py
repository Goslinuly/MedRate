import argparse
from pathlib import Path

import db
from config import SAMPLES_DIR


def main() -> None:
    parser = argparse.ArgumentParser(description="Обработка прайс-листов MedRate")
    parser.add_argument("paths", nargs="*", help="файлы, папки или zip-архивы (по умолчанию data/samples/)")
    parser.add_argument("--reset", action="store_true", help="очистить таблицы перед обработкой")
    parser.add_argument("--max-chunks", type=int, default=None, help="ограничить число фрагментов на файл")
    parser.add_argument("--doq", action="store_true", help="импортировать врачей и цены из DOQ API")
    parser.add_argument("--doq-city", type=int, default=3, help="ID города DOQ, по умолчанию 3 = Алматы")
    parser.add_argument("--doq-service", type=int, default=73, help="ID услуги DOQ, по умолчанию 73 = акушер-гинеколог")
    parser.add_argument("--doq-limit", type=int, default=100, help="размер страницы DOQ API")
    parser.add_argument("--doq-max-pages", type=int, default=None, help="ограничить число страниц DOQ API")
    args = parser.parse_args()

    paths = [Path(p) for p in args.paths] or [SAMPLES_DIR]
    conn = db.connect()
    db.init_db(conn)
    if args.reset:
        db.clear_pipeline_tables(conn)

    if args.doq:
        from pipeline.doq import import_doq_doctors

        stats = import_doq_doctors(
            conn,
            city=args.doq_city,
            service=args.doq_service,
            limit=args.doq_limit,
            max_pages=args.doq_max_pages,
        )
        print(stats)
        return

    from pipeline.process import process_paths

    def report(name: str, index: int, total: int) -> None:
        print(f"[{index}/{total}] {name}")
    stats = process_paths(paths, conn, report, max_chunks=args.max_chunks)
    print(stats)


if __name__ == "__main__":
    main()
