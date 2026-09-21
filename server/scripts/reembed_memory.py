"""Re-embed toàn bộ memory đã lưu bằng model embedding hiện hành.

Phải chạy sau khi đổi GEMINI_EMBED_MODEL: vector sinh bởi text-embedding-004 nằm ở
không gian vector khác, so cosine với vector của gemini-embedding-001 là vô nghĩa.
Không re-embed thì retrieve memory trả về thứ tự rác (mà vẫn trông như hợp lệ).

Chạy trong container orchestrator:

    docker exec -it travel-orchestrator python /app/scripts/reembed_memory.py --dry-run
    docker exec -it travel-orchestrator python /app/scripts/reembed_memory.py

Hoặc từ máy host với DB local:

    python server/scripts/reembed_memory.py --dry-run

Tùy chọn:

    --dry-run        chỉ đếm số dòng, không gọi API và không ghi DB
    --table NAME     chỉ xử lý một bảng: user_facts | episodes | agent_facts
    --batch-size N   số text mỗi request (mặc định 100 = mức tối đa API cho phép)
    --sleep S        nghỉ S giây giữa các batch
    --report PATH    ghi báo cáo lỗi dạng JSON (mặc định output/reembed_failures.json)

Quota: Gemini free tier cho 100 request/phút cho mỗi model embedding. Script chỉ tốn
khoảng ceil(số_dòng / batch_size) request, nên 1000 dòng cũng chỉ ~10 request. Khi gặp 429,
script chờ đúng thời gian API yêu cầu (`retryDelay`, thường ~45s) rồi làm tiếp, thay vì bỏ dở.

Script idempotent: chạy lại chỉ tính lại embedding, không nhân đôi dữ liệu.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import GEMINI_EMBED_DIM, GEMINI_EMBED_MODEL, OUTPUT_DIR  # noqa: E402
from app.db.models import AgentFact, Episode, UserFact  # noqa: E402
from app.db.session import db_session  # noqa: E402
from app.memory.embed import embed_texts_with_errors  # noqa: E402
from packages.agent_runtime.embed import PATIENT  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402

# bảng -> (model ORM, tên cột chứa text đem đi embed)
TABLES = {
    "user_facts": (UserFact, "text"),
    "episodes": (Episode, "summary"),
    "agent_facts": (AgentFact, "text"),
}

PREVIEW = 90


class Stats:
    def __init__(self, name: str):
        self.name = name
        self.total = 0
        self.embedded = 0
        self.failed = 0
        self.empty = 0
        self.reasons: Counter = Counter()
        self.samples: dict = {}

    def add_failure(self, reason: str, text: str) -> None:
        self.failed += 1
        self.reasons[reason] += 1
        # giữ 1 ví dụ text + độ dài để biết lỗi do dữ liệu hay do API
        self.samples.setdefault(reason, {"preview": text[:PREVIEW], "chars": len(text)})

    def line(self) -> str:
        return (
            f"{self.name:<12} rows={self.total:<6} re-embedded={self.embedded:<6} "
            f"empty={self.empty:<6} failed={self.failed}"
        )

    def report(self) -> dict:
        return {
            "rows": self.total,
            "re_embedded": self.embedded,
            "failed": self.failed,
            "reasons": [
                {
                    "reason": reason[:300],
                    "count": count,
                    "sample_chars": self.samples[reason]["chars"],
                    "sample": self.samples[reason]["preview"],
                }
                for reason, count in self.reasons.most_common()
            ],
        }


def reembed_table(name: str, model_cls, column: str, args) -> Stats:
    stats = Stats(name)
    session = db_session()
    try:
        try:
            rows = session.query(model_cls).all()
        except SQLAlchemyError as exc:
            raise SystemExit(
                f"-> Không truy vấn được bảng {name}: {exc}\n"
                "   Kiểm tra DATABASE_URL. Chạy cùng Docker Compose thì chạy trong container:\n"
                "   docker exec -it travel-orchestrator python /app/scripts/reembed_memory.py"
            ) from exc
        stats.total = len(rows)
        stale = sum(1 for row in rows if getattr(row, "embed_model", None) != GEMINI_EMBED_MODEL)
        if stale:
            print(
                f"  {name}: {stale}/{len(rows)} dong sinh boi model khac "
                f"(hoac chua ro) — cosine voi {GEMINI_EMBED_MODEL} la vo nghia"
            )
        pending = [row for row in rows if (getattr(row, column) or "").strip()]
        stats.empty = stats.total - len(pending)
        if args.dry_run or not pending:
            return stats

        for start in range(0, len(pending), args.batch_size):
            if start and args.sleep:
                time.sleep(args.sleep)
            batch = pending[start : start + args.batch_size]
            texts = [getattr(row, column).strip() for row in batch]
            vectors, errors = embed_texts_with_errors(texts, policy=PATIENT)
            for row, vector, error in zip(batch, vectors, errors):
                if vector is None:
                    stats.add_failure(error or "không rõ lý do", getattr(row, column).strip())
                    continue
                setattr(row, "embedding", vector)
                # Ghi lai model da sinh vector, de lan sau biet dong nao con cu.
                setattr(row, "embed_model", GEMINI_EMBED_MODEL)
                stats.embedded += 1
            session.commit()
            print(f"  {name}: {min(start + args.batch_size, len(pending))}/{len(pending)}", flush=True)
        return stats
    finally:
        session.close()


def print_failures(results: list) -> None:
    if not any(stats.failed for stats in results):
        return
    print("\nLý do lỗi:")
    for stats in results:
        for reason, count in stats.reasons.most_common():
            sample = stats.samples[reason]
            print(f"  [{stats.name}] {count:>4} dòng · {sample['chars']} ký tự · {reason[:200]}")
            print(f"          ví dụ: {sample['preview']!r}")


def write_report(results: list, path: Path) -> None:
    payload = {
        "model": GEMINI_EMBED_MODEL,
        "dim": GEMINI_EMBED_DIM,
        "tables": {stats.name: stats.report() for stats in results},
        "failed_total": sum(stats.failed for stats in results),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nBáo cáo: {path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Re-embed stored memory with the current model.")
    parser.add_argument("--dry-run", action="store_true", help="Count rows only; no API calls, no writes.")
    parser.add_argument("--table", choices=sorted(TABLES), help="Only process one table.")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Texts per embedding request (100 = API maximum, ít request nhất).",
    )
    parser.add_argument("--sleep", type=float, default=0.0, help="Seconds to wait between batches.")
    parser.add_argument(
        "--report",
        default=str(Path(OUTPUT_DIR) / "reembed_failures.json"),
        help="Where to write the JSON failure report.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.batch_size < 1:
        print("--batch-size phải >= 1")
        return 2

    print(f"Model      : {GEMINI_EMBED_MODEL} (output_dimensionality={GEMINI_EMBED_DIM})")
    print(f"Chế độ     : {'DRY RUN (không ghi DB)' if args.dry_run else 'GHI DB'}")
    if args.sleep:
        print(f"Nghỉ giữa batch: {args.sleep}s")
    print()

    names = [args.table] if args.table else sorted(TABLES)
    results = []
    for name in names:
        model_cls, column = TABLES[name]
        print(f"-> {name}")
        results.append(reembed_table(name, model_cls, column, args))

    print()
    for stats in results:
        print(stats.line())

    failed = sum(stats.failed for stats in results)
    print_failures(results)
    if not args.dry_run:
        write_report(results, Path(args.report))

    if failed:
        print(
            f"\n{failed} dòng lỗi. Xem lý do ở trên hoặc trong báo cáo JSON; "
            f"chạy lại script để thử tiếp (idempotent)."
        )
        return 1
    if args.dry_run:
        print("\nDry run xong. Bỏ --dry-run để ghi embedding mới.")
    else:
        print("\nXong. Kiểm tra lại bằng một câu hỏi cần memory ngữ nghĩa.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
